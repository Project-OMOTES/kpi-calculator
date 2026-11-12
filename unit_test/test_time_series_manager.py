# unit_test/test_time_series_manager.py
"""Tests for TimeSeriesManager database dispatch."""

import unittest
from unittest.mock import Mock, patch

import pandas as pd
from esdl import esdl

from kpicalculator.adapters.base_adapter import ValidationResult
from kpicalculator.adapters.time_series_manager import TimeSeriesManager
from kpicalculator.common.constants import COMPOSITE_KEY_SEPARATOR


def _energy_system(*profiles: object) -> esdl.EnergySystem:
    """Real EnergySystem holding the profiles on in-ports of separate demands."""
    energy_system = esdl.EnergySystem(id="es1")
    instance = esdl.Instance(id="inst1")
    energy_system.instance.append(instance)
    area = esdl.Area(id="area1")
    instance.area = area
    for i, profile in enumerate(profiles):
        demand = esdl.HeatingDemand(id=f"asset{i}")
        port = esdl.InPort(id=f"port{i}")
        demand.port.append(port)
        port.profile.append(profile)
        area.asset.append(demand)
    return energy_system


def _postgres_profile(**kwargs: object) -> esdl.DataTableProfile:
    profile = esdl.DataTableProfile(tableName="tbl", columnName="col", **kwargs)
    profile.configuration = esdl.DatabaseConfiguration(
        id="cfg1", host="pg.example.com", port=5432, type=esdl.DatabaseTypeEnum.POSTGRESQL
    )
    return profile


class TestHasDatabaseProfiles(unittest.TestCase):
    """_has_database_profiles uses the shared eligibility predicate."""

    def setUp(self) -> None:
        self.manager = TimeSeriesManager(Mock())

    def test_empty_energy_system(self) -> None:
        self.assertFalse(self.manager._has_database_profiles(_energy_system()))

    def test_postgres_data_table_profile(self) -> None:
        self.assertTrue(self.manager._has_database_profiles(_energy_system(_postgres_profile())))

    def test_ineligible_profiles_do_not_hide_an_eligible_one(self) -> None:
        output = _postgres_profile(profileType=esdl.ProfileTypeEnum.OUTPUT)
        self.assertTrue(
            self.manager._has_database_profiles(_energy_system(output, _postgres_profile()))
        )

    def test_profile_on_out_port_is_found(self) -> None:
        energy_system = _energy_system()
        area = energy_system.instance[0].area
        asset = esdl.HeatingDemand(id="asset_out")
        port = esdl.OutPort(id="out_port")
        port.profile.append(_postgres_profile())
        asset.port.append(port)
        area.asset.append(asset)
        self.assertTrue(self.manager._has_database_profiles(energy_system))


