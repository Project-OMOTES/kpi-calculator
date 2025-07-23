# Claude Instructions for KPI Calculator Project

## Project Overview
The KPI Calculator is a Python package for calculating Key Performance Indicators (KPIs) for energy systems. It processes data from different sources (ESDL files, simulator data, mesido data) and calculates various KPIs related to costs, energy consumption/production, and emissions.

## Repository Structure
```
kpi-calculator/
├── src/
│   └── kpicalculator/
│       ├── __init__.py
│       ├── kpi_manager.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── common_model.py
│       │   ├── esdl_adapter.py
│       │   ├── simulator_adapter.py
│       │   ├── mesido_adapter.py
│       │   └── xml_time_series_adapter.py
│       └── calculators/
│           ├── __init__.py
│           ├── cost_calculator.py
│           ├── energy_calculator.py
│           └── emission_calculator.py
├── unit_test/
│   ├── data/
│   └── new_kpi_calculator_test.py
└── README.md
```

## Key Components

### Common Model
- `Asset`: Represents an energy system asset with properties like power, length, costs, etc.
- `AssetType`: Enum for different types of assets (PRODUCER, CONSUMER, etc.)
- `TimeSeries`: Represents time series data with time steps and values
- `EnergySystem`: Container for assets with unit conversion factors

### Adapters
- `EsdlAdapter`: Converts ESDL files to the common model
- `SimulatorAdapter`: Converts simulator data to the common model
- `MesidoAdapter`: Converts mesido data to the common model
- `xml_time_series_adapter`: Parses time series data from XML files

### Calculators
- `CostCalculator`: Calculates cost-related KPIs (CAPEX, OPEX, NPV, LCOE)
- `EnergyCalculator`: Calculates energy-related KPIs (consumption, demand, production, efficiency)
- `EmissionCalculator`: Calculates emission-related KPIs (total emissions, emissions per MWh)

### KPI Manager
- Main entry point for the package
- Coordinates loading data from different sources
- Delegates KPI calculations to specialized calculators
- Aggregates results into a structured format

## Usage Example
```python
from kpicalculator import KpiManager

# Create KPI manager
kpi_manager = KpiManager("path/to/unit_conversion.csv")

# Load data from ESDL
kpi_manager.load_from_esdl(
    "path/to/model.esdl",
    "path/to/timeseries.xml",
    "path/to/pipes_costs.csv",
    "path/to/assets_costs.csv"
)

# Calculate KPIs
results = kpi_manager.calculate_all_kpis(system_lifetime=30)

# Access results
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
print(f"Total emissions: {results['emissions']['total']} tons CO2")
```

## Development Tasks
1. Fix the emissions calculation issue in the emission calculator
2. Complete the implementation of any missing components
3. Update tests to use the new architecture
4. Create example scripts to demonstrate usage

## Dependencies
- pandas
- numpy
- esdl (Energy System Description Language)
- xmltodict