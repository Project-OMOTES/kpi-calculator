# src/kpicalculator/kpi_manager.py
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import pandas as pd

from .adapters.common_model import Asset
from .adapters.common_model import EnergySystem


class KpiManager:
    """Main class for managing KPI calculations across different data sources."""

    def __init__(self, unit_conversion_file: Optional[str] = None):
        """Initialize the KPI manager.

        Args:
            unit_conversion_file: Path to CSV file with unit conversion factors
        """
        self.energy_system = None
        self.unit_conversion = {}

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
        self, esdl_file: str, time_series_file: str, pipes_cost_file: str, assets_cost_file: str
    ) -> None:
        """Load energy system data from ESDL file.

        Args:
            esdl_file: Path to ESDL file
            time_series_file: Path to time series file
            pipes_cost_file: Path to pipes cost CSV file
            assets_cost_file: Path to assets cost CSV file
        """
        from .adapters.esdl_adapter import EsdlAdapter

        adapter = EsdlAdapter(self.unit_conversion)
        self.energy_system = adapter.load(
            esdl_file, time_series_file, pipes_cost_file, assets_cost_file
        )

    def load_from_simulator(self, simulator_data: Any) -> None:
        """Load energy system data from simulator data structure.

        Args:
            simulator_data: Simulator data structure
        """
        from .adapters.simulator_adapter import SimulatorAdapter

        adapter = SimulatorAdapter(self.unit_conversion)
        self.energy_system = adapter.load(simulator_data)

    def load_from_mesido(self, mesido_data: Any) -> None:
        """Load energy system data from mesido data structure.

        Args:
            mesido_data: Mesido data structure
        """
        from .adapters.mesido_adapter import MesidoAdapter

        adapter = MesidoAdapter(self.unit_conversion)
        self.energy_system = adapter.load(mesido_data)

    def calculate_all_kpis(self, system_lifetime: int = 30) -> Dict[str, Any]:
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

        results = {
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