class TestLoadTimeSeriesDispatch(unittest.TestCase):
    """load_time_series routes to the database loader only for eligible profiles."""

    def setUp(self) -> None:
        self.manager = TimeSeriesManager(Mock())
        self.db_result: tuple = ({}, ValidationResult(is_valid=True, warnings=["from database"]))
        self.xml_result: tuple = ({}, ValidationResult(is_valid=True, warnings=["from xml"]))

    def test_postgres_profile_dispatches_to_database_loader(self) -> None:
        es = _energy_system(_postgres_profile())
        with (
            patch.object(
                self.manager.database_loader,
                "load_time_series_from_esdl",
                return_value=self.db_result,
            ) as mock_db,
            patch.object(self.manager, "_load_from_xml", return_value=self.xml_result) as mock_xml,
        ):
            result = self.manager.load_time_series(es, xml_file="series.xml")

        self.assertIs(result, self.db_result)
        mock_db.assert_called_once_with(es)
        mock_xml.assert_not_called()

    def test_only_ineligible_profiles_fall_through_to_xml(self) -> None:
        output = _postgres_profile(profileType=esdl.ProfileTypeEnum.OUTPUT)
        file_profile = esdl.DataTableProfile(tableName="tbl", columnName="col")
        file_profile.configuration = esdl.FileConfiguration(uri="x.csv")
        es = _energy_system(output, file_profile)
        self.assertFalse(self.manager._has_database_profiles(es))
        with (
            patch.object(
                self.manager.database_loader,
                "load_time_series_from_esdl",
                return_value=self.db_result,
            ) as mock_db,
            patch.object(self.manager, "_load_from_xml", return_value=self.xml_result) as mock_xml,
        ):
            result = self.manager.load_time_series(es, xml_file="series.xml")

        self.assertIs(result, self.xml_result)
        mock_db.assert_not_called()
        mock_xml.assert_called_once_with("series.xml", es)

    def test_only_ineligible_profiles_and_no_xml_gives_empty_result(self) -> None:
        output = _postgres_profile(profileType=esdl.ProfileTypeEnum.OUTPUT)
        with patch.object(self.manager.database_loader, "load_time_series_from_esdl") as mock_db:
            data, result = self.manager.load_time_series(_energy_system(output))

        self.assertEqual(data, {})
        self.assertEqual(result.warnings, ["No time series data loaded"])
        mock_db.assert_not_called()

    def test_dataframes_take_precedence_over_database_profiles(self) -> None:
        es = _energy_system(_postgres_profile())
        index = pd.date_range("2024-01-01", periods=3, freq="h")
        frames = {"asset0": pd.DataFrame({"heat_supplied": [1.0, 2.0, 3.0]}, index=index)}
        with patch.object(self.manager.database_loader, "load_time_series_from_esdl") as mock_db:
            data, _ = self.manager.load_time_series(es, timeseries_dataframes=frames)

        mock_db.assert_not_called()
        self.assertIn(f"asset0{COMPOSITE_KEY_SEPARATOR}heat_supplied", data)

    def test_database_loader_failure_falls_through_to_xml(self) -> None:
        es = _energy_system(_postgres_profile())
        with (
            patch.object(
                self.manager.database_loader,
                "load_time_series_from_esdl",
                side_effect=RuntimeError("db boom"),
            ) as mock_db,
            patch.object(self.manager, "_load_from_xml", return_value=self.xml_result),
        ):
            result = self.manager.load_time_series(es, xml_file="series.xml")

        mock_db.assert_called_once_with(es)
        self.assertIs(result, self.xml_result)

    def test_database_loader_failure_recorded_when_nothing_else_loads(self) -> None:
        es = _energy_system(_postgres_profile())
        with patch.object(
            self.manager.database_loader,
            "load_time_series_from_esdl",
            side_effect=RuntimeError("db boom"),
        ) as mock_db:
            data, result = self.manager.load_time_series(es)

        mock_db.assert_called_once_with(es)
        self.assertEqual(data, {})
        self.assertEqual(
            result.warnings,
            ["No time series data loaded", "Failed to load time series from database: db boom"],
        )

    def test_custom_source_priority_without_database_skips_it(self) -> None:
        es = _energy_system(_postgres_profile())
        with patch.object(self.manager.database_loader, "load_time_series_from_esdl") as mock_db:
            data, _ = self.manager.load_time_series(es, source_priority=["empty"])

        self.assertEqual(data, {})
        mock_db.assert_not_called()


class TestPasswordlessFlagPlumbing(unittest.TestCase):
    """allow_passwordless_database reaches the database loader."""

    def test_defaults_to_fail_closed(self) -> None:
        self.assertFalse(TimeSeriesManager(Mock()).database_loader.allow_passwordless_database)

    def test_flag_reaches_database_loader(self) -> None:
        manager = TimeSeriesManager(Mock(), allow_passwordless_database=True)
        self.assertTrue(manager.database_loader.allow_passwordless_database)


