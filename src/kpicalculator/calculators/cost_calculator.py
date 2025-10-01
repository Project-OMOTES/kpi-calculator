# src/kpicalculator/calculators/cost_calculator.py
import math

from ..adapters.common_model import Asset, AssetType, EnergySystem
from ..common.constants import (
    DEFAULT_DISCOUNT_RATE_PERCENT,
    PERCENTAGE_TO_DECIMAL,
    SECONDS_PER_YEAR,
)


class CostCalculator:
    """Calculator for cost-related KPIs."""

    def __init__(self, energy_system: EnergySystem):
        """Initialize the cost calculator.

        Args:
            energy_system: Energy system to calculate KPIs for
        """
        self.energy_system = energy_system

    def get_capex_by_category(self) -> dict[str, float]:
        """Get CAPEX by asset category.

        Returns:
            Dictionary with CAPEX by category
        """
        categories = ["Production", "Consumption", "Storage", "Transport", "Conversion", "All"]
        result = {}

        for category in categories:
            result[category] = self._calculate_capex_for_category(category)

        return result

    def get_opex_by_category(self) -> dict[str, float]:
        """Get OPEX by asset category.

        Returns:
            Dictionary with OPEX by category
        """
        categories = ["Production", "Consumption", "Storage", "Transport", "Conversion", "All"]
        result = {}

        for category in categories:
            result[category] = self._calculate_opex_for_category(category)

        return result

    def calculate_npv(
        self, system_lifetime: float, discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT
    ) -> float:
        """Calculate Net Present Value for the energy system.

        Args:
            system_lifetime: System lifetime in years
            discount_rate: Discount rate in percentage

        Returns:
            Net Present Value
        """
        npv = 0.0

        for asset in self.energy_system.assets:
            # Calculate NPV for CAPEX
            capex_npv = asset.investment_cost + asset.installation_cost
            capex_npv *= sum(
                [
                    1.0
                    / math.pow(
                        1.0 + discount_rate * PERCENTAGE_TO_DECIMAL, asset.technical_lifetime * n
                    )
                    for n in range(math.ceil(system_lifetime / asset.technical_lifetime))
                ]
            )

            # Calculate NPV for OPEX
            opex_annual = (
                self._calculate_fixed_operational_cost(asset)
                + self._calculate_variable_operational_cost(asset)
                + self._calculate_fixed_maintenance_cost(asset)
                + self._calculate_variable_maintenance_cost(asset)
            )

            opex_npv = opex_annual * sum(
                1.0 / math.pow(1.0 + discount_rate * PERCENTAGE_TO_DECIMAL, n)
                for n in range(int(system_lifetime))
            )

            npv += capex_npv + opex_npv

        return npv

    def calculate_lcoe(
        self, system_lifetime: float, discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT
    ) -> float:
        """Calculate Levelized Cost of Energy.

        Args:
            system_lifetime: System lifetime in years
            discount_rate: Discount rate in percentage

        Returns:
            Levelized Cost of Energy in EUR/MWh
        """
        from ..calculators.energy_calculator import EnergyCalculator

        energy_calc = EnergyCalculator(self.energy_system)
        annual_energy = (
            energy_calc.get_total_energy_consumption_per_year() / 3.6e9
        )  # Convert to MWh

        if annual_energy <= 0:
            return 0.0

        npv = self.calculate_npv(system_lifetime, discount_rate)

        # Calculate discounted energy production
        discounted_energy = 0.0
        for year in range(int(system_lifetime)):
            discounted_energy += annual_energy / math.pow(
                1.0 + discount_rate * PERCENTAGE_TO_DECIMAL, year
            )

        return npv / discounted_energy

    def _calculate_capex_for_category(self, category: str) -> float:
        """Calculate CAPEX for a specific asset category.

        Args:
            category: Asset category

        Returns:
            CAPEX for the category
        """
        capex = 0.0

        for asset in self.energy_system.assets:
            if category == "All" or self._asset_belongs_to_category(asset, category):
                capex += self._calculate_investment_cost(asset) + self._calculate_installation_cost(
                    asset
                )

        return capex

    def _calculate_opex_for_category(self, category: str) -> float:
        """Calculate OPEX for a specific asset category.

        Args:
            category: Asset category

        Returns:
            OPEX for the category
        """
        opex = 0.0

        for asset in self.energy_system.assets:
            if category == "All" or self._asset_belongs_to_category(asset, category):
                opex += (
                    self._calculate_fixed_operational_cost(asset)
                    + self._calculate_variable_operational_cost(asset)
                    + self._calculate_fixed_maintenance_cost(asset)
                    + self._calculate_variable_maintenance_cost(asset)
                )

        return opex

    def _asset_belongs_to_category(self, asset: Asset, category: str) -> bool:
        """Check if an asset belongs to a specific category.

        Args:
            asset: Asset to check
            category: Category to check

        Returns:
            True if the asset belongs to the category, False otherwise
        """
        category_mapping = {
            "Production": [AssetType.PRODUCER, AssetType.GEOTHERMAL],
            "Consumption": [AssetType.CONSUMER],
            "Storage": [AssetType.STORAGE],
            "Transport": [AssetType.TRANSPORT, AssetType.PIPE, AssetType.PUMP],
            "Conversion": [AssetType.CONVERSION],
        }

        return asset.asset_type in category_mapping.get(category, [])

    def _calculate_investment_cost(self, asset: Asset) -> float:
        """Calculate investment cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Investment cost
        """
        allowed_units = ["EUR", "EUR/kW", "EUR/MW", "EUR/m", "EUR/km", "EUR/m3"]

        if asset.investment_cost_unit not in allowed_units:
            return 0.0

        value = asset.investment_cost
        factor = 1.0

        if asset.investment_cost_unit == "EUR":
            return value

        if asset.investment_cost_unit in ["EUR/kW", "EUR/MW"]:
            factor = self._get_unit_factor(asset.investment_cost_unit)
            return value * asset.power * factor

        if asset.investment_cost_unit in ["EUR/m", "EUR/km"]:
            factor = self._get_unit_factor(asset.investment_cost_unit)
            return value * asset.length * factor

        if asset.investment_cost_unit == "EUR/m3":
            return value * asset.volume

        return 0.0

    def _calculate_installation_cost(self, asset: Asset) -> float:
        """Calculate installation cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Installation cost
        """
        allowed_units = ["EUR", "EUR/kW", "EUR/MW", "EUR/m", "EUR/km", "EUR/m3"]

        if asset.installation_cost_unit not in allowed_units:
            return 0.0

        value = asset.installation_cost
        factor = 1.0

        if asset.installation_cost_unit == "EUR":
            return value

        if asset.installation_cost_unit in ["EUR/kW", "EUR/MW"]:
            factor = self._get_unit_factor(asset.installation_cost_unit)
            return value * asset.power * factor

        if asset.installation_cost_unit in ["EUR/m", "EUR/km"]:
            factor = self._get_unit_factor(asset.installation_cost_unit)
            return value * asset.length * factor

        if asset.installation_cost_unit == "EUR/m3":
            return value * asset.volume

        return 0.0

    def _calculate_fixed_operational_cost(self, asset: Asset) -> float:
        """Calculate fixed operational cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Fixed operational cost
        """
        allowed_units = ["EUR", "EUR/yr", "% OF CAPEX", "EUR/MW"]

        if asset.fixed_operational_cost_unit not in allowed_units:
            return 0.0

        value = asset.fixed_operational_cost

        if asset.fixed_operational_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.fixed_operational_cost_unit == "% OF CAPEX":
            capex = self._calculate_investment_cost(asset) + self._calculate_installation_cost(
                asset
            )
            factor = self._get_unit_factor(asset.fixed_operational_cost_unit)
            return capex * value * factor

        if asset.fixed_operational_cost_unit == "EUR/MW":
            factor = self._get_unit_factor(asset.fixed_operational_cost_unit)
            return value * asset.power * factor

        return 0.0

    def _calculate_variable_operational_cost(self, asset: Asset) -> float:
        """Calculate variable operational cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Variable operational cost
        """
        allowed_units = ["EUR", "EUR/yr", "EUR/kWh", "EUR/MWh"]

        if asset.variable_operational_cost_unit not in allowed_units:
            return 0.0

        value = asset.variable_operational_cost

        if asset.variable_operational_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.variable_operational_cost_unit in ["EUR/kWh", "EUR/MWh"]:
            # Check if we have time series data
            if not asset.time_series:
                return 0.0

            # Get the first time series (assuming it's the relevant one)
            ts = next(iter(asset.time_series.values()), None)
            if ts is None:
                return 0.0

            # Calculate annual energy
            duration = ts.time_step * len(ts.values)
            time_factor = SECONDS_PER_YEAR / duration
            energy_sum = sum(ts.values) * ts.time_step

            # Apply unit conversion
            factor = self._get_unit_factor(asset.variable_operational_cost_unit)

            # Special case for geothermal sources
            if asset.asset_type == AssetType.GEOTHERMAL and asset.cop > 0:
                return time_factor * factor * value * energy_sum / asset.cop

            return time_factor * factor * value * energy_sum

        return 0.0

    def _calculate_fixed_maintenance_cost(self, asset: Asset) -> float:
        """Calculate fixed maintenance cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Fixed maintenance cost
        """
        allowed_units = ["EUR", "EUR/yr", "% OF CAPEX", "EUR/MW"]

        if asset.fixed_maintenance_cost_unit not in allowed_units:
            return 0.0

        value = asset.fixed_maintenance_cost

        if asset.fixed_maintenance_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.fixed_maintenance_cost_unit == "% OF CAPEX":
            capex = self._calculate_investment_cost(asset) + self._calculate_installation_cost(
                asset
            )
            factor = self._get_unit_factor(asset.fixed_maintenance_cost_unit)
            return capex * value * factor

        if asset.fixed_maintenance_cost_unit == "EUR/MW":
            factor = self._get_unit_factor(asset.fixed_maintenance_cost_unit)
            return value * asset.power * factor

        return 0.0

    def _calculate_variable_maintenance_cost(self, asset: Asset) -> float:
        """Calculate variable maintenance cost for an asset.

        Args:
            asset: Asset to calculate cost for

        Returns:
            Variable maintenance cost
        """
        allowed_units = ["EUR", "EUR/yr", "EUR/kWh", "EUR/MWh"]

        if asset.variable_maintenance_cost_unit not in allowed_units:
            return 0.0

        value = asset.variable_maintenance_cost

        if asset.variable_maintenance_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.variable_maintenance_cost_unit in ["EUR/kWh", "EUR/MWh"]:
            # Check if we have time series data
            if not asset.time_series:
                return 0.0

            # Get the first time series (assuming it's the relevant one)
            ts = next(iter(asset.time_series.values()), None)
            if ts is None:
                return 0.0

            # Calculate annual energy
            duration = ts.time_step * len(ts.values)
            time_factor = SECONDS_PER_YEAR / duration
            energy_sum = sum(ts.values) * ts.time_step

            # Apply unit conversion
            factor = self._get_unit_factor(asset.variable_maintenance_cost_unit)

            # Special case for geothermal sources
            if asset.asset_type == AssetType.GEOTHERMAL and asset.cop > 0:
                return time_factor * factor * value * energy_sum / asset.cop

            return time_factor * factor * value * energy_sum

        return 0.0

    def _get_unit_factor(self, unit: str) -> float:
        """Get the conversion factor for a unit.

        Args:
            unit: Unit to get conversion factor for

        Returns:
            Conversion factor
        """
        if unit in self.energy_system.unit_conversion:
            return self.energy_system.unit_conversion[unit]
        return 1.0
