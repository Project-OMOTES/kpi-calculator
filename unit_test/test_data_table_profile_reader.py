# unit_test/test_data_table_profile_reader.py
"""Tests for the DataTableProfile helpers (eligibility, validation, credential guard, reshape)."""

import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from esdl import esdl
from esdl.profiles.credentials import Credential, Credentials

from kpicalculator.adapters.data_table_profile_reader import (
    DataTableTarget,
    check_database_login,
    detached_copy,
    enable_autocommit,
    is_database_profile,
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

    def test_non_postgresql_configuration_types_rejected(self) -> None:
        for config_type in (
            esdl.DatabaseTypeEnum.INFLUXDB,
            esdl.DatabaseTypeEnum.UNDEFINED,
            esdl.DatabaseTypeEnum.MYSQL,
        ):
            with self.subTest(config_type=config_type):
                config = make_config(config_type=config_type, database="energy")
                with self.assertRaises(ValidationError) as ctx:
                    validate_data_table_profile(make_profile(config=config), "asset1")
                message = str(ctx.exception)
                self.assertIn("only POSTGRESQL DataTableProfiles are supported", message)
                self.assertIn("use InfluxDBProfile for InfluxDB", message)
                self.assertIn("asset1", message)

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

    def test_unset_port_is_not_defaulted(self) -> None:
        # pyESDL would default port 0 to 5432 and could match a host-only credential.
        with self.assertRaises(ValidationError) as ctx:
            validate_data_table_profile(make_profile(config=make_config(port=0)), "a1")
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

    def test_filter_that_pyesdl_would_silently_change_rejected(self) -> None:
        cases = (
            "\"a\"='x' OR \"b\"='y'",
            "\"a\"='x' or \"b\"='y'",
            "\"a\"='x' AND",
            "AND \"a\"='x'",
            "\"a\"='x' AND AND \"b\"='y'",
            "\"a\"='x' \"b\"='y'",
            "\"a\"='x' AND \"a\"='y'",
            "\"a\"='x' AND b=1",
        )
        for filter_ in cases:
            with self.subTest(filter_=filter_), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(filter_=filter_), "a1")
            self.assertIn("must be key='value' pairs joined by AND", str(ctx.exception))
            self.assertIn(filter_, str(ctx.exception))

    def test_filter_forms_read_as_written_accepted(self) -> None:
        # An OR inside a quoted value is data, not an operator. Mismatched quotes are accepted
        # because pyESDL parses them the same way; key case is significant in Postgres.
        cases = (
            "a='x OR y'",
            "\"a\"='x OR y'",
            "a='x'AND b='y'",
            "a='x' And b='y'",
            "a='x'\nAND\tb='y'",
            "a=''",
            "a_1='x'",
            "a='x',b='y'",
            "A='x' AND a='y'",
            "a=\"x'",
        )
        for filter_ in cases:
            with self.subTest(filter_=filter_):
                target = validate_data_table_profile(make_profile(filter_=filter_), "a1")
                self.assertEqual(target, DataTableTarget("pg.example.com", 5432))

    def test_filter_with_stray_separators_or_quotes_rejected(self) -> None:
        cases = (
            "a='x',",
            ",a='x'",
            "a='x' , , b='y'",
            "a='x' ANDb='y'",
            "a='x' ANDROID b='y'",
            'a="it\'s"',
            "x='a=\"b\"'",
        )
        for filter_ in cases:
            with self.subTest(filter_=filter_), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(filter_=filter_), "a1")
            self.assertIn("must be key='value' pairs joined by AND", str(ctx.exception))

    def test_padded_table_name_is_not_rejected(self) -> None:
        # Only a missing name is rejected; pyESDL quotes the identifier and the database
        # reports an unknown table.
        target = validate_data_table_profile(make_profile(table=" heat "), "a1")
        self.assertEqual(target, DataTableTarget("pg.example.com", 5432))

    def test_filter_joined_by_and_or_comma_accepted(self) -> None:
        cases = (
            "a='x'",
            "\"a\"='x' AND \"b\"='y' AND c='z'",
            "\"a\"='x' and \"b\"='y'",
            "  \"a\"='x' ,  \"b\"='y'  ",
        )
        for filter_ in cases:
            with self.subTest(filter_=filter_):
                target = validate_data_table_profile(make_profile(filter_=filter_), "a1")
                self.assertEqual(target.port, 5432)

    def test_blank_table_name_rejected(self) -> None:
        for table in (None, "", "   "):
            with self.subTest(table=table), self.assertRaises(ValidationError) as ctx:
                validate_data_table_profile(make_profile(table=table), "a1")  # type: ignore[arg-type]
            self.assertIn("has no tableName", str(ctx.exception))
            self.assertIn("asset a1", str(ctx.exception))

    def test_parsable_filter_accepted(self) -> None:
        profile = make_profile(filter_="\"assetId\"='abc' AND \"portId\"='p1'")
        self.assertEqual(validate_data_table_profile(profile, "a1").host, "pg.example.com")

    def test_empty_filter_accepted(self) -> None:
        self.assertEqual(validate_data_table_profile(make_profile(filter_=""), "a1").port, 5432)


