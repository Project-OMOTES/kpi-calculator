# unit_test/test_credential_manager.py
"""Tests for credential management system."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kpicalculator.common.types import DatabaseCredentials
from kpicalculator.exceptions import SecurityError
from kpicalculator.security.credential_manager import (
    ChainedCredentialManager,
    ConfigFileCredentialManager,
    CredentialManager,
    SecureCredentialManager,
    create_default_credential_manager,
)


class TestSecureCredentialManager(unittest.TestCase):
    """Test environment-based credential manager."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.manager = SecureCredentialManager()

    @staticmethod
    def _filter_env_vars(*excluded_prefixes: str) -> dict[str, str]:
        """Filter environment variables excluding specified prefixes.

        Args:
            *excluded_prefixes: Variable prefixes to exclude

        Returns:
            Filtered environment dictionary
        """
        return {
            k: v
            for k, v in os.environ.items()
            if not any(k.startswith(prefix) for prefix in excluded_prefixes)
        }

    @patch.dict(
        os.environ,
        {
            "KPI_DB_EXAMPLE_COM_443_USERNAME": "testuser",
            "KPI_DB_EXAMPLE_COM_443_PASSWORD": "testpass",
            "KPI_DB_EXAMPLE_COM_443_DATABASE": "testdb",
            "KPI_DB_EXAMPLE_COM_443_SSL": "true",
            "KPI_DB_EXAMPLE_COM_443_VERIFY_SSL": "false",
        },
    )
    def test_get_database_credentials_success(self) -> None:
        """Test successful credential retrieval from environment."""
        credentials = self.manager.get_database_credentials("example.com", 443)

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.host, "example.com")
        self.assertEqual(credentials.port, 443)
        self.assertEqual(credentials.username, "testuser")
        self.assertEqual(credentials.password, "testpass")
        self.assertEqual(credentials.database, "testdb")
        self.assertTrue(credentials.ssl)
        self.assertFalse(credentials.verify_ssl)

    @patch.dict(
        os.environ,
        {
            "KPI_DB_EXAMPLE_COM_443_USERNAME": "testuser",
            "KPI_DB_EXAMPLE_COM_443_PASSWORD": "testpass",
            # No SSL or VERIFY_SSL variables - should use defaults
        },
    )
    def test_get_database_credentials_defaults(self) -> None:
        """Test credential retrieval with default SSL settings."""
        credentials = self.manager.get_database_credentials("example.com", 443)

        self.assertIsNotNone(credentials)
        self.assertFalse(
            credentials.ssl
        )  # Default from code: ssl_env.lower() in ("true", "1", "yes", "on")
        self.assertFalse(
            credentials.verify_ssl
        )  # Default from code: verify_ssl_env.lower() in ("true", "1", "yes", "on")
        self.assertEqual(
            credentials.database, "energy_profiles"
        )  # Default from code: os.getenv(..., "energy_profiles")

    @patch.dict(
        os.environ,
        {
            "KPI_DB_COMPLEX_HOST_NAME_8080_USERNAME": "testuser",
            "KPI_DB_COMPLEX_HOST_NAME_8080_PASSWORD": "testpass",
        },
    )
    def test_get_database_credentials_complex_hostname(self) -> None:
        """Test credential retrieval with complex hostname normalization."""
        credentials = self.manager.get_database_credentials("complex-host.name", 8080)

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.username, "testuser")

    def test_get_database_credentials_not_found(self) -> None:
        """Test credential retrieval when credentials not found."""
        clean_env = self._filter_env_vars("KPI_DB_NONEXISTENT_COM_443_")

        with patch.dict(os.environ, clean_env, clear=True):
            credentials = self.manager.get_database_credentials("nonexistent.com", 443)
            self.assertIsNone(credentials)

    def test_get_database_credentials_invalid_inputs(self) -> None:
        """Test credential retrieval with various invalid input scenarios."""
        test_cases = [
            ("", "testpass", None, "empty username"),
            ("testuser", "", None, "empty password"),
            ("testuser", None, None, "missing password"),
            (None, "testpass", None, "missing username"),
        ]

        for username, password, expected, description in test_cases:
            with self.subTest(case=description):
                test_env = self._filter_env_vars("KPI_DB_EXAMPLE_COM_443_")

                if username is not None:
                    test_env["KPI_DB_EXAMPLE_COM_443_USERNAME"] = username
                if password is not None:
                    test_env["KPI_DB_EXAMPLE_COM_443_PASSWORD"] = password

                with patch.dict(os.environ, test_env, clear=True):
                    credentials = self.manager.get_database_credentials("example.com", 443)
                    self.assertEqual(credentials, expected)

    @patch.dict(
        os.environ,
        {
            "INFLUXDB_USERNAME": "simulator_user",
            "INFLUXDB_PASSWORD": "simulator_pass",
            "INFLUXDB_DATABASE": "simulator_db",
        },
    )
    def test_get_database_credentials_influxdb_fallback(self) -> None:
        """Test fallback to INFLUXDB_* variables for simulator-worker compatibility."""
        credentials = self.manager.get_database_credentials("localhost", 8086)

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.host, "localhost")
        self.assertEqual(credentials.port, 8086)
        self.assertEqual(credentials.username, "simulator_user")
        self.assertEqual(credentials.password, "simulator_pass")
        self.assertEqual(credentials.database, "simulator_db")
        self.assertFalse(credentials.ssl)  # Default
        self.assertFalse(credentials.verify_ssl)  # Default

    @patch.dict(
        os.environ,
        {
            "KPI_DB_LOCALHOST_8086_USERNAME": "kpi_user",
            "KPI_DB_LOCALHOST_8086_PASSWORD": "kpi_pass",
            "INFLUXDB_USERNAME": "simulator_user",
            "INFLUXDB_PASSWORD": "simulator_pass",
        },
    )
    def test_get_database_credentials_kpi_takes_precedence(self) -> None:
        """Test that KPI_DB_* variables take precedence over INFLUXDB_* variables."""
        credentials = self.manager.get_database_credentials("localhost", 8086)

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.username, "kpi_user")  # KPI_DB_* wins
        self.assertEqual(credentials.password, "kpi_pass")  # KPI_DB_* wins


