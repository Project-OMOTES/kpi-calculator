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
   * - EAC
     - EUR/year
     - Project-specific
     - Per-asset annualized cost; annual budget comparison across different asset lifetimes
   * - TCO
     - EUR
     - Project-specific
     - Undiscounted lifecycle cost; comparable to MESIDO optimizer output
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
       (investment + installation) × Sum over replacements k=0,1,...,ceil(lifetime/TL)-1:
           1 / (1 + r) ^ (technical_lifetime × k)

   Let N = floor(system_lifetime), f = system_lifetime - N

   OPEX_npv = Sum over assets of:
       annual_opex × (Sum t=1..N of 1/(1+r)^t  +  f/(1+r)^(N+1))

   NPV = CAPEX_npv + OPEX_npv

CAPEX is paid at the start of each replacement cycle (start-of-period). OPEX follows the standard engineering economics end-of-period convention — costs incurred at the end of each year are discounted accordingly. A fractional final year is prorated linearly.

When an asset's technical lifetime is shorter than the system lifetime, the CAPEX term includes replacement costs — each replacement is discounted to its installation year. For example, an asset with a 15-year technical lifetime in a 30-year analysis has two replacement events, each discounted further into the future.

Defaults: 30-year system lifetime, 5% discount rate.

NPV captures the full cost picture: a system with high CAPEX but low OPEX can have a lower (better) NPV than a cheap-to-build system with expensive fuel costs. When comparing designs, lower NPV means lower total cost. If two designs have NPV within €50k of each other, the result is sensitive to assumptions — try varying the system lifetime to check.

LCOE (Levelized Cost of Energy)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Average cost per MWh of energy delivered over the system lifetime, in EUR/MWh. Energy is discounted using the same end-of-period convention and parameters as NPV OPEX, so costs and energy are on a consistent present-value basis. This is the most useful metric for comparing designs of different sizes and technologies.

.. code-block:: text

   r = discount_rate / 100

   Let N = floor(system_lifetime), f = system_lifetime - N

   Discounted_Energy = Sum t=1..N of annual_energy_MWh/(1+r)^t  +  f×annual_energy_MWh/(1+r)^(N+1)

   LCOE [EUR/MWh] = NPV [EUR] / Discounted_Energy [MWh]

Typical benchmarks:

- Natural gas boiler: €40-60/MWh
- Heat pump: €50-80/MWh
- District heating: €30-50/MWh

Lower LCOE means more cost-effective, but the cheapest option may not meet emission targets.

EAC (Equivalent Annual Cost)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sum of per-asset annualized costs, in EUR/year. Each asset's CAPEX is spread over its
own technical lifetime using the annuity formula; OPEX is already annual and is added
directly.

.. code-block:: text

   For each asset:
       r   = asset discount_rate / 100  (from ESDL, or system default)
       TL  = asset technical_lifetime

       annualized_CAPEX = (investment + installation) × r / (1 - (1 + r) ^ -TL)

       Special case (r = 0):
       annualized_CAPEX = (investment + installation) / TL

       annualized_OPEX = annual_opex  (fixed + variable operational + maintenance)

   EAC = Sum over assets of (annualized_CAPEX + annualized_OPEX)

The annuity formula is identical to ``calculate_annuity_factor`` in the MESIDO
optimizer (``financial_mixin.py``).

**Replacement assumption:** the annuity spreads one asset purchase over its technical
lifetime, implicitly assuming the asset is always replaced when it reaches end of life.
The annual charge is therefore the same regardless of how many replacements occur within
the system lifetime — a pipe with a 40-year lifetime and a heat pump with a 15-year
lifetime each carry their own constant annual charge. This avoids the need to count
replacement cycles explicitly and makes EAC independent of ``system_lifetime``.

The implication is that EAC does not account for salvage value at the end of the system
lifetime. If an asset is replaced partway through the final cycle, the unused residual
life is not credited. For long system lifetimes relative to asset lifetimes this effect
is small; for short system lifetimes it may be material.

