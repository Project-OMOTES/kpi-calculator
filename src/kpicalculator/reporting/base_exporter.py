"""Base exporter interface for KPI results."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..adapters.common_model import EnergySystem
from ..kpi_manager import KpiResults


class BaseExporter(ABC):
    """Abstract base class for KPI result exporters."""

    @abstractmethod
    def export(
        self,
        results: KpiResults,
        energy_system: EnergySystem,
        destination: str | Path | None = None,
        **kwargs: Any,
    ) -> bool | Any:
        """Export KPI results to specified destination.

        Args:
            results: KPI calculation results
            energy_system: Energy system with metadata
            destination: Export destination (file path, etc.). If None, return data structure.
            **kwargs: Additional export parameters

        Returns:
            bool: True if file export succeeded, False otherwise
            Any: Data structure if destination is None

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        pass
