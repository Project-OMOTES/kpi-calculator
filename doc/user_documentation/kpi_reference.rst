Input Reference
===============

This page collects technical reference information for users providing data to the KPI Calculator. For explanations of what each KPI means and how to interpret results, see :doc:`kpi_guide`. For usage instructions, see :doc:`../getting_started`.

Time Series Keys
----------------

The calculators search for time series data on each asset using specific key names. The first matching key is used; if none match, the asset contributes zero to that metric.

**Energy calculator:**

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Metric
     - Asset types
     - Keys searched (in order)
   * - Consumption
     - Consumer
     - ``ThermalConsumption``, ``Consumption``, ``Energy``
   * - Production
     - Producer, Geothermal
     - ``ThermalProduction``, ``Production``, ``Energy``
   * - Demand
     - Consumer
     - ``ThermalDemand``, ``Demand`` (falls back to consumption keys)

**Emission calculator:**

.. list-table::
   :header-rows: 1
   :widths: 25 25 50

   * - Asset type
     - Keys searched (in order)
     - Notes
   * - Producer, Geothermal
     - ``ThermalProduction``, ``Production``, ``Energy``
     - Same as energy production
   * - Consumer
     - ``ThermalConsumption``, ``Consumption``, ``Energy``
     - Same as energy consumption
   * - Conversion
     - ``ElectricalConsumption``, ``ThermalProduction``
     - Only used for emission calculation

Time series values are in Watts (power). The calculator integrates over the time step to get energy in Joules and annualizes based on the series duration. If no matching key is found, the asset contributes zero to that metric (logged at DEBUG level). If the time series has a non-positive duration (``time_step × number_of_values ≤ 0``), the asset is skipped with a WARNING log.

**Cost calculator:** Variable operational and maintenance costs in ``EUR/kWh`` or ``EUR/MWh`` use the **first** time series available on the asset (regardless of key name). For geothermal assets with COP > 0, the energy is divided by COP before applying the cost rate.

Asset Categories
----------------

Cost KPIs (CAPEX, OPEX) are broken down by category. Each ESDL asset type maps to one category:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Category
     - Asset types
   * - Production
     - Producer, Geothermal
   * - Consumption
     - Consumer
   * - Storage
     - Storage
   * - Transport
     - Transport, Pipe, Pump
   * - Conversion
     - Conversion

The **All** category is the sum across all asset types.

Cost Units
----------

The calculator accepts cost values in the units specified in the ESDL ``costInformation`` element. Built-in conversion factors (defined in ``COST_UNIT_FACTORS`` in ``constants.py``) handle the conversion automatically.

**Investment and installation costs:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Unit
     - Conversion
   * - ``EUR``
     - Used directly (no conversion factor needed)
   * - ``EUR/kW``
     - value x asset power (W) x 0.001
   * - ``EUR/MW``
     - value x asset power (W) x 1e-6
   * - ``EUR/m``
     - value x asset length (m)
   * - ``EUR/km``
     - value x asset length (m) x 0.001
   * - ``EUR/m3``
     - value x asset volume (m3), no factor needed

**Fixed operational and fixed maintenance costs:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Unit
     - Conversion
   * - ``EUR``, ``EUR/yr``
     - Used directly as annual cost
   * - ``EUR/MW``
     - value x asset power (W) x 1e-6
   * - ``% OF CAPEX``
     - value x (investment + installation) x 0.01

**Variable operational and variable maintenance costs:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Unit
     - Conversion
   * - ``EUR``, ``EUR/yr``
     - Used directly as annual cost
   * - ``EUR/kWh``
     - value x annual energy (J) x 2.78e-7
   * - ``EUR/MWh``
     - value x annual energy (J) x 2.78e-10

If a cost field uses a unit not listed above, the cost is ignored and a WARNING is logged with the asset name and the unsupported unit string. Check the log output when cost KPIs seem unexpectedly low.
