# src/kpicalculator/adapters/simulator_adapter.py
"""Adapter for OMOTES Simulator results."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
from esdl import esdl  # type: ignore[import-untyped]
from esdl.esdl_handler import EnergySystemHandler  # type: ignore[import-untyped]

from ..exceptions import ValidationError
from .base_adapter import BaseAdapter, ValidationResult
from .common_model import EnergySystem

logger = logging.getLogger(__name__)


class SimulatorAdapter(BaseAdapter):
    """Adapter for OMOTES Simulator results.

    Converts the simulator's port-indexed DataFrame to the asset-indexed common
    model expected by the KPI calculators.

    The simulator produces a DataFrame with ``(port_id, property_name)`` tuple
    columns — one column per simulated property per port. The KPI calculator
    works in terms of assets, not ports. This adapter bridges the two
    representations by resolving port IDs to their owning assets via ESDL
    object tree traversal, then delegates cost and asset extraction to
    :class:`~kpicalculator.adapters.esdl_adapter.EsdlAdapter`.

    Keeping this logic inside the adapter means that if the KPI calculator's
    internal time series contract (e.g. ``KNOWN_TIME_SERIES_FIELDS``) changes,
    only this adapter needs updating — not the simulator worker.

    Usage::

        adapter = SimulatorAdapter()
        energy_system = adapter.load_data(simulator_result_df, esdl_string=input_esdl)
        kpi_manager = KpiManager()
        kpi_manager.energy_system = energy_system
        results = kpi_manager.calculate_all_kpis()
    """

    def load_data(  # type: ignore[override]  # narrows source: Any → pd.DataFrame intentionally
        self,
        source: pd.DataFrame,
        esdl_string: str,
        **kwargs: Any,
    ) -> EnergySystem:
        """Load simulator results into the common model.

        Args:
            source: DataFrame produced by the simulator, with a DatetimeIndex
                and columns as ``(port_id, property_name)`` tuples.
            esdl_string: The input ESDL as an XML string, used both to resolve
                port IDs to their owning assets and to extract cost / system data.

        Returns:
            EnergySystem with asset costs from ESDL and time series from the
            simulator DataFrame.

        Raises:
            ValidationError: If ``esdl_string`` is empty or ``source`` is not a
                DataFrame containing ``(port_id, property_name)`` tuple columns.
        """
        if not esdl_string.strip():
            raise ValidationError("esdl_string is required for SimulatorAdapter.load_data()")

        validation = self.validate_source(source)
        if not validation.is_valid:
            raise ValidationError(f"Invalid simulator result: {validation.errors}")

        # Parse once — reuse the same object for both port→asset resolution
        # and cost extraction via EsdlAdapter.load_from_esdl_object().
        esh = EnergySystemHandler()
        try:
            es = esh.load_from_string(esdl_string)
        except Exception as e:
            raise ValidationError(f"Failed to parse ESDL string: {e}") from e

        # Convert (port_id, property) columns → asset_id-keyed DataFrames.
        timeseries_by_asset = self._convert_to_asset_dataframes(source, es)

        # Delegate to EsdlAdapter for asset/cost extraction, passing the
        # already-parsed object so no second XML parse is needed.
        from .esdl_adapter import EsdlAdapter

        return EsdlAdapter().load_from_esdl_object(
            es,
            timeseries_dataframes=timeseries_by_asset,
        )

    def validate_source(self, source: Any) -> ValidationResult:  # type: ignore[override]
        """Validate the simulator result DataFrame.

        Args:
            source: Expected to be a pandas DataFrame with ``(port_id, property_name)``
                tuple columns.

        Returns:
            ValidationResult indicating if the source is usable.
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(source, pd.DataFrame):
            errors.append(
                f"SimulatorAdapter expects a pandas DataFrame, got {type(source).__name__}"
            )
            return ValidationResult(False, errors, warnings)

        if source.empty:
            warnings.append("Simulator result DataFrame is empty — no time series will be loaded")
            return ValidationResult(True, errors, warnings)

        tuple_columns = [col for col in source.columns if isinstance(col, tuple) and len(col) == 2]
        if not tuple_columns:
            warnings.append(
                "No (port_id, property_name) tuple columns found in simulator result. "
                "Ensure the DataFrame uses the simulator's MultiIndex column format."
            )

        return ValidationResult(True, errors, warnings)

    def get_supported_source_type(self) -> str:
        """Return identifier for the simulator adapter."""
        return "simulator"

    def get_supported_parameters(self) -> list[str]:
        """Return optional parameter names accepted by load_data beyond ``source``."""
        return ["esdl_string"]

    def _convert_to_asset_dataframes(
        self,
        simulator_result: pd.DataFrame,
        energy_system: esdl.EnergySystem,
    ) -> dict[str, pd.DataFrame]:
        """Map ``(port_id, property)`` columns to asset-id-keyed DataFrames.

        For each ``(port_id, property_name)`` column:

        1. Find the asset that owns ``port_id`` via ESDL tree traversal.
        2. Append the column to that asset's DataFrame under ``property_name``.

        Columns that are not 2-tuples are skipped silently (e.g. a plain
        ``"datetime"`` column that was not yet converted to a DatetimeIndex).
        Ports that cannot be matched to any asset are skipped with a warning.

        Args:
            simulator_result: Simulator output DataFrame.
            energy_system: Parsed ESDL energy system for port-to-asset lookup.

        Returns:
            Dict mapping ``asset_id`` → time-indexed DataFrame of property columns.
        """
        # Build a port_id → asset_id lookup once so each column resolves in O(1)
        # rather than walking the full ESDL tree for every (port, property) column.
        port_to_asset: dict[str, str] = {
            port.id: item.id
            for item in energy_system.eAllContents()
            if isinstance(item, esdl.Asset)
            for port in item.port
        }

        asset_data: dict[str, pd.DataFrame] = {}
        processed = 0
        skipped = 0

        for col in simulator_result.columns:
            if not isinstance(col, tuple) or len(col) != 2:
                continue
            port_id, property_name = col
            asset_id = port_to_asset.get(port_id)
            if asset_id is None:
                logger.warning(
                    "Could not find asset for port %s (property %s) — skipped",
                    port_id,
                    property_name,
                )
                skipped += 1
                continue
            processed += 1

            if asset_id not in asset_data:
                asset_data[asset_id] = pd.DataFrame(index=simulator_result.index)
            asset_data[asset_id][property_name] = simulator_result[col]

        logger.info(
            "Converted simulator format: %d assets, %d properties processed, %d skipped",
            len(asset_data),
            processed,
            skipped,
        )
        return asset_data
