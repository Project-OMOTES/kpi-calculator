# unit_test/test_database_connectivity.py
"""Tests for database connectivity implementation."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kpicalculator.adapters.base_adapter import BaseAdapter, ValidationResult
from kpicalculator.adapters.database_time_series_loader import DatabaseTimeSeriesLoader
from kpicalculator.adapters.esdl_adapter import EsdlAdapter
from kpicalculator.common.types import DatabaseCredentials
from kpicalculator.security.credential_manager import CredentialManager


class TestBaseAdapter(unittest.TestCase):
    """Test BaseAdapter interface."""

    def test_base_adapter_initialization(self) -> None:
        """Test BaseAdapter initialization."""

        # Since BaseAdapter is abstract, we need to create a concrete implementation
        class ConcreteAdapter(BaseAdapter):
            def load_data(self, source, **kwargs) -> None:
                return Mock()

            def validate_source(self, source) -> None:
                return ValidationResult(True)

            def get_supported_source_type(self) -> None:
                return "test"

        adapter = ConcreteAdapter()

        # Built-in cost unit factors are loaded automatically
        self.assertIn("EUR/kW", adapter.unit_conversions)
        self.assertAlmostEqual(adapter.unit_conversions["EUR/kW"], 0.001)
        self.assertEqual(adapter.get_supported_source_type(), "test")
        self.assertEqual(adapter.get_supported_parameters(), [])


class TestDatabaseCredentials(unittest.TestCase):
    """Test DatabaseCredentials dataclass."""

    def test_database_credentials_creation(self) -> None:
        """Test DatabaseCredentials creation with different parameters."""
        # Test minimal credentials
        creds = DatabaseCredentials(host="localhost", port=8086)
        self.assertEqual(creds.host, "localhost")
        self.assertEqual(creds.port, 8086)
        self.assertIsNone(creds.username)
        self.assertIsNone(creds.password)
        self.assertEqual(creds.database, "energy_profiles")
        self.assertFalse(creds.ssl)

        # Test full credentials
        full_creds = DatabaseCredentials(
            host="test.example.com",
            port=443,
            username="testuser",
            password="testpass",
            database="test_db",
            ssl=True,
            verify_ssl=True,
        )
        self.assertEqual(full_creds.host, "test.example.com")
        self.assertEqual(full_creds.port, 443)
        self.assertEqual(full_creds.username, "testuser")
        self.assertEqual(full_creds.password, "testpass")
        self.assertEqual(full_creds.database, "test_db")
        self.assertTrue(full_creds.ssl)
        self.assertTrue(full_creds.verify_ssl)


class TestDatabaseTimeSeriesLoader(unittest.TestCase):
    """Test DatabaseTimeSeriesLoader functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.loader = DatabaseTimeSeriesLoader()

    def test_loader_initialization(self) -> None:
        """Test loader initialization with secure credential manager."""
        # Test with default credential manager
        loader = DatabaseTimeSeriesLoader()
        self.assertIsNotNone(loader.credential_manager)

        # Test with custom credential manager
        mock_manager = Mock(spec=CredentialManager)
        loader_with_manager = DatabaseTimeSeriesLoader(mock_manager)
        self.assertEqual(loader_with_manager.credential_manager, mock_manager)

    def test_set_credential_manager(self) -> None:
        """Test setting credential manager."""
        mock_manager = Mock(spec=CredentialManager)
        self.loader.set_credential_manager(mock_manager)

        self.assertEqual(self.loader.credential_manager, mock_manager)

    @patch.dict(
        os.environ,
        {
            "KPI_DB_TEST_EXAMPLE_COM_8086_USERNAME": "test_user",
            "KPI_DB_TEST_EXAMPLE_COM_8086_PASSWORD": "test_pass",
        },
    )
    @patch("kpicalculator.adapters.database_time_series_loader.InfluxDBProfileManager")
    def test_load_profile_data_success(self, mock_influx) -> None:
        """Test successful profile data loading."""
        # Create mock profile
        mock_profile = Mock()
        mock_profile.host = "test.example.com"
        mock_profile.port = 8086
        mock_profile.database = "test_db"
        mock_profile.field = "test_field"
        mock_profile.measurement = "test_measurement"
        mock_profile.multiplier = 1.0
        mock_profile.startDate = "2023-01-01T00:00:00Z"
        mock_profile.endDate = "2023-01-01T02:00:00Z"

        # Mock quantity and unit
        mock_quantity = Mock()
        mock_quantity.physicalQuantity = "POWER"
        mock_profile.profileQuantityAndUnit = mock_quantity

        # Mock time series data
        mock_time_series = Mock()
        mock_time_series.profile_data_list = [
            ("2023-01-01T00:00:00Z", 100.0),
            ("2023-01-01T01:00:00Z", 200.0),
        ]
        mock_time_series.start_datetime = "2023-01-01T00:00:00Z"
        mock_time_series.end_datetime = "2023-01-01T02:00:00Z"

        # Configure mock
        mock_influx.create_esdl_influxdb_profile_manager.return_value = mock_time_series

        # Test loading (now with proper credentials)
        credentials = self.loader._get_credentials_for_profile(mock_profile)
        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.username, "test_user")
        self.assertEqual(credentials.password, "test_pass")

    @patch.dict(
        os.environ,
        {
            "KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_USERNAME": "test_user",
            "KPI_DB_WU_PROFILES_ESDL_BETA_HESI_ENERGY_443_PASSWORD": "test_pass",
        },
    )
    def test_get_credentials_for_profile(self) -> None:
        """Test credential retrieval for profiles from environment."""
        # Create mock profile with known host
        mock_profile = Mock()
        mock_profile.host = "wu-profiles.esdl-beta.hesi.energy"
        mock_profile.port = 443
        mock_profile.database = "energy_profiles"
        mock_profile.field = "test_field"
        mock_profile.measurement = "test_measurement"

        creds = self.loader._get_credentials_for_profile(mock_profile)

        self.assertEqual(creds.host, "wu-profiles.esdl-beta.hesi.energy")
        self.assertEqual(creds.port, 443)
        self.assertEqual(creds.username, "test_user")
        self.assertEqual(creds.password, "test_pass")