class TestDetachedCopy(unittest.TestCase):
    """The read copy has no configuration id and leaves the caller's ESDL unchanged."""

    def test_copy_has_no_configuration_id(self) -> None:
        copy = detached_copy(make_profile())
        self.assertIsNone(copy.configuration.id)

    def test_original_profile_and_configuration_unchanged(self) -> None:
        profile = make_profile()
        configuration = profile.configuration
        detached_copy(profile)
        self.assertIs(profile.configuration, configuration)
        self.assertEqual(configuration.id, "cfg1")
        self.assertEqual(configuration.host, "pg.example.com")

    def test_copy_keeps_the_attributes_pyesdl_reads(self) -> None:
        profile = make_profile(
            table="tbl",
            filter_="a=1",
            schema="sch",
            multiplier=2.5,
            startDate=T0,
            endDate=T0 + HOUR,
            datetimeColumnName="ts",
            id="prof1",
        )
        profile.configuration.database = "energy"
        copy = detached_copy(profile)
        for name in (
            "tableName",
            "columnName",
            "datetimeColumnName",
            "filter",
            "schema",
            "multiplier",
            "id",
        ):
            with self.subTest(attribute=name):
                self.assertEqual(getattr(copy, name), getattr(profile, name))
        self.assertEqual(copy.startDate, T0)
        self.assertEqual(copy.endDate, T0 + HOUR)
        self.assertEqual(copy.configuration.host, "pg.example.com")
        self.assertEqual(copy.configuration.port, 5432)
        self.assertEqual(copy.configuration.database, "energy")
        self.assertEqual(copy.configuration.type, esdl.DatabaseTypeEnum.POSTGRESQL)

    def test_changing_the_copy_does_not_change_the_original(self) -> None:
        profile = make_profile()
        copy = detached_copy(profile)
        copy.configuration.host = "other.example.com"
        copy.columnName = "other"
        self.assertEqual(profile.configuration.host, "pg.example.com")
        self.assertEqual(profile.columnName, "HeatIn.Q")

    def test_configuration_id_colliding_with_a_registry_key_is_neutralised(self) -> None:
        saved = dict(Credentials.credentials_dict)
        self.addCleanup(self._restore, saved)
        Credentials.credentials_dict.clear()
        Credentials.add_credential("victim.example.com", "user", "secret")
        config = esdl.DatabaseConfiguration(
            id="victim.example.com",
            host="attacker.example.com",
            port=5432,
            type=esdl.DatabaseTypeEnum.POSTGRESQL,
        )
        self.assertIsNotNone(Credentials.get_credential(config))
        self.assertIsNone(
            Credentials.get_credential(detached_copy(make_profile(config=config)).configuration)
        )

    @staticmethod
    def _restore(saved: dict[str, Credential]) -> None:
        Credentials.credentials_dict.clear()
        Credentials.credentials_dict.update(saved)


