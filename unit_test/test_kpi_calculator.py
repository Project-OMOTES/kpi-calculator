import math
import sys
import unittest
from pathlib import Path

import pandas as pd

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from kpicalculator import KpiManager  # noqa: E402


class NewKpiCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        # Create KPI manager
        self.kpi_manager = KpiManager()

        # Load ESDL data (CSV costs not provided since ESDL has complete cost information)
        esdl = DATA_DIR / "Unit_test_ESDL.esdl"
        series = DATA_DIR / "power_timeseries.xml"

        self.kpi_manager.load_from_esdl(str(esdl), time_series_file=str(series))

    def test_calculate_all_kpis(self) -> None:
        # Calculate KPIs
        results = self.kpi_manager.calculate_all_kpis(system_lifetime=40)

        # Check that results contain expected keys
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)

        # Check specific values (using ESDL costInformation only)
        self.assertAlmostEqual(
            results["costs"]["capex"]["All"], 107900.03, places=2, msg="Total CAPEX is incorrect"
        )

        self.assertAlmostEqual(
            results["energy"]["consumption"],
            473040000000.0,
            places=0,
            msg="Energy consumption is incorrect",
        )

        self.assertAlmostEqual(
            results["emissions"]["total"], 21.665232, places=3, msg="Total emissions are incorrect"
        )


class EsdlStringLoadingTest(unittest.TestCase):
    """Tests for loading ESDL from string content instead of file path."""

    def test_load_from_esdl_string_empty_raises_error(self) -> None:
        """Test that empty ESDL string raises ValidationError."""
        from kpicalculator.exceptions import ValidationError

        kpi_manager = KpiManager()

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("")

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("   ")

    def test_load_from_esdl_string_invalid_raises_error(self) -> None:
        """Test that invalid ESDL string raises ValidationError."""
        from kpicalculator.exceptions import ValidationError

        kpi_manager = KpiManager()

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("not valid xml")

    def test_load_from_esdl_string_uses_esdl_name(self) -> None:
        """Test that model name is derived from ESDL name attribute."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        esdl_string = esdl_file.read_text(encoding="utf-8")

        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl_string(esdl_string)

        # The test ESDL has name="KPI_calc_test_model"
        self.assertEqual(kpi_manager.energy_system.name, "KPI_calc_test_model")

    def test_load_from_esdl_string_fallback_name(self) -> None:
        """Test that model name falls back to default when ESDL has no name."""
        # Minimal valid ESDL without a name attribute
        esdl_no_name = """<?xml version='1.0' encoding='UTF-8'?>
        <esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl" id="test-id">
            <instance id="instance-1">
                <area id="area-1"/>
            </instance>
        </esdl:EnergySystem>"""

        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl_string(esdl_no_name)

        self.assertEqual(kpi_manager.energy_system.name, "esdl_from_string")

    def test_load_from_esdl_string_matches_file_loading(self) -> None:
        """Test that string loading produces identical KPI results to file loading."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"

        # Load from file
        file_manager = KpiManager()
        file_manager.load_from_esdl(str(esdl_file))
        file_results = file_manager.calculate_all_kpis(system_lifetime=40)

        # Load from string
        esdl_string = esdl_file.read_text(encoding="utf-8")
        string_manager = KpiManager()
        string_manager.load_from_esdl_string(esdl_string)

        # Verify string loading sets correct state
        self.assertIsNotNone(string_manager.energy_system)
        self.assertIsNone(string_manager.source_esdl_file)

        # Compare KPI results - should be identical
        string_results = string_manager.calculate_all_kpis(system_lifetime=40)
        self.assertAlmostEqual(
            file_results["costs"]["capex"]["All"],
            string_results["costs"]["capex"]["All"],
            places=2,
            msg="CAPEX mismatch between file and string loading",
        )
        self.assertEqual(
            file_results["energy"]["consumption"],
            string_results["energy"]["consumption"],
            msg="Energy consumption mismatch between file and string loading",
        )
        self.assertAlmostEqual(
            file_results["emissions"]["total"],
            string_results["emissions"]["total"],
            places=6,
            msg="Emissions mismatch between file and string loading",
        )


