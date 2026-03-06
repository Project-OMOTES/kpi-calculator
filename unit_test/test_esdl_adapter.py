# unit_test/test_esdl_adapter.py
"""Unit tests for EsdlAdapter — targeting previously uncovered branches.

Coverage groups addressed:
  High value
    - load_data() raises TypeError for non-path sources (line 83)
    - load_data() raises ValueError when validate_source() fails (line 90)
    - load_data() raises ValidationError when InputValidator rejects the path (lines 98-99)
    - validate_source() returns error for non-string source (lines 282-283)
    - validate_source() returns error when path is a directory (line 290)

  Medium value
    - Joint elements are skipped during asset iteration (line 243)
    - Disabled assets (state.value != 0) are skipped (line 250)
    - _get_asset_type() returns None for unsupported types → asset omitted (line 329)
    - Legacy time series warning is emitted once and de-duplicated (lines 369-378)
    - Asset validation failure causes the asset to be skipped, not raise (lines 388-391)
    - _get_asset_type() maps Pump, Transport, Storage, Conversion types (lines 414-418)

All tests are pure unit tests: no InfluxDB, no real file I/O beyond the existing
Unit_test_ESDL.esdl fixture (used only for validate_source path tests).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# ---------------------------------------------------------------------------
# Helper: create a minimal mock ESDL element that looks like an asset type
# ---------------------------------------------------------------------------


def _mock_asset(esdl_class, asset_id: str = "test-asset-id", name: str = "TestAsset"):
    """Return a MagicMock that passes isinstance checks for *esdl_class*.

    PyEcore isinstance is based on Python's native isinstance, so we must
    inject the class into the mock's __class__ attribute.
    """
    mock = MagicMock(spec=esdl_class)
    mock.__class__ = esdl_class
    mock.id = asset_id
    mock.name = name
    mock.port = []
    mock.technicalLifetime = 40.0
    mock.aggregationCount = 0
    mock.costInformation = None
    # Disable state by default (state is falsy → not disabled)
    mock.state = None
    return mock


# ---------------------------------------------------------------------------
# High value: validate_source()
# ---------------------------------------------------------------------------


class TestValidateSourceBranches(unittest.TestCase):
    """validate_source() branches that were not covered."""

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def test_non_string_source_returns_invalid_with_error(self) -> None:
        """validate_source() with a non-str source must return is_valid=False.

        Lines 282-283: the first branch checks isinstance(source, str) and
        appends an error message before returning early.
        """
        result = self.adapter.validate_source(12345)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("file path string" in e for e in result.errors),
            f"Expected 'file path string' in errors, got: {result.errors}",
        )

    def test_path_object_source_returns_invalid_with_error(self) -> None:
        """A Path object (not str) also triggers the non-string branch."""
        result = self.adapter.validate_source(Path("some/path.esdl"))

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("file path string" in e for e in result.errors),
            f"Expected 'file path string' in errors, got: {result.errors}",
        )

    def test_directory_path_returns_invalid_with_error(self) -> None:
        """validate_source() with an existing directory path returns is_valid=False.

        Line 290: the elif branch handles a path that exists but is not a file.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = self.adapter.validate_source(tmp_dir)

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("not a file" in e for e in result.errors),
            f"Expected 'not a file' in errors, got: {result.errors}",
        )

    def test_nonexistent_path_returns_invalid(self) -> None:
        """validate_source() with a path that does not exist returns is_valid=False."""
        result = self.adapter.validate_source("/nonexistent/path/file.esdl")

        self.assertFalse(result.is_valid)
        self.assertTrue(
            any("does not exist" in e for e in result.errors),
            f"Expected 'does not exist' in errors, got: {result.errors}",
        )

    def test_valid_esdl_file_returns_valid(self) -> None:
        """validate_source() with the real test ESDL fixture returns is_valid=True."""
        result = self.adapter.validate_source(str(DATA_DIR / "Unit_test_ESDL.esdl"))

        self.assertTrue(result.is_valid, f"Unexpected errors: {result.errors}")
        self.assertEqual(result.errors, [])


# ---------------------------------------------------------------------------
# High value: load_data() error paths
# ---------------------------------------------------------------------------