class TestCheckDatabaseLogin(unittest.TestCase):
    """The guard judges the credential pyESDL will use for the configuration."""

    def setUp(self) -> None:
        self._saved = dict(Credentials.credentials_dict)
        Credentials.credentials_dict.clear()
        self.addCleanup(self._restore)
        self.config = make_config()

    def _restore(self) -> None:
        Credentials.credentials_dict.clear()
        Credentials.credentials_dict.update(self._saved)

    def test_complete_credential_under_host_port_accepted(self) -> None:
        Credentials.add_credential("pg.example.com:5432", "user", "secret")
        self.assertIsNone(check_database_login(self.config, allow_passwordless=False))

    def test_complete_credential_under_host_accepted_for_any_port(self) -> None:
        Credentials.add_credential("pg.example.com", "user", "secret")
        self.assertIsNone(check_database_login(self.config, allow_passwordless=False))

    def test_credential_for_another_host_does_not_count(self) -> None:
        Credentials.add_credential("other.example.com", "user", "secret")
        with self.assertRaises(CredentialError):
            check_database_login(self.config, allow_passwordless=False)

    def test_credential_for_another_port_does_not_count(self) -> None:
        Credentials.add_credential("pg.example.com:5433", "user", "secret")
        with self.assertRaises(CredentialError) as ctx:
            check_database_login(self.config, allow_passwordless=False)
        self.assertIn("pg.example.com:5432", str(ctx.exception))

    def test_credential_host_match_is_case_sensitive(self) -> None:
        # pyESDL looks the key up exactly, so the guard must not accept a differently cased host.
        Credentials.add_credential("PG.example.com", "user", "secret")
        with self.assertRaises(CredentialError):
            check_database_login(self.config, allow_passwordless=False)

    def test_whitespace_only_login_counts_as_complete_like_in_pyesdl(self) -> None:
        # pyESDL's own test is plain truthiness, so the guard must agree with it.
        Credentials.credentials_dict["pg.example.com"] = Credential(" ", " ")
        self.assertIsNone(check_database_login(self.config, allow_passwordless=False))

    def test_missing_credential_rejected_with_actionable_message(self) -> None:
        with self.assertRaises(CredentialError) as ctx:
            check_database_login(self.config, allow_passwordless=False)
        message = str(ctx.exception)
        self.assertIn("pg.example.com:5432", message)
        self.assertIn("'pg.example.com'", message)
        self.assertIn("DB_HOST, DB_USER and DB_PASSWORD", message)
        self.assertIn("first imported", message)
        self.assertNotIn("secret", message)

    def test_incomplete_credential_rejected(self) -> None:
        for username, password in (("user", ""), ("", "secret"), ("", ""), ("user", None)):
            with self.subTest(username=username, password=password):
                Credentials.credentials_dict["pg.example.com"] = Credential(username, password)  # type: ignore[arg-type]
                with self.assertRaises(CredentialError):
                    check_database_login(self.config, allow_passwordless=False)

    def test_incomplete_host_port_credential_hides_a_complete_host_credential(self) -> None:
        # pyESDL stops at the first key it finds, so it would connect without a login.
        Credentials.add_credential("pg.example.com:5432", "user", "")
        Credentials.add_credential("pg.example.com", "user", "secret")
        with self.assertRaises(CredentialError):
            check_database_login(self.config, allow_passwordless=False)

    def test_configuration_id_is_consulted_like_pyesdl(self) -> None:
        # The guard is run on the detached copy; on a configuration that still has an id,
        # the id match wins, exactly as in pyESDL.
        Credentials.add_credential("cfg1", "user", "secret")
        self.assertIsNone(check_database_login(self.config, allow_passwordless=False))

    def test_passwordless_flag_allows_a_missing_credential(self) -> None:
        warning = check_database_login(self.config, allow_passwordless=True)
        self.assertIsNotNone(warning)
        self.assertIn("pg.example.com:5432", warning)
        self.assertNotIn("ignored", warning)

    def test_passwordless_flag_warns_that_an_incomplete_credential_is_ignored(self) -> None:
        Credentials.add_credential("pg.example.com", "user", "")
        warning = check_database_login(self.config, allow_passwordless=True)
        self.assertIsNotNone(warning)
        self.assertIn("ignored", warning)

    def test_passwordless_flag_is_silent_with_a_complete_credential(self) -> None:
        Credentials.add_credential("pg.example.com", "user", "secret")
        self.assertIsNone(check_database_login(self.config, allow_passwordless=True))


