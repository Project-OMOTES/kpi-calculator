Architecture
============

This document describes how the KPI Calculator is structured, how data flows through it, and where to look when making changes.

Role in the OMOTES Toolkit
--------------------------

The KPI calculator can be used standalone (via its Python API or command line), but within the OMOTES design toolkit it typically runs as part of a larger pipeline. The `ESDL MapEditor <https://github.com/ESDLMapEditorESSIM/esdl-mapeditor>`_ serves as the interface for drawing energy systems, triggering computations, and displaying results. The MapEditor already supports KPI visualization: dashboards, color-coded maps based on KPI values, and tabular result views.

The typical flow is:

1. A user designs an energy system in the MapEditor
2. The MapEditor sends the ESDL to the OMOTES orchestrator
3. A worker (simulator or optimizer) processes the ESDL and calls the KPI calculator
4. The KPI calculator returns results, which are written back into the ESDL as ``DistributionKPI`` elements
5. The MapEditor renders the KPIs from the returned ESDL

This means that decisions about output format — asset-level vs. system-level KPIs, category breakdowns, export structure — should be guided by what the MapEditor can consume and display. The richer the ESDL KPI output, the more the MapEditor can visualize.

Overview
--------

The package has four layers:

.. code-block:: text

   ┌──────────────────────────────────────────────────────────┐
   │  Public API                                              │
   │    api.py → calculate_kpis()                             │
   ├──────────────────────────────────────────────────────────┤
   │  KPI Manager (Orchestrator)                              │
   │    kpi_manager.py → KpiManager                           │
   ├──────────────────────────────────────────────────────────┤
   │  Calculators                                             │
   │    cost_calculator    energy_calculator    emission_calc  │
   ├──────────────────────────────────────────────────────────┤
   │  Adapters                                                │
   │    esdl_adapter    simulator_adapter    time_series_mgr   │
   ├──────────────────────────────────────────────────────────┤
   │  Common Model                                            │
   │    Asset    TimeSeries    EnergySystem                    │
   └──────────────────────────────────────────────────────────┘

**Adapters** parse external data (ESDL files, time series) into the common model. **Calculators** consume the common model and produce KPI results. The **KPI Manager** coordinates loading and calculation. The **API** is a thin wrapper that validates inputs and delegates to the manager.

Data Flow
---------

When ``calculate_kpis("model.esdl")`` is called:

1. ``api.py`` validates the file path and creates a ``KpiManager``
2. ``KpiManager.load_from_esdl()`` calls the ESDL adapter
3. The ESDL adapter:

   a. Parses the ESDL file using PyESDL (``EnergySystemHandler.load_file()``)
   b. Stores the parsed PyESDL object on ``EnergySystem.esdl_energy_system`` for later export
   c. Iterates over all assets in ``es.eAllContents()``, extracting physical properties and costs
   d. Delegates time series loading to ``TimeSeriesManager``
   e. Returns a populated ``EnergySystem`` containing ``Asset`` objects

4. ``KpiManager.calculate_all_kpis()`` runs the three calculators against the ``EnergySystem``
5. Results are returned as a ``KpiResults`` TypedDict

Common Model
------------

The common model (``adapters/common_model.py``) is the contract between adapters and calculators. Everything goes through these types.

Asset
^^^^^

.. code-block:: python

   @dataclass
   class Asset:
       id: str
       name: str
       asset_type: AssetType  # Producer, Consumer, Storage, Transport, etc.

       # Physical properties
       power: float = 0.0      # Watts
       length: float = 0.0     # meters (pipes)
       volume: float = 0.0     # m³ (storage)
       cop: float = 0.0        # Coefficient of performance

       # Cost properties (6 types, each with value + unit)
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

       # Lifecycle
       technical_lifetime: float = 40.0   # years
       discount_rate: float = 5.0         # percent
       emission_factor: float = 0.0       # kg CO2/GJ

       # Aggregation
       aggregation_count: int = 1

       # Time series data
       time_series: dict[str, TimeSeries] = field(default_factory=dict)

Cost units are stored as-is from ESDL. The cost calculator handles the conversion (see `Cost Unit Conversion`_).

TimeSeries
^^^^^^^^^^

.. code-block:: python

   @dataclass
   class TimeSeries:
       time_step: float        # seconds between data points
       values: list[float]     # measured values

EnergySystem
^^^^^^^^^^^^

.. code-block:: python

   @dataclass
   class EnergySystem:
       name: str
       assets: list[Asset]
       unit_conversion: dict[str, float] = field(default_factory=dict)
       source_metadata: dict[str, str] = field(default_factory=dict)
       esdl_energy_system: esdl.EnergySystem | None = None

