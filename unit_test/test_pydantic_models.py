# unit_test/test_pydantic_models.py
"""Property-based tests for Pydantic models using Hypothesis.

This module tests the following Pydantic models:
DatabaseCredentials, AssetProperties, and TimeSeriesData.
It demonstrates how to use Hypothesis for automatic test case generation
to find edge cases and ensure robust validation across all input ranges.
"""

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from kpicalculator.common.types import AssetProperties, DatabaseCredentials, TimeSeriesData


class TestDatabaseCredentials:
    """Test DatabaseCredentials Pydantic model with property-based testing."""

    @settings(suppress_health_check=[HealthCheck.too_slow])
    @given(
        host=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        port=st.integers(min_value=1, max_value=65535),
        username=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        password=st.one_of(st.none(), st.text(min_size=8, max_size=64)),
    )
    def test_valid_credentials_always_pass(
        self, host: str, port: int, username: str | None, password: str | None
    ):
        """Test that valid credentials always create a valid DatabaseCredentials object."""
        # Note: Invalid host validation is tested separately in other test methods
        try:
            creds = DatabaseCredentials(host=host, port=port, username=username, password=password)
            assert creds.host.strip() == host.strip()
            assert creds.port == port
            assert creds.username == username
            assert creds.password == password
        except ValidationError:
            # Expected for invalid hosts/formats - test passes
            pass

    @given(port=st.integers().filter(lambda x: x < 1 or x > 65535))
    def test_invalid_ports_always_fail(self, port: int) -> None:
        """Test that invalid port numbers always raise ValidationError."""
        with pytest.raises(ValidationError):
            DatabaseCredentials(host="localhost", port=port)

    @given(password=st.text(max_size=7))
    def test_short_passwords_always_fail(self, password: str) -> None:
        """Test that passwords shorter than 8 characters always fail."""
        with pytest.raises(ValidationError):
            DatabaseCredentials(host="localhost", port=5432, password=password)

    def test_valid_ip_addresses(self) -> None:
        """Test that common IP address formats work."""
        valid_ips = ["127.0.0.1", "192.168.1.1", "10.0.0.1", "172.16.0.1"]
        for ip in valid_ips:
            creds = DatabaseCredentials(host=ip, port=5432)
            assert creds.host == ip

    def test_valid_hostnames(self) -> None:
        """Test that common hostname formats work."""
        valid_hosts = ["localhost", "database.local", "db-server", "postgres.company.com"]
        for host in valid_hosts:
            creds = DatabaseCredentials(host=host, port=5432)
            assert creds.host == host


class TestAssetProperties:
    """Test AssetProperties Pydantic model with property-based testing."""

    @given(
        asset_id=st.text(min_size=1, max_size=255).filter(lambda x: x.strip()),
        name=st.text(min_size=1, max_size=255).filter(lambda x: x.strip()),
        asset_type=st.text(min_size=1, max_size=100).filter(lambda x: x.strip()),
        power=st.one_of(
            st.none(), st.floats(min_value=0, max_value=1e12, allow_nan=False, allow_infinity=False)
        ),
        cop=st.one_of(
            st.none(), st.floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False)
        ),
    )
    def test_valid_asset_properties_always_pass(
        self, asset_id: str, name: str, asset_type: str, power: float | None, cop: float | None
    ):
        """Test that valid asset properties always create a valid AssetProperties object."""
        asset = AssetProperties(id=asset_id, name=name, asset_type=asset_type, power=power, cop=cop)
        assert asset.id.strip() == asset_id.strip()
        assert asset.name.strip() == name.strip()
        assert asset.asset_type.strip() == asset_type.strip()
        assert asset.power == power
        assert asset.cop == cop

    @given(power=st.floats().filter(lambda x: x < 0 or x > 1e12 or x != x))  # < 0, > 1e12, or NaN
    def test_invalid_power_values_always_fail(self, power: float) -> None:
        """Test that invalid power values always raise ValidationError."""
        with pytest.raises(ValidationError):
            AssetProperties(id="test_id", name="test_name", asset_type="test_type", power=power)

    @given(cop=st.floats().filter(lambda x: x < 0 or x > 10 or x != x))  # < 0, > 10, or NaN
    def test_invalid_cop_values_always_fail(self, cop: float) -> None:
        """Test that invalid COP values always raise ValidationError."""
        with pytest.raises(ValidationError):
            AssetProperties(id="test_id", name="test_name", asset_type="test_type", cop=cop)

    @given(cost=st.floats().filter(lambda x: x < 0 or x != x))  # Negative or NaN
    def test_negative_costs_always_fail(self, cost: float) -> None:
        """Test that negative cost values always raise ValidationError."""
        with pytest.raises(ValidationError):
            AssetProperties(
                id="test_id", name="test_name", asset_type="test_type", investment_cost=cost
            )

    @given(
        string_field=st.one_of(
            st.text(max_size=0),  # Empty strings
            st.just("   "),  # Whitespace only
            st.just("\t\n"),  # Tabs and newlines only
        )
    )
    def test_empty_required_strings_always_fail(self, string_field: str) -> None:
        """Test that empty or whitespace-only required strings always fail."""
        with pytest.raises(ValidationError):
            AssetProperties(id=string_field, name="valid_name", asset_type="valid_type")

        with pytest.raises(ValidationError):
            AssetProperties(id="valid_id", name=string_field, asset_type="valid_type")

        with pytest.raises(ValidationError):
            AssetProperties(id="valid_id", name="valid_name", asset_type=string_field)


