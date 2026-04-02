# src/kpicalculator/calculators/cost_calculator.py
import logging
import math

from ..adapters.common_model import Asset, AssetType, EnergySystem
from ..common.constants import (
    DEFAULT_DISCOUNT_RATE_PERCENT,
    PERCENTAGE_TO_DECIMAL,
    SECONDS_PER_YEAR,
)
from ..exceptions import CalculationError

logger = logging.getLogger(__name__)


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
        self,
        system_lifetime: float,
        discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
        round_up_replacement: bool = True,
    ) -> float:
        """Calculate Net Present Value for the energy system.

        By default (``round_up_replacement=True``) CAPEX uses a start-of-period
        convention: one discounted payment per replacement cycle, with the number of
        replacements equal to ``ceil(system_lifetime / technical_lifetime)``.
        OPEX uses the standard end-of-period convention (``t = 1 … n``). A fractional
        final year is prorated linearly. See ``kpi_guide.rst`` for the full formula.

        Set ``round_up_replacement=False`` to use the continuous replacement factor
        ``max(1, system_lifetime / technical_lifetime)`` as a scalar multiplier on a
        single undiscounted CAPEX — the approximation used by optimizers such as MESIDO.

        Raises:
            CalculationError: If ``system_lifetime <= 0``, ``discount_rate`` is outside
                [0, 100], or any asset has a non-positive ``technical_lifetime``.

        Args:
            system_lifetime: System lifetime in years. May be fractional.
            discount_rate: Discount rate in percentage (e.g. 5 for 5%).
            round_up_replacement: If True (default), use ``ceil`` for the replacement
                count with per-replacement discounting. If False, use the continuous
                factor ``max(1, n / technical_lifetime)`` for optimizer compatibility.

        Returns:
            Net Present Value in EUR.
        """
        if system_lifetime <= 0:
            raise CalculationError(f"system_lifetime must be positive (got {system_lifetime}).")
        if discount_rate < 0 or discount_rate > 100:
            raise CalculationError(
                f"discount_rate must be between 0 and 100 (got {discount_rate})."
            )

        discount_rate_ratio = discount_rate * PERCENTAGE_TO_DECIMAL
        npv = 0.0

        for asset in self.energy_system.assets:
            if asset.technical_lifetime <= 0:
                raise CalculationError(
                    f"Asset '{asset.name}' has non-positive technical_lifetime "
                    f"({asset.technical_lifetime}). Cannot compute NPV."
                )

            # Calculate NPV for CAPEX
            capex = asset.investment_cost + asset.installation_cost
            if round_up_replacement:
                capex_npv = capex * sum(
                    1.0 / math.pow(1.0 + discount_rate_ratio, asset.technical_lifetime * n)
                    for n in range(math.ceil(system_lifetime / asset.technical_lifetime))
                )
            else:
                replacements = max(1.0, system_lifetime / asset.technical_lifetime)
                capex_npv = capex * replacements

            # Calculate NPV for OPEX
            opex_annual = (
                self._calculate_fixed_operational_cost(asset)
                + self._calculate_fixed_maintenance_cost(asset)
                + self._calculate_variable_operational_cost(asset)
                + self._calculate_variable_maintenance_cost(asset)
            )

            # End-of-period convention (standard engineering economics): OPEX at year t
            # is discounted by (1+r)^t, t = 1..n. Consistent with the annuity formula
            # in calculate_eac. A fractional final year is prorated linearly.
            full_years = int(system_lifetime)
            opex_npv = opex_annual * sum(
                1.0 / math.pow(1.0 + discount_rate_ratio, t) for t in range(1, full_years + 1)
            )
            fraction = system_lifetime - full_years
            if fraction > 0:
                opex_npv += (
                    opex_annual * fraction / math.pow(1.0 + discount_rate_ratio, full_years + 1)
                )

            npv += capex_npv + opex_npv

        return npv

    def calculate_eac(self, discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT) -> float:
        """Calculate Equivalent Annual Cost for the energy system.

        Sums per-asset annualized costs using each asset's own ``technical_lifetime``
        and ``discount_rate`` (from ESDL ``costInformation.discountRate``, falling back
        to the ``discount_rate`` parameter). The annuity formula spreads one asset
        purchase over its technical lifetime, implicitly assuming perpetual replacement —
        the annual charge is the same regardless of how many replacements occur within
        the system lifetime. OPEX is already annual and is passed through directly.

        This matches the approach used in the MESIDO optimizer
        (``calculate_annuity_factor`` in ``financial_mixin.py``). See ``kpi_guide.rst``
        for the formula and a discussion of the replacement assumption.

        Raises:
            CalculationError: If ``discount_rate`` is outside [0, 100] or any asset
                has a non-positive ``technical_lifetime``.

        Args:
            discount_rate: Fallback discount rate in percentage (e.g. 5 for 5%),
                used when ``asset.discount_rate is None`` (i.e. no
                ``costInformation.discountRate`` was present in the ESDL for that asset).

        Returns:
            Equivalent Annual Cost in EUR/year.
        """
        if discount_rate < 0 or discount_rate > 100:
            raise CalculationError(
                f"discount_rate must be between 0 and 100 (got {discount_rate})."
            )

        eac = 0.0

        for asset in self.energy_system.assets:
            if asset.technical_lifetime <= 0:
                raise CalculationError(
                    f"Asset '{asset.name}' has non-positive technical_lifetime "
                    f"({asset.technical_lifetime}). Cannot compute EAC."
                )

            r = self._get_effective_discount_rate(asset, discount_rate) * PERCENTAGE_TO_DECIMAL

            capex = self._calculate_investment_cost(asset) + self._calculate_installation_cost(
                asset
            )
            if r == 0.0:
                annualized_capex = capex / asset.technical_lifetime
            else:
                annualized_capex = capex * r / (1.0 - math.pow(1.0 + r, -asset.technical_lifetime))

            opex_annual = (
                self._calculate_fixed_operational_cost(asset)
                + self._calculate_fixed_maintenance_cost(asset)
                + self._calculate_variable_operational_cost(asset)
                + self._calculate_variable_maintenance_cost(asset)
            )

            eac += annualized_capex + opex_annual

        return eac

    def calculate_tco(self, system_lifetime: float, round_up_replacement: bool = True) -> float:
        """Calculate Total Cost of Ownership for the energy system.

        Undiscounted sum of all costs over the system lifetime::

            TCO = Sum over assets of:
                (investment + installation) * replacement_factor
                + annual_opex * system_lifetime

        By default (``round_up_replacement=True``) the replacement factor is
        ``ceil(system_lifetime / technical_lifetime)`` — the financially exact count
        of full asset purchases needed to keep the system operational. This is
        consistent with ``calculate_npv()``, which uses the same ``ceil`` logic for
        CAPEX discounting, so ``TCO == NPV`` at ``discount_rate=0``.

        Set ``round_up_replacement=False`` to use the continuous factor
        ``max(1, system_lifetime / technical_lifetime)`` instead. Optimizers such as
        MESIDO use this approximation to keep the objective smooth and differentiable.
        Use this option only when comparing KPI output against optimizer results.

        Note: MESIDO's ``MinimizeTCO`` covers variable and fixed operational costs only.
        This calculator also includes fixed and variable maintenance costs, so TCO values
        will differ from MESIDO when maintenance costs are non-zero.

        Raises:
            CalculationError: If ``system_lifetime <= 0`` or any asset has a non-positive
                ``technical_lifetime``.

        Args:
            system_lifetime: System lifetime in years.
            round_up_replacement: If True (default), use ``ceil`` for the replacement
                count (financially exact). If False, use the continuous factor
                ``max(1, n / technical_lifetime)`` for optimizer compatibility.

        Returns:
            Total Cost of Ownership in EUR.
        """
        if system_lifetime <= 0:
            raise CalculationError(f"system_lifetime must be positive (got {system_lifetime}).")

        tco = 0.0

        for asset in self.energy_system.assets:
            if asset.technical_lifetime <= 0:
                raise CalculationError(
                    f"Asset '{asset.name}' has non-positive technical_lifetime "
                    f"({asset.technical_lifetime}). Cannot compute TCO."
                )

            capex = self._calculate_investment_cost(asset) + self._calculate_installation_cost(
                asset
            )
            replacements: float
            if round_up_replacement:
                replacements = math.ceil(system_lifetime / asset.technical_lifetime)
            else:
                replacements = max(1.0, system_lifetime / asset.technical_lifetime)
            tco += capex * replacements

            opex_annual = (
                self._calculate_fixed_operational_cost(asset)
                + self._calculate_variable_operational_cost(asset)
                + self._calculate_fixed_maintenance_cost(asset)
                + self._calculate_variable_maintenance_cost(asset)
            )
            tco += opex_annual * system_lifetime

        return tco

    def calculate_lcoe(
        self,
        system_lifetime: float,
        discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
        round_up_replacement: bool = True,
    ) -> float:
        """Calculate Levelized Cost of Energy.

        Divides NPV by discounted energy to put costs and energy on the same
        present-value basis. Energy discounting uses the same end-of-period convention
        and fractional-year proration as NPV OPEX. See ``kpi_guide.rst`` for the formula.

        The ``round_up_replacement`` flag is passed through to ``calculate_npv``; see
        that method for its effect on CAPEX replacement counting.

        Returns 0.0 if annual energy consumption is zero or negative.

        Raises:
            CalculationError: If ``system_lifetime <= 0``, ``discount_rate`` is outside
                [0, 100], or any asset has a non-positive ``technical_lifetime``.

        Args:
            system_lifetime: System lifetime in years. May be fractional.
            discount_rate: Discount rate in percentage (e.g. 5 for 5%).
            round_up_replacement: Passed through to ``calculate_npv``. If True (default),
                use ``ceil`` for the replacement count. If False, use the continuous
                factor for optimizer compatibility.

        Returns:
            Levelized Cost of Energy in EUR/MWh.
        """
        if system_lifetime <= 0:
            raise CalculationError(f"system_lifetime must be positive (got {system_lifetime}).")

        from ..calculators.energy_calculator import EnergyCalculator

        energy_calc = EnergyCalculator(self.energy_system)
        annual_energy = (
            energy_calc.get_total_energy_consumption_per_year() / 3.6e9
        )  # Convert to MWh

        if annual_energy <= 0:
            return 0.0

        npv = self.calculate_npv(
            system_lifetime, discount_rate, round_up_replacement=round_up_replacement
        )

        # Calculate discounted energy — end-of-period convention matches NPV OPEX discounting.
        discount_rate_ratio = discount_rate * PERCENTAGE_TO_DECIMAL
        full_years = int(system_lifetime)
        discounted_energy = sum(
            annual_energy / math.pow(1.0 + discount_rate_ratio, t) for t in range(1, full_years + 1)
        )
        fraction = system_lifetime - full_years
        if fraction > 0:
            discounted_energy += (
                annual_energy * fraction / math.pow(1.0 + discount_rate_ratio, full_years + 1)
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
            logger.warning(
                "Unsupported unit '%s' for investment cost on asset '%s'. Cost ignored.",
                asset.investment_cost_unit,
                asset.name,
            )
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
            logger.warning(
                "Unsupported unit '%s' for installation cost on asset '%s'. Cost ignored.",
                asset.installation_cost_unit,
                asset.name,
            )
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
            logger.warning(
                "Unsupported unit '%s' for fixed operational cost on asset '%s'. Cost ignored.",
                asset.fixed_operational_cost_unit,
                asset.name,
            )
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
            logger.warning(
                "Unsupported unit '%s' for variable operational cost on asset '%s'. Cost ignored.",
                asset.variable_operational_cost_unit,
                asset.name,
            )
            return 0.0

        value = asset.variable_operational_cost

        if asset.variable_operational_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.variable_operational_cost_unit in ["EUR/kWh", "EUR/MWh"]:
            # Check if we have time series data
            if not asset.time_series:
                logger.debug(
                    "No time series data for asset '%s'. "
                    "Variable operational cost returned as 0.0.",
                    asset.name,
                )
                return 0.0

            # Get the first time series (assuming it's the relevant one)
            ts = next(iter(asset.time_series.values()), None)
            if ts is None:
                logger.debug(
                    "Empty time series dict for asset '%s'. "
                    "Variable operational cost returned as 0.0.",
                    asset.name,
                )
                return 0.0

            # Calculate annual energy
            duration = ts.time_step * len(ts.values)
            if duration <= 0:
                logger.warning(
                    "Non-positive duration in time series for asset '%s'. "
                    "Variable operational cost returned as 0.0.",
                    asset.name,
                )
                return 0.0
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
            logger.warning(
                "Unsupported unit '%s' for fixed maintenance cost on asset '%s'. Cost ignored.",
                asset.fixed_maintenance_cost_unit,
                asset.name,
            )
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
            logger.warning(
                "Unsupported unit '%s' for variable maintenance cost on asset '%s'. Cost ignored.",
                asset.variable_maintenance_cost_unit,
                asset.name,
            )
            return 0.0

        value = asset.variable_maintenance_cost

        if asset.variable_maintenance_cost_unit in ["EUR", "EUR/yr"]:
            return value

        if asset.variable_maintenance_cost_unit in ["EUR/kWh", "EUR/MWh"]:
            # Check if we have time series data
            if not asset.time_series:
                logger.debug(
                    "No time series data for asset '%s'. "
                    "Variable maintenance cost returned as 0.0.",
                    asset.name,
                )
                return 0.0

            # Get the first time series (assuming it's the relevant one)
            ts = next(iter(asset.time_series.values()), None)
            if ts is None:
                logger.debug(
                    "Empty time series dict for asset '%s'. "
                    "Variable maintenance cost returned as 0.0.",
                    asset.name,
                )
                return 0.0

            # Calculate annual energy
            duration = ts.time_step * len(ts.values)
            if duration <= 0:
                logger.warning(
                    "Non-positive duration in time series for asset '%s'. "
                    "Variable maintenance cost returned as 0.0.",
                    asset.name,
                )
                return 0.0
            time_factor = SECONDS_PER_YEAR / duration
            energy_sum = sum(ts.values) * ts.time_step

            # Apply unit conversion
            factor = self._get_unit_factor(asset.variable_maintenance_cost_unit)

            # Special case for geothermal sources
            if asset.asset_type == AssetType.GEOTHERMAL and asset.cop > 0:
                return time_factor * factor * value * energy_sum / asset.cop

            return time_factor * factor * value * energy_sum

        return 0.0

    def _get_effective_discount_rate(self, asset: Asset, fallback_rate: float) -> float:
        """Return the discount rate to use for an asset, in percentage.

        Uses the per-asset rate from ESDL costInformation when available,
        falling back to ``fallback_rate`` otherwise.

        Args:
            asset: Asset to retrieve the discount rate for.
            fallback_rate: System-level discount rate in percentage, used when
                ``asset.discount_rate`` is None.

        Returns:
            Effective discount rate in percentage.
        """
        return asset.discount_rate if asset.discount_rate is not None else fallback_rate

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
