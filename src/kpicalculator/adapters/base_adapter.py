# src/kpicalculator/adapters/base_adapter.py
"""Base adapter interface for consistent data source integration."""

from abc import ABC, abstractmethod
from typing import Any

from ..common.constants import COST_UNIT_FACTORS
from .common_model import EnergySystem


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

    The base class enforces only the ``EnergySystem`` return type. Each concrete
    adapter defines its own typed ``load_data()`` signature matching the inputs
    that its data source actually requires. Callers (e.g. ``KpiManager``) invoke
    the specific adapter directly rather than through this base interface, so
    there is no need to funnel every adapter's parameters through a single
    overly-broad signature.

    All adapters must implement:
        - ``load_data()`` — typed per adapter, returns ``EnergySystem``
        - ``validate_source()`` — returns ``ValidationResult``
        - ``get_supported_source_type()`` — returns a short string identifier
    """

    def __init__(self) -> None:
        """Initialize adapter with built-in cost unit conversion factors."""
        self.unit_conversions: dict[str, float] = dict(COST_UNIT_FACTORS)

    @abstractmethod
    def load_data(self, source: Any, **kwargs: Any) -> EnergySystem:
        """Load data from source and convert to the common model.

        Concrete adapters narrow ``source: Any`` to their actual input type.
        Always call through the concrete adapter type — never through a
        ``BaseAdapter`` reference — or the narrowed signature will not apply.

        Returns:
            EnergySystem object with standardised data model.

        Raises:
            ValidationError: If source data is invalid.
            DataSourceError: If data loading fails.
        """

    @abstractmethod
    def validate_source(self, source: Any) -> ValidationResult:
        """Validate that source data is compatible with this adapter.

        Args:
            source: Data source to validate.

        Returns:
            ValidationResult indicating if source is valid.
        """

    @abstractmethod
    def get_supported_source_type(self) -> str:
        """Return a short identifier for this adapter's source type.

        Returns:
            String identifier, e.g. ``"esdl"``, ``"mesido"``, ``"simulator"``.
        """

    def get_supported_parameters(self) -> list[str]:
        """Return optional parameter names accepted by ``load_data``.

        Returns:
            List of parameter names this adapter supports beyond ``source``.
        """
        return []

    def _validate_energy_system(self, energy_system: EnergySystem) -> ValidationResult:
        """Validate the constructed energy system for consistency.

        Intended to be called by concrete ``load_data`` implementations after
        the ``EnergySystem`` has been built, so that warnings about empty
        systems or invalid asset properties are surfaced uniformly.

        Args:
            energy_system: The constructed EnergySystem object.

        Returns:
            ValidationResult with validation status and messages.
        """
        errors = []
        warnings = []

        if not energy_system.assets:
            warnings.append("Energy system contains no assets")

        for asset in energy_system.assets:
            if asset.technical_lifetime <= 0:
                errors.append(
                    f"Asset {asset.id} has invalid technical lifetime: {asset.technical_lifetime}"
                )
            if asset.power < 0:
                errors.append(f"Asset {asset.id} has negative power: {asset.power}")

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)