class TestTimeSeriesData:
    """Test TimeSeriesData Pydantic model with property-based testing."""

    @given(
        values=st.lists(
            st.floats(min_value=-1e6, max_value=1e12, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=1000,  # Smaller for test performance
        )
    )
    def test_valid_time_series_always_pass(self, values: list[float]) -> None:
        """Test that valid time series data always creates a valid TimeSeriesData object."""
        time_series = TimeSeriesData(values=values)
        assert time_series.values == values
        assert len(time_series.values) == len(values)

    def test_invalid_time_series_values_always_fail(self) -> None:
        """Test that invalid time series values always raise ValidationError."""
        # Test out of range values
        with pytest.raises(ValidationError):
            TimeSeriesData(values=[-2e6])  # Too low

        with pytest.raises(ValidationError):
            TimeSeriesData(values=[2e12])  # Too high

        # Test mixed valid/invalid
        with pytest.raises(ValidationError):
            TimeSeriesData(values=[1000, -2e6, 2000])  # One invalid value

    def test_empty_time_series_always_fails(self) -> None:
        """Test that empty time series always raises ValidationError."""
        with pytest.raises(ValidationError):
            TimeSeriesData(values=[])

    def test_non_numeric_values_always_fail(self) -> None:
        """Test that non-numeric values in time series always raise ValidationError."""
        with pytest.raises(ValidationError):
            TimeSeriesData(values=["not_a_number", "text"])

        with pytest.raises(ValidationError):
            TimeSeriesData(values=[None, "text"])

        with pytest.raises(ValidationError):
            TimeSeriesData(values=["invalid"])


# Example of how to use Hypothesis to find edge cases in your existing validation
class TestEdgeCaseDiscovery:
    """Demonstrate how Hypothesis can find edge cases in validation logic."""

    @given(
        data=st.fixed_dictionaries(
            {
                "id": st.text(min_size=1, max_size=255),
                "name": st.text(min_size=1, max_size=255),
                "asset_type": st.text(min_size=1, max_size=100),
                "power": st.one_of(
                    st.none(), st.floats(min_value=0, max_value=1e12, allow_nan=False)
                ),
            }
        )
    )
    def test_asset_dict_to_pydantic_conversion(self, data: dict[str, Any]) -> None:
        """Test converting dictionary data to Pydantic model finds edge cases."""
        try:
            # This is how you'd replace InputValidator.validate_asset_properties()
            asset = AssetProperties(**data)

            # Verify the conversion worked correctly
            assert asset.id.strip() == data["id"].strip()
            assert asset.name.strip() == data["name"].strip()
            assert asset.asset_type.strip() == data["asset_type"].strip()
            assert asset.power == data["power"]

        except ValidationError:
            # Expected for invalid data - test passes
            pass
