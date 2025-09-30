# src/kpicalculator/adapters/time_series_protocols.py
"""Protocols for time series data providers.

This module defines clear interfaces for objects that can provide time series data,
eliminating the need for runtime attribute checking and improving type safety.
"""

from typing import Protocol


class TimeSeriesProvider(Protocol):
    """Protocol for objects that can provide time series data.

    This protocol defines the expected interface for any adapter that can
    provide time series data for energy system assets. Implementing this
    protocol ensures type safety and clear contracts.
    """

    def get_time_series(self, asset_id: str) -> list[float] | None:
        """Get time series data for a specific asset.

        Args:
            asset_id: Unique identifier for the asset

        Returns:
            List of numeric values representing time series data,
            or None if no data is available for the asset
        """
        ...

    @property
    def time_series(self) -> dict[str, list[float]]:
        """Access to all available time series data.

        Returns:
            Dictionary mapping asset IDs to their time series data
        """
        ...

    def get_time_series_with_parameters(self) -> dict[str, dict[str, tuple[list[float], float]]]:
        """Get all time series data organized by asset and parameter with time step info.

        Returns:
            Dictionary mapping asset_id -> parameter_name -> (values, time_step)
            Example: {"asset_1": {"ThermalConsumption": ([10.0, 20.0], 3600.0)}}
        """
        ...


class TimeSeriesMetadata(Protocol):
    """Protocol for time series providers that include metadata."""

    @property
    def time_step(self) -> float:
        """Time step in seconds between data points."""
        ...

    @property
    def start_time(self) -> str:
        """Start time of the time series in ISO format."""
        ...

    @property
    def end_time(self) -> str:
        """End time of the time series in ISO format."""
        ...
