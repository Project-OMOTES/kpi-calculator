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
        # Check if we have time series data
        if not asset.time_series:
            return 0.0
        
        # Get the first time series (assuming it's the relevant one)
        if not asset.time_series:
            return 0.0
        
        # Look for relevant time series based on asset type
        ts_name = None
        if asset.asset_type in [AssetType.PRODUCER, AssetType.GEOTHERMAL]:
            for name in ["ThermalProduction", "Production", "Energy"]:
                if name in asset.time_series:
                    ts_name = name
                    break
        elif asset.asset_type == AssetType.CONSUMER:
            for name in ["ThermalConsumption", "Consumption", "Energy"]:
                if name in asset.time_series:
                    ts_name = name
                    break
        elif asset.asset_type == AssetType.CONVERSION:
            for name in ["ElectricalConsumption", "ThermalProduction"]:
                if name in asset.time_series:
                    ts_name = name
                    break
        
        if not ts_name:
            return 0.0
        
        ts = asset.time_series[ts_name]
        
        # Calculate annual energy
        duration = ts.time_step * len(ts.values)
        time_factor = 3600 * 24 * 365 / duration
        energy_sum = sum(ts.values) * ts.time_step
        
        # Calculate emissions (emission_factor is in kg/GJ, energy_sum is in J)
        # Convert J to GJ (1 GJ = 1e9 J) and kg to tons (1 ton = 1000 kg)
        emissions = asset.emission_factor * energy_sum * time_factor / 1e9 / 1000
        
        return emissions