class TestLoadDataErrorPaths(unittest.TestCase):
    """load_data() branches that were not covered."""

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def test_non_path_source_raises_type_error(self) -> None:
        """load_data() raises TypeError for non-str/Path source.

        Line 83: MESIDO/Simulator protocol objects are not supported by this adapter.
        The adapter raises the built-in TypeError (not a custom exception).
        """
        with self.assertRaises(TypeError):
            self.adapter.load_data(source=42)

    def test_non_path_source_arbitrary_object_raises_type_error(self) -> None:
        """Any non-str/Path object triggers the TypeError branch.

        EsdlAdapter only accepts file paths. Passing any other type should raise
        TypeError immediately, before any file I/O is attempted.
        """
        mock_data = MagicMock()
        with self.assertRaises(TypeError):
            self.adapter.load_data(source=mock_data)

    def test_dataframe_source_raises_type_error_with_clear_message(self) -> None:
        """Passing a DataFrame raises TypeError with the actual type name in the message.

        This is the most likely caller mistake: using EsdlAdapter instead of
        SimulatorAdapter when the source is a simulator result DataFrame.
        """
        import pandas as pd

        df = pd.DataFrame()
        with self.assertRaises(TypeError) as ctx:
            self.adapter.load_data(source=df)

        self.assertIn("DataFrame", str(ctx.exception))

    def test_invalid_esdl_path_raises_value_error(self) -> None:
        """load_data() raises ValueError when validate_source() returns errors.

        Line 90: a non-existent file fails validation → ValueError is raised
        with the error list in the message.
        """
        with self.assertRaises(ValueError):
            self.adapter.load_data(source="/nonexistent/path/file.esdl")

    def test_security_validation_failure_raises_validation_error(self) -> None:
        """load_data() raises ValidationError when InputValidator rejects the path.

        Lines 98-99: InputValidator.validate_file_path() raises SecurityError or
        ValidationError (e.g. path traversal detected).  The adapter wraps this in
        a ValidationError and re-raises.

        We patch validate_source to return a valid result (so line 90 is not hit),
        then patch InputValidator.validate_file_path to raise SecurityError.
        """
        from kpicalculator.exceptions import SecurityError, ValidationError

        with (
            patch.object(
                self.adapter,
                "validate_source",
                return_value=MagicMock(is_valid=True, errors=[]),
            ),
            patch(
                "kpicalculator.adapters.esdl_adapter.InputValidator.validate_file_path",
                side_effect=SecurityError("path traversal detected"),
            ),
        ):
            with self.assertRaises(ValidationError):
                self.adapter.load_data(source="../../etc/passwd.esdl")


# ---------------------------------------------------------------------------
# Medium value: Joint and disabled asset skipping
# ---------------------------------------------------------------------------


