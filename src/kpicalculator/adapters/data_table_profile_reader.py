# src/kpicalculator/adapters/data_table_profile_reader.py
"""Helpers for reading ``esdl.DataTableProfile`` database profiles.

The database access itself is done by pyESDL
(``esdl.profiles.profile_utils.load_profile_data_and_header``), which takes the login from
its own ``Credentials`` registry. This module holds the steps around that read: profile
eligibility, pre-read validation of the profile and its ``DatabaseConfiguration``, the
credential guard, the connection setup (``enable_autocommit``), and the reshaping of the
returned rows into a clean, hourly, UTC time series.
"""

import math
import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, NamedTuple

from esdl import esdl
from esdl.profiles.credentials import Credentials
from esdl.profiles.data_configurations.postgresql_datatable_manager import (
    PostgresqlDataTableManager,
)
from esdl.profiles.datatableprofilemanager import DataTableProfileManager

from ..common.constants import SECONDS_PER_HOUR
from ..exceptions import CredentialError, ValidationError
from ..security.input_validator import InputValidator

DATABASE_READ_LOCK_TIMEOUT_SECONDS = 300.0
"""How long a thread waits for ``DATABASE_READ_LOCK`` before giving up."""

DATABASE_READ_LOCK = threading.RLock()
"""Serialises this package's use of pyESDL's shared state (connection manager cache).

Held around the credential check plus each read, and around ``close_db_connections()``.
Take it with ``database_read_lock()``, which bounds the wait. The holder itself is not
bounded: a query that stalls after connecting keeps the lock until the database answers, so
set ``PGCONNECT_TIMEOUT`` for connection setup. The lock does not serialise other pyESDL
users in the process, and ``close_db_connections()`` also closes the connections they hold.
"""


@contextmanager
def database_read_lock() -> Iterator[None]:
    """Hold ``DATABASE_READ_LOCK`` for the block, waiting at most the configured timeout.

    Raises:
        TimeoutError: Another thread held the lock for ``DATABASE_READ_LOCK_TIMEOUT_SECONDS``.
    """
    if not DATABASE_READ_LOCK.acquire(timeout=DATABASE_READ_LOCK_TIMEOUT_SECONDS):
        raise TimeoutError(
            f"Timed out after {DATABASE_READ_LOCK_TIMEOUT_SECONDS:g}s waiting for another "
            f"database read in this process to finish"
        )
    try:
        yield
    finally:
        DATABASE_READ_LOCK.release()


class DataTableTarget(NamedTuple):
    """Validated connection target of a ``DataTableProfile``."""

    host: str
    port: int


def is_database_profile(profile: object) -> bool:
    """Return True if the profile is read from a database by the time series loader.

    ``InfluxDBProfile`` is always eligible. A ``DataTableProfile`` is eligible unless its
    ``profileType`` is OUTPUT or its ``configuration`` is something other than a
    ``DatabaseConfiguration``. A missing ``configuration`` stays eligible so that the
    loader reports it as an error instead of silently ignoring the profile.
    """
    if isinstance(profile, esdl.InfluxDBProfile):
        return True
    if isinstance(profile, esdl.DataTableProfile):
        if profile.profileType == esdl.ProfileTypeEnum.OUTPUT:
            return False
        return profile.configuration is None or isinstance(
            profile.configuration, esdl.DatabaseConfiguration
        )
    return False


def validate_data_table_profile(profile: esdl.DataTableProfile, asset_id: str) -> DataTableTarget:
    """Validate a ``DataTableProfile`` before any database access.

    Args:
        profile: The profile to validate.
        asset_id: Asset identifier used in error messages.

    Returns:
        The validated host and port.

    Raises:
        ValidationError: Missing configuration, host, port, table name or column name, a
            configuration type other than POSTGRESQL, or a filter that is not a list of
            ``key='value'`` pairs joined by AND.
        SecurityError: Host rejected by the host policy.
    """
    configuration = profile.configuration
    if configuration is None:
        raise ValidationError(
            f"DataTableProfile for asset {asset_id} (table '{profile.tableName}') has no "
            f"DatabaseConfiguration in EnergySystemInformation.dataconfigurations"
        )
    if configuration.type != esdl.DatabaseTypeEnum.POSTGRESQL:
        raise ValidationError(
            f"DatabaseConfiguration for asset {asset_id} (table '{profile.tableName}') has type "
            f"{configuration.type}; only POSTGRESQL DataTableProfiles are supported "
            f"(use InfluxDBProfile for InfluxDB)"
        )
    # An unset port reads as 0 (or None); pyESDL would default it to 5432 and could match
    # a host-only credential, so host and port must both be explicit.
    if not configuration.host or not configuration.port:
        raise ValidationError(
            f"DatabaseConfiguration for asset {asset_id} (table '{profile.tableName}') "
            f"must define both host and port"
        )
    # pyESDL builds its credential key from the raw host, so a padded host would never
    # match the credential registered for it.
    if configuration.host != configuration.host.strip():
        raise ValidationError(
            f"DatabaseConfiguration host '{configuration.host}' for asset {asset_id} "
            f"(table '{profile.tableName}') has surrounding whitespace"
        )
    InputValidator.validate_database_host(configuration.host)
    InputValidator.validate_database_port(configuration.port)

    if not profile.tableName or not profile.tableName.strip():
        raise ValidationError(
            f"DataTableProfile for asset {asset_id} (column '{profile.columnName}') has no "
            f"tableName; it is required to select the table"
        )
    if not profile.columnName or not profile.columnName.strip():
        raise ValidationError(
            f"DataTableProfile for asset {asset_id} (table '{profile.tableName}') has no "
            f"columnName; it is required to name the time series"
        )
    # The column name is the series key and the pyESDL column lookup; padding would match
    # no column.
    if profile.columnName != profile.columnName.strip():
        raise ValidationError(
            f"columnName '{profile.columnName}' of DataTableProfile for asset {asset_id} "
            f"(table '{profile.tableName}') has surrounding whitespace"
        )
    _validate_filter(profile, asset_id)
    return DataTableTarget(configuration.host, configuration.port)


