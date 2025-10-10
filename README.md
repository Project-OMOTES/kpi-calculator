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

### Production Mode (Recommended)

The KPI calculator can extract cost information directly from ESDL files, eliminating the need for separate CSV cost files:

```python
from kpicalculator import calculate_kpis

# Calculate KPIs with costs extracted from ESDL file
results = calculate_kpis(
    esdl_file="path/to/model.esdl",
    time_series="path/to/timeseries.xml",  # Optional: can use database refs, DataFrames, or omit
    system_lifetime=30  # Optional: defaults to 30 years
)

# Access results with type safety
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
print(f"Total OPEX: {results['costs']['opex']['All']} EUR/year")
print(f"NPV: {results['costs']['npv']} EUR")
print(f"LCOE: {results['costs']['lcoe']} EUR/MWh")
print(f"Total emissions: {results['emissions']['total']} tons CO2")
print(f"Energy consumption: {results['energy']['consumption']} J")
print(f"Heat production: {results['energy']['production']} MWh thermal")
```

**How it works:**
- Cost data is automatically extracted from ESDL `costInformation` elements
- Supports diverse cost units: EUR/m, EUR/kW, EUR/MW, EUR/kWh, EUR/MWh, %, EUR/yr
- Automatically applies unit conversions (e.g., EUR/m × pipe length = total investment)
- No external CSV files required for production systems

**Time Series Data Sources:**
The `time_series` parameter is optional. Time series data can be provided through:
1. **XML file**: Traditional `time_series="path/to/timeseries.xml"`
2. **Database references**: Automatically loaded from InfluxDB when ESDL contains database profile references
3. **Pandas DataFrames**: Pass `timeseries_dataframes` parameter for in-memory data (see section below)
4. **None**: Omit time series when only asset-level calculations are needed

### Override Mode (Testing)

For testing or when external cost databases are preferred, you can override ESDL costs with CSV files:

```python
from kpicalculator import calculate_kpis

# Override ESDL costs with CSV files
results = calculate_kpis(
    esdl_file="path/to/model.esdl",
    pipes_cost="path/to/pipes_costs.csv",      # Optional: overrides ESDL pipe costs
    assets_cost="path/to/assets_costs.csv",    # Optional: overrides ESDL asset costs
    time_series="path/to/timeseries.xml",      # Optional: can use database refs, DataFrames, or omit
    system_lifetime=30  # Optional: defaults to 30 years
)
```

**Cost Priority:**
1. CSV files (if provided) - highest priority
2. ESDL costInformation - automatic fallback
3. None - graceful degradation (calculations proceed without costs)

### Available KPI Categories

The calculator provides three main categories of KPIs:

#### 1. Cost KPIs (`results['costs']`)
- **CAPEX** (Capital Expenditure): Initial investment costs by asset type and total
- **OPEX** (Operating Expenditure): Annual operating costs by asset type and total
- **NPV** (Net Present Value): Discounted lifetime value
- **LCOE** (Levelized Cost of Energy): Cost per unit of energy delivered

#### 2. Energy KPIs (`results['energy']`)
- **consumption**: Total energy consumed (J)
- **demand**: Energy demand metrics
- **production**: Energy produced (MWh thermal)
- **efficiency**: System efficiency metrics

#### 3. Emission KPIs (`results['emissions']`)
- **total**: Total CO2 emissions (tons)
- **per_mwh**: Emissions per unit of thermal energy delivered

### Supported Data Sources

The KPI calculator supports multiple input sources:

1. **ESDL Files**: Direct energy system descriptions with XML time series
2. **MESIDO Results**: Optimization workflow outputs (planned)
3. **OMOTES Simulator**: Thermo-hydraulic simulation results (planned)

### Using Pandas DataFrames

For integration with simulators or when working with in-memory time series data:

```python
import pandas as pd
from kpicalculator import calculate_kpis

# Prepare time series as pandas DataFrames
# DataFrames should have a time index and columns for energy/power values
timeseries_data = {
    "asset_id_1": pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=8760, freq="H"),
        "power": [100.0, 120.0, 110.0, ...]  # Power values in appropriate units
    }).set_index("timestamp"),
    "asset_id_2": pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=8760, freq="H"),
        "energy": [50.0, 55.0, 52.0, ...]  # Energy values in appropriate units
    }).set_index("timestamp"),
}

# Calculate KPIs using the API function with DataFrame input
results = calculate_kpis(
    esdl_file="path/to/model.esdl",
    pipes_cost="path/to/pipes_costs.csv",
    assets_cost="path/to/assets_costs.csv",
    timeseries_dataframes=timeseries_data,  # Provide DataFrames directly
    unit_conversion="path/to/unit_conversion.csv",
    system_lifetime=30
)

# Access results as usual
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
```

**Note**: When `timeseries_dataframes` is provided, it takes precedence over the `time_series` file parameter. This is particularly useful for:
- Integration with OMOTES simulator-worker
- Processing real-time simulation results
- Working with preprocessed time series data

### Advanced Usage with KpiManager

```python
# Direct use of KpiManager for more control
kpi_manager = KpiManager("path/to/unit_conversion.csv")

# Load from ESDL with pandas DataFrames
kpi_manager.load_from_esdl(
    esdl_file="path/to/model.esdl",
    pipes_cost_file="path/to/pipes_costs.csv",
    assets_cost_file="path/to/assets_costs.csv",
    timeseries_dataframes=timeseries_data  # Optional: Use DataFrames instead of files
)

# Or load from XML file
kpi_manager.load_from_esdl(
    esdl_file="path/to/model.esdl",
    pipes_cost_file="path/to/pipes_costs.csv",
    assets_cost_file="path/to/assets_costs.csv",
    time_series_file="path/to/timeseries.xml"  # Traditional file-based approach
)

# Calculate with custom parameters
results = kpi_manager.calculate_all_kpis(system_lifetime=30)

# Export results back to ESDL (planned feature)
# kpi_manager.export_to_esdl("path/to/output.esdl")
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
- **numpy** (~2.1.0) - Numerical operations, compatible with simulator-worker
- **pyesdl** (~25.5.1) - Energy System Description Language support, compatible with simulator-worker
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
