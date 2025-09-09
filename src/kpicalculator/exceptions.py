# src/kpicalculator/exceptions.py
"""Custom exception hierarchy for KPI Calculator."""


class KpiCalculatorError(Exception):
    """Base exception for KPI Calculator."""

    pass


class ValidationError(KpiCalculatorError):
    """Raised when input validation fails."""

    pass


class SecurityError(KpiCalculatorError):
    """Raised when security validation fails."""

    pass


class DataSourceError(KpiCalculatorError):
    """Raised when data source loading fails."""

    pass


class CalculationError(KpiCalculatorError):
    """Raised when KPI calculation fails."""

    pass


class MathematicalError(CalculationError):
    """Raised when mathematical constraints are violated."""

    pass


class ExportError(KpiCalculatorError):
    """Raised when result export fails."""

    pass


class ConfigurationError(KpiCalculatorError):
    """Raised when configuration is invalid."""

    pass


class DatabaseError(DataSourceError):
    """Raised when database operations fail."""

    pass


class CredentialError(SecurityError):
    """Raised when credential loading or validation fails."""

    pass