def detached_copy(profile: esdl.DataTableProfile) -> esdl.DataTableProfile:
    """Return a copy of the profile whose configuration copy has no ``id``.

    pyESDL looks a credential up by ``configuration.id`` first, then ``host:port``, then
    ``host``. The id comes from the ESDL file, so an id equal to a registry key would pick
    that key's login for an unrelated host. The read therefore runs on this copy. Only
    plain attributes are copied; the caller's profile and configuration stay unchanged
    (``copy.copy`` is not used because it shares state with the original).
    """
    configuration = _copy_attributes(profile.configuration, id=None)
    return _copy_attributes(profile, configuration=configuration)


def _copy_attributes(source: Any, **overrides: Any) -> Any:
    """Return a new object of the same class holding the source's single-valued attributes."""
    target = type(source)()
    for attribute in source.eClass.eAllAttributes():
        if not attribute.many and source.eIsSet(attribute):
            setattr(target, attribute.name, getattr(source, attribute.name))
    for name, value in overrides.items():
        setattr(target, name, value)
    return target


def check_database_login(
    configuration: esdl.DatabaseConfiguration, *, allow_passwordless: bool
) -> str | None:
    """Require the login that pyESDL will use for this configuration to be complete.

    pyESDL connects without a user or password unless the credential it finds has both,
    and libpq then falls back to ``PGUSER``, ``PGPASSWORD``, ``.pgpass``, ``PGSERVICE`` or
    trust authentication. The check looks the credential up the way pyESDL does, so it
    judges the credential pyESDL will use. Call it under ``DATABASE_READ_LOCK`` with the
    configuration of the ``detached_copy``.

    Args:
        configuration: Configuration of the profile copy that is about to be read.
        allow_passwordless: Proceed without a complete login instead of failing.

    Returns:
        A warning to log when the read goes ahead without a complete login, else None.

    Raises:
        CredentialError: No complete login is registered and ``allow_passwordless`` is False.
    """
    credential = Credentials.get_credential(configuration)
    if credential is not None and credential.username and credential.password:
        return None
    host, port = configuration.host, configuration.port
    if allow_passwordless:
        incomplete = (
            "; the registered credential has no username or no password and is ignored"
            if credential is not None
            else ""
        )
        return f"Reading {host}:{port} without a complete login{incomplete}"
    raise CredentialError(
        f"No complete database login registered for {host}:{port}. Register a username and "
        f"password with pyESDL under '{host}:{port}' or '{host}' (Credentials.add_credential), "
        f"or set DB_HOST, DB_USER and DB_PASSWORD before esdl.profiles.credentials is first "
        f"imported. The registry is shared by the whole process."
    )


def enable_autocommit(profile: esdl.DataTableProfile) -> None:
    """Switch the pyESDL connection that will serve this profile to autocommit.

    pyESDL keeps one connection per host, port, database and login and, with
    ``close_connection_after_load=False``, reuses it for the next profile. Outside
    autocommit every statement runs in one open transaction, and a failed statement (pyESDL
    swallows a failed ``datatable_metadata`` lookup) leaves that transaction aborted, so
    every later read on the connection fails with ``InFailedSqlTransaction``. In autocommit
    each statement stands alone. The setting applies to the shared connection until
    ``close_db_connections()``. Call it under ``DATABASE_READ_LOCK`` before the read; a
    connection that could not be opened is left for pyESDL to report.
    """
    connection = PostgresqlDataTableManager.get_from_cache_or_create(profile).connection
    if connection is not None and not connection.closed:
        connection.autocommit = True


