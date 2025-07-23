# src/kpicalculator/adapters/esdl_adapter.py
import logging
from pathlib import Path
from typing import Dict, Optional

from esdl import esdl  # type: ignore[import-untyped]
from esdl.esdl_handler import EnergySystemHandler  # type: ignore[import-untyped]
import pandas as pd  # type: ignore[import-untyped]

from .common_model import Asset, AssetType, EnergySystem, TimeSeries
from .xml_time_series_adapter import PiXmlTimeSeries


class EsdlAdapter:
    """Adapter for loading energy system data from ESDL files."""

    def __init__(self, unit_conversion: Dict[str, float]):
        """Initialize the ESDL adapter.

        Args:
            unit_conversion: Dictionary with unit conversion factors
        """
        self.unit_conversion = unit_conversion

    def load(
        self, esdl_file: str, time_series_file: str, pipes_cost_file: str, assets_cost_file: str
    ) -> EnergySystem:
        """Load energy system data from ESDL file.

        Args:
            esdl_file: Path to ESDL file
            time_series_file: Path to time series file
            pipes_cost_file: Path to pipes cost CSV file
            assets_cost_file: Path to assets cost CSV file

        Returns:
            EnergySystem object
        """
        # Load ESDL file
        esh = EnergySystemHandler()
        es = esh.load_file(esdl_file)

        # Load time series
        time_series_dict = PiXmlTimeSeries(time_series_file, "locationId", "parameterId")

        # Load cost data
        pipe_costs = pd.read_csv(pipes_cost_file)
        asset_costs = pd.read_csv(assets_cost_file)

        # Create energy system
        model_name = Path(esdl_file).stem
        if "optimal_topology_mod" in model_name[-20:]:
            model_name = model_name[:-21]
        if "mod" in model_name[-4:]:
            model_name = model_name[:-4]

        energy_system = EnergySystem(
            name=model_name, assets=[], unit_conversion=self.unit_conversion
        )

        # Process assets
        for esdl_element in es.eAllContents():
            if isinstance(esdl_element, esdl.Asset):
                if isinstance(esdl_element, esdl.Joint):
                    continue
                # Check if the asset is enabled
                if esdl_element.state.value != 0:
                    continue

                asset = self._create_asset_from_esdl(
                    esdl_element, time_series_dict, pipe_costs, asset_costs, model_name
                )

                if asset:
                    energy_system.assets.append(asset)

        return energy_system

    def _create_asset_from_esdl(
        self,
        esdl_element: esdl.Asset,
        time_series_dict: PiXmlTimeSeries,
        pipe_costs: pd.DataFrame,
        asset_costs: pd.DataFrame,
        model_name: str,
    ) -> Optional[Asset]:
        """Create an Asset object from an ESDL element.

        Args:
            esdl_element: ESDL element
            time_series_dict: Time series dictionary
            pipe_costs: DataFrame with pipe costs
            asset_costs: DataFrame with asset costs
            model_name: Model name

        Returns:
            Asset object or None if the element is not supported
        """
        # Get asset type
        asset_type = self._get_asset_type(esdl_element)
        if not asset_type:
            return None

        # Get asset properties
        asset_dict = {
            "id": esdl_element.id,
            "name": esdl_element.name,
            "asset_type": asset_type,
            "length": self._get_length(esdl_element),
            "power": self._get_power(esdl_element),
            "cop": self._get_cop(esdl_element),
            "volume": self._get_volume(esdl_element),
            "technical_lifetime": self._get_tech_lifetime(esdl_element),
            "aggregation_count": self._get_aggregation_count(esdl_element),
            "emission_factor": self._get_emission_factor(esdl_element),
        }

        # Get cost properties
        if isinstance(esdl_element, esdl.Pipe):
            cost_df = pipe_costs
        else:
            cost_df = asset_costs

        try:
            cost_row = cost_df[cost_df["esdlId"] == esdl_element.id].iloc[0]

            asset_dict.update(
                {
                    "investment_cost": float(cost_row["investmentCosts"]),
                    "investment_cost_unit": cost_row["investmentCostsUnit"],
                    "installation_cost": float(cost_row["installationCosts"]),
                    "installation_cost_unit": cost_row["installationCostsUnit"],
                    "fixed_operational_cost": float(cost_row["fixedOperationalCosts"]),
                    "fixed_operational_cost_unit": cost_row["fixedOperationalCostsUnit"],
                    "variable_operational_cost": float(cost_row["variableOperationalCosts"]),
                    "variable_operational_cost_unit": cost_row["variableOperationalCostsUnit"],
                    "fixed_maintenance_cost": float(cost_row["fixedMaintenanceCosts"]),
                    "fixed_maintenance_cost_unit": cost_row["fixedMaintenanceCostsUnit"],
                    "variable_maintenance_cost": float(cost_row["variableMaintenanceCosts"]),
                    "variable_maintenance_cost_unit": cost_row["variableMaintenanceCostsUnit"],
                    "discount_rate": (
                        float(cost_row["discountRate"]) if "discountRate" in cost_row else 5.0
                    ),
                }
            )
        except (IndexError, KeyError) as e:
            logging.warning(f"Could not find cost data for asset {esdl_element.name}: {e}")
            return None

        # Get time series
        name = f"{model_name}_{esdl_element.id}"
        if name in time_series_dict.time_series:
            ts_data = time_series_dict.time_series[name]

            # Determine which time series to use based on asset type
            ts_mapping = {
                AssetType.PRODUCER: ["ThermalProduction"],
                AssetType.CONSUMER: ["ThermalConsumption"],
                AssetType.PUMP: ["ElectricalConsumption"],
                AssetType.PIPE: ["Speed"],
                AssetType.CONVERSION: ["ElectricalConsumption", "ThermalProduction"],
                AssetType.STORAGE: ["ElectricalConsumption"],
            }

            if asset_type in ts_mapping:
                for ts_name in ts_mapping[asset_type]:
                    if ts_name in ts_data:
                        values = [event.value for event in ts_data[ts_name].events]
                        time_step = ts_data[ts_name].get_time_step()

                        asset_dict["time_series"] = {
                            ts_name: TimeSeries(time_step=time_step, values=values)
                        }
                        break

        return Asset(**asset_dict)

    def _get_asset_type(self, esdl_element: esdl.Asset) -> Optional[AssetType]:
        """Get the asset type from an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            AssetType enum value or None if the element is not supported
        """
        if isinstance(esdl_element, esdl.GeothermalSource):
            return AssetType.GEOTHERMAL
        elif isinstance(esdl_element, esdl.Producer):
            return AssetType.PRODUCER
        elif isinstance(esdl_element, esdl.Consumer):
            return AssetType.CONSUMER
        elif isinstance(esdl_element, esdl.Storage):
            return AssetType.STORAGE
        elif isinstance(esdl_element, esdl.Conversion):
            return AssetType.CONVERSION
        elif isinstance(esdl_element, esdl.Pipe):
            return AssetType.PIPE
        elif isinstance(esdl_element, esdl.Pump):
            return AssetType.PUMP
        elif isinstance(esdl_element, esdl.Transport):
            return AssetType.TRANSPORT
        else:
            return None

    def _get_length(self, esdl_element: esdl.Asset) -> float:
        """Get the length of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Length in meters or 0.0 if not applicable
        """
        if isinstance(esdl_element, esdl.Pipe):
            return float(esdl_element.length) if esdl_element.length is not None else 0.0
        return 0.0

    def _get_power(self, esdl_element: esdl.Asset) -> float:
        """Get the power of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Power in watts or 0.0 if not applicable
        """
        if (
            (isinstance(esdl_element, esdl.Producer))
            or (isinstance(esdl_element, esdl.Consumer))
            or (isinstance(esdl_element, esdl.Conversion))
        ):
            if esdl_element.power is None:
                return 0.0
            return float(esdl_element.power)
        return 0.0

    def _get_cop(self, esdl_element: esdl.Asset) -> float:
        """Get the COP of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            COP or 0.0 if not applicable
        """
        if isinstance(esdl_element, esdl.GeothermalSource):
            if esdl_element.COP is None:
                return 0.0
            return float(esdl_element.COP)
        return 0.0

    def _get_volume(self, esdl_element: esdl.Asset) -> float:
        """Get the volume of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Volume in cubic meters or 0.0 if not applicable
        """
        if isinstance(esdl_element, esdl.Storage):
            if esdl_element.volume is None:
                return 0.0
            return float(esdl_element.volume)
        return 0.0

    def _get_tech_lifetime(self, esdl_element: esdl.Asset) -> float:
        """Get the technical lifetime of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Technical lifetime in years
        """
        if esdl_element.technicalLifetime is None:
            return 40.0
        if esdl_element.technicalLifetime == 0.0:
            logging.info(f"Technical life time not set or zero for asset {esdl_element.name}")
            return 40.0
        return float(esdl_element.technicalLifetime)

    def _get_aggregation_count(self, esdl_element: esdl.Asset) -> int:
        """Get the aggregation count of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Aggregation count or 0 if not applicable
        """
        if esdl_element.aggregationCount:
            return int(esdl_element.aggregationCount)
        return 0

    def _get_emission_factor(self, esdl_element: esdl.Asset) -> float:
        """Get the emission factor of an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            Emission factor in kg/GJ
        """
        # Uses ESDL carrier emission factors
        # TODO: Implement dynamic unit conversion based on ESDL emissionUnit specifications
        # (pending frontend team discussion)
        for port in esdl_element.port:
            if port.carrier is not None:
                if isinstance(port.carrier, esdl.EnergyCarrier):
                    return float(port.carrier.emission) / 1e9  # Convert to match old implementation
                return 0.0
        return 0.0
