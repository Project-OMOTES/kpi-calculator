# unit_test/test_data_table_profile_reader.py
"""Tests for the pure DataTableProfile helpers (eligibility, validation, reshape)."""

import threading
import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from esdl import esdl
from esdl.profiles.credentials import Credential, Credentials

from kpicalculator.adapters.data_table_profile_reader import (
    DataTableTarget,
    is_database_profile,
    registered_credential,
    require_honoured_tls,
    reshape_rows,
    validate_data_table_profile,
)
from kpicalculator.exceptions import CredentialError, SecurityError, ValidationError
from kpicalculator.security.input_validator import InputValidator

T0 = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def make_config(
    host: str | None = "pg.example.com",
    port: int | None = 5432,
    config_type: esdl.DatabaseTypeEnum = esdl.DatabaseTypeEnum.POSTGRESQL,
    database: str | None = None,
) -> esdl.DatabaseConfiguration:
    """Return a real DatabaseConfiguration."""
    return esdl.DatabaseConfiguration(
        id="cfg1", host=host, port=port, type=config_type, database=database
    )


def make_profile(
    config: object = "default",
    column: str | None = "HeatIn.Q",
    table: str = "tbl",
    filter_: str | None = None,
    **kwargs: object,
) -> esdl.DataTableProfile:
    """Return a real DataTableProfile; config="default" attaches a valid database config."""
    profile = esdl.DataTableProfile(tableName=table, columnName=column, filter=filter_, **kwargs)
    profile.configuration = make_config() if config == "default" else config
    return profile


def hourly(values: list[object]) -> list[list[object]]:
    """Rows [datetime, value] with hourly spacing starting at T0."""
    return [[T0 + i * HOUR, v] for i, v in enumerate(values)]


class TestIsDatabaseProfile(unittest.TestCase):
    """Eligibility predicate."""

    def test_influx_profile_is_eligible(self) -> None:
        self.assertTrue(is_database_profile(esdl.InfluxDBProfile(measurement="m", field="f")))

    def test_data_table_profile_with_database_configuration_is_eligible(self) -> None:
        self.assertTrue(is_database_profile(make_profile()))

    def test_data_table_profile_without_configuration_is_eligible(self) -> None:
        self.assertTrue(is_database_profile(make_profile(config=None)))

    def test_input_and_undefined_profile_types_are_eligible(self) -> None:
        for profile_type in (esdl.ProfileTypeEnum.INPUT, esdl.ProfileTypeEnum.UNDEFINED):
            with self.subTest(profile_type=profile_type):
                self.assertTrue(is_database_profile(make_profile(profileType=profile_type)))

    def test_output_profile_not_eligible_whatever_the_configuration(self) -> None:
        for config in (None, esdl.FileConfiguration(uri="x.csv"), make_config()):
            with self.subTest(config=type(config).__name__):
                profile = make_profile(config=config, profileType=esdl.ProfileTypeEnum.OUTPUT)
                self.assertFalse(is_database_profile(profile))

    def test_file_configuration_is_not_eligible(self) -> None:
        profile = make_profile(config=esdl.FileConfiguration(uri="x.csv"))
        self.assertFalse(is_database_profile(profile))

    def test_other_profile_kinds_are_not_eligible(self) -> None:
        for other in (esdl.TimeSeriesProfile(), esdl.DateTimeProfile(), esdl.ProfileReference()):
            with self.subTest(kind=type(other).__name__):
                self.assertFalse(is_database_profile(other))

    def test_non_profile_objects_are_not_eligible(self) -> None:
        self.assertFalse(is_database_profile(None))
        self.assertFalse(is_database_profile(esdl.Pipe()))
        self.assertFalse(is_database_profile("profile"))


