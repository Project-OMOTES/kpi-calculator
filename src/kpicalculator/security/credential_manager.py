# src/kpicalculator/security/credential_manager.py
"""Secure credential management for database connections."""

import json
import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path

from ..common.logging_utils import get_database_logger, get_security_logger
from ..common.types import DatabaseCredentials
from ..exceptions import ConfigurationError, SecurityError


class CredentialManager(ABC):
    """Abstract base class for credential management."""

    @abstractmethod
    def get_database_credentials(self, host: str, port: int) -> DatabaseCredentials | None:
        """Get database credentials for host:port combination.

        Args:
            host: Database host
            port: Database port

        Returns:
            DatabaseCredentials if found, None otherwise
        """
        pass

    @abstractmethod
    def supports_environment_credentials(self) -> bool:
        """Return True if this manager supports environment-based credentials.

        Returns:
            True if manager can read from environment variables
        """
        pass


class SecureCredentialManager(CredentialManager):
    """Secure credential management using environment variables."""

    def __init__(self) -> None:
        """Initialize the secure credential manager."""
        self.security_logger = get_security_logger()
        self.db_logger = get_database_logger("credential_manager")
        self._env_prefix_cache: dict[tuple[str, int], str] = {}

    def _get_env_prefix(self, host: str, port: int) -> str:
        """Get environment variable prefix for host:port (cached)."""
        cache_key = (host, port)
        if cache_key not in self._env_prefix_cache:
            normalized_host = host.replace(".", "_").replace("-", "_").upper()
            self._env_prefix_cache[cache_key] = f"KPI_DB_{normalized_host}_{port}"
        return self._env_prefix_cache[cache_key]

    def get_database_credentials(self, host: str, port: int) -> DatabaseCredentials | None:
        """Load credentials from environment variables.

        This method first attempts to load credentials using environment variables
        with the format KPI_DB_{HOST}_{PORT}_{FIELD}, where HOST is uppercased and
        dots/hyphens are replaced with underscores. If either the username or password
        is missing, it falls back to using INFLUXDB_* environment variables for
        compatibility with simulator-worker setups. The priority order is:
        1. KPI_DB_{HOST}_{PORT}_{FIELD} (primary)
        2. INFLUXDB_* (fallback if primary is incomplete)

        Args:
            host: Database host (e.g., "wu-profiles.esdl-beta.hesi.energy")
            port: Database port (e.g., 443)

        Returns:
            DatabaseCredentials if environment variables are set, None otherwise
        """
        env_prefix = self._get_env_prefix(host, port)

        # Try KPI_DB_* variables first (primary)
        username = os.getenv(f"{env_prefix}_USERNAME")
        password = os.getenv(f"{env_prefix}_PASSWORD")
        database = os.getenv(f"{env_prefix}_DATABASE")
        ssl_env = os.getenv(f"{env_prefix}_SSL")
        verify_ssl_env = os.getenv(f"{env_prefix}_VERIFY_SSL")

        # Fallback to INFLUXDB_* variables (simulator-worker compatibility)
        if not username or not password:
            username = username or os.getenv("INFLUXDB_USERNAME")
            password = password or os.getenv("INFLUXDB_PASSWORD")
            database = database or os.getenv("INFLUXDB_DATABASE")
            # INFLUXDB_HOSTNAME and INFLUXDB_PORT are informational only
            # (we already know host:port from the ESDL InfluxDBProfile)

        if not username or not password:
            self.db_logger.debug(
                "No credentials found in environment", {"host": host, "port": port}
            )
            return None

        # Set defaults
        database = database or "energy_profiles"
        ssl_env = (ssl_env or "false").lower()
        verify_ssl_env = (verify_ssl_env or "false").lower()

        # Parse boolean values
        ssl = ssl_env in ("true", "1", "yes", "on")
        verify_ssl = verify_ssl_env in ("true", "1", "yes", "on")

        self.security_logger.log_credential_access(host, port, "environment_variables")
        self.db_logger.log_credential_load(host, port, "environment")

        return DatabaseCredentials(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            ssl=ssl,
            verify_ssl=verify_ssl,
        )

    def supports_environment_credentials(self) -> bool:
        """Return True since this manager reads from environment variables."""
        return True


