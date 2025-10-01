"""ESDL KPI exporter for converting KPI results to ESDL format."""

import logging
import uuid
from pathlib import Path
from typing import Any

from esdl import esdl
from esdl.esdl_handler import EnergySystemHandler

from ..adapters.common_model import EnergySystem
from ..common.constants import TONS_TO_GRAMS
from ..kpi_manager import CostResults, EmissionResults, EnergyResults, KpiResults
from .base_exporter import BaseExporter

logger = logging.getLogger(__name__)


class EsdlKpiExporter(BaseExporter):
    """Export KPI calculation results to ESDL (Energy System Description Language) format.

    This exporter takes pre-calculated KPI results and integrates them into ESDL files
    by adding DistributionKPI elements with StringLabelDistribution structures.

    The exporter operates in two modes:
    - File mode: Saves enhanced ESDL file to disk and returns success boolean
    - Data structure mode: Returns ESDL EnergySystem object with integrated KPIs

    Note: This exporter does NOT perform any calculations. All KPI values must be
    pre-calculated by the appropriate calculator classes.
    """

    def __init__(self) -> None:
        """Initialize the ESDL KPI exporter."""
        self.handler = EnergySystemHandler()

    def export(
        self,
        results: KpiResults,
        energy_system: EnergySystem,
        destination: str | Path | None = None,
        level: str = "system",
        source_esdl_file: str | Path | None = None,
        **kwargs: Any,
    ) -> bool | esdl.EnergySystem:
        """Export pre-calculated KPI results to ESDL format.

        Takes KPI calculation results and integrates them into an ESDL energy system
        by adding DistributionKPI elements with StringLabelDistribution structures.
        Operates in dual mode: file export or data structure return.

        Args:
            results: Pre-calculated KPI results from cost/energy/emission calculators.
                Must contain 'costs', 'energy', and 'emissions' dictionaries with
                calculated values (no calculations performed by this method).
            energy_system: Energy system with source metadata for ESDL file location.
            destination: Output ESDL file path. If None, returns data structure instead.
            level: KPI integration level - 'system' (main area), 'area' (per area),
                or 'asset' (per asset). Currently 'area' and 'asset' delegate to 'system'.
            source_esdl_file: Explicit path to source ESDL file. If None, extracts
                from energy_system.source_metadata['esdl_file'].
            **kwargs: Reserved for future export options.

        Returns:
            When destination provided: bool indicating file save success
            When destination is None: esdl.EnergySystem object with integrated KPIs

        Raises:
            ValueError: If level is invalid, results structure is malformed,
                or source ESDL file cannot be determined or loaded.
            OSError: If file operations fail during save.
        """
        # Validate level parameter
        valid_levels = ["system", "area", "asset"]
        if level not in valid_levels:
            raise ValueError(f"Invalid KPI level '{level}'. Must be one of: {valid_levels}")

        # KPI results structure is validated by TypedDict at runtime

        # Get source ESDL file from parameter or energy system metadata
        esdl_file = source_esdl_file
        if (
            not esdl_file
            and hasattr(energy_system, "source_metadata")
            and energy_system.source_metadata
        ):
            esdl_file = energy_system.source_metadata.get("esdl_file")

        if not esdl_file:
            raise ValueError(
                "Source ESDL file must be provided either as parameter or in "
                "energy_system.source_metadata"
            )

        # Load original ESDL file
        esdl_system = self.handler.load_file(esdl_file)

        # Add KPIs to the appropriate level
        if level == "system":
            self._add_kpis_to_system(esdl_system, results)
        elif level == "area":
            self._add_kpis_to_areas(esdl_system, results)
        elif level == "asset":
            self._add_kpis_to_assets(esdl_system, results)

        # Export or return based on destination
        if destination is not None:
            # File mode - save and return boolean
            try:
                # Set the energy system in the handler and save to file
                self.handler.energy_system = esdl_system
                self.handler.save(destination)
                return True
            except OSError as e:
                logger.error(f"File I/O error saving ESDL file to {destination}: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error saving ESDL file to {destination}: {e}")
                return False
        else:
            # Data structure mode - return ESDL object
            return esdl_system

    def _add_kpis_to_system(self, esdl_system: esdl.EnergySystem, results: KpiResults) -> None:
        """Add system-level KPIs to the main area of the ESDL energy system.

        Integrates cost, energy, and emission KPIs into the main area's KPIs container.
        Creates the KPIs container if it doesn't exist.

        Args:
            esdl_system: ESDL energy system to modify
            results: Pre-calculated KPI results organized by category
        """
        # Get the main area from first instance
        if not esdl_system.instance or not esdl_system.instance[0].area:
            return

        main_area = esdl_system.instance[0].area

        # Create or get KPIs container
        if main_area.KPIs is None:
            main_area.KPIs = esdl.KPIs()
            main_area.KPIs.id = str(uuid.uuid4())

        # Add KPIs by category
        if "costs" in results:
            self._add_cost_kpis(main_area.KPIs, results["costs"])
        if "energy" in results:
            self._add_energy_kpis(main_area.KPIs, results["energy"])
        if "emissions" in results:
            self._add_emission_kpis(main_area.KPIs, results["emissions"])

    def _add_kpis_to_areas(self, esdl_system: esdl.EnergySystem, results: KpiResults) -> None:
        """Add area-level KPIs to individual areas (placeholder implementation).

        Currently delegates to system-level KPI addition. Future enhancement will
        support per-area KPI calculations and placement.

        Args:
            esdl_system: ESDL energy system to modify
            results: Pre-calculated KPI results organized by category
        """
        # For now, add to main area - can be extended for per-area results
        self._add_kpis_to_system(esdl_system, results)

    def _add_kpis_to_assets(self, esdl_system: esdl.EnergySystem, results: KpiResults) -> None:
        """Add asset-level KPIs to individual assets (placeholder implementation).

        Currently delegates to system-level KPI addition. Future enhancement will
        support per-asset KPI calculations and placement.

        Args:
            esdl_system: ESDL energy system to modify
            results: Pre-calculated KPI results organized by category
        """
        # For now, add to main area - can be extended for per-asset results
        self._add_kpis_to_system(esdl_system, results)

    def _add_cost_kpis(self, kpis: esdl.KPIs, cost_data: CostResults) -> None:
        """Add cost-related KPIs to the ESDL KPIs container.

        Creates DistributionKPI elements for cost breakdowns, NPV, and LCOE using
        pre-calculated values from the cost calculator. Does not perform calculations.

        Args:
            kpis: ESDL KPIs container to add cost KPIs to
            cost_data: Pre-calculated cost results with 'capex', 'opex', 'npv', 'lcoe'
        """

        # High level cost breakdown (using pre-calculated values)
        if "capex" in cost_data and "opex" in cost_data:
            capex_all = cost_data["capex"].get("All", 0.0)
            opex_all = cost_data["opex"].get("All", 0.0)

            # Note: OPEX from cost calculator is already yearly, CAPEX is total
            items = [("CAPEX (total)", capex_all), ("OPEX (yearly)", opex_all)]

            kpi = self._create_distribution_kpi(
                "High level cost breakdown [EUR]", "COST", "EURO", items
            )
            kpis.kpi.append(kpi)

        # NPV KPI
        if "npv" in cost_data:
            items = [("NPV", cost_data["npv"])]
            kpi = self._create_distribution_kpi("Net Present Value [EUR]", "COST", "EURO", items)
            kpis.kpi.append(kpi)

        # LCOE KPI
        if "lcoe" in cost_data:
            items = [("LCOE", cost_data["lcoe"])]
            kpi = self._create_distribution_kpi(
                "Levelized Cost of Energy [EUR/MWh]", "COST", "EURO", items, per_unit="WATTHOUR"
            )
            kpis.kpi.append(kpi)

    def _add_energy_kpis(self, kpis: esdl.KPIs, energy_data: EnergyResults) -> None:
        """Add energy-related KPIs to the ESDL KPIs container.

        Creates DistributionKPI elements for energy flows and efficiency metrics using
        pre-calculated values from the energy calculator.

        Args:
            kpis: ESDL KPIs container to add energy KPIs to
            energy_data: Pre-calculated energy results with consumption, production, demand,
                efficiency
        """
        # Energy breakdown
        energy_items = []
        if "consumption" in energy_data:
            energy_items.append(("Consumption", energy_data["consumption"]))
        if "production" in energy_data:
            energy_items.append(("Production", energy_data["production"]))
        if "demand" in energy_data:
            energy_items.append(("Demand", energy_data["demand"]))

        if energy_items:
            kpi = self._create_distribution_kpi(
                "Energy breakdown [Wh]", "ENERGY", "WATTHOUR", energy_items
            )
            kpis.kpi.append(kpi)

        # Energy efficiency
        if "efficiency" in energy_data:
            items = [("System Efficiency", energy_data["efficiency"])]
            kpi = self._create_distribution_kpi("Energy efficiency [-]", "ENERGY", "NONE", items)
            kpis.kpi.append(kpi)

    def _add_emission_kpis(self, kpis: esdl.KPIs, emission_data: EmissionResults) -> None:
        """Add emission-related KPIs to the ESDL KPIs container.

        Creates DistributionKPI elements for total emissions and emission intensity
        using pre-calculated values from the emission calculator.

        Args:
            kpis: ESDL KPIs container to add emission KPIs to
            emission_data: Pre-calculated emission results with total and per_mwh values
        """
        # Total emissions
        if "total" in emission_data:
            # Convert to grams for ESDL
            total_grams = emission_data["total"] * TONS_TO_GRAMS
            items = [("Total CO2 Emissions", total_grams)]
            kpi = self._create_distribution_kpi("CO2 emissions [g]", "EMISSION", "GRAM", items)
            kpis.kpi.append(kpi)

        # Emissions per MWh
        if "per_mwh" in emission_data:
            # Convert to g/MWh
            per_mwh_grams = emission_data["per_mwh"] * TONS_TO_GRAMS
            items = [("CO2 per MWh", per_mwh_grams)]
            kpi = self._create_distribution_kpi(
                "CO2 emissions per MWh [g/MWh]", "EMISSION", "GRAM", items, per_unit="WATTHOUR"
            )
            kpis.kpi.append(kpi)

    def _create_distribution_kpi(
        self,
        name: str,
        physical_quantity: str,
        unit: str,
        items: list[tuple[str, float]],
        per_unit: str | None = None,
    ) -> esdl.DistributionKPI:
        """Create an ESDL DistributionKPI element with labeled data points.

        Creates a KPI that contains multiple labeled values (e.g., CAPEX=100, OPEX=50)
        using ESDL's StringLabelDistribution structure. This allows representing
        categorical breakdowns of metrics like cost components or energy flows.

        Args:
            name: Human-readable KPI name (e.g., "High level cost breakdown [EUR]")
            physical_quantity: ESDL physical quantity type (e.g., "COST", "ENERGY")
            unit: Primary unit for the values (e.g., "EURO", "WATTHOUR")
            items: List of (label, value) tuples for the distribution
            per_unit: Optional unit for compound measures (e.g., "WATTHOUR" for EUR/MWh)

        Returns:
            Configured ESDL DistributionKPI with StringLabelDistribution containing
            the labeled data points
        """
        kpi = esdl.DistributionKPI()
        kpi.id = str(uuid.uuid4())
        kpi.name = name

        # Set quantity and unit
        kpi.quantityAndUnit = esdl.QuantityAndUnitType()
        kpi.quantityAndUnit.physicalQuantity = self._get_physical_quantity_enum(physical_quantity)
        kpi.quantityAndUnit.unit = self._get_unit_enum(unit)

        # Set per unit if specified
        if per_unit:
            kpi.quantityAndUnit.perUnit = self._get_unit_enum(per_unit)

        # Create distribution
        kpi.distribution = esdl.StringLabelDistribution()

        # Add string items
        for label, value in items:
            string_item = self._create_string_item(label, value)
            kpi.distribution.stringItem.append(string_item)

        return kpi

    def _get_physical_quantity_enum(self, quantity_name: str) -> esdl.PhysicalQuantityEnum:
        """Convert string to ESDL PhysicalQuantityEnum with error handling.

        Args:
            quantity_name: String name of physical quantity (e.g., "COST", "ENERGY")

        Returns:
            Corresponding ESDL PhysicalQuantityEnum member

        Raises:
            ValueError: If quantity_name is not a valid ESDL physical quantity
        """
        try:
            return getattr(esdl.PhysicalQuantityEnum, quantity_name)
        except AttributeError as e:
            raise ValueError(f"Invalid ESDL physical quantity: {quantity_name}") from e

    def _get_unit_enum(self, unit_name: str) -> esdl.UnitEnum:
        """Convert string to ESDL UnitEnum with error handling.

        Args:
            unit_name: String name of unit (e.g., "EURO", "WATTHOUR", "GRAM")

        Returns:
            Corresponding ESDL UnitEnum member

        Raises:
            ValueError: If unit_name is not a valid ESDL unit
        """
        try:
            return getattr(esdl.UnitEnum, unit_name)
        except AttributeError as e:
            raise ValueError(f"Invalid ESDL unit: {unit_name}") from e

    def _create_string_item(self, label: str, value: float) -> esdl.StringItem:
        """Create an ESDL StringItem for labeled distribution data.

        Args:
            label: Text label for the data point (e.g., "CAPEX", "Production")
            value: Numeric value associated with the label

        Returns:
            ESDL StringItem with label and float value set
        """
        item = esdl.StringItem()
        item.label = label
        item.value = float(value)
        return item
