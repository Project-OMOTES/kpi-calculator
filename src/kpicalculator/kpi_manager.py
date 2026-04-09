# src/kpicalculator/kpi_manager.py
import logging
from typing import Any, TypedDict, cast

import pandas as pd  # type: ignore[import-untyped]
from esdl import esdl

from .adapters.common_model import EnergySystem
from .adapters.esdl_adapter import EsdlAdapter
from .adapters.simulator_adapter import SimulatorAdapter
from .calculators.emission_calculator import EmissionCalculator
from .calculators.energy_calculator import EnergyCalculator
from .calculators.financial_calculator import (
    PRODUCER_ASSET_TYPES,
    AssetFinancialResult,
    FinancialCalculator,
)
from .common.constants import (
    DEFAULT_DISCOUNT_RATE_PERCENT,
    DEFAULT_SYSTEM_LIFETIME_YEARS,
)

# Public API of this module — controls re-exports recognised by mypy and static analysers.
__all__ = [
    "AssetFinancialResult",
    "EmissionResults",
    "EnergyResults",
    "FinancialResults",
    "KpiManager",
    "KpiResults",
]

_logger = logging.getLogger(__name__)


class FinancialResults(TypedDict):
    """System-level financial KPI results.

    All monetary values are in EUR or EUR/year. Each field is the sum of the
    corresponding per-asset value across all assets in the system (except
    ``lcoe``, which is computed as ``sum(per-asset NPVs) / total_discounted_energy``
    and is therefore *not* the average of per-asset LCOEs).

    ``capex`` and ``opex`` are broken down by asset category:
    ``"Production"``, ``"Consumption"``, ``"Storage"``, ``"Transport"``,
    ``"Conversion"``, and ``"All"`` (the system-wide sum).
    """

    capex: dict[str, float]
    """CAPEX by asset category in EUR (investment + installation costs)."""
    opex: dict[str, float]
    """Annual OPEX by asset category in EUR/year (fixed + variable costs)."""
    npv: float
    """Net Present Value — discounted lifecycle cost in EUR."""
    lcoe: float
    """Levelized Cost of Energy in EUR/MWh (``system_npv / discounted_energy``).

    ``system_npv`` is the sum of per-asset NPVs, each discounted at the
    asset's own rate (from ESDL ``costInformation.discountRate``, falling back
    to the system default). It is not the average of per-asset LCOEs.
    """
    eac: float
    """Equivalent Annual Cost — sum of per-asset annualized costs in EUR/year."""
    tco: float
    """Total Cost of Ownership — undiscounted lifecycle cost in EUR."""


class EnergyResults(TypedDict):
    """System-level energy KPI results. All values in Joules."""

    consumption: float
    """Total thermal energy consumed by all consumer assets in J."""
    demand: float
    """Total thermal energy demand from all consumer assets in J."""
    production: float
    """Total thermal energy produced by all producer assets in J."""
    efficiency: float
    """Distribution efficiency: consumption / production (0-1). Zero when production is zero."""


class EmissionResults(TypedDict):
    """System-level emission KPI results."""

    total: float
    """Total greenhouse gas emissions in tonnes CO2e/year."""
    per_mwh: float
    """Emission intensity in kg CO2e/MWh of energy consumed."""


class KpiResults(TypedDict):
    """Complete KPI results returned by ``KpiManager.calculate_all_kpis()`` and the
    top-level ``kpicalculator.calculate_kpis()`` function.

    Four top-level keys:

    - ``financials``: system-level monetary KPIs (CAPEX, OPEX, NPV, LCOE, EAC, TCO)
    - ``energy``: system-level energy totals in Joules
    - ``emissions``: system-level CO2e emissions
    - ``asset_financials``: per-asset financial breakdown keyed by asset ID;
      system totals in ``financials`` are derived by summing these values
    """

    financials: FinancialResults
    energy: EnergyResults
    emissions: EmissionResults
    asset_financials: dict[str, AssetFinancialResult]


