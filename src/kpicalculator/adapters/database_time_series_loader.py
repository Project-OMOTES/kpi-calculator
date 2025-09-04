# src/kpicalculator/adapters/database_time_series_loader.py
"""Database time series loader following MESIDO InfluxDB pattern."""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from esdl import esdl
from esdl.profiles.influxdbprofilemanager import InfluxDBProfileManager
from esdl.units.conversion import ENERGY_IN_J, POWER_IN_W, convert_to_unit

from .common_model import TimeSeries
from .base_adapter import ValidationResult
from ..common.types import DatabaseCredentials
from ..exceptions import SecurityError, DatabaseError, CredentialError, ValidationError
from ..security.credential_manager import CredentialManager, create_default_credential_manager
from ..security.input_validator import InputValidator


logger = logging.getLogger(__name__)



class DatabaseTimeSeriesLoader:
    """Load time series data from database references in ESDL files.
    
    This follows the MESIDO pattern for InfluxDB connectivity, supporting
    InfluxDBProfile elements embedded in ESDL files with connection details.
    Uses secure credential management with no hard-coded credentials.
    """
    
    def __init__(self, credential_manager: Optional[CredentialManager] = None):
        """Initialize database loader with secure credential management.
        
        Args:
            credential_manager: Secure credential manager. Uses default if None.
        """
        self.credential_manager = credential_manager or create_default_credential_manager()
        
    def _get_secure_credentials(self, host: str, port: int) -> DatabaseCredentials:
        """Get credentials securely with no hard-coded fallbacks.
        
        Args:
            host: Database host
            port: Database port
            
        Returns:
            DatabaseCredentials from secure sources
            
        Raises:
            CredentialError: If no credentials found for the host:port combination
        """
        credentials = self.credential_manager.get_database_credentials(host, port)
        
        if not credentials:
            raise CredentialError(
                f"No credentials found for {host}:{port}. "
                f"Set environment variables or configure credentials file.",
                context={
                    "host": host,
                    "port": port,
                    "env_prefix": f"KPI_DB_{host.replace('.', '_').replace('-', '_').upper()}_{port}"
                }
            )
        
        return credentials
    
    def load_time_series_from_esdl(self, energy_system: esdl.EnergySystem) -> Tuple[Dict[str, TimeSeries], ValidationResult]:
        """Load all InfluxDB time series profiles from ESDL energy system.
        
        Args:
            energy_system: ESDL EnergySystem containing InfluxDBProfile elements
            
        Returns:
            Tuple of (time_series_dict, validation_result)
            - time_series_dict: Maps asset_id to TimeSeries objects
            - validation_result: Validation status and any warnings/errors
        """
        logger.info("Loading time series from InfluxDB profiles...")
        time_series_data = {}
        errors = []
        warnings = []
        
        try:
            # Find all InfluxDBProfile elements in the ESDL
            influx_profiles = [x for x in energy_system.eAllContents() 
                             if isinstance(x, esdl.InfluxDBProfile)]
            
            if not influx_profiles:
                warnings.append("No InfluxDB profiles found in ESDL file")
                return time_series_data, ValidationResult(True, [], warnings)
            
            for profile in influx_profiles:
                try:
                    # Extract asset ID associated with this profile
                    asset_id = self._extract_asset_id(profile)
                    
                    # Load time series data
                    time_series = self._load_profile_data(profile)
                    
                    if time_series:
                        time_series_data[asset_id] = time_series
                        logger.info(f"Loaded time series for asset {asset_id}")
                    
                except Exception as e:
                    error_msg = f"Failed to load profile for field {profile.field}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
        except Exception as e:
            errors.append(f"Failed to process InfluxDB profiles: {str(e)}")
            logger.error(f"Error loading time series: {str(e)}")
        
        validation_result = ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
        
        return time_series_data, validation_result
    
    def _extract_asset_id(self, profile: esdl.InfluxDBProfile) -> str:
        """Extract asset ID from InfluxDB profile container."""
        try:
            # Profile associated to asset port
            return profile.eContainer().energyasset.id
        except AttributeError:
            try:
                # Profile associated to carrier
                return profile.eContainer().id
            except AttributeError:
                # Fallback to using measurement as ID
                return profile.measurement
    
    def _load_profile_data(self, profile: esdl.InfluxDBProfile) -> Optional[TimeSeries]:
        """Load data for a single InfluxDB profile.
        
        Args:
            profile: ESDL InfluxDBProfile element
            
        Returns:
            TimeSeries object with loaded data, or None if loading failed
        """
        try:
            # Get database credentials
            credentials = self._get_credentials_for_profile(profile)
            
            # Create InfluxDB profile manager
            time_series_data = InfluxDBProfileManager.create_esdl_influxdb_profile_manager(
                profile,
                credentials.username,
                credentials.password,
                credentials.ssl,
                credentials.verify_ssl
            )
            
            # Validate profile data
            self._validate_profile_data(profile, time_series_data)
            
            # Convert to pandas DataFrame
            data_points = {
                t[0].strftime("%Y-%m-%dT%H:%M:%SZ"): t[1] 
                for t in time_series_data.profile_data_list
            }
            df = pd.DataFrame.from_dict(data_points, orient="index")
            df.index = pd.to_datetime(df.index, utc=True)
            
            # Convert units to standard format
            df = self._convert_units(df, profile)
            
            # Apply multiplier
            df = df * profile.multiplier
            
            # Convert to TimeSeries
            return TimeSeries(
                time_step=3600.0,  # 1 hour in seconds
                values=df.values.flatten().tolist()
            )
            
        except Exception as e:
            logger.error(f"Failed to load profile data: {str(e)}")
            return None
    
    def _get_credentials_for_profile(self, profile: esdl.InfluxDBProfile) -> DatabaseCredentials:
        """Get database credentials for InfluxDB profile securely.
        
        Args:
            profile: ESDL InfluxDBProfile element
            
        Returns:
            DatabaseCredentials from secure sources
            
        Raises:
            CredentialError: If no credentials found for the profile
        """
        # Parse host from profile (handle URL prefixes)
        profile_host = profile.host
        ssl_setting = False
        
        # Handle https/http prefixes
        if "https" in profile_host:
            profile_host = profile_host[8:]
            ssl_setting = True
        elif "http" in profile_host:
            profile_host = profile_host[7:]
        
        if profile.port == 443:
            ssl_setting = True
        
        try:
            credentials = self._get_secure_credentials(profile_host, profile.port)
            
            # Validate credentials for security
            InputValidator.validate_database_credentials(credentials)
            
            # Override SSL setting from profile if needed
            if ssl_setting and not credentials.ssl:
                # Create new credentials with corrected SSL setting
                credentials = DatabaseCredentials(
                    host=credentials.host,
                    port=credentials.port,
                    username=credentials.username,
                    password=credentials.password,
                    database=credentials.database,
                    ssl=ssl_setting,
                    verify_ssl=credentials.verify_ssl
                )
                
                # Re-validate modified credentials
                InputValidator.validate_database_credentials(credentials)
            
            return credentials
            
        except CredentialError as e:
            # Add profile context to the error
            raise CredentialError(
                f"Cannot load credentials for InfluxDB profile: {e}",
                context={
                    **e.context,
                    "profile_host": profile.host,
                    "profile_port": profile.port,
                    "profile_database": profile.database,
                    "profile_field": profile.field,
                    "profile_measurement": profile.measurement
                }
            ) from e
    
    def _validate_profile_data(self, profile: esdl.InfluxDBProfile, 
                             time_series_data) -> None:
        """Validate profile data following MESIDO pattern."""
        # Validate start/end dates match
        if time_series_data.end_datetime != profile.endDate:
            raise ValueError(
                f"Profile end datetime mismatch: expected {profile.endDate}, "
                f"got {time_series_data.end_datetime} for field {profile.field}"
            )
        
        if time_series_data.start_datetime != profile.startDate:
            raise ValueError(
                f"Profile start datetime mismatch: expected {profile.startDate}, "
                f"got {time_series_data.start_datetime} for field {profile.field}"
            )
        
        # Validate data range consistency
        if time_series_data.start_datetime != time_series_data.profile_data_list[0][0]:
            raise ValueError(
                f"Start datetime inconsistency in profile data for field {profile.field}"
            )
        
        if time_series_data.end_datetime != time_series_data.profile_data_list[-1][0]:
            raise ValueError(
                f"End datetime inconsistency in profile data for field {profile.field}"
            )
        
        # Validate time resolution (expect hourly data)
        for i in range(len(time_series_data.profile_data_list) - 1):
            time_resolution = (
                time_series_data.profile_data_list[i + 1][0] - 
                time_series_data.profile_data_list[i][0]
            )
            if time_resolution.seconds != 3600:
                raise ValueError(
                    f"Expected 3600s time resolution, got {time_resolution.seconds}s "
                    f"for profile {profile.measurement}-{profile.field}"
                )
    
    def _convert_units(self, df: pd.DataFrame, profile: esdl.InfluxDBProfile) -> pd.DataFrame:
        """Convert units to standard format following MESIDO pattern."""
        try:
            # Get physical quantity
            try:
                unit = profile.profileQuantityAndUnit.reference.physicalQuantity
            except AttributeError:
                unit = profile.profileQuantityAndUnit.physicalQuantity
            
            # Convert based on physical quantity
            for i in range(len(df)):
                if unit == esdl.PhysicalQuantityEnum.POWER:
                    df.iloc[i] = convert_to_unit(
                        df.iloc[i], profile.profileQuantityAndUnit, POWER_IN_W
                    )
                elif unit == esdl.PhysicalQuantityEnum.ENERGY:
                    df.iloc[i] = convert_to_unit(
                        df.iloc[i], profile.profileQuantityAndUnit, ENERGY_IN_J
                    )
                elif unit == esdl.PhysicalQuantityEnum.COST:
                    # No unit conversion for cost
                    pass
                else:
                    logger.warning(f"Unsupported physical quantity: {unit}")
            
            return df
            
        except Exception as e:
            logger.warning(f"Unit conversion failed: {str(e)}, using original values")
            return df
    
    def set_credential_manager(self, credential_manager: CredentialManager) -> None:
        """Set a new credential manager.
        
        Args:
            credential_manager: New credential manager to use
        """
        self.credential_manager = credential_manager
        logger.info("Updated credential manager")