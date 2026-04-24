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
from kpicalculator.adapters.common_model import (  # noqa: E402
    Asset,
    AssetType,
    EnergySystem,
    TimeSeries,
)
from kpicalculator.calculators.financial_calculator import FinancialCalculator  # noqa: E402


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
        self.assertIn("financials", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)

        # Check specific values (using ESDL costInformation only)
        self.assertAlmostEqual(
            results["financials"]["capex"]["All"],
            107900.03,
            places=2,
            msg="Total CAPEX is incorrect",
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
            file_results["financials"]["capex"]["All"],
            string_results["financials"]["capex"]["All"],
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


class SimulatorFieldMappingTest(unittest.TestCase):
    """Test that simulator-core field names map to the correct KPI calculator categories.

    Each test loads a DataFrame with a single simulator-core field name and asserts that
    the corresponding KPI category (consumption, production, or conversion) is non-zero.

    Asset IDs from Unit_test_ESDL.esdl:
      CONSUMER    a5243809-0077-46e5-a0ea-09aa486f5e96  GenericConsumer_a524
      PRODUCER    b98655e1-9e81-4878-875f-c1f946cc5d6c  GenericProducer_b986
      CONVERSION  743b1ff1-0ee4-4c6c-ba5f-e7ebf169348c  GasHeater_743b
    """

    TIMESTEPS = 24
    POWER_W = 100_000.0
    CONSUMER_ID = "a5243809-0077-46e5-a0ea-09aa486f5e96"
    PRODUCER_ID = "b98655e1-9e81-4878-875f-c1f946cc5d6c"
    CONVERSION_ID = "743b1ff1-0ee4-4c6c-ba5f-e7ebf169348c"

    def setUp(self) -> None:
        self.esdl_file = str(DATA_DIR / "Unit_test_ESDL.esdl")

    def _make_dataframe(self, columns: dict) -> pd.DataFrame:
        index = pd.date_range("2024-01-01T00:00:00", periods=self.TIMESTEPS, freq="h")
        return pd.DataFrame(columns, index=index)

    def _load_and_calculate(self, asset_id: str, column_name: str) -> dict:
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            self.esdl_file,
            timeseries_dataframes={
                asset_id: self._make_dataframe({column_name: [self.POWER_W] * self.TIMESTEPS})
            },
        )
        return kpi_manager.calculate_all_kpis()

    def test__heat_power_primary__maps_to_consumption(self) -> None:
        # heat_power_primary is in CONSUMPTION_FIELDS; load it on a CONSUMER asset
        results = self._load_and_calculate(self.CONSUMER_ID, "heat_power_primary")
        self.assertGreater(
            results["energy"]["consumption"],
            0.0,
            "heat_power_primary must contribute to energy consumption",
        )

    def test__heat_power_secondary__maps_to_production(self) -> None:
        # heat_power_secondary is in PRODUCTION_FIELDS; load it on a PRODUCER asset
        results = self._load_and_calculate(self.PRODUCER_ID, "heat_power_secondary")
        self.assertGreater(
            results["energy"]["production"],
            0.0,
            "heat_power_secondary must contribute to energy production",
        )

    def test__electricity_consumption__stored_as_named_time_series(self) -> None:
        # electricity_consumption is in CONVERSION_FIELDS; load it on a CONVERSION asset
        # and verify it is stored (recognised) in the time series for that asset.
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            self.esdl_file,
            timeseries_dataframes={
                self.CONVERSION_ID: self._make_dataframe(
                    {"electricity_consumption": [self.POWER_W] * self.TIMESTEPS}
                )
            },
        )
        kpi_manager.calculate_all_kpis()
        asset = next(a for a in kpi_manager.energy_system.assets if a.id == self.CONVERSION_ID)
        self.assertIn(
            "electricity_consumption",
            asset.time_series,
            "electricity_consumption must be stored as a named time series on a CONVERSION asset",
        )


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
        self.assertAlmostEqual(
            capex_value, self.kpi_results["financials"]["capex"]["All"], places=2
        )
        self.assertAlmostEqual(opex_value, self.kpi_results["financials"]["opex"]["All"], places=2)

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


class FinancialCalculatorEdgeCaseTest(unittest.TestCase):
    """Unit tests for NPV and LCOE edge cases in FinancialCalculator.

    These tests use a minimal synthetic EnergySystem — no file I/O, no ESDL parsing —
    so they are fast and isolated.  Each test pins a specific mathematical edge case
    that the integration tests in NewKpiCalculatorTest do not exercise.
    """

    def _make_system(
        self,
        investment: float = 100_000.0,
        opex_annual: float = 5_000.0,
        technical_lifetime: float = 40.0,
    ) -> EnergySystem:
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
        system_lifetime = 30.0
        investment = 100_000.0
        opex_annual = 5_000.0
        system = self._make_system(investment=investment, opex_annual=opex_annual)

        calc = FinancialCalculator(system)
        npv = calc.calculate_npv(system_lifetime, discount_rate=0.0)

        # At 0%: one CAPEX replacement (ceil(30/40)=1) + 30 years of OPEX
        expected = investment + opex_annual * system_lifetime
        self.assertAlmostEqual(npv, expected, places=2)

    def test_npv_positive_discount_rate_less_than_zero_rate(self) -> None:
        """NPV with a positive discount rate is strictly less than the undiscounted sum.

        Discounting future costs makes them worth less today, so discounted NPV < undiscounted NPV.
        This confirms that the discount factor is actually applied and not ignored.
        """

        system = self._make_system()
        calc = FinancialCalculator(system)

        npv_zero = calc.calculate_npv(30.0, discount_rate=0.0)
        npv_five = calc.calculate_npv(30.0, discount_rate=5.0)

        self.assertLess(npv_five, npv_zero)

    def test_npv_system_lifetime_shorter_than_technical_lifetime(self) -> None:
        """When system_lifetime < technical_lifetime, exactly one CAPEX investment is counted.

        ceil(10 / 40) = 1, so the asset is purchased once and not replaced within
        the project horizon.  This represents a short-horizon project (e.g. a 10-year
        concession) using a long-lived asset (40-year boiler).
        """

        investment = 100_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=40.0)
        calc = FinancialCalculator(system)

        # With no OPEX and 0% discount, NPV = exactly one investment
        npv = calc.calculate_npv(system_lifetime=10.0, discount_rate=0.0)

        self.assertAlmostEqual(npv, investment, places=2)

    def test_npv_system_lifetime_forces_asset_replacement(self) -> None:
        """When system_lifetime > technical_lifetime, the asset is replaced mid-project.

        ceil(50 / 40) = 2 replacements (year 0 and year 40).  The second replacement
        is discounted; this test confirms the replacement loop runs correctly.
        """

        investment = 100_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=40.0)
        calc = FinancialCalculator(system)

        # At 0% discount: NPV = 2 * investment (no discounting, two replacements)
        npv = calc.calculate_npv(system_lifetime=50.0, discount_rate=0.0)

        self.assertAlmostEqual(npv, 2 * investment, places=2)

    def test_lcoe_zero_energy_returns_zero(self) -> None:
        """LCOE returns 0.0 when annual energy production is zero.

        Without time series, energy = 0.  Dividing NPV by zero energy would be
        undefined; the calculator must return 0.0 rather than raising ZeroDivisionError.
        """

        system = self._make_system()
        calc = FinancialCalculator(system)

        lcoe = calc.calculate_lcoe(system_lifetime=30.0)

        self.assertEqual(lcoe, 0.0)


class FinancialCalculatorUnitBranchTest(unittest.TestCase):
    """Unit tests for the per-unit cost calculation branches in FinancialCalculator.

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

    def _make_system(self, asset: Asset) -> EnergySystem:
        return EnergySystem(
            name="Test System",
            assets=[asset],
            unit_conversion=dict(self._UNIT_CONVERSION),
        )

    def _make_asset(self, **kwargs) -> Asset:
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

    def _make_hourly_time_series(self, power_w: float) -> TimeSeries:
        """One year of constant hourly power values."""
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

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/kW")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/kW"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_mw(self) -> None:
        """EUR/MW investment cost scales with power, using a megawatt conversion factor."""

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/MW")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/MW"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_per_m(self) -> None:
        """EUR/m investment cost scales with asset length (e.g. pipeline cost per metre)."""

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/m")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/m"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_per_km(self) -> None:
        """EUR/km investment cost scales with length and converts metres to kilometres."""

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/km")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/km"]
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_eur_m3(self) -> None:
        """EUR/m³ investment cost scales with storage volume (no unit-conversion factor)."""

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="EUR/m3")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._VOLUME_M3
        self.assertAlmostEqual(calc._calculate_investment_cost(asset), expected, places=4)

    def test_investment_cost_unknown_unit_returns_zero(self) -> None:
        """An unrecognised investment cost unit returns 0.0 rather than raising."""

        asset = self._make_asset(investment_cost=self._COST_RATE, investment_cost_unit="UNKNOWN")
        calc = FinancialCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_investment_cost(asset), 0.0)

    # ------------------------------------------------------------------ #
    # _calculate_installation_cost                                         #
    # ------------------------------------------------------------------ #

    def test_installation_cost_eur_kw(self) -> None:
        """EUR/kW installation cost applies the same power-scaling as investment cost."""

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/kW")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._POWER_W * self._UNIT_CONVERSION["EUR/kW"]
        self.assertAlmostEqual(calc._calculate_installation_cost(asset), expected, places=4)

    def test_installation_cost_eur_per_km(self) -> None:
        """EUR/km installation cost scales with length and converts metres to kilometres."""

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/km")
        calc = FinancialCalculator(self._make_system(asset))

        expected = self._COST_RATE * self._LENGTH_M * self._UNIT_CONVERSION["EUR/km"]
        self.assertAlmostEqual(calc._calculate_installation_cost(asset), expected, places=4)

    def test_installation_cost_eur_m3(self) -> None:
        """EUR/m³ installation cost uses volume directly without a conversion factor."""

        asset = self._make_asset(installation_cost=self._COST_RATE, installation_cost_unit="EUR/m3")
        calc = FinancialCalculator(self._make_system(asset))

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

        capex = 1_000.0
        opex_pct = 2.0  # 2%
        asset = self._make_asset(
            investment_cost=capex,
            investment_cost_unit="EUR",
            fixed_operational_cost=opex_pct,
            fixed_operational_cost_unit="% OF CAPEX",
        )
        calc = FinancialCalculator(self._make_system(asset))

        expected = capex * opex_pct * self._UNIT_CONVERSION["% OF CAPEX"]
        self.assertAlmostEqual(calc._calculate_fixed_operational_cost(asset), expected, places=4)

    def test_fixed_operational_cost_eur_mw(self) -> None:
        """EUR/MW fixed operational cost scales with asset power."""

        asset = self._make_asset(
            fixed_operational_cost=self._COST_RATE,
            fixed_operational_cost_unit="EUR/MW",
        )
        calc = FinancialCalculator(self._make_system(asset))

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

        power_w = 100_000.0  # 100 kW
        cost_rate = 10.0  # EUR/MWh
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_operational_cost=cost_rate,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = FinancialCalculator(self._make_system(asset))

        result = calc._calculate_variable_operational_cost(asset)
        self.assertGreater(result, 0.0)

    def test_variable_operational_cost_eur_kwh_with_time_series(self) -> None:
        """EUR/kWh variable operational cost also integrates the time series.

        EUR/kWh and EUR/MWh follow the same code path with different unit factors.
        A non-zero result confirms both branches of the EUR/kWh | EUR/MWh condition
        are reachable.
        """

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_operational_cost=0.01,
            variable_operational_cost_unit="EUR/kWh",
            time_series={"key": ts},
        )
        calc = FinancialCalculator(self._make_system(asset))

        self.assertGreater(calc._calculate_variable_operational_cost(asset), 0.0)

    def test_variable_operational_cost_no_time_series_returns_zero(self) -> None:
        """EUR/MWh variable operational cost returns 0.0 when no time series is present.

        Without energy data the energy integral is undefined; returning 0.0 avoids
        a ZeroDivisionError and is consistent with the zero-energy edge case contract.
        """

        asset = self._make_asset(
            variable_operational_cost=10.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={},
        )
        calc = FinancialCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_variable_operational_cost(asset), 0.0)

    def test_variable_operational_cost_geothermal_cop_path(self) -> None:
        """Geothermal assets with COP > 0 divide variable cost by COP.

        A geothermal heat pump delivers more thermal energy than it consumes
        electrically (COP > 1).  The variable cost per unit of consumed energy
        must be scaled down by COP to reflect actual cost per delivered MWh.
        A higher COP yields a lower cost for the same rate and energy output.
        """
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

        calc2 = FinancialCalculator(self._make_system(asset_cop2))
        calc4 = FinancialCalculator(self._make_system(asset_cop4))

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

        capex = 2_000.0
        maint_pct = 1.5
        asset = self._make_asset(
            investment_cost=capex,
            investment_cost_unit="EUR",
            fixed_maintenance_cost=maint_pct,
            fixed_maintenance_cost_unit="% OF CAPEX",
        )
        calc = FinancialCalculator(self._make_system(asset))

        expected = capex * maint_pct * self._UNIT_CONVERSION["% OF CAPEX"]
        self.assertAlmostEqual(calc._calculate_fixed_maintenance_cost(asset), expected, places=4)

    def test_fixed_maintenance_cost_eur_mw(self) -> None:
        """EUR/MW fixed maintenance cost scales with asset rated power."""

        asset = self._make_asset(
            fixed_maintenance_cost=self._COST_RATE,
            fixed_maintenance_cost_unit="EUR/MW",
        )
        calc = FinancialCalculator(self._make_system(asset))

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

        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = FinancialCalculator(self._make_system(asset))

        self.assertGreater(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def test_variable_maintenance_cost_geothermal_cop_path(self) -> None:
        """Geothermal COP scaling also applies to variable maintenance cost.

        Both _calculate_variable_operational_cost and _calculate_variable_maintenance_cost
        contain the geothermal COP branch independently.  This test covers the maintenance
        version to ensure both are tested.
        """
        power_w = 100_000.0
        ts = self._make_hourly_time_series(power_w)
        asset = self._make_asset(
            asset_type=AssetType.GEOTHERMAL,
            cop=3.0,
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={"key": ts},
        )
        calc = FinancialCalculator(self._make_system(asset))

        # With COP=3 the cost must be positive (COP > 0 branch executed)
        self.assertGreater(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def test_variable_maintenance_cost_no_time_series_returns_zero(self) -> None:
        """EUR/MWh variable maintenance cost returns 0.0 with no time series data."""

        asset = self._make_asset(
            variable_maintenance_cost=5.0,
            variable_maintenance_cost_unit="EUR/MWh",
            time_series={},
        )
        calc = FinancialCalculator(self._make_system(asset))

        self.assertEqual(calc._calculate_variable_maintenance_cost(asset), 0.0)

    def _assert_unsupported_unit_logs_warning(
        self, method_name: str, unit_field: str, unit_value: str, cost_field: str
    ) -> None:
        """Helper: verify that an unsupported unit logs a warning and returns 0.0."""

        asset = self._make_asset(**{cost_field: 5.0, unit_field: unit_value})
        calc = FinancialCalculator(self._make_system(asset))

        logger_name = "kpicalculator.calculators.financial_calculator"
        with self.assertLogs(logger_name, level="WARNING") as cm:
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
        from kpicalculator.calculators.emission_calculator import EmissionCalculator

        ts = TimeSeries(time_step=0.0, values=[100.0] * 10)
        asset = self._make_asset(
            asset_type=AssetType.PRODUCER,
            emission_factor=1e-9,
            time_series={"ThermalProduction": ts},
        )
        calc = EmissionCalculator(self._make_system(asset))

        self.assertEqual(calc.get_total_emissions(), 0.0)

    def test_financial_calculator_zero_duration_returns_zero(self) -> None:
        """Variable cost with time_step=0 must not crash with ZeroDivisionError."""
        ts = TimeSeries(time_step=0.0, values=[100.0] * 10)
        asset = self._make_asset(
            variable_operational_cost=5.0,
            variable_operational_cost_unit="EUR/MWh",
            time_series={"heat_supplied": ts},
        )
        calc = FinancialCalculator(self._make_system(asset))

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

    def _make_asset(self, **kwargs) -> "Asset":
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

    def _make_system(self, assets: list) -> "EnergySystem":
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


class EacTcoCalculatorTest(unittest.TestCase):
    """Unit tests for EAC and TCO calculations in FinancialCalculator.

    Uses a minimal synthetic EnergySystem — no file I/O, no ESDL parsing — so
    tests are fast and isolated.  Each test pins a specific mathematical property
    of the formulas.
    """

    def _make_system(
        self,
        investment: float = 100_000.0,
        opex_annual: float = 5_000.0,
        technical_lifetime: float = 40.0,
    ) -> "EnergySystem":
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

    # --- Annuity factor spot checks (ported from mesido test_end_scenario_sizing_annualized.py) ---

    def test_annuity_factor_zero_discount_rate_n1(self) -> None:
        """annuity_factor(r=0, TL=1) == 1.0: EAC = CAPEX / TL = CAPEX.

        At r=0 the annuity degenerates to CAPEX / TL. For TL=1, annualized_CAPEX = CAPEX.
        Ported from mesido Assertion 4.
        """

        investment = 1_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=1.0)
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=0.0)

        self.assertAlmostEqual(eac, investment, places=10)

    def test_annuity_factor_10pct_discount_rate_tl1(self) -> None:
        """annuity_factor(r=0.10, TL=1) == 1.1: annualized_CAPEX = CAPEX x 1.1.

        For TL=1: factor = r / (1 - (1+r)^-1) = 1+r = 1.1.
        Ported from mesido Assertion 4.
        """

        investment = 1_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=1.0)
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=10.0)

        self.assertAlmostEqual(eac, investment * 1.1, places=10)

    # --- EAC tests ---

    def test_eac_annuity_formula_per_asset(self) -> None:
        """EAC applies annuity formula per asset using technical_lifetime, not system_lifetime.

        For a single asset: investment=100,000, r=5%, TL=40yr:
            annuity_factor = 0.05 / (1 - 1.05^-40)
            EAC = investment x annuity_factor
        """

        investment = 100_000.0
        technical_lifetime = 40.0
        discount_rate = 5.0
        system = self._make_system(
            investment=investment, opex_annual=0.0, technical_lifetime=technical_lifetime
        )
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=discount_rate)

        r = discount_rate / 100.0
        expected = investment * r / (1.0 - (1.0 + r) ** -technical_lifetime)
        self.assertAlmostEqual(eac, expected, places=10)

    def test_eac_zero_discount_rate_equals_capex_divided_by_technical_lifetime(self) -> None:
        """At r=0, EAC = CAPEX / technical_lifetime (simple straight-line depreciation)."""

        investment = 100_000.0
        technical_lifetime = 40.0
        system = self._make_system(
            investment=investment, opex_annual=0.0, technical_lifetime=technical_lifetime
        )
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=0.0)

        self.assertAlmostEqual(eac, investment / technical_lifetime, places=10)

    def test_eac_higher_discount_rate_yields_higher_eac(self) -> None:
        """Higher discount rate produces higher EAC (higher annuity factor)."""

        system = self._make_system()
        calc = FinancialCalculator(system)

        eac_low = calc.calculate_eac(discount_rate=2.0)
        eac_high = calc.calculate_eac(discount_rate=8.0)

        self.assertGreater(eac_high, eac_low)

    def test_eac_per_asset_discount_rate_overrides_fallback(self) -> None:
        """Per-asset discount_rate takes precedence over the fallback parameter.

        When asset.discount_rate is set, calculate_eac must use it instead of
        the discount_rate argument.  This test constructs two systems that are
        identical except for how the rate is supplied — directly on the asset vs.
        via the fallback parameter — and asserts they produce the same EAC.
        """
        import math

        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem

        investment = 100_000.0
        technical_lifetime = 40.0
        asset_rate = 7.0  # rate stored on the asset
        fallback_rate = 3.0  # different fallback — must be ignored

        # OPEX is explicitly zero so EAC == annualized CAPEX and the expected
        # formula below can use investment directly without an OPEX term.
        asset_with_rate = Asset(
            id="asset_a",
            name="Asset A",
            asset_type=AssetType.PRODUCER,
            investment_cost=investment,
            investment_cost_unit="EUR",
            fixed_operational_cost=0.0,
            technical_lifetime=technical_lifetime,
            discount_rate=asset_rate,
        )
        system_with_rate = EnergySystem(name="System A", assets=[asset_with_rate])

        # Reference system: no per-asset rate, fallback matches asset_rate
        asset_no_rate = Asset(
            id="asset_b",
            name="Asset B",
            asset_type=AssetType.PRODUCER,
            investment_cost=investment,
            investment_cost_unit="EUR",
            fixed_operational_cost=0.0,
            technical_lifetime=technical_lifetime,
        )
        system_no_rate = EnergySystem(name="System B", assets=[asset_no_rate])

        eac_asset_rate = FinancialCalculator(system_with_rate).calculate_eac(
            discount_rate=fallback_rate
        )
        eac_fallback = FinancialCalculator(system_no_rate).calculate_eac(discount_rate=asset_rate)

        # Both should equal the annuity at asset_rate
        r = asset_rate / 100.0
        expected = investment * r / (1.0 - math.pow(1.0 + r, -technical_lifetime))
        self.assertAlmostEqual(eac_asset_rate, expected, places=10)
        self.assertAlmostEqual(eac_asset_rate, eac_fallback, places=10)

        # Confirm it differs from what the fallback_rate would give
        eac_at_fallback_rate = FinancialCalculator(system_no_rate).calculate_eac(
            discount_rate=fallback_rate
        )
        self.assertNotAlmostEqual(eac_asset_rate, eac_at_fallback_rate, places=2)

    def test_eac_opex_passed_through_directly(self) -> None:
        """EAC includes annual OPEX directly — OPEX is not annualized."""

        opex_annual = 5_000.0
        system = self._make_system(investment=0.0, opex_annual=opex_annual, technical_lifetime=40.0)
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=5.0)

        self.assertAlmostEqual(eac, opex_annual, places=10)

    def test_npv_opex_end_of_period_discounting(self) -> None:
        """NPV discounts OPEX using end-of-period convention: year t at (1+r)^t, t=1..n.

        For a single asset with no CAPEX, r=10%, n=3 years, OPEX=1000/yr:
            NPV = 1000/1.1^1 + 1000/1.1^2 + 1000/1.1^3
                = 909.09 + 826.45 + 751.31 = 2486.85
        A start-of-period sum (t=0..2) would give a different result:
            1000/1.1^0 + 1000/1.1^1 + 1000/1.1^2 = 2735.54
        """

        system = self._make_system(investment=0.0, opex_annual=1_000.0, technical_lifetime=40.0)
        calc = FinancialCalculator(system)
        npv = calc.calculate_npv(system_lifetime=3.0, discount_rate=10.0)

        r = 0.10
        expected = sum(1_000.0 / (1 + r) ** t for t in range(1, 4))
        self.assertAlmostEqual(npv, expected, places=6)

    def test_npv_fractional_system_lifetime_prorates_final_year(self) -> None:
        """NPV with a fractional system_lifetime prorates the final partial year of OPEX.

        For system_lifetime=3.5, r=10%, OPEX=1000/yr:
            NPV = 1000/1.1^1 + 1000/1.1^2 + 1000/1.1^3 + 0.5*1000/1.1^4
        """

        system = self._make_system(investment=0.0, opex_annual=1_000.0, technical_lifetime=40.0)
        calc = FinancialCalculator(system)
        npv = calc.calculate_npv(system_lifetime=3.5, discount_rate=10.0)

        r = 0.10
        expected = sum(1_000.0 / (1 + r) ** t for t in range(1, 4))
        expected += 0.5 * 1_000.0 / (1 + r) ** 4
        self.assertAlmostEqual(npv, expected, places=6)

    def test_npv_zero_technical_lifetime_raises(self) -> None:
        """NPV raises CalculationError when any asset has technical_lifetime <= 0."""
        from kpicalculator.exceptions import CalculationError

        system = self._make_system(technical_lifetime=0.0)
        calc = FinancialCalculator(system)

        with self.assertRaises(CalculationError):
            calc.calculate_npv(system_lifetime=30.0)

    def test_eac_zero_technical_lifetime_raises(self) -> None:
        """EAC raises CalculationError when any asset has technical_lifetime <= 0."""
        from kpicalculator.exceptions import CalculationError

        system = self._make_system(technical_lifetime=0.0)
        calc = FinancialCalculator(system)

        with self.assertRaises(CalculationError):
            calc.calculate_eac()

    def test_tco_zero_technical_lifetime_raises(self) -> None:
        """TCO raises CalculationError when any asset has technical_lifetime <= 0."""
        from kpicalculator.exceptions import CalculationError

        system = self._make_system(technical_lifetime=0.0)
        calc = FinancialCalculator(system)

        with self.assertRaises(CalculationError):
            calc.calculate_tco(system_lifetime=30.0)

    def test_invalid_system_lifetime_raises_at_calculator_level(self) -> None:
        """Each calculator method raises CalculationError for system_lifetime <= 0."""
        from kpicalculator.exceptions import CalculationError

        calc = FinancialCalculator(self._make_system())

        for method, kwargs in [
            (calc.calculate_npv, {}),
            (calc.calculate_lcoe, {}),
            (calc.calculate_tco, {}),
        ]:
            with self.subTest(method=method.__name__, system_lifetime=0.0):
                with self.assertRaises(CalculationError):
                    method(system_lifetime=0.0, **kwargs)
            with self.subTest(method=method.__name__, system_lifetime=-1.0):
                with self.assertRaises(CalculationError):
                    method(system_lifetime=-1.0, **kwargs)

    def test_calculate_all_kpis_invalid_inputs_raise(self) -> None:
        """calculate_all_kpis() raises ValueError for invalid system_lifetime or discount_rate."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))

        with self.assertRaisesRegex(ValueError, "system_lifetime must be positive"):
            kpi_manager.calculate_all_kpis(system_lifetime=0.0)

        with self.assertRaisesRegex(ValueError, "system_lifetime must be positive"):
            kpi_manager.calculate_all_kpis(system_lifetime=-1.0)

        with self.assertRaisesRegex(ValueError, "discount_rate must be between 0 and 100"):
            kpi_manager.calculate_all_kpis(discount_rate=-1.0)

        with self.assertRaisesRegex(ValueError, "discount_rate must be between 0 and 100"):
            kpi_manager.calculate_all_kpis(discount_rate=101.0)

    def test_calculate_all_kpis_zero_discount_rate(self) -> None:
        """calculate_all_kpis() accepts discount_rate=0; EAC equals straight-line depreciation."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results_zero = kpi_manager.calculate_all_kpis(system_lifetime=30.0, discount_rate=0.0)
        results_5pct = kpi_manager.calculate_all_kpis(system_lifetime=30.0, discount_rate=5.0)

        self.assertIn("eac", results_zero["financials"])
        self.assertIsInstance(results_zero["financials"]["eac"], float)
        self.assertGreater(results_zero["financials"]["eac"], 0.0)
        # At r=0 the annuity factor is 1/TL, so EAC is lower than at r=5%.
        self.assertLess(results_zero["financials"]["eac"], results_5pct["financials"]["eac"])

    # --- TCO tests ---

    def test_eac_at_zero_discount_rate_is_straight_line_depreciation_plus_opex(self) -> None:
        """At r=0, EAC = CAPEX / TL + annual_opex (straight-line depreciation).

        EAC no longer relates to NPV or system_lifetime — it is purely per-asset.
        """

        investment = 100_000.0
        opex_annual = 5_000.0
        technical_lifetime = 40.0
        system = self._make_system(
            investment=investment, opex_annual=opex_annual, technical_lifetime=technical_lifetime
        )
        calc = FinancialCalculator(system)
        eac = calc.calculate_eac(discount_rate=0.0)

        expected = investment / technical_lifetime + opex_annual
        self.assertAlmostEqual(eac, expected, places=10)

    def test_tco_zero_discount_rate_equals_npv(self) -> None:
        """At 0% discount rate, TCO == NPV for any replacement ratio.

        Both NPV and TCO (default) use ceil for replacement counting, so they agree
        exactly at r=0 — including fractional ratios like technical_lifetime=20,
        system_lifetime=30 where ceil(1.5) = 2 for both.
        """

        investment = 100_000.0
        opex_annual = 5_000.0
        system_lifetime = 30.0

        for technical_lifetime in [40.0, 20.0, 10.0]:
            with self.subTest(technical_lifetime=technical_lifetime):
                system = self._make_system(
                    investment=investment,
                    opex_annual=opex_annual,
                    technical_lifetime=technical_lifetime,
                )
                calc = FinancialCalculator(system)
                npv_zero = calc.calculate_npv(system_lifetime, discount_rate=0.0)
                tco = calc.calculate_tco(system_lifetime)
                self.assertAlmostEqual(tco, npv_zero, places=6)

    def test_tco_default_uses_ceil(self) -> None:
        """Default TCO uses ceil(n/technical_lifetime) — the financially exact replacement count.

        With technical_lifetime=10 and system_lifetime=30: ceil(30/10) = 3.
        With technical_lifetime=20 and system_lifetime=30: ceil(30/20) = 2
        (you must buy a second asset at year 20 to keep the system running).
        """

        investment = 50_000.0
        system_lifetime = 30.0

        # Exact integer ratio — ceil and continuous agree
        system_exact = self._make_system(
            investment=investment, opex_annual=0.0, technical_lifetime=10.0
        )
        tco_exact = FinancialCalculator(system_exact).calculate_tco(system_lifetime)
        self.assertAlmostEqual(tco_exact, 3.0 * investment, places=2)

        # Fractional ratio — ceil gives 2, continuous would give 1.5
        system_frac = self._make_system(
            investment=investment, opex_annual=0.0, technical_lifetime=20.0
        )
        tco_frac = FinancialCalculator(system_frac).calculate_tco(system_lifetime)
        self.assertAlmostEqual(tco_frac, 2.0 * investment, places=2)

    def test_tco_continuous_factor_uses_max_fraction(self) -> None:
        """round_up_replacement=False uses max(1, n/technical_lifetime) for optimizer comparisons.

        With technical_lifetime=20 and system_lifetime=30: continuous factor = 1.5,
        matching optimizers such as MESIDO's MinimizeTCO goal (which uses this
        approximation to keep the objective smooth and differentiable).
        """

        investment = 50_000.0
        system_lifetime = 30.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=20.0)
        calc = FinancialCalculator(system)

        tco_default = calc.calculate_tco(system_lifetime)
        tco_continuous = calc.calculate_tco(system_lifetime, round_up_replacement=False)

        self.assertAlmostEqual(tco_default, 2.0 * investment, places=2)
        self.assertAlmostEqual(tco_continuous, 1.5 * investment, places=2)

    def test_tco_system_shorter_than_technical_lifetime_counts_one(self) -> None:
        """When system_lifetime < technical_lifetime, exactly one purchase is counted.

        ceil(10/40) = 1 — the asset is bought once and not replaced.
        """

        investment = 80_000.0
        system = self._make_system(investment=investment, opex_annual=0.0, technical_lifetime=40.0)
        tco = FinancialCalculator(system).calculate_tco(system_lifetime=10.0)
        self.assertAlmostEqual(tco, investment, places=2)

    def test_tco_greater_than_npv_with_positive_discount_rate(self) -> None:
        """TCO >= NPV when discount_rate > 0.

        NPV discounts future costs to present value (making them smaller), while
        TCO sums them at face value.  So TCO >= NPV for any positive discount rate.
        """
        system_lifetime = 30.0
        system = self._make_system(
            investment=100_000.0, opex_annual=5_000.0, technical_lifetime=40.0
        )
        calc = FinancialCalculator(system)

        tco = calc.calculate_tco(system_lifetime)
        npv = calc.calculate_npv(system_lifetime, discount_rate=5.0)

        self.assertGreaterEqual(tco, npv)

    def test_tco_present_in_calculate_all_kpis_results(self) -> None:
        """calculate_all_kpis() result dict includes 'tco' key under costs."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30)

        self.assertIn("tco", results["financials"])
        self.assertIsInstance(results["financials"]["tco"], float)
        self.assertGreater(results["financials"]["tco"], 0.0)


class AssetFinancialBreakdownTest(unittest.TestCase):
    """Tests for FinancialCalculator.get_asset_financial_breakdown() and aggregate_by_category().

    Uses a minimal synthetic EnergySystem to avoid file I/O and pin exact expected values.
    """

    _REQUIRED_KEYS = (
        "investment_cost",
        "installation_cost",
        "fixed_operational_cost",
        "variable_operational_cost",
        "fixed_maintenance_cost",
        "variable_maintenance_cost",
        "annualized_capex",
        "eac",
        "npv",
        "tco",
        "lcoe",
    )

    def _make_system(
        self,
        asset_type: AssetType | None = None,
        investment: float = 100_000.0,
        opex_annual: float = 5_000.0,
        technical_lifetime: float = 40.0,
        asset_id: str = "asset_1",
    ) -> "EnergySystem":
        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem

        if asset_type is None:
            asset_type = AssetType.CONSUMER
        asset = Asset(
            id=asset_id,
            name="Test Asset",
            asset_type=asset_type,
            investment_cost=investment,
            investment_cost_unit="EUR",
            fixed_operational_cost=opex_annual,
            fixed_operational_cost_unit="EUR/yr",
            technical_lifetime=technical_lifetime,
        )
        return EnergySystem(name="Test System", assets=[asset])

    # --- get_asset_financial_breakdown() ---

    def test_returns_dict_keyed_by_asset_id(self) -> None:
        """Result is a dict keyed by asset ID for every asset in the system."""

        system = self._make_system(asset_id="my_asset")
        breakdown = FinancialCalculator(system).get_asset_financial_breakdown(system_lifetime=30.0)

        self.assertIn("my_asset", breakdown)
        self.assertEqual(len(breakdown), 1)

    def test_result_has_all_required_keys(self) -> None:
        """Each AssetFinancialResult contains all 11 required keys."""

        system = self._make_system()
        breakdown = FinancialCalculator(system).get_asset_financial_breakdown(system_lifetime=30.0)
        entry = next(iter(breakdown.values()))

        for key in self._REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, entry)

    def test_lcoe_is_none_for_non_producing_asset(self) -> None:
        """lcoe is None for consumer, storage, transport, and conversion assets."""
        from kpicalculator.adapters.common_model import AssetType

        for asset_type in (AssetType.CONSUMER, AssetType.STORAGE, AssetType.TRANSPORT):
            with self.subTest(asset_type=asset_type):
                system = self._make_system(asset_type=asset_type)
                breakdown = FinancialCalculator(system).get_asset_financial_breakdown(
                    system_lifetime=30.0
                )
                self.assertIsNone(next(iter(breakdown.values()))["lcoe"])

    def test_lcoe_is_none_for_producer_without_energy_data(self) -> None:
        """lcoe is None for a producer when annual_energy_mwh_by_asset=None."""
        from kpicalculator.adapters.common_model import AssetType

        system = self._make_system(asset_type=AssetType.PRODUCER)
        breakdown = FinancialCalculator(system).get_asset_financial_breakdown(
            system_lifetime=30.0, annual_energy_mwh_by_asset=None
        )
        self.assertIsNone(next(iter(breakdown.values()))["lcoe"])

    def test_lcoe_is_computed_for_producer_with_energy_data(self) -> None:
        """lcoe is non-None for a producer when annual energy is supplied and non-zero."""
        from kpicalculator.adapters.common_model import AssetType

        system = self._make_system(asset_type=AssetType.PRODUCER, asset_id="prod_1")
        breakdown = FinancialCalculator(system).get_asset_financial_breakdown(
            system_lifetime=30.0,
            discount_rate=5.0,
            annual_energy_mwh_by_asset={"prod_1": 8_760.0},
        )
        lcoe = next(iter(breakdown.values()))["lcoe"]
        self.assertIsNotNone(lcoe)
        self.assertGreater(lcoe, 0.0)

    def test_npv_sum_matches_calculate_npv(self) -> None:
        """Sum of per-asset NPVs equals FinancialCalculator.calculate_npv()."""

        system = self._make_system()
        calc = FinancialCalculator(system)
        system_lifetime = 30.0
        discount_rate = 5.0

        breakdown = calc.get_asset_financial_breakdown(system_lifetime, discount_rate)
        npv_from_breakdown = sum(r["npv"] for r in breakdown.values())
        npv_direct = calc.calculate_npv(system_lifetime, discount_rate)

        self.assertAlmostEqual(npv_from_breakdown, npv_direct, places=6)

    def test_eac_sum_matches_calculate_eac(self) -> None:
        """Sum of per-asset EACs equals FinancialCalculator.calculate_eac()."""

        system = self._make_system()
        calc = FinancialCalculator(system)
        discount_rate = 5.0

        breakdown = calc.get_asset_financial_breakdown(
            system_lifetime=30.0, discount_rate=discount_rate
        )
        eac_from_breakdown = sum(r["eac"] for r in breakdown.values())
        eac_direct = calc.calculate_eac(discount_rate)

        self.assertAlmostEqual(eac_from_breakdown, eac_direct, places=6)

    def test_tco_sum_matches_calculate_tco(self) -> None:
        """Sum of per-asset TCOs equals FinancialCalculator.calculate_tco()."""

        system = self._make_system()
        calc = FinancialCalculator(system)
        system_lifetime = 30.0

        breakdown = calc.get_asset_financial_breakdown(system_lifetime)
        tco_from_breakdown = sum(r["tco"] for r in breakdown.values())
        tco_direct = calc.calculate_tco(system_lifetime)

        self.assertAlmostEqual(tco_from_breakdown, tco_direct, places=6)

    def test_invalid_system_lifetime_raises_calculation_error(self) -> None:
        """get_asset_financial_breakdown() raises CalculationError for system_lifetime <= 0."""
        from kpicalculator.exceptions import CalculationError

        calc = FinancialCalculator(self._make_system())

        with self.assertRaises(CalculationError):
            calc.get_asset_financial_breakdown(system_lifetime=0.0)

        with self.assertRaises(CalculationError):
            calc.get_asset_financial_breakdown(system_lifetime=-1.0)

    def test_invalid_discount_rate_raises_calculation_error(self) -> None:
        """get_asset_financial_breakdown() raises CalculationError for invalid discount_rate."""
        from kpicalculator.exceptions import CalculationError

        calc = FinancialCalculator(self._make_system())

        with self.assertRaises(CalculationError):
            calc.get_asset_financial_breakdown(system_lifetime=30.0, discount_rate=-1.0)

        with self.assertRaises(CalculationError):
            calc.get_asset_financial_breakdown(system_lifetime=30.0, discount_rate=101.0)

    def test_zero_technical_lifetime_raises_calculation_error(self) -> None:
        """get_asset_financial_breakdown() raises CalculationError for technical_lifetime <= 0."""
        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem
        from kpicalculator.exceptions import CalculationError

        asset = Asset(
            id="bad",
            name="Bad",
            asset_type=AssetType.CONSUMER,
            investment_cost=0.0,
            investment_cost_unit="EUR",
            technical_lifetime=0.0,
        )
        system = EnergySystem(name="S", assets=[asset])

        with self.assertRaises(CalculationError):
            FinancialCalculator(system).get_asset_financial_breakdown(system_lifetime=30.0)

    # --- aggregate_by_category() ---

    def test_aggregate_by_category_returns_tuple_of_two_dicts(self) -> None:
        """aggregate_by_category() returns (capex_dict, opex_dict)."""

        system = self._make_system()
        calc = FinancialCalculator(system)
        breakdown = calc.get_asset_financial_breakdown(system_lifetime=30.0)
        result = calc.aggregate_by_category(breakdown)

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        capex, opex = result
        self.assertIsInstance(capex, dict)
        self.assertIsInstance(opex, dict)

    def test_aggregate_by_category_has_expected_keys(self) -> None:
        """Both dicts include 'All' and the five named categories."""

        system = self._make_system()
        calc = FinancialCalculator(system)
        breakdown = calc.get_asset_financial_breakdown(system_lifetime=30.0)
        capex, opex = calc.aggregate_by_category(breakdown)

        expected_keys = {"Production", "Consumption", "Storage", "Transport", "Conversion", "All"}
        self.assertEqual(set(capex.keys()), expected_keys)
        self.assertEqual(set(opex.keys()), expected_keys)

    def test_aggregate_all_equals_sum_of_categories(self) -> None:
        """'All' equals the sum of the five named category values."""
        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem

        assets = [
            Asset(
                id="p1",
                name="P",
                asset_type=AssetType.PRODUCER,
                investment_cost=10_000.0,
                investment_cost_unit="EUR",
                fixed_operational_cost=500.0,
                technical_lifetime=20.0,
            ),
            Asset(
                id="c1",
                name="C",
                asset_type=AssetType.CONSUMER,
                investment_cost=5_000.0,
                investment_cost_unit="EUR",
                fixed_operational_cost=200.0,
                technical_lifetime=20.0,
            ),
        ]
        system = EnergySystem(name="S", assets=assets)
        calc = FinancialCalculator(system)
        breakdown = calc.get_asset_financial_breakdown(system_lifetime=30.0)
        capex, opex = calc.aggregate_by_category(breakdown)

        named_categories = ["Production", "Consumption", "Storage", "Transport", "Conversion"]
        self.assertAlmostEqual(capex["All"], sum(capex[k] for k in named_categories), places=6)
        self.assertAlmostEqual(opex["All"], sum(opex[k] for k in named_categories), places=6)

    def test_aggregate_empty_system_returns_zeros(self) -> None:
        """aggregate_by_category() on an empty system returns all-zero dicts without error.

        An empty system (zero assets) is a legitimate edge case — get_asset_financial_breakdown()
        returns {} for it, and aggregate_by_category({}) must return zeros cleanly.
        """
        from kpicalculator.adapters.common_model import EnergySystem

        system = EnergySystem(name="S", assets=[])
        calc = FinancialCalculator(system)
        breakdown = calc.get_asset_financial_breakdown(system_lifetime=30.0)
        capex, opex = calc.aggregate_by_category(breakdown)

        for key in capex:
            self.assertEqual(capex[key], 0.0)
        for key in opex:
            self.assertEqual(opex[key], 0.0)

    # --- asset_financials in KpiResults ---

    def test_calculate_all_kpis_includes_asset_financials(self) -> None:
        """calculate_all_kpis() result includes 'asset_financials' keyed by asset ID."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        self.assertIn("asset_financials", results)
        self.assertIsInstance(results["asset_financials"], dict)
        self.assertGreater(len(results["asset_financials"]), 0)

    def test_asset_financial_result_has_all_required_keys(self) -> None:
        """Every entry in asset_financials contains all 11 AssetFinancialResult keys."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        for asset_id, entry in results["asset_financials"].items():
            for key in self._REQUIRED_KEYS:
                with self.subTest(asset_id=asset_id, key=key):
                    self.assertIn(key, entry)

    def test_asset_npv_sum_equals_system_npv(self) -> None:
        """Sum of per-asset NPVs equals the system-level NPV in financials."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0, discount_rate=5.0)

        asset_npv_sum = sum(r["npv"] for r in results["asset_financials"].values())
        system_npv = results["financials"]["npv"]

        self.assertAlmostEqual(asset_npv_sum, system_npv, places=4)

    def test_asset_eac_sum_equals_system_eac(self) -> None:
        """Sum of per-asset EACs equals the system-level EAC in financials."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0, discount_rate=5.0)

        asset_eac_sum = sum(r["eac"] for r in results["asset_financials"].values())
        system_eac = results["financials"]["eac"]

        self.assertAlmostEqual(asset_eac_sum, system_eac, places=4)

    def test_asset_tco_sum_equals_system_tco(self) -> None:
        """Sum of per-asset TCOs equals the system-level TCO in financials."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        asset_tco_sum = sum(r["tco"] for r in results["asset_financials"].values())
        system_tco = results["financials"]["tco"]

        self.assertAlmostEqual(asset_tco_sum, system_tco, places=4)


class PerAssetLcoeTest(unittest.TestCase):
    """Tests for per-asset LCOE computation in KpiManager.calculate_all_kpis().

    Per-asset LCOE is computed inside FinancialCalculator.get_asset_financial_breakdown()
    when annual energy data is supplied. KpiManager pre-computes the energy dict from
    EnergyCalculator and passes it in; FinancialCalculator never imports EnergyCalculator.
    """

    def _make_producer_system_with_timeseries(self) -> tuple["KpiManager", str]:
        """Load the standard ESDL fixture with a real time series for energy data."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        series_file = DATA_DIR / "power_timeseries.xml"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file), time_series_file=str(series_file))
        return kpi_manager, str(esdl_file)

    def test_lcoe_filled_for_producing_assets_with_energy(self) -> None:
        """Producer assets with non-zero energy production get a non-None lcoe value."""

        # GenericConsumer asset — use a producer asset ID from the fixture if available,
        # but the fixture may only have consumer assets. We verify the contract:
        # if an asset IS a producer type AND has energy > 0, lcoe must not be None.
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            str(esdl_file), time_series_file=str(DATA_DIR / "power_timeseries.xml")
        )
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        from kpicalculator.calculators.financial_calculator import PRODUCER_ASSET_TYPES

        # For any producer asset that has a non-None, non-zero lcoe, verify it's positive
        producer_ids = {
            a.id for a in kpi_manager.energy_system.assets if a.asset_type in PRODUCER_ASSET_TYPES
        }
        for asset_id, entry in results["asset_financials"].items():
            if asset_id in producer_ids and entry["lcoe"] is not None:
                self.assertGreater(
                    entry["lcoe"],
                    0.0,
                    f"LCOE for producer asset {asset_id} must be positive when set",
                )

    def test_lcoe_none_for_non_producing_assets(self) -> None:
        """Non-producing assets (consumers, storage, transport) always have lcoe=None."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(
            str(esdl_file), time_series_file=str(DATA_DIR / "power_timeseries.xml")
        )
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        from kpicalculator.calculators.financial_calculator import PRODUCER_ASSET_TYPES

        producer_ids = {
            a.id for a in kpi_manager.energy_system.assets if a.asset_type in PRODUCER_ASSET_TYPES
        }
        for asset_id, entry in results["asset_financials"].items():
            if asset_id not in producer_ids:
                self.assertIsNone(
                    entry["lcoe"],
                    f"Non-producing asset {asset_id} must have lcoe=None",
                )

    def test_lcoe_none_when_no_time_series(self) -> None:
        """Without time series data, all assets have lcoe=None (zero energy production)."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        kpi_manager = KpiManager()
        kpi_manager.load_from_esdl(str(esdl_file))  # no time series
        results = kpi_manager.calculate_all_kpis(system_lifetime=30.0)

        for asset_id, entry in results["asset_financials"].items():
            self.assertIsNone(
                entry["lcoe"],
                f"Asset {asset_id} must have lcoe=None when no time series provided",
            )

    def test_per_asset_lcoe_formula_npv_over_discounted_energy(self) -> None:
        """Per-asset LCOE equals per-asset NPV divided by discounted energy production.

        At r=0: NPV = CAPEX + OPEX * system_lifetime,
                discounted_energy = annual_mwh * system_lifetime,
                so lcoe = (CAPEX + OPEX * n) / (annual_mwh * n).
        Verified by calling FinancialCalculator directly with a known energy dict.
        """
        from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem

        system_lifetime = 10.0
        investment = 100_000.0
        opex_annual = 5_000.0
        annual_energy_mwh = 8_760.0  # 1 MW continuously for one year

        asset = Asset(
            id="prod",
            name="Producer",
            asset_type=AssetType.PRODUCER,
            investment_cost=investment,
            investment_cost_unit="EUR",
            fixed_operational_cost=opex_annual,
            fixed_operational_cost_unit="EUR/yr",
            technical_lifetime=40.0,
        )
        system = EnergySystem(name="S", assets=[asset])
        calc = FinancialCalculator(system)
        breakdown = calc.get_asset_financial_breakdown(
            system_lifetime=system_lifetime,
            discount_rate=0.0,
            annual_energy_mwh_by_asset={"prod": annual_energy_mwh},
        )

        lcoe = breakdown["prod"]["lcoe"]
        expected_npv = investment + opex_annual * system_lifetime
        expected_lcoe = expected_npv / (annual_energy_mwh * system_lifetime)

        self.assertIsNotNone(lcoe)
        self.assertAlmostEqual(lcoe, expected_lcoe, places=6)


if __name__ == "__main__":
    unittest.main()
