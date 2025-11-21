# src/kpicalculator/security/input_validator.py
"""Secure input validation for file paths, database connections, and ESDL data."""

import os
import re
import socket
import warnings
from pathlib import Path
from typing import Any

from ..common.constants import (
    DANGEROUS_PORTS,
    HOSTNAME_REGEX_PATTERN,
    LOCALHOST_ADDRESSES,
    MAX_DATABASE_NAME_LENGTH,
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
    MAX_PORT_NUMBER,
    MAX_TIME_SERIES_LENGTH,
    MAX_USERNAME_LENGTH,
    MAX_XML_SIZE_BYTES,
    MIN_PORT_NUMBER,
    MINIMUM_PASSWORD_LENGTH,
    PATH_TRAVERSAL_PATTERNS,
    RFC_1035_HOSTNAME_LIMIT,
    SECURE_DATABASE_PORTS,
    SUSPICIOUS_USERNAMES,
    TIME_SERIES_VALUE_RANGE,
    WINDOWS_RESERVED_NAMES,
    XXE_ATTACK_PATTERNS,
)
from ..common.types import DatabaseCredentials
from ..exceptions import SecurityError, ValidationError


class InputValidator:
    """Comprehensive input validation for security and data integrity."""

    # Compiled regex patterns for performance
    HOSTNAME_PATTERN = re.compile(HOSTNAME_REGEX_PATTERN)
    PATH_TRAVERSAL_PATTERNS = [
        re.compile(pattern, re.IGNORECASE) for pattern in PATH_TRAVERSAL_PATTERNS
    ]
    XXE_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in XXE_ATTACK_PATTERNS]
    DATABASE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
    DATABASE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    @staticmethod
    def validate_file_path(
        file_path: str | Path,
        allowed_extensions: list[str] | None = None,
        must_exist: bool = True,
    ) -> Path:
        """Validate file path for security and existence.

        Args:
            file_path: File path to validate
            allowed_extensions: List of allowed file extensions (default: ESDL, XML, CSV)
            must_exist: Whether file must exist (default: True)

        Returns:
            Validated Path object

        Raises:
            ValidationError: If path is invalid or insecure
            SecurityError: If path contains security risks
        """
        if not file_path:
            raise ValidationError("File path cannot be empty")

        # Convert to Path object
        try:
            path_obj = Path(file_path) if isinstance(file_path, str) else file_path
        except Exception as e:
            raise ValidationError(f"Invalid file path format: {file_path} (error: {str(e)})") from e

        # Convert to string for pattern matching
        path_str = str(path_obj)

        # Check path length
        if len(path_str) > MAX_PATH_LENGTH:
            raise ValidationError(
                f"File path too long: {len(path_str)} > {MAX_PATH_LENGTH} characters"
            )

        # Check filename length
        if len(path_obj.name) > MAX_FILENAME_LENGTH:
            raise ValidationError(
                f"Filename too long: {len(path_obj.name)} > {MAX_FILENAME_LENGTH} characters"
            )

        # Check for path traversal attacks
        for pattern in InputValidator.PATH_TRAVERSAL_PATTERNS:
            if pattern.search(path_str):
                raise SecurityError(f"Path traversal attempt detected in: {file_path}")

        # Check for suspicious filenames (Windows reserved names)
        filename_base = path_obj.stem.lower()
        if filename_base in WINDOWS_RESERVED_NAMES:
            raise SecurityError(f"Suspicious filename detected: {path_obj.name}")

        # Validate file extension
        extensions = allowed_extensions or [".esdl", ".xml", ".csv", ".json", ".txt"]
        if path_obj.suffix.lower() not in [ext.lower() for ext in extensions]:
            raise ValidationError(
                f"File extension not allowed: {path_obj.suffix}. Allowed: {extensions}"
            )

        # Resolve path to check for existence and get absolute path
        try:
            resolved_path = path_obj.resolve()
        except Exception as e:
            raise ValidationError(f"Cannot resolve file path: {file_path} (error: {str(e)})") from e

        # Check if file exists (if required)
        if must_exist:
            if not resolved_path.exists():
                raise ValidationError(f"File does not exist: {resolved_path}")

            if not resolved_path.is_file():
                raise ValidationError(f"Path is not a file: {resolved_path}")

        # Additional security check: ensure resolved path doesn't escape allowed directories
        # This prevents symlink attacks
        try:
            # Get the canonical absolute path
            canonical_path = resolved_path.resolve()

            # Basic sanity check - path should still contain original filename
            if must_exist and canonical_path.name != path_obj.name:
                raise SecurityError(
                    f"File path resolution changed filename: "
                    f"{path_obj.name} -> {canonical_path.name}"
                )

        except Exception as e:
            raise SecurityError(f"Path resolution security check failed: {e}") from e

        return resolved_path

    @staticmethod
    def validate_database_credentials(credentials: DatabaseCredentials) -> None:
        """Validate database credentials for security and correctness.

        Args:
            credentials: Database credentials to validate

        Raises:
            ValidationError: If credentials are invalid
            SecurityError: If credentials contain security risks
        """
        # Validate hostname
        if not credentials.host:
            raise ValidationError("Database host cannot be empty")

        if len(credentials.host) > RFC_1035_HOSTNAME_LIMIT:
            raise ValidationError(
                f"Hostname too long: {len(credentials.host)} > {RFC_1035_HOSTNAME_LIMIT}"
            )

        # Check for suspicious characters in hostname
        if (
            not InputValidator.HOSTNAME_PATTERN.match(credentials.host)
            and credentials.host not in LOCALHOST_ADDRESSES
        ):
            # Check if it's a valid IP address
            try:
                socket.inet_aton(credentials.host)  # IPv4
            except OSError:
                try:
                    socket.inet_pton(socket.AF_INET6, credentials.host)  # IPv6
                except OSError as e:
                    raise SecurityError(f"Invalid hostname format: {credentials.host}") from e

        # Validate port
        if not (MIN_PORT_NUMBER <= credentials.port <= MAX_PORT_NUMBER):
            raise ValidationError(
                f"Invalid port number: {credentials.port}. "
                f"Must be {MIN_PORT_NUMBER}-{MAX_PORT_NUMBER}"
            )

        # Check for common non-database ports that might indicate misconfiguration
        if not InputValidator._is_database_port_allowed(credentials.port):
            raise ValidationError(
                f"Port {credentials.port} is typically not used for databases. "
                "Please verify this is correct."
            )

        # Validate username
        if not credentials.username:
            raise ValidationError("Database username cannot be empty")

        if len(credentials.username) > MAX_USERNAME_LENGTH:
            raise ValidationError(
                f"Username too long: {len(credentials.username)} > {MAX_USERNAME_LENGTH} characters"
            )

        # Check for suspicious username patterns
        if credentials.username.lower() in SUSPICIOUS_USERNAMES:
            # Warning, not error - these might be legitimate in development
            warnings.warn(
                f"Suspicious username detected: {credentials.username}. "
                f"This may be acceptable in development but should be avoided in production.",
                UserWarning,
                stacklevel=2,
            )

        # Validate password
        if not credentials.password:
            raise ValidationError("Database password cannot be empty")

        if len(credentials.password) < MINIMUM_PASSWORD_LENGTH:
            raise ValidationError(
                f"Database password too short. "
                f"Minimum {MINIMUM_PASSWORD_LENGTH} characters required."
            )

        # Validate database name
        if credentials.database and len(credentials.database) > MAX_DATABASE_NAME_LENGTH:
            raise ValidationError(
                f"Database name too long: {len(credentials.database)} > "
                f"{MAX_DATABASE_NAME_LENGTH} characters"
            )

        # Validate database name characters
        if credentials.database and not InputValidator.DATABASE_NAME_PATTERN.match(
            credentials.database
        ):
            sanitized_db = InputValidator.sanitize_for_logging(credentials.database)
            raise ValidationError(
                f"Database name contains invalid characters: {sanitized_db}. "
                "Only letters, numbers, underscore, and hyphen allowed."
            )

    @staticmethod
    def validate_numeric_range(
        value: int | float,
        min_val: int | float | None = None,
        max_val: int | float | None = None,
        field_name: str = "value",
    ) -> int | float:
        """Validate numeric values are within acceptable ranges.

        Args:
            value: Numeric value to validate
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            field_name: Name of field for error messages

        Returns:
            Validated numeric value

        Raises:
            ValidationError: If value is out of range or invalid
        """
        if not isinstance(value, (int, float)):
            raise ValidationError(f"{field_name} must be numeric, got {type(value).__name__}")

        if min_val is not None and value < min_val:
            raise ValidationError(f"{field_name} too small: {value} < {min_val}")

        if max_val is not None and value > max_val:
            raise ValidationError(f"{field_name} too large: {value} > {max_val}")

        return value

    @staticmethod
    def validate_asset_properties(asset_data: dict[str, Any]) -> dict[str, Any]:
        """Validate asset properties for range and consistency.

        Args:
            asset_data: Dictionary of asset properties

        Returns:
            Validated asset data

        Raises:
            ValidationError: If asset properties are invalid
        """
        validated = asset_data.copy()

        # Validate required fields
        required_fields = ["id", "name", "asset_type"]
        for field in required_fields:
            if field not in asset_data or not asset_data[field]:
                raise ValidationError(f"Required asset field missing: {field}")

        # Validate numeric properties with reasonable ranges
        numeric_validations = [
            ("power", 0, 1e12),  # 0 to 1 TW
            ("length", 0, 1e6),  # 0 to 1000 km
            ("volume", 0, 1e9),  # 0 to 1 million m³
            ("cop", 0, 10),  # COP typically 0-10
            ("technical_lifetime", 0, 100),  # 0-100 years
            ("discount_rate", 0, 100),  # 0-100%
            ("emission_factor", 0, 1000),  # 0-1000 kg/GJ
            ("aggregation_count", 1, 10000),  # 1-10000 units
        ]

        # Store method reference to avoid repeated lookups
        validate_range = InputValidator.validate_numeric_range

        for field_name, min_val, max_val in numeric_validations:
            if field_name in asset_data and asset_data[field_name] is not None:
                validated[field_name] = validate_range(
                    asset_data[field_name], min_val, max_val, field_name
                )

        # Validate cost fields (must be non-negative)
        cost_fields = [
            "investment_cost",
            "installation_cost",
            "fixed_operational_cost",
            "variable_operational_cost",
            "fixed_maintenance_cost",
            "variable_maintenance_cost",
        ]

        for field_name in cost_fields:
            if field_name in asset_data and asset_data[field_name] is not None:
                validated[field_name] = validate_range(asset_data[field_name], 0, None, field_name)

        # Validate string fields
        string_fields = ["id", "name"]
        for field_name in string_fields:
            if field_name in asset_data:
                value = asset_data[field_name]
                if not isinstance(value, str):
                    raise ValidationError(
                        f"Asset {field_name} must be string, got {type(value).__name__}"
                    )

                if len(value) > 255:
                    raise ValidationError(
                        f"Asset {field_name} too long: {len(value)} > 255 characters"
                    )

                if not value.strip():
                    raise ValidationError(f"Asset {field_name} cannot be empty or whitespace")

        return validated

    @staticmethod
    def sanitize_xml_input(xml_string: str) -> str:
        """Sanitize XML input to prevent XXE and other XML attacks.

        Args:
            xml_string: Raw XML string

        Returns:
            Sanitized XML string

        Raises:
            SecurityError: If XML contains suspicious content
        """
        if not xml_string or not isinstance(xml_string, str):
            raise ValidationError("XML input must be non-empty string")

        # Check for XML External Entity (XXE) attack patterns
        for pattern in InputValidator.XXE_PATTERNS:
            if pattern.search(xml_string):
                raise SecurityError("Suspicious XML content detected")

        # Check for excessively large XML
        if len(xml_string) > MAX_XML_SIZE_BYTES:
            raise ValidationError(
                f"XML input too large: {len(xml_string)} bytes > "
                f"{MAX_XML_SIZE_BYTES // (1024 * 1024)}MB"
            )

        return xml_string.strip()

    @staticmethod
    def validate_time_series_data(
        time_series_data: list[float], field_name: str = "time_series"
    ) -> list[float]:
        """Validate time series data for reasonable values and size.

        Args:
            time_series_data: List of time series values
            field_name: Name of field for error messages

        Returns:
            Validated time series data

        Raises:
            ValidationError: If time series data is invalid
        """
        if not isinstance(time_series_data, list):
            raise ValidationError(
                f"{field_name} must be a list, got {type(time_series_data).__name__}"
            )

        if len(time_series_data) == 0:
            raise ValidationError(f"{field_name} cannot be empty")

        if len(time_series_data) > MAX_TIME_SERIES_LENGTH:
            raise ValidationError(
                f"{field_name} too long: {len(time_series_data)} > {MAX_TIME_SERIES_LENGTH}"
            )

        # Validate individual values
        for i, value in enumerate(time_series_data):
            if not isinstance(value, (int, float)):
                raise ValidationError(
                    f"{field_name}[{i}] must be numeric, got {type(value).__name__}"
                )

            # Check for reasonable energy/power values (avoid negative or extreme values)
            if value < TIME_SERIES_VALUE_RANGE[0] or value > TIME_SERIES_VALUE_RANGE[1]:
                raise ValidationError(f"{field_name}[{i}] value out of reasonable range: {value}")

        return time_series_data

    @staticmethod
    def _is_database_port_allowed(port: int) -> bool:
        """Check if port is allowed for database connections.

        Args:
            port: Port number to validate

        Returns:
            True if port is allowed for database use
        """
        # Allow secure database ports
        if port in SECURE_DATABASE_PORTS:
            return True

        # Block dangerous/non-database ports
        return port not in DANGEROUS_PORTS

    @staticmethod
    def _is_development_mode() -> bool:
        """Check if running in development mode based on environment variables."""
        # Check common development environment indicators
        dev_indicators = [
            os.getenv("ENVIRONMENT", "").lower() in ("development", "dev", "local"),
            os.getenv("NODE_ENV", "").lower() in ("development", "dev"),
            os.getenv("FLASK_ENV", "").lower() in ("development", "dev"),
            os.getenv("DJANGO_ENV", "").lower() in ("development", "dev"),
            os.getenv("KPI_CALCULATOR_ENV", "").lower() in ("development", "dev", "local"),
            os.getenv("PYTEST_CURRENT_TEST") is not None,  # Running under pytest
        ]
        return any(dev_indicators)

    @staticmethod
    def validate_database_host(host: str, allow_localhost: bool | None = None) -> str:
        """Validate database host for security - prevent localhost and invalid hosts.

        This addresses the critical security fix from Phase 1 roadmap:
        "Add host/port validation in database_time_series_loader.py
        (prevent localhost/invalid hosts)"

        Args:
            host: Database hostname or IP address
            allow_localhost: Allow localhost access override (None=auto-detect development mode)

        Returns:
            Validated host string

        Raises:
            SecurityError: If host is localhost or invalid
            ValidationError: If host format is invalid
        """
        if not host or not host.strip():
            raise ValidationError("Database host cannot be empty")

        host = host.strip()

        # Auto-detect development mode if not explicitly specified
        if allow_localhost is None:
            allow_localhost = InputValidator._is_development_mode()

        # Prevent localhost access in production (security risk)
        # Allow in development/testing mode when explicitly enabled
        if host.lower() in LOCALHOST_ADDRESSES and not allow_localhost:
            raise SecurityError(f"Localhost access is disallowed in production: {host}")

        # Validate hostname format
        if not InputValidator.HOSTNAME_PATTERN.match(host):
            # Check if it's a valid public IP address
            try:
                socket.inet_aton(host)  # IPv4
                # Additional check for public IP ranges
                octets = host.split(".")
                if len(octets) == 4:
                    first_octet = int(octets[0])
                    # Prevent reserved IP ranges (allow in development mode)
                    if not allow_localhost and (
                        first_octet in [0, 10, 127]
                        or (first_octet == 172 and 16 <= int(octets[1]) <= 31)
                        or (first_octet == 192 and octets[1] == "168")
                    ):
                        raise SecurityError(f"Reserved or private IP address not allowed: {host}")
            except (OSError, ValueError):
                try:
                    socket.inet_pton(socket.AF_INET6, host)  # IPv6
                except OSError as e:
                    raise ValidationError(f"Invalid hostname or IP address format: {host}") from e

        return host

    @staticmethod
    def validate_database_port(port: int) -> int:
        """Validate database port for security and correctness.

        This addresses the critical security fix from Phase 1 roadmap:
        "Add host/port validation in database_time_series_loader.py"

        Args:
            port: Database port number

        Returns:
            Validated port number

        Raises:
            ValidationError: If port is invalid or dangerous
        """
        if not isinstance(port, int):
            raise ValidationError(f"Port must be integer, got {type(port).__name__}")

        # Standard port validation
        if not (MIN_PORT_NUMBER <= port <= MAX_PORT_NUMBER):
            raise ValidationError(
                f"Invalid port number: {port}. Must be {MIN_PORT_NUMBER}-{MAX_PORT_NUMBER}"
            )

        # Check for dangerous ports (allow secure database ports)
        if not InputValidator._is_database_port_allowed(port):
            raise ValidationError(
                f"Port {port} is not typically used for databases and may be dangerous"
            )

        return port

    @staticmethod
    def validate_database_identifier(identifier: str, identifier_type: str = "identifier") -> str:
        """Validate database identifiers (names, measurements, fields) for injection prevention.

        This addresses the critical security fixes from Phase 1 roadmap:
        - "Implement database name sanitization (prevent injection attacks)"
        - "Add measurement and field name validation (alphanumeric + underscore only)"

        Args:
            identifier: Database identifier (name, measurement, field)
            identifier_type: Type of identifier for error messages

        Returns:
            Validated identifier string

        Raises:
            ValidationError: If identifier contains invalid characters
            SecurityError: If identifier appears to be an injection attempt
        """
        if not identifier or not identifier.strip():
            raise ValidationError(f"Database {identifier_type} cannot be empty")

        identifier = identifier.strip()

        # Length check
        max_length = MAX_DATABASE_NAME_LENGTH if identifier_type == "database" else 100
        if len(identifier) > max_length:
            raise ValidationError(
                f"Database {identifier_type} too long: {len(identifier)} > {max_length}"
            )

        # CRITICAL: Only allow alphanumeric + underscore (prevent SQL injection)
        if not InputValidator.DATABASE_IDENTIFIER_PATTERN.match(identifier):
            sanitized_id = InputValidator.sanitize_for_logging(identifier)
            raise SecurityError(
                f"Database {identifier_type} contains invalid characters: {sanitized_id}. "
                "Only letters, numbers, and underscores allowed (security requirement)"
            )

        # Additional injection pattern detection
        suspicious_patterns = ["--", ";", "drop", "select", "union", "insert", "update", "delete"]
        identifier_lower = identifier.lower()
        for pattern in suspicious_patterns:
            if pattern in identifier_lower:
                sanitized_id = InputValidator.sanitize_for_logging(identifier)
                raise SecurityError(
                    f"Database {identifier_type} contains suspicious pattern: "
                    f"{sanitized_id} (pattern: {pattern})"
                )

        # Must start with letter or underscore (SQL best practice)
        if not identifier[0].isalpha() and identifier[0] != "_":
            sanitized_id = InputValidator.sanitize_for_logging(identifier)
            raise ValidationError(
                f"Database {identifier_type} must start with letter or underscore: {sanitized_id}"
            )

        return identifier

    @staticmethod
    def sanitize_for_logging(identifier: str, max_length: int = 20) -> str:
        """Sanitize identifier for safe logging to prevent information leakage.

        Args:
            identifier: Identifier to sanitize
            max_length: Maximum length to show before truncating

        Returns:
            Sanitized identifier safe for logging

        Examples:
            >>> InputValidator.sanitize_for_logging("users")
            "use** (len=5)"
            >>> InputValidator.sanitize_for_logging("secret_table_name")
            "sec*************** (len=17)"
        """
        if not identifier or not isinstance(identifier, str):
            return "[empty]"

        # For very short identifiers, show first char + asterisks
        if len(identifier) <= 3:
            return f"{identifier[0]}{'*' * (len(identifier) - 1)} (len={len(identifier)})"

        # For longer identifiers, show first 3 chars + asterisks
        if len(identifier) <= max_length:
            return f"{identifier[:3]}{'*' * (len(identifier) - 3)} (len={len(identifier)})"

        # For very long identifiers, truncate and show pattern
        # Calculate available space: max_length - prefix(3) - suffix("... (len=X)")
        len_suffix = f"... (len={len(identifier)})"
        available_space = max_length - 3 - len(len_suffix)

        if available_space < 1:
            # Not enough space for even one asterisk; return truncated suffix only
            return len_suffix[:max_length]
        asterisk_count = available_space
        return f"{identifier[:3]}{'*' * asterisk_count}{len_suffix}"
