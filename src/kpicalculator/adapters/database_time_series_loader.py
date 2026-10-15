# src/kpicalculator/adapters/database_time_series_loader.py
"""Database time series loader for InfluxDB and PostgreSQL profiles in ESDL files."""

import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, cast

import pandas as pd
from esdl import esdl
from esdl.profiles.influxdbprofilemanager import ConnectionSettings, InfluxDBProfileManager
from esdl.profiles.profile_utils import close_db_connections, load_profile_data_and_header
from esdl.units.conversion import ENERGY_IN_J, POWER_IN_W, convert_to_unit

from ..common.constants import (
    COMPOSITE_KEY_SEPARATOR,
    DEFAULT_DATABASE_SSL_PORT,
    DEFAULT_TIME_STEP_SECONDS,
    HTTP_PREFIX_LENGTH,
    HTTPS_PREFIX_LENGTH,
    SECONDS_PER_HOUR,
)
from ..common.logging_utils import get_database_logger
from ..common.types import DatabaseCredentials
from ..exceptions import CredentialError, SecurityError, ValidationError
from ..security.credential_manager import (
    CredentialManager,
    create_default_credential_manager,
)
from ..security.input_validator import InputValidator
from .base_adapter import ValidationResult
from .common_model import TimeSeries
from .data_table_profile_reader import (
    is_database_profile,
    registered_credential,
    reshape_rows,
    validate_data_table_profile,
)


class TimeSeriesDataProtocol(Protocol):
    """Protocol for time series data from InfluxDBProfileManager."""

    start_datetime: datetime
    end_datetime: datetime
    profile_data_list: Sequence[Sequence[datetime | float | None]]


class InfluxDBProfileProtocol(Protocol):
    """Protocol for InfluxDB profile objects with database connection details."""

    host: str
    port: int
    database: str
    measurement: str
    field: str


class _BatchHardError(Exception):
    """Raised by _execute_batch_query for unrecoverable misconfigurations (no fallback)."""

    def __init__(self, failed_count: int) -> None:
        self.failed_count = failed_count


