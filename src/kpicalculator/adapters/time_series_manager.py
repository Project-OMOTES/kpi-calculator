# src/kpicalculator/adapters/time_series_manager.py
"""Centralized time series loading with multiple source support."""

import logging

import pandas as pd
from esdl import esdl
from esdl.profiles.profilemanager import ProfileManager, ProfileType

from ..common.constants import COMPOSITE_KEY_SEPARATOR
from ..security.credential_manager import CredentialManager
from .base_adapter import ValidationResult
from .common_model import TimeSeries
from .database_time_series_loader import DatabaseTimeSeriesLoader
from .time_series_protocols import TimeSeriesProvider
from .xml_time_series_adapter import PiXmlTimeSeries


class TimeSeriesManager:
    """Centralized time series loading with multiple source support.

    This class implements the Factory pattern to provide a single entry point
    for loading time series data from various sources (DataFrame, database, XML)
    with configurable priority and graceful degradation.
    """

    def __init__(self, credential_manager: CredentialManager | None = None):
        """Initialize TimeSeriesManager with required components.

        Args:
            credential_manager: Manager for secure database credentials
        """
        self.database_loader = DatabaseTimeSeriesLoader(credential_manager)
        self.logger = logging.getLogger(__name__)

    def load_time_series(
        self,
        energy_system: esdl.EnergySystem,
        timeseries_dataframes: dict[str, pd.DataFrame] | None = None,
        xml_file: str | None = None,
        source_priority: list[str] | None = None,
    ) -> tuple[dict[str, TimeSeries], ValidationResult]:
        """Single entry point for all time series loading with source priority.

        Args:
            energy_system: ESDL energy system containing asset definitions
            timeseries_dataframes: Optional dict mapping asset IDs to pandas DataFrames
                with time-indexed energy/power data. When provided, takes precedence
                over database loading.
            xml_file: Optional XML time series file path (testing only)
            source_priority: Optional list defining loading priority
                Default: ["dataframes", "database", "xml", "empty"]

        Returns:
            Tuple of (time_series_dict, validation_result)

        Raises:
            ValidationError: If critical validation fails across all sources
        """
        # Default priority: DataFrames → Database → XML → Empty
        priority = source_priority or ["dataframes", "database", "xml", "empty"]

        validation_results = []

        for source in priority:
            try:
                if source == "dataframes" and timeseries_dataframes:
                    self.logger.info("Loading time series from pandas DataFrames")
                    return self._load_from_dataframes(timeseries_dataframes, energy_system)

                if source == "database" and self._has_database_profiles(energy_system):
                    self.logger.info("Loading time series from InfluxDB database")
                    return self.database_loader.load_time_series_from_esdl(energy_system)

                if source == "xml" and xml_file:
                    self.logger.info(f"Loading time series from XML file: {xml_file}")
                    return self._load_from_xml(xml_file, energy_system)

            except Exception as e:
                error_msg = f"Failed to load time series from {source}: {e}"
                self.logger.warning(error_msg)
                validation_results.append(error_msg)
                continue

        # If no sources succeeded, return empty with warnings
        self.logger.info("No time series data loaded - using empty time series")
        return {}, ValidationResult(
            is_valid=True, warnings=["No time series data loaded"] + validation_results
        )

    def _load_from_dataframes(
        self, dataframes: dict[str, pd.DataFrame], energy_system: esdl.EnergySystem
    ) -> tuple[dict[str, TimeSeries], ValidationResult]:
        """Load time series from pandas DataFrames using pyESDL ProfileManager.

        Args:
            dataframes: Dict mapping asset IDs to pandas DataFrames
            energy_system: ESDL energy system for validation

        Returns:
            Tuple of (time_series_dict, validation_result)
        """
        time_series_dict = {}
        issues = []

        # Validate DataFrame format and content
        validation_result = self._validate_dataframe_time_series(dataframes, energy_system)

        for asset_id, df in dataframes.items():
            try:
                # Validate DataFrame is not empty
                if df.empty:
                    issues.append(f"Empty DataFrame for asset {asset_id}")
                    continue

                # Use pyESDL ProfileManager for proper conversion
                profile_manager = ProfileManager()

                # Convert DataFrame to ProfileManager format
                profile_header = ["datetime", "value"]  # pyESDL expects 'datetime' as first column
                profile_data_list = [
                    [timestamp.isoformat(), value]
                    for timestamp, value in zip(
                        df.index.tolist(), df.iloc[:, 0].tolist(), strict=True
                    )
                ]

                # Set profile data using pyESDL ProfileManager
                profile_manager.set_profile(
                    profile_header=profile_header,
                    profile_data_list=profile_data_list,
                    profile_type=ProfileType.TIMESERIES,
                )

                # Detect time step from DataFrame index
                time_step = self._detect_time_step(df)

                # Convert to internal TimeSeries format
                # This maintains compatibility with existing KPI calculators
                time_series_dict[asset_id] = TimeSeries(
                    time_step=time_step,
                    values=df.iloc[:, 0].tolist(),
                )

                self.logger.debug(
                    f"Converted DataFrame for asset {asset_id}: {len(df)} data points"
                )

            except Exception as e:
                error_msg = f"Failed to convert DataFrame for asset {asset_id}: {e}"
                self.logger.error(error_msg)
                issues.append(error_msg)
                continue

        # Combine validation results
        combined_validation = ValidationResult(
            is_valid=validation_result.is_valid and len(issues) == 0,
            errors=validation_result.errors + issues,
            warnings=validation_result.warnings,
        )

        return time_series_dict, combined_validation

    def _validate_dataframe_time_series(
        self, dataframes: dict[str, pd.DataFrame], energy_system: esdl.EnergySystem
    ) -> ValidationResult:
        """Validate DataFrame time series against ESDL assets.

        Args:
            dataframes: Dict mapping asset IDs to pandas DataFrames
            energy_system: ESDL energy system for validation

        Returns:
            ValidationResult with validation status and issues
        """
        issues = []
        warnings = []

        # Extract asset IDs from ESDL
        esdl_asset_ids = {
            asset.id
            for asset in energy_system.eAllContents()
            if isinstance(asset, esdl.Asset) and asset.id
        }

        # Check DataFrame keys match asset IDs
        dataframe_ids = set(dataframes.keys())
        missing_assets = esdl_asset_ids - dataframe_ids
        unknown_assets = dataframe_ids - esdl_asset_ids

        if missing_assets:
            warnings.append(f"Missing DataFrames for assets: {missing_assets}")
        if unknown_assets:
            warnings.append(f"Unknown assets in DataFrames: {unknown_assets}")

        # Validate DataFrame structure
        for asset_id, df in dataframes.items():
            if df.empty:
                issues.append(f"Empty DataFrame for asset {asset_id}")
                continue

            if not isinstance(df.index, pd.DatetimeIndex):
                issues.append(f"DataFrame for {asset_id} must have DatetimeIndex")
                continue

            if df.isnull().any().any():
                issues.append(f"DataFrame for {asset_id} contains null values")
                continue

            # Check for reasonable data ranges
            values = df.iloc[:, 0]
            if (values < 0).any():
                warnings.append(f"DataFrame for {asset_id} contains negative values")

            if values.max() > 1e9:  # Very large values might indicate unit issues
                warnings.append(
                    f"DataFrame for {asset_id} contains very large values - check units"
                )

        return ValidationResult(is_valid=len(issues) == 0, errors=issues, warnings=warnings)

    def _detect_time_step(self, df: pd.DataFrame) -> float:
        """Detect time step from DataFrame DatetimeIndex.

        Args:
            df: DataFrame with DatetimeIndex

        Returns:
            Time step in seconds (default: 3600.0 for hourly)
        """
        if len(df) < 2:
            self.logger.warning("DataFrame has less than 2 points, defaulting to hourly time step")
            return 3600.0

        try:
            # Calculate differences between consecutive timestamps
            time_diffs: pd.Series = pd.Series(df.index[1:] - df.index[:-1])

            # Check if all time steps are equal (current requirement)
            unique_diffs = time_diffs.unique()
            if len(unique_diffs) > 1:
                # For now, require equally spaced time steps
                # TODO: Future enhancement - support variable time steps
                diff_seconds_all = [diff.total_seconds() for diff in unique_diffs]
                min_diff = min(diff_seconds_all)
                max_diff = max(diff_seconds_all)
                mean_diff = sum(diff_seconds_all) / len(diff_seconds_all)
                count_unique = len(diff_seconds_all)
                raise ValueError(
                    f"Non-uniform time steps detected: min={min_diff}, max={max_diff}, "
                    f"mean={mean_diff:.1f}, count={count_unique}. "
                    "Currently only equally spaced time series are supported."
                )

            # All time steps are equal - use the common interval
            time_step_timedelta = unique_diffs[0]
            time_step_seconds = time_step_timedelta.total_seconds()

            self.logger.debug(f"Detected uniform time step: {time_step_seconds} seconds")
            return float(time_step_seconds)

        except ValueError:
            # Re-raise validation errors for non-uniform time steps
            raise
        except Exception as e:
            self.logger.warning(f"Failed to detect time step: {e}, defaulting to hourly")
            return 3600.0

    def _has_database_profiles(self, energy_system: esdl.EnergySystem) -> bool:
        """Check if energy system contains InfluxDB profile references.

        Args:
            energy_system: ESDL energy system to check

        Returns:
            True if database profiles are found, False otherwise
        """
        influx_profiles = [
            x for x in energy_system.eAllContents() if isinstance(x, esdl.InfluxDBProfile)
        ]
        return len(influx_profiles) > 0

    def _load_from_xml(
        self, xml_file: str, energy_system: esdl.EnergySystem
    ) -> tuple[dict[str, TimeSeries], ValidationResult]:
        """Load time series from XML file (testing/fallback).

        Args:
            xml_file: Path to XML time series file
            energy_system: ESDL energy system for validation

        Returns:
            Tuple of (time_series_dict, validation_result)
        """
        try:
            # Use PiXmlTimeSeries adapter with clear interface contract
            xml_adapter: TimeSeriesProvider = PiXmlTimeSeries(xml_file, "locationId", "parameterId")
            time_series_dict = {}
            warnings = []

            # Extract asset IDs from ESDL to match time series
            esdl_asset_ids = {
                asset.id
                for asset in energy_system.eAllContents()
                if isinstance(asset, esdl.Asset) and asset.id
            }

            # Extract all time series with parameter information from XML
            # Use public interface to preserve parameter names
            try:
                asset_parameters = xml_adapter.get_time_series_with_parameters()
                for asset_id, parameters in asset_parameters.items():
                    if asset_id in esdl_asset_ids:
                        for parameter_name, (values, time_step) in parameters.items():
                            # Create composite key to preserve parameter information
                            composite_key = f"{asset_id}{COMPOSITE_KEY_SEPARATOR}{parameter_name}"
                            time_series_dict[composite_key] = TimeSeries(
                                time_step=time_step,
                                values=values,
                            )
                            self.logger.debug(
                                f"Loaded XML time series for asset {asset_id} "
                                f"parameter {parameter_name} with time step {time_step}s"
                            )
            except Exception as e:
                warnings.append(f"Failed to access XML time series with parameter info: {e}")

            # Fallback: use the simplified interface if parameter extraction fails
            if not time_series_dict:
                try:
                    for key, value in xml_adapter.time_series.items():
                        if key in esdl_asset_ids and value:
                            time_series_dict[key] = TimeSeries(
                                time_step=3600.0,
                                values=value,
                            )
                            warnings.append(
                                f"XML time series for {key} loaded without parameter information"
                            )
                except Exception as e:
                    warnings.append(f"Failed to access time_series property: {e}")

            return time_series_dict, ValidationResult(is_valid=True, warnings=warnings)

        except Exception as e:
            error_msg = f"Failed to load XML time series from {xml_file}: {e}"
            self.logger.error(error_msg)
            return {}, ValidationResult(is_valid=False, errors=[error_msg])
