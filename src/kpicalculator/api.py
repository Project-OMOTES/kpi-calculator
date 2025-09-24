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

from .exceptions import KpiCalculatorError
from .kpi_manager import KpiManager, KpiResults


def calculate_kpis(
    esdl_file: str | Path,
    time_series: str | Path,
    pipes_cost: str | Path,
    assets_cost: str | Path,
    unit_conversion: str | Path | None = None,
    system_lifetime: int = 30,
) -> KpiResults:
    """Calculate KPIs from ESDL files with supporting data.

    This is the main library function that can be called programmatically.

    Args:
        esdl_file: Path to ESDL file
        time_series: Path to time series XML
        pipes_cost: Path to pipes cost CSV
        assets_cost: Path to assets cost CSV
        unit_conversion: Optional path to unit conversion CSV file
        system_lifetime: System lifetime in years (default: 30)

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

    try:
        kpi_manager = KpiManager(unit_conversion_path)
        kpi_manager.load_from_esdl(
            str(esdl_path), str(time_series), str(pipes_cost), str(assets_cost)
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
