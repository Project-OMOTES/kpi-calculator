# src/kpicalculator/security/credential_manager.py
"""Secure credential management for database connections."""

import json
import os
import stat
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from ..common.types import DatabaseCredentials
from ..exceptions import SecurityError, CredentialError, ConfigurationError


logger = logging.getLogger(__name__)


class CredentialManager(ABC):
    """Abstract base class for credential management."""
    
    @abstractmethod
    def get_database_credentials(self, host: str, port: int) -> Optional[DatabaseCredentials]:
        """Get database credentials for host:port combination.
        
        Args:
            host: Database host
            port: Database port
            
        Returns:
            DatabaseCredentials if found, None otherwise
        """
        pass


class SecureCredentialManager(CredentialManager):
    """Secure credential management using environment variables."""
    
    def get_database_credentials(self, host: str, port: int) -> Optional[DatabaseCredentials]:
        """Load credentials from environment variables.
        
        Environment variable format:
        KPI_DB_{HOST}_{PORT}_{FIELD}
        
        Where HOST has dots and hyphens replaced with underscores and is uppercase.
        
        Args:
            host: Database host (e.g., "wu-profiles.esdl-beta.hesi.energy")
            port: Database port (e.g., 443)
            
        Returns:
            DatabaseCredentials if environment variables are set, None otherwise
        """
        # Normalize host for environment variable naming
        normalized_host = host.replace('.', '_').replace('-', '_').upper()
        env_prefix = f"KPI_DB_{normalized_host}_{port}"
        
        username = os.getenv(f"{env_prefix}_USERNAME")
        password = os.getenv(f"{env_prefix}_PASSWORD")
        database = os.getenv(f"{env_prefix}_DATABASE", "energy_profiles")
        ssl_env = os.getenv(f"{env_prefix}_SSL", "false").lower()
        verify_ssl_env = os.getenv(f"{env_prefix}_VERIFY_SSL", "false").lower()
        
        if not username or not password:
            logger.debug(f"No credentials found in environment for {host}:{port}")
            return None
        
        # Parse boolean values
        ssl = ssl_env in ("true", "1", "yes", "on")
        verify_ssl = verify_ssl_env in ("true", "1", "yes", "on")
        
        logger.info(f"Loaded credentials from environment for {host}:{port}")
        
        return DatabaseCredentials(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            ssl=ssl,
            verify_ssl=verify_ssl
        )


class ConfigFileCredentialManager(CredentialManager):
    """Load credentials from secure configuration files."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize with optional config file path.
        
        Args:
            config_path: Path to credentials config file. 
                        Defaults to ~/.kpi-calculator/credentials.json
        """
        self.config_path = config_path or Path.home() / ".kpi-calculator" / "credentials.json"
        self._cached_credentials: Optional[Dict[str, DatabaseCredentials]] = None
        
    def get_database_credentials(self, host: str, port: int) -> Optional[DatabaseCredentials]:
        """Get credentials from config file.
        
        Args:
            host: Database host
            port: Database port
            
        Returns:
            DatabaseCredentials if found in config, None otherwise
        """
        credentials = self._load_credentials()
        host_port_key = f"{host}:{port}"
        
        if host_port_key in credentials:
            logger.info(f"Loaded credentials from config file for {host}:{port}")
            return credentials[host_port_key]
        
        logger.debug(f"No credentials found in config file for {host}:{port}")
        return None
    
    def _load_credentials(self) -> Dict[str, DatabaseCredentials]:
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
            logger.info(f"Credentials config file not found: {self.config_path}")
            self._cached_credentials = {}
            return self._cached_credentials
        
        # Validate file permissions for security
        self._validate_file_permissions()
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise ConfigurationError(
                f"Invalid JSON in credentials file: {self.config_path}",
                context={"error": str(e)}
            ) from e
        except Exception as e:
            raise ConfigurationError(
                f"Failed to read credentials file: {self.config_path}",
                context={"error": str(e)}
            ) from e
        
        # Parse and validate credentials
        credentials = {}
        databases_config = config.get('databases', {})
        
        for host_port, creds_config in databases_config.items():
            try:
                credentials[host_port] = DatabaseCredentials(
                    host=creds_config['host'],
                    port=creds_config['port'],
                    username=creds_config['username'],
                    password=creds_config['password'],
                    database=creds_config.get('database', 'energy_profiles'),
                    ssl=creds_config.get('ssl', False),
                    verify_ssl=creds_config.get('verify_ssl', False)
                )
            except (KeyError, TypeError) as e:
                raise ConfigurationError(
                    f"Invalid credential configuration for {host_port}",
                    context={"error": str(e), "config": creds_config}
                ) from e
        
        self._cached_credentials = credentials
        logger.info(f"Loaded {len(credentials)} credential entries from config file")
        
        return credentials
    
    def _validate_file_permissions(self) -> None:
        """Validate that config file has secure permissions.
        
        Raises:
            SecurityError: If file permissions are too permissive
        """
        try:
            file_stat = self.config_path.stat()
            
            # Check if file is readable by group or others (Unix-like systems)
            if hasattr(stat, 'S_IRGRP') and hasattr(stat, 'S_IROTH'):
                if file_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
                    raise SecurityError(
                        f"Credentials file has insecure permissions: {self.config_path}. "
                        f"File should only be readable by owner (chmod 600).",
                        context={"file_mode": oct(file_stat.st_mode)[-3:]}
                    )
        except AttributeError:
            # Windows or other systems without detailed permission checking
            logger.warning(f"Cannot validate file permissions on this system: {self.config_path}")


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
        
    def get_database_credentials(self, host: str, port: int) -> Optional[DatabaseCredentials]:
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
        
        logger.warning(f"No credentials found for {host}:{port} in any manager")
        return None


def create_default_credential_manager() -> CredentialManager:
    """Create default credential manager with secure fallback chain.
    
    Returns:
        ChainedCredentialManager with environment variables as primary,
        config file as secondary fallback
    """
    return ChainedCredentialManager(
        SecureCredentialManager(),  # Primary: environment variables
        ConfigFileCredentialManager()  # Fallback: config file
    )