class TestValidateDataTableProfile(unittest.TestCase):
    """Pre-read validation of profile and configuration."""

    def test_influxdb_configuration_without_database_rejected(self) -> None:
        for database in (None, ""):
            with self.subTest(database=database):
                config = make_config(config_type=esdl.DatabaseTypeEnum.INFLUXDB, database=database)
                with self.assertRaises(ValidationError) as ctx:
                    validate_data_table_profile(make_profile(config=config), "asset1")
                self.assertIn("INFLUXDB but names no database", str(ctx.exception))
                self.assertIn("asset1", str(ctx.exception))

    def test_influxdb_configuration_with_database_accepted(self) -> None:
        config = make_config(config_type=esdl.DatabaseTypeEnum.INFLUXDB, database="energy")
        target = validate_data_table_profile(make_profile(config=config), "asset1")
        self.assertEqual(target, DataTableTarget("pg.example.com", 5432))

    def test_postgresql_configuration_without_database_accepted(self) -> None:
        for database in (None, ""):
            with self.subTest(database=database):
                config = make_config(database=database)
                target = validate_data_table_profile(make_profile(config=config), "asset1")
                self.assertEqual(target, DataTableTarget("pg.example.com", 5432))

    def test_valid_profile_returns_target(self) -> None:
        target = validate_data_table_profile(make_profile(), "asset1")
        self.assertEqual(target, DataTableTarget("pg.example.com", 5432))

    def test_missing_configuration_names_asset_and_dataconfigurations(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_data_table_profile(make_profile(config=None), "asset1")
        message = str(ctx.exception)
        self.assertIn("asset1", message)
        self.assertIn(
            "no DatabaseConfiguration in EnergySystemInformation.dataconfigurations", message
        )

    def test_missing_host_rejected(self) -> None:
        for host in (None, ""):
            with self.subTest(host=host), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(config=make_config(host=host)), "a1")
            self.assertIn("both host and port", str(ctx.exception))

    def test_missing_port_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_data_table_profile(make_profile(config=make_config(port=None)), "a1")
        self.assertIn("both host and port", str(ctx.exception))

    def test_invalid_host_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_data_table_profile(make_profile(config=make_config(host="bad host!")), "a1")
        self.assertIn("Invalid hostname or IP address format", str(ctx.exception))

    def test_localhost_rejected_outside_development_mode(self) -> None:
        profile = make_profile(config=make_config(host="localhost"))
        with (
            patch.object(InputValidator, "_is_development_mode", return_value=False),
            self.assertRaises(SecurityError) as ctx,
        ):
            validate_data_table_profile(profile, "a1")
        self.assertIn("Localhost access is disallowed", str(ctx.exception))

    def test_dangerous_port_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            validate_data_table_profile(make_profile(config=make_config(port=22)), "a1")
        self.assertIn("Port 22 is not typically used for databases", str(ctx.exception))

    def test_host_with_surrounding_whitespace_rejected(self) -> None:
        # pyESDL builds its credential key from the raw host, so a padded host would never
        # match the credential registered for it.
        for host in (
            " pg.example.com",
            "pg.example.com ",
            " pg.example.com ",
            "  ",
            "\tpg.example.com",
            "pg.example.com\n",
            "\r\n",
        ):
            with self.subTest(host=host), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(config=make_config(host=host)), "a1")
            self.assertIn("surrounding whitespace", str(ctx.exception))

    def test_missing_column_name_rejected(self) -> None:
        for column in (None, "", "   ", "\t", "\n"):
            with self.subTest(column=column), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(column=column), "a1")
            self.assertIn("no columnName", str(ctx.exception))

    def test_column_name_with_surrounding_whitespace_rejected(self) -> None:
        # The column name becomes the series key and the pyESDL column lookup, so a padded
        # name would silently match nothing.
        for column in (" HeatIn.Q", "HeatIn.Q ", "\tHeatIn.Q"):
            with self.subTest(column=column), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(column=column), "a1")
            self.assertIn("surrounding whitespace", str(ctx.exception))

    def test_unparsable_filter_rejected(self) -> None:
        for filter_ in ("not a filter", "   "):
            with self.subTest(filter_=filter_), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(filter_=filter_), "a1")
            self.assertIn("cannot be parsed", str(ctx.exception))

    def test_parsable_filter_accepted(self) -> None:
        profile = make_profile(filter_="\"assetId\"='abc' AND \"portId\"='p1'")
        self.assertEqual(validate_data_table_profile(profile, "a1").host, "pg.example.com")

    def test_empty_filter_accepted(self) -> None:
        self.assertEqual(validate_data_table_profile(make_profile(filter_=""), "a1").port, 5432)


