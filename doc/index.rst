KPI Calculator Documentation
============================

.. TODO: Register the project on ReadTheDocs (https://readthedocs.org/) and update the
   documentation URL in pyproject.toml from the placeholder to the live URL once the
   RTD project is created and the webhook is configured on the GitHub repository.

The KPI Calculator computes cost, energy, and emission key performance indicators from
`ESDL <https://energytransition.github.io/>`_ energy system models. Given an ESDL file and
optional time series data, it returns standardized metrics — CAPEX, OPEX, NPV, LCOE,
consumption, production, efficiency, CO2 emissions — that support design decisions in the
`OMOTES <https://github.com/Project-OMOTES>`_ energy system design toolkit.

Everyone should start with the :doc:`Getting Started <getting_started>` guide — installation,
usage examples, and results format.

**Then, depending on your role:**

- **Energy system designers and analysts** interpreting results: continue with the
  :doc:`KPI Guide <user_documentation/kpi_guide>`.
- **Software developers** integrating the calculator into a pipeline or contributing to the
  codebase: see :doc:`Architecture <dev_documentation/architecture>` and
  :doc:`Development <dev_documentation/development>`.
- **API users** looking up function signatures and return types: see the
  :doc:`API Reference <api_reference>`.

**Links:**

- `PyPI <https://pypi.org/project/kpi-calculator/>`_ — install with ``pip install kpi-calculator``
- `GitHub <https://github.com/Project-OMOTES/kpi-calculator>`_ — source code, issues, and pull requests
- `Releases <https://github.com/Project-OMOTES/kpi-calculator/releases>`_ — changelog and version history

.. toctree::
   :hidden:

   getting_started

.. toctree::
   :hidden:
   :caption: User Guide

   user_documentation/kpi_guide
   user_documentation/kpi_reference

.. toctree::
   :hidden:
   :caption: Developer Guide

   dev_documentation/architecture
   dev_documentation/development

.. toctree::
   :hidden:
   :caption: Reference

   api_reference
   indices
