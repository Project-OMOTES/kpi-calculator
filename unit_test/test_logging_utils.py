# unit_test/test_logging_utils.py
"""Tests for structured logging utilities."""

import json
import logging
import unittest
from datetime import datetime
from io import StringIO
from unittest.mock import patch

from kpicalculator.common.logging_utils import (
    DatabaseLogger,
    SecurityLogger,
    StructuredLogger,
    get_database_logger,
    get_security_logger,
)


class TestStructuredLogger(unittest.TestCase):
    """Test structured logger functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.logger = StructuredLogger("test.component")
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.logger.logger.addHandler(self.handler)
        self.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_structured_logging_info(self) -> None:
        """Test info logging with and without context data."""
        test_cases = [
            ("basic", "Test message", None),
            ("with_context", "Test message", {"asset_id": "test_asset", "port": 443}),
        ]

        for case_name, message, context in test_cases:
            with self.subTest(case=case_name):
                # Clear the stream for each test
                self.stream.seek(0)
                self.stream.truncate(0)

                self.logger.info(message, context)

                log_output = self.stream.getvalue().strip()
                self.assertIn(message, log_output)

                # Parse JSON log entry
                log_data = json.loads(log_output)
                self.assertEqual(log_data["message"], message)
                self.assertEqual(log_data["component"], "test.component")
                self.assertIn("timestamp", log_data)

                if context:
                    self.assertEqual(log_data["context"], context)

    def test_error_logging_with_exception(self) -> None:
        """Test error logging with exception details."""
        test_exception = ValueError("Test error")

        with patch("traceback.format_exc") as mock_traceback:
            mock_traceback.return_value = "Traceback: ValueError: Test error"
            self.logger.error("Error occurred", None, test_exception)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Error occurred")
        self.assertIn("exception", log_data)
        self.assertEqual(log_data["exception"]["type"], "ValueError")
        self.assertEqual(log_data["exception"]["message"], "Test error")
        self.assertIn("traceback", log_data["exception"])

    def test_structured_logging_levels(self) -> None:
        """Test structured logging across different levels."""
        test_cases = [
            ("warning", "Validation warning", {"validation_type": "file_path"}, None),
            ("debug", "Debug message", {"debug_info": "test"}, None),
            ("critical", "Critical issue", {"severity": "high"}, RuntimeError("Critical error")),
        ]

        for level, message, context, exception in test_cases:
            with self.subTest(level=level):
                # Clear the stream for each test
                self.stream.seek(0)
                self.stream.truncate(0)

                # Call the appropriate logging method
                logger_method = getattr(self.logger, level)
                if exception:
                    with patch("traceback.format_exc") as mock_traceback:
                        mock_traceback.return_value = f"{level.capitalize()} traceback"
                        logger_method(message, context, exception)
                else:
                    logger_method(message, context)

                log_output = self.stream.getvalue().strip()
                log_data = json.loads(log_output)

                self.assertEqual(log_data["message"], message)
                if context:
                    for key, value in context.items():
                        self.assertEqual(log_data["context"][key], value)
                if exception:
                    self.assertIn("exception", log_data)


class TestDatabaseLogger(unittest.TestCase):
    """Test database-specific logging functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.db_logger = DatabaseLogger("test_component")
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.db_logger.logger.logger.addHandler(self.handler)
        self.db_logger.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.db_logger.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_log_connection_attempt(self) -> None:
        """Test connection attempt logging."""
        self.db_logger.log_connection_attempt("example.com", 443, "test_db")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Attempting database connection")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)
        self.assertEqual(log_data["context"]["database"], "test_db")

    def test_log_connection_success(self) -> None:
        """Test connection success logging."""
        self.db_logger.log_connection_success("example.com", 443)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Database connection established")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)

    def test_log_connection_error(self) -> None:
        """Test connection error logging."""
        error = ConnectionError("Connection failed")

        with patch("traceback.format_exc") as mock_traceback:
            mock_traceback.return_value = "Connection error traceback"
            self.db_logger.log_connection_error("example.com", 443, error, "test_db")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Database connection failed")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)
        self.assertEqual(log_data["context"]["database"], "test_db")
        self.assertIn("exception", log_data)

    def test_log_credential_load(self) -> None:
        """Test credential loading logging."""
        self.db_logger.log_credential_load("example.com", 443, "environment")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Loaded database credentials")
        self.assertEqual(log_data["context"]["credential_source"], "environment")

    def test_log_query_execution(self) -> None:
        """Test query execution logging."""
        time_range = (datetime(2024, 1, 1), datetime(2024, 1, 2))
        self.db_logger.log_query_execution("measurement", "field", time_range)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Executing database query")
        self.assertEqual(log_data["context"]["measurement"], "measurement")
        self.assertEqual(log_data["context"]["field"], "field")
        self.assertIn("start_time", log_data["context"])
        self.assertIn("end_time", log_data["context"])

    def test_log_query_success(self) -> None:
        """Test query success logging."""
        self.db_logger.log_query_success("measurement", "field", 100, 0.5)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Database query completed successfully")
        self.assertEqual(log_data["context"]["record_count"], 100)
        self.assertEqual(log_data["context"]["execution_time_ms"], 500.0)

    def test_log_data_validation(self) -> None:
        """Test data validation logging."""
        details = {"value_count": 8760, "measurement": "power"}
        self.db_logger.log_data_validation("asset_123", "time_series", True, details)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Data validation completed")
        self.assertEqual(log_data["context"]["asset_id"], "asset_123")
        self.assertEqual(log_data["context"]["validation_result"], "passed")
        self.assertEqual(log_data["context"]["value_count"], 8760)

    def test_log_time_series_processing(self) -> None:
        """Test time series processing logging."""
        self.db_logger.log_time_series_processing("asset_123", 8760, 3600.0, 0.25)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Time series data processed")
        self.assertEqual(log_data["context"]["asset_id"], "asset_123")
        self.assertEqual(log_data["context"]["data_points"], 8760)
        self.assertEqual(log_data["context"]["time_step_seconds"], 3600.0)
        self.assertEqual(log_data["context"]["processing_time_ms"], 250.0)


