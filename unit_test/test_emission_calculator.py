# unit_test/test_emission_calculator.py
"""Unit tests for EmissionCalculator.

Coverage targets:
  - get_emissions_per_energy_unit(): warning emitted, correct kg/GJ return (lines 80-94)
  - _calculate_asset_emissions(): duration == 0 guard returns 0.0 (line 128)

All tests use synthetic EnergySystem objects — no file I/O, no ESDL parsing.
"""

from __future__ import annotations

import unittest
import warnings

from kpicalculator.adapters.common_model import Asset, AssetType, EnergySystem, TimeSeries
from kpicalculator.calculators.emission_calculator import EmissionCalculator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMISSION_FACTOR_KG_PER_J = 0.05 / 1e9  # 0.05 kg/GJ → kg/J


def _make_asset(
    asset_id: str = "asset-1",
    asset_type: AssetType = AssetType.PRODUCER,
    emission_factor: float = _EMISSION_FACTOR_KG_PER_J,
    time_series: dict | None = None,
) -> Asset:
    return Asset(
        id=asset_id,
        name="Test Asset",
        asset_type=asset_type,
        emission_factor=emission_factor,
        time_series=time_series or {},
    )


def _make_system(assets: list[Asset]) -> EnergySystem:
    return EnergySystem(name="Test System", assets=assets)


def _hourly_ts(power_w: float, hours: int = 8760) -> TimeSeries:
    """One year of constant hourly power values."""
    return TimeSeries(time_step=3600.0, values=[power_w] * hours)


# ---------------------------------------------------------------------------
# get_emissions_per_energy_unit()
# ---------------------------------------------------------------------------


class TestGetEmissionsPerEnergyUnit(unittest.TestCase):
    """Tests for the kg/GJ emissions intensity method (lines 80-94)."""

    def _make_system_with_ts(self, power_w: float = 100_000.0) -> EnergySystem:
        """System with both a consumer (drives energy denominator) and a producer
        (drives emission numerator), so both get_emissions_per_energy_unit() and
        get_emissions_per_mwh() return non-zero values."""
        ts = _hourly_ts(power_w)
        consumer = _make_asset(
            asset_id="consumer-1",
            asset_type=AssetType.CONSUMER,
            time_series={"ThermalConsumption": ts},
        )
        producer = _make_asset(
            asset_id="producer-1",
            asset_type=AssetType.PRODUCER,
            time_series={"ThermalProduction": ts},
        )
        return _make_system([consumer, producer])

    def test_emits_user_warning(self) -> None:
        """get_emissions_per_energy_unit() must emit a UserWarning on every call.

        The warning signals that this method is not yet part of the public
        KpiManager output and callers should use get_emissions_per_mwh() instead.
        """
        calc = EmissionCalculator(self._make_system_with_ts())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            calc.get_emissions_per_energy_unit()

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        self.assertEqual(len(user_warnings), 1)
        self.assertIn("not yet integrated", str(user_warnings[0].message))

    def test_returns_zero_when_no_energy(self) -> None:
        """Returns 0.0 when energy consumption is zero (line 85-86).

        A system with no consumer time series produces zero energy consumption,
        so the early-return guard at line 85 is triggered.
        """
        asset = _make_asset(asset_type=AssetType.CONSUMER, time_series={})
        calc = EmissionCalculator(_make_system([asset]))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            result = calc.get_emissions_per_energy_unit()

        self.assertEqual(result, 0.0)

    def test_returns_positive_value_with_energy(self) -> None:
        """Returns a positive kg/GJ value when energy and emissions are present."""
        calc = EmissionCalculator(self._make_system_with_ts(power_w=100_000.0))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            result = calc.get_emissions_per_energy_unit()

        self.assertGreater(result, 0.0)

    def test_kg_per_gj_is_smaller_than_kg_per_mwh(self) -> None:
        """kg/GJ result must be smaller than kg/MWh for the same system.

        1 MWh = 3.6 GJ, so the same energy expressed in GJ is a larger number
        than in MWh.  Dividing the same emission mass by a larger denominator
        gives a smaller ratio: kg/GJ = (kg/MWh) / 3.6 < kg/MWh.
        """
        system = self._make_system_with_ts(power_w=100_000.0)
        calc = EmissionCalculator(system)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            per_gj = calc.get_emissions_per_energy_unit()

        per_mwh = calc.get_emissions_per_mwh()

        # 1 MWh = 3.6 GJ, so per_gj should be per_mwh / 3.6
        self.assertAlmostEqual(per_gj, per_mwh / 3.6, places=6)

    def test_consistent_with_get_emissions_per_mwh(self) -> None:
        """The two intensity methods must be consistent: kg/GJ = kg/MWh / 3.6."""
        system = self._make_system_with_ts(power_w=200_000.0)
        calc = EmissionCalculator(system)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            per_gj = calc.get_emissions_per_energy_unit()

        per_mwh = calc.get_emissions_per_mwh()
        self.assertAlmostEqual(per_gj * 3.6, per_mwh, places=6)


# ---------------------------------------------------------------------------
# _calculate_asset_emissions() — duration == 0 guard (line 128)
# ---------------------------------------------------------------------------


class TestCalculateAssetEmissionsDurationZero(unittest.TestCase):
    """Tests for the duration == 0 guard in _calculate_asset_emissions() (line 128)."""

    def test_zero_time_step_returns_zero(self) -> None:
        """A TimeSeries with time_step=0 produces duration=0 → returns 0.0.

        duration = time_step * len(values) = 0 * N = 0.
        The guard at line 128 prevents ZeroDivisionError in the time_factor
        calculation and returns 0.0.
        """
        ts = TimeSeries(time_step=0.0, values=[100_000.0] * 10)
        asset = _make_asset(
            asset_type=AssetType.PRODUCER,
            time_series={"ThermalProduction": ts},
        )
        calc = EmissionCalculator(_make_system([asset]))

        result = calc._calculate_asset_emissions(asset)

        self.assertEqual(result, 0.0)

    def test_empty_values_list_returns_zero(self) -> None:
        """A TimeSeries with an empty values list also produces duration=0.

        duration = time_step * len([]) = 3600 * 0 = 0 → returns 0.0.
        """
        ts = TimeSeries(time_step=3600.0, values=[])
        asset = _make_asset(
            asset_type=AssetType.PRODUCER,
            time_series={"ThermalProduction": ts},
        )
        calc = EmissionCalculator(_make_system([asset]))

        result = calc._calculate_asset_emissions(asset)

        self.assertEqual(result, 0.0)

    def test_normal_duration_returns_nonzero(self) -> None:
        """A normal TimeSeries bypasses the duration guard and returns a positive value."""
        ts = _hourly_ts(power_w=100_000.0, hours=24)
        asset = _make_asset(
            asset_type=AssetType.PRODUCER,
            time_series={"ThermalProduction": ts},
        )
        calc = EmissionCalculator(_make_system([asset]))

        result = calc._calculate_asset_emissions(asset)

        self.assertGreater(result, 0.0)


if __name__ == "__main__":
    unittest.main()