class TestRequireHonouredTls(unittest.TestCase):
    """TLS requirements pyESDL cannot be told about are rejected unless guaranteed anyway."""

    def test_postgres_requirements_follow_pgsslmode(self) -> None:
        config = make_config()
        # (ssl, verify_ssl, PGSSLMODE, accepted)
        cases = [
            (False, False, None, True),
            (False, False, "disable", True),
            (True, False, None, False),
            (True, False, "prefer", False),
            (True, False, "require", True),
            (True, False, "verify-ca", True),
            (True, False, "VERIFY-FULL", True),
            (False, True, "require", False),
            (False, True, "verify-ca", True),
            (True, True, "verify-full", True),
            (True, True, "require", False),
        ]
        for ssl, verify_ssl, mode, accepted in cases:
            with self.subTest(ssl=ssl, verify_ssl=verify_ssl, mode=mode):
                env = {} if mode is None else {"PGSSLMODE": mode}
                with patch.dict("os.environ", env, clear=True):
                    if accepted:
                        require_honoured_tls(config, ssl, verify_ssl)
                    else:
                        with self.assertRaisesRegex(CredentialError, "PGSSLMODE"):
                            require_honoured_tls(config, ssl, verify_ssl)

    def test_postgres_requirement_rejected_when_a_service_file_may_override_pgsslmode(
        self,
    ) -> None:
        env = {"PGSSLMODE": "verify-full", "PGSERVICE": "svc"}
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaisesRegex(CredentialError, "unset PGSERVICE"):
                require_honoured_tls(make_config(), True, False)
            # No requirement, nothing to guarantee.
            require_honoured_tls(make_config(), False, False)

    def test_influxdb_requirements_follow_pyesdl_tls_rule(self) -> None:
        # (host, port, accepted): pyESDL uses TLS for port 443 or an "https" host.
        cases = [
            ("influx.example.com", 443, True),
            ("https://influx.example.com", 8086, True),
            ("influx.example.com", 8086, False),
        ]
        for host, port, accepted in cases:
            with self.subTest(host=host, port=port):
                config = make_config(
                    host=host,
                    port=port,
                    config_type=esdl.DatabaseTypeEnum.INFLUXDB,
                    database="energy",
                )
                # PGSSLMODE must not matter for INFLUXDB-typed reads.
                with patch.dict("os.environ", {"PGSSLMODE": "verify-full"}, clear=True):
                    if accepted:
                        require_honoured_tls(config, True, True)
                    else:
                        with self.assertRaisesRegex(CredentialError, "https host or port 443"):
                            require_honoured_tls(config, True, False)


