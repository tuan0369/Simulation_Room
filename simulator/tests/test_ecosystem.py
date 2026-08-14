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
