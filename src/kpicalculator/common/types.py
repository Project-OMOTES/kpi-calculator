# src/kpicalculator/common/types.py
"""Common type definitions and data structures."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class DatabaseCredentials:
    """Database connection credentials."""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    database: str = "energy_profiles"
    ssl: bool = False
    verify_ssl: bool = False