class TestRegisteredCredential(unittest.TestCase):
    """Credential registration is scoped to the with block."""

    KEY = "pg.example.com:5432"

    def setUp(self) -> None:
        self._saved = dict(Credentials.credentials_dict)
        Credentials.credentials_dict.pop(self.KEY, None)

    def tearDown(self) -> None:
        Credentials.credentials_dict.clear()
        Credentials.credentials_dict.update(self._saved)

    def test_registered_inside_and_removed_after(self) -> None:
        with registered_credential("pg.example.com", 5432, "user", "password1"):
            self.assertEqual(
                Credentials.credentials_dict[self.KEY], Credential("user", "password1")
            )
        self.assertNotIn(self.KEY, Credentials.credentials_dict)

    def test_removed_after_exception(self) -> None:
        with (
            self.assertRaises(RuntimeError),
            registered_credential("pg.example.com", 5432, "user", "password1"),
        ):
            raise RuntimeError("read failed")
        self.assertNotIn(self.KEY, Credentials.credentials_dict)

    def test_previous_value_restored(self) -> None:
        previous = Credential("old", "oldpassword")
        Credentials.credentials_dict[self.KEY] = previous
        with registered_credential("pg.example.com", 5432, "user", "password1"):
            self.assertEqual(Credentials.credentials_dict[self.KEY].username, "user")
        self.assertIs(Credentials.credentials_dict[self.KEY], previous)

    def test_previous_value_restored_after_exception(self) -> None:
        previous = Credential("old", "oldpassword")
        Credentials.credentials_dict[self.KEY] = previous
        with (
            self.assertRaises(RuntimeError),
            registered_credential("pg.example.com", 5432, "user", "password1"),
        ):
            raise RuntimeError("read failed")
        self.assertIs(Credentials.credentials_dict[self.KEY], previous)

    def test_add_credential_failure_leaves_registry_unchanged(self) -> None:
        previous = Credential("old", "oldpassword")
        Credentials.credentials_dict[self.KEY] = previous

        def add_partially_then_fail(*_args: object, **_kwargs: object) -> None:
            Credentials.credentials_dict[self.KEY] = Credential("partial", "partialpw")
            raise RuntimeError("add failed")

        with (
            patch.object(Credentials, "add_credential", side_effect=add_partially_then_fail),
            self.assertRaises(RuntimeError),
            registered_credential("pg.example.com", 5432, "user", "password1"),
        ):
            self.fail("body must not run when registration fails")
        self.assertIs(Credentials.credentials_dict[self.KEY], previous)

    def test_concurrent_registration_of_same_key_is_serialised(self) -> None:
        other_entered = threading.Event()

        def register_other() -> None:
            with registered_credential("pg.example.com", 5432, "other", "otherpassword"):
                other_entered.set()

        with registered_credential("pg.example.com", 5432, "user", "password1"):
            thread = threading.Thread(target=register_other)
            thread.start()
            self.assertFalse(other_entered.wait(timeout=0.2))
            self.assertEqual(Credentials.credentials_dict[self.KEY].username, "user")
        thread.join(timeout=5)

        self.assertTrue(other_entered.is_set())
        self.assertNotIn(self.KEY, Credentials.credentials_dict)

    def test_other_keys_untouched(self) -> None:
        Credentials.credentials_dict["other.example.com"] = Credential("o", "otherpassword")
        with registered_credential("pg.example.com", 5432, "user", "password1"):
            pass
        self.assertEqual(Credentials.credentials_dict["other.example.com"].username, "o")


