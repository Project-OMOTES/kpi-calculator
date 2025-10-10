"""Test README examples to ensure documentation accuracy.

Purpose:
    These tests validate that all code examples in README.md actually work.
    This prevents documentation drift and ensures users can trust the examples.

Maintenance:
    When updating README examples, update corresponding tests here.
    Tests should fail if README examples become outdated or broken.
"""

import pandas as pd

from kpicalculator import KpiManager, calculate_kpis


class TestReadmeExamples:
    """Test all code examples from README.md."""

    def test_quick_start(self) -> None:
        """Test Quick Start example.

        Note: Uses XML for testing since we don't have InfluxDB in CI.
        In production, time_series parameter is omitted for automatic database loading.
        """
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"
        time_series = "unit_test/data/power_timeseries.xml"

        results = calculate_kpis(esdl_file=esdl_file, time_series=time_series)

        assert "costs" in results
        assert "capex" in results["costs"]
        assert "All" in results["costs"]["capex"]

    def test_basic_usage_production(self) -> None:
        """Test Basic Usage - production example.

        Note: Uses XML for testing since we don't have InfluxDB in CI.
        In production, time_series parameter is omitted for automatic database loading.
        """
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"
        time_series = "unit_test/data/power_timeseries.xml"

        results = calculate_kpis(esdl_file=esdl_file, time_series=time_series)

        assert "costs" in results

    def test_basic_usage_with_parameters(self) -> None:
        """Test Basic Usage - with optional parameters.

        Note: Uses XML for testing since we don't have InfluxDB in CI.
        In production, time_series parameter is omitted for automatic database loading.
        """
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"
        time_series = "unit_test/data/power_timeseries.xml"

        results = calculate_kpis(esdl_file=esdl_file, system_lifetime=30, time_series=time_series)

        assert "costs" in results

    def test_basic_usage_testing_override(self) -> None:
        """Test Basic Usage - testing with XML override."""
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"
        time_series = "unit_test/data/power_timeseries.xml"

        results = calculate_kpis(esdl_file=esdl_file, time_series=time_series)

        assert "costs" in results

    def test_simulator_integration(self) -> None:
        """Test Simulator Integration example."""
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"

        timeseries_data = {
            "asset_id": pd.DataFrame(
                {"power": [100, 120, 110]},
                index=pd.date_range("2024-01-01", periods=3, freq="h"),
            )
        }

        results = calculate_kpis(esdl_file=esdl_file, timeseries_dataframes=timeseries_data)

        assert "costs" in results

    def test_advanced_batch_processing(self) -> None:
        """Test Advanced Batch Processing example."""
        manager = KpiManager("unit_test/data/unit_conversion.csv")
        scenarios = [
            {"file": "unit_test/data/Unit_test_ESDL.esdl", "lifetime": 25},
            {"file": "unit_test/data/Unit_test_ESDL.esdl", "lifetime": 30},
        ]

        for scenario in scenarios:
            manager.load_from_esdl(
                scenario["file"], time_series_file="unit_test/data/power_timeseries.xml"
            )
            results = manager.calculate_all_kpis(system_lifetime=scenario["lifetime"])
            assert "costs" in results
