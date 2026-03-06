"""Unit tests for ESDL cost extraction functionality."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Get the absolute path to the test directory
TEST_DIR = Path(__file__).parent
DATA_DIR = TEST_DIR / "data"

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
        # Unit should be EUR/kWh (simplified from EUR/WATTHOUR with KILO multiplier)
        self.assertEqual(costs["variable_operational_cost_unit"], "EUR/kWh")

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
        self.assertEqual(costs["fixed_maintenance_cost_unit"], "EUR/yr")

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

        # Verify unit string is EUR/MWh (simplified from EUR/WATTHOUR with MEGA multiplier)
        self.assertIn("variable_maintenance_cost_unit", costs)
        self.assertEqual(costs["variable_maintenance_cost_unit"], "EUR/MWh")

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
            lambda self: (_ for _ in ()).throw(AttributeError("Test error"))  # noqa: ARG005
        )

        unit_string = self.adapter._extract_unit_string(mock_unit_spec)
        self.assertEqual(unit_string, "EUR")


class TestEsdlCostLoading(unittest.TestCase):
    """Test that costs are extracted from ESDL costInformation."""

    def test_esdl_costs_extracted(self) -> None:
        """Test that costs are extracted from ESDL costInformation elements."""
        adapter = EsdlAdapter()
        esdl_file = str(DATA_DIR / "Unit_test_ESDL.esdl")
        time_series = str(DATA_DIR / "power_timeseries.xml")

        energy_system = adapter.load_data(
            esdl_file,
            time_series_file=time_series,
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


class TestApiCostExtraction(unittest.TestCase):
    """Test that API function extracts costs from ESDL."""

    def test_api_extracts_esdl_costs(self) -> None:
        """Test that calculate_kpis extracts costs from ESDL file."""
        from kpicalculator.api import calculate_kpis

        esdl_file = DATA_DIR / "Unit_test_ESDL.esdl"
        time_series = DATA_DIR / "power_timeseries.xml"

        results = calculate_kpis(
            esdl_file=str(esdl_file),
            time_series=str(time_series),
        )

        # Verify results structure
        self.assertIn("costs", results)
        self.assertIn("energy", results)
        self.assertIn("emissions", results)


if __name__ == "__main__":
    unittest.main()


class TestConvertedUnitGeneration(unittest.TestCase):
    """Test _get_converted_unit method for correct unit string generation."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.adapter = EsdlAdapter()

    def test_get_converted_unit_energy_kwh(self) -> None:
        """Test converted unit for EUR/kWh (WATTHOUR with KILO multiplier)."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = None
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "WATTHOUR"
        mock_unit_spec.perMultiplier = MagicMock()
        mock_unit_spec.perMultiplier.name = "KILO"
        mock_unit_spec.perTimeUnit = None

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "EUR/kWh")

    def test_get_converted_unit_energy_mwh(self) -> None:
        """Test converted unit for EUR/MWh (WATTHOUR with MEGA multiplier)."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = None
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "WATTHOUR"
        mock_unit_spec.perMultiplier = MagicMock()
        mock_unit_spec.perMultiplier.name = "MEGA"
        mock_unit_spec.perTimeUnit = None

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "EUR/MWh")

    def test_get_converted_unit_length_converted_to_eur(self) -> None:
        """Test converted unit for EUR/m becomes EUR after conversion."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = None
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "METRE"
        mock_unit_spec.perMultiplier = None
        mock_unit_spec.perTimeUnit = None

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "EUR")

    def test_get_converted_unit_power_converted_to_eur(self) -> None:
        """Test converted unit for EUR/kW becomes EUR after conversion."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = None
        mock_unit_spec.perUnit = MagicMock()
        mock_unit_spec.perUnit.name = "WATT"
        mock_unit_spec.perMultiplier = MagicMock()
        mock_unit_spec.perMultiplier.name = "KILO"
        mock_unit_spec.perTimeUnit = None

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "EUR")

    def test_get_converted_unit_annual(self) -> None:
        """Test converted unit for EUR/yr remains EUR/yr."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = None
        mock_unit_spec.perUnit = None
        mock_unit_spec.perMultiplier = None
        mock_unit_spec.perTimeUnit = MagicMock()
        mock_unit_spec.perTimeUnit.name = "YEAR"

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "EUR/yr")

    def test_get_converted_unit_percentage(self) -> None:
        """Test converted unit for percentage becomes % OF CAPEX."""
        mock_unit_spec = MagicMock()
        mock_unit_spec.unit = MagicMock()
        mock_unit_spec.unit.name = "PERCENT"
        mock_unit_spec.perUnit = None
        mock_unit_spec.perMultiplier = None
        mock_unit_spec.perTimeUnit = None

        unit = self.adapter._get_converted_unit(mock_unit_spec)
        self.assertEqual(unit, "% OF CAPEX")