class TestEnableAutocommit(unittest.TestCase):
    """The pyESDL connection for the profile is switched to autocommit."""

    MANAGER = "kpicalculator.adapters.data_table_profile_reader.PostgresqlDataTableManager"

    def _connection(self, manager: MagicMock, closed: bool = False) -> MagicMock:
        connection = manager.get_from_cache_or_create.return_value.connection
        connection.closed = closed
        connection.autocommit = False
        return connection

    def test_open_connection_switched_to_autocommit(self) -> None:
        profile = make_profile()
        with patch(self.MANAGER) as manager:
            connection = self._connection(manager)
            enable_autocommit(profile)

        manager.get_from_cache_or_create.assert_called_once_with(profile)
        self.assertTrue(connection.autocommit)

    def test_closed_connection_left_alone(self) -> None:
        with patch(self.MANAGER) as manager:
            connection = self._connection(manager, closed=True)
            enable_autocommit(make_profile())

        self.assertFalse(connection.autocommit)

    def test_missing_connection_is_left_for_pyesdl_to_report(self) -> None:
        with patch(self.MANAGER) as manager:
            manager.get_from_cache_or_create.return_value.connection = None
            profile = make_profile()
            self.assertIsNone(enable_autocommit(profile))

        manager.get_from_cache_or_create.assert_called_once_with(profile)


class TestReshapeRows(unittest.TestCase):
    """Rows to sorted hourly UTC float rows."""

    HEADER = ("datetime", "HeatIn.Q")

    def reshape(self, data: object, header: object = None) -> list[list[object]]:
        return reshape_rows(data, header or list(self.HEADER), "HeatIn.Q")  # type: ignore[arg-type]

    def test_happy_path(self) -> None:
        self.assertEqual(self.reshape(hourly([1.0, 2.0, 3.0])), hourly([1.0, 2.0, 3.0]))

    def test_single_row_series_accepted(self) -> None:
        self.assertEqual(self.reshape(hourly([1.0])), hourly([1.0]))

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

    def test_spring_forward_with_aware_timestamps_is_hourly_in_utc(self) -> None:
        # Amsterdam 2024-03-31: 01:00+01:00 is followed by 03:00+02:00, one hour later.
        aware = [
            [datetime(2024, 3, 31, 1, tzinfo=timezone(timedelta(hours=1))), 1.0],
            [datetime(2024, 3, 31, 3, tzinfo=timezone(timedelta(hours=2))), 2.0],
        ]
        rows = self.reshape(aware)
        self.assertEqual(
            [r[0] for r in rows], [datetime(2024, 3, 31, h, tzinfo=UTC) for h in (0, 1)]
        )

    def test_spring_forward_with_naive_wall_clock_rejected_as_a_gap(self) -> None:
        naive = [[datetime(2024, 3, 31, 1), 1.0], [datetime(2024, 3, 31, 3), 2.0]]
        with self.assertRaises(ValueError) as ctx:
            self.reshape(naive)
        self.assertIn("got 7200s", str(ctx.exception))

    def test_fall_back_with_naive_wall_clock_rejected_as_duplicate(self) -> None:
        naive = [
            [datetime(2024, 10, 27, 1), 1.0],
            [datetime(2024, 10, 27, 2), 2.0],
            [datetime(2024, 10, 27, 2), 3.0],
            [datetime(2024, 10, 27, 3), 4.0],
        ]
        with self.assertRaises(ValueError) as ctx:
            self.reshape(naive)
        self.assertIn("duplicate timestamp", str(ctx.exception))

    def test_date_without_time_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.reshape([[date(2024, 1, 1), 1.0]])
        self.assertIn("non-datetime timestamp: date", str(ctx.exception))

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
