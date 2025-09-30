# src/kpicalculator/kpi_manager.py
from typing import Any, TypedDict

import pandas as pd  # type: ignore[import-untyped]

from .adapters.common_model import EnergySystem
from .common.constants import DEFAULT_SYSTEM_LIFETIME_YEARS


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
    """Main class for managing KPI calculations across different data sources."""

    def __init__(self, unit_conversion_file: str | None = None):
        """Initialize the KPI manager.

        Args:
            unit_conversion_file: Path to CSV file with unit conversion factors
        """
        self.energy_system: EnergySystem | None = None
        self.unit_conversion: dict[str, float] = {}

        if unit_conversion_file:
            self.load_unit_conversion(unit_conversion_file)

    def load_unit_conversion(self, file_path: str) -> None:
        """Load unit conversion factors from CSV file.

        Args:
            file_path: Path to CSV file with unit conversion factors
        """
        unit_conversion_df = pd.read_csv(file_path)
        for _, row in unit_conversion_df.iterrows():
            self.unit_conversion[row["Unit"]] = row["Factor"]

    def load_from_esdl(
        self,
        esdl_file: str,
        pipes_cost_file: str,
        assets_cost_file: str,
        time_series_file: str | None = None,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        """Load energy system data from ESDL file.

        Args:
            esdl_file: Path to ESDL file
            pipes_cost_file: Path to pipes cost CSV file
            assets_cost_file: Path to assets cost CSV file
            time_series_file: Optional path to time series file (when
                timeseries_dataframes not provided)
            timeseries_dataframes: Optional dict mapping asset IDs to pandas
                DataFrames with time-indexed energy/power data. When provided,
                takes precedence over database loading and time_series_file.
        """
        from .adapters.esdl_adapter import EsdlAdapter

        adapter = EsdlAdapter(self.unit_conversion)
        self.energy_system = adapter.load_data(
            esdl_file,
            time_series_file=time_series_file,
            pipes_cost_file=pipes_cost_file,
            assets_cost_file=assets_cost_file,
            timeseries_dataframes=timeseries_dataframes,
            use_database_profiles=False,  # Disable database profiles for testing
        )

    def load_from_simulator(self, simulator_data: Any) -> None:
        """Load energy system data from simulator data structure.

        Args:
            simulator_data: Simulator data structure
        """
        # TODO: Implement simulator adapter
        raise NotImplementedError("Simulator adapter not implemented yet")

    def load_from_mesido(self, mesido_data: Any) -> None:
        """Load energy system data from mesido data structure.

        Args:
            mesido_data: Mesido data structure
        """
        # TODO: Implement mesido adapter
        raise NotImplementedError("Mesido adapter not implemented yet")

    def calculate_all_kpis(
        self, system_lifetime: int = DEFAULT_SYSTEM_LIFETIME_YEARS
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

        return results


# TODO: Add method to save the results
