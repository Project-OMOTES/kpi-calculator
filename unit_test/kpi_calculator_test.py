import sys
import os
import json
import unittest
from pathlib import Path

# Get the absolute path to the directory containing kpi-calculator
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # Go up one level to kpi-calculator
project_root = os.path.dirname(parent_dir)  # Go up another level to project root

# Add the project root to Python path
if project_root not in sys.path:
    sys.path.append(project_root)
    sys.path.append(parent_dir)

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

from kpi_calculator import kpi_model_class


class KpiCalculatorTest(unittest.TestCase):
    def setUp(self):
        # Use Path.joinpath or / operator to create platform-independent paths
        esdl = DATA_DIR / "Unit_test_ESDL.esdl"
        pipes = DATA_DIR / "pipes_kpi_factors.csv"
        assets = DATA_DIR / "nodes_kpi_factors.csv"
        series = DATA_DIR / "power_timeseries.xml"
        unit_conv = DATA_DIR / "unit_conversion.csv"
        # self.model = kpi_model_class.KpiModelEsdl(
        #     "klaas", esdl, series, pipes, assets, unit_conv_file=unit_conv
        # )

    def test_investment_costs(self):
        # need to include costs per Mw
        group = "Investment costs"
        values = {
            "Production": 3000.03,
            "Consumption": 1000.0,
            "Storage": 500.0,
            "Transport": 100000.0,
            "Conversion": 2000.0,
            "All": 106500.03,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Investment costs are not equal")

    def test_installation_costs(self):
        # need to include costs per Mw
        group = "Installation costs"
        values = {
            "Production": 1500.0006,
            "Consumption": 100.0,
            "Storage": 600.0,
            "Transport": 0.1,
            "Conversion": 200.0,
            "All": 2400.1005999999998,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Installation costs are not equal")

    def test_capex(self):
        values = {
            "Production": 4500.0306,
            "Consumption": 1100.0,
            "Storage": 1100.0,
            "Transport": 100000.1,
            "Conversion": 2200,
            "All": 108900.1306,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_capex(item)
        self.assertDictEqual(result, values, "Capex costs are not equal")

    def test_fixed_maintenance_costs(self):
        group = "Fixed maintenance costs"
        values = {
            "Production": 3300.0,
            "Consumption": 33.0,
            "Storage": 11.0,
            "Transport": 0.0,
            "Conversion": 22.0,
            "All": 3366.0,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Fixed maintenance costs are not equal")

    def test_fixed_operational_costs(self):
        group = "Fixed operational costs"
        values = {
            "Production": 3200.0,
            "Consumption": 33.0,
            "Storage": 55.0,
            "Transport": 0.0,
            "Conversion": 44.0,
            "All": 3332.0,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Fixed operational costs are not equal")

    def test_variable_maintenance_costs(self):
        group = "Variable maintenance costs"
        values = {
            "Production": 657.5255999999999,
            "Consumption": 0.0,
            "Storage": 0.0,
            "Transport": 0.0,
            "Conversion": 26301.023999999998,
            "All": 26958.5496,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Variable maintenance costs are not equal")

    def test_variable_operational_costs(self):
        # need to include costs per Mw
        group = "Variable operational costs"
        values = {
            "Production": 263141.74512,
            "Consumption": 0.0,
            "Storage": 0.0,
            "Transport": 0.0,
            "Conversion": 13150.511999999999,
            "All": 276292.25711999997,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_costs_item(group, item)
        self.assertDictEqual(result, values, "Variable operational costs are not equal")

    def test_opex(self):
        values = {
            "Production": 270299.27072000003,
            "Consumption": 33.0 + 33.0 + 0.0 + 0.0,
            "Storage": 11.0 + 55.0 + 0.0 + 0.0,
            "Transport": 0.0 + 0.0 + 0.0 + 0.0,
            "Conversion": 22.0 + 44.0 + 26301.023999999998 + 13150.511999999999,
            "All": 309948.80672000005,
        }
        result = {}
        for item in values:
            result[item] = self.model.get_opex(item)
        self.assertDictEqual(result, values, "opex costs are not equal")

    def test_energy_consumed(self):
        energy_cons = self.model.get_total_energy_consumption_per_year()
        self.assertEqual(energy_cons, 473040000000.0)

    def test_energy_demand(self):
        energy_cons = self.model.get_total_energy_demand_per_year()
        self.assertEqual(energy_cons, 315360000000.0)

    def test_npv(self):
        npv = self.model.calc_npv(40, 5.0)
        self.assertEqual(npv, 5695914.376800004, "NPV is different")

    def test_topo_to_kpi(self):
        # create input
        asset_dict = {}
        for asset in self.model.assets:
            asset_dict[asset.name] = asset.asset_info_dict
            if asset.time_series:
                asset_dict[asset.name]["timeSeries"] = asset.time_series["time_series"]
                asset_dict[asset.name]["timeStep"] = asset.time_series["time_step"]
        asset_dict["GenericProducer_b986"]["power"] = 1000
        input = {
            "system_life_time": 40,
            "assets": asset_dict,
        }
        topo_kpi_model = kpi_model_class.KpiModelTopo(json.dumps(input))
        asset_dict["GenericConsumer_a524"]["TechnicalLifetime"] = 20.0
        input2 = json.dumps({"system_life_time": 40, "assets": asset_dict})
        topo_kpi_model.get_kpis(input2)
        # get results and compare them
        self.assertTrue(True)

    def test_capex_serie(self):
        test = self.model.assets[0].get_capex_life_time(40, True)
        test = self.model.assets[0].get_opex_life_time(40, True)
        opex = self.model.get_capex_lifetime("All", 40, True)
        values = self.model.get_costs_item_life_time("Fixed operational costs", "All", 40, True)
        self.assertTrue(True)

    def test_emission(self):
        emission = self.model.get_emission()
        self.assertAlmostEqual(emission, 7.0956, 3, "Emission is different")
        self.assertAlmostEqual(
            emission / self.model.get_total_energy_production_per_year() * 1e9,
            0.0075000000000000015,
            3,
            "Emission is different",
        )
        self.assertAlmostEqual(
            sum(self.model.get_costs_item_life_time("CO2", "Production", 40)), 4.7304 * 40, 3
        )


if __name__ == "__main__":
    unittest.main()
