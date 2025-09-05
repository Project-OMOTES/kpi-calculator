# unit_test/test_logging_utils.py
"""Tests for structured logging utilities."""

import json
import logging
import unittest
from datetime import datetime
from io import StringIO
from unittest.mock import Mock, patch

from src.kpicalculator.common.logging_utils import (
    DatabaseLogger,
    SecurityLogger,
    StructuredLogger,
    get_database_logger,
    get_security_logger,
)


class TestStructuredLogger(unittest.TestCase):
    """Test structured logger functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.logger = StructuredLogger("test.component")
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.logger.logger.addHandler(self.handler)
        self.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up test fixtures."""
        self.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_info_logging_basic(self):
        """Test basic info logging."""
        self.logger.info("Test message")

        log_output = self.stream.getvalue().strip()
        self.assertIn("Test message", log_output)

        # Parse JSON log entry
        log_data = json.loads(log_output)
        self.assertEqual(log_data["message"], "Test message")
        self.assertEqual(log_data["component"], "test.component")
        self.assertIn("timestamp", log_data)

    def test_info_logging_with_context(self):
        """Test info logging with context data."""
        context = {"asset_id": "test_asset", "port": 443}
        self.logger.info("Test message", context)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Test message")
        self.assertEqual(log_data["context"], context)

    def test_error_logging_with_exception(self):
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

    def test_warning_logging(self):
        """Test warning logging."""
        context = {"validation_type": "file_path"}
        self.logger.warning("Validation warning", context)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Validation warning")
        self.assertEqual(log_data["context"]["validation_type"], "file_path")

    def test_debug_logging(self):
        """Test debug logging."""
        self.logger.debug("Debug message", {"debug_info": "test"})

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Debug message")
        self.assertEqual(log_data["context"]["debug_info"], "test")

    def test_critical_logging(self):
        """Test critical logging."""
        test_exception = RuntimeError("Critical error")

        with patch("traceback.format_exc") as mock_traceback:
            mock_traceback.return_value = "Critical traceback"
            self.logger.critical("Critical issue", {"severity": "high"}, test_exception)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Critical issue")
        self.assertEqual(log_data["context"]["severity"], "high")
        self.assertIn("exception", log_data)

    def test_json_serialization_fallback(self):
        """Test fallback when JSON serialization fails."""
        # Create a non-serializable context
        non_serializable = {"func": lambda x: x}

        with patch("json.dumps", side_effect=TypeError("Not serializable")):
            self.logger.info("Test message", non_serializable)

        log_output = self.stream.getvalue().strip()
        # Should fallback to simple string logging
        self.assertIn("Test message", log_output)
        self.assertIn("Context:", log_output)

    def test_timestamp_format(self):
        """Test timestamp format in logs."""
        with patch("src.kpicalculator.common.logging_utils.datetime") as mock_datetime:
            mock_now = Mock()
            mock_now.isoformat.return_value = "2024-01-01T12:00:00"
            mock_datetime.now.return_value = mock_now

            self.logger.info("Test message")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["timestamp"], "2024-01-01T12:00:00")


class TestDatabaseLogger(unittest.TestCase):
    """Test database-specific logging functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.db_logger = DatabaseLogger("test_component")
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.db_logger.logger.logger.addHandler(self.handler)
        self.db_logger.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up test fixtures."""
        self.db_logger.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_log_connection_attempt(self):
        """Test connection attempt logging."""
        self.db_logger.log_connection_attempt("example.com", 443, "test_db")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Attempting database connection")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)
        self.assertEqual(log_data["context"]["database"], "test_db")

    def test_log_connection_success(self):
        """Test connection success logging."""
        self.db_logger.log_connection_success("example.com", 443)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Database connection established")
        self.assertEqual(log_data["context"]["host"], "example.com")
        self.assertEqual(log_data["context"]["port"], 443)

    def test_log_connection_error(self):
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

    def test_log_credential_load(self):
        """Test credential loading logging."""
        self.db_logger.log_credential_load("example.com", 443, "environment")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Loaded database credentials")
        self.assertEqual(log_data["context"]["credential_source"], "environment")

    def test_log_query_execution(self):
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

    def test_log_query_success(self):
        """Test query success logging."""
        self.db_logger.log_query_success("measurement", "field", 100, 0.5)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Database query completed successfully")
        self.assertEqual(log_data["context"]["record_count"], 100)
        self.assertEqual(log_data["context"]["execution_time_ms"], 500.0)

    def test_log_data_validation(self):
        """Test data validation logging."""
        details = {"value_count": 8760, "measurement": "power"}
        self.db_logger.log_data_validation("asset_123", "time_series", True, details)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Data validation completed")
        self.assertEqual(log_data["context"]["asset_id"], "asset_123")
        self.assertEqual(log_data["context"]["validation_result"], "passed")
        self.assertEqual(log_data["context"]["value_count"], 8760)

    def test_log_data_validation_failed(self):
        """Test failed data validation logging."""
        self.db_logger.log_data_validation("asset_123", "file_path", False)

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["context"]["validation_result"], "failed")

    def test_log_time_series_processing(self):
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

    def setUp(self):
        """Set up test fixtures."""
        self.security_logger = SecurityLogger()
        self.stream = StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.security_logger.logger.logger.addHandler(self.handler)
        self.security_logger.logger.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        """Clean up test fixtures."""
        self.security_logger.logger.logger.removeHandler(self.handler)
        self.handler.close()

    def test_log_validation_attempt(self):
        """Test validation attempt logging."""
        self.security_logger.log_validation_attempt("file_path", "/path/to/file")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Security validation initiated")
        self.assertEqual(log_data["context"]["validation_type"], "file_path")
        self.assertEqual(log_data["context"]["resource"], "/path/to/file")

    def test_log_validation_success(self):
        """Test validation success logging."""
        self.security_logger.log_validation_success("credentials", "user:pass@host:443")

        log_output = self.stream.getvalue().strip()
        log_data = json.loads(log_output)

        self.assertEqual(log_data["message"], "Security validation passed")
        self.assertEqual(log_data["context"]["validation_type"], "credentials")

    def test_log_validation_failure(self):
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

    def test_log_security_threat(self):
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

    def test_log_credential_access(self):
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

    def test_get_database_logger(self):
        """Test database logger factory."""
        logger = get_database_logger("test_component")
        self.assertIsInstance(logger, DatabaseLogger)
        self.assertIn("database.test_component", logger.logger.logger.name)

    def test_get_security_logger(self):
        """Test security logger factory."""
        logger = get_security_logger()
        self.assertIsInstance(logger, SecurityLogger)
        self.assertIn("security", logger.logger.logger.name)

    def test_database_logger_component_naming(self):
        """Test database logger component naming."""
        logger1 = get_database_logger("loader")
        logger2 = get_database_logger("validator")

        self.assertIn("database.loader", logger1.logger.logger.name)
        self.assertIn("database.validator", logger2.logger.logger.name)
        self.assertNotEqual(logger1.logger.logger.name, logger2.logger.logger.name)


if __name__ == "__main__":
    unittest.main()