class TestConfigFileCredentialManager(unittest.TestCase):
    """Test configuration file credential manager."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "credentials.json"
        self.manager = ConfigFileCredentialManager(self.config_path)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_get_database_credentials_success(self) -> None:
        """Test successful credential retrieval from config file."""
        config_data = {
            "databases": {
                "example.com: 443": {
                    "host": "example.com",
                    "port": 443,
                    "username": "testuser",
                    "password": "testpass",
                    "database": "testdb",
                    "ssl": True,
                    "verify_ssl": False,
                }
            }
        }

        # Write config file and mock secure permissions
        self.config_path.write_text(json.dumps(config_data))

        with patch.object(self.manager, "_validate_file_permissions"):
            credentials = self.manager.get_database_credentials("example.com", 443)

            self.assertIsNotNone(credentials)
            self.assertEqual(credentials.host, "example.com")
            self.assertEqual(credentials.port, 443)
            self.assertEqual(credentials.username, "testuser")
            self.assertEqual(credentials.password, "testpass")
            self.assertEqual(credentials.database, "testdb")
            self.assertTrue(credentials.ssl)
            self.assertFalse(credentials.verify_ssl)

    def test_get_database_credentials_not_found(self) -> None:
        """Test credential retrieval when host:port not in config."""
        config_data = {
            "databases": {
                "other.com: 443": {
                    "host": "other.com",
                    "port": 443,
                    "username": "otheruser",
                    "password": "otherpass",
                }
            }
        }

        self.config_path.write_text(json.dumps(config_data))

        with patch.object(self.manager, "_validate_file_permissions"):
            credentials = self.manager.get_database_credentials("example.com", 443)
            self.assertIsNone(credentials)

    def test_get_database_credentials_file_not_exists(self) -> None:
        """Test credential retrieval when config file doesn't exist."""
        # Don't create the file - returns empty dict as per implementation
        credentials = self.manager.get_database_credentials("example.com", 443)
        self.assertIsNone(credentials)

    def test_get_database_credentials_invalid_json(self) -> None:
        """Test credential retrieval with invalid JSON."""
        # Write invalid JSON - should raise ConfigurationError
        self.config_path.write_text("invalid json content")

        with self.assertRaises(Exception):  # ConfigurationError expected
            self.manager.get_database_credentials("example.com", 443)

    def test_get_database_credentials_minimal_config(self) -> None:
        """Test credential retrieval with minimal configuration."""
        config_data = {
            "databases": {
                "example.com: 443": {
                    "host": "example.com",
                    "port": 443,
                    "username": "testuser",
                    "password": "testpass",
                    # No database, ssl, or verify_ssl - should use defaults
                }
            }
        }

        self.config_path.write_text(json.dumps(config_data))

        with patch.object(self.manager, "_validate_file_permissions"):
            credentials = self.manager.get_database_credentials("example.com", 443)

            self.assertIsNotNone(credentials)
            self.assertEqual(credentials.username, "testuser")
            self.assertEqual(credentials.password, "testpass")
            self.assertEqual(credentials.database, "energy_profiles")  # Default from code
            self.assertFalse(credentials.ssl)  # Default from code
            self.assertFalse(credentials.verify_ssl)  # Default from code

    def test_validate_file_permissions_secure(self) -> None:
        """Test file permission validation when permissions are secure."""
        config_data = {
            "databases": {
                "test.com: 443": {
                    "host": "test.com",
                    "port": 443,
                    "username": "user",
                    "password": "password123",
                }
            }
        }
        self.config_path.write_text(json.dumps(config_data))

        # Mock secure permissions (owner read/write only, no group/other bits)
        mock_stat_result = Mock()
        mock_stat_result.st_mode = 0o100600  # Regular file with 600 permissions

        # Patch the stat module attributes directly in the credential manager module
        with patch("pathlib.Path.stat", return_value=mock_stat_result):
            with (
                patch("kpicalculator.security.credential_manager.stat.S_IRGRP", 0o040),
                patch("kpicalculator.security.credential_manager.stat.S_IROTH", 0o004),
            ):
                # Should not raise any exception - secure permissions
                credentials = self.manager.get_database_credentials("test.com", 443)
                self.assertIsNotNone(credentials)

    def test_validate_file_permissions_insecure(self) -> None:
        """Test file permission validation when permissions are insecure."""
        config_data = {
            "databases": {
                "test.com: 443": {
                    "host": "test.com",
                    "port": 443,
                    "username": "user",
                    "password": "password123",
                }
            }
        }
        self.config_path.write_text(json.dumps(config_data))

        # Mock insecure permissions (readable by others)
        mock_stat_result = Mock()
        mock_stat_result.st_mode = 0o100644  # Regular file with 644 permissions (world readable)

        with patch("pathlib.Path.stat", return_value=mock_stat_result):
            with (
                patch("kpicalculator.security.credential_manager.stat.S_IRGRP", 0o040),
                patch("kpicalculator.security.credential_manager.stat.S_IROTH", 0o004),
            ):
                with self.assertRaises(SecurityError) as context:
                    self.manager.get_database_credentials("test.com", 443)

                error = context.exception
                self.assertIn("Credentials file has insecure permissions", str(error))
                self.assertIn("file_mode", str(error))


