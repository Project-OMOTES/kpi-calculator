import sys
import unittest
from pathlib import Path

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from kpicalculator import KpiManager  # noqa: E402


class NewKpiCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        # Create KPI manager
        unit_conv = DATA_DIR / "unit_conversion.csv"
        self.kpi_manager = KpiManager(str(unit_conv))

        # Load ESDL data (CSV costs not provided since ESDL has complete cost information)
        esdl = DATA_DIR / "Unit_test_ESDL.esdl"
        series = DATA_DIR / "power_timeseries.xml"

        self.kpi_manager.load_from_esdl(str(esdl), time_series_file=str(series))

    def test_calculate_all_kpis(self) -> None:
        # Calculate KPIs
        results = self.kpi_manager.calculate_all_kpis(system_lifetime=40)

        # Check that results contain expected keys
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)

        # Check specific values (using ESDL costInformation only)
        self.assertAlmostEqual(
            results["costs"]["capex"]["All"], 107900.03, places=2, msg="Total CAPEX is incorrect"
        )

        self.assertAlmostEqual(
            results["energy"]["consumption"],
            473040000000.0,
            places=0,
            msg="Energy consumption is incorrect",
        )

        self.assertAlmostEqual(
            results["emissions"]["total"], 21.665232, places=3, msg="Total emissions are incorrect"
        )


class EsdlStringLoadingTest(unittest.TestCase):
    """Tests for loading ESDL from string content instead of file path."""

    def test_load_from_esdl_string_empty_raises_error(self) -> None:
        """Test that empty ESDL string raises ValidationError."""
        from kpicalculator.exceptions import ValidationError

        unit_conv = DATA_DIR / "unit_conversion.csv"
        kpi_manager = KpiManager(str(unit_conv))

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("")

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("   ")

    def test_load_from_esdl_string_invalid_raises_error(self) -> None:
        """Test that invalid ESDL string raises ValidationError."""
        from kpicalculator.exceptions import ValidationError

        unit_conv = DATA_DIR / "unit_conversion.csv"
        kpi_manager = KpiManager(str(unit_conv))

        with self.assertRaises(ValidationError):
            kpi_manager.load_from_esdl_string("not valid xml")

    def test_load_from_esdl_string_uses_esdl_name(self) -> None:
        """Test that model name is derived from ESDL name attribute."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        esdl_string = esdl_file.read_text(encoding="utf-8")

        unit_conv = DATA_DIR / "unit_conversion.csv"
        kpi_manager = KpiManager(str(unit_conv))
        kpi_manager.load_from_esdl_string(esdl_string)

        # The test ESDL has name="KPI_calc_test_model"
        self.assertEqual(kpi_manager.energy_system.name, "KPI_calc_test_model")

    def test_load_from_esdl_string_fallback_name(self) -> None:
        """Test that model name falls back to default when ESDL has no name."""
        # Minimal valid ESDL without a name attribute
        esdl_no_name = """<?xml version='1.0' encoding='UTF-8'?>
        <esdl:EnergySystem xmlns:esdl="http://www.tno.nl/esdl" id="test-id">
            <instance id="instance-1">
                <area id="area-1"/>
            </instance>
        </esdl:EnergySystem>"""

        unit_conv = DATA_DIR / "unit_conversion.csv"
        kpi_manager = KpiManager(str(unit_conv))
        kpi_manager.load_from_esdl_string(esdl_no_name)

        self.assertEqual(kpi_manager.energy_system.name, "esdl_from_string")

    def test_load_from_esdl_string_matches_file_loading(self) -> None:
        """Test that string loading produces identical KPI results to file loading."""
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        unit_conv = DATA_DIR / "unit_conversion.csv"

        # Load from file
        file_manager = KpiManager(str(unit_conv))
        file_manager.load_from_esdl(str(esdl_file))
        file_results = file_manager.calculate_all_kpis(system_lifetime=40)

        # Load from string
        esdl_string = esdl_file.read_text(encoding="utf-8")
        string_manager = KpiManager(str(unit_conv))
        string_manager.load_from_esdl_string(esdl_string)

        # Verify string loading sets correct state
        self.assertIsNotNone(string_manager.energy_system)
        self.assertIsNone(string_manager.source_esdl_file)

        # Compare KPI results - should be identical
        string_results = string_manager.calculate_all_kpis(system_lifetime=40)
        self.assertAlmostEqual(
            file_results["costs"]["capex"]["All"],
            string_results["costs"]["capex"]["All"],
            places=2,
            msg="CAPEX mismatch between file and string loading",
        )
        self.assertEqual(
            file_results["energy"]["consumption"],
            string_results["energy"]["consumption"],
            msg="Energy consumption mismatch between file and string loading",
        )
        self.assertAlmostEqual(
            file_results["emissions"]["total"],
            string_results["emissions"]["total"],
            places=6,
            msg="Emissions mismatch between file and string loading",
        )


if __name__ == "__main__":
    unittest.main()
