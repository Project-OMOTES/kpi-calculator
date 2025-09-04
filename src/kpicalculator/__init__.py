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

"""KPI Calculator package for energy systems."""

from .adapters.common_model import Asset, AssetType, EnergySystem, TimeSeries
from .exceptions import (
    CalculationError,
    CredentialError,
    DatabaseError,
    DataSourceError,
    KpiCalculatorError,
    SecurityError,
    ValidationError,
)
from .kpi_manager import KpiManager
from .security import ConfigFileCredentialManager, SecureCredentialManager

__all__ = [
    "Asset",
    "AssetType",
    "EnergySystem",
    "TimeSeries",
    "KpiManager",
    "KpiCalculatorError",
    "ValidationError",
    "SecurityError",
    "DataSourceError",
    "CalculationError",
    "DatabaseError",
    "CredentialError",
    "SecureCredentialManager",
    "ConfigFileCredentialManager",
]

# Version information
__version__ = "0.1.0"
