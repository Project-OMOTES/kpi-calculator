# KPI Calculator

Calculates cost, energy, and emission KPIs from ESDL energy system models. Takes an ESDL file, handles the parsing, unit conversions, and time series loading, and returns standardized results in a single function call.

Part of the [OMOTES](https://github.com/Project-OMOTES) project (Nieuwe Warmte Nu Design Toolkit).

## Where It Fits

The KPI calculator can be used as a standalone tool (via its Python API or command line), but within the OMOTES design toolkit it typically runs as part of a larger pipeline. The [ESDL MapEditor](https://github.com/ESDLMapEditorESSIM/esdl-mapeditor) is the interface where users draw energy systems, run computations, and view results. The KPI calculator is called by worker processes (e.g., the [simulator-worker](https://github.com/Project-OMOTES/simulator-worker)) to compute KPIs after a simulation or optimization run. Results are written back into the ESDL as `DistributionKPI` elements, which the MapEditor then renders as dashboards, colored maps, and tables.

```
MapEditor  →  Orchestrator  →  Worker (simulation/optimization)
                                  ↓
                              KPI Calculator (this package)
                                  ↓
                              ESDL with KPIs  →  MapEditor (visualization)
```

## Quick Start

```python
from kpicalculator import calculate_kpis

results = calculate_kpis(esdl_file="path/to/model.esdl")
print(f"Total CAPEX: {results['costs']['capex']['All']} EUR")
print(f"LCOE: {results['costs']['lcoe']} EUR/MWh")
```

## What It Does

The package reads an ESDL energy system design and:

1. **Extracts cost data** from ESDL `costInformation` elements, converting between units (EUR/m, EUR/kW, EUR/MW, EUR/MWh, %, etc.)
2. **Loads time series** from the best available source — pandas DataFrames, InfluxDB profiles, or XML files. Without time series, energy values are returned as zero.
3. **Calculates KPIs** across three categories:
   - **Cost**: CAPEX, OPEX, NPV (30-year, 5% discount), LCOE
   - **Energy**: Consumption, production, demand, efficiency
   - **Emissions**: Total CO2e, emissions intensity per MWh

Cost results are broken down by asset category (Production, Transport, Storage, Conversion, Consumption, All). Energy and emission results are system-wide totals.

## Installation

```bash
pip install kpi-calculator
```

For full usage instructions — all parameter variants, time series options, ESDL string loading, command-line interface, and results format — see the [Getting Started](https://kpi-calculator.readthedocs.io/en/latest/getting_started.html) guide.

## Dependencies

- pyesdl ~=25.7
- pandas >= 2.2.2
- numpy >= 2.1.0
- pydantic >= 2.0.0
- influxdb >= 5.3.2
- coloredlogs ~=15.0.1
- xmltodict == 0.14.2
- urllib3 >= 2.6.3
- filelock >= 3.20.1

## Development

```bash
git clone https://github.com/Project-OMOTES/kpi-calculator.git
cd kpi-calculator
pip install uv
uv sync --all-extras
uv run pytest unit_test/
```

See the [developer documentation](doc/dev_documentation/) for architecture details, tooling, and contribution workflow.

Tests enforce a minimum coverage threshold (configured in `pyproject.toml`).

## Releases

Published to [PyPI](https://pypi.org/project/kpi-calculator/) automatically when a GitHub Release is created from a version tag.

## Documentation

Full documentation is hosted on [ReadTheDocs](https://kpi-calculator.readthedocs.io/):

- [Getting Started](https://kpi-calculator.readthedocs.io/en/latest/getting_started.html) — installation, usage, and results format
- [KPI Guide](https://kpi-calculator.readthedocs.io/en/latest/user_documentation/kpi_guide.html) — interpreting calculation results
- [Developer Documentation](https://kpi-calculator.readthedocs.io/en/latest/dev_documentation/architecture.html) — architecture, setup, and contributing

## License

GNU General Public License v3.0
