# KPI Calculator

A Python package for calculating Key Performance Indicators (KPIs) for heat network designs from ESDL files.

Part of the 'Nieuwe Warmte Nu Design Toolkit' project.

## Quick Start

```python
from kpicalculator import calculate_kpis

# Automatic: Loads time series from InfluxDB references in ESDL
results = calculate_kpis(esdl_file="path/to/model.esdl")
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
```

[See test](unit_test/test_examples.py)

## Installation

```bash
pip install git+https://github.com/Project-OMOTES/kpi-calculator.git@feature/database-connectivity # From development branch

pip install kpi-calculator  # Coming soon
```

## Features

**KPI Categories:**
- **Cost**: CAPEX, OPEX, NPV, LCOE
- **Energy**: Consumption, production, efficiency
- **Emissions**: Total CO2, emissions per MWh

**Data Sources:**
- ESDL files with embedded cost data
- InfluxDB time series (automatic)
- XML time series files (testing)
- Pandas DataFrames (simulator integration)

**Architecture:**
- Modular adapters, calculators, and managers
- Full type safety with Pydantic v2
- Secure InfluxDB integration ([setup guide](doc/SECURE_DATABASE_SETUP.md))
- Comprehensive test coverage (83%+)

## Usage

### Basic Usage

```python
from kpicalculator import calculate_kpis

# Production: Automatically loads time series from InfluxDB profiles in ESDL
results = calculate_kpis(esdl_file="model.esdl")

# With optional parameters
results = calculate_kpis(
    esdl_file="model.esdl",
    system_lifetime=30  # Default: 30 years
)

# Testing: Override with XML file when database is unavailable
results = calculate_kpis(
    esdl_file="model.esdl",
    time_series="timeseries.xml"  # For testing only
)
```

[See tests](unit_test/test_examples.py)

### Data Source Options

**Cost Data** (priority order):
1. ESDL `costInformation` elements (production default)
2. CSV files (testing override only)

**Time Series Data** (priority order):
1. Pandas DataFrames (in-memory, simulator integration)
2. InfluxDB profiles (automatic from ESDL InfluxDBProfile references)
3. XML files (testing override when database unavailable)
4. None (asset-level calculations only)

**Note:** In production, time series are automatically loaded from InfluxDB when your ESDL file contains InfluxDBProfile references. You only need to specify `time_series` parameter for testing with XML files.

**Database Setup:** See [Secure Database Setup](doc/SECURE_DATABASE_SETUP.md) for configuring InfluxDB credentials using environment variables or secure configuration files.

### Simulator Integration

Pass time series data directly as pandas DataFrames:

```python
import pandas as pd

# Create time series data indexed by datetime
datetime_index = pd.date_range("2024-01-01", periods=24, freq="H")

timeseries_data = {
    "asset_id_1": pd.DataFrame({
        "mass_flow": [2.5, 2.6, 2.4, ...],
        "temperature": [353.15, 353.20, ...],
        "heat_supplied": [100000, 102000, ...],
    }, index=datetime_index),

    "asset_id_2": pd.DataFrame({
        "heat_demand": [80000, 81000, ...],
    }, index=datetime_index),
}

results = calculate_kpis(
    esdl_file="model.esdl",
    timeseries_dataframes=timeseries_data,
    system_lifetime=30
)
```

**Requirements for `timeseries_dataframes`:**
- **Keys**: Asset IDs matching ESDL file
- **Values**: DataFrames with datetime index and property columns
- **Properties**: Any of `mass_flow`, `pressure`, `temperature`, `volume_flow`, `heat_supplied`, `heat_demand`, `velocity`, `pressure_loss`, `heat_loss`

**Integration example:** The [simulator-worker](https://github.com/Project-OMOTES/simulator-worker) converts its port-level tuple-column format to asset-level DataFrames before calling `calculate_kpis()`. See [integration guide](https://github.com/Project-OMOTES/simulator-worker/blob/feature/kpi-calculator-integration/doc/SIMULATOR_WORKER_KPI_INTEGRATION.md).

[See test: test_timeseries_dataframes_integration](unit_test/test_examples.py)

### Testing with CSV Override

```python
# Override ESDL costs for testing
results = calculate_kpis(
    esdl_file="model.esdl",
    pipes_cost="test_pipes.csv",
    assets_cost="test_assets.csv"
)
```

[See test](unit_test/test_examples.py)

<details>
<summary><b>Advanced: Batch Processing</b></summary>

```python
from kpicalculator import KpiManager

# Batch process multiple scenarios
manager = KpiManager("unit_conversion.csv")
scenarios = [
    {"file": "scenario_1.esdl", "lifetime": 25},
    {"file": "scenario_2.esdl", "lifetime": 30},
    {"file": "scenario_3.esdl", "lifetime": 35}
]

for scenario in scenarios:
    manager.load_from_esdl(scenario["file"])
    results = manager.calculate_all_kpis(system_lifetime=scenario["lifetime"])
    # Compare results across scenarios
```

[See test](unit_test/test_examples.py)
</details>

## Results Structure

```python
{
    "costs": {
        "capex": {"All": 1000000, "HeatProducer": 500000, ...},
        "opex": {"All": 50000, ...},
        "npv": 850000,
        "lcoe": 45.5
    },
    "energy": {
        "consumption": 1e9,
        "production": 950000,
        "efficiency": 0.95
    },
    "emissions": {
        "total": 1200,
        "per_mwh": 1.26
    }
}
```

## Supported ESDL Features

**Cost Units:**
- EUR, EUR/m, EUR/kW, EUR/MW, EUR/kWh, EUR/MWh, EUR/yr, %
- Automatic unit conversion (e.g., EUR/m × pipe length = total investment)

**Time Series:**
- InfluxDBProfile references (production)
- XML files (testing)
- Pandas DataFrames (simulator integration)

**Asset Types:**
- Producers, consumers, pipes, storage, conversion, pumps

## Dependencies

**Runtime:**
- pandas ≥2.0.0
- numpy ~2.1.0
- pyesdl ~25.5.1
- pydantic ≥2.0.0
- influxdb ≥5.3.2
- xmltodict 0.14.2
- coloredlogs ~15.0.1

## Development Status

**Implemented:**
- ESDL adapter with cost extraction
- Cost, energy, and emission calculators
- InfluxDB integration
- Security layer with input validation
- CI/CD pipeline with UV

**Planned:**
- MESIDO adapter
- OMOTES Simulator adapter
- Advanced caching

See [Roadmap](https://github.com/Project-OMOTES/kpi-calculator/pull/1#issue-3238717128) for details.

## Contributing

This project is part of the OMOTES (Optimization and Modeling for Thermal Energy Systems) initiative.

## Releases

Releases are automatically published to [PyPI](https://pypi.org/project/kpi-calculator/) when a GitHub Release is created:

1. Ensure all changes are merged to `main`
2. Create and push a version tag: `git tag -a v1.2.3 -m "Release 1.2.3" && git push origin v1.2.3`
3. [Create a GitHub Release](https://github.com/Project-OMOTES/kpi-calculator/releases/new) from the tag
4. The [CI workflow](.github/workflows/ci.yml) will automatically build, verify, and publish to PyPI

The workflow includes security scanning, build verification, and generates cryptographic attestations for supply chain security.

## License

GNU General Public License v3.0
