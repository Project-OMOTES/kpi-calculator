import math
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import ClassVar

import pandas as pd

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

from esdl import esdl  # noqa: E402

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


class ZeroEnergyEdgeCaseTest(unittest.TestCase):
    """Verify documented behavior: no time series → all energy KPIs are 0.0."""

    def test_no_time_series_produces_zero_energy_kpis_and_warning(self) -> None:
        """Loading ESDL without any time series source must yield 0.0 for every
        energy KPI and emit a warning so callers can distinguish genuine zero
        results from missing data."""
        import logging

        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(DATA_DIR / "Unit_test_ESDL.esdl"))

        with self.assertLogs("kpicalculator.kpi_manager", level=logging.WARNING) as log:
            results = kpi_manager.calculate_all_kpis()

        energy = results["energy"]
        self.assertEqual(energy["consumption"], 0.0)
        self.assertEqual(energy["production"], 0.0)
        self.assertEqual(energy["demand"], 0.0)
        self.assertEqual(energy["efficiency"], 0.0)
        self.assertTrue(
            any("No time series data" in msg for msg in log.output),
            f"Expected 'No time series data' warning, got: {log.output}",
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


class TestTimeSeriesManagerValidation(unittest.TestCase):
    """Tests for uncovered validation branches in TimeSeriesManager."""

    ASSET_ID = "a5243809-0077-46e5-a0ea-09aa486f5e96"
    TIMESTEPS = 4

    def setUp(self) -> None:
        from esdl.esdl_handler import EnergySystemHandler

        from kpicalculator.adapters.time_series_manager import TimeSeriesManager

        handler = EnergySystemHandler()
        self.energy_system = handler.load_file(str(DATA_DIR / "Unit_test_ESDL.esdl"))
        self.manager = TimeSeriesManager()

    def _make_df(self, columns: dict, freq: str = "h") -> pd.DataFrame:
        index = pd.date_range("2024-01-01", periods=self.TIMESTEPS, freq=freq)
        return pd.DataFrame(columns, index=index)

    # ------------------------------------------------------------------ #
    # _validate_dataframe_time_series branches                            #
    # ------------------------------------------------------------------ #

    def test_empty_dataframe_produces_error(self) -> None:
        """Empty DataFrame (0 rows) is recorded as an error, asset is skipped."""
        empty_df = pd.DataFrame(
            {"ThermalConsumption": pd.Series([], dtype=float)},
            index=pd.DatetimeIndex([]),
        )
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: empty_df},
        )
        self.assertFalse(validation.is_valid)
        self.assertTrue(
            any("Empty DataFrame" in e for e in validation.errors),
            f"Expected 'Empty DataFrame' error, got: {validation.errors}",
        )

    def test_nan_values_produce_error(self) -> None:
        """DataFrame containing NaN values is recorded as an error."""
        import math

        df = self._make_df({"ThermalConsumption": [1.0, math.nan, 3.0, 4.0]})
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: df},
        )
        self.assertFalse(validation.is_valid)
        self.assertTrue(
            any("null values" in e for e in validation.errors),
            f"Expected 'null values' error, got: {validation.errors}",
        )

    def test_orphaned_asset_id_produces_warning(self) -> None:
        """Asset ID present in DataFrames but absent from ESDL produces a warning."""
        df = self._make_df({"ThermalConsumption": [1.0] * self.TIMESTEPS})
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={"nonexistent-asset-id": df},
        )
        self.assertTrue(
            any("Unknown assets" in w for w in validation.warnings),
            f"Expected 'Unknown assets' warning, got: {validation.warnings}",
        )

    def test_non_datetime_index_produces_error(self) -> None:
        """DataFrame with a plain integer index (not DatetimeIndex) is an error."""
        df = pd.DataFrame(
            {"ThermalConsumption": [1.0] * self.TIMESTEPS},
            index=range(self.TIMESTEPS),
        )
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: df},
        )
        self.assertFalse(validation.is_valid)
        self.assertTrue(
            any("DatetimeIndex" in e for e in validation.errors),
            f"Expected 'DatetimeIndex' error, got: {validation.errors}",
        )

    def test_negative_values_produce_warning(self) -> None:
        """Negative numeric values produce a warning (not an error)."""
        df = self._make_df({"ThermalConsumption": [-1.0, -2.0, 3.0, 4.0]})
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: df},
        )
        self.assertTrue(
            any("negative values" in w for w in validation.warnings),
            f"Expected 'negative values' warning, got: {validation.warnings}",
        )

    def test_very_large_values_produce_warning(self) -> None:
        """Values exceeding 1e9 produce a 'check units' warning."""
        df = self._make_df({"ThermalConsumption": [2e9] * self.TIMESTEPS})
        _, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: df},
        )
        self.assertTrue(
            any("very large values" in w for w in validation.warnings),
            f"Expected 'very large values' warning, got: {validation.warnings}",
        )

    # ------------------------------------------------------------------ #
    # _detect_time_step branches                                          #
    # ------------------------------------------------------------------ #

    def test_single_row_dataframe_defaults_to_hourly(self) -> None:
        """A DataFrame with only one row cannot compute a time step: defaults to 3600 s."""
        single_row = pd.DataFrame(
            {"ThermalConsumption": [100.0]},
            index=pd.DatetimeIndex(["2024-01-01T00:00:00"]),
        )
        ts_dict, _ = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: single_row},
        )
        from kpicalculator.common.constants import COMPOSITE_KEY_SEPARATOR

        key = f"{self.ASSET_ID}{COMPOSITE_KEY_SEPARATOR}ThermalConsumption"
        self.assertIn(key, ts_dict)
        self.assertEqual(ts_dict[key].time_step, 3600.0)

    def test_non_uniform_time_steps_asset_is_skipped(self) -> None:
        """Non-uniform time steps raise ValueError inside _detect_time_step;
        the per-asset exception handler records the error and skips the asset."""
        from kpicalculator.common.constants import COMPOSITE_KEY_SEPARATOR

        index = pd.DatetimeIndex(
            [
                "2024-01-01T00:00:00",
                "2024-01-01T01:00:00",
                "2024-01-01T03:00:00",
                "2024-01-01T06:00:00",
            ]
        )
        df = pd.DataFrame({"ThermalConsumption": [1.0, 2.0, 3.0, 4.0]}, index=index)
        ts_dict, validation = self.manager.load_time_series(
            self.energy_system,
            timeseries_dataframes={self.ASSET_ID: df},
        )
        key = f"{self.ASSET_ID}{COMPOSITE_KEY_SEPARATOR}ThermalConsumption"
        self.assertNotIn(key, ts_dict, "Non-uniform time series must not be stored")
        self.assertTrue(
            any("Non-uniform time steps" in e for e in validation.errors),
            f"Expected non-uniform time step error, got: {validation.errors}",
        )

    # ------------------------------------------------------------------ #
    # XML fallback path                                                   #
    # ------------------------------------------------------------------ #

    def test_xml_fallback_loads_time_series(self) -> None:
        """_load_from_xml returns a non-empty dict when given the standard test fixture."""
        xml_file = str(DATA_DIR / "power_timeseries.xml")
        ts_dict, validation = self.manager.load_time_series(
            self.energy_system,
            xml_file=xml_file,
        )
        self.assertTrue(validation.is_valid)
        self.assertGreater(len(ts_dict), 0, "XML load should produce at least one time series")

    def test_xml_fallback_missing_file_returns_invalid(self) -> None:
        """A non-existent XML file results in an invalid ValidationResult."""
        ts_dict, validation = self.manager.load_time_series(
            self.energy_system,
            xml_file="/nonexistent/path/to/file.xml",
        )
        self.assertEqual(ts_dict, {})
        self.assertFalse(validation.is_valid)

    def test_source_exception_is_recorded_and_falls_through_to_empty(self) -> None:
        """When _load_from_dataframes raises unexpectedly, the error is recorded
        and load_time_series falls through to the empty result."""
        from unittest.mock import patch

        df = self._make_df({"ThermalConsumption": [1.0] * self.TIMESTEPS})

        with patch.object(self.manager, "_load_from_dataframes", side_effect=RuntimeError("boom")):
            ts_dict, validation = self.manager.load_time_series(
                self.energy_system,
                timeseries_dataframes={self.ASSET_ID: df},
            )

        self.assertEqual(ts_dict, {})
        self.assertTrue(validation.is_valid)
        self.assertTrue(
            any("Failed to load time series from dataframes" in w for w in validation.warnings),
            f"Expected source-level error in warnings, got: {validation.warnings}",
        )

    def test_per_column_exception_is_recorded_as_error(self) -> None:
        """When converting a column raises unexpectedly, the error is recorded
        and the column is skipped while other columns still succeed."""
        from unittest.mock import patch

        df = self._make_df(
            {
                "ThermalConsumption": [1.0] * self.TIMESTEPS,
                "ThermalDemand": [2.0] * self.TIMESTEPS,
            }
        )

        original_is_numeric = pd.api.types.is_numeric_dtype

        def is_numeric_side_effect(series: pd.Series) -> bool:
            # Fail specifically on ThermalDemand; ThermalConsumption passes normally.
            # Keying on the series name is robust to column processing order changes.
            if getattr(series, "name", None) == "ThermalDemand":
                raise RuntimeError("simulated dtype check failure")
            return original_is_numeric(series)

        with patch("pandas.api.types.is_numeric_dtype", side_effect=is_numeric_side_effect):
            _ts_dict, validation = self.manager.load_time_series(
                self.energy_system,
                timeseries_dataframes={self.ASSET_ID: df},
            )

        self.assertTrue(
            any("Failed to convert DataFrame column" in e for e in validation.errors),
            f"Expected column-level error, got: {validation.errors}",
        )


