# src/kpicalculator/exceptions.py
"""Custom exception hierarchy for KPI Calculator."""


class KpiCalculatorError(Exception):
    """Base exception for KPI Calculator."""


class ValidationError(KpiCalculatorError):
    """Raised when input validation fails."""


class SecurityError(KpiCalculatorError):
    """Raised when security validation fails."""


class DataSourceError(KpiCalculatorError):
    """Raised when data source loading fails."""


class CalculationError(KpiCalculatorError):
    """Raised when KPI calculation fails."""


class MathematicalError(CalculationError):
    """Raised when mathematical constraints are violated."""


class ExportError(KpiCalculatorError):
    """Raised when result export fails."""


class ConfigurationError(KpiCalculatorError):
    """Raised when configuration is invalid."""


class DatabaseError(DataSourceError):
    """Raised when database operations fail."""


class CredentialError(SecurityError):
    """Raised when credential loading or validation fails."""
