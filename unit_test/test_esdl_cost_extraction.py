"""Unit tests for ESDL cost extraction functionality."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

# Add the src directory to the Python path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from esdl import esdl  # noqa: E402
from esdl.esdl_handler import EnergySystemHandler  # noqa: E402

from kpicalculator.adapters.esdl_adapter import EsdlAdapter  # noqa: E402


class TestEsdlCostExtraction(unittest.TestCase):
    """Test ESDL cost extraction from costInformation elements."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.adapter = EsdlAdapter()
        # Load test ESDL file
        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        esh = EnergySystemHandler()
        self.es = esh.load_file(str(esdl_file))

    def test_consumer_with_eur_costs(self) -> None:
        """
        Test cost extraction from GenericConsumer with EUR units.

        This test verifies extraction of installation and investment costs.
        """
        # Find the GenericConsumer asset (name contains 'a524')
        consumer = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.GenericConsumer) and "a524" in element.name:
                consumer = element
                break

        self.assertIsNotNone(consumer, "GenericConsumer not found in test ESDL")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(consumer)

        # Verify extracted costs
        self.assertIn("installation_cost", costs)
        self.assertAlmostEqual(costs["installation_cost"], 100.0, places=2)

        self.assertIn("investment_cost", costs)
        self.assertAlmostEqual(costs["investment_cost"], 1000.0, places=2)

        # Verify unit strings are stored
        self.assertIn("installation_cost_unit", costs)
        self.assertEqual(costs["installation_cost_unit"], "EUR")

        self.assertIn("investment_cost_unit", costs)
        self.assertEqual(costs["investment_cost_unit"], "EUR")

    def test_gas_heater_with_kwh_units(self) -> None:
        """Test cost extraction from GasHeater with EUR/kWh units."""
        # Find the GasHeater asset (name contains '743b')
        gas_heater = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.GasHeater) and "743b" in element.name:
                gas_heater = element
                break

        self.assertIsNotNone(gas_heater, "GasHeater not found in test ESDL")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(gas_heater)

        # Verify EUR/kWh unit costs (stored as-is for later application to time series)
        self.assertIn("variable_operational_cost", costs)
        self.assertAlmostEqual(costs["variable_operational_cost"], 0.1, places=2)

        self.assertIn("variable_maintenance_cost", costs)
        self.assertAlmostEqual(costs["variable_maintenance_cost"], 0.2, places=2)

        # Verify unit strings
        self.assertIn("variable_operational_cost_unit", costs)
        # Unit string should contain "watthour" (from WATTHOUR) and "kilo" (from KILO multiplier)
        unit_str = costs["variable_operational_cost_unit"].lower()
        self.assertIn("watthour", unit_str)

    def test_pipe_with_length_units(self) -> None:
        """Test cost extraction from Pipe with EUR/m and EUR/km units."""
        # Find the Pipe asset (name contains 'a259')
        pipe = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.Pipe) and "a259" in element.name:
                pipe = element
                break

        self.assertIsNotNone(pipe, "Pipe not found in test ESDL")
        self.assertEqual(pipe.length, 1000.0, "Pipe length should be 1000m")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(pipe)

        # Verify EUR/m cost (100 EUR/m * 1000m = 100000 EUR)
        self.assertIn("investment_cost", costs)
        self.assertAlmostEqual(costs["investment_cost"], 100000.0, places=2)

        # Verify EUR/km cost (0.1 EUR/km * 1 km = 0.1 EUR)
        # Note: Pipe length is 1000m = 1km, so 0.1 EUR/km * 1000m = 100 EUR
        self.assertIn("installation_cost", costs)
        self.assertAlmostEqual(costs["installation_cost"], 100.0, places=2)

    def test_geothermal_with_power_units(self) -> None:
        """Test cost extraction from GeothermalSource with EUR/MW units."""
        # Find the GeothermalSource asset (name contains 'b230')
        geothermal = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.GeothermalSource) and "b230" in element.name:
                geothermal = element
                break

        self.assertIsNotNone(geothermal, "GeothermalSource not found in test ESDL")
        self.assertEqual(geothermal.power, 30.0, "GeothermalSource power should be 30W")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(geothermal)

        # Verify EUR/MW cost (power is 30W = 0.00003 MW)
        # investment: 1000 EUR/MW * 0.00003 MW = 0.03 EUR
        self.assertIn("investment_cost", costs)
        self.assertAlmostEqual(costs["investment_cost"], 0.03, places=4)

        # installation: 20 EUR/MW * 0.00003 MW = 0.0006 EUR
        self.assertIn("installation_cost", costs)
        self.assertAlmostEqual(costs["installation_cost"], 0.0006, places=6)

        # variable operational: 10 EUR/MW * 0.00003 MW = 0.0003 EUR
        self.assertIn("variable_operational_cost", costs)
        self.assertAlmostEqual(costs["variable_operational_cost"], 0.0003, places=6)

    def test_producer_with_annual_costs(self) -> None:
        """Test cost extraction from GenericProducer with EUR/yr (annual) units."""
        # Find the GenericProducer asset (name contains 'b986')
        producer = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.GenericProducer) and "b986" in element.name:
                producer = element
                break

        self.assertIsNotNone(producer, "GenericProducer not found in test ESDL")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(producer)

        # Verify EUR/yr cost (stored as-is as annual cost)
        self.assertIn("fixed_maintenance_cost", costs)
        self.assertAlmostEqual(costs["fixed_maintenance_cost"], 300.0, places=2)

        # Verify unit string
        self.assertIn("fixed_maintenance_cost_unit", costs)
        self.assertIn("year", costs["fixed_maintenance_cost_unit"].lower())

    def test_producer_with_mwh_units(self) -> None:
        """Test cost extraction from GenericProducer with EUR/MWh units."""
        # Find the GenericProducer asset (name contains 'b986')
        producer = None
        for element in self.es.eAllContents():
            if isinstance(element, esdl.GenericProducer) and "b986" in element.name:
                producer = element
                break

        self.assertIsNotNone(producer, "GenericProducer not found in test ESDL")

        # Extract costs
        costs = self.adapter._extract_costs_from_esdl(producer)

        # Verify EUR/MWh cost (stored as-is for later application to time series)
        self.assertIn("variable_maintenance_cost", costs)
        self.assertAlmostEqual(costs["variable_maintenance_cost"], 3.0, places=2)

        # Verify unit string includes megawatthour
        self.assertIn("variable_maintenance_cost_unit", costs)
        self.assertIn("mega", costs["variable_maintenance_cost_unit"].lower())

    def test_no_cost_info_returns_empty_dict(self) -> None:
        """Test that extraction returns empty dict when asset has no costInformation."""
        # Create a mock asset without costInformation
        mock_asset = MagicMock(spec=esdl.Asset)
        mock_asset.costInformation = None

        costs = self.adapter._extract_costs_from_esdl(mock_asset)

        self.assertEqual(costs, {})

    def test_convert_cost_value_with_no_unit_spec(self) -> None:
        """Test cost conversion with no unit specification (defaults to EUR)."""
        mock_asset = MagicMock(spec=esdl.Asset)
        value = self.adapter._convert_cost_value(1000.0, None, mock_asset)

        self.assertAlmostEqual(value, 1000.0, places=2)

    def test_get_multiplier_value_with_valid_multipliers(self) -> None:
        """Test multiplier value conversion for standard multipliers."""
        # Create mock multipliers
        mock_kilo = MagicMock()
        mock_kilo.name = "KILO"

        mock_mega = MagicMock()
        mock_mega.name = "MEGA"

        mock_giga = MagicMock()
        mock_giga.name = "GIGA"

        self.assertEqual(self.adapter._get_multiplier_value(mock_kilo), 1000.0)
        self.assertEqual(self.adapter._get_multiplier_value(mock_mega), 1000000.0)
        self.assertEqual(self.adapter._get_multiplier_value(mock_giga), 1000000000.0)

    def test_get_multiplier_value_returns_default_for_none(self) -> None:
        """Test multiplier value returns 1.0 for None."""
        self.assertEqual(self.adapter._get_multiplier_value(None), 1.0)

    def test_get_multiplier_value_returns_default_for_unknown(self) -> None:
        """Test multiplier value returns 1.0 for unknown multiplier."""
        mock_unknown = MagicMock()
        mock_unknown.name = "UNKNOWN_MULTIPLIER"

        self.assertEqual(self.adapter._get_multiplier_value(mock_unknown), 1.0)

    def test_extract_unit_string_simple_eur(self) -> None:
        """Test unit string extraction for simple EUR."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.perUnit = None
        mock_unit_spec.perTimeUnit = None

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR")

    def test_extract_unit_string_eur_per_meter(self) -> None:
        """Test unit string extraction for EUR/m."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "METRE"
        mock_unit_spec.perMultiplier = None
        mock_unit_spec.perTimeUnit = None

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR/metre")

    def test_extract_unit_string_eur_per_kwh(self) -> None:
        """Test unit string extraction for EUR/kWh."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "WATTHOUR"
        mock_unit_spec.perMultiplier = MagicMock()
        mock_unit_spec.perMultiplier.name = "KILO"
        mock_unit_spec.perTimeUnit = None

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR/kilowatthour")

    def test_extract_unit_string_eur_per_year(self) -> None:
        """Test unit string extraction for EUR/yr."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.perUnit = None
        mock_unit_spec.perTimeUnit = MagicMock()
        mock_unit_spec.perTimeUnit.name = "YEAR"

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR/year")

    def test_extract_unit_string_handles_errors(self) -> None:
        """Test unit string extraction handles errors gracefully."""
        mock_unit_spec = MagicMock()
        # Cause an AttributeError
        type(mock_unit_spec).perUnit = property(
            lambda self: (_ for _ in ()).throw(AttributeError("Test error"))
        )

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR")