class EsdlKpiExportIntegrationTest(unittest.TestCase):
    """Integration tests for ESDL KPI export through the KpiManager public API.

    These tests exercise the full pipeline: load ESDL + time series → calculate
    KPIs → export back to ESDL structure or file.  Unit-level tests for
    EsdlKpiExporter in isolation live in test_esdl_kpi_exporter.py.
    """

    def setUp(self) -> None:
        self.kpi_manager = KpiManager()
        self.kpi_manager.load_from_esdl(
            str(DATA_DIR / "Unit_test_ESDL.esdl"),
            time_series_file=str(DATA_DIR / "power_timeseries.xml"),
        )
        self.kpi_results = self.kpi_manager.calculate_all_kpis(system_lifetime=30)
        self._temp_dir = tempfile.TemporaryDirectory()
        self.test_temp_dir = Path(self._temp_dir.name)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_export_to_esdl_file_success(self) -> None:
        """Full round-trip: export KPIs to file and verify the file content."""
        output_file = str(self.test_temp_dir / "test_export.esdl")

        success = self.kpi_manager.export_to_esdl(self.kpi_results, output_file)

        self.assertTrue(success)
        self.assertTrue(Path(output_file).exists())
        content = Path(output_file).read_text(encoding="utf-8")
        self.assertIn("<KPIs", content)
        self.assertIn("DistributionKPI", content)
        self.assertIn("CAPEX", content)
        self.assertIn("OPEX", content)

    def test_build_esdl_with_kpis_data_structure(self) -> None:
        """build_esdl_with_kpis returns an EnergySystem containing cost KPI elements."""
        esdl_with_kpis = self.kpi_manager.build_esdl_with_kpis(self.kpi_results)

        self.assertIsInstance(esdl_with_kpis, esdl.EnergySystem)
        main_area = esdl_with_kpis.instance[0].area
        self.assertIsNotNone(main_area.KPIs)
        self.assertGreater(len(main_area.KPIs.kpi), 0)
        cost_kpis = [kpi for kpi in main_area.KPIs.kpi if "cost" in kpi.name.lower()]
        self.assertGreater(len(cost_kpis), 0)
        cost_kpi = cost_kpis[0]
        self.assertIsNotNone(cost_kpi.quantityAndUnit)
        self.assertIsNotNone(cost_kpi.distribution)
        self.assertGreater(len(cost_kpi.distribution.stringItem), 0)

    def test_kpi_content_accuracy(self) -> None:
        """Exported CAPEX and OPEX values match the values returned by calculate_all_kpis."""
        esdl_with_kpis = self.kpi_manager.build_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        high_level_kpi = next(
            (kpi for kpi in main_area.KPIs.kpi if "High level cost breakdown" in kpi.name),
            None,
        )
        self.assertIsNotNone(high_level_kpi, "High level cost breakdown KPI not found")

        capex_value = next(
            (
                float(item.value)
                for item in high_level_kpi.distribution.stringItem
                if "CAPEX" in item.label
            ),
            None,
        )
        opex_value = next(
            (
                float(item.value)
                for item in high_level_kpi.distribution.stringItem
                if "OPEX" in item.label
            ),
            None,
        )

        self.assertIsNotNone(capex_value)
        self.assertIsNotNone(opex_value)
        self.assertAlmostEqual(capex_value, self.kpi_results["costs"]["capex"]["All"], places=2)
        self.assertAlmostEqual(opex_value, self.kpi_results["costs"]["opex"]["All"], places=2)

    def test_kpi_structure_compliance(self) -> None:
        """Every exported KPI follows the ESDL DistributionKPI schema."""
        esdl_with_kpis = self.kpi_manager.build_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        self.assertIsInstance(main_area.KPIs, esdl.KPIs)
        self.assertIsNotNone(main_area.KPIs.id)

        for kpi in main_area.KPIs.kpi:
            self.assertIsInstance(kpi, esdl.DistributionKPI)
            self.assertIsNotNone(kpi.id)
            self.assertIsNotNone(kpi.name)
            self.assertIsInstance(kpi.quantityAndUnit, esdl.QuantityAndUnitType)
            self.assertIsNotNone(kpi.quantityAndUnit.physicalQuantity)
            self.assertIsNotNone(kpi.quantityAndUnit.unit)
            self.assertIsInstance(kpi.distribution, esdl.StringLabelDistribution)
            self.assertGreater(len(kpi.distribution.stringItem), 0)
            for item in kpi.distribution.stringItem:
                self.assertIsInstance(item, esdl.StringItem)
                self.assertIsNotNone(item.label)
                self.assertIsNotNone(item.value)

    def test_multiple_kpi_categories(self) -> None:
        """Exported ESDL contains KPIs for all three categories: cost, energy, emissions."""
        esdl_with_kpis = self.kpi_manager.build_esdl_with_kpis(self.kpi_results)
        kpi_names = [kpi.name.lower() for kpi in esdl_with_kpis.instance[0].area.KPIs.kpi]

        self.assertTrue(any("cost" in name for name in kpi_names))
        self.assertTrue(any("energy" in name for name in kpi_names))
        self.assertTrue(any("emission" in name or "co2" in name for name in kpi_names))

    def test_error_handling_no_energy_system(self) -> None:
        """export_to_esdl and build_esdl_with_kpis raise ValueError when no system is loaded."""
        empty_manager = KpiManager()

        with self.assertRaises(ValueError):
            empty_manager.export_to_esdl({}, "output.esdl")
        with self.assertRaises(ValueError):
            empty_manager.build_esdl_with_kpis({})

    def test_uuid_generation(self) -> None:
        """Every KPI element has a unique, well-formed UUID."""
        esdl_with_kpis = self.kpi_manager.build_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        seen: set[str] = set()
        kpis_id = main_area.KPIs.id
        self.assertIsNotNone(kpis_id)
        uuid.UUID(kpis_id)  # raises ValueError if malformed
        seen.add(kpis_id)

        for kpi in main_area.KPIs.kpi:
            self.assertIsNotNone(kpi.id)
            uuid.UUID(kpi.id)  # raises ValueError if malformed
            self.assertNotIn(kpi.id, seen, f"Duplicate UUID: {kpi.id}")
            seen.add(kpi.id)


