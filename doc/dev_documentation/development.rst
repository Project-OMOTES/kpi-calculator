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

Pre-commit Hooks
----------------

The project uses `pre-commit <https://pre-commit.com/>`_ to run checks automatically on every
commit. Install the hooks once after cloning:

.. code-block:: bash

   uv run pre-commit install

The hooks configured in ``.pre-commit-config.yaml`` run on every ``git commit``:

- **ruff** — linting with auto-fixes and formatting
- **mypy** — static type checking on ``src/kpicalculator/``
- **pre-commit-hooks** — trailing whitespace, YAML/TOML validity, merge conflict markers, debug statements
- **pytest** — full test suite

If a hook fails, the commit is aborted. Fix the reported issues and commit again. To run hooks
manually without committing:

.. code-block:: bash

   uv run pre-commit run --all-files

Code Quality
------------

To run linting, formatting, or type checking independently (e.g., on specific files or
without committing):

.. code-block:: bash

   uv run ruff check --fix src/ unit_test/
   uv run ruff format src/ unit_test/
   uv run mypy src/kpicalculator

The project uses `Ruff <https://docs.astral.sh/ruff/>`_ for both linting and formatting, and mypy for static type checking. All three checks are enforced in CI on every push and pull request.

Testing
-------

.. code-block:: bash

   uv run pytest unit_test/

With coverage:

.. code-block:: bash

   uv run pytest --cov=src/kpicalculator --cov-report term-missing --cov-fail-under 80 unit_test/

The minimum coverage threshold is configured via ``--cov-fail-under`` in ``pyproject.toml`` and enforced in CI. Test data lives in ``unit_test/data/`` and includes ESDL files and XML time series.

Full Validation Pipeline
^^^^^^^^^^^^^^^^^^^^^^^^

Run all checks in one command before opening a pull request:

.. code-block:: bash

   uv run ruff check --fix src/ unit_test/ && uv run ruff format src/ unit_test/ && uv run mypy src/kpicalculator && uv run pytest --cov=src/kpicalculator --cov-report term-missing --cov-fail-under 80 unit_test/ -q

Building Documentation
----------------------

Documentation dependencies are declared in the ``docs`` group in ``pyproject.toml`` and are
included when you run ``uv sync --all-extras``. To build the HTML docs locally:

.. code-block:: bash

   uv run sphinx-build doc doc/_build/html

Then open ``doc/_build/html/index.html`` in a browser.

``doc/requirements.txt`` is kept alongside for ReadTheDocs, which uses pip internally and reads
the file during its CI build. Keep both files in sync when adding Sphinx extensions.

CI/CD
-----

The GitHub Actions workflow (``.github/workflows/ci.yml``) runs the full validation pipeline on every push and pull request. Releases are published to PyPI automatically when a GitHub Release is created from a version tag.

Security scanning (``uv run bandit -r src/``) is also part of the CI pipeline. The ``security/`` package handles input validation (path traversal prevention) and credential management (environment variables for InfluxDB). See ``input_validator.py`` and ``credential_manager.py``.