This is the top-level container passed to all calculators. ``unit_conversion`` holds cost unit conversion factors (automatically populated from ``COST_UNIT_FACTORS`` in ``constants.py``). ``source_metadata`` records how the system was loaded (e.g., ``{"esdl_file": "model.esdl"}`` or ``{"esdl_source": "string"}``). ``esdl_energy_system`` holds the original PyESDL object set by the adapter for both file-loaded and string-loaded systems, enabling ESDL export without re-reading from disk.

ESDL Adapter
------------

The ESDL adapter (``adapters/esdl_adapter.py``) is the most complex component in the package. It does two things: extract assets with costs, and load time series.

Asset and Cost Extraction
^^^^^^^^^^^^^^^^^^^^^^^^^

The adapter iterates over ``es.eAllContents()`` and converts each ESDL asset to the common model ``Asset``. For each asset, it:

1. Maps the ESDL type to an ``AssetType`` enum value
2. Extracts physical properties (power, length, volume)
3. Extracts cost data from the ESDL ``costInformation`` element

The cost extraction maps six ESDL fields to internal fields:

.. code-block:: text

   ESDL costInformation field       →  Asset field
   ─────────────────────────────────────────────────
   investmentCosts                  →  investment_cost
   installationCosts                →  installation_cost
   fixedOperationalCosts            →  fixed_operational_cost
   variableOperationalCosts         →  variable_operational_cost
   fixedMaintenanceCosts            →  fixed_maintenance_cost
   variableMaintenanceCosts         →  variable_maintenance_cost

Each cost element in ESDL has a ``profileQuantityAndUnit`` that specifies the unit. The adapter stores both the raw value and the unit string on the ``Asset``.

Time Series Loading
^^^^^^^^^^^^^^^^^^^

Time series loading is handled by ``TimeSeriesManager`` (``adapters/time_series_manager.py``). The priority list is built dynamically by ``EsdlAdapter._process_energy_system()`` based on which sources are enabled:

.. code-block:: python

   source_priority = ["dataframes"]
   if use_database_profiles:
       source_priority.append("database")
   if time_series_file:
       source_priority.append("xml")
   source_priority.append("empty")

The full priority order when all sources are enabled is:

1. **pandas DataFrames** — passed directly via the ``timeseries_dataframes`` parameter
2. **InfluxDB profiles** — loaded from ``InfluxDBProfile`` references found in the ESDL
3. **XML files** — loaded from the ``time_series`` parameter
4. **No data** — calculators return zero for energy values (no rated-capacity fallback is implemented)

Each source is attempted in order. If one fails, it logs a warning and tries the next. In the OMOTES pipeline, the simulator-worker provides time series via DataFrames, bypassing InfluxDB entirely.

**InfluxDB disabled in the default API:** The public API (``KpiManager.load_from_esdl()``) passes ``use_database_profiles=False`` to the adapter. This means InfluxDB is **not added to the priority list at all** — it is excluded, not tried-and-skipped. The effective priority for the default API is: DataFrames → XML → empty. This is intentional: the default entry point is designed to work without a database connection. The adapter layer itself fully supports InfluxDB; re-enabling it requires passing ``use_database_profiles=True`` when constructing the adapter directly.

DataFrame Composite Key Mapping
""""""""""""""""""""""""""""""""

``TimeSeriesManager._load_from_dataframes()`` iterates over every column in each DataFrame and
stores the data under a **composite key** in the format ``asset_id|column_name``. This matches
the format produced by the InfluxDB and XML loaders, so ``EsdlAdapter._build_asset()`` can
resolve the time series without any special-casing for the DataFrame path.

The column name is used as the field name and must match one of the names recognised by the KPI
calculators. The full set is defined in ``KNOWN_TIME_SERIES_FIELDS`` (``common/constants.py``),
derived from the field name tuples imported by the calculators:

.. code-block:: text

   CONSUMPTION_FIELDS        ThermalConsumption, Consumption, Energy
   DEMAND_FIELDS             ThermalDemand, Demand
   PRODUCTION_FIELDS         ThermalProduction, Production, Energy
   ELECTRICAL_CONSUMPTION    ElectricalConsumption

Columns with unrecognised names are stored in the time series dict but will not be picked up by
any calculator — a warning is logged at load time so callers can catch the mismatch early.
Non-numeric columns are rejected with an error recorded in ``ValidationResult`` and never stored.

Cost Unit Conversion
--------------------

The cost calculator (``calculators/cost_calculator.py``) converts cost values from ESDL units to EUR using the asset's physical properties and built-in conversion factors defined in ``COST_UNIT_FACTORS`` (``common/constants.py``). The factors are looked up by ``_get_unit_factor(unit)`` from ``energy_system.unit_conversion``, which is automatically populated by the adapter.

