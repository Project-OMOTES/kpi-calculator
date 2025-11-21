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

    def test_timeseries_dataframes_integration(self) -> None:
        """Test timeseries_dataframes parameter with realistic simulator data.

        Validates that the kpi-calculator can process time series data passed
        directly as pandas DataFrames, which is the primary integration method
        for simulators like omotes-simulator-core and MESIDO.

        Tests with realistic multi-asset, multi-property data:
        - 3 assets (producer, consumer, pipe)
        - 9 different properties (mass_flow, pressure, temperature, volume_flow,
          heat_supplied, heat_demand, velocity, pressure_loss, heat_loss)
        - 24 timesteps (one day, hourly resolution)
        """
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"

        # Create realistic simulator-style time series with multiple properties
        timesteps = 24  # One day, hourly
        datetime_index = pd.date_range("2019-01-01T00:00:00", periods=timesteps, freq="h")

        # Simulate multiple assets with multiple properties each
        # In reality, these would be port IDs from the ESDL file
        asset1_data = pd.DataFrame(
            {
                "mass_flow": [2.5 + i * 0.1 for i in range(timesteps)],
                "pressure": [200000.0] * timesteps,
                "temperature": [353.15] * timesteps,
                "volume_flow": [0.0025 + i * 0.0001 for i in range(timesteps)],
                "heat_supplied": [100000.0 + i * 2000 for i in range(timesteps)],
            },
            index=datetime_index,
        )

        asset2_data = pd.DataFrame(
            {
                "mass_flow": [2.0 + i * 0.05 for i in range(timesteps)],
                "pressure": [180000.0] * timesteps,
                "temperature": [323.15] * timesteps,
                "volume_flow": [0.002 + i * 0.00005 for i in range(timesteps)],
                "heat_demand": [80000.0 + i * 1500 for i in range(timesteps)],
            },
            index=datetime_index,
        )

        asset3_data = pd.DataFrame(
            {
                "mass_flow": [2.3 + i * 0.08 for i in range(timesteps)],
                "pressure": [190000.0 - i * 100 for i in range(timesteps)],
                "temperature": [340.15 - i * 0.5 for i in range(timesteps)],
                "volume_flow": [0.0023 + i * 0.00008 for i in range(timesteps)],
                "velocity": [1.2 + i * 0.02 for i in range(timesteps)],
                "pressure_loss": [500.0 + i * 10 for i in range(timesteps)],
                "heat_loss": [1000.0 + i * 50 for i in range(timesteps)],
            },
            index=datetime_index,
        )

        # Package as expected by KPI calculator
        timeseries_dataframes = {
            "producer_asset_1": asset1_data,
            "consumer_asset_1": asset2_data,
            "pipe_asset_1": asset3_data,
        }

        # Calculate KPIs with realistic simulator data
        results = calculate_kpis(esdl_file=esdl_file, timeseries_dataframes=timeseries_dataframes)

        # Verify results structure
        assert "costs" in results
        assert "energy" in results
        assert "emissions" in results

        # Verify that calculations worked with multiple properties
        assert "capex" in results["costs"]
        assert results["energy"]["consumption"] >= 0

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
