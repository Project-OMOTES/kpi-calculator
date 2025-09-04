# unit_test/test_secure_credentials.py
"""Tests for secure credential management system."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.kpicalculator.common.types import DatabaseCredentials
from src.kpicalculator.exceptions import (
    ConfigurationError,
    CredentialError,
    SecurityError,
)
from src.kpicalculator.security.credential_manager import (
    ChainedCredentialManager,
    ConfigFileCredentialManager,
    SecureCredentialManager,
    create_default_credential_manager,
)


class TestSecureCredentialManager(unittest.TestCase):
    """Test SecureCredentialManager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = SecureCredentialManager()

    @patch.dict(
        os.environ,
        {
            "KPI_DB_TEST_EXAMPLE_COM_8086_USERNAME": "test_user",
            "KPI_DB_TEST_EXAMPLE_COM_8086_PASSWORD": "test_pass",
            "KPI_DB_TEST_EXAMPLE_COM_8086_DATABASE": "test_db",
            "KPI_DB_TEST_EXAMPLE_COM_8086_SSL": "true",
        },
    )
    def test_get_credentials_from_environment(self):
        """Test loading credentials from environment variables."""
        creds = self.manager.get_database_credentials("test.example.com", 8086)

        self.assertIsNotNone(creds)
        self.assertEqual(creds.host, "test.example.com")
        self.assertEqual(creds.port, 8086)
        self.assertEqual(creds.username, "test_user")
        self.assertEqual(creds.password, "test_pass")
        self.assertEqual(creds.database, "test_db")
        self.assertTrue(creds.ssl)

    def test_no_credentials_found(self):
        """Test behavior when no credentials are found."""
        creds = self.manager.get_database_credentials("nonexistent.example.com", 9999)
        self.assertIsNone(creds)

    @patch.dict(
        os.environ,
        {
            "KPI_DB_COMPLEX_HOST_NAME_443_USERNAME": "complex_user",
            "KPI_DB_COMPLEX_HOST_NAME_443_PASSWORD": "complex_pass",
        },
    )
    def test_host_normalization(self):
        """Test that host names are properly normalized for environment variables."""
        creds = self.manager.get_database_credentials("complex-host.name", 443)

        self.assertIsNotNone(creds)
        self.assertEqual(creds.username, "complex_user")
        self.assertEqual(creds.password, "complex_pass")


class TestConfigFileCredentialManager(unittest.TestCase):
    """Test ConfigFileCredentialManager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir) / "credentials.json"
        self.manager = ConfigFileCredentialManager(self.config_path)

    def test_no_config_file(self):
        """Test behavior when config file doesn't exist."""
        creds = self.manager.get_database_credentials("test.example.com", 8086)
        self.assertIsNone(creds)

    @patch(
        "src.kpicalculator.security.credential_manager.ConfigFileCredentialManager._validate_file_permissions"
    )
    def test_valid_config_file(self, mock_validate_permissions):
        """Test loading credentials from valid config file."""
        config = {
            "databases": {
                "test.example.com:8086": {
                    "host": "test.example.com",
                    "port": 8086,
                    "username": "config_user",
                    "password": "config_pass",
                    "database": "config_db",
                    "ssl": True,
                }
            }
        }

        with open(self.config_path, "w") as f:
            json.dump(config, f)

        creds = self.manager.get_database_credentials("test.example.com", 8086)

        self.assertIsNotNone(creds)
        self.assertEqual(creds.username, "config_user")
        self.assertEqual(creds.password, "config_pass")
        self.assertEqual(creds.database, "config_db")
        self.assertTrue(creds.ssl)

    @patch(
        "src.kpicalculator.security.credential_manager.ConfigFileCredentialManager._validate_file_permissions"
    )
    def test_invalid_json_config(self, mock_validate_permissions):
        """Test handling of invalid JSON config file."""
        with open(self.config_path, "w") as f:
            f.write("{ invalid json")

        with self.assertRaises(ConfigurationError):
            self.manager.get_database_credentials("test.example.com", 8086)

    @patch(
        "src.kpicalculator.security.credential_manager.ConfigFileCredentialManager._validate_file_permissions"
    )
    def test_missing_required_fields(self, mock_validate_permissions):
        """Test handling of config with missing required fields."""
        config = {
            "databases": {
                "test.example.com:8086": {
                    "host": "test.example.com",
                    "port": 8086,
                    # Missing username and password
                }
            }
        }

        with open(self.config_path, "w") as f:
            json.dump(config, f)

        with self.assertRaises(ConfigurationError):
            self.manager.get_database_credentials("test.example.com", 8086)


