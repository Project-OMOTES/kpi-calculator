# src/kpicalculator/adapters/database_time_series_loader.py
"""Database time series loader for InfluxDB and PostgreSQL profiles in ESDL files."""

import math
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd
from esdl import esdl
from esdl.profiles.influxdbprofilemanager import ConnectionSettings, InfluxDBProfileManager
from esdl.profiles.profile_utils import close_db_connections, load_profile_data_and_header
from esdl.units.conversion import POWER_IN_W, UnitException, convert_to_unit

from ..common.constants import (
    COMPOSITE_KEY_SEPARATOR,
    DEFAULT_DATABASE_SSL_PORT,
    DEFAULT_TIME_STEP_SECONDS,
    HTTP_PREFIX_LENGTH,
    HTTPS_PREFIX_LENGTH,
    KNOWN_TIME_SERIES_FIELDS,
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
    DataTableTarget,
    check_database_login,
    database_read_lock,
    detached_copy,
    enable_autocommit,
    is_database_profile,
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


# Series names listed in the unrecognised-fields warning before it is truncated.
_UNRECOGNISED_PREVIEW = 10


class _ReadLockTimeout(TimeoutError):
    """Raised when a DataTable read could not take ``DATABASE_READ_LOCK`` in time."""


@dataclass
class _ReadLockState:
    """Whether any profile of one load got past acquiring ``DATABASE_READ_LOCK``."""

    acquired: bool = False


@contextmanager
def _read_lock(state: _ReadLockState) -> Iterator[None]:
    """Hold ``DATABASE_READ_LOCK``; failing to take it raises ``_ReadLockTimeout``.

    A ``TimeoutError`` raised inside the block is not a lock timeout and passes through.
    """
    entered = False
    try:
        with database_read_lock():
            entered = True
            state.acquired = True
            yield
    except TimeoutError as e:
        if entered:
            raise
        raise _ReadLockTimeout(str(e)) from e


def _strip_url_scheme(host: str) -> str:
    """Drop a leading ``http://`` or ``https://`` from an ESDL profile host."""
    if host.startswith("https://"):
        return host[HTTPS_PREFIX_LENGTH:]
    if host.startswith("http://"):
        return host[HTTP_PREFIX_LENGTH:]
    return host


def _as_utc(moment: datetime) -> datetime:
    """Return ``moment`` in UTC; a naive datetime is taken as UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class DatabaseTimeSeriesLoader:
    """Load time series data from database references in ESDL files.

    Supports ``InfluxDBProfile`` elements (read with batched InfluxDB queries, following
    the MESIDO pattern) and PostgreSQL ``DataTableProfile`` elements (read per profile
    through pyESDL's ``load_profile_data_and_header``). ``DataTableProfile`` elements with
    ``profileType`` OUTPUT or a non-database configuration are skipped.

    Credentials come from two places. Influx profiles use the ``CredentialManager`` chain
    (``KPI_DB_*``, ``INFLUXDB_*``, config file). PostgreSQL reads use pyESDL's own
    ``Credentials`` registry (``DB_HOST``/``DB_USER``/``DB_PASSWORD`` read once when
    ``esdl.profiles.credentials`` is first imported, or ``Credentials.add_credential``).

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
       - Profiles that load are returned even when others fail; any load failure still
         makes ValidationResult.is_valid False
       - All errors are logged with detailed context for troubleshooting

    3. Helper Methods:
       - _categorize_profile_error(): Categorizes exceptions and formats messages
       - _handle_query_error(): Provides consistent query error logging
       - _process_data_table_profile(): Loads one DataTableProfile with the same degradation

    This design ensures system stability while providing clear error reporting
    for debugging and monitoring database connectivity issues.
    """

    def __init__(
        self,
        credential_manager: CredentialManager | None = None,
        *,
        allow_passwordless_database: bool = False,
    ):
        """Initialize database loader with secure credential management.

        Args:
            credential_manager: Credential manager for Influx profiles. Uses default if None.
            allow_passwordless_database: Read PostgreSQL DataTableProfiles even when pyESDL
                has no complete login (username and password) for the host. The default
                fails closed, because libpq may then authenticate from ``PGUSER``,
                ``PGPASSWORD``, ``.pgpass``, ``PGSERVICE`` or trust authentication.
        """
        self.credential_manager = credential_manager or create_default_credential_manager()
        self.allow_passwordless_database = allow_passwordless_database
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
                    f"Set environment variables (including {env_prefix}_HOST) or "
                    f"configure credentials file. "
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
        merged into one dict listing its entries in ESDL profile order. On a composite-key
        collision the first profile in ESDL order is kept; later ones are not loaded and are
        recorded as errors. When a DataTable read took the database lock, even one that then
        failed, ``close_db_connections()`` runs once in a ``finally`` afterwards.

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
            influx_profiles, table_profiles, esdl_order = self._collect_database_profiles(
                energy_system
            )

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

            planned_keys = [self._planned_key(profile) for profile in esdl_order]
            influx_profiles, table_profiles, failed_loads = self._drop_duplicate_keys(
                influx_profiles, table_profiles, esdl_order, planned_keys, errors
            )
            successful_loads = 0

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

            table_successful, table_failed = self._load_data_table_profiles(
                table_profiles, time_series_data, errors
            )
            successful_loads += table_successful
            failed_loads += table_failed

            time_series_data = self._in_esdl_order(time_series_data, planned_keys)
            unrecognised = self._unrecognised_fields_warning(time_series_data)
            if unrecognised:
                warnings.append(unrecognised)

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

    @staticmethod
    def _unrecognised_fields_warning(time_series_data: dict[str, TimeSeries]) -> str | None:
        """Summarise loaded series whose field is not a recognised KPI field, or None if all are.

        The energy and emission calculators look series up by the recognised names. The series
        stay in the result; only the warning is new, as for DataFrame columns.
        """
        names = [
            f"{asset_id}/{field}"
            for asset_id, _, field in (
                key.partition(COMPOSITE_KEY_SEPARATOR) for key in time_series_data
            )
            if field not in KNOWN_TIME_SERIES_FIELDS
        ]
        if not names:
            return None
        shown = ", ".join(names[:_UNRECOGNISED_PREVIEW])
        more = (
            f", … +{len(names) - _UNRECOGNISED_PREVIEW} more"
            if len(names) > _UNRECOGNISED_PREVIEW
            else ""
        )
        return f"{len(names)} series are not recognised KPI fields: {shown}{more}"

    def _collect_database_profiles(
        self, energy_system: esdl.EnergySystem
    ) -> tuple[
        list[esdl.InfluxDBProfile],
        list[esdl.DataTableProfile],
        list[esdl.InfluxDBProfile | esdl.DataTableProfile],
    ]:
        """Collect Influx and eligible DataTable profiles; warn once about skipped ones.

        Returns:
            (influx_profiles, table_profiles, all_profiles) where ``all_profiles`` holds both
            kinds in the order ``eAllContents()`` yields them.
        """
        influx_profiles: list[esdl.InfluxDBProfile] = []
        table_profiles: list[esdl.DataTableProfile] = []
        esdl_order: list[esdl.InfluxDBProfile | esdl.DataTableProfile] = []
        skipped = 0
        for element in energy_system.eAllContents():
            if isinstance(element, esdl.InfluxDBProfile):
                influx_profiles.append(element)
                esdl_order.append(element)
            elif isinstance(element, esdl.DataTableProfile):
                if is_database_profile(element):
                    table_profiles.append(element)
                    esdl_order.append(element)
                else:
                    skipped += 1
        if skipped:
            self.db_logger.warning(
                f"Skipped {skipped} DataTableProfile(s) that are OUTPUT profiles or use a "
                f"non-database configuration"
            )
        return influx_profiles, table_profiles, esdl_order

    def _planned_key(self, profile: esdl.InfluxDBProfile | esdl.DataTableProfile) -> str | None:
        """Return the composite key a profile will be stored under, or None if unknown.

        None for an Influx profile without a field, a DataTable profile without a column, or a
        profile whose asset id cannot be extracted; those take the normal path, which records
        their own error.
        """
        name = profile.columnName if isinstance(profile, esdl.DataTableProfile) else profile.field
        if not name:
            return None
        try:
            asset_id = self._extract_asset_id(profile)
        except Exception:
            return None
        return f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{name}"

    def _drop_duplicate_keys(
        self,
        influx_profiles: list[esdl.InfluxDBProfile],
        table_profiles: list[esdl.DataTableProfile],
        esdl_order: list[esdl.InfluxDBProfile | esdl.DataTableProfile],
        planned_keys: list[str | None],
        errors: list[str],
    ) -> tuple[list[esdl.InfluxDBProfile], list[esdl.DataTableProfile], int]:
        """Remove every profile whose composite key an earlier profile in ESDL order claims.

        The first profile for a key wins whatever its kind or batch grouping; a dropped
        profile is never queried or read. Each is recorded as one error.

        Returns:
            (influx_profiles, table_profiles, dropped_count) without the dropped profiles.
        """
        seen: set[str] = set()
        dropped: set[int] = set()
        for profile, key in zip(esdl_order, planned_keys, strict=True):
            if key is None:
                continue
            if key not in seen:
                seen.add(key)
                continue
            source = (
                f"table '{profile.tableName}'"
                if isinstance(profile, esdl.DataTableProfile)
                else f"measurement '{profile.measurement}'"
            )
            message = f"Duplicate time series key '{key}' ({source}); keeping the first entry"
            self.db_logger.warning(message)
            errors.append(message)
            dropped.add(id(profile))
        return (
            [p for p in influx_profiles if id(p) not in dropped],
            [p for p in table_profiles if id(p) not in dropped],
            len(dropped),
        )

    def _in_esdl_order(
        self,
        time_series_data: dict[str, TimeSeries],
        planned_keys: list[str | None],
    ) -> dict[str, TimeSeries]:
        """Return the loaded series keyed in ESDL profile order.

        Batching and the separate DataTable pass load profiles in a different order, but
        consumers take an asset's first series as its primary one.
        """
        ordered: dict[str, TimeSeries] = {}
        for key in planned_keys:
            if key is not None and key in time_series_data:
                ordered[key] = time_series_data[key]
        # Keys that no collected profile plans (none expected) keep their load order.
        for key, series in time_series_data.items():
            ordered.setdefault(key, series)
        return ordered

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

        # Profiles with an empty/None field, a non-finite multiplier or an ENERGY quantity
        # cannot be batched; route them per-profile up front, where they are rejected.
        valid_profiles: list[esdl.InfluxDBProfile] = []
        unbatchable_profiles: list[esdl.InfluxDBProfile] = []
        for p in profiles:
            if p.field and self._has_finite_multiplier(p) and not self._is_energy_profile(p):
                valid_profiles.append(p)
            else:
                unbatchable_profiles.append(p)
        # Pick representative from valid profiles so credential validation always succeeds.
        representative = valid_profiles[0] if valid_profiles else profiles[0]
        measurement = representative.measurement
        warn_msg = (
            f"Profile in '{measurement}' has an empty field, non-finite multiplier or ENERGY "
            f"quantity — processing per-profile"
        )
        successful, failed = self._fallback_to_per_profile(
            unbatchable_profiles, time_series_data, errors, warn_msg=warn_msg
        )

        if not valid_profiles:
            return successful, failed

        if len(valid_profiles) == 1:
            success = self._process_single_profile(valid_profiles[0], time_series_data, errors)
            return successful + (1 if success else 0), failed + (0 if success else 1)

        try:
            manager, field_index_map = self._execute_batch_query(
                valid_profiles, representative, measurement
            )
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
    ) -> tuple[InfluxDBProfileManager, dict[str, int]]:
        """Authenticate, issue the batch SELECT, and return the manager + field index map.

        Connects to the profile's database, which the batch group shares. Any failure is
        raised for the caller to fall back from.
        """
        # Fetch representative's credentials first, then validate the rest.
        # The loop calls are validation-only side-effects; return values are intentionally
        # discarded — each profile's host/port must be authorised before batch query.
        credentials = self._get_credentials_for_profile(representative)
        for profile in valid_profiles:
            if profile is not representative:
                self._get_credentials_for_profile(profile)

        manager = InfluxDBProfileManager(
            ConnectionSettings(
                host=_strip_url_scheme(representative.host),
                port=representative.port,
                database=representative.database,
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
            raise ValueError(
                f"No data returned for measurement '{measurement}' in database "
                f"'{representative.database}'"
            )
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
                raise ValidationError(
                    f"InfluxDB profile for asset {asset_id} (measurement "
                    f"'{profile.measurement}') has no field name"
                )

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
            errors.append(self._categorize_profile_error(e, profile.field or "?"))
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

    def _load_data_table_profiles(
        self,
        profiles: list[esdl.DataTableProfile],
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
    ) -> tuple[int, int]:
        """Read DataTable profiles one by one, then close pyESDL's connections once.

        The close is skipped when no read acquired the lock: every profile failed validation
        or a lock timeout left this load with nothing acquired.

        Returns:
            (successful_loads, failed_loads)
        """
        if not profiles:
            return 0, 0
        successful = 0
        lock_state = _ReadLockState()
        try:
            for index, profile in enumerate(profiles):
                try:
                    if self._process_data_table_profile(
                        profile, time_series_data, errors, lock_state
                    ):
                        successful += 1
                except _ReadLockTimeout:
                    # Waiting again for every remaining profile would stack the timeouts.
                    errors.extend(
                        f"Skipped DataTable profile {self._data_table_subject(skipped)} "
                        f"after a database lock timeout"
                        for skipped in profiles[index + 1 :]
                    )
                    break
        finally:
            # This load can only have opened a connection after a read acquired the lock. With
            # no acquisition (every profile rejected by validation, or a lock timeout first)
            # there is nothing of its own to close, and waiting for the lock again, or closing
            # pyESDL's shared connections, would only affect other users.
            if lock_state.acquired:
                try:
                    with database_read_lock():
                        close_db_connections()
                except TimeoutError as e:
                    self.db_logger.error(
                        "Could not close pyESDL database connections; they stay open", {}, e
                    )
        return successful, len(profiles) - successful

    def _data_table_subject(
        self, profile: esdl.DataTableProfile, asset_id: str | None = None
    ) -> str:
        """Describe a DataTable profile in error messages."""
        if asset_id is None:
            asset_id = "?"
            with suppress(Exception):
                asset_id = self._extract_asset_id(profile)
        return f"{profile.columnName or '?'} (asset {asset_id}, table '{profile.tableName}')"

    def _process_data_table_profile(
        self,
        profile: esdl.DataTableProfile,
        time_series_data: dict[str, TimeSeries],
        errors: list[str],
        lock_state: _ReadLockState,
    ) -> bool:
        """Read one DataTableProfile and add it to time_series_data.

        An existing entry with the same composite key is kept; the duplicate is recorded as an
        error without being read.

        Returns:
            True if the profile was loaded successfully, False otherwise.

        Raises:
            _ReadLockTimeout: The profile could not take ``DATABASE_READ_LOCK``. Its error is
                recorded first; the caller stops reading further profiles.
        """
        asset_id: str | None = None
        try:
            asset_id = self._extract_asset_id(profile)
            target = validate_data_table_profile(profile, asset_id)
            self._finite_multiplier(profile)  # fail before any read
            if profile.profileQuantityAndUnit is not None:
                # A unit that cannot be read is reported after the read, like a missing one.
                with suppress(AttributeError):
                    self._require_supported_quantity(
                        profile.profileQuantityAndUnit,
                        f"{profile.tableName}.{profile.columnName}",
                    )

            composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{profile.columnName}"
            if composite_key in time_series_data:
                message = (
                    f"Duplicate time series key '{composite_key}' (table "
                    f"'{profile.tableName}'); keeping the first entry"
                )
                self.db_logger.warning(message)
                errors.append(message)
                return False

            profile_start = time.time()
            time_series = self._read_data_table_profile(profile, target, lock_state)
            profile_time = time.time() - profile_start
            time_series_data[composite_key] = time_series
            self.db_logger.log_time_series_processing(
                asset_id, len(time_series.values), time_series.time_step, profile_time
            )
            return True

        except Exception as e:
            subject = self._data_table_subject(profile, asset_id)
            errors.append(self._categorize_profile_error(e, subject))
            self.db_logger.error(
                "DataTable profile loading failed",
                {"table_name": profile.tableName, "column_name": profile.columnName},
                e,
            )
            if isinstance(e, _ReadLockTimeout):
                raise
            return False

    def _read_data_table_profile(
        self,
        profile: esdl.DataTableProfile,
        target: DataTableTarget,
        lock_state: _ReadLockState,
    ) -> TimeSeries:
        """Read one validated DataTableProfile through pyESDL and reshape it.

        The login comes from pyESDL's ``Credentials`` registry and must be complete unless
        ``allow_passwordless_database`` is set (see ``check_database_login``). The read runs
        on a copy of the profile without a configuration id, so an id from the ESDL file
        cannot select another host's credential. The pyESDL cache is disabled (its key omits
        the profile filter), the multiplier is applied here after float coercion rather than
        by pyESDL, and the connection stays open, in autocommit, for the caller to close.
        A unit that pyESDL reads from ``datatable_metadata`` is stored on the copy.

        Raises:
            _ReadLockTimeout: ``DATABASE_READ_LOCK`` could not be taken in time.
            Exception: Any validation, credential, read or reshape failure.
        """
        read_profile = detached_copy(profile)
        with _read_lock(lock_state):
            warning = check_database_login(
                read_profile.configuration,
                allow_passwordless=self.allow_passwordless_database,
            )
            if warning:
                self.db_logger.warning(warning)
            self.db_logger.log_connection_attempt(target.host, target.port)
            enable_autocommit(read_profile)
            data, header = load_profile_data_and_header(
                read_profile,
                enable_cache=False,
                apply_multiplier=False,
                close_connection_after_load=False,
            )
        return self._data_table_rows_to_time_series(profile, read_profile, data, header)

    def _data_table_rows_to_time_series(
        self,
        profile: esdl.DataTableProfile,
        read_profile: esdl.DataTableProfile,
        data: Sequence[Sequence[Any]] | None,
        header: Sequence[Any] | None,
    ) -> TimeSeries:
        """Convert pyESDL rows into a unit-converted, multiplied and validated TimeSeries.

        The unit is the profile's own ``profileQuantityAndUnit``, else the one pyESDL read from
        ``datatable_metadata`` onto ``read_profile``.

        Raises:
            ValidationError: Neither source provides a unit.
        """
        column_name = cast(str, profile.columnName)
        label = f"{profile.tableName}.{column_name}"
        quantity_and_unit = profile.profileQuantityAndUnit or read_profile.profileQuantityAndUnit
        if quantity_and_unit is None:
            raise ValidationError(
                f"DataTable profile '{label}' has no unit: set profileQuantityAndUnit on the "
                f"profile in the ESDL or provide it in the datatable_metadata table"
            )
        rows = reshape_rows(data, header, column_name)
        self._require_requested_interval(profile, rows, column_name)
        df = pd.DataFrame(
            [row[1] for row in rows], index=pd.DatetimeIndex([row[0] for row in rows])
        )
        df.iloc[:, 0] = self._to_base_unit(df.iloc[:, 0], quantity_and_unit, label)
        multiplier = self._finite_multiplier(profile)
        if multiplier == 0.0:
            self.db_logger.warning(
                f"Profile '{label}' has multiplier=0.0 — all output values will be zero"
            )
        df = df * multiplier
        self._require_finite_values(
            df,
            f"DataTable profile '{label}' has non-finite values after unit conversion "
            f"and multiplier {multiplier}",
        )
        values_list = df.values.flatten().tolist()
        validated_values = InputValidator.validate_time_series_data(
            values_list, f"DataTable profile {label}"
        )
        return TimeSeries(time_step=DEFAULT_TIME_STEP_SECONDS, values=validated_values)

    @staticmethod
    def _require_requested_interval(
        profile: esdl.DataTableProfile, rows: Sequence[Sequence[Any]], column_name: str
    ) -> None:
        """Raise ValueError if the rows start or end more than an hour inside the requested window.

        pyESDL filters inclusively on whichever of ``startDate``/``endDate`` is set. Rows no more
        than an hour from a bound are accepted, so bounds off the hourly grid still work.
        Naive datetimes are taken as UTC.
        """
        first, last = _as_utc(rows[0][0]), _as_utc(rows[-1][0])
        start = _as_utc(profile.startDate) if profile.startDate else None
        end = _as_utc(profile.endDate) if profile.endDate else None
        one_hour = timedelta(seconds=SECONDS_PER_HOUR)
        if (start is not None and first - start > one_hour) or (
            end is not None and end - last > one_hour
        ):
            requested = (
                f"{start.isoformat() if start else 'open'} to {end.isoformat() if end else 'open'}"
            )
            raise ValueError(
                f"Column '{column_name}' returned rows from {first.isoformat()} to "
                f"{last.isoformat()}, which does not cover the requested interval {requested}"
            )

    @staticmethod
    def _require_finite_values(df: pd.DataFrame, message: str) -> None:
        """Raise ValidationError(message) if df holds NaN, inf or non-numeric values."""
        try:
            finite = bool(np.isfinite(df.to_numpy(dtype=float)).all())
        except TypeError, ValueError:
            finite = False
        if not finite:
            raise ValidationError(message)

    @staticmethod
    def _finite_multiplier(profile: esdl.InfluxDBProfile | esdl.DataTableProfile) -> float:
        """Return the profile multiplier (1.0 when unset).

        Raises:
            ValidationError: The multiplier is NaN, infinite or not a number.
        """
        multiplier = getattr(profile, "multiplier", None)
        if multiplier is None:
            return 1.0
        try:
            finite = math.isfinite(multiplier)
        except TypeError, OverflowError:
            finite = False
        if not finite:
            raise ValidationError(f"Profile has a non-finite multiplier ({multiplier})")
        return float(multiplier)

    @staticmethod
    def _is_energy_profile(profile: esdl.InfluxDBProfile) -> bool:
        """Return True if the profile's physical quantity is ENERGY (False if unreadable)."""
        quantity_and_unit = profile.profileQuantityAndUnit
        if quantity_and_unit is None:
            return False
        try:
            quantity = quantity_and_unit.reference.physicalQuantity
        except AttributeError:
            quantity = getattr(quantity_and_unit, "physicalQuantity", None)
        return bool(quantity == esdl.PhysicalQuantityEnum.ENERGY)

    @classmethod
    def _reject_energy_profile(cls, profile: esdl.InfluxDBProfile) -> None:
        """Reject an ENERGY profile before any query.

        Energy per time step is not converted to average power, so the values would be used as
        watts and come out 3600x too high for hourly rows.

        Raises:
            ValidationError: The profile's physical quantity is ENERGY.
        """
        if cls._is_energy_profile(profile):
            raise ValidationError(
                f"InfluxDB profile {profile.measurement}.{profile.field} has physical quantity "
                f"ENERGY; energy per time step is not converted to average power, so it would "
                f"be read as watts (3600x too high for hourly rows). Use a POWER profile "
                f"(W, kW, MW) instead."
            )

    @classmethod
    def _has_finite_multiplier(cls, profile: esdl.InfluxDBProfile | esdl.DataTableProfile) -> bool:
        """Return True if the profile multiplier is unset or a finite number."""
        try:
            cls._finite_multiplier(profile)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _require_supported_quantity(
        quantity_and_unit: esdl.QuantityAndUnitType, label: str
    ) -> esdl.PhysicalQuantityEnum:
        """Return the physical quantity of a DataTable unit if it is power or cost.

        Energy per step is not converted to average power, so it would be read as watts and
        come out 3600x too high for hourly rows; it is rejected with every other quantity.

        Raises:
            ValidationError: The physical quantity is not power or cost.
            AttributeError: The unit has no readable physical quantity.
        """
        try:
            quantity = quantity_and_unit.reference.physicalQuantity
        except AttributeError:
            quantity = quantity_and_unit.physicalQuantity
        if quantity not in (esdl.PhysicalQuantityEnum.POWER, esdl.PhysicalQuantityEnum.COST):
            raise ValidationError(
                f"DataTable profile '{label}' has physical quantity {quantity}; only power "
                f"and cost profiles are supported"
            )
        return quantity

    @classmethod
    def _to_base_unit(
        cls, values: pd.Series, quantity_and_unit: esdl.QuantityAndUnitType, label: str
    ) -> pd.Series:
        """Convert a whole series to W (power) or leave a cost series as it is.

        Raises:
            ValidationError: The physical quantity is not power or cost, or the unit cannot
                be converted to watts.
        """
        quantity = cls._require_supported_quantity(quantity_and_unit, label)
        if quantity == esdl.PhysicalQuantityEnum.COST:
            return values
        try:
            return cast(pd.Series, convert_to_unit(values, quantity_and_unit, POWER_IN_W))
        except UnitException as e:
            raise ValidationError(
                f"DataTable profile '{label}' has a unit that cannot be converted to the "
                f"base unit of {quantity}: {e}"
            ) from e

    def _rows_to_dataframe(
        self, rows: Sequence[Sequence[datetime | float | None]], col_index: int
    ) -> pd.DataFrame:
        """Build a timezone-aware DatetimeIndex float DataFrame from raw InfluxDB rows.

        Values are cast to float because InfluxDB returns integer fields as ints and pandas 3
        refuses to store a converted (non-integral) value in an integer column.
        """
        data_points = {
            row[0].strftime("%Y-%m-%dT%H:%M:%SZ"): row[col_index]  # type: ignore[union-attr]
            for row in rows
        }
        df = pd.DataFrame.from_dict(data_points, orient="index").astype(float)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    def _apply_multiplier(self, df: pd.DataFrame, profile: esdl.InfluxDBProfile) -> pd.DataFrame:
        """Apply profile multiplier to a DataFrame, warning if the multiplier is zero.

        Raises:
            ValidationError: The multiplier is NaN or infinite, or the scaled values are.
        """
        multiplier = self._finite_multiplier(profile)
        if multiplier == 0.0:
            self.db_logger.warning(
                f"Profile '{profile.measurement}.{profile.field}' has multiplier=0.0 — "
                f"all output values will be zero"
            )
        scaled = df * multiplier
        self._require_finite_values(
            scaled,
            f"InfluxDB profile {profile.measurement}.{profile.field} has non-finite values "
            f"after unit conversion and multiplier",
        )
        return scaled

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
            self._finite_multiplier(profile)  # fail before any query
            self._reject_energy_profile(profile)  # fail before any query
            self.db_logger.log_query_execution(
                measurement, field, (profile.startDate, profile.endDate)
            )

            # Get database credentials
            credentials = self._get_credentials_for_profile(profile)

            # Log connection success
            self.db_logger.log_connection_success(
                credentials.host, credentials.port, profile.database
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
            CredentialError: If the profile names no database, or no credentials are found
                for it
        """
        # pyESDL would try to create a database from an empty name.
        if not profile.database:
            raise CredentialError(
                f"InfluxDB profile has no database configured "
                f"(Context: profile_host={profile.host}, profile_port={profile.port}, "
                f"profile_measurement={profile.measurement}, profile_field={profile.field})"
            )

        # Parse host from profile (handle URL prefixes)
        ssl_setting = profile.host.startswith("https://")
        profile_host = _strip_url_scheme(profile.host)

        # CRITICAL SECURITY FIX: Validate host and port before processing
        try:
            validated_host = InputValidator.validate_database_host(profile_host)
            validated_port = InputValidator.validate_database_port(profile.port)

            # CRITICAL SECURITY FIX: Validate database identifiers to prevent injection
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
        if not time_series_data.profile_data_list:
            raise ValueError(
                f"No data returned for {profile.measurement}.{profile.field} in database "
                f"'{profile.database}' between {profile.startDate} and {profile.endDate}"
            )

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

    def _convert_units(self, df: pd.DataFrame, profile: esdl.InfluxDBProfile) -> pd.DataFrame:
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