class ConfigFileCredentialManager(CredentialManager):
    """Load credentials from secure configuration files."""

    def __init__(self, config_path: Path | None = None):
        """Initialize with optional config file path.

        Args:
            config_path: Path to credentials config file.
                        Defaults to ~/.kpi-calculator/credentials.json
        """
        self.config_path = config_path or Path.home() / ".kpi-calculator" / "credentials.json"
        self._cached_credentials: dict[str, DatabaseCredentials] | None = None
        self.security_logger = get_security_logger()
        self.db_logger = get_database_logger("credential_manager")

    def get_database_credentials(self, host: str, port: int) -> DatabaseCredentials | None:
        """Get credentials from config file.

        Args:
            host: Database host
            port: Database port

        Returns:
            DatabaseCredentials if found in config, None otherwise
        """
        credentials = self._load_credentials()
        host_port_key = f"{host}: {port}"

        if host_port_key in credentials:
            self.security_logger.log_credential_access(host, port, "config_file")
            self.db_logger.log_credential_load(host, port, "config_file")
            return credentials[host_port_key]

        self.db_logger.debug("No credentials found in config file", {"host": host, "port": port})
        return None

    def _load_credentials(self) -> dict[str, DatabaseCredentials]:
        """Load credentials from config file with security validation.

        Returns:
            Dictionary mapping host:port to DatabaseCredentials

        Raises:
            SecurityError: If file permissions are insecure
            ConfigurationError: If config file is invalid
        """
        if self._cached_credentials is not None:
            return self._cached_credentials

        if not self.config_path.exists():
            self.db_logger.info(
                "Credentials config file not found", {"config_path": str(self.config_path)}
            )
            self._cached_credentials = {}
            return self._cached_credentials

        # Validate file permissions for security
        self._validate_file_permissions()

        try:
            with self.config_path.open(encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(
                f"Invalid JSON in credentials file: {self.config_path} (error: {str(e)})"
            ) from e
        except Exception as e:
            raise ConfigurationError(
                f"Failed to read credentials file: {self.config_path} (error: {str(e)})"
            ) from e

        # Parse and validate credentials
        credentials = {}
        databases_config = config.get("databases", {})

        for host_port, creds_config in databases_config.items():
            try:
                credentials[host_port] = DatabaseCredentials(
                    host=creds_config["host"],
                    port=creds_config["port"],
                    username=creds_config["username"],
                    password=creds_config["password"],
                    database=creds_config.get("database", "energy_profiles"),
                    ssl=creds_config.get("ssl", False),
                    verify_ssl=creds_config.get("verify_ssl", False),
                )
            except (KeyError, TypeError) as e:
                raise ConfigurationError(
                    f"Invalid credential configuration for {host_port} "
                    f"(error: {str(e)}, config: {creds_config})"
                ) from e

        self._cached_credentials = credentials
        self.db_logger.info(
            "Loaded credentials from config file",
            {"entry_count": len(credentials), "config_path": str(self.config_path)},
        )

        return credentials

    def _validate_file_permissions(self) -> None:
        """Validate that config file has secure permissions.

        Raises:
            SecurityError: If file permissions are too permissive
        """
        try:
            file_stat = self.config_path.stat()

            # Check if file is readable by group or others (Unix-like systems)
            if (
                hasattr(stat, "S_IRGRP")
                and hasattr(stat, "S_IROTH")
                and file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH)
            ):
                raise SecurityError(
                    f"Credentials file has insecure permissions: {self.config_path}. "
                    f"File should only be readable by owner (chmod 600). "
                    f"(file_mode: {oct(file_stat.st_mode)[-3:]})"
                )
        except AttributeError:
            # Windows or other systems without detailed permission checking
            self.security_logger.log_validation_failure(
                "file_permissions",
                str(self.config_path),
                "Cannot validate permissions on this platform",
                "low",
            )

    def supports_environment_credentials(self) -> bool:
        """Return False since this manager reads from config files, not environment."""
        return False


class ChainedCredentialManager(CredentialManager):
    """Chain multiple credential managers with fallback priority."""

    def __init__(self, *managers: CredentialManager):
        """Initialize with ordered list of credential managers.

        Args:
            *managers: Credential managers in priority order (first has highest priority)
        """
        if not managers:
            raise ValueError("At least one credential manager must be provided")

        self.managers = managers
        self.db_logger = get_database_logger("credential_manager")

    def get_database_credentials(self, host: str, port: int) -> DatabaseCredentials | None:
        """Try credential managers in order until credentials are found.

        Args:
            host: Database host
            port: Database port

        Returns:
            DatabaseCredentials from first manager that has them, None if none found
        """
        for manager in self.managers:
            credentials = manager.get_database_credentials(host, port)
            if credentials:
                return credentials

        self.db_logger.warning("No credentials found in any manager", {"host": host, "port": port})
        return None

    def supports_environment_credentials(self) -> bool:
        """Return True if any of the chained managers supports environment credentials."""
        return any(manager.supports_environment_credentials() for manager in self.managers)


def create_default_credential_manager() -> CredentialManager:
    """Create default credential manager with secure fallback chain.

    Returns:
        ChainedCredentialManager with environment variables as primary,
        config file as secondary fallback
    """
    return ChainedCredentialManager(
        SecureCredentialManager(),  # Primary: environment variables
        ConfigFileCredentialManager(),  # Fallback: config file
    )
