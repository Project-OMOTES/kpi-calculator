# src/kpicalculator/common/logging_utils.py
"""Structured logging utilities for KPI Calculator."""

import json
import logging
import traceback
from collections.abc import Mapping
from datetime import datetime
from typing import Any, TypedDict

# Type alias for logging context values
# We use Any here as logging context needs maximum flexibility for JSON serialization
# This is one of the few legitimate uses of Any - for data that will be serialized
ContextValue = Any


class ExceptionInfo(TypedDict):
    """Exception information structure."""

    type: str
    message: str
    traceback: str


class BaseLogEntry(TypedDict):
    """Base log entry structure."""

    timestamp: str
    message: str
    component: str


class LogEntryWithContext(BaseLogEntry, total=False):
    """Log entry with optional context and exception."""

    context: Mapping[str, ContextValue]
    exception: ExceptionInfo


class StructuredLogger:
    """Enhanced logger with structured logging support."""

    def __init__(self, name: str):
        """Initialize structured logger.

        Args:
            name: Logger name (typically __name__)
        """
        self.logger = logging.getLogger(name)

    def _log_structured(
        self,
        level: int,
        message: str,
        context: Mapping[str, ContextValue] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log structured message with context.

        Args:
            level: Log level (logging.INFO, etc.)
            message: Human-readable message
            context: Additional context data
            exception: Exception to include in log
        """
        # Build structured log entry
        log_entry: LogEntryWithContext = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "component": self.logger.name,
        }

        # Add context if provided
        if context:
            log_entry["context"] = context

        # Add exception details if provided
        if exception:
            log_entry["exception"] = {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            }

        # Log as JSON for structured logging systems, with fallback
        try:
            structured_message = json.dumps(log_entry, default=str)
            self.logger.log(level, structured_message)
        except (TypeError, ValueError):
            # Fallback to simple logging if JSON serialization fails
            fallback_message = f"{message}"
            if context:
                fallback_message += f" | Context: {context}"
            if exception:
                fallback_message += f" | Exception: {exception}"
            self.logger.log(level, fallback_message)

    def info(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log info message with context."""
        self._log_structured(logging.INFO, message, context)

    def warning(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log warning message with context."""
        self._log_structured(logging.WARNING, message, context)

    def error(
        self,
        message: str,
        context: Mapping[str, ContextValue] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log error message with context and optional exception."""
        self._log_structured(logging.ERROR, message, context, exception)

    def debug(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log debug message with context."""
        self._log_structured(logging.DEBUG, message, context)

    def critical(
        self,
        message: str,
        context: Mapping[str, ContextValue] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log critical message with context and optional exception."""
        self._log_structured(logging.CRITICAL, message, context, exception)


class DatabaseLogger:
    """Specialized structured logger for database operations."""

    def __init__(self, component_name: str):
        """Initialize database logger.

        Args:
            component_name: Name of the database component
        """
        self.logger = StructuredLogger(f"kpicalculator.database.{component_name}")

    def log_connection_attempt(self, host: str, port: int, database: str | None = None) -> None:
        """Log database connection attempt."""
        context = {"host": host, "port": port}
        if database:
            context["database"] = database
        self.logger.info("Attempting database connection", context)

    def log_connection_success(self, host: str, port: int, database: str | None = None) -> None:
        """Log successful database connection."""
        context = {"host": host, "port": port}
        if database:
            context["database"] = database
        self.logger.info("Database connection established", context)

    def log_connection_error(
        self, host: str, port: int, error: Exception, database: str | None = None
    ) -> None:
        """Log database connection error."""
        context = {"host": host, "port": port}
        if database:
            context["database"] = database
        self.logger.error("Database connection failed", context, error)

    def log_credential_load(self, host: str, port: int, source: str) -> None:
        """Log credential loading."""
        context = {"host": host, "port": port, "credential_source": source}
        self.logger.info("Loaded database credentials", context)

    def log_credential_error(self, host: str, port: int, error: Exception) -> None:
        """Log credential loading error."""
        context = {"host": host, "port": port}
        self.logger.error("Failed to load database credentials", context, error)

    def log_query_execution(
        self, measurement: str, field: str, time_range: tuple | None = None
    ) -> None:
        """Log database query execution."""
        context = {"measurement": measurement, "field": field}
        if time_range:
            context["start_time"] = str(time_range[0])
            context["end_time"] = str(time_range[1])
        self.logger.info("Executing database query", context)

    def log_query_success(
        self,
        measurement: str,
        field: str,
        record_count: int,
        execution_time: float | None = None,
    ) -> None:
        """Log successful database query."""
        context = {
            "measurement": measurement,
            "field": field,
            "record_count": record_count,
        }
        if execution_time:
            context["execution_time_ms"] = round(execution_time * 1000, 2)
        self.logger.info("Database query completed successfully", context)

    def log_query_error(self, measurement: str, field: str, error: Exception) -> None:
        """Log database query error."""
        context = {"measurement": measurement, "field": field}
        self.logger.error("Database query failed", context, error)

    def log_data_validation(
        self,
        asset_id: str,
        validation_type: str,
        result: bool,
        details: Mapping[str, ContextValue] | None = None,
    ) -> None:
        """Log data validation results."""
        context: dict[str, ContextValue] = {
            "asset_id": asset_id,
            "validation_type": validation_type,
            "validation_result": "passed" if result else "failed",
        }
        if details:
            context.update(details)

        level_method = self.logger.info if result else self.logger.warning
        level_method("Data validation completed", context)

    def log_time_series_processing(
        self,
        asset_id: str,
        data_points: int,
        time_step: float,
        processing_time: float | None = None,
    ) -> None:
        """Log time series processing."""
        context = {
            "asset_id": asset_id,
            "data_points": data_points,
            "time_step_seconds": time_step,
        }
        if processing_time:
            context["processing_time_ms"] = round(processing_time * 1000, 2)
        self.logger.info("Time series data processed", context)

    def debug(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log debug message with context."""
        self.logger.debug(message, context)

    def info(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log info message with context."""
        self.logger.info(message, context)

    def warning(self, message: str, context: Mapping[str, ContextValue] | None = None) -> None:
        """Log warning message with context."""
        self.logger.warning(message, context)

    def error(
        self,
        message: str,
        context: Mapping[str, ContextValue] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log error message with context and optional exception."""
        self.logger.error(message, context, exception)


class SecurityLogger:
    """Specialized structured logger for security events."""

    def __init__(self) -> None:
        """Initialize security logger."""
        self.logger = StructuredLogger("kpicalculator.security")

    def log_validation_attempt(self, validation_type: str, resource: str) -> None:
        """Log security validation attempt."""
        context = {"validation_type": validation_type, "resource": resource}
        self.logger.debug("Security validation initiated", context)

    def log_validation_success(self, validation_type: str, resource: str) -> None:
        """Log successful security validation."""
        context = {"validation_type": validation_type, "resource": resource}
        self.logger.info("Security validation passed", context)

    def log_validation_failure(
        self, validation_type: str, resource: str, reason: str, severity: str = "medium"
    ) -> None:
        """Log security validation failure."""
        context = {
            "validation_type": validation_type,
            "resource": resource,
            "failure_reason": reason,
            "severity": severity,
        }
        self.logger.warning("Security validation failed", context)

    def log_security_threat(
        self,
        threat_type: str,
        resource: str,
        details: Mapping[str, ContextValue],
        severity: str = "high",
    ) -> None:
        """Log potential security threat."""
        context = {
            "threat_type": threat_type,
            "resource": resource,
            "severity": severity,
            **details,
        }
        self.logger.critical("Potential security threat detected", context)

    def log_credential_access(self, host: str, port: int, access_method: str) -> None:
        """Log credential access (without sensitive data)."""
        context = {"host": host, "port": port, "access_method": access_method}
        self.logger.info("Credential access granted", context)


def get_database_logger(component_name: str) -> DatabaseLogger:
    """Get a database logger for a component.

    Args:
        component_name: Name of the database component

    Returns:
        Configured DatabaseLogger instance
    """
    return DatabaseLogger(component_name)


def get_security_logger() -> SecurityLogger:
    """Get the security logger.

    Returns:
        Configured SecurityLogger instance
    """
    return SecurityLogger()