class TestAssetSkipping(unittest.TestCase):
    """Tests for asset-level skipping logic in _process_energy_system().

    Rather than loading a real ESDL file, we use load_from_string() with
    minimal ESDL XML that exercises the target branches.
    """

    # Minimal valid ESDL without assets — used as a base for string loading
    _ESDL_EMPTY = """<?xml version='1.0' encoding='UTF-8'?>
<esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl" id="test-es-id" name="TestSystem">
    <instance id="inst-1" name="Instance">
        <area id="area-1" name="Area"/>
    </instance>
</esdl:EnergySystem>"""

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def test_joint_elements_are_skipped(self) -> None:
        """Joint elements must not appear in the resulting asset list.

        Line 243: the first isinstance check inside the asset loop skips Joint.
        We patch eAllContents to return a single Joint mock.
        """
        from esdl import esdl

        joint = _mock_asset(esdl.Joint, "joint-1", "Joint1")

        with patch("kpicalculator.adapters.base_adapter.EnergySystemHandler") as MockHandler:
            mock_es = MagicMock()
            mock_es.name = "TestSystem"
            mock_es.eAllContents.return_value = iter([joint])
            MockHandler.return_value.load_from_string.return_value = mock_es

            result = self.adapter.load_from_string(self._ESDL_EMPTY)

        # Joint must not appear in assets
        self.assertEqual(result.assets, [])

    def test_disabled_asset_is_skipped(self) -> None:
        """An asset with state.value != 0 is treated as disabled and skipped.

        Line 250: the state check continues (skips) when state.value != 0.
        """
        from esdl import esdl

        disabled = _mock_asset(esdl.Producer, "disabled-1", "DisabledProducer")
        # Set a truthy state with value != 0
        state_mock = MagicMock()
        state_mock.value = 1  # non-zero → disabled
        disabled.state = state_mock
        disabled.power = 100_000.0

        with patch("kpicalculator.adapters.base_adapter.EnergySystemHandler") as MockHandler:
            mock_es = MagicMock()
            mock_es.name = "TestSystem"
            mock_es.eAllContents.return_value = iter([disabled])
            MockHandler.return_value.load_from_string.return_value = mock_es

            result = self.adapter.load_from_string(self._ESDL_EMPTY)

        self.assertEqual(result.assets, [])

    def test_enabled_asset_state_zero_is_not_skipped(self) -> None:
        """An asset with state.value == 0 is treated as enabled.

        It reaches _create_asset_from_esdl.

        This contrasts with the disabled case (state.value != 0) which returns early.
        We verify that _create_asset_from_esdl is called, rather than counting final
        assets (which depends on unrelated validation logic for the mock object).
        """
        from esdl import esdl

        enabled = _mock_asset(esdl.Producer, "enabled-1", "EnabledProducer")
        state_mock = MagicMock()
        state_mock.value = 0  # zero → enabled
        enabled.state = state_mock
        enabled.power = 100_000.0

        with (
            patch("kpicalculator.adapters.base_adapter.EnergySystemHandler") as MockHandler,
            patch.object(self.adapter, "_create_asset_from_esdl", return_value=None) as mock_create,
        ):
            mock_es = MagicMock()
            mock_es.name = "TestSystem"
            mock_es.eAllContents.return_value = iter([enabled])
            MockHandler.return_value.load_from_string.return_value = mock_es

            self.adapter.load_from_string(self._ESDL_EMPTY)

        # _create_asset_from_esdl must have been called for the enabled asset
        mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# Medium value: _get_asset_type() — unsupported type and new mappings
# ---------------------------------------------------------------------------


class TestGetAssetType(unittest.TestCase):
    """Tests for _get_asset_type() covering previously uncovered branches."""

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def test_unsupported_type_returns_none(self) -> None:
        """_get_asset_type() returns None for types not in the mapping.

        Line 329: reaching the final return None path (no isinstance branch matched).
        """
        from esdl import esdl

        # esdl.Asset is the base class; it won't match any specific branch
        unsupported = _mock_asset(esdl.Asset, "unsup-1", "Unsupported")
        # Override __class__ to be a raw Asset (not any subclass the adapter handles)
        unsupported.__class__ = esdl.Asset

        result = self.adapter._get_asset_type(unsupported)
        self.assertIsNone(result)

    def test_pump_returns_pump_type(self) -> None:
        """_get_asset_type() returns AssetType.PUMP for esdl.Pump.

        Line 414-415.
        """
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        pump = _mock_asset(esdl.Pump, "pump-1", "Pump1")
        result = self.adapter._get_asset_type(pump)
        self.assertEqual(result, AssetType.PUMP)

    def test_transport_returns_transport_type(self) -> None:
        """_get_asset_type() returns AssetType.TRANSPORT for esdl.Transport.

        Line 416-417.
        """
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        transport = _mock_asset(esdl.Transport, "transport-1", "Transport1")
        result = self.adapter._get_asset_type(transport)
        self.assertEqual(result, AssetType.TRANSPORT)

    def test_storage_returns_storage_type(self) -> None:
        """_get_asset_type() returns AssetType.STORAGE for esdl.Storage.

        Line 408-409.
        """
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        storage = _mock_asset(esdl.Storage, "storage-1", "Storage1")
        result = self.adapter._get_asset_type(storage)
        self.assertEqual(result, AssetType.STORAGE)

    def test_conversion_returns_conversion_type(self) -> None:
        """_get_asset_type() returns AssetType.CONVERSION for esdl.Conversion.

        Line 410-411.
        """
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        conversion = _mock_asset(esdl.Conversion, "conv-1", "Conversion1")
        result = self.adapter._get_asset_type(conversion)
        self.assertEqual(result, AssetType.CONVERSION)

    def test_geothermal_returns_geothermal_type(self) -> None:
        """_get_asset_type() returns AssetType.GEOTHERMAL for esdl.GeothermalSource."""
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        geo = _mock_asset(esdl.GeothermalSource, "geo-1", "GeoSource")
        result = self.adapter._get_asset_type(geo)
        self.assertEqual(result, AssetType.GEOTHERMAL)

    def test_pipe_returns_pipe_type(self) -> None:
        """_get_asset_type() returns AssetType.PIPE for esdl.Pipe."""
        from esdl import esdl

        from kpicalculator.adapters.common_model import AssetType

        pipe = _mock_asset(esdl.Pipe, "pipe-1", "Pipe1")
        result = self.adapter._get_asset_type(pipe)
        self.assertEqual(result, AssetType.PIPE)


