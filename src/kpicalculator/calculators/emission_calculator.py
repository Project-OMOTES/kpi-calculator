# src/kpicalculator/calculators/emission_calculator.py
# No typing imports needed currently

from ..adapters.common_model import Asset, AssetType, EnergySystem
from ..common.constants import KG_TO_TONS, SECONDS_PER_YEAR, TONS_TO_KG


class EmissionCalculator:
    """Calculator for emission-related KPIs."""

    def __init__(self, energy_system: EnergySystem):
        """Initialize the emission calculator.

        Args:
            energy_system: Energy system to calculate KPIs for
        """
        self.energy_system = energy_system

    # def get_total_emissions(self) -> float:
    #     """Calculate total CO2 emissions.

    #     Returns:
    #         Total CO2 emissions in tons per year
    #     """
    #     total_emissions = 0.0

    #     for asset in self.energy_system.assets:
    #         total_emissions += self._calculate_asset_emissions(asset)

    #     return total_emissions

    def get_total_emissions(self) -> float:
        """Calculate total CO2 emissions.

        Returns:
            Total CO2 emissions in tons per year
        """
        total_emissions = 0.0

        for asset in self.energy_system.assets:
            total_emissions += self._calculate_asset_emissions(asset)

        return total_emissions

    def get_emissions_per_mwh(self) -> float:
        """Calculate CO2 emissions per MWh of energy consumed.

        Returns:
            CO2 emissions in kg/MWh
        """
        from .energy_calculator import EnergyCalculator

        energy_calc = EnergyCalculator(self.energy_system)
        energy_consumption = energy_calc.get_total_energy_consumption_per_year()

        if energy_consumption <= 0:
            return 0.0

        # Convert energy from J to MWh (1 MWh = 3.6e9 J)
        energy_consumption_mwh = energy_consumption / 3.6e9

        # Convert emissions from tons to kg
        emissions_kg = self.get_total_emissions() * TONS_TO_KG

        return emissions_kg / energy_consumption_mwh

    def get_emissions_per_energy_unit(self) -> float:
        """Calculate CO2 emissions per GJ of energy consumed.

        Returns:
            CO2 emissions in kg/GJ
        """
        from .energy_calculator import EnergyCalculator

        energy_calc = EnergyCalculator(self.energy_system)
        energy_consumption = energy_calc.get_total_energy_consumption_per_year()

        if energy_consumption <= 0:
            return 0.0

        # Convert energy from J to GJ (1 GJ = 1e9 J)
        energy_consumption_gj = energy_consumption / 1e9

        # Convert emissions from tons to kg
        emissions_kg = self.get_total_emissions() * TONS_TO_KG

        return emissions_kg / energy_consumption_gj

    def _calculate_asset_emissions(self, asset: Asset, annualize: bool = True) -> float:
        """Calculate CO2 emissions for a specific asset.

        Args:
            asset: Asset to calculate emissions for
            annualize: If True, scale emissions to a full year

        Returns:
            CO2 emissions in tons (annualized or for actual period)
        """
        if not asset.time_series:
            return 0.0

        # Select the correct time series key for the asset
        ts_options = {
            AssetType.PRODUCER: ["ThermalProduction", "Production", "Energy"],
            AssetType.GEOTHERMAL: ["ThermalProduction", "Production", "Energy"],
            AssetType.CONSUMER: ["ThermalConsumption", "Consumption", "Energy"],
            AssetType.CONVERSION: ["ElectricalConsumption", "ThermalProduction"],
        }
        ts_name = None
        options = ts_options.get(asset.asset_type, [])
        for key in options:
            if key in asset.time_series:
                ts_name = key
                break
        if not ts_name:
            return 0.0

        ts = asset.time_series[ts_name]
        duration = ts.time_step * len(ts.values)  # seconds
        if duration == 0:
            return 0.0

        # Calculate time factor for annualization
        time_factor = SECONDS_PER_YEAR / duration if annualize else 1

        # Calculate energy sum
        energy_sum = sum(ts.values) * ts.time_step  # Joules

        # Calculate emissions
        # The emission factor from adapter is in kg/J (already divided by 1e9)
        # We multiply directly by energy in Joules and time factor
        # The result is in kg, so we need to convert to tons
        emissions_kg = asset.emission_factor * energy_sum * time_factor  # kg
        return emissions_kg * KG_TO_TONS
