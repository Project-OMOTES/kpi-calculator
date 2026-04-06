# src/kpicalculator/calculators/financial_calculator.py
import logging
import math
from typing import TypedDict

from ..adapters.common_model import Asset, AssetType, EnergySystem
from ..common.constants import (
    DEFAULT_DISCOUNT_RATE_PERCENT,
    PERCENTAGE_TO_DECIMAL,
    SECONDS_PER_YEAR,
)
from ..exceptions import CalculationError

logger = logging.getLogger(__name__)

# Asset types that produce energy — used for per-asset LCOE eligibility.
PRODUCER_ASSET_TYPES = frozenset({AssetType.PRODUCER, AssetType.GEOTHERMAL})

# Single taxonomy used by all category-based methods.
_CATEGORY_MAPPING: dict[str, list[AssetType]] = {
    "Production": [AssetType.PRODUCER, AssetType.GEOTHERMAL],
    "Consumption": [AssetType.CONSUMER],
    "Storage": [AssetType.STORAGE],
    "Transport": [AssetType.TRANSPORT, AssetType.PIPE, AssetType.PUMP],
    "Conversion": [AssetType.CONVERSION],
}


class AssetFinancialResult(TypedDict):
    """Per-asset financial KPIs. System totals are derived by summing these across assets.

    ``lcoe`` is ``None`` for non-producing assets (consumers, transport, storage) because
    LCOE is a ratio of cost to energy output and is only meaningful for assets that
    produce energy.
    """

    investment_cost: float
    installation_cost: float
    fixed_operational_cost: float
    variable_operational_cost: float
    fixed_maintenance_cost: float
    variable_maintenance_cost: float
    annualized_capex: float
    eac: float
    npv: float
    tco: float
    lcoe: float | None