# ---------------------------------------------------------------------------
# Medium value: legacy time series warning deduplication
# ---------------------------------------------------------------------------


class TestLegacyTimeSeriesWarning(unittest.TestCase):
    """Tests for the legacy time series warning de-duplication logic.

    Lines 369-378: when an asset ID key (not composite) is found in time_series_dict,
    a warning is logged once per session and the warning key is tracked to suppress
    subsequent identical warnings.
    """

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def _build_time_series_dict(self, asset_id: str) -> dict:
        """Build a minimal time_series_dict with a plain asset-id key (legacy format)."""
        from kpicalculator.adapters.common_model import TimeSeries

        return {asset_id: TimeSeries(time_step=3600.0, values=[100.0] * 24)}

    def test_legacy_key_triggers_warning_log(self) -> None:
        """A plain asset ID key in time_series_dict triggers the warning path."""
        from esdl import esdl

        asset_id = "legacy-asset-id"
        producer = _mock_asset(esdl.Producer, asset_id, "LegacyProducer")
        producer.power = 100_000.0
        ts_dict = self._build_time_series_dict(asset_id)

        with self.assertLogs("kpicalculator.adapters.esdl_adapter", level="WARNING") as log_ctx:
            self.adapter._create_asset_from_esdl(
                producer,
                ts_dict,
            )

        self.assertTrue(
            any("no parameter information" in msg for msg in log_ctx.output),
            f"Expected legacy warning, got: {log_ctx.output}",
        )

    def test_legacy_warning_emitted_only_once_across_multiple_assets(self) -> None:
        """The legacy warning is logged exactly once, even with multiple legacy assets.

        Lines 372-378: the warning_key is added to self._logged_warnings after the first
        emission; subsequent calls skip the log statement.
        """
        from esdl import esdl

        # Two assets, both with plain (non-composite) keys
        asset_id_1 = "legacy-1"
        asset_id_2 = "legacy-2"
        ts_dict = {
            **self._build_time_series_dict(asset_id_1),
            **self._build_time_series_dict(asset_id_2),
        }

        producer_1 = _mock_asset(esdl.Producer, asset_id_1, "Legacy1")
        producer_1.power = 100_000.0
        producer_2 = _mock_asset(esdl.Producer, asset_id_2, "Legacy2")
        producer_2.power = 200_000.0

        with self.assertLogs("kpicalculator.adapters.esdl_adapter", level="WARNING") as log_ctx:
            self.adapter._create_asset_from_esdl(producer_1, ts_dict)
            self.adapter._create_asset_from_esdl(producer_2, ts_dict)

        # Only one warning message about legacy time series should appear
        legacy_warnings = [msg for msg in log_ctx.output if "no parameter information" in msg]
        self.assertEqual(
            len(legacy_warnings),
            1,
            f"Expected exactly 1 legacy warning, got {len(legacy_warnings)}: {log_ctx.output}",
        )

    def test_legacy_asset_count_increments_for_each_occurrence(self) -> None:
        """_legacy_asset_count increments on every legacy key hit, not just the first."""
        from esdl import esdl

        asset_id_1 = "count-asset-1"
        asset_id_2 = "count-asset-2"
        ts_dict = {
            **self._build_time_series_dict(asset_id_1),
            **self._build_time_series_dict(asset_id_2),
        }

        producer_1 = _mock_asset(esdl.Producer, asset_id_1, "CountAsset1")
        producer_1.power = 100_000.0
        producer_2 = _mock_asset(esdl.Producer, asset_id_2, "CountAsset2")
        producer_2.power = 200_000.0

        with self.assertLogs("kpicalculator.adapters.esdl_adapter", level="WARNING"):
            self.adapter._create_asset_from_esdl(producer_1, ts_dict)
            self.adapter._create_asset_from_esdl(producer_2, ts_dict)

        self.assertEqual(self.adapter._legacy_asset_count, 2)


