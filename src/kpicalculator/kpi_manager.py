# src/kpicalculator/kpi_manager.py
import logging
from typing import Any, TypedDict

import pandas as pd  # type: ignore[import-untyped]
from esdl import esdl

from .adapters.common_model import EnergySystem
from .adapters.esdl_adapter import EsdlAdapter
from .adapters.simulator_adapter import SimulatorAdapter
from .common.constants import DEFAULT_SYSTEM_LIFETIME_YEARS

_logger = logging.getLogger(__name__)


class CostResults(TypedDict):
    """Results structure for cost calculations."""

    capex: dict[str, float]
    opex: dict[str, float]
    npv: float
    lcoe: float


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

    costs: CostResults
    energy: EnergyResults
    emissions: EmissionResults


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
        self, system_lifetime: float = DEFAULT_SYSTEM_LIFETIME_YEARS
    ) -> KpiResults:
        """Calculate all KPIs for the energy system.

        Args:
            system_lifetime: System lifetime in years

        Returns:
            Dictionary with all KPI results
        """
        if not self.energy_system:
            raise ValueError("No energy system loaded. Call one of the load methods first.")

        from .calculators.cost_calculator import CostCalculator
        from .calculators.emission_calculator import EmissionCalculator
        from .calculators.energy_calculator import EnergyCalculator

        cost_calc = CostCalculator(self.energy_system)
        energy_calc = EnergyCalculator(self.energy_system)
        emission_calc = EmissionCalculator(self.energy_system)

        results: KpiResults = {
            "costs": {
                "capex": cost_calc.get_capex_by_category(),
                "opex": cost_calc.get_opex_by_category(),
                "npv": cost_calc.calculate_npv(system_lifetime),
                "lcoe": cost_calc.calculate_lcoe(system_lifetime),
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


# TODO: Add method to save the results
