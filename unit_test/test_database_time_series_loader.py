# unit_test/test_database_time_series_loader.py
"""Tests for database time series loader."""

import threading
import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import pandas as pd
from esdl import esdl
from esdl.profiles.credentials import Credential, Credentials

from kpicalculator.adapters.common_model import TimeSeries
from kpicalculator.adapters.data_table_profile_reader import DATABASE_READ_LOCK
from kpicalculator.adapters.database_time_series_loader import DatabaseTimeSeriesLoader
from kpicalculator.common.constants import (
    COMPOSITE_KEY_SEPARATOR,
)
from kpicalculator.common.types import DatabaseCredentials
from kpicalculator.exceptions import CredentialError
from kpicalculator.security.credential_manager import CredentialManager
from kpicalculator.security.input_validator import InputValidator


class MockCredentialManager(CredentialManager):
    """Mock credential manager for testing."""

    def __init__(self, credentials=None) -> None:
        self.credentials = credentials or {}

    def get_database_credentials(self, host: str, port: int) -> DatabaseCredentials | None:
        key = f"{host}: {port}"
        return self.credentials.get(key)

    def supports_environment_credentials(self) -> bool:
        """Return False for mock - not environment-based."""
        return False


class TestDatabaseTimeSeriesLoader(unittest.TestCase):
    """Test database time series loader functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create test credentials
        self.test_credentials = DatabaseCredentials(
            host="test.example.com",
            port=443,
            username="test_user",
            password="test_password",
            database="test_db",
            ssl=True,
            verify_ssl=True,
        )

        # Create mock credential manager
        self.credential_manager = MockCredentialManager(
            {"test.example.com: 443": self.test_credentials}
        )

        # Create loader
        self.loader = DatabaseTimeSeriesLoader(self.credential_manager)

    def test_init_with_credential_manager(self) -> None:
        """Test initialization with credential manager."""
        loader = DatabaseTimeSeriesLoader(self.credential_manager)
        self.assertEqual(loader.credential_manager, self.credential_manager)
        self.assertIsNotNone(loader.db_logger)

    def test_init_with_default_credential_manager(self) -> None:
        """Test initialization with default credential manager."""
        with patch(
            "kpicalculator.adapters.database_time_series_loader.create_default_credential_manager"
        ) as mock_create:
            mock_manager = Mock()
            mock_create.return_value = mock_manager

            loader = DatabaseTimeSeriesLoader()

            mock_create.assert_called_once()
            self.assertEqual(loader.credential_manager, mock_manager)

    def test_get_secure_credentials_success(self) -> None:
        """Test successful credential retrieval."""
        credentials = self.loader._get_secure_credentials("test.example.com", 443)

        self.assertEqual(credentials, self.test_credentials)
        self.assertEqual(credentials.host, "test.example.com")
        self.assertEqual(credentials.port, 443)

    def test_get_secure_credentials_not_found(self) -> None:
        """Test credential retrieval when credentials not found."""
        with self.assertRaises(CredentialError) as context:
            self.loader._get_secure_credentials("unknown.host.com", 8080)

        error = context.exception
        self.assertIn("No credentials found", str(error))
        self.assertIn("unknown.host.com: 8080", str(error))
        self.assertIn("host=unknown.host.com", str(error))
        self.assertIn("port=8080", str(error))
        self.assertIn("env_prefix=KPI_DB_UNKNOWN_HOST_COM_8080", str(error))

    def test_get_secure_credentials_exception_handling(self) -> None:
        """Test credential retrieval with manager exception."""
        # Create manager that raises exception
        error_manager = Mock()
        error_manager.get_database_credentials.side_effect = RuntimeError("Manager error")

        loader = DatabaseTimeSeriesLoader(error_manager)

        with self.assertRaises(RuntimeError):
            loader._get_secure_credentials("test.example.com", 443)

    def test_extract_asset_id_from_port(self) -> None:
        """Test asset ID extraction from energy asset port."""
        # Create mock profile with energy asset container
        profile = Mock(spec=esdl.InfluxDBProfile)
        energy_asset = Mock()
        energy_asset.id = "test_asset_123"
        container = Mock()
        container.energyasset = energy_asset
        profile.eContainer.return_value = container

        asset_id = self.loader._extract_asset_id(profile)
        self.assertEqual(asset_id, "test_asset_123")

    def test_extract_asset_id_from_carrier(self) -> None:
        """Test asset ID extraction from carrier when port fails."""
        # Create mock profile that fails on energyasset but has carrier
        profile = Mock(spec=esdl.InfluxDBProfile)
        container = Mock()
        container.energyasset = None  # This will cause AttributeError
        container.id = "carrier_456"

        # Make first eContainer() call raise AttributeError, second succeed
        def side_effect():
            if not hasattr(side_effect, "called"):
                side_effect.called = True
                raise AttributeError("No energyasset")
            return container

        profile.eContainer.side_effect = side_effect

        asset_id = self.loader._extract_asset_id(profile)
        self.assertEqual(asset_id, "carrier_456")

    def test_extract_asset_id_fallback_to_measurement(self) -> None:
        """Test asset ID extraction fallback to measurement."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.eContainer.side_effect = AttributeError("No container")
        profile.measurement = "fallback_measurement"

        asset_id = self.loader._extract_asset_id(profile)
        self.assertEqual(asset_id, "fallback_measurement")

    @patch("kpicalculator.adapters.database_time_series_loader.InfluxDBProfileManager")
    @patch("kpicalculator.adapters.database_time_series_loader.InputValidator")
    def test_load_profile_data_success(self, mock_validator, mock_profile_manager) -> None:
        """Test successful profile data loading."""
        # Setup mocks
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.measurement = "power"
        profile.field = "consumption"
        profile.host = "test.example.com"
        profile.port = 443
        profile.startDate = datetime(2024, 1, 1)
        profile.endDate = datetime(2024, 1, 2)
        profile.multiplier = 1.0

        # Mock profile manager
        mock_time_series_data = Mock()
        mock_time_series_data.profile_data_list = [
            (datetime(2024, 1, 1, 0, 0), 100.0),
            (datetime(2024, 1, 1, 1, 0), 200.0),
            (datetime(2024, 1, 1, 2, 0), 150.0),
        ]
        mock_time_series_data.end_datetime = profile.endDate
        mock_time_series_data.start_datetime = profile.startDate

        mock_profile_manager.create_esdl_influxdb_profile_manager.return_value = (
            mock_time_series_data
        )

        # Mock input validator
        test_values = [100.0, 200.0, 150.0]
        mock_validator.validate_time_series_data.return_value = test_values

        # Mock get credentials method
        with patch.object(self.loader, "_get_credentials_for_profile") as mock_get_creds:
            mock_get_creds.return_value = self.test_credentials

            # Mock validation method
            with patch.object(self.loader, "_validate_profile_data"):
                # Mock unit conversion method
                with patch.object(self.loader, "_convert_units") as mock_convert:
                    mock_df = Mock()
                    mock_df.values.flatten.return_value.tolist.return_value = test_values
                    # Make the mock support multiplication (df * profile.multiplier)
                    mock_df.__mul__ = Mock(return_value=mock_df)
                    mock_convert.return_value = mock_df

                    # Mock extract asset ID
                    with patch.object(self.loader, "_extract_asset_id") as mock_extract:
                        mock_extract.return_value = "test_asset"

                        result = self.loader._load_profile_data(profile)

        # Verify result
        self.assertIsInstance(result, TimeSeries)
        self.assertEqual(result.values, test_values)
        self.assertEqual(result.time_step, 3600.0)  # DEFAULT_TIME_STEP_SECONDS

        # Verify mocks were called
        mock_profile_manager.create_esdl_influxdb_profile_manager.assert_called_once()
        mock_validator.validate_time_series_data.assert_called_once()

    def test_load_profile_data_exception_handling(self) -> None:
        """Test profile data loading logs and re-raises a failure."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.measurement = "power"
        profile.field = "consumption"
        profile.multiplier = 1.0

        # Mock get credentials to raise exception
        with patch.object(self.loader, "_get_credentials_for_profile") as mock_get_creds:
            mock_get_creds.side_effect = CredentialError("No credentials")

            with patch.object(self.loader, "_handle_query_error") as mock_handle:
                with self.assertRaises(CredentialError):
                    self.loader._load_profile_data(profile)

        mock_handle.assert_called_once()

    def test_single_profile_credential_failure_is_reported(self) -> None:
        """A credential failure on the single-profile path must appear in the errors."""
        energy_system = Mock()
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.field = "power"
        profile.measurement = "consumption"
        profile.multiplier = 1.0
        energy_system.eAllContents.return_value = [profile]

        with patch.object(self.loader, "_extract_asset_id", return_value="asset_1"):
            with patch.object(self.loader, "_get_credentials_for_profile") as mock_get_creds:
                mock_get_creds.side_effect = CredentialError("No credentials")

                result_data, validation_result = self.loader.load_time_series_from_esdl(
                    energy_system
                )

        self.assertEqual(result_data, {})
        self.assertFalse(validation_result.is_valid)
        self.assertEqual(len(validation_result.errors), 1)
        self.assertIn("Configuration error loading profile power", validation_result.errors[0])
        self.assertIn("No credentials", validation_result.errors[0])

    def test_failed_profile_reported_while_other_profile_loads(self) -> None:
        """One failing profile is reported and the other still loads."""
        energy_system = Mock()
        profile1 = Mock(spec=esdl.InfluxDBProfile)
        profile1.field = "power"
        profile1.measurement = "consumption"
        profile2 = Mock(spec=esdl.InfluxDBProfile)
        profile2.field = "flow"
        profile2.measurement = "heat"
        energy_system.eAllContents.return_value = [profile1, profile2]
        time_series = TimeSeries(time_step=3600.0, values=[1.0, 2.0])

        with patch.object(self.loader, "_extract_asset_id", side_effect=["asset_1", "asset_2"]):
            with patch.object(self.loader, "_load_profile_data") as mock_load:
                mock_load.side_effect = [ConnectionError("db down"), time_series]

                result_data, validation_result = self.loader.load_time_series_from_esdl(
                    energy_system
                )

        self.assertEqual(list(result_data.values()), [time_series])
        self.assertFalse(validation_result.is_valid)
        self.assertEqual(len(validation_result.errors), 1)
        self.assertIn("Database connection failed for profile power", validation_result.errors[0])

    def test_get_credentials_for_profile_https_prefix(self) -> None:
        """Test credential extraction with HTTPS prefix in host."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "https://test.example.com"
        profile.port = 443
        profile.database = "test_db"

        # Mock secure credentials method
        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.return_value = self.test_credentials

            # Mock input validator with proper return values
            with patch(
                "kpicalculator.adapters.database_time_series_loader.InputValidator"
            ) as mock_validator:
                mock_validator.validate_database_host.return_value = "test.example.com"
                mock_validator.validate_database_port.return_value = 443
                result = self.loader._get_credentials_for_profile(profile)

        # Should strip https:// prefix (8 characters) and use validated values
        mock_get_secure.assert_called_once_with("test.example.com", 443)
        mock_validator.validate_database_credentials.assert_called()
        self.assertEqual(result, self.test_credentials)

    def test_get_credentials_for_profile_http_prefix(self) -> None:
        """Test credential extraction with HTTP prefix in host."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "http://test.example.com"
        profile.port = 8080

        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.return_value = self.test_credentials

            with patch(
                "kpicalculator.adapters.database_time_series_loader.InputValidator"
            ) as mock_validator:
                mock_validator.validate_database_host.return_value = "test.example.com"
                mock_validator.validate_database_port.return_value = 8080
                self.loader._get_credentials_for_profile(profile)

        # Should strip http:// prefix (7 characters) and use validated values
        mock_get_secure.assert_called_once_with("test.example.com", 8080)

    def test_get_credentials_for_profile_ssl_port_443(self) -> None:
        """Test SSL setting for port 443."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "test.example.com"
        profile.port = 443

        # Create credentials without SSL
        non_ssl_credentials = DatabaseCredentials(
            host="test.example.com",
            port=443,
            username="user",
            password="password123",  # Updated to meet 8-character minimum
            database="db",
            ssl=False,
            verify_ssl=True,
        )

        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.return_value = non_ssl_credentials

            with patch(
                "kpicalculator.adapters.database_time_series_loader.InputValidator"
            ) as mock_validator:
                result = self.loader._get_credentials_for_profile(profile)

        # Should set SSL to True for port 443
        self.assertTrue(result.ssl)
        # Should be called twice - once for original, once for modified
        self.assertEqual(mock_validator.validate_database_credentials.call_count, 2)

    def test_get_credentials_for_profile_credential_error(self) -> None:
        """Test credential profile error handling."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "test.example.com"
        profile.port = 443
        profile.database = "test_db"
        profile.field = "power"
        profile.measurement = "consumption"

        original_error = CredentialError("Original error")

        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.side_effect = original_error

            with self.assertRaises(CredentialError) as context:
                self.loader._get_credentials_for_profile(profile)

        # Should wrap original error with profile context
        error = context.exception
        self.assertIn("Cannot load credentials for InfluxDB profile", str(error))
        self.assertIn("profile_host=test.example.com", str(error))
        self.assertIn("profile_port=443", str(error))
        self.assertIn("profile_field=power", str(error))

    def test_validate_profile_data_success(self) -> None:
        """Test successful profile data validation."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.endDate = datetime(2024, 1, 1, 1, 0)  # End at 1 hour
        profile.startDate = datetime(2024, 1, 1, 0, 0)  # Start at 0 hour
        profile.field = "power"
        profile.measurement = "consumption"

        # Mock time series data - must match profile dates exactly
        time_series_data = Mock()
        time_series_data.end_datetime = datetime(2024, 1, 1, 1, 0)  # Match profile
        time_series_data.start_datetime = datetime(2024, 1, 1, 0, 0)  # Match profile
        time_series_data.profile_data_list = [
            (datetime(2024, 1, 1, 0, 0), 100.0),  # Start time
            (datetime(2024, 1, 1, 1, 0), 200.0),  # End time (1 hour later)
        ]

        # Should not raise any exception
        self.loader._validate_profile_data(profile, time_series_data)

    def test_validate_profile_data_end_date_mismatch(self) -> None:
        """Test profile data validation with end date mismatch."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.endDate = datetime(2024, 1, 2)
        profile.field = "power"

        time_series_data = Mock()
        time_series_data.end_datetime = datetime(2024, 1, 3)  # Different end date

        with self.assertRaises(ValueError) as context:
            self.loader._validate_profile_data(profile, time_series_data)

        self.assertIn("Profile end datetime mismatch", str(context.exception))
        self.assertIn("power", str(context.exception))

    def test_validate_profile_data_invalid_time_resolution(self) -> None:
        """Test profile data validation with invalid time resolution."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.endDate = datetime(2024, 1, 1, 0, 30)  # End at 30 minutes
        profile.startDate = datetime(2024, 1, 1, 0, 0)  # Start at 0
        profile.field = "power"
        profile.measurement = "consumption"

        time_series_data = Mock()
        time_series_data.end_datetime = datetime(2024, 1, 1, 0, 30)
        time_series_data.start_datetime = datetime(2024, 1, 1, 0, 0)
        time_series_data.profile_data_list = [
            (datetime(2024, 1, 1, 0, 0), 100.0),
            (datetime(2024, 1, 1, 0, 30), 200.0),  # 30 minutes later, not 1 hour
        ]

        with self.assertRaises(ValueError) as context:
            self.loader._validate_profile_data(profile, time_series_data)

        self.assertIn("Expected 3600s time resolution", str(context.exception))

    def test_convert_units_power(self) -> None:
        """Test unit conversion for power quantities."""
        df = pd.DataFrame([100.0, 200.0, 150.0])

        profile = Mock(spec=esdl.InfluxDBProfile)
        profile_unit = Mock()
        profile_unit.reference.physicalQuantity = esdl.PhysicalQuantityEnum.POWER
        profile.profileQuantityAndUnit = profile_unit

        with patch(
            "kpicalculator.adapters.database_time_series_loader.convert_to_unit"
        ) as mock_convert:
            mock_convert.side_effect = [150.0, 250.0, 200.0]  # Mock conversion results

            result_df = self.loader._convert_units(df, profile)

        # Should call convert_to_unit for each row
        self.assertEqual(mock_convert.call_count, 3)
        # Results should be the converted values
        expected_values = [150.0, 250.0, 200.0]
        self.assertEqual(result_df.iloc[0, 0], expected_values[0])

    def test_convert_units_energy(self) -> None:
        """Test unit conversion for energy quantities."""
        df = pd.DataFrame([1000.0])

        profile = Mock(spec=esdl.InfluxDBProfile)
        profile_unit = Mock()
        profile_unit.reference.physicalQuantity = esdl.PhysicalQuantityEnum.ENERGY
        profile.profileQuantityAndUnit = profile_unit

        with patch(
            "kpicalculator.adapters.database_time_series_loader.convert_to_unit"
        ) as mock_convert:
            mock_convert.return_value = 1500.0

            self.loader._convert_units(df, profile)

        mock_convert.assert_called_once()

    def test_convert_units_no_reference(self) -> None:
        """Test unit conversion when no reference attribute."""
        df = pd.DataFrame([100.0])

        profile = Mock(spec=esdl.InfluxDBProfile)
        profile_unit = Mock()
        profile_unit.physicalQuantity = esdl.PhysicalQuantityEnum.POWER  # Direct attribute
        del profile_unit.reference  # No reference attribute
        profile.profileQuantityAndUnit = profile_unit

        with patch(
            "kpicalculator.adapters.database_time_series_loader.convert_to_unit"
        ) as mock_convert:
            mock_convert.return_value = 150.0

            self.loader._convert_units(df, profile)

        mock_convert.assert_called_once()

    def test_convert_units_unsupported_quantity(self) -> None:
        """Test unit conversion with unsupported physical quantity."""
        df = pd.DataFrame([100.0])

        profile = Mock(spec=esdl.InfluxDBProfile)
        profile_unit = Mock()
        # Create a mock enum value that's not POWER, ENERGY, or COST
        mock_quantity = Mock()
        mock_quantity.__str__ = Mock(return_value="UNKNOWN_QUANTITY")
        profile_unit.reference.physicalQuantity = mock_quantity
        profile.profileQuantityAndUnit = profile_unit

        # Should log warning and return original DataFrame
        result_df = self.loader._convert_units(df, profile)

        self.assertEqual(result_df.iloc[0, 0], 100.0)  # Original value

    def test_convert_units_exception_handling(self) -> None:
        """Test unit conversion with exception."""
        df = pd.DataFrame([100.0])

        profile = Mock(spec=esdl.InfluxDBProfile)
        profile_unit = Mock()
        profile_unit.reference.physicalQuantity = esdl.PhysicalQuantityEnum.POWER
        profile.profileQuantityAndUnit = profile_unit

        with patch(
            "kpicalculator.adapters.database_time_series_loader.convert_to_unit"
        ) as mock_convert:
            mock_convert.side_effect = Exception("Conversion error")

            result_df = self.loader._convert_units(df, profile)

        # Should return original DataFrame on exception
        self.assertEqual(result_df.iloc[0, 0], 100.0)

    def test_set_credential_manager(self) -> None:
        """Test credential manager setter."""
        new_manager = Mock()

        self.loader.set_credential_manager(new_manager)

        self.assertEqual(self.loader.credential_manager, new_manager)

    @patch("kpicalculator.adapters.database_time_series_loader.time")
    def test_load_time_series_from_esdl_success(self, mock_time) -> None:
        """Test successful ESDL time series loading."""
        # Mock time.time() for performance measurement
        # Use itertools.count() to provide unlimited mock time values
        import itertools

        mock_time.time.side_effect = itertools.count(0.0, 0.05)

        # Create mock energy system with InfluxDB profiles
        energy_system = Mock()
        profile1 = Mock(spec=esdl.InfluxDBProfile)
        profile1.field = "power"
        profile1.measurement = "consumption"
        profile2 = Mock(spec=esdl.InfluxDBProfile)
        profile2.field = "flow"
        profile2.measurement = "heat"

        energy_system.eAllContents.return_value = [
            profile1,
            profile2,
            Mock(),
        ]  # Third is not InfluxDBProfile

        # Mock profile data loading
        time_series1 = TimeSeries(time_step=3600.0, values=[100.0, 200.0])
        time_series2 = TimeSeries(time_step=3600.0, values=[50.0, 75.0])

        with patch.object(self.loader, "_extract_asset_id") as mock_extract:
            mock_extract.side_effect = ["asset_1", "asset_2"]

            with patch.object(self.loader, "_load_profile_data") as mock_load:
                mock_load.side_effect = [time_series1, time_series2]

                result_data, validation_result = self.loader.load_time_series_from_esdl(
                    energy_system
                )

        # Verify results
        self.assertTrue(validation_result.is_valid)
        self.assertEqual(len(result_data), 2)
        # Results now use composite keys: asset_id|field_name
        expected_keys = {
            f"asset_1{COMPOSITE_KEY_SEPARATOR}power",
            f"asset_2{COMPOSITE_KEY_SEPARATOR}flow",
        }
        self.assertEqual(set(result_data.keys()), expected_keys)
        self.assertEqual(result_data[f"asset_1{COMPOSITE_KEY_SEPARATOR}power"], time_series1)
        self.assertEqual(result_data[f"asset_2{COMPOSITE_KEY_SEPARATOR}flow"], time_series2)

        # Verify mock calls
        self.assertEqual(mock_extract.call_count, 2)
        self.assertEqual(mock_load.call_count, 2)

    def test_load_time_series_from_esdl_no_profiles(self) -> None:
        """Test ESDL loading with no database profiles."""
        energy_system = Mock()
        energy_system.eAllContents.return_value = [Mock(), Mock()]  # No database profiles

        result_data, validation_result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertTrue(validation_result.is_valid)
        self.assertEqual(len(result_data), 0)
        self.assertIn("No database profiles found in ESDL file", validation_result.warnings)

    def test_load_time_series_from_esdl_with_errors(self) -> None:
        """Test ESDL loading with profile errors."""
        energy_system = Mock()
        profile1 = Mock(spec=esdl.InfluxDBProfile)
        profile1.field = "power"
        profile2 = Mock(spec=esdl.InfluxDBProfile)
        profile2.field = "flow"

        energy_system.eAllContents.return_value = [profile1, profile2]

        with patch.object(self.loader, "_extract_asset_id") as mock_extract:
            mock_extract.side_effect = ["asset_1", RuntimeError("Extract error")]

            with patch.object(self.loader, "_load_profile_data") as mock_load:
                mock_load.return_value = TimeSeries(time_step=3600.0, values=[100.0])

                result_data, validation_result = self.loader.load_time_series_from_esdl(
                    energy_system
                )

        # Should have one successful load and one error
        self.assertFalse(validation_result.is_valid)
        self.assertEqual(len(result_data), 1)  # One successful
        self.assertEqual(len(validation_result.errors), 1)
        self.assertIn("Extract error", validation_result.errors[0])

    def test_load_time_series_from_esdl_critical_exception(self) -> None:
        """Test ESDL loading with critical exception."""
        energy_system = Mock()
        energy_system.eAllContents.side_effect = RuntimeError("Critical system error")

        result_data, validation_result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(len(result_data), 0)
        self.assertIn("Critical system error", validation_result.errors[0])

    def test_categorize_profile_error_message_format(self) -> None:
        """Test exception categorization helper method message formatting."""
        # Test new error types not covered by existing integration tests
        test_cases = [
            # Connection errors (not tested elsewhere)
            (
                ConnectionError("Connection failed"),
                "Database connection failed for profile test_field: Connection failed",
            ),
            (
                TimeoutError("Request timeout"),
                "Database connection failed for profile test_field: Request timeout",
            ),
            # Data processing errors (not tested elsewhere)
            (
                ValueError("Invalid value"),
                "Data processing error for profile test_field: Invalid value",
            ),
            (
                KeyError("Missing key"),
                "Data processing error for profile test_field: 'Missing key'",
            ),
            (
                AttributeError("Missing attribute"),
                "Data processing error for profile test_field: Missing attribute",
            ),
            # Unexpected errors (not tested elsewhere)
            (
                RuntimeError("Runtime error"),
                "Unexpected error loading profile test_field: Runtime error",
            ),
        ]

        for error, expected_message in test_cases:
            with self.subTest(error_type=type(error).__name__):
                result = self.loader._categorize_profile_error(error, "test_field")
                self.assertEqual(result, expected_message)

    def test_handle_query_error_logging_behavior(self) -> None:
        """Test query error handling helper method logging behavior."""
        # Test that all error types are properly logged (distinct from existing tests)
        test_errors = [
            ConnectionError("Connection failed"),
            TimeoutError("Request timeout"),
            ValueError("Invalid value"),
            RuntimeError("Runtime error"),
        ]

        for error in test_errors:
            with self.subTest(error_type=type(error).__name__):
                # Mock the database logger to verify it gets called
                with patch.object(self.loader.db_logger, "log_query_error") as mock_log:
                    # Should not raise exception (graceful degradation)
                    result = self.loader._handle_query_error(
                        error, "test_measurement", "test_field"
                    )

                    # Should return None for graceful degradation
                    self.assertIsNone(result)

                    # Should log the error with correct parameters
                    mock_log.assert_called_once_with("test_measurement", "test_field", error)