class CostCalculatorEdgeCaseTest(unittest.TestCase):
    """Unit tests for NPV and LCOE edge cases in CostCalculator.

    These tests use a minimal synthetic EnergySystem — no file I/O, no ESDL parsing —
    so they are fast and isolated.  Each test pins a specific mathematical edge case
    that the integration tests in NewKpiCalculatorTest do not exercise.
    """

    def _make_system(
        self,
        investment: float = 100_000.0,
        opex_annual: float = 5_000.0,
        technical_lifetime: float = 40.0,
    ) -> "EnergySystem":  # noqa: F821  # imported below inside method
        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem

        asset = Asset(
            id="test_asset",
            name="Test Asset",
            asset_type=AssetType.PRODUCER,
            investment_cost=investment,
            investment_cost_unit="EUR",
            fixed_operational_cost=opex_annual,
            fixed_operational_cost_unit="EUR/yr",
            technical_lifetime=technical_lifetime,
        )
        return EnergySystem(name="Test System", assets=[asset])

    def test_npv_zero_discount_rate_equals_undiscounted_sum(self) -> None:
        """NPV at 0% discount rate equals the simple undiscounted sum of all costs.

        With discount_rate=0, the present-value factor 1/(1+0)^n = 1 for every year,
        so NPV reduces to: CAPEX (one investment) + OPEX * system_lifetime.
        This is the social cost accounting approach used in some public-sector projects.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        system_lifetime = 30.0
        investment = 100_000.0
        opex_annual = 5_000.0
        system = self._make_system(investment=investment, opex_annual=opex_annual)

        calc = CostCalculator(system)
        npv = calc.calculate_npv(system_lifetime, discount_rate=0.0)

        # At 0%: one CAPEX replacement (ceil(30/40)=1) + 30 years of OPEX
        expected = investment + opex_annual * system_lifetime
        self.assertAlmostEqual(npv, expected, places=2)

    def test_npv_positive_discount_rate_less_than_zero_rate(self) -> None:
        """NPV with a positive discount rate is strictly less than the undiscounted sum.

        Discounting future costs makes them worth less today, so discounted NPV < undiscounted NPV.
        This confirms that the discount factor is actually applied and not ignored.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        system = self._make_system()
        calc = CostCalculator(system)

        npv_zero = calc.calculate_npv(30.0, discount_rate=0.0)
        npv_five = calc.calculate_npv(30.0, discount_rate=5.0)

        self.assertLess(npv_five, npv_zero)

    def test_npv_system_lifetime_shorter_than_technical_lifetime(self) -> None:
        """When system_lifetime < technical_lifetime, exactly one CAPEX investment is counted.

        ceil(10 / 40) = 1, so the asset is purchased once and not replaced within
        the project horizon.  This represents a short-horizon project (e.g. a 10-year
        concession) using a long-lived asset (40-year boiler).
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        investment = 100_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=40.0)
        calc = CostCalculator(system)

        # With no OPEX and 0% discount, NPV = exactly one investment
        npv = calc.calculate_npv(system_lifetime=10.0, discount_rate=0.0)

        self.assertAlmostEqual(npv, investment, places=2)

    def test_npv_system_lifetime_forces_asset_replacement(self) -> None:
        """When system_lifetime > technical_lifetime, the asset is replaced mid-project.

        ceil(50 / 40) = 2 replacements (year 0 and year 40).  The second replacement
        is discounted; this test confirms the replacement loop runs correctly.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        investment = 100_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=40.0)
        calc = CostCalculator(system)

        # At 0% discount: NPV = 2 * investment (no discounting, two replacements)
        npv = calc.calculate_npv(system_lifetime=50.0, discount_rate=0.0)

        self.assertAlmostEqual(npv, 2 * investment, places=2)

    def test_lcoe_zero_energy_returns_zero(self) -> None:
        """LCOE returns 0.0 when annual energy production is zero.

        Without time series, energy = 0.  Dividing NPV by zero energy would be
        undefined; the calculator must return 0.0 rather than raising ZeroDivisionError.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        system = self._make_system()
        calc = CostCalculator(system)

        lcoe = calc.calculate_lcoe(system_lifetime=30.0)

        self.assertEqual(lcoe, 0.0)


class CostCalculatorUnitBranchTest(unittest.TestCase):
    """Unit tests for the per-unit cost calculation branches in CostCalculator.

    The integration tests in NewKpiCalculatorTest only exercise flat EUR costs because
    the ESDL fixture uses EUR everywhere.  These tests construct Asset objects directly
    with each supported cost unit and verify the calculation is numerically correct.

    This matters because the per-unit branches (EUR/kW, EUR/MW, EUR/m, EUR/km,
    EUR/m³, % OF CAPEX, EUR/MWh, EUR/kWh) are live code paths reached whenever
    the ESDL source contains assets with power-, length-, or volume-denominated costs.
    Vulture confirmed none of these branches are dead code.

    All tests are pure unit tests: no file I/O, no ESDL parsing, no network calls.
    """

    # Unit conversion factors matching COST_UNIT_FACTORS in constants.py
    _UNIT_CONVERSION: ClassVar[dict[str, float]] = {
        "EUR/kW": 1.0 / 1_000,
        "EUR/MW": 1.0 / 1_000_000,
        "EUR/m": 1.0,
        "EUR/km": 1.0 / 1_000,
        "EUR/kWh": 1.0 / 3_600_000,
        "EUR/MWh": 1.0 / 3_600_000_000,
        "% OF CAPEX": 1.0 / 100,
    }

    # Physically plausible reference values used throughout
    _POWER_W = 500_000.0  # 500 kW
    _LENGTH_M = 2_000.0  # 2 km pipe
    _VOLUME_M3 = 50.0  # 50 m³ storage
    _COST_RATE = 200.0  # e.g. 200 EUR/kW
    _HOURS = 8_760  # one year of hourly data
    _TIME_STEP = 3_600.0  # 1 hour in seconds

    def _make_system(self, asset: "Asset") -> "EnergySystem":  # noqa: F821
        from kpicalculator.adapters.common_model import EnergySystem

        return EnergySystem(
            name="Test System",
            assets=[asset],
            unit_conversion=dict(self._UNIT_CONVERSION),
        )

    def _make_asset(self, **kwargs) -> "Asset":  # noqa: F821
        from kpicalculator.adapters.common_model import Asset, AssetType

        defaults = dict(
            id="asset_1",
            name="Test Asset",
            asset_type=AssetType.PRODUCER,
            power=self._POWER_W,
            length=self._LENGTH_M,
            volume=self._VOLUME_M3,
            technical_lifetime=40.0,
        )
        defaults.update(kwargs)
        return Asset(**defaults)

    def _make_hourly_time_series(self, power_w: float) -> "TimeSeries":  # noqa: F821
        """One year of constant hourly power values."""
        from kpicalculator.adapters.common_model import TimeSeries

        return TimeSeries(
            time_step=self._TIME_STEP,
            values=[power_w] * self._HOURS,
        )

    # ------------------------------------------------------------------ #
    # _calculate_investment_cost                                           #
    # ------------------------------------------------------------------ #

    def test_investment_cost_eur_kw(self) -> None:
        """EUR/kW investment cost scales linearly with asset power.

        A 500 kW asset at 200 EUR/kW should cost 100,000 EUR.
        The EUR/kW factor converts watts → kilowatts (÷1000).
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/kW")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/kW"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_mw(self) -> None:
        """EUR/MW investment cost scales with power, using a megawatt conversion factor."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/MW")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/MW"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_per_m(self) -> None:
        """EUR/m investment cost scales with asset length (e.g. pipeline cost per metre)."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/m")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/m"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_per_km(self) -> None:
        """EUR/km investment cost scales with length and converts metres to kilometres."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/km")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/km"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_m3(self) -> None:
        """EUR/m³ investment cost scales with storage volume (no unit-conversion factor)."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/m3")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._VOLUME_M3
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_unknown_unit_returns_zero(self) -> None:
        """An unrecognised investment cost unit returns 0.0 rather than raising."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="UNKNOWN")
        calc = CostCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_investment_cost(asset), 0.0)

    # ------------------------------------------------------------------ #
    # _calculate_installation_cost                                         #
    # ------------------------------------------------------------------ #

    def test_installation_cost_eur_kw(self) -> None:
        """EUR/kW installation cost applies the same power-scaling as investment cost."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/kW")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/kW"]
        self.assertAlmostEqual(calc._calculate_installation_cost(asset), expected, places=4)

    def test_installation_cost_eur_per_km(self) -> None:
        """EUR/km installation cost scales with length and converts metres to kilometres."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/km")
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/km"]
        self.assertAlmostEqual(calc._calculate_installation_cost(asset), expected, places=4)

    def test_installation_cost_eur_m3(self) -> None:
        """EUR/m³ installation cost uses volume directly without a conversion factor."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/m3")
        calc = CostCalculator(self._make_system(asset))

        self.assertAlmostEqual(
            calc._calculate_installation_cost(asset), self._COST_RATE * self._VOLUME_M3, places=4
        )

    # ------------------------------------------------------------------ #
    # _calculate_fixed_operational_cost                                    #
    # ------------------------------------------------------------------ #

    def test_fixed_operational_cost_percent_of_capex(self) -> None:
        """% OF CAPEX fixed operational cost is a fraction of investment + installation cost.

        With 1000 EUR investment and 2% annual OPEX, the cost is 20 EUR/yr.
        This unit is common for O&M modelled as a percentage of total capital cost.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        capex = 1_000.0
        opex_pct = 2.0  # 2%
        asset = self._make_asset(
            investment_cost=capex,
            investment_cost_unit="EUR",
            fixed_operational_cost=opex_pct,
            fixed_operational_cost_unit="% OF CAPEX",
        )
        calc = CostCalculator(self._make_system(asset))

        expected = capex * opex_pct * self._UNIT_CONVERSION["% OF CAPEX"]
        self.assertAlmostEqual(calc._calculate_fixed_operational_cost(asset), expected, places=4)

    def test_fixed_operational_cost_eur_mw(self) -> None:
        """EUR/MW fixed operational cost scales with asset power."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(
            fixed_operational_cost=self._COST_RATE,
            fixed_operational_cost_unit="EUR/MW",
        )
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/MW"]
        self.assertAlmostEqual(calc._calculate_fixed_operational_cost(asset), expected, places=4)

    # ------------------------------------------------------------------ #
    # _calculate_variable_operational_cost                                 #
    # ------------------------------------------------------------------ #

    def test_variable_operational_cost_eur_mwh_with_time_series(self) -> None:
        """EUR/MWh variable operational cost integrates energy from the time series.

        One year of 100 kW constant output at 10 EUR/MWh should give a positive
        annual cost.  This confirms the time-series integration path is reached.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        power_w = 100_000.0  # 100 kW
        cost_rate = 10.0  # EUR/MWh
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_operational_cost=cost_rate,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = CostCalculator(self._make_system(asset))

        result = calc._calculate_variable_operational_cost(asset)
        self.assertGreater(result, 0.0)

    def test_variable_operational_cost_eur_kwh_with_time_series(self) -> None:
        """EUR/kWh variable operational cost also integrates the time series.

        EUR/kWh and EUR/MWh follow the same code path with different unit factors.
        A non-zero result confirms both branches of the EUR/kWh | EUR/MWh condition
        are reachable.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_operational_cost=0.01,
            variable_operational_cost_unit="EUR/kWh",
            time_series={"key": ts},
        )
        calc = CostCalculator(self._make_system(asset))

        self.assertGreater(calc._calculate_variable_operational_cost(asset), 0.0)

    def test_variable_operational_cost_no_time_series_returns_zero(self) -> None:
        """EUR/MWh variable operational cost returns 0.0 when no time series is present.

        Without energy data the energy integral is undefined; returning 0.0 avoids
        a ZeroDivisionError and is consistent with the zero-energy edge case contract.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(
            variable_operational_cost=10.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={},
        )
        calc = CostCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_variable_operational_cost(asset), 0.0)

    def test_variable_operational_cost_geothermal_cop_path(self) -> None:
        """Geothermal assets with COP > 0 divide variable cost by COP.

        A geothermal heat pump delivers more thermal energy than it consumes
        electrically (COP > 1).  The variable cost per unit of consumed energy
        must be scaled down by COP to reflect actual cost per delivered MWh.
        A higher COP yields a lower cost for the same rate and energy output.
        """
        from kpicalculator.adapters.common_model import AssetType
        from kpicalculator.calculators.cost_calculator import CostCalculator

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)

        # Same cost rate and time series; only COP differs
        asset_cop2 = self._make_asset(
            asset_type=AssetType.GEOTHERMAL,
            cop=2.0,
            variable_operational_cost=10.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        asset_cop4 = self._make_asset(
            asset_type=AssetType.GEOTHERMAL,
            cop=4.0,
            variable_operational_cost=10.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )

        calc2 = CostCalculator(self._make_system(asset_cop2))
        calc4 = CostCalculator(self._make_system(asset_cop4))

        # Higher COP → lower variable cost (energy delivered per unit consumed is higher)
        self.assertGreater(
            calc2._calculate_variable_operational_cost(asset_cop2),
            calc4._calculate_variable_operational_cost(asset_cop4),
        )

    # ------------------------------------------------------------------ #
    # _calculate_fixed_maintenance_cost                                    #
    # ------------------------------------------------------------------ #

    def test_fixed_maintenance_cost_percent_of_capex(self) -> None:
        """% OF CAPEX fixed maintenance cost is a fraction of total capital cost."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        capex = 2_000.0
        maint_pct = 1.5
        asset = self._make_asset(
            investment_cost=capex,
            investment_cost_unit="EUR",
            fixed_maintenance_cost=maint_pct,
            fixed_maintenance_cost_unit="% OF CAPEX",
        )
        calc = CostCalculator(self._make_system(asset))

        expected = capex * maint_pct * self._UNIT_CONVERSION["% OF CAPEX"]
        self.assertAlmostEqual(calc._calculate_fixed_maintenance_cost(asset), expected, places=4)

    def test_fixed_maintenance_cost_eur_mw(self) -> None:
        """EUR/MW fixed maintenance cost scales with asset rated power."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(
            fixed_maintenance_cost=self._COST_RATE,
            fixed_maintenance_cost_unit="EUR/MW",
        )
        calc = CostCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/MW"]
        self.assertAlmostEqual(calc._calculate_fixed_maintenance_cost(asset), expected, places=4)

    # ------------------------------------------------------------------ #
    # _calculate_variable_maintenance_cost                                 #
    # ------------------------------------------------------------------ #

    def test_variable_maintenance_cost_eur_mwh_with_time_series(self) -> None:
        """EUR/MWh variable maintenance cost integrates energy from the time series.

        The variable maintenance path is structurally identical to variable OPEX;
        this test confirms the separate maintenance method is also exercised.
        """
        from kpicalculator.calculators.cost_calculator import CostCalculator

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = CostCalculator(self._make_system(asset))

        self.assertGreater(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def test_variable_maintenance_cost_geothermal_cop_path(self) -> None:
        """Geothermal COP scaling also applies to variable maintenance cost.

        Both _calculate_variable_operational_cost and _calculate_variable_maintenance_cost
        contain the geothermal COP branch independently.  This test covers the maintenance
        version to ensure both are tested.
        """
        from kpicalculator.adapters.common_model import AssetType
        from kpicalculator.calculators.cost_calculator import CostCalculator

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            asset_type=AssetType.GEOTHERMAL,
            cop=3.0,
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = CostCalculator(self._make_system(asset))

        # With COP=3 the cost must be positive (COP > 0 branch executed)
        self.assertGreater(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def test_variable_maintenance_cost_no_time_series_returns_zero(self) -> None:
        """EUR/MWh variable maintenance cost returns 0.0 with no time series data."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={},
        )
        calc = CostCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def _assert_unsupported_unit_logs_warning(
        self, method_name: str, unit_field: str, unit_value: str, cost_field: str
    ) -> None:
        """Helper: verify that an unsupported unit logs a warning and returns 0.0."""
        from kpicalculator.calculators.cost_calculator import CostCalculator

        asset = self._make_asset(**{cost_field: 5.0, unit_field: unit_value})
        calc = CostCalculator(self._make_system(asset))

        with self.assertLogs("kpicalculator.calculators.cost_calculator", level="WARNING") as cm:
            result = getattr(calc, method_name)(asset)

        self.assertEqual(result, 0.0)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Unsupported unit", cm.output[0])
        self.assertIn(unit_value, cm.output[0])

    def test_unsupported_investment_cost_unit_logs_warning(self) -> None:
        """'% OF CAPEX' is valid for fixed ops/maintenance but not investment cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_investment_cost", "investment_cost_unit", "% OF CAPEX", "investment_cost"
        )

    def test_unsupported_installation_cost_unit_logs_warning(self) -> None:
        """'% OF CAPEX' is valid for fixed ops/maintenance but not installation cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_installation_cost",
            "installation_cost_unit",
            "% OF CAPEX",
            "installation_cost",
        )

    def test_unsupported_fixed_operational_cost_unit_logs_warning(self) -> None:
        """'EUR/km' is valid for investment/installation but not fixed operational cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_fixed_operational_cost",
            "fixed_operational_cost_unit",
            "EUR/km",
            "fixed_operational_cost",
        )

    def test_unsupported_variable_operational_cost_unit_logs_warning(self) -> None:
        """'% OF CAPEX' is valid for fixed ops/maintenance but not variable operational cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_variable_operational_cost",
            "variable_operational_cost_unit",
            "% OF CAPEX",
            "variable_operational_cost",
        )

    def test_unsupported_fixed_maintenance_cost_unit_logs_warning(self) -> None:
        """'EUR/km' is valid for investment/installation but not fixed maintenance cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_fixed_maintenance_cost",
            "fixed_maintenance_cost_unit",
            "EUR/km",
            "fixed_maintenance_cost",
        )

    def test_unsupported_variable_maintenance_cost_unit_logs_warning(self) -> None:
        """'% OF CAPEX' is valid for fixed ops/maintenance but not variable maintenance cost."""
        self._assert_unsupported_unit_logs_warning(
            "_calculate_variable_maintenance_cost",
            "variable_maintenance_cost_unit",
            "% OF CAPEX",
            "variable_maintenance_cost",
        )

    # ------------------------------------------------------------------ #
    # Zero-duration guards (prevent ZeroDivisionError)                     #
    # ------------------------------------------------------------------ #

    def test_energy_calculator_zero_duration_returns_zero(self) -> None:
        """A time series with time_step=0 must not crash with ZeroDivisionError."""
        from kpicalculator.adapters.common_model import AssetType, TimeSeries
        from kpicalculator.calculators.energy_calculator import EnergyCalculator

        ts = TimeSeries(time_step=0.0, values=[100.0] * 10)
        asset = self._make_asset(
            asset_type=AssetType.CONSUMER,
            time_series={"ThermalConsumption": ts},
        )
        calc = EnergyCalculator(self._make_system(asset))

        self.assertEqual(calc.get_total_energy_consumption_per_year(), 0.0)

    def test_emission_calculator_zero_duration_returns_zero(self) -> None:
        """A time series with time_step=0 must not crash with ZeroDivisionError."""
        from kpicalculator.adapters.common_model import AssetType, TimeSeries
        from kpicalculator.calculators.emission_calculator import EmissionCalculator

        ts = TimeSeries(time_step=0.0, values=[100.0] * 10)
        asset = self._make_asset(
            asset_type=AssetType.PRODUCER,
            emission_factor=1e-9,
            time_series={"ThermalProduction": ts},
        )
        calc = EmissionCalculator(self._make_system(asset))

        self.assertEqual(calc.get_total_emissions(), 0.0)

    def test_cost_calculator_zero_duration_returns_zero(self) -> None:
        """Variable cost with time_step=0 must not crash with ZeroDivisionError."""
        from kpicalculator.adapters.common_model import TimeSeries
        from kpicalculator.calculators.cost_calculator import CostCalculator

        ts = TimeSeries(time_step=0.0, values=[100.0] * 10)
        asset = self._make_asset(
            variable_operational_cost=5.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"heat_supplied": ts},
        )
        calc = CostCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_variable_operational_cost(asset), 0.0)


class BaseAdapterValidationTest(unittest.TestCase):
    """Tests for BaseAdapter._validate_energy_system().

    _validate_energy_system() is a concrete method on the abstract base class.
    It is called by adapters after constructing an EnergySystem to catch
    configuration errors early.  We exercise it through EsdlAdapter — the only
    concrete subclass — without loading any ESDL file.
    """

    def _make_adapter(self) -> "EsdlAdapter":  # noqa: F821
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        return EsdlAdapter()

    def _make_asset(self, **kwargs) -> "Asset":  # noqa: F821
        from kpicalculator.adapters.common_model import Asset, AssetType

        defaults = dict(
            id="asset_1",
            name="Test Asset",
            asset_type=AssetType.PRODUCER,
            power=1_000.0,
            technical_lifetime=30.0,
        )
        defaults.update(kwargs)
        return Asset(**defaults)

    def _make_system(self, assets: list) -> "EnergySystem":  # noqa: F821
        from kpicalculator.adapters.common_model import EnergySystem

        return EnergySystem(name="Test System", assets=assets)

    def test_empty_system_produces_warning_not_error(self) -> None:
        """An EnergySystem with no assets is valid but produces a warning.

        An empty system can result from an ESDL file with no asset elements.
        The validator should warn (so the caller can log it) but not block
        downstream calculation — KPI methods handle empty asset lists gracefully.
        """
        from kpicalculator.adapters.base_adapter import ValidationResult

        adapter = self._make_adapter()
        result = adapter._validate_energy_system(self._make_system(assets=[]))

        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(result.is_valid)
        self.assertGreater(len(result.warnings), 0)
        self.assertIn("no assets", result.warnings[0].lower())

    def test_valid_system_passes_validation(self) -> None:
        """A system with a well-formed asset passes validation with no errors or warnings."""
        adapter = self._make_adapter()
        result = adapter._validate_energy_system(self._make_system(assets=[self._make_asset()]))

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])

    def test_negative_technical_lifetime_produces_error(self) -> None:
        """An asset with technical_lifetime ≤ 0 makes the system invalid.

        A zero or negative lifetime would cause a ZeroDivisionError in the NPV
        calculation (it appears in the denominator of the replacement count).
        The validator must catch this before the calculator runs.
        """
        adapter = self._make_adapter()
        bad_asset = self._make_asset(technical_lifetime=-1.0)
        result = adapter._validate_energy_system(self._make_system(assets=[bad_asset]))

        self.assertFalse(result.is_valid)
        self.assertTrue(any("asset_1" in e for e in result.errors))

    def test_negative_power_produces_error(self) -> None:
        """An asset with negative power makes the system invalid.

        Power is a physical quantity and cannot be negative in the common model
        (negative values indicate a data extraction error in the ESDL adapter).
        """
        adapter = self._make_adapter()
        bad_asset = self._make_asset(power=-500.0)
        result = adapter._validate_energy_system(self._make_system(assets=[bad_asset]))

        self.assertFalse(result.is_valid)
        self.assertTrue(any("asset_1" in e for e in result.errors))

    def test_multiple_errors_all_collected(self) -> None:
        """All asset errors are collected and returned together, not short-circuited.

        When two assets are both invalid, both errors must appear in the result
        so the caller can report all problems at once rather than fixing them one by one.
        """
        adapter = self._make_adapter()
        bad1 = self._make_asset(id="a1", technical_lifetime=0.0)
        bad2 = self._make_asset(id="a2", power=-1.0)
        result = adapter._validate_energy_system(self._make_system(assets=[bad1, bad2]))

        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 2)


if __name__ == "__main__":
    unittest.main()
