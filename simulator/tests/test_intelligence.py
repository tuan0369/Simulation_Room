"""Tests for predictive intelligence, thermal load forecasting, and action recommendations."""
import pytest
from simulator.intelligence import (
    RoomDemandForecast,
    forecast_ecosystem_demand,
    forecast_room_demand,
    generate_recommendations,
)


def test_forecast_room_demand_empty_room():
    fc = forecast_room_demand(
        room_id="room1",
        current_temp_c=24.0,
        setpoint_c=24.0,
        occupancy=0,
        current_airflow_m3_s=0.05,
    )
    assert fc.room_id == "room1"
    assert fc.predicted_internal_heat_w == 0.0
    assert fc.total_thermal_load_w > 0.0  # Wall heat transfer only
    assert fc.urgency in ("low", "medium")


def test_forecast_room_demand_high_occupancy_surge():
    fc = forecast_room_demand(
        room_id="room1",
        current_temp_c=26.0,
        setpoint_c=22.0,
        occupancy=25,
        current_airflow_m3_s=0.02,
    )
    assert fc.predicted_internal_heat_w == 2500.0
    assert fc.total_thermal_load_w >= 2500.0
    assert fc.required_airflow_m3_s > 0.05
    assert fc.urgency in ("high", "critical")
    assert fc.projected_temp_5min_c >= 26.0


def test_forecast_ecosystem_demand_deficit():
    rooms_data = {
        "room1": {"temperature": 27.0, "setpoint": 20.0, "occupancy": 24, "delivered_airflow_m3_s": 0.05},
        "room2": {"temperature": 26.0, "setpoint": 20.0, "occupancy": 10, "delivered_airflow_m3_s": 0.04},
    }
    eco_fc = forecast_ecosystem_demand(
        rooms_data=rooms_data,
        available_ahu_airflow_m3_s=0.08,
    )
    assert len(eco_fc.rooms) == 2
    assert eco_fc.total_required_airflow_m3_s > 0.08
    assert eco_fc.is_capacity_deficit_projected is True
    assert eco_fc.capacity_shortfall_m3_s > 0.0


def test_generate_recommendations_fan_risk():
    rooms_data = {
        "room1": {"temperature": 24.0, "setpoint": 24.0, "occupancy": 2, "delivered_airflow_m3_s": 0.05},
        "room2": {"temperature": 24.0, "setpoint": 24.0, "occupancy": 2, "delivered_airflow_m3_s": 0.05},
    }
    eco_fc = forecast_ecosystem_demand(rooms_data, available_ahu_airflow_m3_s=0.20)
    fan_health = {"failure_risk": 0.72, "risk_band": "high", "wear_pct": 0.65}
    ahu_data = {"filter_clog_pct": 0.10, "fan_speed_pct": 0.80}

    recs = generate_recommendations(eco_fc, fan_health, ahu_data, rooms_data)
    rec_types = [r.action_type for r in recs]
    assert "PROACTIVE_FAN_DERATE" in rec_types


def test_generate_recommendations_filter_clog():
    rooms_data = {
        "room1": {"temperature": 24.0, "setpoint": 24.0, "occupancy": 2, "delivered_airflow_m3_s": 0.05},
        "room2": {"temperature": 24.0, "setpoint": 24.0, "occupancy": 2, "delivered_airflow_m3_s": 0.05},
    }
    eco_fc = forecast_ecosystem_demand(rooms_data, available_ahu_airflow_m3_s=0.20)
    fan_health = {"failure_risk": 0.10, "risk_band": "low", "wear_pct": 0.05}
    ahu_data = {"filter_clog_pct": 0.85, "fan_speed_pct": 0.60}

    recs = generate_recommendations(eco_fc, fan_health, ahu_data, rooms_data)
    rec_types = [r.action_type for r in recs]
    assert "PREEMPTIVE_FILTER_SERVICE" in rec_types


def test_generate_recommendations_precool():
    rooms_data = {
        "room1": {"temperature": 25.0, "setpoint": 23.0, "occupancy": 24, "delivered_airflow_m3_s": 0.05},
        "room2": {"temperature": 24.0, "setpoint": 24.0, "occupancy": 2, "delivered_airflow_m3_s": 0.05},
    }
    eco_fc = forecast_ecosystem_demand(rooms_data, available_ahu_airflow_m3_s=0.20)
    fan_health = {"failure_risk": 0.10, "risk_band": "low", "wear_pct": 0.05}
    ahu_data = {"filter_clog_pct": 0.05, "fan_speed_pct": 0.50}

    recs = generate_recommendations(eco_fc, fan_health, ahu_data, rooms_data)
    rec_types = [r.action_type for r in recs]
    assert "PREEMPTIVE_PRECOOL" in rec_types


def test_generate_recommendations_capex_upgrade():
    rooms_data = {
        "room1": {"temperature": 27.0, "setpoint": 20.0, "occupancy": 30, "delivered_airflow_m3_s": 0.10},
        "room2": {"temperature": 26.0, "setpoint": 20.0, "occupancy": 20, "delivered_airflow_m3_s": 0.10},
        "room3": {"temperature": 26.0, "setpoint": 20.0, "occupancy": 15, "delivered_airflow_m3_s": 0.10},
        "room4": {"temperature": 26.0, "setpoint": 20.0, "occupancy": 20, "delivered_airflow_m3_s": 0.10},
    }
    eco_fc = forecast_ecosystem_demand(rooms_data, available_ahu_airflow_m3_s=0.48)
    fan_health = {"failure_risk": 0.20, "risk_band": "low", "wear_pct": 0.10}
    ahu_data = {"filter_clog_pct": 0.05, "fan_speed_pct": 1.0}

    recs = generate_recommendations(eco_fc, fan_health, ahu_data, rooms_data)
    rec_types = [r.action_type for r in recs]
    assert "EQUIPMENT_RETROFIT_ADVISORY" in rec_types
