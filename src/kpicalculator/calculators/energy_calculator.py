# src/kpicalculator/calculators/energy_calculator.py
# No typing imports needed currently

from ..adapters.common_model import Asset, AssetType, EnergySystem
from ..common.constants import SECONDS_PER_YEAR


class EnergyCalculator:
    """Calculator for energy-related KPIs."""

    def __init__(self, energy_system: EnergySystem):
        """Initialize the energy calculator.

        Args:
            energy_system: Energy system to calculate KPIs for
        """
        self.energy_system = energy_system

    def get_total_energy_consumption_per_year(self) -> float:
        """Calculate total energy consumption per year.

        Returns:
            Total energy consumption in joules per year
        """
        total_consumption = 0.0

        for asset in self.energy_system.assets:
            if asset.asset_type == AssetType.CONSUMER:
                total_consumption += self._calculate_asset_energy_consumption(asset)

        return total_consumption

    def get_total_energy_demand_per_year(self) -> float:
        """Calculate total energy demand per year.

        Returns:
            Total energy demand in joules per year
        """
        total_demand = 0.0

        for asset in self.energy_system.assets:
            if asset.asset_type == AssetType.CONSUMER:
                total_demand += self._calculate_asset_energy_demand(asset)

        return total_demand

    def get_total_energy_production_per_year(self) -> float:
        """Calculate total energy production per year.

        Returns:
            Total energy production in joules per year
        """
        total_production = 0.0

        for asset in self.energy_system.assets:
            if asset.asset_type in [AssetType.PRODUCER, AssetType.GEOTHERMAL]:
                total_production += self._calculate_asset_energy_production(asset)

        return total_production

    def calculate_system_efficiency(self) -> float:
        """Calculate overall system efficiency.

        Returns:
            System efficiency as a ratio (0-1)
        """
        production = self.get_total_energy_production_per_year()
        consumption = self.get_total_energy_consumption_per_year()

        if production <= 0:
            return 0.0

        return consumption / production

    def _calculate_asset_energy_consumption(self, asset: Asset) -> float:
        """Calculate energy consumption for a specific asset.

        Args:
            asset: Asset to calculate energy consumption for

        Returns:
            Energy consumption in joules per year
        """
        # Check if we have time series data
        if not asset.time_series:
            return 0.0

        # Look for consumption time series
        ts_name = None
        for name in ["ThermalConsumption", "Consumption", "Energy"]:
            if name in asset.time_series:
                ts_name = name
                break

        if not ts_name:
            return 0.0

        ts = asset.time_series[ts_name]

        # Calculate annual energy
        duration = ts.time_step * len(ts.values)
        time_factor = SECONDS_PER_YEAR / duration
        energy_sum = sum(ts.values) * ts.time_step

        return energy_sum * time_factor

    def _calculate_asset_energy_demand(self, asset: Asset) -> float:
        """Calculate energy demand for a specific asset.

        Args:
            asset: Asset to calculate energy demand for

        Returns:
            Energy demand in joules per year
        """
        # Check if we have time series data
        if not asset.time_series:
            return 0.0

        # Look for demand time series
        ts_name = None
        for name in ["ThermalDemand", "Demand"]:
            if name in asset.time_series:
                ts_name = name
                break

        if not ts_name:
            return self._calculate_asset_energy_consumption(asset)  # Fall back to consumption

        ts = asset.time_series[ts_name]

        # Calculate annual energy
        duration = ts.time_step * len(ts.values)
        time_factor = SECONDS_PER_YEAR / duration
        energy_sum = sum(ts.values) * ts.time_step

        return energy_sum * time_factor

    def _calculate_asset_energy_production(self, asset: Asset) -> float:
        """Calculate energy production for a specific asset.

        Args:
            asset: Asset to calculate energy production for

        Returns:
            Energy production in joules per year
        """
        # Check if we have time series data
        if not asset.time_series:
            return 0.0

        # Look for production time series
        ts_name = None
        for name in ["ThermalProduction", "Production", "Energy"]:
            if name in asset.time_series:
                ts_name = name
                break

        if not ts_name:
            return 0.0

        ts = asset.time_series[ts_name]

        # Calculate annual energy
        duration = ts.time_step * len(ts.values)
        time_factor = SECONDS_PER_YEAR / duration
        energy_sum = sum(ts.values) * ts.time_step

        return energy_sum * time_factor
