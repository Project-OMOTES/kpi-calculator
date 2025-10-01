# src/kpicalculator/adapters/esdl_adapter.py
import logging
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]
from esdl import esdl  # type: ignore[import-untyped]
from esdl.esdl_handler import EnergySystemHandler  # type: ignore[import-untyped]

from ..common.constants import (
    COMPOSITE_KEY_SEPARATOR,
    DEFAULT_TECHNICAL_LIFETIME_YEARS,
    MOD_SUFFIX_LENGTH,
    OPTIMAL_TOPOLOGY_SUFFIX,
    OPTIMAL_TOPOLOGY_SUFFIX_LENGTH,
)
from ..exceptions import SecurityError, ValidationError
from ..security.credential_manager import CredentialManager
from ..security.input_validator import InputValidator
from .base_adapter import (
    BaseAdapter,
    MesidoResultsProtocol,
    SimulatorResultsProtocol,
    ValidationResult,
)
from .common_model import Asset, AssetType, EnergySystem, TimeSeries
from .database_time_series_loader import DatabaseTimeSeriesLoader
from .time_series_manager import TimeSeriesManager
from .xml_time_series_adapter import PiXmlTimeSeries


class EsdlAdapter(BaseAdapter):
    """Adapter for loading energy system data from ESDL files with database support.

    Supports both XML time series files (for testing) and InfluxDB profiles
    (for production) following the MESIDO pattern.
    """

    def __init__(
        self,
        unit_conversions: dict[str, float] | None = None,
        credential_manager: CredentialManager | None = None,
    ):
        """Initialize the ESDL adapter.

        Args:
            unit_conversions: Dictionary with unit conversion factors
            credential_manager: Optional secure credential manager for database access
        """
        super().__init__(unit_conversions)
        self.database_loader = DatabaseTimeSeriesLoader(credential_manager)
        # Session-level warning tracking to prevent log spam
        self._logged_warnings: set[str] = set()
        self._legacy_asset_count = 0
        self.time_series_manager = TimeSeriesManager(credential_manager)
        self.logger = logging.getLogger(__name__)

    def load_data(
        self,
        source: str | Path | MesidoResultsProtocol | SimulatorResultsProtocol,
        time_series_file: str | None = None,
        pipes_cost_file: str | None = None,
        assets_cost_file: str | None = None,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
        use_database_profiles: bool = True,
        validation_mode: bool = False,
    ) -> EnergySystem:
        """Load energy system data from ESDL file.

        Args:
            source: ESDL file path (only str/Path supported by this adapter)
            time_series_file: Optional XML time series file path (testing only)
            pipes_cost_file: Optional pipes cost CSV file path
            assets_cost_file: Optional assets cost CSV file path
            timeseries_dataframes: Optional dict mapping asset IDs to pandas DataFrames
                with time-indexed energy/power data. When provided, takes precedence
                over database loading and time_series_file parameter.
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
        # Validate inputs with security checks
        validation_result = self.validate_source(esdl_file)
        if not validation_result.is_valid:
            raise ValueError(f"Invalid ESDL file: {validation_result.errors}")

        # Secure file path validation
        try:
            secure_esdl_path = InputValidator.validate_file_path(
                esdl_file, allowed_extensions=[".esdl"], must_exist=True
            )
            esdl_file = str(secure_esdl_path)
        except (ValidationError, SecurityError) as e:
            raise ValidationError(f"ESDL file security validation failed: {e}") from e

        # Load ESDL file
        esh = EnergySystemHandler()
        es = esh.load_file(esdl_file)

        # Load time series data using centralized TimeSeriesManager
        source_priority = ["dataframes"]
        if use_database_profiles:
            source_priority.append("database")
        if time_series_file:
            source_priority.append("xml")
        source_priority.append("empty")

        time_series_dict, ts_validation = self.time_series_manager.load_time_series(
            es,
            timeseries_dataframes=timeseries_dataframes,
            xml_file=time_series_file,
            source_priority=source_priority,
        )

        # Log time series loading results
        if not ts_validation.is_valid:
            for error in ts_validation.errors:
                self.logger.error(f"Time series loading error: {error}")
        for warning in ts_validation.warnings:
            self.logger.warning(f"Time series loading warning: {warning}")

        # Create XML time series adapter for asset processing (legacy compatibility)
        xml_time_series = None
        if time_series_file:
            try:
                xml_time_series = PiXmlTimeSeries(time_series_file, "locationId", "parameterId")
                self.logger.debug("Created XML time series adapter for legacy compatibility")
            except Exception as e:
                self.logger.warning(f"Failed to create XML time series adapter: {e}")

        # Load cost data if provided
        pipe_costs = None
        asset_costs = None
        if pipes_cost_file:
            pipe_costs = pd.read_csv(pipes_cost_file)
        if assets_cost_file:
            asset_costs = pd.read_csv(assets_cost_file)

        # Create energy system
        model_name = Path(esdl_file).stem
        if OPTIMAL_TOPOLOGY_SUFFIX in model_name[-20:]:
            model_name = model_name[:-OPTIMAL_TOPOLOGY_SUFFIX_LENGTH]
        if "mod" in model_name[-4:]:
            model_name = model_name[:-MOD_SUFFIX_LENGTH]

        energy_system = EnergySystem(
            name=model_name,
            assets=[],
            unit_conversion=self.unit_conversions or {},
            source_metadata={"esdl_file": str(esdl_file)},
        )

        # Process assets
        for esdl_element in es.eAllContents():
            if isinstance(esdl_element, esdl.Asset):
                if isinstance(esdl_element, esdl.Joint):
                    continue
                # Check if the asset is enabled
                if (
                    hasattr(esdl_element, "state")
                    and esdl_element.state
                    and esdl_element.state.value != 0
                ):
                    continue

                asset = self._create_asset_from_esdl(
                    esdl_element,
                    time_series_dict,
                    xml_time_series,
                    pipe_costs,
                    asset_costs,
                    model_name,
                )

                if asset:
                    energy_system.assets.append(asset)

        # Log summary of any session warnings to provide final context
        self._log_session_summary()

        return energy_system

    def validate_source(
        self, source: str | Path | MesidoResultsProtocol | SimulatorResultsProtocol
    ) -> ValidationResult:
        """Validate ESDL file path and basic structure.

        Args:
            source: Path to ESDL file

        Returns:
            ValidationResult indicating if source is valid
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(source, str):
            errors.append("ESDL source must be a file path string")
            return ValidationResult(False, errors, warnings)

        file_path = Path(source)

        if not file_path.exists():
            errors.append(f"ESDL file does not exist: {source}")
        elif not file_path.is_file():
            errors.append(f"ESDL path is not a file: {source}")
        elif file_path.suffix.lower() != ".esdl":
            warnings.append(f"File does not have .esdl extension: {source}")

        return ValidationResult(len(errors) == 0, errors, warnings)

    def get_supported_source_type(self) -> str:
        """Return identifier for ESDL adapter."""
        return "esdl"

    def get_supported_parameters(self) -> list[str]:
        """Return list of supported optional parameters."""
        return [
            "time_series_file",
            "pipes_cost_file",
            "assets_cost_file",
            "use_database_profiles",
            "validation_mode",
        ]

    def _create_asset_from_esdl(
        self,
        esdl_element: esdl.Asset,
        time_series_dict: dict[str, TimeSeries],
        xml_time_series_dict: PiXmlTimeSeries | None,
        pipe_costs: pd.DataFrame | None,
        asset_costs: pd.DataFrame | None,
        model_name: str,
    ) -> Asset | None:
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
            cost_df = pipe_costs if isinstance(esdl_element, esdl.Pipe) else asset_costs

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
                            "variable_operational_cost": float(
                                cost_row["variableOperationalCosts"]
                            ),
                            "variable_operational_cost_unit": cost_row[
                                "variableOperationalCostsUnit"
                            ],
                            "fixed_maintenance_cost": float(cost_row["fixedMaintenanceCosts"]),
                            "fixed_maintenance_cost_unit": cost_row["fixedMaintenanceCostsUnit"],
                            "variable_maintenance_cost": float(
                                cost_row["variableMaintenanceCosts"]
                            ),
                            "variable_maintenance_cost_unit": cost_row[
                                "variableMaintenanceCostsUnit"
                            ],
                            "discount_rate": (
                                float(cost_row["discountRate"])
                                if "discountRate" in cost_row
                                else 5.0
                            ),
                        }
                    )
                except (IndexError, KeyError) as e:
                    self.logger.warning(
                        f"Could not find cost data for asset {esdl_element.name}: {e}"
                    )
                    # Don't return None - continue without cost data

        # Get time series data - priority to database profiles
        time_series_data = {}

        # Priority 1: Database time series (production)
        # Check for any time series with composite keys (asset_id|field_name)
        for composite_key, ts_data in time_series_dict.items():
            if COMPOSITE_KEY_SEPARATOR in composite_key:
                asset_id, field_name = composite_key.split(COMPOSITE_KEY_SEPARATOR, 1)
                if asset_id == esdl_element.id:
                    # Use the field name from InfluxDBProfile as the time series key
                    time_series_data[field_name] = ts_data
                    self.logger.debug(
                        f"Using database profile for asset {esdl_element.id} "
                        f"parameter '{field_name}'"
                    )

        # Fallback: check for direct asset_id key (legacy single-parameter systems)
        if not time_series_data and esdl_element.id in time_series_dict:
            # For legacy systems that don't specify parameter names, we cannot arbitrarily
            # assign parameter types. Log a warning once per session and track count.
            self._legacy_asset_count += 1
            warning_key = "legacy_time_series_without_parameters"

            if warning_key not in self._logged_warnings:
                self.logger.warning(
                    f"Found assets with time series data but no parameter information. "
                    f"Use InfluxDBProfile.field or XML parameterId for proper parameter mapping. "
                    f"(First occurrence: asset {esdl_element.id})"
                )
                self._logged_warnings.add(warning_key)
            # Don't add arbitrary mappings - let the system work without time series for this asset

        if time_series_data:
            asset_dict["time_series"] = time_series_data

        # Validate asset properties for security and data integrity
        try:
            validated_asset_dict = InputValidator.validate_asset_properties(asset_dict)
            return Asset(**validated_asset_dict)
        except (ValidationError, SecurityError) as e:
            self.logger.warning(f"Asset validation failed for {esdl_element.id}: {e}")
            # Return None to skip invalid assets rather than failing completely
            return None

    def _get_asset_type(self, esdl_element: esdl.Asset) -> AssetType | None:
        """Get the asset type from an ESDL element.

        Args:
            esdl_element: ESDL element

        Returns:
            AssetType enum value or None if the element is not supported
        """
        if isinstance(esdl_element, esdl.GeothermalSource):
            return AssetType.GEOTHERMAL
        if isinstance(esdl_element, esdl.Producer):
            return AssetType.PRODUCER
        if isinstance(esdl_element, esdl.Consumer):
            return AssetType.CONSUMER
        if isinstance(esdl_element, esdl.Storage):
            return AssetType.STORAGE
        if isinstance(esdl_element, esdl.Conversion):
            return AssetType.CONVERSION
        if isinstance(esdl_element, esdl.Pipe):
            return AssetType.PIPE
        if isinstance(esdl_element, esdl.Pump):
            return AssetType.PUMP
        if isinstance(esdl_element, esdl.Transport):
            return AssetType.TRANSPORT
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
        if isinstance(esdl_element, (esdl.Producer, esdl.Consumer, esdl.Conversion)):
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
            return DEFAULT_TECHNICAL_LIFETIME_YEARS
        if esdl_element.technicalLifetime == 0.0:
            logging.info(f"Technical life time not set or zero for asset {esdl_element.name}")
            return DEFAULT_TECHNICAL_LIFETIME_YEARS
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

    def _log_session_summary(self) -> None:
        """Log summary of session warnings to provide context without spam."""
        if self._legacy_asset_count > 0:
            self.logger.info(
                f"Session summary: {self._legacy_asset_count} assets had time series data "
                f"without parameter information. Consider upgrading to InfluxDBProfile "
                f"with field names for proper parameter mapping."
            )
