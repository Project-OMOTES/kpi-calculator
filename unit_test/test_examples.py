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

    def test_timeseries_dataframes_accepted_without_error(self) -> None:
        """Test that the timeseries_dataframes parameter is accepted without error.

        NOTE: DataFrame time series currently do not reach KPI calculators because
        _load_from_dataframes stores entries under plain asset ID keys, while the
        adapter expects composite keys (asset_id|field_name). This is a known
        limitation — see architecture.rst and ROADMAP.md for details.

        This test verifies that the API accepts DataFrames without crashing and
        returns a well-formed result structure. When the mapping is fixed, this
        test should be updated to assert non-zero energy values.
        """
        esdl_file = "unit_test/data/Unit_test_ESDL.esdl"

        timesteps = 24
        datetime_index = pd.date_range("2019-01-01T00:00:00", periods=timesteps, freq="h")

        timeseries_dataframes = {
            "placeholder_asset": pd.DataFrame(
                {"heat_supplied": [100000.0 + i * 2000 for i in range(timesteps)]},
                index=datetime_index,
            ),
        }

        results = calculate_kpis(esdl_file=esdl_file, timeseries_dataframes=timeseries_dataframes)

        assert "costs" in results
        assert "energy" in results
        assert "emissions" in results

        # TODO(#30): When DataFrame key mapping is fixed, assert non-zero energy
        # values here using real asset IDs from the ESDL fixture.

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

    def test_string_loaded_esdl_export(self) -> None:
        """Test full workflow: load ESDL from string, calculate KPIs, export.

        This validates the fix for string-loaded ESDL export. Previously, the exporter
        would fail when ESDL was loaded via load_from_esdl_string() because it tried
        to re-read from a non-existent file. Now the adapter stores the parsed ESDL
        object and the exporter reuses it.
        """
        from pathlib import Path

        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Read ESDL file as string
        esdl_path = Path("unit_test/data/Unit_test_ESDL.esdl")
        esdl_string = esdl_path.read_text(encoding="utf-8")

        # Load from string
        manager = KpiManager()
        manager.load_from_esdl_string(esdl_string)

        # Calculate KPIs
        results = manager.calculate_all_kpis()

        assert "costs" in results
        assert "energy" in results

        # Export to ESDL (data structure mode)
        exporter = EsdlKpiExporter()
        esdl_with_kpis = exporter.export(
            results=results,
            energy_system=manager.energy_system,
            destination=None,  # Return ESDL object, don't save to file
            level="system",
        )

        # Verify export succeeded and returned an ESDL object
        assert esdl_with_kpis is not None
        assert esdl_with_kpis.instance is not None

        main_area = esdl_with_kpis.instance[0].area
        assert main_area.KPIs is not None
        kpi_by_name = {kpi.name: kpi for kpi in main_area.KPIs.kpi}

        # All three KPI categories must be present
        assert "High level cost breakdown [EUR]" in kpi_by_name
        assert "Net Present Value [EUR]" in kpi_by_name
        assert "Energy breakdown [Wh]" in kpi_by_name
        assert "CO2 emissions [g]" in kpi_by_name

        # Cost values come from ESDL costInformation, not time series — must be non-zero
        expected_capex = results["costs"]["capex"]["All"]
        expected_opex = results["costs"]["opex"]["All"]
        expected_npv = results["costs"]["npv"]
        assert expected_capex > 0, "Fixture ESDL has cost data; CAPEX should be non-zero"
        assert expected_opex > 0, "Fixture ESDL has cost data; OPEX should be non-zero"
        assert expected_npv > 0, "Fixture ESDL has cost data; NPV should be non-zero"

        # Verify exported values round-trip the calculated results exactly
        cost_items = {
            item.label: float(item.value)
            for item in kpi_by_name["High level cost breakdown [EUR]"].distribution.stringItem
        }
        assert cost_items["CAPEX (total)"] == expected_capex, (
            f"Exported CAPEX {cost_items['CAPEX (total)']} != calculated {expected_capex}"
        )
        assert cost_items["OPEX (yearly)"] == expected_opex, (
            f"Exported OPEX {cost_items['OPEX (yearly)']} != calculated {expected_opex}"
        )

        npv_items = {
            item.label: float(item.value)
            for item in kpi_by_name["Net Present Value [EUR]"].distribution.stringItem
        }
        assert npv_items["NPV"] == expected_npv, (
            f"Exported NPV {npv_items['NPV']} != calculated {expected_npv}"
        )
