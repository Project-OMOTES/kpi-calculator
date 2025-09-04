# src/kpicalculator/adapters/esdl_adapter.py
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from esdl import esdl  # type: ignore[import-untyped]
from esdl.esdl_handler import EnergySystemHandler  # type: ignore[import-untyped]

import pandas as pd  # type: ignore[import-untyped]

from .base_adapter import BaseAdapter, ValidationResult, MesidoResultsProtocol, SimulatorResultsProtocol
from .common_model import Asset, AssetType, EnergySystem, TimeSeries
from .database_time_series_loader import DatabaseTimeSeriesLoader
from ..security.credential_manager import CredentialManager
from .xml_time_series_adapter import PiXmlTimeSeries


class EsdlAdapter(BaseAdapter):
    """Adapter for loading energy system data from ESDL files with database support.
    
    Supports both XML time series files (for testing) and InfluxDB profiles 
    (for production) following the MESIDO pattern.
    """

    def __init__(self, unit_conversions: Optional[Dict[str, float]] = None,
                 credential_manager: Optional[CredentialManager] = None):
        """Initialize the ESDL adapter.

        Args:
            unit_conversions: Dictionary with unit conversion factors
            credential_manager: Optional secure credential manager for database access
        """
        super().__init__(unit_conversions)
        self.database_loader = DatabaseTimeSeriesLoader(credential_manager)
        self.logger = logging.getLogger(__name__)

    def load_data(self, 
                  source: Union[str, Path, MesidoResultsProtocol, SimulatorResultsProtocol], 
                  time_series_file: Optional[str] = None,
                  pipes_cost_file: Optional[str] = None,
                  assets_cost_file: Optional[str] = None,
                  use_database_profiles: bool = True,
                  validation_mode: bool = False) -> EnergySystem:
        """Load energy system data from ESDL file.
        
        Args:
            source: ESDL file path (only str/Path supported by this adapter)
            time_series_file: Optional XML time series file path (testing only)
            pipes_cost_file: Optional pipes cost CSV file path
            assets_cost_file: Optional assets cost CSV file path
            use_database_profiles: Whether to load InfluxDB profiles
            validation_mode: Whether to validate existing KPIs
                
        Returns:
            EnergySystem object
            
        Raises:
            TypeError: If source is not a file path (MESIDO/Simulator not supported)
        """
        # ESDL adapter only supports file paths
        if not isinstance(source, (str, Path)):
            raise TypeError(f"ESDL adapter only supports file paths, got {type(source)}")
        
        esdl_file = str(source)
        # Validate inputs
        validation_result = self.validate_source(esdl_file)
        if not validation_result.is_valid:
            raise ValueError(f"Invalid ESDL file: {validation_result.errors}")

        # Load ESDL file
        esh = EnergySystemHandler()
        es = esh.load_file(esdl_file)
        
        # Load time series data
        time_series_dict = {}
        
        # Priority 1: Load InfluxDB profiles from ESDL (production)
        if use_database_profiles:
            try:
                db_time_series, db_validation = self.database_loader.load_time_series_from_esdl(es)
                time_series_dict.update(db_time_series)
                
                if not db_validation.is_valid:
                    self.logger.warning(f"Database profile issues: {db_validation.errors}")
                    
                if db_validation.warnings:
                    for warning in db_validation.warnings:
                        self.logger.warning(warning)
                        
            except Exception as e:
                self.logger.warning(f"Failed to load database profiles: {e}")
        
        # Priority 2: Load XML time series (testing/fallback)
        xml_time_series = None
        if time_series_file:
            try:
                xml_time_series = PiXmlTimeSeries(time_series_file, "locationId", "parameterId")
                self.logger.info("Loaded XML time series for testing")
            except Exception as e:
                self.logger.warning(f"Failed to load XML time series: {e}")

        # Load cost data if provided
        pipe_costs = None
        asset_costs = None
        if pipes_cost_file:
            pipe_costs = pd.read_csv(pipes_cost_file)
        if assets_cost_file:
            asset_costs = pd.read_csv(assets_cost_file)

        # Create energy system
        model_name = Path(esdl_file).stem
        if "optimal_topology_mod" in model_name[-20:]:
            model_name = model_name[:-21]
        if "mod" in model_name[-4:]:
            model_name = model_name[:-4]

        energy_system = EnergySystem(
            name=model_name, assets=[], unit_conversion=self.unit_conversions or {}
        )

        # Process assets
        for esdl_element in es.eAllContents():
            if isinstance(esdl_element, esdl.Asset):
                if isinstance(esdl_element, esdl.Joint):
                    continue
                # Check if the asset is enabled
                if hasattr(esdl_element, 'state') and esdl_element.state and esdl_element.state.value != 0:
                    continue

                asset = self._create_asset_from_esdl(
                    esdl_element, time_series_dict, xml_time_series, pipe_costs, asset_costs, model_name
                )

                if asset:
                    energy_system.assets.append(asset)

        return energy_system

    def validate_source(self, source: Union[str, Path, MesidoResultsProtocol, SimulatorResultsProtocol]) -> ValidationResult:
        """Validate ESDL file path and basic structure.
        
        Args:
            source: Path to ESDL file
            
        Returns:
            ValidationResult indicating if source is valid
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        if not isinstance(source, str):
            errors.append("ESDL source must be a file path string")
            return ValidationResult(False, errors, warnings)
        
        file_path = Path(source)
        
        if not file_path.exists():
            errors.append(f"ESDL file does not exist: {source}")
        elif not file_path.is_file():
            errors.append(f"ESDL path is not a file: {source}")
        elif not file_path.suffix.lower() == '.esdl':
            warnings.append(f"File does not have .esdl extension: {source}")
        
        return ValidationResult(len(errors) == 0, errors, warnings)
    
    def get_supported_source_type(self) -> str:
        """Return identifier for ESDL adapter."""
        return "esdl"
    
    def get_supported_parameters(self) -> List[str]:
        """Return list of supported optional parameters."""
        return [
            "time_series_file",
            "pipes_cost_file", 
            "assets_cost_file",
            "use_database_profiles",
            "validation_mode"
        ]

    def _create_asset_from_esdl(
        self,
        esdl_element: esdl.Asset,
        db_time_series_dict: Dict[str, TimeSeries],
        xml_time_series_dict: Optional[PiXmlTimeSeries],
        pipe_costs: Optional[pd.DataFrame],
        asset_costs: Optional[pd.DataFrame],
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

        # Get cost properties from CSV files if provided
        if pipe_costs is not None or asset_costs is not None:
            if isinstance(esdl_element, esdl.Pipe):
                cost_df = pipe_costs
            else:
                cost_df = asset_costs

            if cost_df is not None:
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
                    self.logger.warning(f"Could not find cost data for asset {esdl_element.name}: {e}")
                    # Don't return None - continue without cost data

        # Get time series data - priority to database profiles
        time_series_data = {}
        
        # Priority 1: Database time series (production)
        if esdl_element.id in db_time_series_dict:
            time_series_data["DatabaseProfile"] = db_time_series_dict[esdl_element.id]
            self.logger.debug(f"Using database profile for asset {esdl_element.id}")
        
        # Priority 2: XML time series (testing/fallback)
        elif xml_time_series_dict is not None:
            name = f"{model_name}_{esdl_element.id}"
            if name in xml_time_series_dict.time_series:
                ts_data = xml_time_series_dict.time_series[name]

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

                            time_series_data[ts_name] = TimeSeries(time_step=time_step, values=values)
                            break
        
        if time_series_data:
            asset_dict["time_series"] = time_series_data

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
