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

- **ruff** — linting with auto-fixes, then a strict pass to catch unfixable violations
- **ruff-format** — code formatting
- **mypy** — static type checking on ``src/kpicalculator/``
- **pre-commit-hooks** — trailing whitespace, YAML/TOML validity, merge conflict markers, debug statements
- **pytest** — full test suite

If a hook fails, the commit is aborted. Fix the reported issues and commit again. To run hooks
manually without committing:

.. code-block:: bash

   uv run pre-commit run --all-files

Code Quality
------------

To run linting, formatting, or type checking independently:

.. code-block:: bash

   uv run ruff check src/ unit_test/          # lint (matches CI)
   uv run ruff check --fix src/ unit_test/    # lint with auto-fix
   uv run ruff format src/ unit_test/         # format
   uv run mypy src/kpicalculator              # type check

The project uses `Ruff <https://docs.astral.sh/ruff/>`_ for both linting and formatting, and mypy for static type checking. All three checks are enforced in CI on every push and pull request.

``uv run check.py`` is a shorthand for ``uv run pre-commit run --all-files``, which runs the
full hook suite (ruff, mypy, pytest, and file checks) in one command. Run this before opening
a pull request.

Pass ``--full`` to also run pylint code analysis (duplicate code, complexity, too-many-locals)
after the pre-commit suite:

.. code-block:: bash

   uv run check.py --full

Testing
-------

.. code-block:: bash

   uv run pytest unit_test/

With coverage:

.. code-block:: bash

   uv run pytest --cov=src/kpicalculator --cov-report term-missing --cov-fail-under 80 unit_test/

The minimum coverage threshold is configured via ``--cov-fail-under`` in ``pyproject.toml`` and enforced in CI. Test data lives in ``unit_test/data/`` and includes ESDL files and XML time series.

Building Documentation
----------------------

Documentation dependencies are declared in the ``docs`` group in ``pyproject.toml`` and are
included when you run ``uv sync --all-extras``. To build the HTML docs locally:

.. code-block:: bash

   uv run sphinx-build doc doc/_build/html

Then open ``doc/_build/html/index.html`` in a browser.

Documentation dependencies are declared in the ``docs`` optional dependency group in
``pyproject.toml``. ReadTheDocs installs them via ``.readthedocs.yaml``
(``extra_requirements: docs``). When adding a Sphinx extension, add it there.

Analysis Tools
--------------

The ``analysis`` dependency group (installed with ``uv sync --all-extras``) provides tools for
deeper code investigation that are not part of the standard pre-commit or CI pipeline.

**Duplicate code and complexity analysis** with `Pylint <https://pylint.readthedocs.io/>`_:

.. code-block:: bash

   uv run check.py --full

Runs pylint with duplicate code detection, too-many-branches, too-many-statements, and
too-many-locals checks. Use this before major refactors or releases to surface extraction
opportunities. Findings require human judgement — not every finding warrants a change.

**Cyclomatic complexity** with `Radon <https://radon.readthedocs.io/>`_:

.. code-block:: bash

   uv run radon cc src/ --min C --show-complexity

Reports functions rated C or above. Use when a function feels hard to test or understand.
Ruff's C901 rule (max-complexity=12) is the enforced gate; radon is a supplementary view.

**Dead code detection** with `Vulture <https://github.com/jendrikseipp/vulture>`_:

.. code-block:: bash

   uv run vulture src/kpicalculator/

Vulture reports attributes, functions, and classes that appear to have no callers. Has a high
false-positive rate for this codebase (Pydantic validators, public API methods) — review
findings carefully before acting on them.

**Dependency vulnerability scanning** with `pip-audit <https://pypi.org/project/pip-audit/>`_:

.. code-block:: bash

   uv run pip-audit --skip-editable

The ``--skip-editable`` flag excludes the local ``kpi-calculator`` package itself from the audit
(it is not on PyPI and cannot be looked up). ``pip-audit`` checks all installed dependencies
against the `OSV <https://osv.dev/>`_ vulnerability database and reports CVEs with fix versions.
Run this periodically or before a release to confirm no production dependencies carry known
vulnerabilities.

CI/CD
-----

The GitHub Actions workflow (``.github/workflows/ci.yml``) runs the full validation pipeline on every push and pull request. Releases are published to PyPI automatically when a GitHub Release is created from a version tag.

Security scanning (``uv run bandit -r src/``) is also part of the CI pipeline. The ``security/`` package handles input validation (path traversal prevention) and credential management (environment variables for InfluxDB). See ``input_validator.py`` and ``credential_manager.py``.
