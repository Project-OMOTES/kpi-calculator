import unittest
from pathlib import Path
import sys
import os

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from kpicalculator import KpiManager


class NewKpiCalculatorTest(unittest.TestCase):
    def setUp(self):
        # Create KPI manager
        unit_conv = DATA_DIR / "unit_conversion.csv"
        self.kpi_manager = KpiManager(str(unit_conv))
        
        # Load ESDL data
        esdl = DATA_DIR / "Unit_test_ESDL.esdl"
        pipes = DATA_DIR / "pipes_kpi_factors.csv"
        assets = DATA_DIR / "nodes_kpi_factors.csv"
        series = DATA_DIR / "power_timeseries.xml"
        
        self.kpi_manager.load_from_esdl(
            str(esdl), str(series), str(pipes), str(assets)
        )
    
    def test_calculate_all_kpis(self):
        # Calculate KPIs
        results = self.kpi_manager.calculate_all_kpis(system_lifetime=40)
        
        # Check that results contain expected keys
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)
        
        # Check specific values
        self.assertAlmostEqual(
            results["costs"]["capex"]["All"], 
            108900.1306, 
            places=2, 
            msg="Total CAPEX is incorrect"
        )
        
        self.assertAlmostEqual(
            results["energy"]["consumption"], 
            473040000000.0, 
            places=0, 
            msg="Energy consumption is incorrect"
        )
        
        self.assertAlmostEqual(
            results["emissions"]["total"], 
            21.665232, 
            places=3, 
            msg="Total emissions are incorrect"
        )


if __name__ == "__main__":
    unittest.main()
