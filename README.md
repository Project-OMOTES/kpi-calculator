# KPI Calculator

This repository is part of the 'Nieuwe Warmte Nu Design Toolkit' project.

A Python package for calculating Key Performance Indicators (KPIs) for heat network designs. The calculator supports multiple data sources including ESDL (Energy System Description Language) files, MESIDO optimization results, and OMOTES Simulator outputs, providing unified KPI calculations regardless of the input source.

## Current Status

⚠️ **Development Version**: This package is currently under active development. The initial architecture has been implemented with ESDL support.

## Features

### Currently Implemented
- [x] Calculate cost-related KPIs (CAPEX, OPEX, NPV, LCOE)
- [x] Calculate energy-related KPIs (consumption, demand, production, efficiency)
- [x] Calculate emission-related KPIs (total emissions, emissions per MWh)
- [x] Support for ESDL files with XML time series data
- [x] Modular architecture with adapters, calculators, and manager components
- [x] Full type annotations and comprehensive test coverage

### Planned Features
- [ ] Support for MESIDO optimization results
- [ ] Support for OMOTES Simulator results
- [ ] Database connectivity for time series data
- [ ] Export functionality to ESDL files

## Installation

### Development Installation
```bash
git clone https://github.com/Project-OMOTES/kpi-calculator.git
cd kpi-calculator
pip install -e .
```

### PyPI Installation (Coming Soon)
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

## Current Limitations

- Only supports ESDL files as data source (MESIDO and OMOTES Simulator adapters not yet implemented)
- Time series data loaded from XML files (database connectivity planned)
- Results returned as dictionaries (ESDL export functionality planned)
- Limited input validation (comprehensive validation architecture planned)

## Dependencies

- pandas (data manipulation)
- numpy (numerical operations)
- pyesdl (ESDL file processing)
- xmltodict (XML parsing)
- coloredlogs (logging)

## Development

### Running Tests
```bash
pytest --cov=kpicalculator --cov-report html unit_test/
```

### Code Quality
```bash
black src/ unit_test/
isort src/ unit_test/
flake8 src/ unit_test/
mypy src/ unit_test/
```

## Roadmap

For the product roadmap with planned improvements and features for the KPI Calculator package see [Pull Request #1](https://github.com/Project-OMOTES/kpi-calculator/pull/1#issue-3238717128).