class TestChainedCredentialManager(unittest.TestCase):
    """Test ChainedCredentialManager functionality."""

    def test_empty_managers_list(self):
        """Test that empty managers list raises error."""
        with self.assertRaises(ValueError):
            ChainedCredentialManager()

    def test_fallback_priority(self):
        """Test that managers are tried in priority order."""
        # Create mock managers
        primary_manager = Mock()
        primary_manager.get_database_credentials.return_value = None

        secondary_manager = Mock()
        secondary_creds = DatabaseCredentials(
            host="test.example.com", port=8086, username="secondary_user", password="secondary_pass"
        )
        secondary_manager.get_database_credentials.return_value = secondary_creds

        # Create chained manager
        chained = ChainedCredentialManager(primary_manager, secondary_manager)

        # Test fallback behavior
        creds = chained.get_database_credentials("test.example.com", 8086)

        self.assertEqual(creds, secondary_creds)
        primary_manager.get_database_credentials.assert_called_once_with("test.example.com", 8086)
        secondary_manager.get_database_credentials.assert_called_once_with("test.example.com", 8086)

    def test_first_manager_success(self):
        """Test that first manager's credentials are used when available."""
        # Create mock managers
        primary_creds = DatabaseCredentials(
            host="test.example.com", port=8086, username="primary_user", password="primary_pass"
        )
        primary_manager = Mock()
        primary_manager.get_database_credentials.return_value = primary_creds

        secondary_manager = Mock()

        # Create chained manager
        chained = ChainedCredentialManager(primary_manager, secondary_manager)

        # Test primary success
        creds = chained.get_database_credentials("test.example.com", 8086)

        self.assertEqual(creds, primary_creds)
        primary_manager.get_database_credentials.assert_called_once_with("test.example.com", 8086)
        # Secondary should not be called
        secondary_manager.get_database_credentials.assert_not_called()


class TestCredentialManagerIntegration(unittest.TestCase):
    """Test integration with database components."""

    @patch.dict(
        os.environ,
        {
            "KPI_DB_INTEGRATION_TEST_COM_8086_USERNAME": "integration_user",
            "KPI_DB_INTEGRATION_TEST_COM_8086_PASSWORD": "integration_pass",
        },
    )
    def test_database_loader_integration(self):
        """Test integration with DatabaseTimeSeriesLoader."""
        from src.kpicalculator.adapters.database_time_series_loader import (
            DatabaseTimeSeriesLoader,
        )

        # Create loader with secure credential manager
        loader = DatabaseTimeSeriesLoader(SecureCredentialManager())

        # Test secure credential retrieval
        creds = loader._get_secure_credentials("integration.test.com", 8086)

        self.assertEqual(creds.username, "integration_user")
        self.assertEqual(creds.password, "integration_pass")

    def test_credential_error_on_missing_credentials(self):
        """Test that CredentialError is raised when credentials are missing."""
        from src.kpicalculator.adapters.database_time_series_loader import (
            DatabaseTimeSeriesLoader,
        )

        loader = DatabaseTimeSeriesLoader(SecureCredentialManager())

        with self.assertRaises(CredentialError) as context:
            loader._get_secure_credentials("missing.example.com", 9999)

        self.assertIn("No credentials found", str(context.exception))
        self.assertIn("missing.example.com:9999", str(context.exception))

    def test_default_credential_manager_creation(self):
        """Test default credential manager creation."""
        manager = create_default_credential_manager()

        self.assertIsInstance(manager, ChainedCredentialManager)
        self.assertEqual(len(manager.managers), 2)
        self.assertIsInstance(manager.managers[0], SecureCredentialManager)
        self.assertIsInstance(manager.managers[1], ConfigFileCredentialManager)


if __name__ == "__main__":
    unittest.main()
