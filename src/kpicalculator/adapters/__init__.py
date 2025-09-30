# src/kpicalculator/adapters/__init__.py
"""Adapters for loading data from different sources."""

from ..common.types import DatabaseCredentials
from .base_adapter import BaseAdapter, ValidationResult
from .common_model import Asset, AssetType, EnergySystem, TimeSeries
from .database_time_series_loader import DatabaseTimeSeriesLoader
from .esdl_adapter import EsdlAdapter
from .time_series_manager import TimeSeriesManager

__all__ = [
    "BaseAdapter",
    "ValidationResult",
    "DatabaseTimeSeriesLoader",
    "DatabaseCredentials",
    "EsdlAdapter",
    "TimeSeriesManager",
    "Asset",
    "AssetType",
    "EnergySystem",
    "TimeSeries",
]
