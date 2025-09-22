# KPI Calculator

This repository is part of the 'Nieuwe Warmte Nu Design Toolkit' project.

A Python package for calculating Key Performance Indicators (KPIs) for heat network designs. The calculator supports multiple data sources including ESDL (Energy System Description Language) files, MESIDO optimization results, and OMOTES Simulator outputs, providing unified KPI calculations regardless of the input source.

## Current Status

**Development Version**: This package is currently under active development. The initial architecture has been implemented with ESDL support.

## Features

### Currently Implemented
- [x] Calculate cost-related KPIs (CAPEX, OPEX, NPV, LCOE)
- [x] Calculate energy-related KPIs (consumption, demand, production, efficiency)
- [x] Calculate emission-related KPIs (total emissions, emissions per MWh thermal)
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

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh  # Linux/macOS
# or: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"  # Windows

# Set up development environment
uv sync --dev
```

### PyPI Installation (Coming Soon)
```bash
pip install kpi-calculator
```

## Usage

```python
from kpicalculator import KpiManager
from kpicalculator.kpi_manager import KpiResults

# Create KPI manager
kpi_manager = KpiManager("path/to/unit_conversion.csv")

# Load data from ESDL
kpi_manager.load_from_esdl(
    "path/to/model.esdl",
    "path/to/timeseries.xml",
    "path/to/pipes_costs.csv",
    "path/to/assets_costs.csv"
)

# Calculate KPIs with typed results
results: KpiResults = kpi_manager.calculate_all_kpis(system_lifetime=30)

# Access results with type safety
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
print(f"Total emissions: {results['emissions']['total']} tons CO2")
print(f"Heat production: {results['energy']['production']} MWh thermal")
```

## Current Status & Implementation

### ✅ Completed Features
- **Modern validation architecture**: Dual-layer validation with Pydantic v2 + InputValidator
- **Database connectivity**: Secure InfluxDB integration with credential management
- **Comprehensive testing**: 181 tests with 89% coverage, property-based testing
- **Type safety**: Full mypy compliance with TypedDict return types
- **Security**: Bandit-validated code, secure credential handling
- **CI/CD**: Complete pipeline with UV dependency management

### 🚧 Current Limitations
- **MESIDO adapter**: Planned for production integration
- **OMOTES Simulator adapter**: Planned for production integration
- **ESDL export**: Results export to ESDL format planned
- **Advanced caching**: Query result caching for performance optimization

## Dependencies

### Runtime Dependencies
- **pandas** (≥2.0.0) - Data manipulation with modern numpy 2.x support
- **numpy** (≥1.24.3, <2.0) - Numerical operations, compatible with pandas
- **pyesdl** (25.5.1) - Energy System Description Language support
- **xmltodict** (0.14.2) - XML parsing for time series data
- **pydantic** (≥2.0.0) - Modern data validation with type hints
- **influxdb** (≥5.3.2) - Database connectivity for time series
- **coloredlogs** (~15.0.1) - Enhanced logging utilities

### Development Dependencies
- **ruff** (≥0.6.0) - Modern linting and formatting (replaces black, flake8, isort)
- **pytest** (~7.3.1) with pytest-cov (~4.0.0) - Testing framework with coverage
- **mypy** (~1.5.1) - Static type checking
- **hypothesis** (≥6.0.0) - Property-based testing for edge case discovery
- **interrogate** (≥1.7.0) - Documentation coverage tracking
- **pytest-xdist** (≥3.0.0) - Parallel test execution
- **pre-commit** (~3.6.0) - Git hook management

## Development Commands

### Modern Development Workflow

The project uses modern Python tooling for development:

```bash
# Run tests with coverage (89% coverage achieved)
uv run pytest --cov=src/kpicalculator --cov-report html --cov-report term-missing unit_test/

# Code quality pipeline (replaces black, flake8, isort)
uv run ruff check --fix src/ unit_test/  # Linting with auto-fixes
uv run ruff format src/ unit_test/        # Code formatting
uv run mypy src/kpicalculator             # Type checking

# Documentation coverage (86.6% achieved)
uv run interrogate src/ --fail-under=80

# Parallel testing
uv run pytest -n auto unit_test/

# Complete validation pipeline
uv run ruff check --fix src/ unit_test/ && uv run ruff format src/ unit_test/ && uv run mypy src/kpicalculator && uv run pytest --cov=src/kpicalculator --cov-report term-missing unit_test/

# Build package
uv build

# Update dependencies
uv lock --upgrade
```

### Quality Metrics
- **Test Coverage**: 89% (target: 80%)
- **Documentation Coverage**: 86.6% (target: 80%)
- **Type Checking**: Full mypy compliance
- **Tests**: 181 tests passing
- **Modern Tooling**: Ruff (replacing black/flake8/isort), Hypothesis, pytest-xdist

## Roadmap

For the product roadmap with planned improvements and features for the KPI Calculator package see [Pull Request #1](https://github.com/Project-OMOTES/kpi-calculator/pull/1#issue-3238717128).