**Investment and installation costs** — allowed units:

.. code-block:: text

   Unit            Conversion
   ──────────────────────────────────────────────────
   EUR             value (no factor needed)
   EUR/kW          value × power_W × 0.001
   EUR/MW          value × power_W × 1e-6
   EUR/m           value × length_m
   EUR/km          value × length_m × 0.001
   EUR/m3          value × volume_m3 (no factor needed)

**Fixed operational and fixed maintenance costs** — allowed units:

.. code-block:: text

   Unit            Conversion
   ──────────────────────────────────────────────────
   EUR, EUR/yr     value (used directly as annual cost)
   EUR/MW          value × power_W × 1e-6
   % OF CAPEX      value × (investment + installation) × 0.01

**Variable operational and variable maintenance costs** — allowed units:

.. code-block:: text

   Unit            Conversion
   ──────────────────────────────────────────────────
   EUR, EUR/yr     value (used directly as annual cost)
   EUR/kWh         value × annual_energy_J × 2.78e-7
   EUR/MWh         value × annual_energy_J × 2.78e-10

Variable costs use the **first** time series on the asset (regardless of key name). For geothermal assets with COP > 0, the energy is divided by COP before applying the cost rate.

**To add a new unit:** Add the unit string to the ``allowed_units`` list in the relevant cost method, add a conversion branch, add the factor to ``COST_UNIT_FACTORS`` in ``constants.py``, and add a test case.

Calculators
-----------

All three calculators take an ``EnergySystem`` and return part of the ``KpiResults`` dict. They are independent of each other.

Cost Calculator
^^^^^^^^^^^^^^^

``calculators/cost_calculator.py`` — the largest calculator.

- **CAPEX**: Sum of (investment + installation) per asset, converted from ESDL units, grouped by asset category (Production, Transport, Storage, Conversion, Consumption, All)
- **OPEX**: Sum of (fixed_operational + variable_operational + fixed_maintenance + variable_maintenance) per asset
- **NPV**: Standard discounted cash flow: ``CAPEX + Sum(OPEX_t / (1 + rate/100)^t)`` over system lifetime (default 30 years, 5% discount rate). Includes asset replacement costs when technical lifetime < system lifetime.
- **LCOE**: ``NPV / discounted_energy_delivered``

