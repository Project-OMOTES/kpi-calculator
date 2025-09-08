# unit_test/test_database_time_series_loader.py
"""Tests for database time series loader."""

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd
from esdl import esdl

from kpicalculator.adapters.common_model import TimeSeries
from kpicalculator.adapters.database_time_series_loader import (
    DatabaseTimeSeriesLoader,
)
from kpicalculator.common.types import DatabaseCredentials
from kpicalculator.exceptions import CredentialError
from kpicalculator.security.credential_manager import CredentialManager


class MockCredentialManager(CredentialManager):
    """Mock credential manager for testing."""

    def __init__(self, credentials=None):
        self.credentials = credentials or {}

    def get_database_credentials(self, host: str, port: int):
        key = f"{host}:{port}"
        return self.credentials.get(key)


class TestDatabaseTimeSeriesLoader(unittest.TestCase):
    """Test database time series loader functionality."""

    def setUp(self):
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
            {"test.example.com:443": self.test_credentials}
        )

        # Create loader
        self.loader = DatabaseTimeSeriesLoader(self.credential_manager)

    def test_init_with_credential_manager(self):
        """Test initialization with credential manager."""
        loader = DatabaseTimeSeriesLoader(self.credential_manager)
        self.assertEqual(loader.credential_manager, self.credential_manager)
        self.assertIsNotNone(loader.db_logger)

    def test_init_with_default_credential_manager(self):
        """Test initialization with default credential manager."""
        with patch(
            "kpicalculator.adapters.database_time_series_loader."
            "create_default_credential_manager"
        ) as mock_create:
            mock_manager = Mock()
            mock_create.return_value = mock_manager

            loader = DatabaseTimeSeriesLoader()

            mock_create.assert_called_once()
            self.assertEqual(loader.credential_manager, mock_manager)

    def test_get_secure_credentials_success(self):
        """Test successful credential retrieval."""
        credentials = self.loader._get_secure_credentials("test.example.com", 443)

        self.assertEqual(credentials, self.test_credentials)
        self.assertEqual(credentials.host, "test.example.com")
        self.assertEqual(credentials.port, 443)

    def test_get_secure_credentials_not_found(self):
        """Test credential retrieval when credentials not found."""
        with self.assertRaises(CredentialError) as context:
            self.loader._get_secure_credentials("unknown.host.com", 8080)

        error = context.exception
        self.assertIn("No credentials found", str(error))
        self.assertIn("unknown.host.com:8080", str(error))
        self.assertIn("host", error.context)
        self.assertIn("port", error.context)
        self.assertIn("env_prefix", error.context)

    def test_get_secure_credentials_exception_handling(self):
        """Test credential retrieval with manager exception."""
        # Create manager that raises exception
        error_manager = Mock()
        error_manager.get_database_credentials.side_effect = RuntimeError("Manager error")

        loader = DatabaseTimeSeriesLoader(error_manager)

        with self.assertRaises(RuntimeError):
            loader._get_secure_credentials("test.example.com", 443)

    def test_extract_asset_id_from_port(self):
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

    def test_extract_asset_id_from_carrier(self):
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

    def test_extract_asset_id_fallback_to_measurement(self):
        """Test asset ID extraction fallback to measurement."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.eContainer.side_effect = AttributeError("No container")
        profile.measurement = "fallback_measurement"

        asset_id = self.loader._extract_asset_id(profile)
        self.assertEqual(asset_id, "fallback_measurement")

    @patch("kpicalculator.adapters.database_time_series_loader.InfluxDBProfileManager")
    @patch("kpicalculator.adapters.database_time_series_loader.InputValidator")
    def test_load_profile_data_success(self, mock_validator, mock_profile_manager):
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

    def test_load_profile_data_exception_handling(self):
        """Test profile data loading with exception."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.measurement = "power"
        profile.field = "consumption"

        # Mock get credentials to raise exception
        with patch.object(self.loader, "_get_credentials_for_profile") as mock_get_creds:
            mock_get_creds.side_effect = CredentialError("No credentials")

            result = self.loader._load_profile_data(profile)

        self.assertIsNone(result)

    def test_get_credentials_for_profile_https_prefix(self):
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

    def test_get_credentials_for_profile_http_prefix(self):
        """Test credential extraction with HTTP prefix in host."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "http://test.example.com"
        profile.port = 8080

        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.return_value = self.test_credentials

            with patch("kpicalculator.adapters.database_time_series_loader.InputValidator") as mock_validator:
                mock_validator.validate_database_host.return_value = "test.example.com"
                mock_validator.validate_database_port.return_value = 8080
                self.loader._get_credentials_for_profile(profile)

        # Should strip http:// prefix (7 characters) and use validated values
        mock_get_secure.assert_called_once_with("test.example.com", 8080)

    def test_get_credentials_for_profile_ssl_port_443(self):
        """Test SSL setting for port 443."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "test.example.com"
        profile.port = 443

        # Create credentials without SSL
        non_ssl_credentials = DatabaseCredentials(
            host="test.example.com",
            port=443,
            username="user",
            password="pass",
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

    def test_get_credentials_for_profile_credential_error(self):
        """Test credential profile error handling."""
        profile = Mock(spec=esdl.InfluxDBProfile)
        profile.host = "test.example.com"
        profile.port = 443
        profile.database = "test_db"
        profile.field = "power"
        profile.measurement = "consumption"

        original_error = CredentialError("Original error", context={"original": "context"})

        with patch.object(self.loader, "_get_secure_credentials") as mock_get_secure:
            mock_get_secure.side_effect = original_error

            with self.assertRaises(CredentialError) as context:
                self.loader._get_credentials_for_profile(profile)

        # Should wrap original error with profile context
        error = context.exception
        self.assertIn("Cannot load credentials for InfluxDB profile", str(error))
        self.assertIn("profile_host", error.context)
        self.assertIn("profile_port", error.context)
        self.assertIn("profile_field", error.context)

    def test_validate_profile_data_success(self):
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

    def test_validate_profile_data_end_date_mismatch(self):
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

    def test_validate_profile_data_invalid_time_resolution(self):
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

    def test_convert_units_power(self):
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

    def test_convert_units_energy(self):
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

    def test_convert_units_no_reference(self):
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

    def test_convert_units_unsupported_quantity(self):
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

    def test_convert_units_exception_handling(self):
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

    def test_set_credential_manager(self):
        """Test credential manager setter."""
        new_manager = Mock()

        self.loader.set_credential_manager(new_manager)

        self.assertEqual(self.loader.credential_manager, new_manager)

    @patch("kpicalculator.adapters.database_time_series_loader.time")
    def test_load_time_series_from_esdl_success(self, mock_time):
        """Test successful ESDL time series loading."""
        # Mock time.time() for performance measurement
        # Provide enough time values for all calls in the method
        mock_time.time.side_effect = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45]

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
        self.assertEqual(result_data["asset_1"], time_series1)
        self.assertEqual(result_data["asset_2"], time_series2)

        # Verify mock calls
        self.assertEqual(mock_extract.call_count, 2)
        self.assertEqual(mock_load.call_count, 2)

    def test_load_time_series_from_esdl_no_profiles(self):
        """Test ESDL loading with no InfluxDB profiles."""
        energy_system = Mock()
        energy_system.eAllContents.return_value = [Mock(), Mock()]  # No InfluxDB profiles

        result_data, validation_result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertTrue(validation_result.is_valid)
        self.assertEqual(len(result_data), 0)
        self.assertIn("No InfluxDB profiles found in ESDL file", validation_result.warnings)

    def test_load_time_series_from_esdl_with_errors(self):
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

    def test_load_time_series_from_esdl_critical_exception(self):
        """Test ESDL loading with critical exception."""
        energy_system = Mock()
        energy_system.eAllContents.side_effect = RuntimeError("Critical system error")

        result_data, validation_result = self.loader.load_time_series_from_esdl(energy_system)

        self.assertFalse(validation_result.is_valid)
        self.assertEqual(len(result_data), 0)
        self.assertIn("Critical system error", validation_result.errors[0])


if __name__ == "__main__":
    unittest.main()