def _make_profile(
    host="influx.example.com",
    port=8086,
    database="db",
    measurement="heat",
    field="field_a",
    start=None,
    end=None,
    filters=None,
    multiplier=1.0,
    asset_id="asset_1",
) -> Mock:
    """Return a minimally-configured InfluxDBProfile mock."""
    p = Mock(spec=esdl.InfluxDBProfile)
    p.host = host
    p.port = port
    p.database = database
    p.measurement = measurement
    p.field = field
    p.startDate = start or datetime(2024, 1, 1, 0)
    p.endDate = end or datetime(2024, 1, 1, 1)
    p.filters = filters
    p.multiplier = multiplier
    # Wire up eContainer so _extract_asset_id returns asset_id
    container = Mock()
    container.energyasset = Mock()
    container.energyasset.id = asset_id
    p.eContainer.return_value = container
    return p


class TestGroupProfilesForBatch(unittest.TestCase):
    """Unit tests for _group_profiles_for_batch."""

    def setUp(self) -> None:
        self.loader = DatabaseTimeSeriesLoader(MockCredentialManager())

    def test_same_measurement_grouped_together(self) -> None:
        """Profiles sharing all batch-key fields land in one group."""
        p1 = _make_profile(field="field_a")
        p2 = _make_profile(field="field_b")

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 1)
        group = next(iter(groups.values()))
        self.assertIn(p1, group)
        self.assertIn(p2, group)

    def test_different_measurements_separate_groups(self) -> None:
        """Profiles with different measurements must not be batched together."""
        p1 = _make_profile(measurement="heat", field="field_a")
        p2 = _make_profile(measurement="power", field="field_b")

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 2)
        all_members = [p for g in groups.values() for p in g]
        self.assertIn(p1, all_members)
        self.assertIn(p2, all_members)
        for group in groups.values():
            self.assertEqual(len(group), 1)

    def test_different_start_dates_separate_groups(self) -> None:
        """Profiles with different date ranges cannot share a query."""
        p1 = _make_profile(field="field_a", start=datetime(2024, 1, 1))
        p2 = _make_profile(field="field_b", start=datetime(2024, 6, 1))

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 2)
        all_members = [p for g in groups.values() for p in g]
        self.assertIn(p1, all_members)
        self.assertIn(p2, all_members)
        for group in groups.values():
            self.assertEqual(len(group), 1)

    def test_none_filters_and_empty_string_normalize_to_same_key(self) -> None:
        """filters=None and filters='' must land in the same batch group."""
        p1 = _make_profile(field="field_a", filters=None)
        p2 = _make_profile(field="field_b", filters="")

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 1)

    def test_different_filters_separate_groups(self) -> None:
        """Profiles with different tag filters cannot share a query."""
        p1 = _make_profile(field="field_a", filters="region='north'")
        p2 = _make_profile(field="field_b", filters="region='south'")

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 2)
        all_members = [p for g in groups.values() for p in g]
        self.assertIn(p1, all_members)
        self.assertIn(p2, all_members)
        for group in groups.values():
            self.assertEqual(len(group), 1)

    def test_missing_filters_attribute_does_not_raise(self) -> None:
        """A profile with no filters attribute at all is handled safely."""
        p1 = _make_profile(field="field_a")
        del p1.filters  # simulate attribute absence

        groups = self.loader._group_profiles_for_batch([p1])

        self.assertEqual(len(groups), 1)

    def test_duplicate_field_in_same_measurement_isolated(self) -> None:
        """Two profiles with the same field on the same measurement must not share a batch."""
        p1 = _make_profile(field="heat_power", asset_id="asset_1")
        p2 = _make_profile(field="heat_power", asset_id="asset_2")  # duplicate field name

        groups = self.loader._group_profiles_for_batch([p1, p2])

        self.assertEqual(len(groups), 2, "Duplicate fields must be isolated into separate groups")
        all_groups = list(groups.values())
        self.assertEqual(len(all_groups[0]), 1)
        self.assertEqual(len(all_groups[1]), 1)
        members = {all_groups[0][0], all_groups[1][0]}
        self.assertEqual(members, {p1, p2})

    def test_duplicate_field_emits_warning(self) -> None:
        """A warning is logged when two profiles share measurement and field."""
        p1 = _make_profile(field="heat_power", asset_id="asset_1")
        p2 = _make_profile(field="heat_power", asset_id="asset_2")

        with patch.object(self.loader.db_logger, "warning") as mock_warn:
            self.loader._group_profiles_for_batch([p1, p2])

        warning_messages = [str(call.args[0]) for call in mock_warn.call_args_list]
        self.assertTrue(
            any("heat_power" in m for m in warning_messages),
            f"Expected duplicate-field warning, got: {warning_messages}",
        )


