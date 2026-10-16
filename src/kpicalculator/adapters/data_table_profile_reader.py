# src/kpicalculator/adapters/data_table_profile_reader.py
"""Pure helpers for reading ``esdl.DataTableProfile`` database profiles.

The database access itself is done by pyESDL
(``esdl.profiles.profile_utils.load_profile_data_and_header``). This module holds the
parts that need no connection: profile eligibility, pre-read validation of the profile
and its ``DatabaseConfiguration``, the temporary credential registration, and the
reshaping of the returned rows into a clean, hourly, UTC time series.
"""

import math
import os
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, NamedTuple

from esdl import esdl
from esdl.profiles.credentials import Credential, Credentials
from esdl.profiles.datatableprofilemanager import DataTableProfileManager

from ..common.constants import DEFAULT_DATABASE_SSL_PORT, SECONDS_PER_HOUR
from ..exceptions import CredentialError, ValidationError
from ..security.input_validator import InputValidator

DATABASE_READ_LOCK = threading.RLock()
"""Serialises use of pyESDL's process-wide state (credential registry, open connections).

Held for the whole network read, without a timeout: a hung host blocks other DataTable
reads and the connection cleanup in the same process.
"""


_TLS_SSLMODES = ("require", "verify-ca", "verify-full")
_VERIFYING_SSLMODES = ("verify-ca", "verify-full")


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
        ValidationError: Missing configuration, host, port or column name, an INFLUXDB
            configuration without a database, or an unparsable filter.
        SecurityError: Host rejected by the host policy.
    """
    configuration = profile.configuration
    if configuration is None:
        raise ValidationError(
            f"DataTableProfile for asset {asset_id} (table '{profile.tableName}') has no "
            f"DatabaseConfiguration in EnergySystemInformation.dataconfigurations"
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
    # pyESDL would try to create an Influx database from an empty name. For POSTGRESQL an
    # empty database name selects the server default, so it is not checked there.
    if configuration.type == esdl.DatabaseTypeEnum.INFLUXDB and not configuration.database:
        raise ValidationError(
            f"DatabaseConfiguration for asset {asset_id} (table '{profile.tableName}') is of "
            f"type INFLUXDB but names no database"
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


def require_honoured_tls(
    configuration: esdl.DatabaseConfiguration, ssl: bool, verify_ssl: bool
) -> None:
    """Reject a TLS requirement that the pyESDL read cannot honour.

    pyESDL's credentials carry only a username and password, so ``ssl`` and ``verify_ssl``
    cannot be passed on. Postgres reads use libpq's ``sslmode``, which pyESDL leaves to
    libpq: the ``PGSSLMODE`` environment variable, or a service file selected by
    ``PGSERVICE``, whose values override it. The default, ``prefer``, may fall back to
    plaintext. A requirement is therefore accepted only when ``PGSSLMODE`` guarantees it
    and ``PGSERVICE`` is unset. INFLUXDB-typed reads use TLS, with verification, when the
    host contains "https" or the port is 443.

    Raises:
        CredentialError: ``ssl`` or ``verify_ssl`` is requested but not guaranteed.
    """
    if not (ssl or verify_ssl):
        return
    if configuration.type == esdl.DatabaseTypeEnum.INFLUXDB:
        if "https" in configuration.host or configuration.port == DEFAULT_DATABASE_SSL_PORT:
            return
        remedy = f"use an https host or port {DEFAULT_DATABASE_SSL_PORT}"
    else:
        mode = os.environ.get("PGSSLMODE", "").strip().lower()
        accepted = _VERIFYING_SSLMODES if verify_ssl else _TLS_SSLMODES
        if os.environ.get("PGSERVICE"):
            remedy = (
                f"unset PGSERVICE (its service file can override PGSSLMODE) and set "
                f"PGSSLMODE to one of {', '.join(accepted)}"
            )
        elif mode in accepted:
            return
        else:
            remedy = f"set PGSSLMODE to one of {', '.join(accepted)}"
    raise CredentialError(
        f"Credentials for {configuration.host}:{configuration.port} require "
        f"{'verified ' if verify_ssl else ''}TLS, which pyESDL cannot be told to use; "
        f"{remedy}, or remove ssl/verify_ssl from the credentials"
    )


def _validate_filter(profile: esdl.DataTableProfile, asset_id: str) -> None:
    """Reject a non-empty filter that pyESDL cannot parse (it would drop the filter)."""
    if (
        profile.filter
        and DataTableProfileManager._parse_profile_filter(profile.filter, as_dict=True) is None
    ):
        raise ValidationError(
            f"Filter '{profile.filter}' of DataTableProfile for asset {asset_id} "
            f"(table '{profile.tableName}') cannot be parsed"
        )


@contextmanager
def registered_credential(host: str, port: int, username: str, password: str) -> Iterator[None]:
    """Register a credential under ``host:port`` with pyESDL and restore the registry on exit.

    ``Credentials.credentials_dict`` is process-wide, so the previous entry for the key (or
    its absence) is put back after the ``with`` block, also when the block raises.
    ``DATABASE_READ_LOCK`` is held for the whole block, so concurrent loads in one process
    cannot read or restore each other's credential.
    """
    key = f"{host}:{port}"
    with DATABASE_READ_LOCK:
        registry = Credentials.credentials_dict
        previous: Credential | None = registry.get(key)
        try:
            Credentials.add_credential(key, username, password)
            yield
        finally:
            if previous is None:
                registry.pop(key, None)
            else:
                registry[key] = previous


def _coerce_value(value: Any) -> float:
    """Coerce one database value (float, int, Decimal) to float; NULL becomes NaN."""
    return math.nan if value is None else float(value)


def _to_utc(timestamp: Any, column_name: str) -> datetime:
    """Normalise a timestamp to UTC; naive timestamps are taken to be UTC already."""
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
