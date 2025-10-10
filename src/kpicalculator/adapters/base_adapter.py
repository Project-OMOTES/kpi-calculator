# src/kpicalculator/adapters/base_adapter.py
"""Base adapter interface for consistent data source integration."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

import pandas as pd  # type: ignore[import-untyped]

from .common_model import EnergySystem


class DatabaseReference(Protocol):
    """Protocol for database connection references."""

    host: str
    port: int
    database: str
    username: str | None
    password: str | None


class MesidoResultsProtocol(Protocol):
    """Protocol for MESIDO optimization results."""

    assets: dict[str, object]
    time_series: dict[str, object]
    parameters: dict[str, float]
    # Optional database reference for time series
    database_ref: DatabaseReference | None


class SimulatorResultsProtocol(Protocol):
    """Protocol for OMOTES Simulator results."""

    assets: dict[str, object]
    simulation_data: dict[str, object]
    time_series: dict[str, object]
    # Optional database reference for time series
    database_ref: DatabaseReference | None


class ValidationResult:
    """Result of input validation."""

    def __init__(
        self,
        is_valid: bool,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []


class BaseAdapter(ABC):
    """Abstract base class for all data source adapters.

    This interface ensures consistency across ESDL, MESIDO, and Simulator adapters.
    All adapters must implement these methods for standardized data loading.
    """

    def __init__(self, unit_conversions: dict[str, float] | None = None):
        """Initialize adapter with unit conversion factors.

        Args:
            unit_conversions: Dictionary of unit conversion factors
        """
        self.unit_conversions = unit_conversions or {}

    @abstractmethod
    def load_data(
        self,
        source: str | Path | MesidoResultsProtocol | SimulatorResultsProtocol,
        time_series_file: str | None = None,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
        use_database_profiles: bool = True,
    ) -> EnergySystem:
        """Load data from source and convert to common model.

        Args:
            source: Data source - can be:
                - str/Path: ESDL file path (may contain InfluxDB profile references)
                - MesidoResultsProtocol: MESIDO optimization results (data structures or DB refs)
                - SimulatorResultsProtocol: OMOTES Simulator results (data structures or DB refs)
            time_series_file: Optional XML time series file path (testing only)
            timeseries_dataframes: Optional dict mapping asset IDs to pandas DataFrames
                with time-indexed energy/power data. When provided, takes precedence
                over database loading and time_series_file parameter.
            use_database_profiles: Whether to load database-referenced time series

        Returns:
            EnergySystem object with standardized data model

        Raises:
            ValidationError: If source data is invalid
            DataSourceError: If data loading fails
        """
        pass

    @abstractmethod
    def validate_source(
        self, source: str | Path | MesidoResultsProtocol | SimulatorResultsProtocol
    ) -> ValidationResult:
        """Validate that source data is compatible with this adapter.

        Args:
            source: Data source to validate

        Returns:
            ValidationResult indicating if source is valid
        """
        pass

    @abstractmethod
    def get_supported_source_type(self) -> str:
        """Return identifier for this adapter's source type.

        Returns:
            String identifier (e.g., "esdl", "mesido", "simulator")
        """
        pass

    def get_supported_parameters(self) -> list[str]:
        """Return list of supported optional parameters for load_data.

        Returns:
            List of parameter names this adapter supports
        """
        return []

    def _validate_energy_system(self, energy_system: EnergySystem) -> ValidationResult:
        """Validate the constructed energy system for consistency.

        Args:
            energy_system: The constructed EnergySystem object

        Returns:
            ValidationResult with validation status and messages
        """
        errors = []
        warnings = []

        # Check for empty system
        if not energy_system.assets:
            warnings.append("Energy system contains no assets")

        # Validate asset properties
        for asset in energy_system.assets:
            if asset.technical_lifetime <= 0:
                errors.append(
                    f"Asset {asset.id} has invalid technical lifetime: {asset.technical_lifetime}"
                )

            if asset.power < 0:
                errors.append(f"Asset {asset.id} has negative power: {asset.power}")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
