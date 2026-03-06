# src/kpicalculator/common/constants.py
"""Constants used throughout the KPI Calculator application."""

from types import MappingProxyType

# Time conversion constants
SECONDS_PER_HOUR = 3600
HOURS_PER_DAY = 24
DAYS_PER_YEAR = 365
SECONDS_PER_DAY = SECONDS_PER_HOUR * HOURS_PER_DAY
SECONDS_PER_YEAR = SECONDS_PER_DAY * DAYS_PER_YEAR
HOURS_PER_YEAR = 8760  # 365 * 24

# Time step defaults
DEFAULT_TIME_STEP_SECONDS = 3600.0  # 1 hour
DEFAULT_WEEK_TIME_STEP = 3600 * 24 * 7  # 1 week in seconds

# System defaults
DEFAULT_SYSTEM_LIFETIME_YEARS = 30.0
DEFAULT_TECHNICAL_LIFETIME_YEARS = 40.0
DEFAULT_DISCOUNT_RATE_PERCENT = 5.0

# Cost unit conversion factors.
# These convert ESDL cost units to EUR by accounting for the physical unit
# in the denominator:
#   EUR/kW:  1 kW = 1000 W       → factor = 1/1000 = 0.001
#   EUR/MW:  1 MW = 1e6 W        → factor = 1/1e6
#   EUR/m:   already in metres   → factor = 1
#   EUR/km:  1 km = 1000 m       → factor = 1/1000 = 0.001
#   EUR/kWh: 1 kWh = 3.6e6 J    → factor = 1/3.6e6
#   EUR/MWh: 1 MWh = 3.6e9 J    → factor = 1/3.6e9
#   % OF CAPEX: percentage       → factor = 1/100 = 0.01
# MappingProxyType makes this immutable at runtime — callers cannot accidentally
# mutate the global constant.  Adapters copy it with dict() for local use.
COST_UNIT_FACTORS: MappingProxyType[str, float] = MappingProxyType(
    {
        "EUR/kW": 1.0 / 1_000,
        "EUR/MW": 1.0 / 1_000_000,
        "EUR/m": 1.0,
        "EUR/km": 1.0 / 1_000,
        "EUR/kWh": 1.0 / 3_600_000,
        "EUR/MWh": 1.0 / 3_600_000_000,
        "% OF CAPEX": 1.0 / 100,
    }
)

# Unit conversion constants
TONS_TO_KG = 1000
TONS_TO_GRAMS = 1000000
KG_TO_TONS = 1.0 / 1000
PERCENTAGE_TO_DECIMAL = 1.0 / 100.0

# Database constants
DEFAULT_DATABASE_SSL_PORT = 443
HTTPS_PREFIX_LENGTH = 8  # len("https://")
HTTP_PREFIX_LENGTH = 7  # len("http://")

# File system limits
MAX_PATH_LENGTH = 4096
MAX_FILENAME_LENGTH = 255
MAX_DATABASE_NAME_LENGTH = 64
MAX_USERNAME_LENGTH = 64

# Network constants
RFC_1035_HOSTNAME_LIMIT = 253
MIN_PORT_NUMBER = 1
MAX_PORT_NUMBER = 65535
MINIMUM_PASSWORD_LENGTH = 8

# Time series composite key format
COMPOSITE_KEY_SEPARATOR = "|"

# Field name lookup lists used by the KPI calculators.
# Each tuple defines the priority order in which field names are tried for
# a given energy category. The calculators import these directly so there
# is a single source of truth.
CONSUMPTION_FIELDS: tuple[str, ...] = ("ThermalConsumption", "Consumption", "Energy")
DEMAND_FIELDS: tuple[str, ...] = ("ThermalDemand", "Demand")
PRODUCTION_FIELDS: tuple[str, ...] = ("ThermalProduction", "Production", "Energy")
ELECTRICAL_CONSUMPTION_FIELDS: tuple[str, ...] = ("ElectricalConsumption",)
CONVERSION_FIELDS: tuple[str, ...] = ("ElectricalConsumption", "ThermalProduction")