class TestReshapeRows(unittest.TestCase):
    """Rows to sorted hourly UTC float rows."""

    HEADER = ("datetime", "HeatIn.Q")

    def reshape(self, data: object, header: object = None) -> list[list[object]]:
        return reshape_rows(data, header or list(self.HEADER), "HeatIn.Q")  # type: ignore[arg-type]

    def test_happy_path(self) -> None:
        self.assertEqual(self.reshape(hourly([1.0, 2.0, 3.0])), hourly([1.0, 2.0, 3.0]))

    def test_decimal_and_int_coerced_to_float(self) -> None:
        rows = self.reshape(hourly([Decimal("1.5"), 2, Decimal("3")]))
        self.assertEqual([r[1] for r in rows], [1.5, 2.0, 3.0])
        self.assertTrue(all(type(r[1]) is float for r in rows))

    def test_null_value_rejected_with_column_and_count(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.reshape(hourly([1.0, None, None, 4.0]))
        message = str(ctx.exception)
        self.assertIn("HeatIn.Q", message)
        self.assertIn("2 NULL/NaN/infinite value(s) out of 4", message)

    def test_non_numeric_value_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.reshape(hourly([1.0, "abc"]))
        self.assertIn("could not convert string to float: 'abc'", str(ctx.exception))

    def test_empty_rows_rejected(self) -> None:
        empty_inputs: list[object] = [[], None]
        for data in empty_inputs:
            with self.subTest(data=data), self.assertRaises(ValueError) as ctx:
                self.reshape(data)
            self.assertIn("No data returned for column 'HeatIn.Q'", str(ctx.exception))

    def test_header_without_exactly_one_value_column_rejected(self) -> None:
        for header in (["datetime", "a", "b"], ["datetime"], None):
            with self.subTest(header=header), self.assertRaises(ValueError) as ctx:
                reshape_rows(hourly([1.0]), header, "HeatIn.Q")
            self.assertIn("exactly one value column", str(ctx.exception))

    def test_row_width_mismatch_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.reshape([[T0, 1.0, 2.0]])
        self.assertIn("Row has 3 fields, expected 2, for 'HeatIn.Q'", str(ctx.exception))

    def test_unordered_rows_sorted(self) -> None:
        rows = hourly([1.0, 2.0, 3.0])
        shuffled = [rows[2], rows[0], rows[1]]
        self.assertEqual(self.reshape(shuffled), rows)

    def test_duplicate_timestamps_rejected(self) -> None:
        rows = hourly([1.0, 2.0])
        with self.assertRaises(ValueError) as ctx:
            self.reshape([rows[0], rows[0], rows[1]])
        self.assertIn("duplicate timestamp", str(ctx.exception))

    def test_hourly_spacing_must_be_exact(self) -> None:
        for offset in (3599, 3601, 1800, 3600.5, 0.5, 3600.000001, 3599.999999):
            with self.subTest(offset=offset), self.assertRaises(ValueError) as ctx:
                self.reshape([[T0, 1.0], [T0 + timedelta(seconds=offset), 2.0]])
            self.assertIn(f"Expected 3600s time resolution, got {offset}s", str(ctx.exception))
        exact = [[T0, 1.0], [T0 + timedelta(seconds=3600), 2.0]]
        self.assertEqual(self.reshape(exact), hourly([1.0, 2.0]))

    def test_infinite_value_rejected(self) -> None:
        non_finite = (
            float("nan"),
            float("inf"),
            float("-inf"),
            Decimal("Infinity"),
            Decimal("NaN"),
        )
        for value in non_finite:
            with self.subTest(value=value), self.assertRaises(ValueError) as ctx:
                self.reshape(hourly([1.0, value]))
            self.assertIn(
                "Column 'HeatIn.Q' contains 1 NULL/NaN/infinite value(s) out of 2",
                str(ctx.exception),
            )

    def test_short_rows_rejected_and_tuple_rows_accepted(self) -> None:
        for short_row in ([], [T0]):
            with self.subTest(row=short_row), self.assertRaises(ValueError) as ctx:
                self.reshape([short_row])
            self.assertIn("expected 2", str(ctx.exception))
        tuples = [(T0, 1.0), (T0 + HOUR, 2.0)]
        self.assertEqual(self.reshape(tuples), hourly([1.0, 2.0]))

    def test_gap_in_series_rejected(self) -> None:
        rows = [[T0, 1.0], [T0 + HOUR, 2.0], [T0 + 3 * HOUR, 3.0]]
        with self.assertRaises(ValueError) as ctx:
            self.reshape(rows)
        self.assertIn("got 7200s", str(ctx.exception))

    def test_non_datetime_timestamp_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.reshape([["2024-01-01", 1.0]])
        self.assertIn("non-datetime timestamp", str(ctx.exception))

    def test_naive_timestamps_treated_as_utc(self) -> None:
        naive = [[datetime(2024, 1, 1, 0), 1.0], [datetime(2024, 1, 1, 1), 2.0]]
        rows = self.reshape(naive)
        self.assertEqual(rows, hourly([1.0, 2.0]))
        for row in rows:
            self.assertEqual(row[0].utcoffset(), timedelta(0))  # type: ignore[attr-defined]

    def test_aware_timestamps_normalised_to_utc(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        aware = [
            [datetime(2024, 1, 1, 2, tzinfo=plus_two), 1.0],
            [datetime(2024, 1, 1, 3, tzinfo=plus_two), 2.0],
        ]
        rows = self.reshape(aware)
        self.assertEqual(rows, hourly([1.0, 2.0]))
        for row in rows:
            self.assertEqual(row[0].utcoffset(), timedelta(0))  # type: ignore[attr-defined]

    def test_mixed_naive_and_aware_equal_instants_are_duplicates(self) -> None:
        rows = [[datetime(2024, 1, 1), 1.0], [T0, 2.0]]
        with self.assertRaises(ValueError) as ctx:
            self.reshape(rows)
        self.assertIn("duplicate timestamp", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