class TestChainedCredentialManager(unittest.TestCase):
    """Test chained credential manager with fallback priority."""

    def test_init_success(self) -> None:
        """Test successful chained manager initialization."""
        manager1 = Mock(spec=CredentialManager)
        manager2 = Mock(spec=CredentialManager)

        chained = ChainedCredentialManager(manager1, manager2)

        self.assertEqual(chained.managers, (manager1, manager2))
        self.assertIsNotNone(chained.db_logger)

    def test_init_no_managers(self) -> None:
        """Test chained manager initialization with no managers."""
        with self.assertRaises(ValueError) as context:
            ChainedCredentialManager()

        self.assertIn("At least one credential manager must be provided", str(context.exception))

    def test_get_database_credentials_first_manager_success(self) -> None:
        """Test credential retrieval when first manager succeeds."""
        test_credentials = DatabaseCredentials(
            host="example.com",
            port=443,
            username="user",
            password="password123",
            database="db",
            ssl=True,
            verify_ssl=True,
        )

        manager1 = Mock(spec=CredentialManager)
        manager1.get_database_credentials.return_value = test_credentials

        manager2 = Mock(spec=CredentialManager)

        chained = ChainedCredentialManager(manager1, manager2)

        credentials = chained.get_database_credentials("example.com", 443)

        self.assertEqual(credentials, test_credentials)
        # First manager should be called
        manager1.get_database_credentials.assert_called_once_with("example.com", 443)
        # Second manager should not be called
        manager2.get_database_credentials.assert_not_called()

    def test_get_database_credentials_fallback_to_second(self) -> None:
        """Test credential retrieval falls back to second manager."""
        test_credentials = DatabaseCredentials(
            host="example.com",
            port=443,
            username="user",
            password="password123",
            database="db",
            ssl=True,
            verify_ssl=True,
        )

        manager1 = Mock(spec=CredentialManager)
        manager1.get_database_credentials.return_value = None  # First fails

        manager2 = Mock(spec=CredentialManager)
        manager2.get_database_credentials.return_value = test_credentials  # Second succeeds

        chained = ChainedCredentialManager(manager1, manager2)

        credentials = chained.get_database_credentials("example.com", 443)

        self.assertEqual(credentials, test_credentials)
        # Both managers should be called
        manager1.get_database_credentials.assert_called_once_with("example.com", 443)
        manager2.get_database_credentials.assert_called_once_with("example.com", 443)

    def test_get_database_credentials_all_fail(self) -> None:
        """Test credential retrieval when all managers fail."""
        manager1 = Mock(spec=CredentialManager)
        manager1.get_database_credentials.return_value = None

        manager2 = Mock(spec=CredentialManager)
        manager2.get_database_credentials.return_value = None

        with patch("kpicalculator.common.logging_utils.get_database_logger"):
            chained = ChainedCredentialManager(manager1, manager2)

            credentials = chained.get_database_credentials("example.com", 443)

            self.assertIsNone(credentials)
            # Both managers should be called
            manager1.get_database_credentials.assert_called_once_with("example.com", 443)
            manager2.get_database_credentials.assert_called_once_with("example.com", 443)

    def test_get_database_credentials_exception_handling(self) -> None:
        """Test credential retrieval with manager exceptions."""
        manager1 = Mock(spec=CredentialManager)
        manager1.get_database_credentials.side_effect = Exception("Manager 1 error")

        test_credentials = DatabaseCredentials(
            host="example.com",
            port=443,
            username="user",
            password="password123",
            database="db",
            ssl=True,
            verify_ssl=True,
        )
        manager2 = Mock(spec=CredentialManager)
        manager2.get_database_credentials.return_value = test_credentials

        with patch("kpicalculator.common.logging_utils.get_database_logger"):
            chained = ChainedCredentialManager(manager1, manager2)

            # Exception should propagate - not handled by ChainedCredentialManager
            with self.assertRaises(Exception):
                chained.get_database_credentials("example.com", 443)

    def test_get_database_credentials_three_managers(self) -> None:
        """Test credential retrieval with three managers."""
        manager1 = Mock(spec=CredentialManager)
        manager1.get_database_credentials.return_value = None

        manager2 = Mock(spec=CredentialManager)
        manager2.get_database_credentials.return_value = None

        test_credentials = DatabaseCredentials(
            host="example.com",
            port=443,
            username="user",
            password="password123",
            database="db",
            ssl=True,
            verify_ssl=True,
        )
        manager3 = Mock(spec=CredentialManager)
        manager3.get_database_credentials.return_value = test_credentials

        chained = ChainedCredentialManager(manager1, manager2, manager3)

        credentials = chained.get_database_credentials("example.com", 443)

        self.assertEqual(credentials, test_credentials)
        # All three should be called
        manager1.get_database_credentials.assert_called_once()
        manager2.get_database_credentials.assert_called_once()
        manager3.get_database_credentials.assert_called_once()


