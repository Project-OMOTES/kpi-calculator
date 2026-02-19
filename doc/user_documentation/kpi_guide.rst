KPI Guide
=========

The KPI Calculator extracts cost data and time series from an ESDL energy system model and returns standardized cost, energy, and emission metrics. This guide explains what each metric means and how to interpret it for energy system design decisions.

For installation and usage instructions, see :doc:`../getting_started`. For time series keys, asset categories, and cost unit formats, see :doc:`kpi_reference`.

KPI Summary
-----------

.. list-table::
   :header-rows: 1
   :widths: 20 15 15 50

   * - KPI
     - Unit
     - Typical Range
     - Purpose
   * - CAPEX
     - EUR
     - Project-specific
     - Budget planning
   * - OPEX
     - EUR/year
     - €15-60/MWh
     - Operating budget
   * - NPV
     - EUR
     - Lower is better
     - Lifecycle cost comparison
   * - LCOE
     - EUR/MWh
     - €30-80
     - Cost-effectiveness ranking
   * - Consumption
     - Joules
     - Demand-driven
     - Demand verification
   * - Production
     - Joules
     - 1.05-1.15 × consumption
     - System sizing check
   * - Efficiency
     - 0-1
     - 0.80-0.95
     - Distribution quality
   * - Demand
     - Joules
     - Demand-driven
     - Energy need verification
   * - Total Emissions
     - t CO2e/yr
     - <2t/household/yr target
     - Climate compliance
   * - Emissions Intensity
     - kg CO2e/MWh
     - <100 target
     - Environmental comparison

Cost breakdowns use the categories **Production**, **Consumption**, **Storage**, **Transport**, **Conversion**, and **All**. For the full return structure and example values, see the :ref:`results-structure` section in the Getting Started guide.

Cost KPIs
---------

CAPEX (Capital Expenditure)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Total upfront investment to build the system, in EUR.

.. code-block:: text

   CAPEX = Sum of (investment_cost + installation_cost) for all assets

CAPEX is broken down by asset category. In a typical district heating system, transport (pipes) accounts for 40-60% and production equipment for 20-40%. If a single category dominates (>70%), the design may be over-specified in that area.

Higher CAPEX isn't necessarily bad — it often comes with lower operating costs. Use LCOE and NPV to see the full picture.

OPEX (Operating Expenditure)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Annual costs to run and maintain the system, in EUR/year. Includes maintenance, fuel, and electricity.

.. code-block:: text

   OPEX = Sum of (fixed_costs + variable_costs) per year

To compare systems of different sizes, normalize by energy delivered:

- Gas systems: typically €30-60 per MWh
- Heat pumps: €20-40 per MWh
- District heating: €15-30 per MWh

NPV (Net Present Value)
^^^^^^^^^^^^^^^^^^^^^^^^

Total lifecycle cost in today's money, accounting for the time value of future expenses.

.. code-block:: text

   r = discount_rate / 100

   CAPEX_npv = Sum over assets of:
       (investment + installation) × Sum over replacements n=0,1,...:
           1 / (1 + r) ^ (technical_lifetime × n)

   OPEX_npv = Sum over assets of:
       annual_opex × Sum over years t=0..system_lifetime-1:
           1 / (1 + r) ^ t

   NPV = CAPEX_npv + OPEX_npv

When an asset's technical lifetime is shorter than the system lifetime, the CAPEX term includes replacement costs — each replacement is discounted to its installation year. For example, an asset with a 15-year technical lifetime in a 30-year analysis has two replacement events, each discounted further into the future.

Defaults: 30-year system lifetime, 5% discount rate.

NPV captures the full cost picture: a system with high CAPEX but low OPEX can have a lower (better) NPV than a cheap-to-build system with expensive fuel costs. When comparing designs, lower NPV means lower total cost. If two designs have NPV within €50k of each other, the result is sensitive to assumptions — try varying the system lifetime to check.

LCOE (Levelized Cost of Energy)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Average cost per MWh of energy delivered over the system lifetime, in EUR/MWh. Energy delivered is discounted using the same discount rate and lifetime as for NPV, so costs and energy are on a consistent present-value basis. This is the most useful metric for comparing designs of different sizes and technologies.

.. code-block:: text

   r = discount_rate / 100

   Discounted_Energy = Sum over years t=0..system_lifetime-1:
       annual_energy_MWh / (1 + r) ^ t

   LCOE [EUR/MWh] = NPV [EUR] / Discounted_Energy [MWh]

Typical benchmarks:

- Natural gas boiler: €40-60/MWh
- Heat pump: €50-80/MWh
- District heating: €30-50/MWh

Lower LCOE means more cost-effective, but the cheapest option may not meet emission targets.

Energy KPIs
-----------

Consumption and Production
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Total thermal energy consumed and produced, in Joules.

