"""Tests for EsdlKpiExporter class implementation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from esdl import esdl

# Test data constants
_TEST_KPI_NAME_COST_BREAKDOWN = "High level cost breakdown"
_TEST_KPI_NAME_ENERGY_BREAKDOWN = "Energy breakdown"
_TEST_KPI_NAME_EFFICIENCY = "efficiency"
_TEST_KPI_NAME_NPV = "Net Present Value [EUR]"
_TEST_KPI_NAME_LCOE = "Levelized Cost of Energy [EUR/MWh]"
_TEST_KPI_NAME_EAC = "Equivalent Annual Cost [EUR/yr]"
_TEST_KPI_NAME_TCO = "Total Cost of Ownership [EUR]"
_TEST_KPI_NAME_CO2_EMISSIONS = "CO2 emissions [g]"
_TEST_KPI_NAME_CO2_PER_MWH = "CO2 emissions per MWh [g/MWh]"
_TEST_KPI_NAME_ENERGY_EFFICIENCY = "Energy efficiency [-]"
_TEST_KPI_NAME_ENERGY_BREAKDOWN_WH = "Energy breakdown [Wh]"


def _create_mock_esdl_system() -> esdl.EnergySystem:
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

    def create_mock_esdl_system(self) -> esdl.EnergySystem:
        """Create a minimal mock ESDL energy system for testing."""
        return _create_mock_esdl_system()

    def _find_distribution_item(self, kpi, label_fragment):
        """Find a distribution item by label substring."""
        return next(
            (item for item in kpi.distribution.stringItem if label_fragment in item.label),
            None,
        )

    def _get_kpi_count(self, system):
        """Get the number of KPIs in the system."""
        return len(system.instance[0].area.KPIs.kpi)

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_create_distribution_kpi(self, _mock_handler):
        """Test _create_distribution_kpi method creates correct ESDL structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        exporter = EsdlKpiExporter()
        items = [("CAPEX", 5000.0), ("OPEX", 3000.0)]

        # Act
        kpi = exporter._create_distribution_kpi("Test KPI [EUR]", "COST", "EURO", items)

        # Assert
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

        # Arrange
        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Act
        exporter._add_financial_kpis(kpis, self.mock_kpi_results["financials"])

        # Assert
        self.assertGreater(len(kpis.kpi), 0)
        high_level_kpis = [kpi for kpi in kpis.kpi if _TEST_KPI_NAME_COST_BREAKDOWN in kpi.name]
        self.assertGreater(len(high_level_kpis), 0)

        cost_kpi = high_level_kpis[0]
        capex_item = self._find_distribution_item(cost_kpi, "CAPEX")
        opex_item = self._find_distribution_item(cost_kpi, "OPEX")
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

        # Arrange
        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Act
        exporter._add_energy_kpis(kpis, self.mock_kpi_results["energy"])

        # Assert
        energy_kpis = [kpi for kpi in kpis.kpi if "energy" in kpi.name.lower()]
        self.assertGreater(len(energy_kpis), 0, "Should add energy KPIs")
        energy_breakdown_kpi = next(
            (kpi for kpi in energy_kpis if _TEST_KPI_NAME_ENERGY_BREAKDOWN in kpi.name), None
        )
        self.assertIsNotNone(energy_breakdown_kpi, "Should contain energy breakdown KPI")
        self.assertEqual(energy_breakdown_kpi.quantityAndUnit.unit, esdl.UnitEnum.WATTHOUR)
        efficiency_kpis = [kpi for kpi in kpis.kpi if _TEST_KPI_NAME_EFFICIENCY in kpi.name.lower()]
        self.assertGreater(len(efficiency_kpis), 0, "Should add efficiency KPI")

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_add_emission_kpis(self, _mock_handler):
        """Test _add_emission_kpis adds correct emission KPI structure."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        exporter = EsdlKpiExporter()
        kpis = esdl.KPIs()
        kpis.id = "test-kpis"

        # Act
        exporter._add_emission_kpis(kpis, self.mock_kpi_results["emissions"])

        # Assert
        emission_kpis = [
            kpi for kpi in kpis.kpi if "emission" in kpi.name.lower() or "co2" in kpi.name.lower()
        ]
        self.assertGreater(len(emission_kpis), 0, "Should add emission KPIs")

        emission_kpi = emission_kpis[0]
        self.assertEqual(
            emission_kpi.quantityAndUnit.physicalQuantity, esdl.PhysicalQuantityEnum.EMISSION
        )
        self.assertEqual(emission_kpi.quantityAndUnit.unit, esdl.UnitEnum.GRAM)

    def test_export_file_mode(self):
        """Test export method in file mode saves to disk and returns True."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        with tempfile.TemporaryDirectory(prefix="esdl_exporter_test_") as test_temp_dir:
            # Arrange
            mock_esdl_system = self.create_mock_esdl_system()
            output_file = f"{test_temp_dir}/test_output.esdl"
            exporter = EsdlKpiExporter()

            # Act
            result = exporter.export(
                self.mock_kpi_results, mock_esdl_system, output_file, level="system"
            )

            # Assert
            self.assertTrue(result)
            self.assertTrue(
                Path(output_file).exists(), f"Output file {output_file} was not created."
            )

    @patch("kpicalculator.reporting.esdl_kpi_exporter.EnergySystemHandler")
    def test_export_data_structure_mode(self, mock_handler):
        """Test export method in data structure mode returns esdl.EnergySystem without saving."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        mock_esdl_system = self.create_mock_esdl_system()
        exporter = EsdlKpiExporter()

        # Act
        result = exporter.export(
            self.mock_kpi_results, mock_esdl_system, destination=None, level="system"
        )

        # Assert
        self.assertIsInstance(result, esdl.EnergySystem)
        self.assertEqual(result.id, "test-system")
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs)
        self.assertGreater(len(main_area.KPIs.kpi), 0)
        mock_handler.return_value.save.assert_not_called()

    def test_export_none_esdl_system_raises_error(self):
        """Test that passing None as esdl_energy_system raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        exporter = EsdlKpiExporter()

        # Act & Assert
        with self.assertRaises(ValueError):
            exporter.export(self.mock_kpi_results, None, destination=None, level="system")  # type: ignore[arg-type]

    def test_export_invalid_level_raises_error(self):
        """Test that invalid level parameter raises ValueError."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        exporter = EsdlKpiExporter()

        # Act & Assert
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

        # Arrange
        exporter = EsdlKpiExporter()
        empty_kpi_results = {"financials": {}, "energy": {}, "emissions": {}}
        mock_esdl_system = self.create_mock_esdl_system()

        # Act
        result = exporter.export(
            empty_kpi_results,
            mock_esdl_system,
            destination=None,
            level="system",
        )

        # Assert
        self.assertIsInstance(
            result, esdl.EnergySystem, "Should handle gracefully and return ESDL system"
        )
        main_area = result.instance[0].area
        self.assertIsNotNone(main_area.KPIs, "KPIs container should still be created")

    def test_repeated_export_does_not_accumulate_kpis(self):
        """Test that exporting twice does not duplicate KPIs."""
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        # Arrange
        mock_esdl_system = self.create_mock_esdl_system()
        exporter = EsdlKpiExporter()

        # Act
        exporter.export(self.mock_kpi_results, mock_esdl_system, destination=None, level="system")
        kpi_count_1 = self._get_kpi_count(mock_esdl_system)

        exporter.export(self.mock_kpi_results, mock_esdl_system, destination=None, level="system")
        kpi_count_2 = self._get_kpi_count(mock_esdl_system)

        # Assert
        self.assertEqual(kpi_count_1, kpi_count_2, "Repeated export should not accumulate KPIs")


class TestEsdlKpiExporterSkipZero(unittest.TestCase):
    """Test that KPI elements with zero (missing-data) values are omitted from ESDL output."""

    def _export(self, results: dict) -> dict:
        from kpicalculator.reporting.esdl_kpi_exporter import EsdlKpiExporter

        es = _create_mock_esdl_system()
        exported = EsdlKpiExporter().export(results, es, destination=None, level="system")
        self.assertIsInstance(exported, esdl.EnergySystem)
        return {kpi.name: kpi for kpi in exported.instance[0].area.KPIs.kpi}

    def test__zero_npv__omits_npv_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "npv": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_NPV, kpi_by_name)

    def test__nonzero_npv__includes_npv_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "npv": 5000.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertIn(_TEST_KPI_NAME_NPV, kpi_by_name)

    def test__zero_lcoe__omits_lcoe_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "lcoe": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_LCOE, kpi_by_name)

    def test__nonzero_lcoe__includes_lcoe_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "lcoe": 0.05}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertIn(_TEST_KPI_NAME_LCOE, kpi_by_name)

    def test__zero_eac__omits_eac_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "eac": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_EAC, kpi_by_name)

    def test__zero_tco__omits_tco_kpi(self) -> None:
        # Arrange
        results = {"financials": {"capex": {"All": 0.0}, "opex": {"All": 0.0}, "tco": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_TCO, kpi_by_name)

    def test__zero_energy_values__omits_energy_breakdown_kpi(self) -> None:
        # Arrange
        results = {"energy": {"consumption": 0.0, "production": 0.0, "demand": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_ENERGY_BREAKDOWN_WH, kpi_by_name)

    def test__nonzero_production_only__includes_energy_breakdown(self) -> None:
        # Arrange
        results = {"energy": {"consumption": 0.0, "production": 1e9, "demand": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertIn(_TEST_KPI_NAME_ENERGY_BREAKDOWN_WH, kpi_by_name)
        items = {
            item.label: item.value
            for item in kpi_by_name[_TEST_KPI_NAME_ENERGY_BREAKDOWN_WH].distribution.stringItem
        }
        self.assertNotIn("Consumption", items)
        self.assertIn("Production", items)

    def test__zero_efficiency__omits_efficiency_kpi(self) -> None:
        # Arrange
        results = {"energy": {"efficiency": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_ENERGY_EFFICIENCY, kpi_by_name)

    def test__zero_emissions__omits_co2_kpis(self) -> None:
        # Arrange
        results = {"emissions": {"total": 0.0, "per_mwh": 0.0}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertNotIn(_TEST_KPI_NAME_CO2_EMISSIONS, kpi_by_name)
        self.assertNotIn(_TEST_KPI_NAME_CO2_PER_MWH, kpi_by_name)

    def test__nonzero_emissions__includes_co2_kpis(self) -> None:
        # Arrange
        results = {"emissions": {"total": 500.0, "per_mwh": 1.2}}

        # Act
        kpi_by_name = self._export(results)

        # Assert
        self.assertIn(_TEST_KPI_NAME_CO2_EMISSIONS, kpi_by_name)
        self.assertIn(_TEST_KPI_NAME_CO2_PER_MWH, kpi_by_name)


if __name__ == "__main__":
    unittest.main()
