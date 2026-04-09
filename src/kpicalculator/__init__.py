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

"""KPI Calculator package for energy systems.

The main entry points are :func:`calculate_kpis` and :class:`KpiManager`.
Both return a :class:`KpiResults` dict. The following types are exported for
use in type annotations:

- :class:`KpiResults` — top-level results dict
- :class:`FinancialResults` — ``results["financials"]``
- :class:`EnergyResults` — ``results["energy"]``
- :class:`EmissionResults` — ``results["emissions"]``
- :class:`AssetFinancialResult` — ``results["asset_financials"]["<asset_id>"]``
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from .adapters.common_model import Asset, AssetType, EnergySystem, TimeSeries
from .api import calculate_kpis
from .exceptions import (
    CalculationError,
    CredentialError,
    DatabaseError,
    DataSourceError,
    KpiCalculatorError,
    SecurityError,
    ValidationError,
)
from .kpi_manager import (
    AssetFinancialResult,
    EmissionResults,
    EnergyResults,
    FinancialResults,
    KpiManager,
    KpiResults,
)
from .security import ConfigFileCredentialManager, SecureCredentialManager

__all__ = [
    "Asset",
    "AssetFinancialResult",
    "AssetType",
    "CalculationError",
    "ConfigFileCredentialManager",
    "CredentialError",
    "DataSourceError",
    "DatabaseError",
    "EmissionResults",
    "EnergyResults",
    "EnergySystem",
    "FinancialResults",
    "KpiCalculatorError",
    "KpiManager",
    "KpiResults",
    "SecureCredentialManager",
    "SecurityError",
    "TimeSeries",
    "ValidationError",
    "calculate_kpis",
]

# Version information
__version__ = "0.1.0"


def main() -> None:
    """CLI entry point for KPI Calculator.

    Calculate KPIs from ESDL files with supporting data.

    Example:
        kpicalculator system.esdl --time-series data.xml
    """
    # Set up basic logging for CLI usage
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Calculate KPIs from ESDL files")

    parser.add_argument("esdl_file", type=Path, help="Path to ESDL file")
    parser.add_argument("--time-series", type=Path, help="Path to time series XML")
    parser.add_argument(
        "--system-lifetime", type=int, default=30, help="System lifetime in years (default: 30)"
    )

    args = parser.parse_args()

    try:
        results = calculate_kpis(
            esdl_file=args.esdl_file,
            time_series=args.time_series,
            system_lifetime=args.system_lifetime,
        )

        # TODO: Export results to ESDL file instead of printing JSON
        # This should write KPI results back to the ESDL file or create a new one
        logger = logging.getLogger(__name__)
        logger.info("KPI calculation completed successfully")
        logger.info(f"Total CAPEX: {results['financials']['capex']['All']:.2f} EUR")
        logger.info(f"Total emissions: {results['emissions']['total']:.3f} tons CO2")
        logger.info(f"Energy consumption: {results['energy']['consumption']:.0f} J")

        # Temporary: Print results until ESDL export is implemented
        print(json.dumps(results, indent=2))  # noqa: T201

    except KpiCalculatorError as e:
        print(f"Error: {e}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
