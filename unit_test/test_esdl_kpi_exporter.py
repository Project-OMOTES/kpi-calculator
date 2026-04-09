"""Tests for EsdlKpiExporter class implementation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from esdl import esdl


class TestEsdlKpiExporter(unittest.TestCase):
    """Test EsdlKpiExporter class functionality in isolation."""

    def setUp(self) -> None:
        """Set up test environment with mock data."""
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

        self.test_temp_dir = tempfile.mkdtemp(prefix="esdl_exporter_test_")

    def tearDown(self) -> None:
        """Clean up temporary files."""
        import shutil

        if Path(self.test_temp_dir).exists():
            shutil.rmtree(self.test_temp_dir)

    def create_mock_esdl_system(self) -> esdl.EnergySystem:
        """Create a minimal mock ESDL energy system for testing."""
        energy_system = esdl.EnergySystem()
        energy_system.id = "test-system"
        energy_system.name = "Test System"

        instance = esdl.Instance()
        instance.id = "test-instance"
        instance.name = "Test Instance"

        area = esdl.Area()
        area.id = "test-area"
        area.name = "Test Area"

        instance.area = area
        energy_system.instance.append(instance)

        return energy_system

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_create_distribution_kpi(self, _mock_handler):
        """Test _create_distribution_kpi method creates correct ESDL structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        items = [("CAPEX", 5000.0), ("OPEX", 3000.0)]
        kpi = exporter._create_distribution_kpi("Test KPI [EUR]", "COST", "EURO", items)

        self.assertIsInstance(kpi, esdl.DistributionKPI)
        self.assertEqual(kpi.name, "Test KPI [EUR]")
        self.assertIsNotNone(kpi.id)
        self.assertIsNotNone(kpi.quantityAndUnit)
        self.assertEqual(kpi.quantityAndUnit.physicalQuantity, esdl.PhysicalQuantityEnum.COST)
        self.assertEqual(kpi.quantityAndUnit.unit, esdl.UnitEnum.EURO)
        self.assertIsNotNone(kpi.distribution)
        self.assertIsInstance(kpi.distribution, esdl.StringLabelDistribution)
        self.assertEqual(len(kpi.distribution.stringItem), 2)
        for i, (expected_label, expected_value) in enumerate(items):
            item = kpi.distribution.stringItem[i]
            self.assertEqual(item.label, expected_label)
            self.assertEqual(item.value, expected_value)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_financial_kpis(self, _mock_handler):
        """Test _add_financial_kpis adds correct cost KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        exporter._add_financial_kpis(kpis, self.mock_kpi_results["financials"])

        self.assertGreater(len(kpis.kpi), 0)
        high_level_kpis = [kpi for kpi in kpis.kpi if "High level cost breakdown" in kpi.name]
        self.assertGreater(len(high_level_kpis), 0)

        cost_kpi = high_level_kpis[0]
        capex_item = next(
            (item for item in cost_kpi.distribution.stringItem if "CAPEX" in item.label), None
        )
        opex_item = next(
            (item for item in cost_kpi.distribution.stringItem if "OPEX" in item.label), None
        )
        self.assertIsNotNone(capex_item, "Should contain CAPEX item")
        self.assertIsNotNone(opex_item, "Should contain OPEX item")

        expected_capex = self.mock_kpi_results["financials"]["capex"]["All"]
        expected_opex = self.mock_kpi_results["financials"]["opex"]["All"]
        self.assertAlmostEqual(float(capex_item.value), expected_capex, places=2)
        self.assertAlmostEqual(float(opex_item.value), expected_opex, places=2)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_energy_kpis(self, _mock_handler):
        """Test _add_energy_kpis adds correct energy KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        exporter._add_energy_kpis(kpis, self.mock_kpi_results["energy"])

        energy_kpis = [kpi for kpi in kpis.kpi if "energy" in kpi.name.lower()]
        self.assertGreater(len(energy_kpis), 0, "Should add energy KPIs")
        energy_breakdown_kpi = next(
            (kpi for kpi in energy_kpis if "Energy breakdown" in kpi.name), None
        )
        self.assertIsNotNone(energy_breakdown_kpi, "Should contain energy breakdown KPI")
        self.assertEqual(energy_breakdown_kpi.quantityAndUnit.unit, esdl.UnitEnum.WATTHOUR)
        efficiency_kpis = [kpi for kpi in kpis.kpi if "efficiency" in kpi.name.lower()]
        self.assertGreater(len(efficiency_kpis), 0, "Should add efficiency KPI")

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_emission_kpis(self, _mock_handler):
        """Test _add_emission_kpis adds correct emission KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        exporter._add_emission_kpis(kpis, self.mock_kpi_results["emissions"])

        emission_kpis = [
            kpi for kpi in kpis.kpi if "emission" in kpi.name.lower() or "co2" in kpi.name.lower()
        ]
        self.assertGreater(len(emission_kpis), 0, "Should add emission KPIs")

        emission_kpi = emission_kpis[0]
        self.assertEqual(
            emission_kpi.quantityAndUnit.physicalQuantity, esdl.PhysicalQuantityEnum.EMISSION
        )
        self.assertEqual(emission_kpi.quantityAndUnit.unit, esdl.UnitEnum.GRAM)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_file_mode(self, mock_handler):
        """Test export method in file mode saves to disk and returns True."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()
        mock_handler_instance = mock_handler.return_value
        output_file = f"{self.test_temp_dir}/test_output.esdl"

        exporter = EsdlKpiExporter()
        result = exporter.export(
            self.mock_kpi_results, mock_esdl_system, output_file, level="system"
        )

        self.assertTrue(result)
        mock_handler_instance.save.assert_called_once_with(output_file)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_data_structure_mode(self, mock_handler):
        """Test export method in data structure mode returns esdl.EnergySystem without saving."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()
        exporter = EsdlKpiExporter()

        result = exporter.export(
            self.mock_kpi_results, mock_esdl_system, destination=None, level="system"
        )

        self.assertIsInstance(result, esdl.EnergySystem)
        self.assertEqual(result.id, "test-system")
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs)
        self.assertGreater(len(main_area.KPIs.kpi), 0)
        mock_handler.return_value.save.assert_not_called()

    def test_export_none_esdl_system_raises_error(self):
        """Test that passing None as esdl_energy_system raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        with self.assertRaises(ValueError, msg="None esdl_energy_system should raise ValueError"):
            exporter.export(self.mock_kpi_results, None, destination=None, level="system")  # type: ignore[arg-type]

    def test_export_invalid_level_raises_error(self):
        """Test that invalid level parameter raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()

        with self.assertRaises(ValueError):
            exporter.export(
                self.mock_kpi_results,
                self.create_mock_esdl_system(),
                destination=None,
                level="invalid_level",
            )

    def test_export_empty_kpi_data(self):
        """Test that export handles empty KPI data gracefully."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        exporter = EsdlKpiExporter()
        result = exporter.export(
            {"financials": {}, "energy": {}, "emissions": {}},
            self.create_mock_esdl_system(),
            destination=None,
            level="system",
        )

        self.assertIsInstance(
            result, esdl.EnergySystem, "Should handle gracefully and return ESDL system"
        )
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs, "KPIs container should still be created")

    def test_repeated_export_does_not_accumulate_kpis(self):
        """Test that exporting twice does not duplicate KPIs."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        mock_esdl_system = self.create_mock_esdl_system()
        exporter = EsdlKpiExporter()

        exporter.export(self.mock_kpi_results, mock_esdl_system, destination=None, level="system")
        kpi_count_1 = len(mock_esdl_system.instance[0].area.KPIs.kpi)

        exporter.export(self.mock_kpi_results, mock_esdl_system, destination=None, level="system")
        kpi_count_2 = len(mock_esdl_system.instance[0].area.KPIs.kpi)

        self.assertEqual(kpi_count_1, kpi_count_2, "Repeated export should not accumulate KPIs")


if __name__ == "__main__":
    unittest.main()