class KpiManager:
    """Main class for managing KPI calculations across different data sources.

    Cost unit conversion factors (EUR/kW, EUR/MW, EUR/km, EUR/kWh, EUR/MWh,
    % OF CAPEX, etc.) are built-in and used by the cost calculator when
    computing KPI values from ESDL costInformation elements.
    """

    def __init__(self) -> None:
        """Initialize the KPI manager."""
        self.energy_system: EnergySystem | None = None
        self.source_esdl_file: str | None = None

    def load_from_esdl(
        self,
        esdl_file: str,
        time_series_file: str | None = None,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        """Load energy system data from ESDL file.

        Cost data is extracted from ESDL costInformation elements.

        Note:
            InfluxDB profile loading is disabled here. To enable it, call
            ``EsdlAdapter().load_data(..., use_database_profiles=True)`` directly.

        Args:
            esdl_file: Path to ESDL file
            time_series_file: Optional path to time series file (when
                timeseries_dataframes not provided)
            timeseries_dataframes: Optional dict mapping asset IDs to pandas
                DataFrames with time-indexed energy/power data. When provided,
                takes precedence over database loading and time_series_file.
        """
        adapter = EsdlAdapter()
        self.energy_system = adapter.load_data(
            esdl_file,
            time_series_file=time_series_file,
            timeseries_dataframes=timeseries_dataframes,
            use_database_profiles=False,
        )
        self.source_esdl_file = esdl_file

    def load_from_esdl_string(
        self,
        esdl_string: str,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        """Load energy system data from ESDL XML string content.

        This method allows loading ESDL data directly from a string without
        needing a temporary file. Useful for integration with systems that
        provide ESDL content in memory (e.g., simulator_worker).

        Cost data is extracted from ESDL costInformation elements.

        Args:
            esdl_string: ESDL XML content as a string
            timeseries_dataframes: Optional dict mapping asset IDs to pandas
                DataFrames with time-indexed energy/power data.
        """
        adapter = EsdlAdapter()
        self.energy_system = adapter.load_from_string(
            esdl_string,
            timeseries_dataframes=timeseries_dataframes,
        )
        self.source_esdl_file = None

    def load_from_simulator(
        self,
        simulator_result: pd.DataFrame,
        esdl_string: str,
    ) -> None:
        """Load energy system data from OMOTES Simulator results.

        Converts the simulator's port-indexed DataFrame to the asset-indexed
        common model and extracts cost data from the supplied ESDL string.

        Args:
            simulator_result: DataFrame produced by the simulator, with a
                DatetimeIndex and ``(port_id, property_name)`` tuple columns.
            esdl_string: The input ESDL as an XML string, used to resolve
                port IDs to their owning assets and to extract cost data.
        """
        adapter = SimulatorAdapter()
        self.energy_system = adapter.load_data(simulator_result, esdl_string=esdl_string)
        self.source_esdl_file = None

    def load_from_mesido(self, _mesido_data: Any) -> None:
        """Load energy system data from mesido data structure.

        Args:
            _mesido_data: Mesido data structure (unused, placeholder for future implementation)
        """
        # TODO: Implement mesido adapter
        raise NotImplementedError("Mesido adapter not implemented yet")

    def calculate_all_kpis(
        self,
        system_lifetime: float = DEFAULT_SYSTEM_LIFETIME_YEARS,
        discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
        round_up_replacement: bool = True,
    ) -> KpiResults:
        """Calculate all KPIs for the energy system.

        Raises:
            ValueError: If no energy system is loaded, ``system_lifetime <= 0``,
                or ``discount_rate`` is outside [0, 100].

        Args:
            system_lifetime: System lifetime in years. Must be positive.
                Default: ``DEFAULT_SYSTEM_LIFETIME_YEARS``.
            discount_rate: System-wide fallback discount rate in percentage
                (e.g. 5 for 5%). Must be in [0, 100]. Individual assets may
                override this via ``costInformation.discountRate`` in the ESDL
                — this method respects those overrides because it uses
                ``get_asset_financial_breakdown()`` internally. Note that
                calling ``FinancialCalculator.calculate_npv()`` directly does
                not respect per-asset overrides.
                Default: ``DEFAULT_DISCOUNT_RATE_PERCENT``.
            round_up_replacement: If True (default), NPV, LCOE, and TCO use
                ``ceil`` for the asset replacement count — the financially exact
                calculation. If False, uses the continuous factor
                ``max(1, system_lifetime / technical_lifetime)`` for
                compatibility with MESIDO optimizer output. Only set this to
                False when comparing results against MESIDO.

        Returns:
            ``KpiResults`` dict with ``financials``, ``energy``, ``emissions``,
            and ``asset_financials`` keys.
        """
        if not self.energy_system:
            raise ValueError("No energy system loaded. Call one of the load methods first.")
        if system_lifetime <= 0:
            raise ValueError(f"system_lifetime must be positive (got {system_lifetime}).")
        if discount_rate < 0 or discount_rate > 100:
            raise ValueError(f"discount_rate must be between 0 and 100 (got {discount_rate}).")

        cost_calc = FinancialCalculator(self.energy_system)
        energy_calc = EnergyCalculator(self.energy_system)
        emission_calc = EmissionCalculator(self.energy_system)

        # Pre-compute annual energy production (MWh) for generating assets so
        # FinancialCalculator can compute per-asset LCOE in its single pass.
        # Non-generating assets are omitted; FinancialCalculator treats a missing key as 0.
        annual_energy_mwh_by_asset = {
            asset.id: energy_calc.get_asset_energy_production_per_year(asset) / 3.6e9
            for asset in self.energy_system.assets
            if asset.asset_type in PRODUCER_ASSET_TYPES
        }

        asset_financials = cost_calc.get_asset_financial_breakdown(
            system_lifetime,
            discount_rate,
            round_up_replacement=round_up_replacement,
            annual_energy_mwh_by_asset=annual_energy_mwh_by_asset,
        )

        system_npv = 0.0
        system_eac = 0.0
        system_tco = 0.0
        for r in asset_financials.values():
            system_npv += r["npv"]
            system_eac += r["eac"]
            system_tco += r["tco"]
        capex_by_cat, opex_by_cat = cost_calc.aggregate_by_category(asset_financials)

        results: KpiResults = {
            "financials": {
                "capex": capex_by_cat,
                "opex": opex_by_cat,
                "npv": system_npv,
                # System LCOE = total NPV / total discounted energy — not a sum of per-asset LCOEs.
                "lcoe": cost_calc.calculate_lcoe(
                    system_lifetime,
                    discount_rate,
                    round_up_replacement=round_up_replacement,
                    system_npv=system_npv,
                ),
                "eac": system_eac,
                # TCO is intentionally undiscounted — discount_rate is not used.
                "tco": system_tco,
            },
            "energy": {
                "consumption": energy_calc.get_total_energy_consumption_per_year(),
                "demand": energy_calc.get_total_energy_demand_per_year(),
                "production": energy_calc.get_total_energy_production_per_year(),
                "efficiency": energy_calc.calculate_system_efficiency(),
            },
            "emissions": {
                "total": emission_calc.get_total_emissions(),
                "per_mwh": emission_calc.get_emissions_per_mwh(),
            },
            "asset_financials": asset_financials,
        }

        no_asset_has_time_series = not any(asset.time_series for asset in self.energy_system.assets)
        if no_asset_has_time_series:
            _logger.warning(
                "No time series data found for any asset. All energy and emission KPIs "
                "will be 0.0. Provide time_series_file or timeseries_dataframes to "
                "load_from_esdl(), or use load_from_esdl_string() with dataframes."
            )

        return results

    def _warn_if_level_not_system(self, level: str) -> None:
        """Emit a warning when a non-system export level is requested.

        Area-level and asset-level KPI placement are not yet implemented;
        all levels currently fall back to system-wide export.
        """
        if level != "system":
            _logger.warning(
                "KPI export level '%s' is not yet implemented; falling back to 'system'.", level
            )

    def export_to_esdl(
        self, results: KpiResults, output_file: str | None = None, level: str = "system"
    ) -> bool | esdl.EnergySystem:
        """Export KPI results to ESDL format.

        Args:
            results: KPI calculation results from calculate_all_kpis()
            output_file: Output ESDL file path. If None, returns data structure.
            level: KPI granularity — ``'system'``, ``'area'``, or ``'asset'``.
                Currently all levels write system-wide KPIs to the main area;
                area-level and asset-level placement are not yet implemented.

        Returns:
            bool: True if file export succeeded (when output_file provided)
            esdl.EnergySystem: ESDL data structure (when output_file is None)

        Raises:
            ValueError: If no energy system is loaded or invalid parameters
        """
        if not self.energy_system:
            raise ValueError("No energy system loaded. Call one of the load methods first.")
        if self.energy_system.esdl_energy_system is None:
            raise ValueError(
                "No ESDL object available; the loaded adapter did not store one "
                "(e.g. load_from_simulator). Use load_from_esdl() or "
                "load_from_esdl_string(), or use build_esdl_string_with_kpis() "
                "to embed KPIs into an ESDL string without a loaded manager."
            )

        self._warn_if_level_not_system(level)

        from .reporting.esdl_kpi_exporter import EsdlKpiExporter

        return EsdlKpiExporter().export(
            results,
            self.energy_system.esdl_energy_system,
            output_file,
            level=level,
        )

    def build_esdl_with_kpis(self, results: KpiResults, level: str = "system") -> esdl.EnergySystem:
        """Build an ESDL energy system data structure with KPI results embedded.

        Args:
            results: KPI calculation results from calculate_all_kpis()
            level: KPI granularity — ``'system'``, ``'area'``, or ``'asset'``.
                Currently all levels write system-wide KPIs to the main area;
                area-level and asset-level placement are not yet implemented.

        Returns:
            esdl.EnergySystem: ESDL data structure with KPIs

        Raises:
            ValueError: If no energy system is loaded or invalid parameters
        """
        result = self.export_to_esdl(results, output_file=None, level=level)
        if not isinstance(result, esdl.EnergySystem):
            raise ValueError("Failed to generate ESDL data structure")
        return result

    def build_esdl_string_with_kpis(
        self, esdl_string: str, results: KpiResults, level: str = "system"
    ) -> str:
        """Embed KPI results into an ESDL XML string and return the updated string.

        This is the preferred integration method for systems that work with ESDL
        strings (e.g. simulator-worker). It operates entirely on a local
        ``EnergySystemHandler`` parsed from ``esdl_string`` and does not modify
        any manager state, making it safe to call repeatedly on the same instance.

        Args:
            esdl_string: Input ESDL XML string to embed KPIs into.
            results: KPI calculation results from calculate_all_kpis()
            level: KPI granularity — ``'system'``, ``'area'``, or ``'asset'``.
                Currently all levels write system-wide KPIs to the main area;
                area-level and asset-level placement are not yet implemented.

        Returns:
            ESDL XML string with KPIs embedded.

        Raises:
            ValueError: If esdl_string is empty or invalid parameters are provided.
        """
        if not esdl_string.strip():
            raise ValueError("esdl_string must not be empty.")

        self._warn_if_level_not_system(level)

        from esdl.esdl_handler import EnergySystemHandler

        from .reporting.esdl_kpi_exporter import EsdlKpiExporter

        esh = EnergySystemHandler()
        esh.load_from_string(esdl_string)
        EsdlKpiExporter().export(results, esh.energy_system, destination=None, level=level)
        return cast(str, esh.to_string())


# TODO: Add method to save the results
