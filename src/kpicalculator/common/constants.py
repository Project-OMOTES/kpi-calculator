# src/kpicalculator/common/constants.py
"""Constants used throughout the KPI Calculator application."""

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
MAX_STRING_FIELD_LENGTH = 255

# Network constants
RFC_1035_HOSTNAME_LIMIT = 253
MIN_PORT_NUMBER = 1
MAX_PORT_NUMBER = 65535
MINIMUM_PASSWORD_LENGTH = 8

# Time series composite key format
COMPOSITE_KEY_SEPARATOR = "|"
COMPOSITE_KEY_FORMAT = "{asset_id}" + COMPOSITE_KEY_SEPARATOR + "{field_name}"

# Security-related ports to validate against
DANGEROUS_PORTS = {22, 23, 80, 3389, 5985, 5986}  # SSH, Telnet, HTTP, RDP, WinRM
# Secure database ports (allowed for SSL/TLS connections)
SECURE_DATABASE_PORTS = {443, 8443}

# Asset property validation ranges
ASSET_VALIDATION_RANGES = {
    "power": (0, 1e12),  # 0 to 1 TW
    "length": (0, 1e6),  # 0 to 1000 km
    "volume": (0, 1e9),  # 0 to 1 million m³
    "cop": (0, 10),  # COP typically 0-10
    "technical_lifetime": (0, 100),  # 0-100 years
    "discount_rate": (0, 100),  # 0-100%
    "emission_factor": (0, 1000),  # 0-1000 kg/GJ
    "aggregation_count": (1, 10000),  # 1-10000 units
}

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

# File extensions
ALLOWED_FILE_EXTENSIONS = {".esdl", ".xml", ".csv", ".json", ".txt"}
ESDL_EXTENSION = ".esdl"

# File permissions (octal)
SECURE_FILE_PERMISSIONS = 0o600  # Read/write for owner only

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