class TestProcessProfileBatch(unittest.TestCase):
    """Unit tests for _process_profile_batch."""

    _INFLUXDB_PATH = "kpicalculator.adapters.database_time_series_loader.InfluxDBProfileManager"

    def setUp(self) -> None:
        self.credentials = DatabaseCredentials(
            host="influx.example.com",
            port=8086,
            username="user",
            password="password1",
            database="db",
            ssl=False,
            verify_ssl=False,
        )
        self.loader = DatabaseTimeSeriesLoader(
            MockCredentialManager({"influx.example.com: 8086": self.credentials})
        )

    def _make_mock_manager(
        self,
        fields: list[str],
        values_by_field: dict[str, list[float]],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Mock:
        """Build a mock InfluxDBProfileManager with hourly rows from start to end (inclusive)."""
        from datetime import timedelta

        start = start or datetime(2024, 1, 1, 0)
        end = end or datetime(2024, 1, 1, 1)
        manager = Mock()
        manager.profile_header = ["datetime", *fields]
        timestamps = []
        ts = start
        while ts <= end:
            timestamps.append(ts)
            ts += timedelta(hours=1)
        rows = []
        for i, t in enumerate(timestamps):
            row = [t] + [values_by_field[f][i] for f in fields]
            rows.append(row)
        manager.profile_data_list = rows
        manager.start_datetime = start
        manager.end_datetime = end
        return manager

    @patch(_INFLUXDB_PATH)
    def test_single_load_influxdb_call_for_multiple_profiles(self, mock_influx_cls) -> None:
        """The batch path issues exactly one load_influxdb call regardless of profile count."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [10.0, 20.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                time_series_data: dict = {}
                self.loader._process_profile_batch([p1, p2], time_series_data, [])

        mock_manager.load_influxdb.assert_called_once()
        call_kwargs = mock_manager.load_influxdb.call_args
        self.assertCountEqual(call_kwargs.kwargs["fields"], ["field_a", "field_b"])

    @patch(_INFLUXDB_PATH)
    def test_correct_field_values_assigned_to_correct_asset(self, mock_influx_cls) -> None:
        """Each profile gets its own field's column — not swapped or mixed."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [100.0, 200.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                time_series_data: dict = {}
                self.loader._process_profile_batch([p1, p2], time_series_data, [])

        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        key_b = f"asset_2{COMPOSITE_KEY_SEPARATOR}field_b"
        self.assertIn(key_a, time_series_data)
        self.assertIn(key_b, time_series_data)
        self.assertEqual(time_series_data[key_a].values, [1.0, 2.0])
        self.assertEqual(time_series_data[key_b].values, [100.0, 200.0])

    @patch(_INFLUXDB_PATH)
    def test_per_profile_multiplier_applied_independently(self, mock_influx_cls) -> None:
        """A multiplier on one profile does not affect the other profile's values."""
        p1 = _make_profile(field="field_a", asset_id="asset_1", multiplier=2.0)
        p2 = _make_profile(field="field_b", asset_id="asset_2", multiplier=10.0)

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 1.0], "field_b": [1.0, 1.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                time_series_data: dict = {}
                self.loader._process_profile_batch([p1, p2], time_series_data, [])

        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        key_b = f"asset_2{COMPOSITE_KEY_SEPARATOR}field_b"
        self.assertEqual(time_series_data[key_a].values, [2.0, 2.0])
        self.assertEqual(time_series_data[key_b].values, [10.0, 10.0])

    @patch(_INFLUXDB_PATH)
    def test_zero_multiplier_produces_zero_values_with_warning(self, mock_influx_cls) -> None:
        """multiplier=0.0 produces all-zero output and a warning log."""
        p1 = _make_profile(field="field_a", asset_id="asset_1", multiplier=0.0)
        p2 = _make_profile(field="field_b", asset_id="asset_2", multiplier=1.0)

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [5.0, 5.0], "field_b": [3.0, 3.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(self.loader.db_logger, "warning") as mock_warn:
                    time_series_data: dict = {}
                    self.loader._process_profile_batch([p1, p2], time_series_data, [])

        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        key_b = f"asset_2{COMPOSITE_KEY_SEPARATOR}field_b"
        self.assertEqual(time_series_data[key_a].values, [0.0, 0.0])
        self.assertEqual(time_series_data[key_b].values, [3.0, 3.0])
        warning_messages = [str(call.args[0]) for call in mock_warn.call_args_list]
        self.assertTrue(any("multiplier=0.0" in m for m in warning_messages))

    @patch(_INFLUXDB_PATH)
    def test_failed_retry_after_batch_extraction_reports_single_error(
        self, mock_influx_cls
    ) -> None:
        """A profile whose batch extraction and per-profile retry both fail yields one error."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [float("nan"), 20.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        errors: list[str] = []
        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(
                    self.loader, "_load_profile_data", side_effect=ConnectionError("DB down")
                ):
                    time_series_data: dict = {}
                    successful, failed = self.loader._process_profile_batch(
                        [p1, p2], time_series_data, errors
                    )

        self.assertEqual((successful, failed), (1, 1))
        self.assertEqual(list(time_series_data), [f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"])
        self.assertEqual(len(errors), 1)
        self.assertIn("Database connection failed for profile field_b", errors[0])

    @patch(_INFLUXDB_PATH)
    def test_batch_failure_falls_back_to_per_profile(self, mock_influx_cls) -> None:
        """When the batch query raises, every profile is retried individually."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_influx_cls.return_value.load_influxdb.side_effect = ConnectionError("DB down")
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(
                self.loader, "_process_single_profile", return_value=True
            ) as mock_single:
                time_series_data: dict = {}
                successful, failed = self.loader._process_profile_batch(
                    [p1, p2], time_series_data, []
                )

        self.assertEqual(mock_single.call_count, 2)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

    @patch(_INFLUXDB_PATH)
    def test_security_validation_runs_for_every_profile(self, mock_influx_cls) -> None:
        """_get_credentials_for_profile is called for each profile, not just the representative."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")
        p3 = _make_profile(field="field_c", asset_id="asset_3")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b", "field_c"],
            {
                "field_a": [1.0, 1.0],
                "field_b": [2.0, 2.0],
                "field_c": [3.0, 3.0],
            },
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ) as mock_get_creds:
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                self.loader._process_profile_batch([p1, p2, p3], {}, [])

        # Called once for the representative explicitly, then once each for the remaining profiles.
        self.assertEqual(mock_get_creds.call_count, 3)
        validated_profiles = [call.args[0] for call in mock_get_creds.call_args_list]
        self.assertIn(p1, validated_profiles)
        self.assertIn(p2, validated_profiles)
        self.assertIn(p3, validated_profiles)

    @patch(_INFLUXDB_PATH)
    def test_extraction_failure_retries_per_profile_and_succeeds(self, mock_influx_cls) -> None:
        """A profile missing from the batch result is retried per-profile; others are unaffected."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_missing", asset_id="asset_2")  # not in header

        mock_manager = self._make_mock_manager(
            ["field_a"],
            {"field_a": [5.0, 5.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        errors: list = []
        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(
                    self.loader, "_process_single_profile", return_value=True
                ) as mock_single:
                    time_series_data: dict = {}
                    successful, failed = self.loader._process_profile_batch(
                        [p1, p2], time_series_data, errors
                    )

        # p2 extraction failed but retry succeeded — 2 successful, 0 failed, no errors
        mock_single.assert_called_once_with(p2, time_series_data, errors)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(len(errors), 0)
        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        self.assertIn(key_a, time_series_data)
        self.assertEqual(time_series_data[key_a].values, [5.0, 5.0])

    @patch(_INFLUXDB_PATH)
    def test_extraction_failure_retries_per_profile_and_also_fails(self, mock_influx_cls) -> None:
        """When batch extraction and per-profile retry both fail, the profile counts as failed."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_missing", asset_id="asset_2")  # not in header

        mock_manager = self._make_mock_manager(
            ["field_a"],
            {"field_a": [5.0, 5.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        errors: list = []
        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(
                    self.loader,
                    "_process_single_profile",
                    side_effect=lambda _p, _ts, errs: (errs.append("retry failed"), False)[-1],
                ):
                    time_series_data: dict = {}
                    successful, failed = self.loader._process_profile_batch(
                        [p1, p2], time_series_data, errors
                    )

        self.assertEqual(successful, 1)
        self.assertEqual(failed, 1)
        self.assertEqual(len(errors), 1)

    def test_single_profile_delegates_to_process_single_profile(self) -> None:
        """A batch of size 1 delegates directly, avoiding an unnecessary InfluxDB constructor."""
        p = _make_profile(field="field_a", asset_id="asset_1")

        with patch.object(self.loader, "_process_single_profile", return_value=True) as mock_single:
            successful, failed = self.loader._process_profile_batch([p], {}, [])

        mock_single.assert_called_once_with(p, {}, [])
        self.assertEqual(successful, 1)
        self.assertEqual(failed, 0)

    @patch(_INFLUXDB_PATH)
    def test_empty_batch_result_falls_back_to_per_profile(self, mock_influx_cls) -> None:
        """A batch query returning no rows falls back to per-profile loading."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = Mock()
        mock_manager.profile_header = None
        mock_manager.profile_data_list = []
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(
                self.loader, "_process_single_profile", return_value=True
            ) as mock_single:
                successful, failed = self.loader._process_profile_batch([p1, p2], {}, [])

        self.assertEqual(mock_single.call_count, 2)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

    @patch(_INFLUXDB_PATH)
    def test_nan_in_batch_result_triggers_per_profile_retry(self, mock_influx_cls) -> None:
        """NaN values (not just None) in a batch cell trigger the per-profile retry path."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        start, end = datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 1)
        mock_manager = Mock()
        mock_manager.profile_header = ["datetime", "field_a", "field_b"]
        # field_b has float('nan') instead of None for its missing union row
        mock_manager.profile_data_list = [
            [start, 1.0, float("nan")],
            [end, 2.0, float("nan")],
        ]
        mock_manager.start_datetime = start
        mock_manager.end_datetime = end
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(
                    self.loader, "_process_single_profile", return_value=True
                ) as mock_single:
                    time_series_data: dict = {}
                    successful, failed = self.loader._process_profile_batch(
                        [p1, p2], time_series_data, []
                    )

        # p2 hit the NaN guard and was retried per-profile successfully; p1 extracted normally
        mock_single.assert_called_once_with(p2, unittest.mock.ANY, unittest.mock.ANY)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)
        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        self.assertIn(key_a, time_series_data)
        self.assertEqual(time_series_data[key_a].values, [1.0, 2.0])

    @patch(_INFLUXDB_PATH)
    def test_invalid_field_first_does_not_prevent_batching_valid_profiles(
        self, mock_influx_cls
    ) -> None:
        """When the first profile has an empty field, valid profiles still get a batch query."""
        p_bad = _make_profile(field="", asset_id="asset_bad")
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [3.0, 4.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(
                    self.loader, "_process_single_profile", return_value=True
                ) as mock_single:
                    time_series_data: dict = {}
                    successful, failed = self.loader._process_profile_batch(
                        [p_bad, p1, p2], time_series_data, []
                    )

        # p_bad processed per-profile; p1+p2 batched (one load_influxdb call)
        mock_single.assert_called_once_with(p_bad, time_series_data, [])
        mock_manager.load_influxdb.assert_called_once()
        self.assertEqual(successful, 3)
        self.assertEqual(failed, 0)
        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        key_b = f"asset_2{COMPOSITE_KEY_SEPARATOR}field_b"
        self.assertIn(key_a, time_series_data)
        self.assertIn(key_b, time_series_data)

    @patch(f"{_INFLUXDB_PATH.rsplit('.', 1)[0]}.ConnectionSettings")
    @patch(_INFLUXDB_PATH)
    def test_batch_connects_to_the_profile_database(self, mock_influx_cls, mock_settings) -> None:
        """The batch query uses the profile's database, as the single-profile path does."""
        p1 = _make_profile(field="field_a", asset_id="asset_1", database="profile_db")
        p2 = _make_profile(field="field_b", asset_id="asset_2", database="profile_db")

        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [3.0, 4.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []
        other_db = DatabaseCredentials(
            host="influx.example.com",
            port=8086,
            username="user",
            password="password1",
            database="credentials_db",
            ssl=False,
            verify_ssl=False,
        )

        errors: list = []
        time_series_data: dict = {}
        with patch.object(self.loader, "_get_credentials_for_profile", return_value=other_db):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                with patch.object(self.loader, "_process_single_profile") as mock_single:
                    successful, failed = self.loader._process_profile_batch(
                        [p1, p2], time_series_data, errors
                    )

        self.assertEqual(mock_settings.call_args.kwargs["database"], "profile_db")
        mock_single.assert_not_called()
        self.assertEqual((successful, failed, errors), (2, 0, []))

    @patch(_INFLUXDB_PATH)
    def test_non_finite_multiplier_fails_before_any_query(self, mock_influx_cls) -> None:
        """A single Influx profile with a NaN/inf multiplier is recorded once, with no query."""
        for multiplier in (float("nan"), float("inf")):
            with self.subTest(multiplier=multiplier):
                mock_influx_cls.reset_mock()
                profile = _make_profile(field="field_a", asset_id="asset_1", multiplier=multiplier)
                errors: list = []
                with patch.object(
                    self.loader, "_get_credentials_for_profile", return_value=self.credentials
                ):
                    successful, failed = self.loader._process_profile_batch([profile], {}, errors)

                mock_influx_cls.create_esdl_influxdb_profile_manager.assert_not_called()
                self.assertEqual((successful, failed), (0, 1))
                self.assertEqual(len(errors), 1)
                self.assertIn("multiplier must be finite", errors[0])

    def test_profile_without_database_is_rejected_before_any_query(self) -> None:
        for database in (None, ""):
            with self.subTest(database=database):
                profile = _make_profile(database=database)
                with self.assertRaises(CredentialError) as ctx:
                    self.loader._get_credentials_for_profile(profile)
                self.assertIn("no database configured", str(ctx.exception))

    @patch(_INFLUXDB_PATH)
    def test_batch_without_database_falls_back_and_records_one_error_per_profile(
        self, mock_influx_cls
    ) -> None:
        p1 = _make_profile(field="field_a", asset_id="asset_1", database=None)
        p2 = _make_profile(field="field_b", asset_id="asset_2", database=None)
        errors: list = []

        successful, failed = self.loader._process_profile_batch([p1, p2], {}, errors)

        mock_influx_cls.assert_not_called()
        self.assertEqual((successful, failed), (0, 2))
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("no database configured" in e for e in errors))

    @patch(_INFLUXDB_PATH)
    def test_non_numeric_multiplier_is_recorded_without_aborting_the_batch(
        self, mock_influx_cls
    ) -> None:
        """A non-numeric multiplier fails that profile only; the rest of the group still loads."""
        bad = _make_profile(field="field_bad", asset_id="asset_bad", multiplier="abc")
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")
        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [3.0, 4.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        errors: list = []
        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                successful, failed = self.loader._process_profile_batch([bad, p1, p2], {}, errors)

        self.assertEqual((successful, failed), (2, 1))
        self.assertEqual(len(errors), 1)
        self.assertIn("multiplier must be finite", errors[0])

    @patch(_INFLUXDB_PATH)
    def test_non_finite_multiplier_is_not_batched_and_not_retried(self, mock_influx_cls) -> None:
        """In a batch, the bad-multiplier profile fails once; the others share one query."""
        bad = _make_profile(field="field_bad", asset_id="asset_bad", multiplier=float("nan"))
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")
        mock_manager = self._make_mock_manager(
            ["field_a", "field_b"],
            {"field_a": [1.0, 2.0], "field_b": [3.0, 4.0]},
        )
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        errors: list = []
        time_series_data: dict = {}
        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                successful, failed = self.loader._process_profile_batch(
                    [bad, p1, p2], time_series_data, errors
                )

        mock_manager.load_influxdb.assert_called_once()
        self.assertEqual(
            mock_manager.load_influxdb.call_args.kwargs["fields"], ["field_a", "field_b"]
        )
        mock_influx_cls.create_esdl_influxdb_profile_manager.assert_not_called()
        self.assertEqual((successful, failed), (2, 1))
        self.assertEqual(len(errors), 1)
        self.assertIn("multiplier must be finite", errors[0])

    @patch(_INFLUXDB_PATH)
    def test_missing_profile_header_falls_back_to_per_profile(self, mock_influx_cls) -> None:
        """Non-empty profile_data_list with a None header triggers graceful fallback."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        mock_manager = Mock()
        mock_manager.profile_header = None
        mock_manager.profile_data_list = [[datetime(2024, 1, 1), 1.0]]
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(
                self.loader, "_process_single_profile", return_value=True
            ) as mock_single:
                successful, failed = self.loader._process_profile_batch([p1, p2], {}, [])

        self.assertEqual(mock_single.call_count, 2)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)


class TestLoadTimeSeriesFromEsdlBatchIntegration(unittest.TestCase):
    """Integration-level tests verifying batching through load_time_series_from_esdl."""

    _INFLUXDB_PATH = "kpicalculator.adapters.database_time_series_loader.InfluxDBProfileManager"

    def setUp(self) -> None:
        self.credentials = DatabaseCredentials(
            host="influx.example.com",
            port=8086,
            username="user",
            password="password1",
            database="db",
            ssl=False,
            verify_ssl=False,
        )
        self.loader = DatabaseTimeSeriesLoader(
            MockCredentialManager({"influx.example.com: 8086": self.credentials})
        )

    @patch(_INFLUXDB_PATH)
    def test_two_profiles_same_measurement_issue_one_query(self, mock_influx_cls) -> None:
        """End-to-end: two profiles on the same measurement produce exactly one DB query."""
        p1 = _make_profile(field="field_a", asset_id="asset_1")
        p2 = _make_profile(field="field_b", asset_id="asset_2")

        start, end = datetime(2024, 1, 1, 0), datetime(2024, 1, 1, 1)
        mock_manager = Mock()
        mock_manager.profile_header = ["datetime", "field_a", "field_b"]
        mock_manager.profile_data_list = [
            [start, 10.0, 20.0],
            [end, 11.0, 21.0],
        ]
        mock_manager.start_datetime = start
        mock_manager.end_datetime = end
        mock_influx_cls.return_value = mock_manager
        mock_influx_cls._parse_esdl_profile_filters.return_value = []

        energy_system = Mock()
        energy_system.eAllContents.return_value = [p1, p2]

        with patch.object(
            self.loader, "_get_credentials_for_profile", return_value=self.credentials
        ):
            with patch.object(self.loader, "_convert_units", side_effect=lambda df, _: df):
                result_data, validation = self.loader.load_time_series_from_esdl(energy_system)

        mock_manager.load_influxdb.assert_called_once()
        self.assertTrue(validation.is_valid)
        key_a = f"asset_1{COMPOSITE_KEY_SEPARATOR}field_a"
        key_b = f"asset_2{COMPOSITE_KEY_SEPARATOR}field_b"
        self.assertIn(key_a, result_data)
        self.assertIn(key_b, result_data)
        self.assertEqual(result_data[key_a].values, [10.0, 11.0])
        self.assertEqual(result_data[key_b].values, [20.0, 21.0])

    @patch(_INFLUXDB_PATH)
    def test_profiles_on_different_measurements_produce_two_batch_calls(
        self, _mock_influx_cls
    ) -> None:
        """Profiles on different measurements land in separate groups and issue two batch calls."""
        p1 = _make_profile(measurement="heat", field="field_a", asset_id="asset_1")
        p2 = _make_profile(measurement="power", field="field_b", asset_id="asset_2")

        energy_system = Mock()
        energy_system.eAllContents.return_value = [p1, p2]

        with patch.object(
            self.loader, "_process_profile_batch", wraps=self.loader._process_profile_batch
        ) as mock_batch:
            with patch.object(self.loader, "_process_single_profile", return_value=True):
                self.loader.load_time_series_from_esdl(energy_system)

        self.assertEqual(mock_batch.call_count, 2)
        batch_inputs = [call.args[0] for call in mock_batch.call_args_list]
        self.assertIn([p1], batch_inputs)
        self.assertIn([p2], batch_inputs)


# --------------------------------------------------------------------------------------
# DataTableProfile (PostgreSQL / database-configured) loading
# --------------------------------------------------------------------------------------

_LOADER_MODULE = "kpicalculator.adapters.database_time_series_loader"
_READ_PATH = f"{_LOADER_MODULE}.load_profile_data_and_header"
_CLOSE_PATH = f"{_LOADER_MODULE}.close_db_connections"
_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_HOUR = timedelta(hours=1)
_PG_HOST = "pg.example.com"
_PG_PORT = 5432
_PG_KEY = f"{_PG_HOST}:{_PG_PORT}"
_HEADER = ["datetime", "HeatIn.Q"]


def _table_rows(values: list) -> list:
    """Hourly [datetime, value] rows starting at 2024-01-01 UTC."""
    return [[_T0 + i * _HOUR, v] for i, v in enumerate(values)]


def _table_profile(
    column: str | None = "HeatIn.Q",
    table: str = "tbl",
    host: str | None = _PG_HOST,
    port: int | None = _PG_PORT,
    configuration: object = "default",
    **kwargs: object,
) -> esdl.DataTableProfile:
    """Return a real DataTableProfile; configuration="default" attaches a Postgres config."""
    profile = esdl.DataTableProfile(tableName=table, columnName=column, **kwargs)
    if configuration == "default":
        profile.configuration = esdl.DatabaseConfiguration(
            id="cfg1", host=host, port=port, type=esdl.DatabaseTypeEnum.POSTGRESQL
        )
    else:
        profile.configuration = configuration
    return profile


def _energy_system(profiles: list[tuple[str, object]]) -> esdl.EnergySystem:
    """Real EnergySystem with one HeatingDemand (id) per (id, profile) pair."""
    energy_system = esdl.EnergySystem(id="es1")
    instance = esdl.Instance(id="inst1")
    energy_system.instance.append(instance)
    area = esdl.Area(id="area1")
    instance.area = area
    for asset_id, profile in profiles:
        demand = esdl.HeatingDemand(id=asset_id)
        port = esdl.InPort(id=f"{asset_id}_port")
        demand.port.append(port)
        port.profile.append(profile)
        area.asset.append(demand)
    return energy_system


def _pg_credentials(**overrides: object) -> DatabaseCredentials:
    values = {
        "host": _PG_HOST,
        "port": _PG_PORT,
        "username": "pg_user",
        "password": "pg_password",
        "database": "energy_profiles",
    }
    values.update(overrides)
    return DatabaseCredentials(**values)  # type: ignore[arg-type]


class _DataTableTestBase(unittest.TestCase):
    """Common fixtures: loader with Postgres credentials, patched read, isolated registry."""

    def setUp(self) -> None:
        self._saved_credentials = dict(Credentials.credentials_dict)
        Credentials.credentials_dict.pop(_PG_KEY, None)
        self.loader = DatabaseTimeSeriesLoader(
            MockCredentialManager({f"{_PG_HOST}: {_PG_PORT}": _pg_credentials()})
        )
        read_patcher = patch(_READ_PATH)
        close_patcher = patch(_CLOSE_PATH)
        self.mock_read = read_patcher.start()
        self.mock_close = close_patcher.start()
        self.addCleanup(read_patcher.stop)
        self.addCleanup(close_patcher.stop)
        self.mock_read.return_value = (_table_rows([1.0, 2.0, 3.0]), _HEADER)
        warning_patcher = patch.object(self.loader.db_logger, "warning")
        self.mock_warning = warning_patcher.start()
        self.addCleanup(warning_patcher.stop)

    def tearDown(self) -> None:
        Credentials.credentials_dict.clear()
        Credentials.credentials_dict.update(self._saved_credentials)

    def load(self, *profiles: object) -> tuple[dict, object]:
        """Load profiles, each on its own asset (asset1, asset2, ...)."""
        pairs = [(f"asset{i + 1}", p) for i, p in enumerate(profiles)]
        return self.loader.load_time_series_from_esdl(_energy_system(pairs))

    def warning_texts(self) -> list[str]:
        return [str(c.args[0]) for c in self.mock_warning.call_args_list]


class TestDataTableProfileLoading(_DataTableTestBase):
    """Happy path and read parameters."""

    KEY = f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"

    def test_loads_series_under_composite_key(self) -> None:
        data, result = self.load(_table_profile())

        self.assertTrue(result.is_valid)
        self.assertEqual(list(data), [self.KEY])
        self.assertEqual(data[self.KEY].values, [1.0, 2.0, 3.0])
        self.assertEqual(data[self.KEY].time_step, 3600.0)

    def test_read_called_without_cache_or_multiplier_and_connection_kept_open(self) -> None:
        profile = _table_profile()
        self.load(profile)

        self.mock_read.assert_called_once_with(
            profile,
            enable_cache=False,
            apply_multiplier=False,
            close_connection_after_load=False,
        )

    def test_postgres_only_esdl_does_not_report_no_profiles(self) -> None:
        data, result = self.load(_table_profile())

        self.assertEqual(len(data), 1)
        self.assertEqual(result.warnings, [])

    def test_influxdb_typed_database_configuration_is_read(self) -> None:
        profile = _table_profile()
        profile.configuration.type = esdl.DatabaseTypeEnum.INFLUXDB
        profile.configuration.database = "energy"
        data, result = self.load(profile)

        self.assertTrue(result.is_valid)
        self.assertEqual(list(data), [self.KEY])
        self.assertEqual(data[self.KEY].values, [1.0, 2.0, 3.0])
        self.mock_read.assert_called_once()

    def test_influxdb_typed_configuration_without_database_reported_before_read(self) -> None:
        profile = _table_profile()
        profile.configuration.type = esdl.DatabaseTypeEnum.INFLUXDB
        data, result = self.load(profile)

        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertIn("INFLUXDB but names no database", result.errors[0])
        self.mock_read.assert_not_called()

    def test_two_columns_on_one_asset_both_load(self) -> None:
        energy_system = _energy_system([("asset1", _table_profile(column="A"))])
        port = next(p for p in energy_system.eAllContents() if isinstance(p, esdl.InPort))
        port.profile.append(_table_profile(column="B"))
        data, result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(
            sorted(data),
            [f"asset1{COMPOSITE_KEY_SEPARATOR}A", f"asset1{COMPOSITE_KEY_SEPARATOR}B"],
        )

    def test_decimal_values_coerced_to_float(self) -> None:
        self.mock_read.return_value = (_table_rows([Decimal("1.5"), Decimal("2.5")]), _HEADER)
        data, result = self.load(_table_profile())

        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(data[self.KEY].values, [1.5, 2.5])
        self.assertTrue(all(type(v) is float for v in data[self.KEY].values))

    def test_unordered_rows_are_sorted(self) -> None:
        rows = _table_rows([1.0, 2.0, 3.0])
        self.mock_read.return_value = ([rows[2], rows[0], rows[1]], _HEADER)
        data, _ = self.load(_table_profile())

        self.assertEqual(data[self.KEY].values, [1.0, 2.0, 3.0])

    def test_naive_and_aware_timestamps_give_same_series(self) -> None:
        frames: list[pd.DataFrame] = []
        original = self.loader._rows_to_dataframe

        def capture(rows: object, col_index: int) -> pd.DataFrame:
            df = original(rows, col_index)  # type: ignore[arg-type]
            frames.append(df)
            return df

        naive_rows = [[datetime(2024, 1, 1, i), float(i)] for i in range(3)]
        plus_two = timezone(timedelta(hours=2))
        aware_rows = [[datetime(2024, 1, 1, i + 2, tzinfo=plus_two), float(i)] for i in range(3)]
        with patch.object(self.loader, "_rows_to_dataframe", side_effect=capture):
            self.mock_read.return_value = (naive_rows, _HEADER)
            naive_data, naive_result = self.load(_table_profile())
            self.mock_read.return_value = (aware_rows, _HEADER)
            aware_data, aware_result = self.load(_table_profile())

        self.assertTrue(naive_result.is_valid and aware_result.is_valid)
        self.assertEqual(naive_data[self.KEY].values, aware_data[self.KEY].values)
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].index.equals(frames[1].index))
        for frame in frames:
            self.assertEqual(str(frame.index.tz), "UTC")
            self.assertEqual(frame.index[0], pd.Timestamp("2024-01-01", tz="UTC"))

    def test_asset_id_falls_back_to_table_name_for_orphan_profile(self) -> None:
        profile = _table_profile(table="orphan_table")
        self.assertEqual(self.loader._extract_asset_id(profile), "orphan_table")

    def test_asset_id_fallback_for_influx_profile_unchanged(self) -> None:
        profile = esdl.InfluxDBProfile(measurement="orphan_measurement", field="f")
        self.assertEqual(self.loader._extract_asset_id(profile), "orphan_measurement")


class TestDataTableProfileSkippedAndInvalid(_DataTableTestBase):
    """Ineligible profiles and per-profile validation failures."""

    def test_missing_configuration_reported(self) -> None:
        data, result = self.load(_table_profile(configuration=None))

        self.assertFalse(result.is_valid)
        self.assertEqual(data, {})
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Configuration error loading profile HeatIn.Q", result.errors[0])
        self.assertIn("asset1", result.errors[0])
        self.assertIn(
            "no DatabaseConfiguration in EnergySystemInformation.dataconfigurations",
            result.errors[0],
        )
        self.mock_read.assert_not_called()

    def test_file_configuration_skipped_with_single_counted_warning(self) -> None:
        file_profile = _table_profile(configuration=esdl.FileConfiguration(uri="x.csv"))
        output_profile = _table_profile(profileType=esdl.ProfileTypeEnum.OUTPUT, column="out")
        output_profile2 = _table_profile(profileType=esdl.ProfileTypeEnum.OUTPUT, column="out2")
        data, result = self.load(file_profile, output_profile, output_profile2)

        self.assertEqual(data, {})
        self.assertEqual(result.warnings, ["No database profiles found in ESDL file"])
        skipped = [w for w in self.warning_texts() if w.startswith("Skipped")]
        self.assertEqual(len(skipped), 1)
        self.assertIn("Skipped 3 DataTableProfile(s)", skipped[0])
        self.mock_read.assert_not_called()

    def test_skipped_profiles_do_not_block_eligible_ones(self) -> None:
        output_profile = _table_profile(profileType=esdl.ProfileTypeEnum.OUTPUT, column="out")
        data, result = self.load(output_profile, _table_profile())

        self.assertTrue(result.is_valid)
        self.assertEqual(list(data), [f"asset2{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"])
        skipped = [w for w in self.warning_texts() if w.startswith("Skipped")]
        self.assertEqual(len(skipped), 1)
        self.assertIn("Skipped 1 DataTableProfile(s)", skipped[0])
        self.mock_read.assert_called_once()

    def test_no_skip_warning_when_nothing_skipped(self) -> None:
        self.load(_table_profile())
        self.assertEqual([w for w in self.warning_texts() if w.startswith("Skipped")], [])

    def test_missing_host_reported(self) -> None:
        data, result = self.load(_table_profile(host=None))

        self.assertEqual(data, {})
        self.assertIn("must define both host and port", result.errors[0])
        self.mock_read.assert_not_called()

    def test_missing_port_reported(self) -> None:
        data, result = self.load(_table_profile(port=None))

        self.assertEqual(data, {})
        self.assertIn("must define both host and port", result.errors[0])
        self.mock_read.assert_not_called()

    def test_unset_port_reported_not_defaulted(self) -> None:
        data, result = self.load(_table_profile(port=0))

        self.assertEqual(data, {})
        self.assertIn("must define both host and port", result.errors[0])
        self.mock_read.assert_not_called()

    def test_invalid_host_reported_before_credential_lookup(self) -> None:
        spy = Mock(wraps=self.loader.credential_manager)
        self.loader.set_credential_manager(spy)
        data, result = self.load(_table_profile(host="bad host!"))

        self.assertEqual(data, {})
        self.assertIn("Configuration error loading profile", result.errors[0])
        self.assertIn("Invalid hostname or IP address format", result.errors[0])
        self.assertNotIn("No credentials found", result.errors[0])
        spy.get_database_credentials.assert_not_called()
        self.mock_read.assert_not_called()

    def test_localhost_rejected_outside_development_mode(self) -> None:
        with patch.object(InputValidator, "_is_development_mode", return_value=False):
            data, result = self.load(_table_profile(host="localhost"))

        self.assertEqual(data, {})
        self.assertIn("Localhost access is disallowed", result.errors[0])
        self.mock_read.assert_not_called()

    def test_missing_column_name_reported_with_placeholder(self) -> None:
        data, result = self.load(_table_profile(column=None))

        self.assertEqual(data, {})
        self.assertIn("Configuration error loading profile ?", result.errors[0])
        self.assertIn("no columnName", result.errors[0])
        self.mock_read.assert_not_called()

    def test_unparsable_filter_reported(self) -> None:
        data, result = self.load(_table_profile(filter="no key value pairs here"))

        self.assertEqual(data, {})
        self.assertIn("cannot be parsed", result.errors[0])
        self.mock_read.assert_not_called()

    def test_parsable_filter_is_read(self) -> None:
        filter_text = "\"assetId\"='abc'"
        data, result = self.load(_table_profile(filter=filter_text))

        self.assertTrue(result.is_valid)
        self.assertEqual(len(data), 1)
        self.mock_read.assert_called_once()
        self.assertEqual(self.mock_read.call_args.args[0].filter, filter_text)

    def test_one_bad_profile_does_not_block_a_good_one(self) -> None:
        data, result = self.load(_table_profile(configuration=None), _table_profile())

        self.assertFalse(result.is_valid)
        self.assertEqual(list(data), [f"asset2{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("no DatabaseConfiguration", result.errors[0])


class TestDataTableProfileCredentials(_DataTableTestBase):
    """Credential resolution, registration and restore."""

    def test_missing_credential_reported(self) -> None:
        self.loader.set_credential_manager(MockCredentialManager({}))
        data, result = self.load(_table_profile())

        self.assertEqual(data, {})
        self.assertIn("Configuration error loading profile HeatIn.Q", result.errors[0])
        self.assertIn("No credentials found", result.errors[0])
        self.mock_read.assert_not_called()

    def test_empty_or_missing_username_or_password_reported(self) -> None:
        missing_user_msg = "Database username cannot be empty"
        cases = {
            "none username": (_pg_credentials(username=None), missing_user_msg),
            "empty username": (
                DatabaseCredentials.model_construct(
                    **{**_pg_credentials().model_dump(), "username": ""}
                ),
                missing_user_msg,
            ),
            "none password": (_pg_credentials(password=None), "Database password cannot be empty"),
            "empty password": (
                DatabaseCredentials.model_construct(
                    **{**_pg_credentials().model_dump(), "password": ""}
                ),
                "Database password cannot be empty",
            ),
            "7-char password": (
                DatabaseCredentials.model_construct(
                    **{**_pg_credentials().model_dump(), "password": "a" * 7}
                ),
                "Database password too short",
            ),
        }
        for name, (credentials, message) in cases.items():
            with self.subTest(case=name):
                self.loader.set_credential_manager(
                    MockCredentialManager({f"{_PG_HOST}: {_PG_PORT}": credentials})
                )
                data, result = self.load(_table_profile())

                self.assertEqual(data, {})
                self.assertIn("Configuration error", result.errors[0])
                self.assertIn(message, result.errors[0])
                self.mock_read.assert_not_called()

    def test_registry_clean_across_ok_fail_ok_sequence(self) -> None:
        previous = Credential("old_user", "old_password")
        Credentials.credentials_dict[_PG_KEY] = previous
        ok = (_table_rows([1.0, 2.0]), _HEADER)
        self.mock_read.side_effect = [ok, ConnectionError("db down"), ok]
        data, result = self.load(_table_profile(), _table_profile(), _table_profile())

        self.assertEqual(len(result.errors), 1)
        self.assertIn("Database connection failed for profile HeatIn.Q", result.errors[0])
        self.assertIn("db down", result.errors[0])
        self.assertEqual(
            sorted(data),
            [
                f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q",
                f"asset3{COMPOSITE_KEY_SEPARATOR}HeatIn.Q",
            ],
        )
        self.assertIs(Credentials.credentials_dict[_PG_KEY], previous)

    def test_each_target_reads_with_its_own_credential(self) -> None:
        second_host = "pg2.example.com"
        self.loader.set_credential_manager(
            MockCredentialManager(
                {
                    f"{_PG_HOST}: {_PG_PORT}": _pg_credentials(username="u1"),
                    f"{second_host}: {_PG_PORT}": _pg_credentials(
                        host=second_host, username="u2", password="another_password"
                    ),
                }
            )
        )
        seen: list = []

        def fake_read(profile: object, *_args: object, **_kwargs: object) -> tuple:
            registered = {
                key: cred.username
                for key, cred in Credentials.credentials_dict.items()
                if key.startswith("pg")
            }
            seen.append((profile.configuration.host, registered))  # type: ignore[attr-defined]
            return _table_rows([1.0, 2.0]), _HEADER

        self.mock_read.side_effect = fake_read
        _, result = self.load(_table_profile(), _table_profile(host=second_host))

        self.assertEqual(result.errors, [])
        self.assertEqual(
            seen,
            [
                (_PG_HOST, {_PG_KEY: "u1"}),
                (second_host, {f"{second_host}:{_PG_PORT}": "u2"}),
            ],
        )
        self.assertEqual([key for key in Credentials.credentials_dict if key.startswith("pg")], [])

    def test_credential_registered_under_host_port_at_read_time_and_removed_after(self) -> None:
        seen: list = []

        def fake_read(*_args: object, **_kwargs: object) -> tuple:
            seen.append(Credentials.credentials_dict.get(_PG_KEY))
            return _table_rows([1.0, 2.0]), _HEADER

        self.mock_read.side_effect = fake_read
        self.load(_table_profile())

        self.assertEqual(seen, [Credential("pg_user", "pg_password")])
        self.assertNotIn(_PG_KEY, Credentials.credentials_dict)

    def test_credential_removed_after_failed_read(self) -> None:
        self.mock_read.side_effect = ConnectionError("db down")
        _, result = self.load(_table_profile())

        self.assertFalse(result.is_valid)
        self.assertNotIn(_PG_KEY, Credentials.credentials_dict)

    def test_prior_credential_restored_after_success(self) -> None:
        previous = Credential("old_user", "old_password")
        Credentials.credentials_dict[_PG_KEY] = previous
        self.load(_table_profile())

        self.assertIs(Credentials.credentials_dict[_PG_KEY], previous)

    def test_prior_credential_restored_after_failed_read(self) -> None:
        previous = Credential("old_user", "old_password")
        Credentials.credentials_dict[_PG_KEY] = previous
        self.mock_read.side_effect = RuntimeError("boom")
        self.load(_table_profile())

        self.assertIs(Credentials.credentials_dict[_PG_KEY], previous)

    def test_other_registry_entries_untouched(self) -> None:
        other = Credential("other_user", "other_password")
        Credentials.credentials_dict["other.example.com"] = other
        self.load(_table_profile())

        self.assertIs(Credentials.credentials_dict["other.example.com"], other)


class TestDataTableProfileConnections(_DataTableTestBase):
    """Read failures and connection cleanup."""

    def test_connections_closed_once_after_success(self) -> None:
        self.load(_table_profile(), _table_profile(column="other"))
        self.mock_close.assert_called_once_with()

    def test_connections_closed_once_after_failed_read(self) -> None:
        self.mock_read.side_effect = ConnectionError("db down")
        _, result = self.load(_table_profile())

        self.mock_close.assert_called_once_with()
        self.assertIn("Database connection failed for profile HeatIn.Q", result.errors[0])

    def test_connections_closed_when_loading_raises_unexpectedly(self) -> None:
        with patch.object(
            self.loader, "_process_data_table_profile", side_effect=RuntimeError("unexpected")
        ):
            data, result = self.load(_table_profile())

        self.mock_close.assert_called_once_with()
        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertIn("Failed to process database profiles: unexpected", result.errors[0])

    def test_close_failure_keeps_loaded_data_but_marks_result_invalid(self) -> None:
        # Closing connections failing after a successful load keeps the data and
        # reports the failure as the only error.
        self.mock_close.side_effect = RuntimeError("close boom")
        data, result = self.load(_table_profile())

        self.assertEqual(list(data), [f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"])
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["Failed to process database profiles: close boom"])

    def test_all_invalid_profiles_each_reported_and_close_called_once(self) -> None:
        data, result = self.load(
            _table_profile(configuration=None),
            _table_profile(host=None),
            _table_profile(column=None),
        )

        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 3)
        self.assertIn("no DatabaseConfiguration", result.errors[0])
        self.assertIn("must define both host and port", result.errors[1])
        self.assertIn("no columnName", result.errors[2])
        self.assertNotIn("No database profiles found in ESDL file", result.warnings)
        self.mock_close.assert_called_once_with()
        self.mock_read.assert_not_called()

    def test_connections_not_closed_when_nothing_to_load(self) -> None:
        self.load(_table_profile(configuration=esdl.FileConfiguration(uri="x.csv")))
        self.mock_close.assert_not_called()

    def test_read_failure_reported_as_data_processing_error_with_datetime_column_passed(
        self,
    ) -> None:
        self.mock_read.side_effect = ValueError("'ts' is not in list")
        data, result = self.load(_table_profile(datetimeColumnName="ts"))

        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertIn("Data processing error for profile HeatIn.Q", result.errors[0])
        self.assertIn("'ts' is not in list", result.errors[0])

    def test_unexpected_read_exception_categorised_as_unexpected(self) -> None:
        self.mock_read.side_effect = RuntimeError("PostgreSQL connection not established")
        _, result = self.load(_table_profile())

        self.assertIn("Unexpected error loading profile HeatIn.Q", result.errors[0])

    def test_read_failure_of_one_profile_keeps_others(self) -> None:
        self.mock_read.side_effect = [
            ConnectionError("db down"),
            (_table_rows([1.0, 2.0]), _HEADER),
        ]
        data, result = self.load(_table_profile(), _table_profile())

        self.assertEqual(list(data), [f"asset2{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Database connection failed for profile HeatIn.Q", result.errors[0])
        self.assertIn("db down", result.errors[0])

    def test_connections_closed_and_registry_restored_on_keyboard_interrupt(self) -> None:
        previous = Credential("old_user", "old_password")
        Credentials.credentials_dict[_PG_KEY] = previous
        self.mock_read.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.load(_table_profile())

        self.mock_close.assert_called_once_with()
        self.assertIs(Credentials.credentials_dict[_PG_KEY], previous)


def _lock_held_by_another_thread() -> bool:
    """Probe DATABASE_READ_LOCK from a separate thread (an RLock is re-entrant per thread)."""
    acquired: list[bool] = []

    def probe() -> None:
        got = DATABASE_READ_LOCK.acquire(blocking=False)
        if got:
            DATABASE_READ_LOCK.release()
        acquired.append(got)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return not acquired[0]


class TestDatabaseReadLock(_DataTableTestBase):
    """Loads in one process are serialised on pyESDL's shared state."""

    def test_lock_held_while_profiles_load_and_connections_close(self) -> None:
        held: list[bool] = []

        def read(*_args: object, **_kwargs: object) -> tuple[list, list]:
            held.append(_lock_held_by_another_thread())
            return _table_rows([1.0, 2.0, 3.0]), _HEADER

        self.mock_read.side_effect = read
        self.mock_close.side_effect = lambda: held.append(_lock_held_by_another_thread())

        self.load(_table_profile())

        self.assertEqual(held, [True, True])
        self.assertFalse(_lock_held_by_another_thread())

    def test_lock_not_held_during_influx_batches(self) -> None:
        held: list[bool] = []

        def batch(*_args: object, **_kwargs: object) -> tuple[int, int]:
            held.append(_lock_held_by_another_thread())
            return 1, 0

        with (
            patch.object(self.loader, "_group_profiles_for_batch", return_value={"k": [1]}),
            patch.object(self.loader, "_process_profile_batch", side_effect=batch),
        ):
            self.loader._load_database_profiles([Mock()], [], {}, [])

        self.assertEqual(held, [False])


class TestDataTableProfileReshapeErrors(_DataTableTestBase):
    """Bad data returned by the read is reported, never loaded."""

    def test_malformed_read_results_reported_as_data_processing_errors(self) -> None:
        rows = _table_rows([1.0, 2.0])
        cases = {
            "null value": (_table_rows([1.0, None, 3.0]), _HEADER),
            "multi-column header": ([[_T0, 1.0, 2.0]], ["datetime", "a", "b"]),
            "empty rows": ([], _HEADER),
            "no result": (None, None),
            "duplicate timestamps": ([rows[0], rows[0], rows[1]], _HEADER),
            "non-hourly spacing": ([[_T0, 1.0], [_T0 + timedelta(minutes=15), 2.0]], _HEADER),
        }
        for name, read_result in cases.items():
            with self.subTest(case=name):
                self.mock_read.return_value = read_result
                data, result = self.load(_table_profile())

                self.assertEqual(data, {})
                self.assertFalse(result.is_valid)
                self.assertEqual(len(result.errors), 1)
                self.assertTrue(
                    result.errors[0].startswith("Data processing error for profile HeatIn.Q"),
                    result.errors[0],
                )

    def test_infinite_value_with_zero_multiplier_rejected(self) -> None:
        # inf * 0.0 is NaN, which passes the range comparison, so the value must be
        # rejected before the multiplier is applied.
        self.mock_read.return_value = (_table_rows([1.0, float("inf")]), _HEADER)
        data, result = self.load(_table_profile(multiplier=0.0))

        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertIn("NULL/NaN/infinite", result.errors[0])


class TestDataTableProfileMultiplierAndUnits(_DataTableTestBase):
    """Multiplier and unit handling."""

    KEY = f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"

    def test_multiplier_applied_exactly_once(self) -> None:
        data, _ = self.load(_table_profile(multiplier=2.0))
        self.assertEqual(data[self.KEY].values, [2.0, 4.0, 6.0])

    def test_none_multiplier_treated_as_one(self) -> None:
        profile = _table_profile()
        profile.multiplier = None
        data, result = self.load(profile)

        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(data[self.KEY].values, [1.0, 2.0, 3.0])

    def test_non_finite_multiplier_rejected(self) -> None:
        for multiplier in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(multiplier=multiplier):
                data, result = self.load(_table_profile(multiplier=multiplier))

                self.assertEqual(data, {})
                self.assertFalse(result.is_valid)
                self.assertIn("multiplier must be finite", result.errors[0])
                self.mock_read.assert_not_called()

    def test_negative_multiplier_applied(self) -> None:
        data, _ = self.load(_table_profile(multiplier=-1.0))
        self.assertEqual(data[self.KEY].values, [-1.0, -2.0, -3.0])

    def test_zero_multiplier_warns_and_zeroes_values(self) -> None:
        data, _ = self.load(_table_profile(multiplier=0.0))

        self.assertEqual(data[self.KEY].values, [0.0, 0.0, 0.0])
        zero_warnings = [w for w in self.warning_texts() if "multiplier=0.0" in w]
        self.assertEqual(len(zero_warnings), 1)
        self.assertIn("tbl.HeatIn.Q", zero_warnings[0])

    def test_missing_unit_warns_once_and_does_not_crash(self) -> None:
        data, result = self.load(_table_profile())

        self.assertTrue(result.is_valid)
        self.assertEqual(len(data), 1)
        no_unit = [w for w in self.warning_texts() if "has no unit" in w]
        self.assertEqual(len(no_unit), 1)
        self.assertIn("tbl.HeatIn.Q", no_unit[0])

    def test_unit_conversion_applied_when_unit_present(self) -> None:
        unit = esdl.QuantityAndUnitType(
            physicalQuantity=esdl.PhysicalQuantityEnum.POWER,
            unit=esdl.UnitEnum.WATT,
            multiplier=esdl.MultiplierEnum.MEGA,
        )
        data, result = self.load(_table_profile(profileQuantityAndUnit=unit))

        self.assertTrue(result.is_valid, result.errors)
        self.assertEqual(data[self.KEY].values, [1e6, 2e6, 3e6])
        self.assertEqual([w for w in self.warning_texts() if "has no unit" in w], [])

    def test_unit_conversion_and_multiplier_both_applied(self) -> None:
        unit = esdl.QuantityAndUnitType(
            physicalQuantity=esdl.PhysicalQuantityEnum.POWER,
            unit=esdl.UnitEnum.WATT,
            multiplier=esdl.MultiplierEnum.KILO,
        )
        data, _ = self.load(_table_profile(profileQuantityAndUnit=unit, multiplier=2.0))

        self.assertEqual(data[self.KEY].values, [2000.0, 4000.0, 6000.0])

    def test_influx_zero_multiplier_warning_text_unchanged(self) -> None:
        profile = _make_profile(measurement="heat", field="field_a", multiplier=0.0)
        df = pd.DataFrame({0: [1.0, 2.0]})

        self.loader._apply_multiplier(df, profile)

        self.assertIn(
            "Profile 'heat.field_a' has multiplier=0.0 — all output values will be zero",
            self.warning_texts(),
        )


class TestDataTableProfileMergeWithInflux(_DataTableTestBase):
    """Influx and DataTable profiles in one ESDL."""

    def _influx_profile(self) -> esdl.InfluxDBProfile:
        return esdl.InfluxDBProfile(
            host="influx.example.com", port=8086, database="db", measurement="heat", field="power"
        )

    def _fake_influx_load(self, key: str, values: list[float]) -> object:
        def fake(
            _profile: object, time_series_data: dict[str, TimeSeries], _errors: list[str]
        ) -> bool:
            time_series_data[key] = TimeSeries(time_step=3600.0, values=values)
            return True

        return fake

    def test_influx_and_data_table_results_merged(self) -> None:
        influx_key = f"asset1{COMPOSITE_KEY_SEPARATOR}power"
        with patch.object(
            self.loader,
            "_process_single_profile",
            side_effect=self._fake_influx_load(influx_key, [9.0]),
        ) as mock_single:
            data, result = self.load(self._influx_profile(), _table_profile())

        self.assertTrue(result.is_valid)
        mock_single.assert_called_once()
        self.assertEqual(set(data), {influx_key, f"asset2{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"})
        self.assertEqual(data[influx_key].values, [9.0])
        self.mock_close.assert_called_once_with()

    def test_influx_plus_output_only_data_table_skips_without_no_profiles_warning(self) -> None:
        influx_key = f"asset1{COMPOSITE_KEY_SEPARATOR}power"
        output_profile = _table_profile(profileType=esdl.ProfileTypeEnum.OUTPUT, column="out")
        with patch.object(
            self.loader,
            "_process_single_profile",
            side_effect=self._fake_influx_load(influx_key, [9.0]),
        ):
            data, result = self.load(self._influx_profile(), output_profile)

        self.assertEqual(list(data), [influx_key])
        self.assertEqual(result.warnings, [])
        skipped = [w for w in self.warning_texts() if w.startswith("Skipped")]
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped[0].startswith("Skipped 1"))
        self.mock_read.assert_not_called()

    def test_influx_only_esdl_does_not_touch_data_table_read(self) -> None:
        influx_key = f"asset1{COMPOSITE_KEY_SEPARATOR}power"
        with patch.object(
            self.loader,
            "_process_single_profile",
            side_effect=self._fake_influx_load(influx_key, [9.0]),
        ):
            data, _ = self.load(self._influx_profile())

        self.assertEqual(list(data), [influx_key])
        self.mock_read.assert_not_called()
        self.mock_close.assert_called_once_with()

    def test_key_collision_with_influx_keeps_first_and_reports_error(self) -> None:
        # Influx profile on asset1 with field "HeatIn.Q" and a DataTable profile on the same
        # asset with the same column: the Influx entry (loaded first) wins.
        key = f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"
        energy_system = _energy_system([("asset1", self._influx_profile())])
        port = next(p for p in energy_system.eAllContents() if isinstance(p, esdl.InPort))
        port.profile.append(_table_profile())
        with patch.object(
            self.loader,
            "_process_single_profile",
            side_effect=self._fake_influx_load(key, [9.0]),
        ):
            data, result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertEqual(data[key].values, [9.0])
        self.assertFalse(result.is_valid)
        self.assertIn(f"Duplicate time series key '{key}'", result.errors[0])
        self.assertEqual(len(result.errors), 1)
        duplicates = [w for w in self.warning_texts() if "Duplicate time series key" in w]
        self.assertEqual(len(duplicates), 1)
        self.assertIn(key, duplicates[0])

    def test_key_collision_between_data_table_profiles_keeps_first_and_reports_error(self) -> None:
        self.mock_read.side_effect = [
            (_table_rows([1.0, 2.0]), _HEADER),
            (_table_rows([7.0, 8.0]), _HEADER),
        ]
        energy_system = _energy_system([("asset1", _table_profile())])
        port = next(p for p in energy_system.eAllContents() if isinstance(p, esdl.InPort))
        port.profile.append(_table_profile(table="other_table"))
        data, result = self.loader.load_time_series_from_esdl(energy_system)

        key = f"asset1{COMPOSITE_KEY_SEPARATOR}HeatIn.Q"
        self.assertEqual(data[key].values, [1.0, 2.0])
        self.assertFalse(result.is_valid)
        self.assertIn(f"Duplicate time series key '{key}'", result.errors[0])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(
            len([w for w in self.warning_texts() if "Duplicate time series key" in w]), 1
        )


if __name__ == "__main__":
    unittest.main()