class TestSecurityLogger(unittest.TestCase):
    """Test security-specific logging functionality."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.security_logger = SecurityLogger()
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.security_logger.logger.logger.addHandler(self.handler)
        self.security_logger.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.security_logger.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_log_validation_attempt(self) -> None:
        """Test validation attempt logging."""
        self.security_logger.log_validation_attempt("file_path", "/path/to/file")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Security validation initiated")
        self.assertEqual(log_data["context"]["validation_type"], "file_path")
        self.assertEqual(log_data["context"]["resource"], "/path/to/file")

    def test_log_validation_success(self) -> None:
        """Test validation success logging."""
        self.security_logger.log_validation_success("credentials", "user:pass@host:443")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Security validation passed")
        self.assertEqual(log_data["context"]["validation_type"], "credentials")

    def test_log_validation_failure(self) -> None:
        """Test validation failure logging."""
        self.security_logger.log_validation_failure(
            "path_traversal", "/path/../../../etc/passwd", "Path traversal detected", "high"
        )

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Security validation failed")
        self.assertEqual(log_data["context"]["validation_type"], "path_traversal")
        self.assertEqual(log_data["context"]["failure_reason"], "Path traversal detected")
        self.assertEqual(log_data["context"]["severity"], "high")

    def test_log_security_threat(self) -> None:
        """Test security threat logging."""
        details = {"pattern_matched": r"\.\.\/", "ip_address": "192.168.1.100"}
        self.security_logger.log_security_threat("xxe_attack", "malicious.xml", details, "critical")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Potential security threat detected")
        self.assertEqual(log_data["context"]["threat_type"], "xxe_attack")
        self.assertEqual(log_data["context"]["severity"], "critical")
        self.assertIn("pattern_matched", log_data["context"])
        self.assertIn("ip_address", log_data["context"])

    def test_log_credential_access(self) -> None:
        """Test credential access logging."""
        self.security_logger.log_credential_access("example.com", 443, "config_file")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Credential access granted")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)
        self.assertEqual(log_data["context"]["access_method"], "config_file")


class TestLoggerFactories(unittest.TestCase):
    """Test logger factory functions."""

    def test_get_database_logger(self) -> None:
        """Test database logger factory."""
        logger = get_database_logger("test_component")
        self.assertIsInstance(logger, DatabaseLogger)
        self.assertIn("database.test_component", logger.logger.logger.name)

    def test_get_security_logger(self) -> None:
        """Test security logger factory."""
        logger = get_security_logger()
        self.assertIsInstance(logger, SecurityLogger)
        self.assertIn("security", logger.logger.logger.name)


if __name__ == "__main__":
    unittest.main()