Lifetime Handling
"""""""""""""""""

Two different lifetimes are used:

- **System lifetime** (default 30 years): The analysis period for NPV and LCOE. Passed as a parameter to ``calculate_kpis()``.
- **Technical lifetime** (default 40 years per asset): How long each asset lasts. Extracted from ESDL ``costInformation.technicalLifetime``. When an asset's technical lifetime is shorter than the system lifetime, the cost calculator includes replacement costs.

Energy Calculator
^^^^^^^^^^^^^^^^^

``calculators/energy_calculator.py`` — ~170 lines.

- **Consumption/Production/Demand**: Sums time series values × time step, annualized
- **Efficiency**: consumption / production

Without time series, energy values are returned as zero (no rated-capacity fallback is implemented).

Emission Calculator
^^^^^^^^^^^^^^^^^^^

``calculators/emission_calculator.py`` — ~135 lines.

- **Total emissions**: Sum of (emission_factor × energy) per asset, converted to tonnes
- **Emissions per MWh**: total_emissions / consumption_in_MWh

Emission factors come from ESDL carrier definitions (kg CO2/GJ).

ESDL Export
-----------

The exporter (``reporting/esdl_kpi_exporter.py``) writes KPI results back into an ESDL structure using ``DistributionKPI`` elements. Currently supports system-level export only.

The exporter does not perform calculations — it receives pre-calculated results and formats them into ESDL-compliant XML elements.

String-Loaded ESDL Support
^^^^^^^^^^^^^^^^^^^^^^^^^^

The adapter stores the parsed PyESDL object on the ``EnergySystem.esdl_energy_system`` field for both file-loaded and string-loaded systems. The exporter checks this field first and reuses the stored object, avoiding the need to re-load from disk.

**ESDL object resolution in the exporter:**

1. Check ``energy_system.esdl_energy_system`` — use it if present (covers both load paths)
2. Otherwise, fall back to ``handler.load_file()`` using ``source_metadata["esdl_file"]`` or the ``source_esdl_file`` parameter
3. If neither is available, raise ``ValueError``

This enables workflows where ESDL never touches disk: load from string → calculate KPIs → export to ESDL object → serialize to string or pass to another service. Critical for simulator-worker integration and MapEditor REST service.

Project Layout
--------------

.. code-block:: text

   src/kpicalculator/
   ├── api.py                          # Public API: calculate_kpis()
   ├── kpi_manager.py                  # Orchestrator + result TypedDicts
   ├── exceptions.py                   # Custom exception hierarchy
   ├── adapters/
   │   ├── base_adapter.py             # Abstract base (enforces EnergySystem return)
   │   ├── common_model.py             # Asset, TimeSeries, EnergySystem
   │   ├── esdl_adapter.py             # ESDL parsing + cost extraction
   │   ├── simulator_adapter.py        # OMOTES Simulator port→asset mapping
   │   ├── time_series_manager.py      # Multi-source time series loading
   │   ├── database_time_series_loader.py  # InfluxDB integration
   │   └── xml_time_series_adapter.py  # XML time series (testing)
   ├── calculators/
   │   ├── cost_calculator.py          # CAPEX, OPEX, NPV, LCOE
   │   ├── energy_calculator.py        # Consumption, production, efficiency
   │   └── emission_calculator.py      # CO2 emissions
   ├── reporting/
   │   ├── base_exporter.py            # Export interface
   │   └── esdl_kpi_exporter.py        # Write KPIs back to ESDL
   ├── security/
   │   ├── credential_manager.py       # Database credential handling
   │   └── input_validator.py          # Path and input validation
   └── common/
       ├── constants.py                # Defaults and conversion factors
       ├── types.py                    # Pydantic models
       └── logging_utils.py            # Structured logging

Test Layout
-----------

Tests live in ``unit_test/`` alongside the source. Test data (ESDL files, XML time series) is in ``unit_test/data/``.

.. code-block:: text

   unit_test/
   ├── data/
   │   ├── Unit_test_ESDL.esdl       # Main test ESDL fixture
   │   └── power_timeseries.xml      # Matching XML time series
   ├── test_api.py                   # Public API integration tests
   ├── test_kpi_calculator.py        # End-to-end KPI calculation + DataFrame mapping + ESDL export
   ├── test_examples.py              # README code examples (regression tests)
   ├── test_esdl_adapter.py          # ESDL adapter branch coverage
   ├── test_esdl_cost_extraction.py  # Cost extraction + unit conversion
   ├── test_esdl_kpi_exporter.py     # Unit: EsdlKpiExporter in isolation (mocked)
   ├── test_emission_calculator.py   # Emission calculator edge cases
   ├── test_database_time_series_loader.py  # InfluxDB loader (mocked connections)
   ├── test_database_connectivity.py # Database connection handling
   ├── test_credential_manager.py    # Credential loading and environment variables
   ├── test_input_validator.py       # Path, host, and input validation
   ├── test_pydantic_models.py       # Pydantic model validation (property-based)
   └── test_logging_utils.py         # Structured logging

The test files fall into three categories:

- **Integration tests** (``test_kpi_calculator.py``, ``test_examples.py``, ``test_api.py``) — load real ESDL fixtures, run the full pipeline, and assert specific output values.
- **Unit tests** (all other ``test_*.py`` files) — test individual classes in isolation, using mocks for external dependencies (database connections, file I/O).
- **Security tests** (``test_credential_manager.py``, ``test_input_validator.py``) — validate threat detection, path traversal prevention, and credential management.

Run the full suite with coverage:

.. code-block:: bash

   uv run pytest unit_test/

Adding a New Adapter
--------------------

To add a new data source (e.g., MESIDO optimization results):

1. Create ``adapters/mesido_adapter.py`` subclassing ``BaseAdapter``
2. Define a **typed** ``load_data()`` method whose signature matches the actual inputs
   of your data source — do not try to fit all adapters into one shared signature
3. Parse the source data and construct ``Asset`` objects with costs, time series, and
   physical properties; return a populated ``EnergySystem``
4. Add a ``load_from_mesido()`` method to ``KpiManager`` that instantiates your adapter
   and calls it directly
5. Export the new class from ``adapters/__init__.py``

The calculators don't need to change — they only depend on the common model.

**BaseAdapter design principle**: the base class enforces only the ``EnergySystem``
return type. Each adapter owns its own loading signature. ``KpiManager`` calls the
specific adapter it knows about directly, not through the base class interface. The
``SimulatorAdapter`` (``adapters/simulator_adapter.py``) is the reference implementation
for this pattern: it accepts a ``(pd.DataFrame, esdl_string)`` pair, resolves port IDs
to asset IDs, and delegates cost extraction to ``EsdlAdapter.load_from_string()``.

The ``# type: ignore[override]`` annotations on ``load_data`` and ``validate_source``
in concrete adapters are intentional — they narrow the inherited ``Any`` signature to
specific types without breaking Liskov substitutability in practice, because callers
always use the concrete type directly.
