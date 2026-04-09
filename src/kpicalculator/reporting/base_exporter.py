"""Base exporter interface for KPI results."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from esdl import esdl

from ..kpi_manager import KpiResults


class BaseExporter(ABC):
    """Abstract base class for KPI result exporters."""

    @abstractmethod
    def export(
        self,
        results: KpiResults,
        esdl_energy_system: esdl.EnergySystem,
        destination: str | Path | None = None,
    ) -> bool | Any:
        """Export KPI results to specified destination.

        Args:
            results: KPI calculation results.
            esdl_energy_system: Parsed PyESDL energy system object to write KPIs into.
            destination: Export destination (file path, etc.). If None, return data structure.

        Returns:
            bool: True if file export succeeded.
            Any: Data structure if destination is None.

        Raises:
            ValueError: If required parameters are missing or invalid.
        """
        ...
