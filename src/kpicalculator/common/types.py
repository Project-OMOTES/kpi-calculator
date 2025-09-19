# src/kpicalculator/common/types.py
"""Common type definitions and data structures."""

from dataclasses import dataclass


@dataclass
class DatabaseCredentials:
    """Database connection credentials."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    database: str = "energy_profiles"
    ssl: bool = False
    verify_ssl: bool = False
