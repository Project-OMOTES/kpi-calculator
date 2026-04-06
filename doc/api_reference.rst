API Reference
=============

This page documents the public API of the KPI Calculator. For usage examples, see
:doc:`getting_started`. For architecture details, see
:doc:`dev_documentation/architecture`.

Public API
----------

.. automodule:: kpicalculator
   :noindex:

.. autofunction:: kpicalculator.calculate_kpis

.. autoclass:: kpicalculator.KpiManager
   :members:

Calculators
-----------

.. automodule:: kpicalculator.calculators.financial_calculator
   :members:

.. automodule:: kpicalculator.calculators.energy_calculator
   :members:

.. automodule:: kpicalculator.calculators.emission_calculator
   :members:

Common Model
------------

.. automodule:: kpicalculator.adapters.common_model
   :noindex:

.. autoclass:: kpicalculator.adapters.common_model.Asset
   :members:

.. autoclass:: kpicalculator.adapters.common_model.EnergySystem
   :members:

.. autoclass:: kpicalculator.adapters.common_model.TimeSeries
   :members:

Adapters
--------

.. automodule:: kpicalculator.adapters.esdl_adapter
   :members:

.. automodule:: kpicalculator.adapters.time_series_manager
   :members:

Reporting
---------

.. automodule:: kpicalculator.reporting.esdl_kpi_exporter
   :members:

Exceptions
----------

.. automodule:: kpicalculator.exceptions
   :members:
