# unit_test/test_simulator_adapter.py
"""Unit tests for SimulatorAdapter.

Coverage groups:
  validate_source()
    - Non-DataFrame input          → is_valid=False
    - Empty DataFrame              → is_valid=True, warning emitted
    - DataFrame with no 2-tuples   → is_valid=True, warning emitted
    - Well-formed DataFrame        → is_valid=True, no warnings

  get_supported_source_type / get_supported_parameters
    - Return the expected strings

  _convert_to_asset_dataframes()
    - Non-tuple columns skipped (no crash)
    - Multiple properties for same asset merged into one DataFrame
    - Unknown port skipped (warning, not crash)

  load_data() error paths
    - Empty / whitespace esdl_string → ValidationError
    - Non-DataFrame source           → ValidationError
    - Unparseable ESDL string        → ValidationError

  load_data() integration
    - Correct timeseries_dataframes shape passed to EsdlAdapter.load_from_string
    - Returns the EnergySystem produced by EsdlAdapter
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from esdl import esdl
from esdl.esdl_handler import EnergySystemHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ESDL_ONE_ASSET = """<?xml version='1.0' encoding='UTF-8'?>
<esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   id="es-1" name="TestSystem">
  <instance id="inst-1">
    <area id="area-1">
      <asset xsi:type="esdl:GeothermalSource" id="asset-1" name="Geo1">
        <port xsi:type="esdl:OutPort" id="port-out-1" name="Out"/>
      </asset>
    </area>
  </instance>
</esdl:EnergySystem>"""

_ESDL_TWO_ASSETS = """<?xml version='1.0' encoding='UTF-8'?>
<esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                   id="es-2" name="TestSystem2">
  <instance id="inst-1">
    <area id="area-1">
      <asset xsi:type="esdl:GeothermalSource" id="asset-1" name="Geo1">
        <port xsi:type="esdl:OutPort" id="port-out-1" name="Out"/>
      </asset>
      <asset xsi:type="esdl:HeatingDemand" id="asset-2" name="Demand1">
        <port xsi:type="esdl:InPort" id="port-in-2" name="In"/>
      </asset>
    </area>
  </instance>
</esdl:EnergySystem>"""


def _parse_esdl(esdl_string: str) -> esdl.EnergySystem:
    esh = EnergySystemHandler()
    return esh.load_from_string(esdl_string)


def _make_df(**columns) -> pd.DataFrame:
    """Build a small time-indexed DataFrame from keyword args mapping column → values.

    Scoped to this module. test_kpi_calculator.py has its own instance-method
    variant — the two are independent and serve different fixture shapes.
    """
    index = pd.date_range("2024-01-01", periods=3, freq="h")
    return pd.DataFrame(columns, index=index)


# ---------------------------------------------------------------------------
# validate_source()
# ---------------------------------------------------------------------------


class TestValidateSource(unittest.TestCase):
    """validate_source() covers the input type and shape checks."""

    def setUp(self) -> None:
        from kpicalculator.adapters.simulator_adapter import SimulatorAdapter

        self.adapter = SimulatorAdapter()

    def test_non_dataframe_is_invalid(self) -> None:
        """Passing anything that is not a DataFrame must return is_valid=False."""
        result = self.adapter.validate_source("not a dataframe")
        self.assertFalse(result.is_valid)
        self.assertTrue(result.errors)

    def test_empty_dataframe_is_valid_with_warning(self) -> None:
        """An empty DataFrame is accepted but warrants a warning."""
        result = self.adapter.validate_source(pd.DataFrame())
        self.assertTrue(result.is_valid)
        self.assertTrue(result.warnings)
        self.assertTrue(any("empty" in w.lower() for w in result.warnings))

    def test_dataframe_without_tuple_columns_is_valid_with_warning(self) -> None:
        """A non-empty DataFrame with no (port_id, property) columns produces a warning."""
        df = _make_df(column_a=[1, 2, 3])
        result = self.adapter.validate_source(df)
        self.assertTrue(result.is_valid)
        self.assertTrue(any("tuple" in w.lower() or "port" in w.lower() for w in result.warnings))

    def test_well_formed_dataframe_is_valid_no_warnings(self) -> None:
        """A DataFrame with (port_id, property_name) tuple columns passes cleanly."""
        df = _make_df()
        df[("port-1", "Heat_GJ")] = [10.0, 20.0, 30.0]
        result = self.adapter.validate_source(df)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])


# ---------------------------------------------------------------------------
# get_supported_source_type / get_supported_parameters
# ---------------------------------------------------------------------------


class TestMetadata(unittest.TestCase):
    def setUp(self) -> None:
        from kpicalculator.adapters.simulator_adapter import SimulatorAdapter

        self.adapter = SimulatorAdapter()

    def test_source_type(self) -> None:
        self.assertEqual(self.adapter.get_supported_source_type(), "simulator")

    def test_supported_parameters(self) -> None:
        self.assertIn("esdl_string", self.adapter.get_supported_parameters())


# ---------------------------------------------------------------------------
# _convert_to_asset_dataframes()
# ---------------------------------------------------------------------------


class TestConvertToAssetDataframes(unittest.TestCase):
    """Port→asset reindexing logic."""

    def setUp(self) -> None:
        from kpicalculator.adapters.simulator_adapter import SimulatorAdapter

        self.adapter = SimulatorAdapter()
        self.es = _parse_esdl(_ESDL_ONE_ASSET)

    def test_known_port_maps_to_asset(self) -> None:
        """A column (port-out-1, Heat_GJ) ends up in asset_data['asset-1']['Heat_GJ']."""
        df = _make_df()
        df[("port-out-1", "Heat_GJ")] = [100.0, 200.0, 300.0]

        result = self.adapter._convert_to_asset_dataframes(df, self.es)

        self.assertIn("asset-1", result)
        self.assertIn("Heat_GJ", result["asset-1"].columns)

    def test_multiple_properties_same_asset_merged(self) -> None:
        """Two properties for the same port both end up in one asset DataFrame."""
        df = _make_df()
        df[("port-out-1", "Heat_GJ")] = [1.0, 2.0, 3.0]
        df[("port-out-1", "Flow_m3s")] = [0.1, 0.2, 0.3]

        result = self.adapter._convert_to_asset_dataframes(df, self.es)

        self.assertIn("asset-1", result)
        self.assertIn("Heat_GJ", result["asset-1"].columns)
        self.assertIn("Flow_m3s", result["asset-1"].columns)

    def test_non_tuple_columns_skipped(self) -> None:
        """Plain string columns (e.g. 'datetime') are silently ignored."""
        df = _make_df(datetime=["a", "b", "c"])
        df[("port-out-1", "Heat_GJ")] = [1.0, 2.0, 3.0]

        result = self.adapter._convert_to_asset_dataframes(df, self.es)

        # 'datetime' must not appear as an asset key
        self.assertNotIn("datetime", result)
        self.assertIn("asset-1", result)

    def test_unknown_port_skipped_with_no_crash(self) -> None:
        """A port ID not present in the ESDL is skipped (warning logged, no exception)."""
        df = _make_df()
        df[("unknown-port", "Heat_GJ")] = [1.0, 2.0, 3.0]

        result = self.adapter._convert_to_asset_dataframes(df, self.es)

        self.assertEqual(result, {})

    def test_index_preserved(self) -> None:
        """The time index from the source DataFrame is preserved in the output."""
        df = _make_df()
        df[("port-out-1", "Heat_GJ")] = [5.0, 6.0, 7.0]

        result = self.adapter._convert_to_asset_dataframes(df, self.es)

        pd.testing.assert_index_equal(result["asset-1"].index, df.index)


# ---------------------------------------------------------------------------
# load_data() — error paths
# ---------------------------------------------------------------------------


class TestLoadDataErrors(unittest.TestCase):
    """load_data() must fail fast with clear exceptions for invalid inputs."""

    def setUp(self) -> None:
        from kpicalculator.adapters.simulator_adapter import SimulatorAdapter

        self.adapter = SimulatorAdapter()

    def test_empty_esdl_string_raises_validation_error(self) -> None:
        from kpicalculator.exceptions import ValidationError

        df = pd.DataFrame()
        with self.assertRaises(ValidationError):
            self.adapter.load_data(df, esdl_string="")

    def test_whitespace_esdl_string_raises_validation_error(self) -> None:
        """Whitespace-only strings are caught by the .strip() guard before parsing."""
        from kpicalculator.exceptions import ValidationError

        df = pd.DataFrame()
        with self.assertRaises(ValidationError):
            self.adapter.load_data(df, esdl_string="   ")

    def test_non_dataframe_source_raises_validation_error(self) -> None:
        from kpicalculator.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.adapter.load_data("not a dataframe", esdl_string=_ESDL_ONE_ASSET)

    def test_unparseable_esdl_raises_validation_error(self) -> None:
        from kpicalculator.exceptions import ValidationError

        df = _make_df()
        df[("port-out-1", "Heat_GJ")] = [1.0, 2.0, 3.0]
        with self.assertRaises(ValidationError):
            self.adapter.load_data(df, esdl_string="<not valid esdl xml")


# ---------------------------------------------------------------------------
# load_data() — integration (EsdlAdapter delegated correctly)
# ---------------------------------------------------------------------------


class TestLoadDataIntegration(unittest.TestCase):
    """load_data() must pass the correctly shaped timeseries_dataframes to EsdlAdapter."""

    def setUp(self) -> None:
        from kpicalculator.adapters.simulator_adapter import SimulatorAdapter

        self.adapter = SimulatorAdapter()

    def test_timeseries_dataframes_passed_to_esdl_adapter(self) -> None:
        """The asset-keyed DataFrames produced by _convert_to_asset_dataframes are
        forwarded unchanged to EsdlAdapter.load_from_esdl_object."""
        df = _make_df()
        df[("port-out-1", "Heat_GJ")] = [1.0, 2.0, 3.0]

        mock_energy_system = MagicMock()

        with patch("kpicalculator.adapters.esdl_adapter.EsdlAdapter") as MockEsdlAdapter:
            MockEsdlAdapter.return_value.load_from_esdl_object.return_value = mock_energy_system

            result = self.adapter.load_data(df, esdl_string=_ESDL_ONE_ASSET)

        MockEsdlAdapter.return_value.load_from_esdl_object.assert_called_once()
        call_kwargs = MockEsdlAdapter.return_value.load_from_esdl_object.call_args

        # First positional arg is the parsed esdl.EnergySystem object (not the string)
        self.assertIsNotNone(call_kwargs.args[0])

        # timeseries_dataframes must be a dict keyed by asset ID
        ts_dfs = call_kwargs.kwargs["timeseries_dataframes"]
        self.assertIsInstance(ts_dfs, dict)
        self.assertIn("asset-1", ts_dfs)
        self.assertIn("Heat_GJ", ts_dfs["asset-1"].columns)

        # Return value is whatever EsdlAdapter produced
        self.assertIs(result, mock_energy_system)

    def test_empty_dataframe_delegates_to_esdl_adapter(self) -> None:
        """An empty source DataFrame still delegates to EsdlAdapter (with empty ts dict)."""
        df = pd.DataFrame()
        mock_energy_system = MagicMock()

        with patch("kpicalculator.adapters.esdl_adapter.EsdlAdapter") as MockEsdlAdapter:
            MockEsdlAdapter.return_value.load_from_esdl_object.return_value = mock_energy_system

            result = self.adapter.load_data(df, esdl_string=_ESDL_ONE_ASSET)

        ts_dfs = MockEsdlAdapter.return_value.load_from_esdl_object.call_args.kwargs[
            "timeseries_dataframes"
        ]
        self.assertEqual(ts_dfs, {})
        self.assertIs(result, mock_energy_system)


if __name__ == "__main__":
    unittest.main()