class TestCreateDefaultCredentialManager(unittest.TestCase):
    """Test default credential manager factory function."""

    def test_create_default_credential_manager(self) -> None:
        """Test default credential manager creation."""
        manager = create_default_credential_manager()

        # Should return a ChainedCredentialManager
        self.assertIsInstance(manager, ChainedCredentialManager)

        # Should have two managers: Secure (env) and ConfigFile
        self.assertEqual(len(manager.managers), 2)
        self.assertIsInstance(manager.managers[0], SecureCredentialManager)
        self.assertIsInstance(manager.managers[1], ConfigFileCredentialManager)

    def test_default_manager_integration(self) -> None:
        """Test default manager integration with environment variables."""
        with patch.dict(
            os.environ,
            {
                "KPI_DB_TEST_HOST_443_USERNAME": "envuser",
                "KPI_DB_TEST_HOST_443_PASSWORD": "envpassword123",
            },
        ):
            manager = create_default_credential_manager()
            credentials = manager.get_database_credentials("test.host", 443)

            self.assertIsNotNone(credentials)
            self.assertEqual(credentials.username, "envuser")
            self.assertEqual(credentials.password, "envpassword123")

    def test_default_manager_fallback(self) -> None:
        """Test default manager fallback to config file."""
        # Create a temporary config file
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "credentials.json"
            config_data = {
                "databases": {
                    "fallback.host: 443": {
                        "host": "fallback.host",
                        "port": 443,
                        "username": "configuser",
                        "password": "configpass",
                    }
                }
            }
            config_path.write_text(json.dumps(config_data))

            # Create manager with custom config path
            env_manager = SecureCredentialManager()
            config_manager = ConfigFileCredentialManager(config_path)

            with patch("kpicalculator.common.logging_utils.get_database_logger"):
                with patch.object(config_manager, "_validate_file_permissions"):
                    manager = ChainedCredentialManager(env_manager, config_manager)

                    # Should fall back to config file since env vars are not set
                    clean_env = {
                        k: v
                        for k, v in os.environ.items()
                        if not k.startswith("KPI_DB_FALLBACK_HOST_443_")
                    }

                    with patch.dict(os.environ, clean_env, clear=True):
                        credentials = manager.get_database_credentials("fallback.host", 443)

                        self.assertIsNotNone(credentials)
                        self.assertEqual(credentials.username, "configuser")
                        self.assertEqual(credentials.password, "configpass")


