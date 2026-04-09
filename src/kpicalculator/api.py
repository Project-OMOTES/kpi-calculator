#  Copyright (c) 2024 Deltares / TNO.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Public API for KPI Calculator library.

Entry points by data source:

- :func:`calculate_kpis` — ESDL file + optional time series file or DataFrames
- :func:`calculate_kpis_from_simulator` — OMOTES simulator DataFrame + ESDL string

Embedding:

- :func:`build_esdl_string_with_kpis` — write any :class:`KpiResults` into an ESDL string;
  data-source-agnostic, usable after any ``calculate_kpis_from_*`` call.
"""

import logging
from pathlib import Path

import pandas as pd

from .common.constants import DEFAULT_DISCOUNT_RATE_PERCENT, DEFAULT_SYSTEM_LIFETIME_YEARS
from .exceptions import KpiCalculatorError
from .kpi_manager import KpiManager, KpiResults

_logger = logging.getLogger(__name__)


def calculate_kpis(
    esdl_file: str | Path,
    time_series: str | Path | None = None,
    timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
    system_lifetime: float = DEFAULT_SYSTEM_LIFETIME_YEARS,
    discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
    round_up_replacement: bool = True,
) -> KpiResults:
    """Calculate KPIs from an ESDL file with optional time series data.

    Cost data is extracted from ESDL ``costInformation`` elements. Cost unit
    conversion factors (EUR/kW, EUR/MW, etc.) are built-in; see
    ``kpicalculator.common.constants.COST_UNIT_FACTORS`` for the full list.

    Args:
        esdl_file: Path to ESDL file.
        time_series: Optional path to time series XML (when
            ``timeseries_dataframes`` not provided).
        timeseries_dataframes: Optional dict mapping asset IDs to pandas
            DataFrames with time-indexed energy/power data. Takes precedence
            over ``time_series`` when provided.
        system_lifetime: System lifetime in years.
            Default: ``DEFAULT_SYSTEM_LIFETIME_YEARS``.
        discount_rate: System-wide fallback discount rate in percent.
            Default: ``DEFAULT_DISCOUNT_RATE_PERCENT``.
        round_up_replacement: If True (default), NPV, LCOE, and TCO use
            ``ceil`` for the asset replacement count (financially exact).
            If False, uses the continuous factor
            ``max(1, n / technical_lifetime)`` for optimizer compatibility.

    Returns:
        :class:`KpiResults` containing calculated KPIs.

    Raises:
        KpiCalculatorError: For any calculation or validation errors.
    """
    esdl_path = Path(esdl_file)
    if not esdl_path.exists():
        raise KpiCalculatorError(f"ESDL file not found: {esdl_path}")

    _logger.info(f"Loading ESDL file: {esdl_path}")

    try:
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            str(esdl_path),
            time_series_file=str(time_series) if time_series else None,
            timeseries_dataframes=timeseries_dataframes,
        )
        return kpi_manager.calculate_all_kpis(
            system_lifetime=system_lifetime,
            discount_rate=discount_rate,
            round_up_replacement=round_up_replacement,
        )
    except KpiCalculatorError:
        raise
    except Exception as e:
        raise KpiCalculatorError(f"Calculation failed: {e}") from e


def calculate_kpis_from_simulator(
    simulator_result: pd.DataFrame,
    esdl_string: str,
    system_lifetime: float = DEFAULT_SYSTEM_LIFETIME_YEARS,
    discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT,
    round_up_replacement: bool = True,
) -> KpiResults:
    """Calculate KPIs from OMOTES simulator results.

    Args:
        simulator_result: DataFrame produced by the simulator, with a
            ``DatetimeIndex`` and ``(port_id, property_name)`` tuple columns.
        esdl_string: The input ESDL as an XML string, used to resolve port IDs
            to their owning assets and to extract cost data.
        system_lifetime: System lifetime in years.
            Default: ``DEFAULT_SYSTEM_LIFETIME_YEARS``.
        discount_rate: System-wide fallback discount rate in percent.
            Default: ``DEFAULT_DISCOUNT_RATE_PERCENT``.
        round_up_replacement: If True (default), NPV, LCOE, and TCO use
            ``ceil`` for the asset replacement count (financially exact).
            If False, uses the continuous factor
            ``max(1, n / technical_lifetime)`` for optimizer compatibility.

    Returns:
        :class:`KpiResults` containing calculated KPIs.

    Raises:
        KpiCalculatorError: For any calculation or validation errors.
    """
    try:
        kpi_manager = KpiManager()
        kpi_manager.load_from_simulator(simulator_result, esdl_string)
        return kpi_manager.calculate_all_kpis(
            system_lifetime=system_lifetime,
            discount_rate=discount_rate,
            round_up_replacement=round_up_replacement,
        )
    except KpiCalculatorError:
        raise
    except Exception as e:
        raise KpiCalculatorError(f"Calculation failed: {e}") from e


def build_esdl_string_with_kpis(esdl_string: str, kpi_results: KpiResults) -> str:
    """Embed KPI results into an ESDL XML string and return the updated string.

    Data-source-agnostic: works with results from any ``calculate_kpis_from_*``
    function. The KPI values are written as ``DistributionKPI`` elements on the
    main area of the energy system, ready for MapEditor visualisation.

    This is the standalone equivalent of :meth:`KpiManager.build_esdl_string_with_kpis`
    — use this when you do not hold a ``KpiManager`` instance.

    Args:
        esdl_string: ESDL XML string to embed KPIs into.
        kpi_results: KPI results from any ``calculate_kpis_from_*`` call.

    Returns:
        Updated ESDL XML string with KPIs embedded.

    Raises:
        KpiCalculatorError: If embedding fails.
    """
    from typing import cast

    from esdl.esdl_handler import EnergySystemHandler

    from .reporting.esdl_kpi_exporter import EsdlKpiExporter

    if not esdl_string or not esdl_string.strip():
        raise KpiCalculatorError("esdl_string must not be empty.")
    try:
        esh = EnergySystemHandler()
        esh.load_from_string(esdl_string)
        EsdlKpiExporter().export(kpi_results, esh.energy_system, destination=None, level="system")
        return cast(str, esh.to_string())
    except KpiCalculatorError:
        raise
    except Exception as e:
        raise KpiCalculatorError(f"Failed to build ESDL string with KPIs: {e}") from e