# The key='value' pattern of pyESDL's DataTableProfileManager._parse_profile_filter.
_FILTER_PAIR = re.compile(r"\"?(\w+)\"?\s*=\s*[\"']([^\"']*)[\"']")
_FILTER_JOINER = re.compile(r"\s*(?:AND|,)\s*", re.IGNORECASE)


def _validate_filter(profile: esdl.DataTableProfile, asset_id: str) -> None:
    """Reject a non-empty filter that is not ``key='value'`` pairs joined by AND.

    pyESDL extracts the pairs with a regex and ignores all other text, so ``a='x' OR b='y'``
    would be read as ``a='x' AND b='y'``, a dangling AND would be dropped, and a repeated key
    would keep only its last value. Any of these would read other rows than the ESDL author
    intended, so they are rejected here. A comma is accepted as a joiner like AND.
    """
    if not profile.filter:
        return
    subject = f"Filter '{profile.filter}' of DataTableProfile for asset {asset_id}"
    if DataTableProfileManager._parse_profile_filter(profile.filter, as_dict=True) is None:
        raise ValidationError(f"{subject} (table '{profile.tableName}') cannot be parsed")

    pairs = list(_FILTER_PAIR.finditer(profile.filter))
    keys = [pair.group(1) for pair in pairs]
    before = profile.filter[: pairs[0].start()]
    after = profile.filter[pairs[-1].end() :]
    between = [profile.filter[a.end() : b.start()] for a, b in pairwise(pairs)]
    if (
        before.strip()
        or after.strip()
        or not all(_FILTER_JOINER.fullmatch(text) for text in between)
        or len(set(keys)) != len(keys)
    ):
        raise ValidationError(
            f"{subject} (table '{profile.tableName}') must be key='value' pairs joined by AND; "
            f"OR, a dangling AND and a repeated key are not supported"
        )


def _coerce_value(value: Any) -> float:
    """Coerce one database value (float, int, Decimal) to float; NULL becomes NaN."""
    return math.nan if value is None else float(value)


def _to_utc(timestamp: Any, column_name: str) -> datetime:
    """Normalise a timestamp to UTC; naive timestamps are taken to be UTC already.

    A ``timestamp without time zone`` column that holds local time is therefore mislabelled as
    UTC. Only a DST transition inside the data is caught, by the hourly-spacing check.
    """
    if not isinstance(timestamp, datetime):
        raise ValueError(
            f"Column '{column_name}' has a non-datetime timestamp: {type(timestamp).__name__}"
        )
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _check_hourly(rows: Sequence[tuple[datetime, float]], column_name: str) -> None:
    """Require strictly increasing, exactly hourly spacing in time-sorted rows."""
    for (previous, _), (current, _) in pairwise(rows):
        spacing = current - previous
        if spacing == timedelta(0):
            raise ValueError(
                f"Column '{column_name}' has duplicate timestamp {current.isoformat()}; "
                f"the profile filter may not have been applied"
            )
        if spacing != timedelta(seconds=SECONDS_PER_HOUR):
            seconds = f"{spacing.total_seconds():.6f}".rstrip("0").rstrip(".")
            raise ValueError(
                f"Expected {SECONDS_PER_HOUR}s time resolution, got {seconds}s "
                f"for column '{column_name}' at {current.isoformat()}"
            )


def reshape_rows(
    data: Sequence[Sequence[Any]] | None, header: Sequence[Any] | None, column_name: str
) -> list[list[Any]]:
    """Turn raw ``[datetime, value]`` rows into sorted, hourly, UTC ``[datetime, float]`` rows.

    Args:
        data: Rows as returned by pyESDL, datetime first.
        header: Column names as returned by pyESDL; must hold exactly the datetime column
            and one value column.
        column_name: Name of the value column, used in error messages.

    Returns:
        Rows sorted by timestamp, UTC-aware, with float values.

    Raises:
        ValueError: No rows, a header other than datetime plus one value column, NULL, NaN,
            infinite or non-numeric values, non-datetime timestamps, duplicate timestamps
            or non-hourly spacing.
    """
    if not data:
        raise ValueError(f"No data returned for column '{column_name}'")
    if header is None or len(header) != 2:
        raise ValueError(
            f"Expected exactly one value column for '{column_name}', got header {header}"
        )
    parsed: list[tuple[datetime, float]] = []
    for row in data:
        if len(row) != 2:
            raise ValueError(f"Row has {len(row)} fields, expected 2, for '{column_name}'")
        parsed.append((_to_utc(row[0], column_name), _coerce_value(row[1])))
    invalid_count = sum(1 for _, value in parsed if not math.isfinite(value))
    if invalid_count:
        raise ValueError(
            f"Column '{column_name}' contains {invalid_count} NULL/NaN/infinite value(s) "
            f"out of {len(parsed)}"
        )
    parsed.sort(key=lambda item: item[0])
    _check_hourly(parsed, column_name)
    return [[timestamp, value] for timestamp, value in parsed]