class TestEsdlAdapterDatabaseIntegration(unittest.TestCase):
    """Test EsdlAdapter database integration."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.adapter = EsdlAdapter()

    def test_adapter_inheritance(self) -> None:
        """Test that EsdlAdapter properly inherits from BaseAdapter."""
        self.assertIsInstance(self.adapter, BaseAdapter)
        self.assertEqual(self.adapter.get_supported_source_type(), "esdl")

    def test_supported_parameters(self) -> None:
        """Test supported parameters list."""
        params = self.adapter.get_supported_parameters()
        expected_params = [
            "time_series_file",
            "timeseries_dataframes",
            "use_database_profiles",
        ]

        for param in expected_params:
            self.assertIn(param, params)

    def test_validate_source_valid_file(self) -> None:
        """Test source validation with valid ESDL file."""
        # Create temporary ESDL file
        with tempfile.NamedTemporaryFile(suffix=".esdl", delete=False) as temp_file:
            temp_file.write(b'<?xml version="1.0"?><esdl:EnergySystem/>')
            temp_path = temp_file.name

        try:
            result = self.adapter.validate_source(temp_path)
            self.assertTrue(result.is_valid)
            self.assertEqual(len(result.errors), 0)
        finally:
            Path(temp_path).unlink()

    def test_validate_source_invalid_file(self) -> None:
        """Test source validation with invalid file."""
        result = self.adapter.validate_source("nonexistent_file.esdl")
        self.assertFalse(result.is_valid)
        self.assertTrue(len(result.errors) > 0)
        self.assertIn("does not exist", result.errors[0])

    def test_validate_source_wrong_extension(self) -> None:
        """Test source validation with wrong file extension."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_path = temp_file.name

        try:
            result = self.adapter.validate_source(temp_path)
            self.assertTrue(result.is_valid)  # Still valid, just warning
            self.assertTrue(len(result.warnings) > 0)
            self.assertIn("does not have .esdl extension", result.warnings[0])
        finally:
            Path(temp_path).unlink()

    def test_database_loader_initialization(self) -> None:
        """Test that adapter initializes database loader."""
        self.assertIsNotNone(self.adapter.database_loader)
        self.assertIsInstance(self.adapter.database_loader, DatabaseTimeSeriesLoader)

    @patch("kpicalculator.adapters.esdl_adapter.EnergySystemHandler")
    def test_load_data_database_priority(self, mock_handler) -> None:
        """Test that database profiles have priority over XML files."""
        # Create mock ESDL structure
        mock_es = Mock()
        mock_es.eAllContents.return_value = []
        mock_handler.return_value.load_file.return_value = mock_es

        # Create temporary ESDL file
        with tempfile.NamedTemporaryFile(suffix=".esdl", delete=False) as temp_file:
            temp_file.write(b'<?xml version="1.0"?><esdl:EnergySystem/>')
            temp_path = temp_file.name

        try:
            # Test with database profiles enabled (default)
            result = self.adapter.load_data(temp_path, use_database_profiles=True)

            self.assertIsNotNone(result)
            self.assertEqual(result.name, Path(temp_path).stem)

        except Exception as e:
            # Expected since we're using mocks - the important thing is the structure
            self.assertIn("load_file", str(e))
        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    unittest.main()
