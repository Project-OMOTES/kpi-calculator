# src/kpicalculator/adapters/database_time_series_loader.py
"""Database time series loader following MESIDO InfluxDB pattern."""

import time
from datetime import datetime
from typing import Protocol

import pandas as pd
from esdl import esdl
from esdl.profiles.influxdbprofilemanager import InfluxDBProfileManager
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


class TimeSeriesDataProtocol(Protocol):
    """Protocol for time series data from InfluxDBProfileManager."""

    start_datetime: datetime
    end_datetime: datetime
    profile_data_list: list[tuple[datetime, float]]


class InfluxDBProfileProtocol(Protocol):
    """Protocol for InfluxDB profile objects with database connection details."""

    host: str
    port: int
    database: str
    measurement: str
    field: str


class DatabaseTimeSeriesLoader:
    """Load time series data from database references in ESDL files.

    This follows the MESIDO pattern for InfluxDB connectivity, supporting
    InfluxDBProfile elements embedded in ESDL files with connection details.
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
       - Failed profiles result in None values rather than exceptions
       - Partial data loading succeeds when some profiles are accessible
       - All errors are logged with detailed context for troubleshooting

    3. Helper Methods:
       - _categorize_profile_error(): Categorizes exceptions and formats messages
       - _handle_query_error(): Provides consistent error logging and degradation

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
        """Load all InfluxDB time series profiles from ESDL energy system.

        Args:
            energy_system: ESDL EnergySystem containing InfluxDBProfile elements

        Returns:
            Tuple of (time_series_dict, validation_result)
            - time_series_dict: Maps asset_id to TimeSeries objects
            - validation_result: Validation status and any warnings/errors
        """
        start_time = time.time()
        self.db_logger.info("Starting InfluxDB profile loading from ESDL")

        time_series_data: dict[str, TimeSeries] = {}
        errors = []
        warnings = []

        try:
            # Find all InfluxDBProfile elements in the ESDL
            influx_profiles = [
                x for x in energy_system.eAllContents() if isinstance(x, esdl.InfluxDBProfile)
            ]

            profile_count = len(influx_profiles)
            self.db_logger.info("Found InfluxDB profiles in ESDL", {"profile_count": profile_count})

            if not influx_profiles:
                warnings.append("No InfluxDB profiles found in ESDL file")
                return time_series_data, ValidationResult(True, [], warnings)

            successful_loads = 0
            failed_loads = 0

            for profile in influx_profiles:
                try:
                    # Extract asset ID associated with this profile
                    asset_id = self._extract_asset_id(profile)

                    # Extract field name (parameter) from profile
                    field_name = profile.field
                    if not field_name:
                        self.db_logger.warning(
                            f"InfluxDB profile for asset {asset_id} has no field name, skipping"
                        )
                        failed_loads += 1
                        continue

                    # Load time series data
                    profile_start = time.time()
                    time_series = self._load_profile_data(profile)
                    profile_time = time.time() - profile_start

                    if time_series:
                        # Create composite key: asset_id|field_name to preserve parameter info
                        composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{field_name}"
                        time_series_data[composite_key] = time_series
                        successful_loads += 1

                        self.db_logger.log_time_series_processing(
                            asset_id, len(time_series.values), time_series.time_step, profile_time
                        )
                        self.db_logger.debug(
                            f"Loaded {field_name} time series for asset {asset_id}"
                        )
                    else:
                        failed_loads += 1

                except Exception as e:
                    failed_loads += 1
                    error_msg = self._categorize_profile_error(e, profile.field)
                    errors.append(error_msg)

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

            # Log summary
            total_time = time.time() - start_time
            self.db_logger.info(
                "InfluxDB profile loading completed",
                {
                    "total_profiles": profile_count,
                    "successful_loads": successful_loads,
                    "failed_loads": failed_loads,
                    "total_time_ms": round(total_time * 1000, 2),
                },
            )

        except Exception as e:
            errors.append(f"Failed to process InfluxDB profiles: {str(e)}")
            self.db_logger.error("Critical error during profile loading", exception=e)

        validation_result = ValidationResult(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings
        )

        return time_series_data, validation_result

    def _extract_asset_id(self, profile: esdl.InfluxDBProfile) -> str:
        """Extract asset ID from InfluxDB profile container."""
        try:
            # Profile associated to asset port
            return str(profile.eContainer().energyasset.id)
        except AttributeError:
            try:
                # Profile associated to carrier
                return str(profile.eContainer().id)
            except AttributeError:
                # Fallback to using measurement as ID
                return str(profile.measurement)

    def _load_profile_data(self, profile: esdl.InfluxDBProfile) -> TimeSeries | None:
        """Load data for a single InfluxDB profile.

        Args:
            profile: ESDL InfluxDBProfile element

        Returns:
            TimeSeries object with loaded data, or None if loading failed
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
            data_points = {
                t[0].strftime("%Y-%m-%dT%H:%M:%SZ"): t[1]
                for t in time_series_data.profile_data_list
            }
            df = pd.DataFrame.from_dict(data_points, orient="index")
            df.index = pd.to_datetime(df.index, utc=True)

            # Convert units to standard format
            df = self._convert_units(df, profile)

            # Apply multiplier with safe default
            multiplier = getattr(profile, "multiplier", 1.0) or 1.0
            df = df * multiplier

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
            return None

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
            time_resolution = (
                time_series_data.profile_data_list[i + 1][0]
                - time_series_data.profile_data_list[i][0]
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
        if isinstance(error, (CredentialError, SecurityError, ValidationError)):
            return f"Configuration error loading profile {profile_field}: {str(error)}"
        if isinstance(error, (ConnectionError, TimeoutError)):
            return f"Database connection failed for profile {profile_field}: {str(error)}"
        if isinstance(error, (ValueError, KeyError, AttributeError)):
            return f"Data processing error for profile {profile_field}: {str(error)}"
        return f"Unexpected error loading profile {profile_field}: {str(error)}"

    def _handle_query_error(self, error: Exception, measurement: str, field: str) -> None:
        """Handle query execution errors with graceful degradation.

        This method implements a consistent error handling strategy for database
        query operations, ensuring that all errors are properly logged while
        maintaining graceful degradation behavior.

        Strategy:
        - All exceptions are logged with detailed context (measurement, field, error)
        - All exceptions result in graceful degradation (caller returns None)
        - No exceptions are re-raised to ensure system stability
        - Consistent logging format for troubleshooting and monitoring

        This approach ensures that individual profile loading failures do not
        crash the entire time series loading process, allowing partial data
        loading when some profiles are accessible.

        Args:
            error: The exception that occurred during query execution
            measurement: The InfluxDB measurement being queried
            field: The specific field being queried

        Note:
            After calling this method, the caller should return None to indicate
            failed loading. This preserves the original graceful degradation
            behavior where all loading failures result in None rather than
            exceptions being propagated.
        """
        self.db_logger.log_query_error(measurement, field, error)
        # All errors result in graceful degradation (return None from caller)