class TestFailedDatabaseLoadFallback(unittest.TestCase):
    """A database load that produced nothing usable lets the next source run."""

    def setUp(self) -> None:
        self.manager = TimeSeriesManager(Mock())
        self.es = _energy_system(_postgres_profile())
        self.failed: tuple = (
            {},
            ValidationResult(is_valid=False, errors=["connection refused"], warnings=["w1"]),
        )
        self.xml_result: tuple = (
            {"asset1|power": Mock()},
            ValidationResult(is_valid=True, warnings=["from xml"]),
        )

    def _load(self, *, xml_file: str | None = "series.xml", xml=None):
        with (
            patch.object(
                self.manager.database_loader, "load_time_series_from_esdl", return_value=self.failed
            ),
            patch.object(
                self.manager,
                "_load_from_xml",
                return_value=xml or self.xml_result,
            ) as mock_xml,
        ):
            return self.manager.load_time_series(self.es, xml_file=xml_file), mock_xml

    def test_failed_database_load_falls_back_to_xml_and_keeps_the_database_error(self) -> None:
        (data, result), mock_xml = self._load()

        mock_xml.assert_called_once_with("series.xml", self.es)
        self.assertEqual(data, self.xml_result[0])
        self.assertTrue(result.is_valid)
        self.assertEqual(
            result.warnings,
            ["from xml", "w1", "Database load failed, used another source: connection refused"],
        )

    def test_fallback_that_loads_nothing_keeps_the_database_failure_as_errors(self) -> None:
        empty_xml = ({}, ValidationResult(is_valid=True, warnings=["xml had no series"]))
        (data, result), mock_xml = self._load(xml=empty_xml)

        mock_xml.assert_called_once_with("series.xml", self.es)
        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["connection refused"])
        self.assertEqual(result.warnings, ["w1", "xml had no series"])

    def test_failed_database_load_without_other_source_stays_invalid(self) -> None:
        (data, result), mock_xml = self._load(xml_file=None)

        mock_xml.assert_not_called()
        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["connection refused"])
        self.assertEqual(result.warnings, ["w1"])

    def test_failed_database_load_and_failed_xml_report_both(self) -> None:
        with (
            patch.object(
                self.manager.database_loader, "load_time_series_from_esdl", return_value=self.failed
            ),
            patch.object(self.manager, "_load_from_xml", side_effect=RuntimeError("xml boom")),
        ):
            data, result = self.manager.load_time_series(self.es, xml_file="series.xml")

        self.assertEqual(data, {})
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["connection refused"])
        self.assertEqual(result.warnings, ["w1", "Failed to load time series from xml: xml boom"])

    def test_partial_database_result_is_returned_without_trying_xml(self) -> None:
        partial = (
            {"asset1|power": Mock()},
            ValidationResult(is_valid=False, errors=["one profile failed"]),
        )
        with (
            patch.object(
                self.manager.database_loader, "load_time_series_from_esdl", return_value=partial
            ),
            patch.object(self.manager, "_load_from_xml") as mock_xml,
        ):
            result = self.manager.load_time_series(self.es, xml_file="series.xml")

        self.assertIs(result, partial)
        mock_xml.assert_not_called()

    def test_failed_database_load_falls_back_to_dataframes_and_keeps_the_database_error(
        self,
    ) -> None:
        index = pd.date_range("2024-01-01", periods=3, freq="h")
        frames = {"asset0": pd.DataFrame({"heat_supplied": [1.0, 2.0, 3.0]}, index=index)}
        with patch.object(
            self.manager.database_loader, "load_time_series_from_esdl", return_value=self.failed
        ):
            data, result = self.manager.load_time_series(
                self.es, timeseries_dataframes=frames, source_priority=["database", "dataframes"]
            )

        self.assertEqual(list(data), [f"asset0{COMPOSITE_KEY_SEPARATOR}heat_supplied"])
        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.warnings,
            ["w1", "Database load failed, used another source: connection refused"],
        )

    def test_invalid_fallback_with_data_stays_invalid_and_gains_the_database_note(self) -> None:
        invalid_xml = (
            {"asset1|power": Mock()},
            ValidationResult(is_valid=False, errors=["xml err"], warnings=["xw"]),
        )
        (data, result), _ = self._load(xml=invalid_xml)

        self.assertEqual(data, invalid_xml[0])
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["xml err"])
        self.assertEqual(
            result.warnings,
            ["xw", "w1", "Database load failed, used another source: connection refused"],
        )


if __name__ == "__main__":
    unittest.main()
