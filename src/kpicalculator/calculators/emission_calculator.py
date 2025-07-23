# src/kpicalculator/calculators/emission_calculator.py
from typing import Dict, Optional
from ..adapters.common_model import EnergySystem, Asset, AssetType


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
        """Calculate total CO2 emissions."""
        total_emissions = 0.0
        
        for asset in self.energy_system.assets:
            asset_emissions = self._calculate_asset_emissions(asset)
            print(f"Asset {asset.name} emissions: {asset_emissions} tons")
            total_emissions += asset_emissions
        
        print(f"Total emissions: {total_emissions} tons")
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
        
        # Convert emissions from tons to kg (1 ton = 1000 kg)
        emissions_kg = self.get_total_emissions() * 1000
        
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
        
        # Convert emissions from tons to kg (1 ton = 1000 kg)
        emissions_kg = self.get_total_emissions() * 1000
        
        return emissions_kg / energy_consumption_gj
    
    def _calculate_asset_emissions(self, asset: Asset) -> float:
        """Calculate CO2 emissions for a specific asset.
        
        Args:
            asset: Asset to calculate emissions for
            
        Returns:
            CO2 emissions in tons per year
        """
        if not asset.time_series:
            return 0.0

        # Print asset details for debugging
        print(f"Asset: {asset.name}, Type: {asset.asset_type}, Emission factor: {asset.emission_factor}")

        # Map asset types to their respective time series keys
        ts_options = {
            AssetType.PRODUCER: ["ThermalProduction", "Production", "Energy"],
            AssetType.GEOTHERMAL: ["ThermalProduction", "Production", "Energy"],
            AssetType.CONSUMER: ["ThermalConsumption", "Consumption", "Energy"],
            AssetType.CONVERSION: ["ElectricalConsumption", "ThermalProduction"]
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
        duration = ts.time_step * len(ts.values)
        time_factor = (3600 * 24 * 365) / duration
        energy_sum = sum(ts.values) * ts.time_step

        # Calculate emissions (emission_factor is in kg/GJ, energy_sum is in J)
        # Convert J to GJ (1 GJ = 1e9 J) and kg to tons (1 ton = 1000 kg)
        emissions = asset.emission_factor * energy_sum * time_factor / 1e9 / 1000

        return emissions