# Union of all recognised field names — used to warn when a DataFrame column
# will not contribute to any KPI calculation.
KNOWN_TIME_SERIES_FIELDS: frozenset[str] = frozenset(
    CONSUMPTION_FIELDS + DEMAND_FIELDS + PRODUCTION_FIELDS + ELECTRICAL_CONSUMPTION_FIELDS
)

# Security-related ports to validate against
DANGEROUS_PORTS = {22, 23, 80, 3389, 5985, 5986}  # SSH, Telnet, HTTP, RDP, WinRM
# Secure database ports (allowed for SSL/TLS connections)
SECURE_DATABASE_PORTS = {443, 8443}
# IANA well-known port boundary: ports 0-1023 are privileged/system ports.
# Ports in this range that are not explicitly recognised (e.g. not in SECURE_DATABASE_PORTS
# or common_db_ports) generate an advisory warning in DatabaseCredentials.validate_port_range.
PRIVILEGED_PORT_MAX = 1023

# Power warning threshold: asset power values above this (1 GW) are physically plausible
# in district heating infrastructure but unusual — validate_power_realistic emits a
# UserWarning for values above this threshold to flag potential unit-conversion errors.
POWER_WARNING_THRESHOLD_W = 1e9  # 1 GW

# Time series validation
MAX_TIME_SERIES_LENGTH = HOURS_PER_YEAR * 10  # 10 years of hourly data
TIME_SERIES_VALUE_RANGE = (-1e12, 1e12)  # ±1 TW

# XML validation
MAX_XML_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

# ESDL model name processing
OPTIMAL_TOPOLOGY_SUFFIX = "optimal_topology_mod"
OPTIMAL_TOPOLOGY_SUFFIX_LENGTH = 21  # len("optimal_topology_mod") + 1 for underscore
MOD_SUFFIX_LENGTH = 4  # len("mod") + 1 for underscore

# Localhost addresses
LOCALHOST_ADDRESSES = ["localhost", "127.0.0.1", "::1"]

# Non-routable IPv4 ranges blocked to prevent SSRF and misconfiguration.
# First octets that are always reserved: 0 (this network), 10 (class A private), 127 (loopback)
PRIVATE_IPV4_RESERVED_FIRST_OCTETS = {0, 10, 127}
# 172.16.0.0/12 - class B private range covers 172.16-172.31
PRIVATE_IPV4_172_FIRST_OCTET = 172
PRIVATE_IPV4_172_SECOND_OCTET_MIN = 16
PRIVATE_IPV4_172_SECOND_OCTET_MAX = 31
# 192.168.0.0/16 — class C private range
PRIVATE_IPV4_192_FIRST_OCTET = 192
PRIVATE_IPV4_192_SECOND_OCTET = 168
# 169.254.0.0/16 — APIPA link-local range (non-routable)
APIPA_FIRST_OCTET = 169
APIPA_SECOND_OCTET = 254

# Suspicious usernames (for warning purposes)
SUSPICIOUS_USERNAMES = {"admin", "root", "administrator", "sa", "test", "guest"}

# Windows reserved filenames
WINDOWS_RESERVED_NAMES = [
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
]

# HTTP status codes and patterns for validation
HTTP_SCHEMA_URL = "http://www.w3.org/2001/XMLSchema-instance"

# Path traversal security patterns
PATH_TRAVERSAL_PATTERNS = [
    r"\.\.[\\/]",  # ../ or ..\
    r"[\\/]\.\.[\\/]",  # /../ or \..\
    r"[\\/]\.\.$",  # /.. or \.. at end
    r"^\.\.[\\/]",  # ../ or ..\ at start
]

# XXE attack patterns
XXE_ATTACK_PATTERNS = [
    r"<!ENTITY",  # Entity declarations
    r"<!ELEMENT",  # Element declarations
    r"<!DOCTYPE.*\[",  # DOCTYPE with internal subset
    r"&\w+;",  # Entity references
    r'SYSTEM\s+["\']',  # System entity references
    r'PUBLIC\s+["\']',  # Public entity references
]

# Hostname validation pattern (RFC 1123 compliant)
HOSTNAME_REGEX_PATTERN = (
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)
