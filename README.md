# KPI Calculator

This repository is part of the 'Nieuwe Warmte Nu Design Toolkit' project.

A Python package for calculating Key Performance Indicators (KPIs) for energy systems described using ESDL (Energy System Description Language).

## Features

- Calculate cost-related KPIs (CAPEX, OPEX, NPV, LCOE)
- Calculate energy-related KPIs (consumption, demand, production, efficiency)
- Calculate emission-related KPIs (total emissions, emissions per MWh)
- Support for different data sources (ESDL files, simulator data, mesido data)

## Installation

```bash
pip install kpi-calculator
```

## Usage

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

## Dependencies

- pandas
- numpy
- esdl
- xmltodict