import pytest

from ahu import (
    COOLING_COP,
    AHUState,
    advance_ahu,
    available_airflow,
    calculate_energy,
    cooling_power_w,
    step_temperature_from_supply_air,
)


def test_filter_clog_reduces_available_airflow():
    clean = AHUState(filter_clog_pct=0.0)
    clogged = AHUState(filter_clog_pct=0.8)
    assert available_airflow(clogged) < available_airflow(clean)


def test_more_supply_air_delivers_more_cooling():
    low = cooling_power_w(28.0, 16.0, 0.03)
    high = cooling_power_w(28.0, 16.0, 0.12)
    assert high > low > 0


def test_supply_air_cools_a_hot_room_more_than_no_airflow():
    cooled = step_temperature_from_supply_air(28.0, 5, 0.12, 16.0, dt=20.0)
    uncooled = step_temperature_from_supply_air(28.0, 5, 0.0, 16.0, dt=20.0)
    assert cooled < uncooled


def test_ahu_energy_integrates_over_simulated_time():
    ahu = AHUState(filter_clog_pct=0.3)
    next_ahu = advance_ahu(ahu, total_delivered_airflow_m3_s=0.15, room_cooling_w=1500.0, dt=60.0)
    assert next_ahu.energy_kwh > ahu.energy_kwh
    assert next_ahu.total_power_w > 0
    assert next_ahu.filter_clog_pct > ahu.filter_clog_pct


def test_energy_fields_share_an_explicit_electrical_basis():
    energy = calculate_energy(
        AHUState(filter_clog_pct=0.0),
        total_delivered_airflow_m3_s=0.12,
        room_cooling_w=1600.0,
    )
    assert energy.cooling_electric_power_w == pytest.approx(1600.0 / COOLING_COP)
    assert energy.total_electric_power_w == pytest.approx(
        energy.fan_electric_power_w + energy.cooling_electric_power_w
    )
