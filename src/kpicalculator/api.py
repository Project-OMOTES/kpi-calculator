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

"""Public API for KPI Calculator library."""

import logging
from pathlib import Path

import pandas as pd

from .common.constants import DEFAULT_SYSTEM_LIFETIME_YEARS
from .exceptions import KpiCalculatorError
from .kpi_manager import KpiManager, KpiResults


def calculate_kpis(
    esdl_file: str | Path,
    time_series: str | Path | None = None,
    timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
    unit_conversion: str | Path | None = None,
    system_lifetime: float = DEFAULT_SYSTEM_LIFETIME_YEARS,
) -> KpiResults:
    """Calculate KPIs from ESDL files with supporting data.

    This is the main library function that can be called programmatically.
    Supports both traditional file-based time series and pandas DataFrames
    for simulator-worker integration.

    Cost data is extracted from ESDL costInformation elements.

    Args:
        esdl_file: Path to ESDL file
        time_series: Optional path to time series XML (when timeseries_dataframes not provided)
        timeseries_dataframes: Optional dict mapping asset IDs to pandas DataFrames
            with time-indexed energy/power data. When provided, takes precedence
            over database loading and time_series file parameter.
        unit_conversion: Optional path to unit conversion CSV file
        system_lifetime: System lifetime in years

    Returns:
        KpiResults containing calculated KPIs

    Raises:
        KpiCalculatorError: For any calculation or validation errors
    """
    logger = logging.getLogger(__name__)

    # Validate inputs
    esdl_path = Path(esdl_file)
    if not esdl_path.exists():
        raise KpiCalculatorError(f"ESDL file not found: {esdl_path}")

    logger.info(f"Loading ESDL file: {esdl_path}")

    # Convert paths to strings for KpiManager
    unit_conversion_path = str(unit_conversion) if unit_conversion else None

    logger.info("Extracting costs from ESDL costInformation elements")

    try:
        kpi_manager = KpiManager(unit_conversion_path)
        kpi_manager.load_from_esdl(
            str(esdl_path),
            time_series_file=str(time_series) if time_series else None,
            timeseries_dataframes=timeseries_dataframes,
        )

        logger.info("Calculating KPIs...")
        results = kpi_manager.calculate_all_kpis(system_lifetime=system_lifetime)
        logger.info("KPI calculation completed successfully")

        return results

    except Exception as e:
        logger.error(f"KPI calculation failed: {e}")
        # Re-raise as KpiCalculatorError if it isn't already one
        if isinstance(e, KpiCalculatorError):
            raise
        raise KpiCalculatorError(f"Calculation failed: {e}") from e