In a well-designed system, production should exceed consumption by 5-15% to account for distribution losses. If production is more than 15% above consumption, the system is likely oversized. If production barely exceeds or is below consumption, producers may be missing from the ESDL model.

Demand
^^^^^^

Total energy demand from all consumers in the system, in Joules. Demand represents what end users need, while consumption represents what the system actually delivers. In a well-calibrated model, demand and consumption should be close. A large gap between the two may indicate that some consumers are not being served or that the model's demand profiles need adjustment.

Efficiency
^^^^^^^^^^

Ratio of energy consumed to energy produced (0 to 1):

.. code-block:: text

   Efficiency = Consumption / Production

Typical values range from 0.80-0.95 for district heating — higher for compact urban networks, lower for long-distance systems. An efficiency above 0.98 is suspiciously high and usually means distribution losses are not being captured.

Without time series data, both consumption and production are zero, making efficiency undefined (returned as 0.0). Time series data is required for meaningful efficiency values.

Emission KPIs
-------------

Total CO2 Emissions
^^^^^^^^^^^^^^^^^^^

Total greenhouse gas emissions from system operation, in tonnes CO2e per year.

.. code-block:: text

   For each asset:
     energy [J]          = sum(time_series_values) × time_step [s]
     annual_energy [J]   = energy × (seconds_per_year / duration)
     emissions [kg CO2e] = emission_factor [kg CO2e/J] × annual_energy [J]

   Total_Emissions [t CO2e/yr] = Sum of asset emissions [kg] / 1000 [kg/t]

Emission factors are read from the ESDL carrier definitions in **kg CO2e/GJ** (the standard ESDL unit) and converted to kg CO2e/J during loading. The calculator multiplies directly by energy in Joules and emissions from kg to tonnes internally. Emission factors cover upstream emissions (fuel extraction and processing). Benchmarks for 100 households:

- Gas heating: 80-120 t CO2e/year
- Heat pump on grid electricity: 20-40 t CO2e/year
- Heat pump on renewable electricity: 5-10 t CO2e/year

The EU 2030 target is below 2 t CO2e per household annually.

Emissions Intensity
^^^^^^^^^^^^^^^^^^^

Emissions per unit of energy consumed, in kg CO2e/MWh. The denominator is total annual energy consumption (the same value reported in the energy KPIs), converted from Joules to MWh.

.. code-block:: text

   Emissions_Intensity [kg CO2e/MWh] = (Total_Emissions [t CO2e] × 1000) / Total_Energy_Consumption [MWh]

Common values:

- Gas boiler: 200-250
- Heat pump (EU grid): 100-150
- Heat pump (renewable): 10-30

The EU 2030 target for heating is below 100 kg CO2e/MWh. Use this metric to compare the environmental performance of different designs.

Comparing Designs
-----------------

Here's an example of how KPIs can inform a design decision:

.. list-table::
   :header-rows: 1

   * - Metric
     - Gas Boiler
     - Heat Pump
     - District Heating
   * - CAPEX
     - €400k
     - €550k
     - €850k
   * - OPEX/year
     - €35k
     - €25k
     - €20k
   * - NPV (30yr)
     - €1.05M
     - €750k
     - €600k
   * - LCOE
     - €52/MWh
     - €48/MWh
     - €35/MWh
   * - Emissions
     - 120 t/yr
     - 35 t/yr
     - 25 t/yr

The gas boiler is cheapest to build but most expensive over its lifetime. District heating requires the largest upfront investment but has the lowest lifecycle cost and emissions. The heat pump sits in between on every metric.

Which option is "best" depends on priorities: budget constraints, long-term cost targets, or climate compliance requirements.

Key Assumptions
---------------

These defaults affect all calculations. Understanding them helps interpret results and compare scenarios.

**System lifetime:** 30 years. Standard for energy infrastructure. Override with ``system_lifetime=25`` in ``calculate_kpis()``.

**Discount rate:** 5%. Represents the cost of capital for energy infrastructure. Not currently overridable through the public API.

**Technical lifetime per asset:** 40 years if not specified in ESDL. Real values vary widely — pipes last 40-50 years, heat pumps 15-20.

Limitations
-----------

**Time series required:** Energy and emission KPIs depend entirely on time series data. Without it, consumption, production, and demand are returned as zero — there is no rated-capacity fallback. For details on how to provide time series data, see :doc:`../getting_started`.

**Efficiency approximation:** The efficiency calculation (Consumption / Production) does not account for pump losses, control system energy, or heat exchanger fouling. Real systems are typically 2-5% less efficient than calculated.

**Static emission factors:** Emission factors are constant over the analysis period — they don't account for grid decarbonization over time. They also exclude embodied carbon in equipment manufacturing and installation.

**System-level results only:** All KPIs are system-wide aggregates. Asset-level and area-level breakdowns are not currently implemented.