# ---------------------------------------------------------------------------
# Medium value: asset validation failure → asset skipped (not raised)
# ---------------------------------------------------------------------------


class TestAssetValidationFailure(unittest.TestCase):
    """Tests for the InputValidator failure path in _create_asset_from_esdl().

    Lines 388-391: when InputValidator.validate_asset_properties() raises
    ValidationError or SecurityError, the adapter logs a warning and returns None
    instead of propagating the exception.  The calling loop then skips the asset.
    """

    def setUp(self) -> None:
        from kpicalculator.adapters.esdl_adapter import EsdlAdapter

        self.adapter = EsdlAdapter()

    def test_validation_failure_returns_none_not_raises(self) -> None:
        """_create_asset_from_esdl() returns None when validation fails.

        Lines 388-391: the except clause catches ValidationError/SecurityError,
        logs a warning, and returns None.
        """
        from esdl import esdl

        from kpicalculator.exceptions import ValidationError

        producer = _mock_asset(esdl.Producer, "val-fail-1", "ValFail")
        producer.power = 100_000.0

        with patch(
            "kpicalculator.adapters.esdl_adapter.InputValidator.validate_asset_properties",
            side_effect=ValidationError("simulated validation failure"),
        ):
            result = self.adapter._create_asset_from_esdl(producer, {})

        self.assertIsNone(result)

    def test_security_error_returns_none_not_raises(self) -> None:
        """_create_asset_from_esdl() returns None when SecurityError is raised."""
        from esdl import esdl

        from kpicalculator.exceptions import SecurityError

        producer = _mock_asset(esdl.Producer, "sec-fail-1", "SecFail")
        producer.power = 100_000.0

        with patch(
            "kpicalculator.adapters.esdl_adapter.InputValidator.validate_asset_properties",
            side_effect=SecurityError("simulated security failure"),
        ):
            result = self.adapter._create_asset_from_esdl(producer, {})

        self.assertIsNone(result)

    def test_validation_failure_warning_is_logged(self) -> None:
        """A warning is logged with the asset ID when validation fails."""
        from esdl import esdl

        from kpicalculator.exceptions import ValidationError

        asset_id = "warn-asset-id"
        producer = _mock_asset(esdl.Producer, asset_id, "WarnAsset")
        producer.power = 100_000.0

        with (
            patch(
                "kpicalculator.adapters.esdl_adapter.InputValidator.validate_asset_properties",
                side_effect=ValidationError("bad data"),
            ),
            self.assertLogs("kpicalculator.adapters.esdl_adapter", level="WARNING") as log_ctx,
        ):
            self.adapter._create_asset_from_esdl(producer, {})

        self.assertTrue(
            any(asset_id in msg for msg in log_ctx.output),
            f"Expected asset ID '{asset_id}' in warning log, got: {log_ctx.output}",
        )

    def test_failed_asset_is_excluded_from_energy_system(self) -> None:
        """An asset that fails validation is not added to the EnergySystem assets list."""
        from kpicalculator.exceptions import ValidationError

        _ESDL_EMPTY = """<?xml version='1.0' encoding='UTF-8'?>
<esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl" id="test-es-id" name="TestSystem">
    <instance id="inst-1" name="Instance">
        <area id="area-1" name="Area"/>
    </instance>
</esdl:EnergySystem>"""

        from esdl import esdl

        producer = _mock_asset(esdl.Producer, "excluded-asset", "Excluded")
        producer.power = 100_000.0

        with (
            patch("kpicalculator.adapters.base_adapter.EnergySystemHandler") as MockHandler,
            patch(
                "kpicalculator.adapters.esdl_adapter.InputValidator.validate_asset_properties",
                side_effect=ValidationError("cannot validate"),
            ),
        ):
            mock_es = MagicMock()
            mock_es.name = "TestSystem"
            mock_es.eAllContents.return_value = iter([producer])
            MockHandler.return_value.load_from_string.return_value = mock_es

            result = self.adapter.load_from_string(_ESDL_EMPTY)

        self.assertEqual(result.assets, [])


if __name__ == "__main__":
    unittest.main()
