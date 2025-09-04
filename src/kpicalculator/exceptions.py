# src/kpicalculator/exceptions.py
"""Custom exception hierarchy for KPI Calculator."""

from datetime import datetime
from typing import Dict, Any, Optional


class KpiCalculatorError(Exception):
    """Base exception for KPI Calculator with context support."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        """Initialize with message and optional context.
        
        Args:
            message: Error message
            context: Optional context information for debugging
        """
        super().__init__(message)
        self.context = context or {}
        self.timestamp = datetime.now()
        
    def __str__(self) -> str:
        """Return formatted error message with context."""
        base_msg = super().__str__()
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{base_msg} (Context: {context_str})"
        return base_msg


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