class FinancialCalculator:
    """Calculator for financial KPIs (CAPEX, OPEX, NPV, LCOE, EAC, TCO)."""

    def __init__(self, energy_system: EnergySystem):
        """Initialize the cost calculator.

        Args:
            energy_system: Energy system to calculate KPIs for
        """
        self.energy_system = energy_system

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

            capex = asset.investment_cost + asset.installation_cost
            if round_up_replacement:
                capex_npv = capex * sum(
                    1.0 / math.pow(1.0 + discount_rate_ratio, asset.technical_lifetime * n)
                    for n in range(math.ceil(system_lifetime / asset.technical_lifetime))
                )
            else:
                replacements = max(1.0, system_lifetime / asset.technical_lifetime)
                capex_npv = capex * replacements

            opex_annual = (
                self._calculate_fixed_operational_cost(asset)
                + self._calculate_fixed_maintenance_cost(asset)
                + self._calculate_variable_operational_cost(asset)
                + self._calculate_variable_maintenance_cost(asset)
            )

            full_years = int(system_lifetime)
            fraction = system_lifetime - full_years
            opex_npv = self._compute_discounted_sum(
                opex_annual, discount_rate_ratio, full_years, fraction
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
            annualized_capex = self._annualize_capex(capex, r, asset.technical_lifetime)

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
        system_npv: float | None = None,
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
            system_npv: Pre-computed system NPV in EUR. When provided, skips the internal
                ``calculate_npv()`` call. Pass this from ``KpiManager.calculate_all_kpis()``
                to avoid a redundant full asset iteration.

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

        if system_npv is None:
            system_npv = self.calculate_npv(
                system_lifetime, discount_rate, round_up_replacement=round_up_replacement
            )

        discount_rate_ratio = discount_rate * PERCENTAGE_TO_DECIMAL
        full_years = int(system_lifetime)
        fraction = system_lifetime - full_years
        discounted_energy = self._compute_discounted_sum(
            annual_energy, discount_rate_ratio, full_years, fraction
        )

        return system_npv / discounted_energy

    def get_asset_financial_breakdown(
        self,
        system_lifetime: float,
        discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
        round_up_replacement: bool = True,
        annual_energy_mwh_by_asset: dict[str, float] | None = None,
    ) -> dict[str, AssetFinancialResult]:
        """Compute per-asset financial KPIs.

        Returns a dict keyed by ``asset.id``. System totals for NPV, TCO, EAC are
        the sum of these values across all assets.

        ``lcoe`` semantics:

        - ``None`` — asset is not a generating type (consumer, storage, transport,
          conversion), or is a generating asset whose annual energy production is zero
          or unknown. ``None`` means *not applicable or not computable*, regardless of
          the output format (ESDL, JSON, or any future schema). Exporters omit the field
          or write a format-appropriate null for ``None`` values.
        - ``float`` — EUR/MWh; only set for generating assets with non-zero energy output.

        System LCOE must be computed separately as total NPV / total discounted energy
        output — it is not the sum of per-asset LCOEs (summing ratios with different
        denominators is mathematically incorrect).

        Raises:
            CalculationError: If ``system_lifetime <= 0``, ``discount_rate`` is outside
                [0, 100], or any asset has a non-positive ``technical_lifetime``.

        Args:
            system_lifetime: System lifetime in years.
            discount_rate: Fallback discount rate in percentage (e.g. 5 for 5%).
            round_up_replacement: If True (default), use ``ceil`` for replacement count.
                If False, use the continuous factor for optimizer compatibility.
            annual_energy_mwh_by_asset: Optional mapping of asset ID to annual energy
                production in MWh. When provided, ``lcoe`` is computed for generating
                assets (those in ``PRODUCER_ASSET_TYPES``) with non-zero energy.
                When ``None`` (default), ``lcoe`` is ``None`` for all assets.
                Callers that hold an energy calculator should pre-compute this dict
                and pass it here rather than relying on a post-hoc fill step.

        Returns:
            Dict mapping asset ID to its ``AssetFinancialResult``.
        """
        if system_lifetime <= 0:
            raise CalculationError(f"system_lifetime must be positive (got {system_lifetime}).")
        if discount_rate < 0 or discount_rate > 100:
            raise CalculationError(
                f"discount_rate must be between 0 and 100 (got {discount_rate})."
            )

        result: dict[str, AssetFinancialResult] = {}
        discount_rate_ratio = discount_rate * PERCENTAGE_TO_DECIMAL
        full_years = int(system_lifetime)
        fraction = system_lifetime - full_years

        for asset in self.energy_system.assets:
            if asset.technical_lifetime <= 0:
                raise CalculationError(
                    f"Asset '{asset.name}' has non-positive technical_lifetime "
                    f"({asset.technical_lifetime}). Cannot compute financial breakdown."
                )
            result[asset.id] = self._compute_asset_result(
                asset,
                system_lifetime,
                discount_rate,
                discount_rate_ratio,
                full_years,
                fraction,
                round_up_replacement,
                annual_energy_mwh_by_asset,
            )

        return result

    def _compute_asset_result(  # pylint: disable=too-many-locals
        self,
        asset: Asset,
        system_lifetime: float,
        discount_rate: float,
        discount_rate_ratio: float,
        full_years: int,
        fraction: float,
        round_up_replacement: bool,
        annual_energy_mwh_by_asset: dict[str, float] | None,
    ) -> AssetFinancialResult:
        """Compute all financial KPIs for a single asset."""
        investment_cost = self._calculate_investment_cost(asset)
        installation_cost = self._calculate_installation_cost(asset)
        fixed_operational_cost = self._calculate_fixed_operational_cost(asset)
        variable_operational_cost = self._calculate_variable_operational_cost(asset)
        fixed_maintenance_cost = self._calculate_fixed_maintenance_cost(asset)
        variable_maintenance_cost = self._calculate_variable_maintenance_cost(asset)

        capex = investment_cost + installation_cost
        opex_annual = (
            fixed_operational_cost
            + variable_operational_cost
            + fixed_maintenance_cost
            + variable_maintenance_cost
        )

        r = self._get_effective_discount_rate(asset, discount_rate) * PERCENTAGE_TO_DECIMAL
        annualized_capex = self._annualize_capex(capex, r, asset.technical_lifetime)
        eac = annualized_capex + opex_annual

        npv, tco = self._compute_asset_npv_tco(
            capex,
            opex_annual,
            asset.technical_lifetime,
            system_lifetime,
            discount_rate_ratio,
            full_years,
            fraction,
            round_up_replacement,
        )
        lcoe = self._compute_asset_lcoe(
            npv,
            asset,
            annual_energy_mwh_by_asset,
            discount_rate_ratio,
            full_years,
            fraction,
        )

        return AssetFinancialResult(
            investment_cost=investment_cost,
            installation_cost=installation_cost,
            fixed_operational_cost=fixed_operational_cost,
            variable_operational_cost=variable_operational_cost,
            fixed_maintenance_cost=fixed_maintenance_cost,
            variable_maintenance_cost=variable_maintenance_cost,
            annualized_capex=annualized_capex,
            eac=eac,
            npv=npv,
            tco=tco,
            lcoe=lcoe,
        )

    def _compute_asset_npv_tco(
        self,
        capex: float,
        opex_annual: float,
        technical_lifetime: float,
        system_lifetime: float,
        discount_rate_ratio: float,
        full_years: int,
        fraction: float,
        round_up_replacement: bool,
    ) -> tuple[float, float]:
        """Compute NPV and TCO for a single asset."""
        if round_up_replacement:
            n_replacements: int = math.ceil(system_lifetime / technical_lifetime)
            replacements: float = n_replacements
            capex_npv = capex * sum(
                1.0 / math.pow(1.0 + discount_rate_ratio, technical_lifetime * n)
                for n in range(n_replacements)
            )
        else:
            replacements = max(1.0, system_lifetime / technical_lifetime)
            capex_npv = capex * replacements

        opex_npv = self._compute_discounted_sum(
            opex_annual, discount_rate_ratio, full_years, fraction
        )

        npv = capex_npv + opex_npv
        tco = capex * replacements + opex_annual * system_lifetime
        return npv, tco

    def _compute_asset_lcoe(
        self,
        npv: float,
        asset: Asset,
        annual_energy_mwh_by_asset: dict[str, float] | None,
        discount_rate_ratio: float,
        full_years: int,
        fraction: float,
    ) -> float | None:
        """Compute per-asset LCOE, or return None if not applicable or not computable."""
        if annual_energy_mwh_by_asset is None or asset.asset_type not in PRODUCER_ASSET_TYPES:
            return None
        annual_energy_mwh = annual_energy_mwh_by_asset.get(asset.id, 0.0)
        if annual_energy_mwh <= 0:
            return None
        discounted_energy = self._compute_discounted_sum(
            annual_energy_mwh, discount_rate_ratio, full_years, fraction
        )
        return npv / discounted_energy if discounted_energy > 0 else None

    def _annualize_capex(self, capex: float, r: float, technical_lifetime: float) -> float:
        """Annualize a CAPEX amount using the annuity formula.

        Args:
            capex: Capital cost in EUR.
            r: Discount rate as a decimal (e.g. 0.05 for 5%).
            technical_lifetime: Asset technical lifetime in years.

        Returns:
            Annualized CAPEX in EUR/yr.
        """
        if r == 0.0:
            return capex / technical_lifetime
        return capex * r / (1.0 - math.pow(1.0 + r, -technical_lifetime))

    @staticmethod
    def _compute_discounted_sum(
        annual_value: float,
        discount_rate_ratio: float,
        full_years: int,
        fraction: float,
    ) -> float:
        """Compute the present value of a constant annual amount over a fractional lifetime.

        Uses end-of-period convention: cash flow at year t is discounted by (1+r)^t.
        A fractional final year is prorated linearly. Consistent with the annuity
        formula used in ``_annualize_capex``.

        Args:
            annual_value: Constant annual amount (e.g. energy MWh or cost EUR/yr).
            discount_rate_ratio: Discount rate as a decimal (e.g. 0.05 for 5%).
            full_years: Integer number of complete years.
            fraction: Fractional remainder of the final year (0 ≤ fraction < 1).

        Returns:
            Present value of the annual amount stream.
        """
        total = annual_value * sum(
            1.0 / math.pow(1.0 + discount_rate_ratio, t) for t in range(1, full_years + 1)
        )
        if fraction > 0:
            total += annual_value * fraction / math.pow(1.0 + discount_rate_ratio, full_years + 1)
        return total

    def _get_asset_category(self, asset: Asset) -> str:
        """Return the named category for an asset, or 'Other' if unrecognised.

        Args:
            asset: Asset to classify.

        Returns:
            Category name string.
        """
        for category, types in _CATEGORY_MAPPING.items():
            if asset.asset_type in types:
                return category
        return "Other"

    def aggregate_by_category(
        self, asset_financials: dict[str, "AssetFinancialResult"]
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Derive CAPEX and OPEX category breakdowns from a pre-computed asset breakdown.

        Args:
            asset_financials: Dict mapping asset ID to ``AssetFinancialResult``, as
                returned by ``get_asset_financial_breakdown()``.

        Returns:
            Tuple of (capex_by_category, opex_by_category), each a dict with keys
            ``"Production"``, ``"Consumption"``, ``"Storage"``, ``"Transport"``,
            ``"Conversion"``, and ``"All"``.
        """
        categories = list(_CATEGORY_MAPPING.keys())
        capex: dict[str, float] = dict.fromkeys(categories, 0.0)
        capex["All"] = 0.0
        opex: dict[str, float] = dict.fromkeys(categories, 0.0)
        opex["All"] = 0.0

        for asset in self.energy_system.assets:
            financials = asset_financials.get(asset.id)
            if financials is None:
                continue
            cat = self._get_asset_category(asset)
            asset_capex = financials["investment_cost"] + financials["installation_cost"]
            asset_opex = (
                financials["fixed_operational_cost"]
                + financials["variable_operational_cost"]
                + financials["fixed_maintenance_cost"]
                + financials["variable_maintenance_cost"]
            )
            if cat in capex:
                capex[cat] += asset_capex
                opex[cat] += asset_opex
            capex["All"] += asset_capex
            opex["All"] += asset_opex

        return capex, opex

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
