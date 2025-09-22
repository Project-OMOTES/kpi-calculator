# src/kpicalculator/common/types.py
"""Common type definitions and data structures."""

import re
import socket
import warnings

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatabaseCredentials(BaseModel):
    """Database connection credentials with automatic validation.

    This Pydantic model provides automatic validation for database credentials,
    ensuring security and correctness of connection parameters.
    """

    host: str = Field(..., min_length=1, max_length=253, description="Database hostname or IP")
    port: int = Field(..., ge=1, le=65535, description="Database port number")
    username: str | None = Field(None, min_length=1, max_length=64, description="Database username")
    password: str | None = Field(None, min_length=8, description="Database password")
    database: str = Field(
        default="energy_profiles", pattern=r"^[a-zA-Z0-9_-]+$", description="Database name"
    )
    ssl: bool = Field(default=False, description="Use SSL connection")
    verify_ssl: bool = Field(default=False, description="Verify SSL certificate")

    @field_validator("host")
    @classmethod
    def validate_host_format(cls, v: str) -> str:
        """Validate hostname format (IP address or valid hostname)."""
        v = v.strip()

        # Try to validate as IP address first
        try:
            socket.inet_aton(v)  # Valid IPv4
            return v
        except OSError:
            try:
                socket.inet_pton(socket.AF_INET6, v)  # Valid IPv6
                return v
            except OSError:
                pass

        # Validate as hostname
        hostname_pattern = re.compile(r"^[a-zA-Z0-9.-]+$")
        if not hostname_pattern.match(v):
            raise ValueError(f"Invalid hostname format: {v}")

        return v

    @field_validator("port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Validate port is in valid range and warn for unusual ports."""
        # Standard database ports for reference
        common_db_ports = {3306, 5432, 1521, 1433, 3389, 27017, 6379, 8086}

        if v not in common_db_ports and v < 1024:
            # Log warning for unusual ports (but don't fail)
            warnings.warn(
                f"Port {v} is unusual for database connections. "
                "Consider using a standard port unless you have a specific reason.",
                UserWarning,
                stacklevel=2,
            )

        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str | None) -> str | None:
        """Validate password meets minimum security requirements."""
        if v is None:
            return v

        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")

        return v

    model_config = ConfigDict(
        validate_assignment=True,  # Validate on attribute changes
        extra="forbid",  # Forbid extra fields
    )


class AssetProperties(BaseModel):
    """Asset properties with comprehensive validation.

    This model replaces the manual validation in InputValidator.validate_asset_properties()
    with automatic Pydantic validation, providing better error messages and type safety.
    """

    # Required fields
    id: str = Field(..., min_length=1, max_length=255, description="Unique asset identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Asset display name")
    asset_type: str = Field(..., min_length=1, max_length=100, description="Type of energy asset")

    # Optional numeric properties with realistic ranges
    power: float | None = Field(None, ge=0, le=1e12, description="Power capacity (0 to 1 TW)")
    length: float | None = Field(None, ge=0, le=1e6, description="Length (0 to 1000 km)")
    volume: float | None = Field(None, ge=0, le=1e9, description="Volume (0 to 1 million m³)")
    cop: float | None = Field(None, ge=0, le=10, description="Coefficient of Performance (0-10)")
    technical_lifetime: float | None = Field(
        None, ge=0, le=100, description="Technical lifetime (0-100 years)"
    )
    discount_rate: float | None = Field(None, ge=0, le=100, description="Discount rate (0-100%)")
    emission_factor: float | None = Field(
        None, ge=0, le=1000, description="Emission factor (0-1000 kg/GJ)"
    )
    aggregation_count: int | None = Field(
        None, ge=1, le=10000, description="Aggregation count (1-10000 units)"
    )

    # Cost fields (must be non-negative)
    investment_cost: float | None = Field(None, ge=0, description="Investment cost")
    installation_cost: float | None = Field(None, ge=0, description="Installation cost")
    fixed_operational_cost: float | None = Field(None, ge=0, description="Fixed operational cost")
    variable_operational_cost: float | None = Field(
        None, ge=0, description="Variable operational cost"
    )
    fixed_maintenance_cost: float | None = Field(None, ge=0, description="Fixed maintenance cost")
    variable_maintenance_cost: float | None = Field(
        None, ge=0, description="Variable maintenance cost"
    )

    @field_validator("id", "name")
    @classmethod
    def validate_string_fields(cls, v: str) -> str:
        """Validate string fields are not empty or whitespace."""
        if not v.strip():
            raise ValueError("Field cannot be empty or whitespace")
        return v.strip()

    @field_validator("power")
    @classmethod
    def validate_power_realistic(cls, v: float | None) -> float | None:
        """Validate power values and warn for very large values."""
        if v is None:
            return v

        if v > 1e9:  # Warning for very large values (>1 GW)
            warnings.warn(f"Very large power value: {v:,.0f} W", UserWarning, stacklevel=2)

        return v

    @field_validator("technical_lifetime")
    @classmethod
    def validate_lifetime_realistic(cls, v: float | None) -> float | None:
        """Validate technical lifetime values."""
        if v is None:
            return v

        if v > 50:  # Warning for unusually long lifetimes
            warnings.warn(
                f"Unusually long technical lifetime: {v} years", UserWarning, stacklevel=2
            )

        return v

    model_config = ConfigDict(
        validate_assignment=True,  # Validate on attribute changes
        extra="forbid",  # Forbid extra fields
        str_strip_whitespace=True,  # Automatically strip whitespace from strings
    )


class TimeSeriesData(BaseModel):
    """Time series data with validation for energy/power values.

    Replaces InputValidator.validate_time_series_data() with Pydantic validation.
    """

    values: list[float] = Field(
        ..., min_length=1, max_length=8760 * 24, description="Time series values"
    )
    field_name: str = Field(default="time_series", description="Name of the time series field")

    @field_validator("values")
    @classmethod
    def validate_time_series_values(cls, v: list[float]) -> list[float]:
        """Validate individual time series values are within reasonable ranges."""
        # Reasonable energy/power value range (prevent negative or extreme values)
        min_val, max_val = -1e6, 1e12  # -1 MW to 1 TW

        for i, value in enumerate(v):
            if not isinstance(value, (int, float)):
                raise ValueError(f"time_series[{i}] must be numeric, got {type(value).__name__}")

            if value < min_val or value > max_val:
                raise ValueError(f"time_series[{i}] value out of reasonable range: {value}")

        return v

    model_config = ConfigDict(validate_assignment=True)
