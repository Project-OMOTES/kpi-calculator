# src/kpicalculator/adapters/common_model.py
from dataclasses import dataclass, field
from enum import Enum

from ..common.constants import DEFAULT_DISCOUNT_RATE_PERCENT, DEFAULT_TECHNICAL_LIFETIME_YEARS


class AssetType(Enum):
    PRODUCER = "Producer"
    CONSUMER = "Consumer"
    STORAGE = "Storage"
    TRANSPORT = "Transport"
    CONVERSION = "Conversion"
    PIPE = "Pipe"
    PUMP = "Pump"
    GEOTHERMAL = "GeothermalSource"


@dataclass
class TimeSeries:
    time_step: float
    values: list[float]


@dataclass
class Asset:
    id: str
    name: str
    asset_type: AssetType

    # Physical properties
    power: float = 0.0  # W
    length: float = 0.0  # m (for pipes)
    volume: float = 0.0  # m³ (for storage)
    cop: float = 0.0  # Coefficient of performance

    # Cost properties
    investment_cost: float = 0.0
    investment_cost_unit: str = "EUR"
    installation_cost: float = 0.0
    installation_cost_unit: str = "EUR"
    fixed_operational_cost: float = 0.0
    fixed_operational_cost_unit: str = "EUR/yr"
    variable_operational_cost: float = 0.0
    variable_operational_cost_unit: str = "EUR/MWh"
    fixed_maintenance_cost: float = 0.0
    fixed_maintenance_cost_unit: str = "EUR/yr"
    variable_maintenance_cost: float = 0.0
    variable_maintenance_cost_unit: str = "EUR/MWh"

    # Lifecycle properties
    technical_lifetime: float = DEFAULT_TECHNICAL_LIFETIME_YEARS  # years
    discount_rate: float = DEFAULT_DISCOUNT_RATE_PERCENT  # %
    emission_factor: float = 0.0  # kg/GJ

    # Aggregation
    aggregation_count: int = 1

    # Time series data
    time_series: dict[str, TimeSeries] = field(default_factory=dict)


@dataclass
class EnergySystem:
    name: str
    assets: list[Asset]
    unit_conversion: dict[str, float] = field(default_factory=dict)
    source_metadata: dict[str, str] = field(default_factory=dict)