Use EAC when you need to answer: *"What does this system cost per year, on average?"*
It is particularly useful when comparing designs with assets of different technical
lifetimes — NPV alone can be misleading because a longer-lived system accumulates more
discounted cost even if it is cheaper per year.

TCO (Total Cost of Ownership)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Undiscounted sum of all costs over the system lifetime, in EUR. Unlike NPV, future costs are not discounted to present value — each euro spent in year 25 counts the same as a euro spent today.

.. code-block:: text

   For each asset:
       replacement_factor = ceil(system_lifetime / technical_lifetime)
       CAPEX_tco = (investment + installation) × replacement_factor
       OPEX_tco  = annual_opex × system_lifetime

   TCO = Sum over all assets of (CAPEX_tco + OPEX_tco)

The replacement factor counts the number of full asset purchases needed to keep the system operational over its lifetime (e.g. 2 for a 30-year system with a 15-year asset). This is the financially exact count and is consistent with the CAPEX replacement logic in NPV.

Pass ``round_up_replacement=False`` to ``FinancialCalculator.calculate_tco()`` to use the continuous factor ``max(1, system_lifetime / technical_lifetime)`` instead. MESIDO's ``MinimizeTCO`` goal uses this approximation to keep the optimizer objective smooth and differentiable. Use this only when comparing output against MESIDO results.

TCO is always greater than or equal to NPV at any positive discount rate — discounting makes future costs smaller, so the undiscounted sum is always higher. Use TCO when you want to verify optimizer results from MESIDO, or when comparing total expenditure without assuming a particular cost of capital.

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
   * - EAC (30yr, 5%)
     - €68k/yr
     - €49k/yr
     - €39k/yr
   * - TCO (30yr)
     - €1.45M
     - €1.30M
     - €1.45M
   * - LCOE
     - €52/MWh
     - €48/MWh
     - €35/MWh
   * - Emissions
     - 120 t/yr
     - 35 t/yr
     - 25 t/yr

The gas boiler is cheapest to build but most expensive over its lifetime. District heating requires the largest upfront investment but has the lowest lifecycle cost and emissions. The heat pump sits in between on every metric.

EAC makes the annual budget impact explicit: district heating costs €39k/year on average, versus €68k for gas. TCO shows the undiscounted total spend — useful for verifying against MESIDO optimizer output.

Which option is "best" depends on priorities: budget constraints, long-term cost targets, or climate compliance requirements.

Key Assumptions
---------------

These defaults affect all calculations. Understanding them helps interpret results and compare scenarios.

**System lifetime:** 30 years. Standard for energy infrastructure. Override with ``system_lifetime=25`` in ``calculate_all_kpis()``.

**Discount rate:** 5%. Represents the cost of capital for energy infrastructure. Override with ``discount_rate=3`` in ``calculate_all_kpis()``.

**Technical lifetime per asset:** 40 years if not specified in ESDL. Real values vary widely — pipes last 40-50 years, heat pumps 15-20.

Limitations
-----------

**Time series required:** Energy and emission KPIs depend entirely on time series data. Without it, consumption, production, and demand are returned as zero — there is no rated-capacity fallback. Missing or unrecognised time series keys are logged at DEBUG level; invalid time series (non-positive duration) are logged at WARNING level. For details on how to provide time series data, see :doc:`../getting_started`.

**Efficiency approximation:** The efficiency calculation (Consumption / Production) does not account for pump losses, control system energy, or heat exchanger fouling. Real systems are typically 2-5% less efficient than calculated.

**Static emission factors:** Emission factors are constant over the analysis period — they don't account for grid decarbonization over time. They also exclude embodied carbon in equipment manufacturing and installation.

**System-level results only:** All KPIs are system-wide aggregates. Asset-level and area-level breakdowns are not currently implemented.
