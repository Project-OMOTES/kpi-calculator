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

_logger = logging.getLogger(__name__)


class FinancialResults(TypedDict):
    """System-level financial KPI results. All values are sums over assets."""

    capex: dict[str, float]
    opex: dict[str, float]
    npv: float
    lcoe: float
    eac: float
    tco: float


class EnergyResults(TypedDict):
    """Results structure for energy calculations."""

    consumption: float
    demand: float
    production: float
    efficiency: float


class EmissionResults(TypedDict):
    """Results structure for emission calculations."""

    total: float
    per_mwh: float


class KpiResults(TypedDict):
    """Complete KPI results structure."""

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
            discount_rate: Discount rate in percentage (e.g. 5 for 5%). Must be in [0, 100].
            round_up_replacement: If True (default), NPV, LCOE, and TCO use ``ceil``
                for the asset replacement count (financially exact). If False, uses the
                continuous factor ``max(1, n / technical_lifetime)`` for optimizer
                compatibility.

        Returns:
            Dictionary with all KPI results.
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

    def export_to_esdl(
        self, results: KpiResults, output_file: str | None = None, level: str = "system"
    ) -> bool | esdl.EnergySystem:
        """Export KPI results to ESDL format.

        Args:
            results: KPI calculation results from calculate_all_kpis()
            output_file: Output ESDL file path. If None, returns data structure.
            level: KPI level ('system', 'area', 'asset')

        Returns:
            bool: True if file export succeeded (when output_file provided)
            esdl.EnergySystem: ESDL data structure (when output_file is None)

        Raises:
            ValueError: If no energy system is loaded or invalid parameters
        """
        if not self.energy_system:
            raise ValueError("No energy system loaded. Call one of the load methods first.")

        from .reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        return exporter.export(
            results,
            self.energy_system,
            output_file,
            level=level,
            source_esdl_file=self.source_esdl_file,
        )

    def build_esdl_with_kpis(self, results: KpiResults, level: str = "system") -> esdl.EnergySystem:
        """Build an ESDL energy system data structure with KPI results embedded.

        Args:
            results: KPI calculation results from calculate_all_kpis()
            level: KPI level ('system', 'area', 'asset')

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
        strings (e.g. simulator-worker). It avoids the need to manipulate internal
        adapter state and produces a self-contained output string.

        Args:
            esdl_string: Input ESDL XML string to embed KPIs into.
            results: KPI calculation results from calculate_all_kpis()
            level: KPI level ('system', 'area', 'asset')

        Returns:
            ESDL XML string with KPIs embedded.

        Raises:
            ValueError: If no energy system is loaded, esdl_string is empty,
                or invalid parameters are provided.
        """
        if not self.energy_system:
            raise ValueError("No energy system loaded. Call one of the load methods first.")
        if not esdl_string.strip():
            raise ValueError("esdl_string must not be empty.")

        from esdl.esdl_handler import EnergySystemHandler

        from .reporting.esdl_kpi_exporter import EsdlKpiExporter

        esh = EnergySystemHandler()
        esh.load_from_string(esdl_string)

        # Redirect the exporter to the target ESDL object tree so KPIs are written
        # into the correct output. Safe because the exporter reads this attribute
        # once into a local variable; try/finally restores the original reference.
        original_esdl_energy_system = self.energy_system.esdl_energy_system
        self.energy_system.esdl_energy_system = esh.energy_system
        try:
            exporter = EsdlKpiExporter()
            exporter.export(results, self.energy_system, destination=None, level=level)
        finally:
            self.energy_system.esdl_energy_system = original_esdl_energy_system

        return cast(str, esh.to_string())


# TODO: Add method to save the results
