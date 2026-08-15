import pytest

from ecosystem import EcosystemSimulator


def test_tick_advances_two_rooms_with_one_shared_ahu():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_room_command("room1", "occupancy", {"value": 24})
    simulator.apply_room_command("room2", "occupancy", {"value": 18})
    simulator.apply_room_command("room1", "hvac", {"command": "on"})
    simulator.apply_room_command("room2", "hvac", {"command": "on"})
    simulator.apply_room_command("room1", "setpoint", {"value": 18.0})
    simulator.apply_room_command("room2", "setpoint", {"value": 18.0})

    snapshot = simulator.tick(dt=10.0, advance_occupancy=False)
    granted = sum(room.delivered_airflow_m3_s for room in snapshot.rooms.values())

    assert set(snapshot.rooms) == {"room1", "room2"}
    assert granted <= snapshot.coordination.available_airflow_m3_s + 1e-9
    assert snapshot.coordination.requested_airflow_m3_s > 0


def test_filter_clog_reduces_shared_capacity_after_injection():
    simulator = EcosystemSimulator(seed=3)
    clean = simulator.tick(dt=1.0, advance_occupancy=False).coordination.available_airflow_m3_s
    assert simulator.apply_ahu_command("filter_clog", {"value": 0.9})
    clogged = simulator.tick(dt=1.0, advance_occupancy=False).coordination.available_airflow_m3_s
    assert clogged < clean


def test_energy_and_risk_are_part_of_each_snapshot():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_ahu_command("fan_wear", {"value": 0.8})
    simulator.apply_ahu_command("filter_clog", {"value": 0.9})
    for _ in range(5):
        snapshot = simulator.tick(dt=60.0, advance_occupancy=False)
    assert snapshot.ahu.energy_kwh > 0
    assert 0 <= snapshot.risk.failure_risk <= 1
    assert snapshot.risk.top_drivers


def test_mqtt_style_room_and_ahu_commands_are_routed():
    simulator = EcosystemSimulator(seed=3)
    assert simulator.apply_command("twin/room2/cmd/occupancy", b'{"value": 14}')
    assert simulator.rooms["room2"].state.occupancy == 14
    assert simulator.apply_command("twin/ahu/cmd/filter_clog", b'{"value": 0.7}')
    assert simulator.ahu.filter_clog_pct == 0.7
    assert not simulator.apply_command("twin/room3/cmd/occupancy", b'{"value": 14}')


def test_command_result_correlates_strict_validation():
    simulator = EcosystemSimulator(seed=3)
    result = simulator.apply_command_result(
        "twin/room1/cmd/setpoint",
        b'{"value": 22.5, "command_id": "cmd-7", "source": "test"}',
    )
    assert result.accepted and result.command_id == "cmd-7"
    assert result.source == "test"
    rejected = simulator.apply_command_result(
        "twin/room1/cmd/setpoint", b'{"value": NaN, "command_id": "cmd-8"}'
    )
    assert not rejected.accepted
    assert rejected.reason == "invalid_json"


def test_pause_resume_and_simulation_emergency_stop():
    simulator = EcosystemSimulator(seed=3)
    before = simulator.rooms["room1"].state.temperature
    assert simulator.apply_command(
        "twin/ecosystem/cmd/simulation", b'{"command":"pause","command_id":"p1"}'
    )
    simulator.tick(dt=60.0, advance_occupancy=False)
    assert simulator.rooms["room1"].state.temperature == before
    assert simulator.apply_command(
        "twin/ecosystem/cmd/simulation", b'{"command":"resume","command_id":"p2"}'
    )
    simulator.tick(dt=60.0, advance_occupancy=False)
    assert simulator.rooms["room1"].state.temperature != before
    assert simulator.apply_command(
        "twin/ecosystem/cmd/simulation",
        b'{"command":"emergency_stop","command_id":"p3"}',
    )
    assert simulator.operating_mode == "simulation_emergency_stop"


def test_named_stress_scenario_is_atomic_and_exposed():
    simulator = EcosystemSimulator(seed=3)
    result = simulator.apply_command_result(
        "twin/ecosystem/cmd/scenario",
        b'{"scenario":"shared_capacity_stress","command_id":"scenario-1"}',
    )
    assert result.accepted
    assert simulator.active_scenario == "shared_capacity_stress"
    assert simulator.ahu.filter_clog_pct == 0.85
    assert simulator.rooms["room1"].state.occupancy == 24
    assert simulator.scenario_state()["last_command_id"] == "scenario-1"


def test_shared_capacity_stress_is_atomic_and_deterministic():
    simulator = EcosystemSimulator(seed=3)

    assert simulator.apply_scenario("shared_capacity_stress")
    assert simulator.rooms["room1"].state.temperature == 27.0
    assert simulator.rooms["room1"].state.occupancy == 24
    assert simulator.rooms["room2"].state.temperature == 26.0
    assert simulator.rooms["room2"].state.occupancy == 5
    assert simulator.ahu.filter_clog_pct == 0.85
    assert simulator.fan.wear_pct == 0.75

    snapshot = simulator.tick(dt=1.0)
    assert snapshot.rooms["room1"].requested_airflow_m3_s == 0.16
    assert snapshot.rooms["room2"].requested_airflow_m3_s == 0.16
    assert abs(snapshot.coordination.available_airflow_m3_s - 0.0953175) < 1e-9
    assert snapshot.rooms["room1"].delivered_airflow_m3_s == snapshot.coordination.available_airflow_m3_s
    assert snapshot.rooms["room2"].delivered_airflow_m3_s == 0.0
    assert snapshot.rooms["room1"].state.occupancy == 24
    assert snapshot.rooms["room2"].state.occupancy == 5