class TestCredentialManagerErrorHandling(unittest.TestCase):
    """Test credential manager error handling scenarios."""

    def test_config_manager_error_scenarios(self) -> None:
        """Test config manager with various error scenarios."""
        test_cases = [
            ("corrupted_json", b"\x00\x01\x02\x03", None),
            ("invalid_json", "invalid json content", None),
            ("permission_error", '{"test": "data"}', PermissionError("Access denied")),
            ("is_directory", None, None),  # Special case handled in setup
        ]

        for error_type, file_content, mock_exception in test_cases:
            with self.subTest(case=error_type):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "credentials.json"

                    if error_type == "is_directory":
                        config_path.mkdir(parents=True, exist_ok=True)
                    elif file_content is not None:
                        if isinstance(file_content, bytes):
                            config_path.write_bytes(file_content)
                        else:
                            config_path.write_text(file_content)

                    manager = ConfigFileCredentialManager(config_path)

                    if mock_exception:
                        with patch("builtins.open", side_effect=mock_exception):
                            with self.assertRaises(Exception):  # ConfigurationError expected
                                manager.get_database_credentials("test.host", 443)
                    else:
                        with self.assertRaises(Exception):  # ConfigurationError expected
                            manager.get_database_credentials("test.host", 443)


if __name__ == "__main__":
    unittest.main()