class DataFrameTimeSeriesTest(unittest.TestCase):
    """Test DataFrame time series loading via timeseries_dataframes parameter."""

    TIMESTEPS = 24

    def setUp(self) -> None:
        self.esdl_file = str(DATA_DIR / "Unit_test_ESDL.esdl")
        # Asset ID from the test ESDL fixture (GenericConsumer)
        self.asset_id = "a5243809-0077-46e5-a0ea-09aa486f5e96"

    def _make_dataframe(self, columns: dict) -> pd.DataFrame:
        index = pd.date_range("2019-01-01T00:00:00", periods=self.TIMESTEPS, freq="h")
        return pd.DataFrame(columns, index=index)

    def test_dataframe_composite_keys_reach_energy_calculator(self) -> None:
        """Test that DataFrame columns are mapped to composite keys and reach the calculator."""
        from kpicalculator.common.constants import SECONDS_PER_YEAR

        power_w = 100_000.0
        time_step_s = 3600.0
        # Annual energy = sum(values) * time_step * (SECONDS_PER_YEAR / total_duration)
        expected_j = (
            power_w
            * self.TIMESTEPS
            * time_step_s
            * (SECONDS_PER_YEAR / (time_step_s * self.TIMESTEPS))
        )

        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            self.esdl_file,
            timeseries_dataframes={
                self.asset_id: self._make_dataframe(
                    {"ThermalConsumption": [power_w] * self.TIMESTEPS}
                )
            },
        )
        results = kpi_manager.calculate_all_kpis()

        self.assertTrue(
            math.isclose(results["energy"]["consumption"], expected_j, rel_tol=1e-9),
            msg=f"Expected {expected_j} J, got {results['energy']['consumption']} J",
        )

    def test_multiple_dataframe_columns_produce_independent_time_series(self) -> None:
        """Test that each DataFrame column becomes a separate composite-keyed time series."""
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            self.esdl_file,
            timeseries_dataframes={
                self.asset_id: self._make_dataframe(
                    {
                        "ThermalConsumption": [100_000.0] * self.TIMESTEPS,
                        "ThermalDemand": [80_000.0] * self.TIMESTEPS,
                    }
                )
            },
        )
        asset = next(a for a in kpi_manager.energy_system.assets if a.id == self.asset_id)
        self.assertIn("ThermalConsumption", asset.time_series)
        self.assertIn("ThermalDemand", asset.time_series)
        self.assertEqual(
            asset.time_series["ThermalConsumption"].values, [100_000.0] * self.TIMESTEPS
        )
        self.assertEqual(asset.time_series["ThermalDemand"].values, [80_000.0] * self.TIMESTEPS)

    def test_unknown_column_name_does_not_crash(self) -> None:
        """Test that unrecognised column names are stored but don't crash the calculator."""
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            self.esdl_file,
            timeseries_dataframes={
                self.asset_id: self._make_dataframe({"unknown_field": [1.0] * self.TIMESTEPS})
            },
        )
        results = kpi_manager.calculate_all_kpis()
        self.assertEqual(
            results["energy"]["consumption"],
            0.0,
            msg="Unrecognised column names must not contribute to energy consumption",
        )

    def test_non_numeric_column_is_skipped(self) -> None:
        """Test that non-numeric DataFrame columns are skipped with a validation issue."""
        from esdl.esdl_handler import EnergySystemHandler

        from kpicalculator.adapters.time_series_manager import TimeSeriesManager
        from kpicalculator.common.constants import COMPOSITE_KEY_SEPARATOR

        handler = EnergySystemHandler()
        energy_system = handler.load_file(self.esdl_file)

        df = self._make_dataframe({"ThermalConsumption": ["a", "b"] * (self.TIMESTEPS // 2)})
        expected_dtype = df["ThermalConsumption"].dtype
        expected_error = (
            f"Column 'ThermalConsumption' for asset {self.asset_id} has non-numeric "
            f"dtype '{expected_dtype}' - skipping"
        )

        manager = TimeSeriesManager()
        time_series_dict, validation = manager.load_time_series(
            energy_system, timeseries_dataframes={self.asset_id: df}
        )

        self.assertFalse(
            any(
                k.endswith(f"{COMPOSITE_KEY_SEPARATOR}ThermalConsumption") for k in time_series_dict
            ),
            "Non-numeric column must not be stored as a TimeSeries",
        )
        self.assertIn(expected_error, validation.errors)


if __name__ == "__main__":
    unittest.main()
