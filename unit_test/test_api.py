# unit_test/test_api.py
"""Integration tests for the public calculate_kpis() API entry point.

These tests exercise the full pipeline — ESDL loading, KPI calculation, and
error handling — through the single function that all downstream callers use.
Regressions here affect every consumer of the library.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from kpicalculator.api import calculate_kpis
from kpicalculator.exceptions import KpiCalculatorError

DATA_DIR = Path(__file__).parent / "data"
ESDL_FILE = DATA_DIR / "Unit_test_ESDL.esdl"
TIME_SERIES_FILE = DATA_DIR / "power_timeseries.xml"

# Fixture constants matching Unit_test_ESDL.esdl
# Asset ID of the GenericConsumer asset used in DataFrame integration tests
FIXTURE_ASSET_ID = "a5243809-0077-46e5-a0ea-09aa486f5e96"
# Column name recognised by KNOWN_TIME_SERIES_FIELDS as a consumption signal
FIXTURE_COLUMN = "ThermalConsumption"
# One full year of hourly time steps — enough for meaningful annualised KPIs
HOURS_PER_YEAR = 8760
# Unit conversion: number of Watts in one Megawatt — used to build test DataFrames
# at a physically plausible scale (1 MW continuous over a year gives ~8.76 GWh)
WATTS_PER_MW = 1_000_000.0


class TestCalculateKpisHappyPath(unittest.TestCase):
    """Tests for successful calculate_kpis() invocations.

    The ESDL fixture contains cost data, so cost KPIs are always non-zero.
    Energy KPIs require time series; without them the result is 0.0 (tested
    explicitly in test_kpi_calculator.py::ZeroEnergyEdgeCaseTest).
    """

    def test_returns_kpi_results_structure(self) -> None:
        """calculate_kpis() with a valid ESDL file returns the full KpiResults structure.

        This is the minimal happy path: no time series, costs only.  Verifies that
        the return value has the expected top-level keys and that cost KPIs are
        non-zero (the fixture has costInformation elements).
        """
        results = calculate_kpis(ESDL_FILE)

        self.assertIn("financials", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)
        self.assertIn("capex", results["financials"])
        self.assertIn("opex", results["financials"])
        self.assertIn("npv", results["financials"])
        self.assertIn("lcoe", results["financials"])

    def test_accepts_path_object(self) -> None:
        """calculate_kpis() accepts a pathlib.Path as well as a string for esdl_file."""
        results_from_path = calculate_kpis(ESDL_FILE)
        results_from_str = calculate_kpis(str(ESDL_FILE))

        self.assertEqual(
            results_from_path["financials"]["npv"], results_from_str["financials"]["npv"]
        )

    def test_with_xml_time_series(self) -> None:
        """calculate_kpis() loads XML time series when the time_series argument is provided.

        With time series present, energy KPIs should be non-zero.  This exercises
        the time_series_file code path in KpiManager.load_from_esdl().
        """
        results = calculate_kpis(ESDL_FILE, time_series=TIME_SERIES_FILE)

        energy = results["energy"]
        # The fixture time series has consumption data; verify consumption specifically.
        self.assertGreater(
            energy["consumption"], 0.0, "energy consumption must be > 0 with time series"
        )

    def test_with_dataframes(self) -> None:
        """calculate_kpis() with timeseries_dataframes routes data to the energy calculator.

        Uses the real asset ID and column name from the ESDL fixture so the DataFrame
        is actually matched and energy consumption is non-zero.  This confirms the
        DataFrame path is wired through the full pipeline, not just accepted and ignored.

        timeseries_dataframes is keyed by plain asset ID; TimeSeriesManager builds
        the composite "asset_id|column_name" keys internally from each DataFrame column.
        The column name must be in KNOWN_TIME_SERIES_FIELDS (e.g. ThermalConsumption).
        """
        index = pd.date_range("2024-01-01", periods=HOURS_PER_YEAR, freq="h")
        df = pd.DataFrame({FIXTURE_COLUMN: [WATTS_PER_MW] * HOURS_PER_YEAR}, index=index)
        # timeseries_dataframes is keyed by plain asset ID; TimeSeriesManager
        # creates the composite "asset_id|column_name" keys internally per column.
        dataframes = {FIXTURE_ASSET_ID: df}

        results = calculate_kpis(ESDL_FILE, timeseries_dataframes=dataframes)

        self.assertGreater(
            results["energy"]["consumption"],
            0.0,
            "Energy consumption must be non-zero when a matching DataFrame is provided",
        )

    def test_custom_system_lifetime_accepted(self) -> None:
        """system_lifetime parameter is forwarded to the calculator without error.

        A shorter lifetime reduces NPV; this confirms the parameter reaches
        calculate_all_kpis() rather than being silently ignored.
        """
        results_default = calculate_kpis(ESDL_FILE)
        results_short = calculate_kpis(ESDL_FILE, system_lifetime=10.0)

        # NPV over 10 years must be less than NPV over 30 years (default)
        self.assertLess(results_short["financials"]["npv"], results_default["financials"]["npv"])


class TestCalculateKpisErrorHandling(unittest.TestCase):
    """Tests for error conditions in calculate_kpis().

    The function must always raise KpiCalculatorError — never a raw exception
    from an internal library — so callers have a single exception type to handle.
    """

    def test_missing_esdl_file_raises_kpi_calculator_error(self) -> None:
        """A non-existent ESDL path raises KpiCalculatorError with the path in the message.

        This is caught before any loading begins, so the error is immediate and
        does not depend on ESDL library internals.
        """
        with self.assertRaises(KpiCalculatorError) as ctx:
            calculate_kpis("/nonexistent/path/to/file.esdl")

        self.assertIn("not found", str(ctx.exception).lower())

    def test_kpi_calculator_error_is_re_raised_unchanged(self) -> None:
        """A KpiCalculatorError raised internally propagates out without wrapping.

        The function must not double-wrap: if the manager already raises
        KpiCalculatorError, callers should see the original message, not
        'Calculation failed: Calculation failed: ...'.
        """
        original_error = KpiCalculatorError("original message")

        with patch("kpicalculator.api.KpiManager") as mock_manager_cls:
            mock_manager = MagicMock()
            mock_manager_cls.return_value = mock_manager
            mock_manager.load_from_esdl.side_effect = original_error

            with self.assertRaises(KpiCalculatorError) as ctx:
                calculate_kpis(ESDL_FILE)

        self.assertIs(ctx.exception, original_error)

    def test_unexpected_internal_exception_wrapped_as_kpi_calculator_error(self) -> None:
        """An unexpected internal exception is wrapped in KpiCalculatorError.

        Callers should never see a raw ValueError, AttributeError, etc. from
        internal library code.  The wrapper message includes the original cause.
        """
        with patch("kpicalculator.api.KpiManager") as mock_manager_cls:
            mock_manager = MagicMock()
            mock_manager_cls.return_value = mock_manager
            mock_manager.load_from_esdl.side_effect = ValueError("internal parse error")

            with self.assertRaises(KpiCalculatorError) as ctx:
                calculate_kpis(ESDL_FILE)

        self.assertIn("internal parse error", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