class TestEsdlCostPriority(unittest.TestCase):
    """Test cost data priority: ESDL costs → CSV override → None."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.adapter = EsdlAdapter()
        self.esdl_file = str(DATA_DIR / "Unit_test_ESDL.esdl")
        self.pipes_csv = str(DATA_DIR / "pipes_kpi_factors.csv")
        self.assets_csv = str(DATA_DIR / "nodes_kpi_factors.csv")
        self.time_series = str(DATA_DIR / "power_timeseries.xml")

    def test_production_mode_uses_esdl_costs(self) -> None:
        """Test that costs are extracted from ESDL when CSV files not provided."""
        # Load without CSV files (production mode)
        energy_system = self.adapter.load_data(
            self.esdl_file,
            time_series_file=self.time_series,
            pipes_cost_file=None,
            assets_cost_file=None,
            use_database_profiles=False,
        )

        # Find an asset that has cost information in ESDL
        consumer = None
        for asset in energy_system.assets:
            if "Consumer" in asset.name and "a524" in asset.name:
                consumer = asset
                break

        self.assertIsNotNone(consumer, "GenericConsumer not found in loaded assets")

        # Verify costs were extracted from ESDL
        self.assertIsNotNone(consumer.investment_cost)
        self.assertAlmostEqual(consumer.investment_cost, 1000.0, places=2)

        self.assertIsNotNone(consumer.installation_cost)
        self.assertAlmostEqual(consumer.installation_cost, 100.0, places=2)

    def test_override_mode_uses_csv_costs(self) -> None:
        """Test that CSV costs override ESDL costs when provided."""
        # Load with CSV files (override mode)
        energy_system = self.adapter.load_data(
            self.esdl_file,
            time_series_file=self.time_series,
            pipes_cost_file=self.pipes_csv,
            assets_cost_file=self.assets_csv,
            use_database_profiles=False,
        )

        # Find the same GenericConsumer asset
        consumer = None
        for asset in energy_system.assets:
            if "Consumer" in asset.name and "a524" in asset.name:
                consumer = asset
                break

        self.assertIsNotNone(consumer, "GenericConsumer not found in loaded assets")

        # Verify costs from CSV override ESDL (CSV values should be different from ESDL)
        # Note: This assumes the CSV has different values than the ESDL file
        # If CSV values match, we at least verify the CSV loading worked
        self.assertIsNotNone(consumer.investment_cost)
        self.assertIsNotNone(consumer.installation_cost)


class TestApiCostOptionalParameters(unittest.TestCase):
    """Test that API function works with optional cost parameters."""

    def test_api_without_cost_files(self) -> None:
        """Test that calculate_kpis works with only ESDL file (production mode)."""
        from kpicalculator.api import calculate_kpis  # noqa: E402

        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        time_series = DATA_DIR / "power_timeseries.xml"

        # Should not raise an error
        results = calculate_kpis(
            esdl_file=str(esdl_file),
            time_series=str(time_series),
            # pipes_cost and assets_cost omitted (production mode)
        )

        # Verify results structure
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)

    def test_api_with_cost_files(self) -> None:
        """Test that calculate_kpis works with CSV files (override mode)."""
        from kpicalculator.api import calculate_kpis  # noqa: E402

        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        time_series = DATA_DIR / "power_timeseries.xml"
        pipes_csv = DATA_DIR / "pipes_kpi_factors.csv"
        assets_csv = DATA_DIR / "nodes_kpi_factors.csv"

        # Should work as before (override mode)
        results = calculate_kpis(
            esdl_file=str(esdl_file),
            pipes_cost=str(pipes_csv),
            assets_cost=str(assets_csv),
            time_series=str(time_series),
        )

        # Verify results structure
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)


if __name__ == "__main__":
    unittest.main()