def test_baseline_scenario_fully_resets_dirty_runtime():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_scenario("shared_capacity_stress")
    for _ in range(3):
        simulator.tick(dt=60.0)
    assert simulator.ahu.energy_kwh > 0
    assert simulator.rooms["room1"].pid._initialized

    assert simulator.apply_scenario("baseline")

    assert simulator.active_scenario == "baseline"
    assert simulator.guided_scenario_active is False
    assert simulator.rooms["room1"].state.temperature == 24.0
    assert simulator.rooms["room2"].state.temperature == 24.5
    assert simulator.rooms["room1"].requested_airflow_m3_s == 0.0
    assert simulator.rooms["room1"].delivered_airflow_m3_s == 0.0
    assert simulator.rooms["room1"].allocation is None
    assert not simulator.rooms["room1"].pid._initialized
    assert simulator.ahu.energy_kwh == 0.0
    assert simulator.ahu.filter_clog_pct == 0.05
    assert simulator.fan.wear_pct == 0.03
    assert simulator.last_coordination.requested_airflow_m3_s == 0.0


def test_unknown_or_malformed_scenario_does_not_mutate_state():
    simulator = EcosystemSimulator(seed=3)
    before = simulator.snapshot()

    assert not simulator.apply_scenario("unknown")
    assert not simulator.apply_command("twin/ecosystem/cmd/scenario", b'{"command": "unknown"}')
    assert not simulator.apply_command("twin/ecosystem/cmd/scenario", b"not-json")
    assert simulator.snapshot() == before


def test_comfort_debt_and_limited_service_evolve_longitudinally():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_scenario("shared_capacity_stress")
    for _ in range(5):
        simulator.tick(dt=10.0, advance_occupancy=False)

    underserved = simulator.rooms["room2"]
    assert underserved.comfort_debt_c_s > 0.0
    assert underserved.limited_service_s > 0.0
    assert underserved.comfort_debt_c_s <= 3_600.0


def test_thermal_and_electrical_energy_reconcile_exactly():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_scenario("shared_capacity_stress")
    snapshot = simulator.tick(dt=10.0, advance_occupancy=False)
    thermal_sum = sum(room.thermal_cooling_power_w for room in snapshot.rooms.values())

    assert thermal_sum > 0.0
    assert snapshot.ahu.cooling_power_w == pytest.approx(thermal_sum / 3.2)
    assert snapshot.ahu.total_power_w == pytest.approx(
        snapshot.ahu.fan_power_w + snapshot.ahu.cooling_power_w
    )


def test_paused_snapshot_zeroes_instantaneous_state_but_preserves_cumulative_values():
    simulator = EcosystemSimulator(seed=3)
    simulator.apply_scenario("shared_capacity_stress")
    running = simulator.tick(dt=10.0, advance_occupancy=False)
    energy = running.ahu.energy_kwh
    debt = {room_id: room.comfort_debt_c_s for room_id, room in running.rooms.items()}
    simulator.apply_command_result(
        "twin/ecosystem/cmd/simulation", b'{"command":"pause"}'
    )
    paused = simulator.tick(dt=60.0, advance_occupancy=False)

    assert paused.ahu.energy_kwh == energy
    assert paused.ahu.total_power_w == 0.0
    assert all(room.requested_airflow_m3_s == 0.0 for room in paused.rooms.values())
    assert all(room.delivered_airflow_m3_s == 0.0 for room in paused.rooms.values())
    assert all(room.thermal_cooling_power_w == 0.0 for room in paused.rooms.values())
    assert {room_id: room.comfort_debt_c_s for room_id, room in paused.rooms.items()} == debt


def test_valid_unchanged_command_is_accepted_without_change():
    simulator = EcosystemSimulator(seed=3)
    result = simulator.apply_command_result(
        "twin/room1/cmd/setpoint", b'{"value":24.0,"command_id":"same"}'
    )
    assert result.accepted is True
    assert result.changed is False
    assert result.reason == "no_change"


def test_non_finite_and_truncated_numeric_commands_are_rejected():
    simulator = EcosystemSimulator(seed=3)

    assert not simulator.apply_room_command("room1", "setpoint", {"value": float("nan")})
    assert not simulator.apply_room_command("room1", "timescale", {"value": 2.9})
    assert not simulator.apply_ahu_command("filter_clog", {"value": float("inf")})
    assert simulator.rooms["room1"].state.setpoint == 24.0
    assert simulator.rooms["room1"].state.time_scale == 1.0
    assert simulator.ahu.filter_clog_pct == 0.05