class DatabaseTimeSeriesLoader:
    """Load time series data from database references in ESDL files.

    Supports ``InfluxDBProfile`` elements (read with batched InfluxDB queries, following
    the MESIDO pattern) and ``DataTableProfile`` elements backed by a
    ``DatabaseConfiguration`` (read per profile through pyESDL's
    ``load_profile_data_and_header``; PostgreSQL or InfluxDB). ``DataTableProfile`` elements
    with ``profileType`` OUTPUT or a non-database configuration are skipped.
    Uses secure credential management with no hard-coded credentials.

    Exception Handling Strategy:
    ===========================
    This class implements a systematic exception categorization and graceful
    degradation strategy to ensure robust time series loading:

    1. Exception Categories:
       - Configuration: Credential, security, validation errors
       - Connection: Network timeouts, database connectivity issues
       - Data Processing: Value errors, missing keys/attributes
       - Unexpected: All other unforeseen errors

    2. Graceful Degradation:
       - Individual profile failures do not crash entire loading process
       - Profiles that fail to load are skipped and reported in ValidationResult.errors
       - Influx profiles with no field name are skipped with a warning only
       - Partial data loading succeeds when some profiles are accessible
       - All errors are logged with detailed context for troubleshooting

    3. Helper Methods:
       - _categorize_profile_error(): Categorizes exceptions and formats messages
       - _handle_query_error(): Provides consistent query error logging
       - _process_data_table_profile(): Loads one DataTableProfile with the same degradation

    This design ensures system stability while providing clear error reporting
    for debugging and monitoring database connectivity issues.
    """

    def __init__(self, credential_manager: CredentialManager | None = None):
        """Initialize database loader with secure credential management.

        Args:
            credential_manager: Secure credential manager. Uses default if None.
        """
        self.credential_manager = credential_manager or create_default_credential_manager()
        self.db_logger = get_database_logger("time_series_loader")

    def _get_secure_credentials(self, host: str, port: int) -> DatabaseCredentials:
        """Get credentials securely with no hard-coded fallbacks.

        Args:
            host: Database host
            port: Database port

        Returns:
            DatabaseCredentials from secure sources

        Raises:
            CredentialError: If no credentials found for the host:port combination
        """
        try:
            self.db_logger.log_connection_attempt(host, port)
            credentials = self.credential_manager.get_database_credentials(host, port)

            if not credentials:
                env_prefix = f"KPI_DB_{host.replace('.', '_').replace('-', '_').upper()}_{port}"
                error = CredentialError(
                    f"No credentials found for {host}: {port}. "
                    f"Set environment variables or configure credentials file. "
                    f"(Context: host={host}, port={port}, env_prefix={env_prefix})"
                )
                self.db_logger.log_credential_error(host, port, error)
                raise error

            # Determine credential source for logging
            source = (
                "environment"
                if self.credential_manager.supports_environment_credentials()
                else "config_file"
            )
            self.db_logger.log_credential_load(host, port, source)
            return credentials

        except Exception as e:
            if not isinstance(e, CredentialError):
                self.db_logger.log_credential_error(host, port, e)
            raise

    def load_time_series_from_esdl(
        self, energy_system: esdl.EnergySystem
    ) -> tuple[dict[str, TimeSeries], ValidationResult]:
        """Load all database time series profiles from an ESDL energy system.

        ``InfluxDBProfile`` elements go through batched InfluxDB queries; eligible
        ``DataTableProfile`` elements are read one by one through pyESDL. Both kinds are
        merged into one dict; on a composite-key collision the first entry is kept and the
        duplicate is recorded as an error. ``close_db_connections()`` runs once in a
        ``finally`` after the profiles have been read.

        Args:
            energy_system: ESDL EnergySystem containing InfluxDBProfile and/or
                DataTableProfile elements

        Returns:
            Tuple of (time_series_dict, validation_result)
            - time_series_dict: Maps composite keys (asset_id|field) to TimeSeries objects
            - validation_result: Validation status and any warnings/errors
        """
        start_time = time.time()
        self.db_logger.info("Starting database profile loading from ESDL")

        time_series_data: dict[str, TimeSeries] = {}
        errors: list[str] = []
        warnings: list[str] = []

        try:
            influx_profiles, table_profiles = self._collect_database_profiles(energy_system)

            profile_count = len(influx_profiles) + len(table_profiles)
            self.db_logger.info(
                "Found database profiles in ESDL",
                {
                    "profile_count": profile_count,
                    "influx_profiles": len(influx_profiles),
                    "data_table_profiles": len(table_profiles),
                },
            )

            if not profile_count:
                warnings.append("No database profiles found in ESDL file")
                return time_series_data, ValidationResult(True, [], warnings)

            try:
                successful_loads, failed_loads = self._load_database_profiles(
                    influx_profiles, table_profiles, time_series_data, errors
                )
            finally:
                close_db_connections()

            # Log summary
            total_time = time.time() - start_time
            self.db_logger.info(
                "Database profile loading completed",
                {
                    "total_profiles": profile_count,
                    "successful_loads": successful_loads,
                    "failed_loads": failed_loads,
                    "total_time_ms": round(total_time * 1000, 2),
                },
            )

        except Exception as e:
            errors.append(f"Failed to process database profiles: {e!s}")
            self.db_logger.error("Critical error during profile loading", exception=e)

        validation_result = ValidationResult(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings
        )

        return time_series_data, validation_result

    def _collect_database_profiles(
        self, energy_system: esdl.EnergySystem
    ) -> tuple[list[esdl.InfluxDBProfile], list[esdl.DataTableProfile]]:
        """Collect Influx and eligible DataTable profiles; warn once about skipped ones."""
        influx_profiles: list[esdl.InfluxDBProfile] = []
        table_profiles: list[esdl.DataTableProfile] = []
        skipped = 0
        for element in energy_system.eAllContents():
            if isinstance(element, esdl.InfluxDBProfile):
                influx_profiles.append(element)
            elif isinstance(element, esdl.DataTableProfile):
                if is_database_profile(element):
                    table_profiles.append(element)
                else:
                    skipped += 1
        if skipped:
            self.db_logger.warning(
                f"Skipped {skipped} DataTableProfile(s) that are OUTPUT profiles or use a "
                f"non-database configuration"
            )
        return influx_profiles, table_profiles

    def _load_database_profiles(
        self,
        influx_profiles: list[esdl.InfluxDBProfile],
        table_profiles: list[esdl.DataTableProfile],
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> tuple[int, int]:
        """Load Influx profiles (batched), then DataTable profiles (one by one).

        Returns:
            (successful_loads, failed_loads)
        """
        successful_loads = 0
        failed_loads = 0

        batches = self._group_profiles_for_batch(influx_profiles)
        self.db_logger.info(
            "Grouped profiles into batches",
            {"profile_count": len(influx_profiles), "batch_count": len(batches)},
        )

        for batch_profiles in batches.values():
            batch_successful, batch_failed = self._process_profile_batch(
                batch_profiles, time_series_data, errors
            )
            successful_loads += batch_successful
            failed_loads += batch_failed

        for table_profile in table_profiles:
            if self._process_data_table_profile(table_profile, time_series_data, errors):
                successful_loads += 1
            else:
                failed_loads += 1

        return successful_loads, failed_loads

    def _group_profiles_for_batch(
        self, profiles: list[esdl.InfluxDBProfile]
    ) -> dict[tuple, list[esdl.InfluxDBProfile]]:
        """Group profiles that can share a single InfluxDB query.

        Profiles are batchable when they share the same host, port, database,
        measurement, date range, and filters — meaning one SELECT with multiple
        fields can replace N individual queries.
        """
        groups: dict[tuple, list[esdl.InfluxDBProfile]] = defaultdict(list)
        seen_fields: dict[tuple, set[str]] = defaultdict(set)
        for profile in profiles:
            filters_val = getattr(profile, "filters", None) or ""
            key = (
                profile.host,
                profile.port,
                profile.database,
                profile.measurement,
                profile.startDate,
                profile.endDate,
                filters_val,
            )
            field = profile.field
            if field in seen_fields[key]:
                # Duplicate field in this batch group — isolate into its own group so
                # profile_header.index(field) cannot pick the wrong occurrence.
                self.db_logger.warning(
                    f"Two profiles share measurement '{profile.measurement}' and field "
                    f"'{field}' — possible ESDL misconfiguration; processing separately"
                )
                unique_key = (*key, id(profile))
                groups[unique_key].append(profile)
            else:
                seen_fields[key].add(field)
                groups[key].append(profile)
        return dict(groups)

    def _process_profile_batch(
        self,
        profiles: list[esdl.InfluxDBProfile],
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> tuple[int, int]:
        """Process a batch of profiles sharing the same measurement/connection.

        Issues one InfluxDB query for all fields in the batch, then splits the
        result per profile and applies per-profile unit conversion and multiplier.
        Falls back to per-profile processing if the batch query fails.

        Returns:
            (successful_loads, failed_loads)
        """
        if len(profiles) == 1:
            success = self._process_single_profile(profiles[0], time_series_data, errors)
            return (1, 0) if success else (0, 1)

        # Profiles with empty/None field cannot be batched; route them per-profile up front.
        valid_profiles = [p for p in profiles if p.field]
        invalid_field_profiles = [p for p in profiles if not p.field]
        # Pick representative from valid profiles so credential validation always succeeds.
        representative = valid_profiles[0] if valid_profiles else profiles[0]
        measurement = representative.measurement
        warn_msg = f"Profile in '{measurement}' has empty field — processing per-profile"
        successful, failed = self._fallback_to_per_profile(
            invalid_field_profiles, time_series_data, errors, warn_msg=warn_msg
        )

        if not valid_profiles:
            return successful, failed

        if len(valid_profiles) == 1:
            success = self._process_single_profile(valid_profiles[0], time_series_data, errors)
            return successful + (1 if success else 0), failed + (0 if success else 1)

        try:
            manager, field_index_map = self._execute_batch_query(
                valid_profiles, representative, measurement, errors, failed
            )
        except _BatchHardError as e:
            return successful, e.failed_count
        except Exception as e:
            self.db_logger.warning(
                f"Batch query failed for measurement '{measurement}', "
                f"falling back to per-profile loading: {e}"
            )
            s, f = self._fallback_to_per_profile(valid_profiles, time_series_data, errors)
            return successful + s, failed + f

        s, f = self._extract_all_profiles_from_batch(
            valid_profiles, field_index_map, manager, measurement, time_series_data, errors
        )
        return successful + s, failed + f

    def _execute_batch_query(
        self,
        valid_profiles: list[esdl.InfluxDBProfile],
        representative: esdl.InfluxDBProfile,
        measurement: str,
        errors: list[str],
        failed_so_far: int,
    ) -> tuple[InfluxDBProfileManager, dict[str, int]]:
        """Authenticate, issue the batch SELECT, and return the manager + field index map.

        Raises _BatchHardError for unrecoverable misconfigurations (e.g. DB name mismatch).
        Raises any other Exception for transient failures the caller should fall back from.
        """
        # Fetch representative's credentials first, then validate the rest.
        # The loop calls are validation-only side-effects; return values are intentionally
        # discarded — each profile's host/port must be authorised before batch query.
        credentials = self._get_credentials_for_profile(representative)
        for profile in valid_profiles:
            if profile is not representative:
                self._get_credentials_for_profile(profile)

        if representative.database != credentials.database:
            error_msg = (
                f"Profile database '{representative.database}' does not match "
                f"credentials database '{credentials.database}' for "
                f"measurement '{measurement}' — skipping batch"
            )
            self.db_logger.error(error_msg)
            errors.extend(
                self._categorize_profile_error(ValueError(error_msg), p.field)
                for p in valid_profiles
            )
            raise _BatchHardError(failed_so_far + len(valid_profiles))

        manager = InfluxDBProfileManager(
            ConnectionSettings(
                host=credentials.host,
                port=credentials.port,
                database=credentials.database,
                username=credentials.username,
                password=credentials.password,
                ssl=credentials.ssl,
                verify_ssl=credentials.verify_ssl,
            )
        )

        fields = [p.field for p in valid_profiles]
        filters = InfluxDBProfileManager._parse_esdl_profile_filters(
            getattr(representative, "filters", None) or ""
        )
        t0 = time.time()
        manager.load_influxdb(
            measurement=measurement,
            fields=fields,
            from_datetime=representative.startDate,
            to_datetime=representative.endDate,
            filters=filters,
        )
        self.db_logger.info(
            "Batch query completed",
            {
                "measurement": measurement,
                "field_count": len(fields),
                "batch_time_ms": round((time.time() - t0) * 1000, 2),
            },
        )

        if not manager.profile_data_list:
            raise ValueError(f"No data returned for measurement '{measurement}'")
        if not manager.profile_header:
            raise ValueError(f"Batch result for measurement '{measurement}' has no header")

        return manager, {name: i for i, name in enumerate(manager.profile_header)}

    def _extract_all_profiles_from_batch(
        self,
        valid_profiles: list[esdl.InfluxDBProfile],
        field_index_map: dict[str, int],
        manager: InfluxDBProfileManager,
        measurement: str,
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> tuple[int, int]:
        """Extract each profile's field from a batch result, retrying per-profile on failure."""
        successful = 0
        failed = 0
        for profile in valid_profiles:
            errors_before = len(errors)
            if self._extract_profile_from_batch(
                profile, field_index_map, manager, measurement, time_series_data, errors
            ):
                successful += 1
            else:
                # Extraction can fail due to batch artifacts (NULL/NaN from non-overlapping
                # timestamps). Retry per-profile before counting as failed.
                # Truncate any errors appended by the failed extraction so the retry
                # can report its own error if it also fails.
                del errors[errors_before:]
                self.db_logger.warning(
                    f"Retrying field '{profile.field}' from measurement '{measurement}' "
                    f"per-profile after batch extraction failure"
                )
                if self._process_single_profile(profile, time_series_data, errors):
                    successful += 1
                else:
                    failed += 1
        return successful, failed

    def _fallback_to_per_profile(
        self,
        profiles: list[esdl.InfluxDBProfile],
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
        warn_msg: str | None = None,
    ) -> tuple[int, int]:
        """Process each profile individually, optionally logging a warning per profile."""
        successful = 0
        failed = 0
        for profile in profiles:
            if warn_msg:
                self.db_logger.warning(warn_msg)
            if self._process_single_profile(profile, time_series_data, errors):
                successful += 1
            else:
                failed += 1
        return successful, failed

    def _extract_profile_from_batch(
        self,
        profile: esdl.InfluxDBProfile,
        field_index_map: dict[str, int],
        manager: InfluxDBProfileManager,
        measurement: str,
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> bool:
        """Extract one profile's field from a batch query result and store it.

        Returns True on success, False on failure.
        """
        try:
            field = profile.field
            asset_id = self._extract_asset_id(profile)
            field_index = field_index_map.get(field)
            if field_index is None:
                raise ValueError(f"Field '{field}' not found in batch result header")

            self._validate_profile_data(profile, manager)

            if any(pd.isna(row[field_index]) for row in manager.profile_data_list):
                raise ValueError(
                    f"Batch result for field '{field}' contains NULL/NaN row(s) out of "
                    f"{len(manager.profile_data_list)} — fields in this measurement "
                    f"may have non-overlapping timestamps"
                )

            df = self._rows_to_dataframe(manager.profile_data_list, field_index)
            df = self._convert_units(df, profile)
            df = self._apply_multiplier(df, profile)

            values_list = df.values.flatten().tolist()
            validated_values = InputValidator.validate_time_series_data(
                values_list, f"InfluxDB profile {measurement}.{field}"
            )

            composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{field}"
            time_series_data[composite_key] = TimeSeries(
                time_step=DEFAULT_TIME_STEP_SECONDS, values=validated_values
            )
            self.db_logger.debug(f"Extracted {field} for asset {asset_id} from batch result")
            return True

        except Exception as e:
            errors.append(self._categorize_profile_error(e, profile.field))
            self.db_logger.error(
                "Failed to extract profile from batch result",
                {"field": profile.field, "measurement": measurement},
                e,
            )
            return False

    def _process_single_profile(
        self,
        profile: esdl.InfluxDBProfile,
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> bool:
        """Process a single InfluxDB profile and add it to time_series_data.

        Args:
            profile: ESDL InfluxDBProfile element to process.
            time_series_data: Dict to populate with the loaded TimeSeries on success.
            errors: List to append error messages to on failure.

        Returns:
            True if the profile was loaded successfully, False otherwise.
        """
        try:
            asset_id = self._extract_asset_id(profile)
            field_name = profile.field
            if not field_name:
                self.db_logger.warning(
                    f"InfluxDB profile for asset {asset_id} has no field name, skipping"
                )
                return False

            profile_start = time.time()
            time_series = self._load_profile_data(profile)
            profile_time = time.time() - profile_start

            composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{field_name}"
            time_series_data[composite_key] = time_series
            self.db_logger.log_time_series_processing(
                asset_id, len(time_series.values), time_series.time_step, profile_time
            )
            self.db_logger.debug(f"Loaded {field_name} time series for asset {asset_id}")
            return True

        except Exception as e:
            errors.append(self._categorize_profile_error(e, profile.field))
            self.db_logger.error(
                "Profile loading failed",
                {
                    "profile_field": profile.field,
                    "profile_measurement": profile.measurement,
                    "profile_host": profile.host,
                    "profile_port": profile.port,
                },
                e,
            )
            return False

    def _process_data_table_profile(
        self,
        profile: esdl.DataTableProfile,
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> bool:
        """Read one DataTableProfile and add it to time_series_data.

        An existing entry with the same composite key is kept; the duplicate is recorded as an
        error.

        Returns:
            True if the profile was loaded successfully, False otherwise.
        """
        try:
            asset_id = self._extract_asset_id(profile)
            profile_start = time.time()
            time_series = self._read_data_table_profile(profile, asset_id)
            profile_time = time.time() - profile_start

            composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{profile.columnName}"
            if composite_key in time_series_data:
                message = (
                    f"Duplicate time series key '{composite_key}' (table "
                    f"'{profile.tableName}'); keeping the first entry"
                )
                self.db_logger.warning(message)
                errors.append(message)
                return False
            time_series_data[composite_key] = time_series
            self.db_logger.log_time_series_processing(
                asset_id, len(time_series.values), time_series.time_step, profile_time
            )
            return True

        except Exception as e:
            errors.append(self._categorize_profile_error(e, profile.columnName or "?"))
            self.db_logger.error(
                "DataTable profile loading failed",
                {"table_name": profile.tableName, "column_name": profile.columnName},
                e,
            )
            return False

    def _read_data_table_profile(self, profile: esdl.DataTableProfile, asset_id: str) -> TimeSeries:
        """Validate, read through pyESDL and reshape one DataTableProfile.

        Credentials come from the CredentialManager chain and are registered into pyESDL
        as ``host:port`` for the duration of the read. The pyESDL cache is disabled (its
        key omits the profile filter), the multiplier is applied here after float coercion
        rather than by pyESDL, and the connection stays open for the caller to close.

        Raises:
            Exception: Any validation, credential, read or reshape failure.
        """
        target = validate_data_table_profile(profile, asset_id)
        username, password = self._get_data_table_credentials(target.host, target.port)
        with registered_credential(target.host, target.port, username, password):
            data, header = load_profile_data_and_header(
                profile,
                enable_cache=False,
                apply_multiplier=False,
                close_connection_after_load=False,
            )
        return self._data_table_rows_to_time_series(profile, data, header)

    def _get_data_table_credentials(self, host: str, port: int) -> tuple[str, str]:
        """Resolve and validate a username and password from the CredentialManager chain.

        Raises:
            CredentialError: No credentials found.
            ValidationError: Username or password empty or invalid.
        """
        credentials = self._get_secure_credentials(host, port)
        InputValidator.validate_database_credentials(credentials)
        return cast(str, credentials.username), cast(str, credentials.password)

    def _data_table_rows_to_time_series(
        self,
        profile: esdl.DataTableProfile,
        data: Sequence[Sequence[Any]] | None,
        header: Sequence[Any] | None,
    ) -> TimeSeries:
        """Convert pyESDL rows into a unit-converted, multiplied and validated TimeSeries."""
        column_name = cast(str, profile.columnName)
        rows = reshape_rows(data, header, column_name)
        df = self._rows_to_dataframe(rows, 1)
        if profile.profileQuantityAndUnit is not None:
            df = self._convert_units(df, profile)
        else:
            self.db_logger.warning(
                f"DataTable profile '{profile.tableName}.{column_name}' has no unit; "
                f"values are used unconverted"
            )
        df = self._apply_multiplier(df, profile)
        values_list = df.values.flatten().tolist()
        validated_values = InputValidator.validate_time_series_data(
            values_list, f"DataTable profile {profile.tableName}.{column_name}"
        )
        return TimeSeries(time_step=DEFAULT_TIME_STEP_SECONDS, values=validated_values)

    def _rows_to_dataframe(
        self, rows: Sequence[Sequence[datetime | float | None]], col_index: int
    ) -> pd.DataFrame:
        """Build a timezone-aware DatetimeIndex DataFrame from raw InfluxDB rows."""
        data_points = {
            row[0].strftime("%Y-%m-%dT%H:%M:%SZ"): row[col_index]  # type: ignore[union-attr]
            for row in rows
        }
        df = pd.DataFrame.from_dict(data_points, orient="index")
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    def _apply_multiplier(
        self, df: pd.DataFrame, profile: esdl.InfluxDBProfile | esdl.DataTableProfile
    ) -> pd.DataFrame:
        """Apply profile multiplier to a DataFrame, warning if the multiplier is zero."""
        multiplier = getattr(profile, "multiplier", None)
        if multiplier is None:
            multiplier = 1.0
        if multiplier == 0.0:
            if isinstance(profile, esdl.DataTableProfile):
                label = f"{profile.tableName}.{profile.columnName}"
            else:
                label = f"{profile.measurement}.{profile.field}"
            self.db_logger.warning(
                f"Profile '{label}' has multiplier=0.0 — all output values will be zero"
            )
        return df * multiplier

    def _extract_asset_id(self, profile: esdl.InfluxDBProfile | esdl.DataTableProfile) -> str:
        """Extract asset ID from the profile container (port, carrier or table/measurement)."""
        try:
            # Profile associated to asset port
            return str(profile.eContainer().energyasset.id)
        except AttributeError:
            try:
                # Profile associated to carrier
                return str(profile.eContainer().id)
            except AttributeError:
                # Fallback to using measurement (Influx) or table name (DataTable) as ID
                if isinstance(profile, esdl.DataTableProfile):
                    return str(profile.tableName)
                return str(profile.measurement)

    def _load_profile_data(self, profile: esdl.InfluxDBProfile) -> TimeSeries:
        """Load data for a single InfluxDB profile.

        Args:
            profile: ESDL InfluxDBProfile element

        Returns:
            TimeSeries object with loaded data

        Raises:
            Exception: Any failure while loading, after it has been logged. The caller
                (``_process_single_profile``) records it in the validation errors.
        """
        measurement = profile.measurement
        field = profile.field

        try:
            self.db_logger.log_query_execution(
                measurement, field, (profile.startDate, profile.endDate)
            )

            # Get database credentials
            credentials = self._get_credentials_for_profile(profile)

            # Log connection success
            self.db_logger.log_connection_success(
                credentials.host, credentials.port, credentials.database
            )

            # Create InfluxDB profile manager
            query_start = time.time()
            time_series_data = InfluxDBProfileManager.create_esdl_influxdb_profile_manager(
                profile,
                credentials.username,
                credentials.password,
                credentials.ssl,
                credentials.verify_ssl,
            )
            query_time = time.time() - query_start

            # Validate profile data
            self._validate_profile_data(profile, time_series_data)

            record_count = len(time_series_data.profile_data_list)
            self.db_logger.log_query_success(measurement, field, record_count, query_time)

            # Convert to pandas DataFrame
            df = self._rows_to_dataframe(time_series_data.profile_data_list, 1)

            # Convert units to standard format
            df = self._convert_units(df, profile)
            df = self._apply_multiplier(df, profile)

            # Validate time series data before creating TimeSeries
            values_list = df.values.flatten().tolist()
            validated_values = InputValidator.validate_time_series_data(
                values_list, f"InfluxDB profile {measurement}.{field}"
            )

            # Log data validation
            asset_id = self._extract_asset_id(profile)
            self.db_logger.debug(
                f"Validated {len(validated_values)} time series values for {asset_id}"
            )

            # Convert to TimeSeries
            return TimeSeries(time_step=DEFAULT_TIME_STEP_SECONDS, values=validated_values)

        except Exception as e:
            self._handle_query_error(e, measurement, field)
            raise

    def _get_credentials_for_profile(self, profile: esdl.InfluxDBProfile) -> DatabaseCredentials:
        """Get database credentials for InfluxDB profile securely.

        Args:
            profile: ESDL InfluxDBProfile element

        Returns:
            DatabaseCredentials from secure sources

        Raises:
            CredentialError: If no credentials found for the profile
        """
        # Parse host from profile (handle URL prefixes)
        profile_host = profile.host
        ssl_setting = False

        # Handle https/http prefixes
        if profile_host.startswith("https://"):
            profile_host = profile_host[HTTPS_PREFIX_LENGTH:]
            ssl_setting = True
        elif profile_host.startswith("http://"):
            profile_host = profile_host[HTTP_PREFIX_LENGTH:]

        # CRITICAL SECURITY FIX: Validate host and port before processing
        try:
            validated_host = InputValidator.validate_database_host(profile_host)
            validated_port = InputValidator.validate_database_port(profile.port)

            # CRITICAL SECURITY FIX: Validate database identifiers to prevent injection
            if profile.database:
                self._validate_profile_field(profile, "database", profile.database)
            self._validate_profile_field(profile, "measurement", profile.measurement)
            self._validate_profile_field(profile, "field", profile.field)

            self.db_logger.debug(
                f"Validated database identifiers for {validated_host}: {validated_port}"
            )

        except (ValidationError, SecurityError) as e:
            self.db_logger.error(
                "Database identifier validation failed - security risk detected",
                {
                    "profile_host": profile.host,
                    "profile_port": profile.port,
                    "profile_database": profile.database,
                    "profile_measurement": profile.measurement,
                    "profile_field": profile.field,
                    "validation_error": str(e),
                },
                e,
            )
            raise CredentialError(
                f"Security validation failed for InfluxDB profile: {e} "
                f"(Context: profile_host={profile.host}, profile_port={profile.port}, "
                f"security_check=database_identifier_validation)"
            ) from e

        if profile.port == DEFAULT_DATABASE_SSL_PORT:
            ssl_setting = True

        try:
            credentials = self._get_secure_credentials(validated_host, validated_port)

            # Validate credentials for security
            InputValidator.validate_database_credentials(credentials)

            # Override SSL setting from profile if needed
            if ssl_setting and not credentials.ssl:
                # Create new credentials with corrected SSL setting
                credentials = DatabaseCredentials(
                    host=credentials.host,
                    port=credentials.port,
                    username=credentials.username,
                    password=credentials.password,
                    database=credentials.database,
                    ssl=ssl_setting,
                    verify_ssl=credentials.verify_ssl,
                )

                # Re-validate modified credentials
                InputValidator.validate_database_credentials(credentials)

            return credentials

        except CredentialError as e:
            # Add profile context to the error
            raise CredentialError(
                f"Cannot load credentials for InfluxDB profile: {e} "
                f"(Context: profile_host={profile.host}, profile_port={profile.port}, "
                f"profile_database={profile.database}, profile_field={profile.field}, "
                f"profile_measurement={profile.measurement})"
            ) from e

    def _validate_profile_data(
        self, profile: esdl.InfluxDBProfile, time_series_data: TimeSeriesDataProtocol
    ) -> None:
        """Validate profile data following MESIDO pattern."""
        # Validate start/end dates match
        if time_series_data.end_datetime != profile.endDate:
            raise ValueError(
                f"Profile end datetime mismatch: expected {profile.endDate}, "
                f"got {time_series_data.end_datetime} for field {profile.field}"
            )

        if time_series_data.start_datetime != profile.startDate:
            raise ValueError(
                f"Profile start datetime mismatch: expected {profile.startDate}, "
                f"got {time_series_data.start_datetime} for field {profile.field}"
            )

        # Validate data range consistency
        if time_series_data.start_datetime != time_series_data.profile_data_list[0][0]:
            raise ValueError(
                f"Start datetime inconsistency in profile data for field {profile.field}"
            )

        if time_series_data.end_datetime != time_series_data.profile_data_list[-1][0]:
            raise ValueError(
                f"End datetime inconsistency in profile data for field {profile.field}"
            )

        # Validate time resolution (expect hourly data)
        for i in range(len(time_series_data.profile_data_list) - 1):
            time_resolution = cast(datetime, time_series_data.profile_data_list[i + 1][0]) - cast(
                datetime, time_series_data.profile_data_list[i][0]
            )
            if int(time_resolution.total_seconds()) != SECONDS_PER_HOUR:
                actual_seconds = int(time_resolution.total_seconds())
                raise ValueError(
                    f"Expected {SECONDS_PER_HOUR}s time resolution, got {actual_seconds}s "
                    f"for profile {profile.measurement}-{profile.field}"
                )

    def _convert_units(
        self, df: pd.DataFrame, profile: esdl.InfluxDBProfile | esdl.DataTableProfile
    ) -> pd.DataFrame:
        """Convert units to standard format following MESIDO pattern."""
        try:
            # Get physical quantity
            try:
                unit = profile.profileQuantityAndUnit.reference.physicalQuantity
            except AttributeError:
                unit = profile.profileQuantityAndUnit.physicalQuantity

            # Convert based on physical quantity
            for i in range(len(df)):
                if unit == esdl.PhysicalQuantityEnum.POWER:
                    df.iloc[i] = convert_to_unit(
                        df.iloc[i], profile.profileQuantityAndUnit, POWER_IN_W
                    )
                elif unit == esdl.PhysicalQuantityEnum.ENERGY:
                    df.iloc[i] = convert_to_unit(
                        df.iloc[i], profile.profileQuantityAndUnit, ENERGY_IN_J
                    )
                elif unit == esdl.PhysicalQuantityEnum.COST:
                    # No unit conversion for cost
                    pass
                else:
                    self.db_logger.warning(
                        "Unsupported physical quantity for unit conversion",
                        {"physical_quantity": str(unit)},
                    )

            return df

        except Exception as e:
            self.db_logger.error("Unit conversion failed, using original values", exception=e)
            return df

    def set_credential_manager(self, credential_manager: CredentialManager) -> None:
        """Set a new credential manager.

        Args:
            credential_manager: New credential manager to use
        """
        self.credential_manager = credential_manager
        self.db_logger.debug("Credential manager updated")

    def _validate_profile_field(
        self, profile: InfluxDBProfileProtocol, field_name: str, field_value: str
    ) -> None:
        """Validate a single profile field with enhanced error context.

        Args:
            profile: InfluxDB profile containing context information
            field_name: Name of the field being validated
            field_value: Value of the field to validate

        Raises:
            CredentialError: If validation fails with detailed context
        """
        try:
            InputValidator.validate_database_identifier(field_value, field_name)
        except (ValidationError, SecurityError) as e:
            self.db_logger.error(
                f"Database identifier validation failed for '{field_name}' - security risk",
                {
                    "field": field_name,
                    "profile_host": profile.host,
                    "profile_port": profile.port,
                    "profile_database": getattr(profile, "database", None),
                    "profile_measurement": profile.measurement,
                    "profile_field": profile.field,
                    "validation_error": str(e),
                },
                e,
            )
            raise CredentialError(
                f"Security validation failed for InfluxDB profile '{field_name}': {e} "
                f"(Context: host={profile.host}, port={profile.port}, "
                f"security_check=database_identifier_validation)"
            ) from e

    def _categorize_profile_error(self, error: Exception, profile_field: str) -> str:
        """Categorize profile loading errors with appropriate error messages.

        This method implements a systematic exception categorization strategy
        for database time series loading, providing clear error classification
        and consistent error message formatting.

        Exception Categories:
        1. Configuration Errors: Issues with credentials, security, or validation
           - CredentialError: Missing or invalid database credentials
           - SecurityError: Security validation failures (paths, hosts, etc.)
           - ValidationError: Data validation failures

        2. Connection Errors: Network/database connectivity issues
           - ConnectionError: Database connection failures
           - TimeoutError: Request timeout during database operations

        3. Data Processing Errors: Issues with data format or access
           - ValueError: Invalid data values or format issues
           - KeyError: Missing expected data keys
           - AttributeError: Missing object attributes during processing

        4. Unexpected Errors: All other exceptions not in above categories
           - RuntimeError, Exception, etc.: Unforeseen errors

        Args:
            error: The exception that occurred
            profile_field: The profile field being processed

        Returns:
            Appropriate error message based on exception type

        Note:
            All errors result in graceful degradation with descriptive messages
            that help identify the root cause and appropriate resolution steps.
        """
        if isinstance(error, CredentialError | SecurityError | ValidationError):
            return f"Configuration error loading profile {profile_field}: {error!s}"
        if isinstance(error, ConnectionError | TimeoutError):
            return f"Database connection failed for profile {profile_field}: {error!s}"
        if isinstance(error, ValueError | KeyError | AttributeError):
            return f"Data processing error for profile {profile_field}: {error!s}"
        return f"Unexpected error loading profile {profile_field}: {error!s}"

    def _handle_query_error(self, error: Exception, measurement: str, field: str) -> None:
        """Log a query execution error with context (measurement, field, error).

        This method only logs. The caller re-raises so that
        ``_process_single_profile`` can record the failure in the validation errors
        and continue with the remaining profiles.

        Args:
            error: The exception that occurred during query execution
            measurement: The InfluxDB measurement being queried
            field: The specific field being queried
        """
        self.db_logger.log_query_error(measurement, field, error)
