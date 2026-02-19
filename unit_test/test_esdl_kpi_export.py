"""Tests for ESDL KPI export functionality."""

import sys
import unittest
import uuid
from pathlib import Path

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from esdl import esdl  # noqa: E402

from kpicalculator import KpiManager  # noqa: E402


class TestEsdlKpiExport(unittest.TestCase):
    """Test ESDL KPI export functionality with focus on core requirements."""

    def setUp(self) -> None:
        """Set up test environment with KPI manager and calculated results."""
        # Create KPI manager
        self.kpi_manager = KpiManager()

        # Load ESDL data
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        series = DATA_DIR / "power_timeseries.xml"

        self.kpi_manager.load_from_esdl(str(esdl_file), time_series_file=str(series))

        # Calculate KPIs for testing
        self.kpi_results = self.kpi_manager.calculate_all_kpis(system_lifetime=30)

        # Create temporary directory for test outputs within the repository
        self.test_temp_dir = TEST_DIR / "temp_test_outputs"
        self.test_temp_dir.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        """Clean up temporary files."""
        import shutil

        if self.test_temp_dir.exists():
            shutil.rmtree(self.test_temp_dir)

    def test_export_to_esdl_file_success(self):
        """Test successful export to ESDL file."""
        output_file = str(self.test_temp_dir / "test_export.esdl")

        # Export KPIs to file
        success = self.kpi_manager.export_to_esdl(self.kpi_results, output_file)

        # Verify export success
        self.assertTrue(success, "ESDL export should succeed")
        self.assertTrue(Path(output_file).exists(), "Output file should be created")

        # Verify file contains KPI data
        with Path(output_file).open(encoding="utf-8") as f:
            content = f.read()
            self.assertIn("<KPIs", content, "File should contain KPIs element")
            self.assertIn(
                "DistributionKPI", content, "File should contain DistributionKPI elements"
            )
            self.assertIn("CAPEX", content, "File should contain CAPEX data")
            self.assertIn("OPEX", content, "File should contain OPEX data")

    def test_get_esdl_with_kpis_data_structure(self):
        """Test getting ESDL with KPIs as data structure."""
        # Get ESDL object with KPIs
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis(self.kpi_results)

        # Verify return type
        self.assertIsInstance(
            esdl_with_kpis, esdl.EnergySystem, "Should return esdl.EnergySystem object"
        )

        # Verify KPIs are added
        main_area = esdl_with_kpis.instance[0].area
        self.assertIsNotNone(main_area.KPIs, "Main area should have KPIs")
        self.assertGreater(len(main_area.KPIs.kpi), 0, "Should contain KPI elements")

        # Verify KPI structure
        cost_kpis = [kpi for kpi in main_area.KPIs.kpi if "cost" in kpi.name.lower()]
        self.assertGreater(len(cost_kpis), 0, "Should contain cost KPIs")

        # Check first cost KPI structure
        cost_kpi = cost_kpis[0]
        self.assertIsNotNone(cost_kpi.quantityAndUnit, "KPI should have quantity and unit")
        self.assertIsNotNone(cost_kpi.distribution, "KPI should have distribution")
        self.assertGreater(
            len(cost_kpi.distribution.stringItem), 0, "Distribution should contain string items"
        )

    def test_export_to_esdl_without_file_returns_data_structure(self):
        """Test export_to_esdl without file parameter returns data structure."""
        # Export without file parameter
        esdl_with_kpis = self.kpi_manager.export_to_esdl(self.kpi_results, output_file=None)

        # Verify return type
        self.assertIsInstance(
            esdl_with_kpis, esdl.EnergySystem, "Should return esdl.EnergySystem object"
        )

        # Verify KPIs are present
        main_area = esdl_with_kpis.instance[0].area
        self.assertIsNotNone(main_area.KPIs, "Should contain KPIs")

    def test_kpi_content_accuracy(self):
        """Test that exported KPI values match calculated results."""
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        # Find high level cost breakdown KPI
        high_level_kpi = None
        for kpi in main_area.KPIs.kpi:
            if "High level cost breakdown" in kpi.name:
                high_level_kpi = kpi
                break

        self.assertIsNotNone(high_level_kpi, "Should find high level cost breakdown KPI")

        # Extract CAPEX and OPEX values from KPI
        capex_value = None
        opex_value = None
        for item in high_level_kpi.distribution.stringItem:
            if "CAPEX" in item.label:
                capex_value = float(item.value)
            elif "OPEX" in item.label:
                opex_value = float(item.value)

        # Verify values match calculated results (CAPEX=total, OPEX=yearly)
        expected_capex_total = self.kpi_results["costs"]["capex"]["All"]
        expected_opex_yearly = self.kpi_results["costs"]["opex"]["All"]

        self.assertIsNotNone(capex_value, "Should find CAPEX value in KPI")
        self.assertIsNotNone(opex_value, "Should find OPEX value in KPI")
        self.assertAlmostEqual(
            capex_value,
            expected_capex_total,
            places=2,
            msg="CAPEX value should match calculated result",
        )
        self.assertAlmostEqual(
            opex_value,
            expected_opex_yearly,
            places=2,
            msg="OPEX value should match calculated result",
        )

    def test_kpi_structure_compliance(self):
        """Test that exported KPIs comply with ESDL schema structure."""
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        # Verify KPIs container
        self.assertIsInstance(main_area.KPIs, esdl.KPIs, "KPIs should be esdl.KPIs type")
        self.assertIsNotNone(main_area.KPIs.id, "KPIs should have ID")

        # Check each KPI element
        for kpi in main_area.KPIs.kpi:
            # Verify KPI type and structure
            self.assertIsInstance(
                kpi, esdl.DistributionKPI, "All KPIs should be DistributionKPI type"
            )
            self.assertIsNotNone(kpi.id, "KPI should have ID")
            self.assertIsNotNone(kpi.name, "KPI should have name")

            # Verify quantity and unit
            self.assertIsNotNone(kpi.quantityAndUnit, "KPI should have quantityAndUnit")
            self.assertIsInstance(
                kpi.quantityAndUnit,
                esdl.QuantityAndUnitType,
                "quantityAndUnit should be correct type",
            )
            self.assertIsNotNone(
                kpi.quantityAndUnit.physicalQuantity, "Should have physical quantity"
            )
            self.assertIsNotNone(kpi.quantityAndUnit.unit, "Should have unit")

            # Verify distribution
            self.assertIsNotNone(kpi.distribution, "KPI should have distribution")
            self.assertIsInstance(
                kpi.distribution,
                esdl.StringLabelDistribution,
                "Distribution should be StringLabelDistribution",
            )
            self.assertGreater(
                len(kpi.distribution.stringItem), 0, "Distribution should contain string items"
            )

            # Verify string items
            for item in kpi.distribution.stringItem:
                self.assertIsInstance(item, esdl.StringItem, "Items should be StringItem type")
                self.assertIsNotNone(item.label, "String item should have label")
                self.assertIsNotNone(item.value, "String item should have value")

    def test_multiple_kpi_categories(self):
        """Test that all KPI categories (cost, energy, emissions) are exported."""
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        kpi_names = [kpi.name.lower() for kpi in main_area.KPIs.kpi]

        # Check for cost KPIs
        has_cost_kpi = any("cost" in name for name in kpi_names)
        self.assertTrue(has_cost_kpi, "Should contain cost KPIs")

        # Check for energy KPIs
        has_energy_kpi = any("energy" in name for name in kpi_names)
        self.assertTrue(has_energy_kpi, "Should contain energy KPIs")

        # Check for emission KPIs
        has_emission_kpi = any("emission" in name or "co2" in name for name in kpi_names)
        self.assertTrue(has_emission_kpi, "Should contain emission KPIs")

    def test_error_handling_no_energy_system(self):
        """Test error handling when no energy system is loaded."""
        # Create fresh KPI manager without loading data
        empty_manager = KpiManager()

        # Attempt export should raise ValueError
        with self.assertRaises(
            ValueError, msg="Should raise ValueError when no energy system loaded"
        ):
            empty_manager.export_to_esdl({}, "output.esdl")

        with self.assertRaises(
            ValueError, msg="Should raise ValueError when no energy system loaded"
        ):
            empty_manager.get_esdl_with_kpis({})

    def test_empty_results_handling(self):
        """Test handling of empty KPI results."""
        # Export with empty results
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis({})

        # Should still create ESDL structure but with minimal KPIs
        main_area = esdl_with_kpis.instance[0].area
        self.assertIsNotNone(main_area.KPIs, "Should create KPIs element even with empty results")

    def test_uuid_generation(self):
        """Test that generated UUIDs are valid and unique."""
        esdl_with_kpis = self.kpi_manager.get_esdl_with_kpis(self.kpi_results)
        main_area = esdl_with_kpis.instance[0].area

        # Collect all UUIDs
        uuids = set()

        # KPIs container UUID
        kpis_id = main_area.KPIs.id
        self.assertIsNotNone(kpis_id, "KPIs should have ID")

        # Validate UUID format
        try:
            uuid.UUID(kpis_id)
        except ValueError:
            self.fail(f"KPIs ID '{kpis_id}' is not a valid UUID")

        uuids.add(kpis_id)

        # Check KPI UUIDs
        for kpi in main_area.KPIs.kpi:
            kpi_id = kpi.id
            self.assertIsNotNone(kpi_id, "Each KPI should have ID")

            # Validate UUID format
            try:
                uuid.UUID(kpi_id)
            except ValueError:
                self.fail(f"KPI ID '{kpi_id}' is not a valid UUID")

            # Check uniqueness
            self.assertNotIn(kpi_id, uuids, f"UUID '{kpi_id}' should be unique")
            uuids.add(kpi_id)

    def test_level_parameter_validation(self):
        """Test validation of level parameter."""
        # Valid levels should work
        for level in ["system", "area", "asset"]:
            try:
                self.kpi_manager.get_esdl_with_kpis(self.kpi_results, level=level)
            except ValueError as e:
                if "Invalid KPI level" in str(e):
                    self.fail(f"Level '{level}' should be valid")

        # Invalid level should raise ValueError
        with self.assertRaises(ValueError, msg="Should raise ValueError for invalid level"):
            self.kpi_manager.get_esdl_with_kpis(self.kpi_results, level="invalid")


if __name__ == "__main__":
    unittest.main()
