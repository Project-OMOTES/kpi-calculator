"""Tests for EsdlKpiExporter class implementation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from esdl import esdl


class TestEsdlKpiExporter(unittest.TestCase):
    """Test EsdlKpiExporter class functionality in isolation."""

    def setUp(self) -> None:
        """Set up test environment with mock data."""
        # Mock KPI results structure
        self.mock_kpi_results = {
            "financials": {
                "capex": {"All": 100000.0, "Producer": 60000.0, "Consumer": 40000.0},
                "opex": {"All": 20000.0, "Producer": 15000.0, "Consumer": 5000.0},
                "npv": 250000.0,
                "lcoe": 0.05,
            },
            "energy": {
                "consumption": 500000000.0,
                "production": 480000000.0,
                "demand": 520000000.0,
                "efficiency": 0.92,
            },
            "emissions": {"total": 1200.0, "per_mwh": 2.4},
        }

        # Mock energy system with source metadata
        self.mock_energy_system = Mock()
        self.mock_energy_system.source_metadata = {"esdl_file": "test_input.esdl"}
        self.mock_energy_system.esdl_energy_system = None

        # Create temporary directory for test outputs
        self.test_temp_dir = tempfile.mkdtemp(prefix="esdl_exporter_test_")

    def tearDown(self) -> None:
        """Clean up temporary files."""
        import shutil

        if Path(self.test_temp_dir).exists():
            shutil.rmtree(self.test_temp_dir)

    def create_mock_esdl_system(self):
        """Create a mock ESDL energy system for testing."""
        # Create basic ESDL structure
        energy_system = esdl.EnergySystem()
        energy_system.id = "test-system"
        energy_system.name = "Test System"

        # Create instance
        instance = esdl.Instance()
        instance.id = "test-instance"
        instance.name = "Test Instance"

        # Create area
        area = esdl.Area()
        area.id = "test-area"
        area.name = "Test Area"

        # Assemble structure
        instance.area = area
        energy_system.instance.append(instance)

        return energy_system

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_create_distribution_kpi(self, _mock_handler):
        """Test _create_distribution_kpi method creates correct ESDL structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        # Test data
        name = "Test KPI [EUR] (yearly averaged)"
        physical_quantity = "COST"
        unit = "EURO"
        items = [("CAPEX", 5000.0), ("OPEX", 3000.0)]

        # Create distribution KPI
        kpi = exporter._create_distribution_kpi(name, physical_quantity, unit, items)

        # Verify structure
        self.assertIsInstance(kpi, esdl.DistributionKPI)
        self.assertEqual(kpi.name, name)
        self.assertIsNotNone(kpi.id)

        # Verify quantity and unit
        self.assertIsNotNone(kpi.quantityAndUnit)
        self.assertEqual(kpi.quantityAndUnit.physicalQuantity, esdl.PhysicalQuantityEnum.COST)
        self.assertEqual(kpi.quantityAndUnit.unit, esdl.UnitEnum.EURO)

        # Verify distribution
        self.assertIsNotNone(kpi.distribution)
        self.assertIsInstance(kpi.distribution, esdl.StringLabelDistribution)
        self.assertEqual(len(kpi.distribution.stringItem), 2)

        # Verify string items
        for i, (expected_label, expected_value) in enumerate(items):
            item = kpi.distribution.stringItem[i]
            self.assertEqual(item.label, expected_label)
            self.assertEqual(item.value, expected_value)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_financial_kpis(self, _mock_handler):
        """Test _add_financial_kpis method adds correct cost KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        # Create KPIs container
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Add cost KPIs
        exporter._add_financial_kpis(kpis, self.mock_kpi_results["financials"])

        # Verify KPIs were added
        self.assertGreater(len(kpis.kpi), 0, "Should add cost KPIs")

        # Find and verify high level cost breakdown
        high_level_kpis = [kpi for kpi in kpis.kpi if "High level cost breakdown" in kpi.name]
        self.assertGreater(len(high_level_kpis), 0, "Should contain high level cost breakdown KPIs")

        # Verify cost breakdown KPI
        cost_kpi = high_level_kpis[0]
        # Check CAPEX and OPEX values
        capex_item = next(
            (item for item in cost_kpi.distribution.stringItem if "CAPEX" in item.label), None
        )
        opex_item = next(
            (item for item in cost_kpi.distribution.stringItem if "OPEX" in item.label), None
        )

        self.assertIsNotNone(capex_item, "Should contain CAPEX item")
        self.assertIsNotNone(opex_item, "Should contain OPEX item")

        # Verify values (use pre-calculated values from cost calculator)
        expected_capex = self.mock_kpi_results["financials"]["capex"]["All"]
        expected_opex = self.mock_kpi_results["financials"]["opex"]["All"]

        self.assertAlmostEqual(float(capex_item.value), expected_capex, places=2)
        self.assertAlmostEqual(float(opex_item.value), expected_opex, places=2)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_energy_kpis(self, _mock_handler):
        """Test _add_energy_kpis method adds correct energy KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        # Create KPIs container
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Add energy KPIs
        exporter._add_energy_kpis(kpis, self.mock_kpi_results["energy"])

        # Verify KPIs were added
        energy_kpis = [kpi for kpi in kpis.kpi if "energy" in kpi.name.lower()]
        self.assertGreater(len(energy_kpis), 0, "Should add energy KPIs")

        # Verify energy breakdown KPI
        energy_breakdown_kpi = next(
            (kpi for kpi in energy_kpis if "Energy breakdown" in kpi.name), None
        )
        self.assertIsNotNone(energy_breakdown_kpi, "Should contain energy breakdown KPI")

        # Verify unit is WATTHOUR
        self.assertEqual(energy_breakdown_kpi.quantityAndUnit.unit, esdl.UnitEnum.WATTHOUR)

        # Check efficiency KPI
        efficiency_kpis = [kpi for kpi in kpis.kpi if "efficiency" in kpi.name.lower()]
        self.assertGreater(len(efficiency_kpis), 0, "Should add efficiency KPI")

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_emission_kpis(self, _mock_handler):
        """Test _add_emission_kpis method adds correct emission KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        # Create KPIs container
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Add emission KPIs
        exporter._add_emission_kpis(kpis, self.mock_kpi_results["emissions"])

        # Verify KPIs were added
        emission_kpis = [
            kpi for kpi in kpis.kpi if "emission" in kpi.name.lower() or "co2" in kpi.name.lower()
        ]
        self.assertGreater(len(emission_kpis), 0, "Should add emission KPIs")

        # Verify emission KPI structure
        emission_kpi = emission_kpis[0]
        self.assertEqual(
            emission_kpi.quantityAndUnit.physicalQuantity, esdl.PhysicalQuantityEnum.EMISSION
        )
        self.assertEqual(emission_kpi.quantityAndUnit.unit, esdl.UnitEnum.GRAM)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_file_mode(self, mock_handler):
        """Test export method in file mode."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Mock handler behavior
        mock_esdl_system = self.create_mock_esdl_system()
        mock_handler_instance = mock_handler.return_value
        mock_handler_instance.load_file.return_value = mock_esdl_system

        exporter = EsdlKpiExporter()
        output_file = f"{self.test_temp_dir}/test_output.esdl"

        # Test export to file
        result = exporter.export(
            self.mock_kpi_results, self.mock_energy_system, output_file, level="system"
        )

        # Verify file mode returns True
        self.assertTrue(result)

        # Verify handler methods were called
        mock_handler_instance.load_file.assert_called_once_with("test_input.esdl")
        mock_handler_instance.save.assert_called_once_with(output_file)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_data_structure_mode(self, mock_handler):
        """Test export method in data structure mode."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Mock handler behavior
        mock_esdl_system = self.create_mock_esdl_system()
        mock_handler_instance = mock_handler.return_value
        mock_handler_instance.load_file.return_value = mock_esdl_system

        exporter = EsdlKpiExporter()

        # Test export without destination (data structure mode)
        result = exporter.export(
            self.mock_kpi_results, self.mock_energy_system, destination=None, level="system"
        )

        # Verify data structure mode returns ESDL object
        self.assertIsInstance(result, esdl.EnergySystem)

        # Verify handler load was called but save was not
        mock_handler_instance.load_file.assert_called_once_with("test_input.esdl")
        mock_handler_instance.save.assert_not_called()

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_invalid_level_raises_error(self, mock_handler):
        """Test that invalid level parameter raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()
        mock_handler_instance = mock_handler.return_value
        mock_handler_instance.load_file.return_value = mock_esdl_system

        exporter = EsdlKpiExporter()

        # Test invalid level
        with self.assertRaises(ValueError, msg="Should raise ValueError for invalid level"):
            exporter.export(
                self.mock_kpi_results,
                self.mock_energy_system,
                destination=None,
                level="invalid_level",
            )

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_missing_source_metadata_raises_error(self, _mock_handler):
        """Test that missing source metadata raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        # Energy system without source metadata and no stored ESDL object
        mock_energy_system_no_metadata = Mock()
        mock_energy_system_no_metadata.source_metadata = {}
        mock_energy_system_no_metadata.esdl_energy_system = None

        # Test missing ESDL file
        with self.assertRaises(ValueError, msg="Should raise ValueError when ESDL file is missing"):
            exporter.export(
                self.mock_kpi_results,
                mock_energy_system_no_metadata,
                destination=None,
                level="system",
            )

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_empty_kpi_data_handling(self, mock_handler):
        """Test handling of empty KPI data."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()
        mock_handler_instance = mock_handler.return_value
        mock_handler_instance.load_file.return_value = mock_esdl_system

        exporter = EsdlKpiExporter()

        # Test with empty results
        empty_results = {"financials": {}, "energy": {}, "emissions": {}}

        result = exporter.export(
            empty_results, self.mock_energy_system, destination=None, level="system"
        )

        # Should handle gracefully and return ESDL system
        self.assertIsInstance(result, esdl.EnergySystem)

        # KPIs container should still be created
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs)

    def test_export_from_string_loaded_esdl(self):
        """Test export works for ESDL loaded from string (not file)."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Create a mock ESDL system
        mock_esdl_system = self.create_mock_esdl_system()

        # Create energy system with stored ESDL object (as set by EsdlAdapter)
        mock_energy_system = Mock()
        mock_energy_system.source_metadata = {"esdl_source": "string"}
        mock_energy_system.esdl_energy_system = mock_esdl_system

        exporter = EsdlKpiExporter()

        # Export should work without file path - uses stored ESDL object
        result = exporter.export(
            self.mock_kpi_results,
            mock_energy_system,
            destination=None,
            level="system",
        )

        # Verify export succeeded
        self.assertIsInstance(result, esdl.EnergySystem)
        self.assertEqual(result.id, "test-system")

        # Verify KPIs were added
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs)
        self.assertGreater(len(main_area.KPIs.kpi), 0)

    def test_export_from_string_without_object_raises_error(self):
        """Test export fails gracefully when string-loaded but no ESDL object stored."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Create energy system with string source but no stored ESDL object
        mock_energy_system = Mock()
        mock_energy_system.source_metadata = {"esdl_source": "string"}
        mock_energy_system.esdl_energy_system = None

        exporter = EsdlKpiExporter()

        # Should raise ValueError when no ESDL object and no file path available
        with self.assertRaises(ValueError):
            exporter.export(
                self.mock_kpi_results,
                mock_energy_system,
                destination=None,
                level="system",
            )

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_uses_stored_esdl_object_over_file(self, mock_handler):
        """Test that export uses stored ESDL object and skips file loading."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()

        # Energy system with both a file path AND a stored ESDL object
        mock_energy_system = Mock()
        mock_energy_system.source_metadata = {"esdl_file": "test_input.esdl"}
        mock_energy_system.esdl_energy_system = mock_esdl_system

        exporter = EsdlKpiExporter()

        result = exporter.export(
            self.mock_kpi_results,
            mock_energy_system,
            destination=None,
            level="system",
        )

        # Stored object should be used — handler.load_file must NOT be called
        mock_handler.return_value.load_file.assert_not_called()

        # Verify export succeeded with the stored object
        self.assertIsInstance(result, esdl.EnergySystem)
        self.assertEqual(result.id, "test-system")

    def test_repeated_export_does_not_accumulate_kpis(self):
        """Test that exporting twice does not duplicate KPIs."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()

        mock_energy_system = Mock()
        mock_energy_system.source_metadata = {"esdl_source": "string"}
        mock_energy_system.esdl_energy_system = mock_esdl_system

        exporter = EsdlKpiExporter()

        # Export twice
        exporter.export(self.mock_kpi_results, mock_energy_system, destination=None, level="system")
        kpi_count_1 = len(mock_esdl_system.instance[0].area.KPIs.kpi)

        exporter.export(self.mock_kpi_results, mock_energy_system, destination=None, level="system")
        kpi_count_2 = len(mock_esdl_system.instance[0].area.KPIs.kpi)

        self.assertEqual(kpi_count_1, kpi_count_2, "Repeated export should not accumulate KPIs")


if __name__ == "__main__":
    unittest.main()
