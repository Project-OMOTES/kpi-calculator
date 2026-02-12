Development
===========

Setup, tooling, and workflow for developing the KPI Calculator.

Setup
-----

.. code-block:: bash

   git clone https://github.com/Project-OMOTES/kpi-calculator.git
   cd kpi-calculator
   pip install uv
   uv sync --all-extras

This installs all runtime and development dependencies using `UV <https://docs.astral.sh/uv/>`_.

Running Tests
-------------

.. code-block:: bash

   uv run pytest unit_test/

With coverage:

.. code-block:: bash

   uv run pytest --cov=src/kpicalculator --cov-report term-missing --cov-fail-under 80 unit_test/

The minimum coverage threshold is configured via ``--cov-fail-under`` in ``pyproject.toml`` and enforced in CI.

Test data lives in ``unit_test/data/`` and includes ESDL files, XML time series, and CSV files for unit conversion.

Linting and Formatting
----------------------

The project uses `Ruff <https://docs.astral.sh/ruff/>`_ for both linting and formatting:

.. code-block:: bash

   uv run ruff check --fix src/ unit_test/
   uv run ruff format src/ unit_test/

Type Checking
-------------

.. code-block:: bash

   uv run mypy src/kpicalculator

Full Validation
---------------

Run all checks before committing:

.. code-block:: bash

   uv run ruff check --fix src/ unit_test/ && uv run ruff format src/ unit_test/ && uv run mypy src/kpicalculator && uv run pytest --cov=src/kpicalculator --cov-report term-missing --cov-fail-under 80 unit_test/ -q

CI/CD
-----

The GitHub Actions workflow (``.github/workflows/ci.yml``) runs the full validation pipeline on every push and pull request. Releases are published to PyPI automatically when a GitHub Release is created from a version tag.

Security Scanning
-----------------

.. code-block:: bash

   uv run bandit -r src/

The ``security/`` package handles input validation (path traversal prevention) and credential management (environment variables for InfluxDB). See ``input_validator.py`` and ``credential_manager.py``.
