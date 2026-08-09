"""Tests for the autonomous room twin and inter-room thermal coupling.

Two of these carry architectural weight rather than merely checking behaviour:
`test_rooms_are_isolated` and `test_twin_runs_without_any_supervisor` are the
evidence for the federated-coordination claim that docs/ecosystem.md makes.
"""
import pytest

from building import load_building
from commands import CMD_HVAC, CMD_MAINTENANCE, CMD_OCCUPANCY, CMD_SETPOINT
from physics import COUPLING_K, ROOM_HEAT_CAPACITY, RoomState, step_temperature
from room_twin import TELEMETRY_FIELDS, RoomTwin


@pytest.fixture(scope="module")
def building():
    return load_building()


@pytest.fixture
def twins(building):
    return {r.twin_id: RoomTwin(r) for r in building.all_rooms()}


def cmd(twin, suffix):
    return twin.topic(suffix)


# ── Inter-room thermal coupling ─────────────────────────────────────────────

def test_no_neighbours_reproduces_project1_physics():
    """The regression guard: without coupling the model is Project 1's exactly."""
    state = RoomState(temperature=24.0, occupancy=8, hvac_on=False)
    baseline = step_temperature(state, dt=1.0)
    assert step_temperature(state, dt=1.0, neighbour_temps=None) == baseline
    assert step_temperature(state, dt=1.0, neighbour_temps={}) == baseline


def test_hot_neighbour_warms_a_cool_room():
    cool = RoomState(temperature=22.0, occupancy=0, hvac_on=False)
    alone = step_temperature(cool, dt=60.0)
    coupled = step_temperature(cool, dt=60.0, neighbour_temps={"n": 32.0})
    assert coupled > alone


def test_cold_neighbour_cools_a_warm_room():
    warm = RoomState(temperature=30.0, occupancy=0, hvac_on=False)
    alone = step_temperature(warm, dt=60.0)
    coupled = step_temperature(warm, dt=60.0, neighbour_temps={"n": 18.0})
    assert coupled < alone


def test_coupling_conserves_energy_between_two_rooms():
    """Whatever A gains, B loses. Temperature changes differ because the rooms
    have different heat capacities; the energy must still balance."""
    t_a, t_b = 20.0, 30.0
    cap_a = cap_b = ROOM_HEAT_CAPACITY
    a = RoomState(temperature=t_a, occupancy=0, hvac_on=False)
    b = RoomState(temperature=t_b, occupancy=0, hvac_on=False)

    # Isolate the coupling term by differencing against the uncoupled step.
    gain_a = (step_temperature(a, dt=1.0, neighbour_temps={"b": t_b})
              - step_temperature(a, dt=1.0)) * cap_a
    loss_b = (step_temperature(b, dt=1.0, neighbour_temps={"a": t_a})
              - step_temperature(b, dt=1.0)) * cap_b
    assert gain_a == pytest.approx(-loss_b, rel=1e-9)


def test_coupled_pair_converges():
    """Heat flows the right way and the pair settles — no runaway."""
    t_a, t_b = 20.0, 30.0
    for _ in range(2000):
        next_a = step_temperature(
            RoomState(temperature=t_a, occupancy=0, hvac_on=False),
            dt=10.0, neighbour_temps={"b": t_b})
        next_b = step_temperature(
            RoomState(temperature=t_b, occupancy=0, hvac_on=False),
            dt=10.0, neighbour_temps={"a": t_a})
        t_a, t_b = next_a, next_b
    assert abs(t_a - t_b) < abs(20.0 - 30.0)


def test_coupling_constant_is_small_relative_to_ac():
    """Coupling must perturb, not dominate: a supervisor nudging one room
    should never be able to overpower a neighbour's own control loop."""
    assert 0 < COUPLING_K < 50.0


# ── Room twin construction ──────────────────────────────────────────────────

def test_all_six_twins_build_from_the_layout(twins):
    assert len(twins) == 6
    assert set(twins) == {
        "f1/lab-a", "f1/lab-b", "f1/server-room",
        "f2/lab-c", "f2/meeting-room", "f2/office",
    }


def test_twin_topics_are_namespaced_per_room(twins):
    assert twins["f1/lab-a"].topic("temperature") == "twin/f1/lab-a/temperature"
    assert twins["f2/office"].topic("cmd/hvac") == "twin/f2/office/cmd/hvac"


def test_always_on_room_starts_cooling(twins):
    server = twins["f1/server-room"]
    assert server.state.hvac_on is True
    assert server.state.mode == "auto"


def test_normal_rooms_start_idle(twins):
    assert twins["f1/lab-a"].state.hvac_on is False


# ── Federated behaviour ─────────────────────────────────────────────────────

def test_rooms_are_isolated(twins):
    """A command to one room must not touch another. This is the core
    federated claim — cite it in docs/ecosystem.md."""
    lab_a, office = twins["f1/lab-a"], twins["f2/office"]
    before = office.state

    lab_a.handle_command(cmd(lab_a, CMD_HVAC), b'{"command": "on"}')
    lab_a.handle_command(cmd(lab_a, CMD_OCCUPANCY), b'{"value": 25}')
    for _ in range(60):
        lab_a.tick(dt=1.0)

    assert lab_a.state.hvac_on is True
    assert office.state == before


def test_twin_runs_without_any_supervisor(twins):
    """No floor or building twin exists in this test. The room must still
    control itself — graceful degradation, not a hard dependency."""
    lab = twins["f2/lab-c"]
    lab.state = lab.state.__class__(
        temperature=30.0, humidity=45.0, occupancy=20,
        hvac_on=True, mode="auto", setpoint=24.0)
    for _ in range(600):
        lab.tick(dt=1.0)
    assert lab.state.temperature < 30.0
    assert lab.state.ac_power_pct > 0.0


def test_server_room_holds_setpoint_under_constant_it_load(twins):
    """Zero occupancy but 4 kW of hardware: proves base_equipment_w is wired
    in and that always_on overrides the empty-room shutoff."""
    server = twins["f1/server-room"]
    server.state = server.state.__class__(
        temperature=24.0, humidity=45.0, occupancy=0,
        hvac_on=True, mode="auto", setpoint=22.0)
    for _ in range(3000):
        server.tick(dt=1.0)
    assert server.state.hvac_on is True, "always-on room switched itself off"
    assert server.state.temperature == pytest.approx(22.0, abs=1.0)


def test_empty_normal_room_shuts_off_in_auto(twins):
    lab = twins["f1/lab-b"]
    lab.state = lab.state.__class__(
        temperature=28.0, humidity=45.0, occupancy=0, hvac_on=True, mode="auto")
    lab.tick(dt=1.0)
    assert lab.state.hvac_on is False
    assert lab.state.ac_power_pct == 0.0


def test_neighbour_heat_reaches_an_adjacent_room(twins):
    """f1/lab-a borders f1/lab-b, so a hot lab-a must warm lab-b."""
    lab_b = twins["f1/lab-b"]
    lab_b.state = lab_b.state.__class__(
        temperature=24.0, humidity=45.0, occupancy=0, hvac_on=False)
    baseline = lab_b.state.temperature

    for _ in range(1800):
        lab_b.tick(dt=1.0, neighbour_temps={"f1/lab-a": 38.0})
    assert lab_b.state.temperature > baseline


# ── Commands ────────────────────────────────────────────────────────────────

def test_setpoint_command_applies_to_the_addressed_room(twins):
    lab = twins["f2/lab-c"]
    lab.handle_command(cmd(lab, CMD_SETPOINT), b'{"value": 21.5}')
    assert lab.state.setpoint == 21.5


def test_occupancy_is_clamped_to_each_rooms_capacity(twins):
    meeting = twins["f2/meeting-room"]          # capacity 16
    meeting.handle_command(cmd(meeting, CMD_OCCUPANCY), b'{"value": 99}')
    assert meeting.state.occupancy == 16

    lab_a = twins["f1/lab-a"]                   # capacity 30
    lab_a.handle_command(cmd(lab_a, CMD_OCCUPANCY), b'{"value": 99}')
    assert lab_a.state.occupancy == 30


def test_turning_hvac_off_resets_the_pid(twins):
    lab = twins["f1/lab-a"]
    lab.handle_command(cmd(lab, CMD_HVAC), b'{"command": "on"}')
    lab.state = lab.state.__class__(
        temperature=32.0, humidity=45.0, occupancy=10, hvac_on=True)
    for _ in range(30):
        lab.tick(dt=1.0)
    assert lab.state.ac_power_pct > 0.0

    lab.handle_command(cmd(lab, CMD_HVAC), b'{"command": "off"}')
    assert lab.state.ac_power_pct == 0.0


def test_malformed_command_leaves_the_twin_untouched(twins):
    lab = twins["f1/lab-a"]
    before = lab.state
    lab.handle_command(cmd(lab, CMD_HVAC), b"not json")
    lab.handle_command(cmd(lab, CMD_OCCUPANCY), b'{"value": true}')
    assert lab.state == before


# ── Maintenance ─────────────────────────────────────────────────────────────

def test_maintenance_command_clears_filter_clog(twins):
    lab = twins["f1/lab-a"]
    lab.health = lab.health.__class__(filter_clog=0.9, bearing_wear=0.5)
    lab.handle_command(cmd(lab, CMD_MAINTENANCE), b'{"action": "replace_filter"}')
    assert lab.health.filter_clog == 0.0
    assert lab.health.bearing_wear == 0.5


def test_maintenance_command_is_idempotent(twins):
    lab = twins["f1/lab-a"]
    lab.health = lab.health.__class__(filter_clog=0.9)
    topic = cmd(lab, CMD_MAINTENANCE)
    lab.handle_command(topic, b'{"action": "replace_filter"}')
    once = lab.health
    lab.handle_command(topic, b'{"action": "replace_filter"}')
    assert lab.health == once


def test_malformed_maintenance_is_ignored(twins):
    lab = twins["f1/lab-a"]
    lab.health = lab.health.__class__(filter_clog=0.9)
    before = lab.health
    lab.handle_command(cmd(lab, CMD_MAINTENANCE), b"not json")
    lab.handle_command(cmd(lab, CMD_MAINTENANCE), b'{"action": 5}')
    assert lab.health == before


# ── Telemetry contract ──────────────────────────────────────────────────────

def test_telemetry_matches_the_declared_feature_contract(twins):
    """Locks the simulator against ml/features.py: if a field is added or
    renamed here without updating TELEMETRY_FIELDS, this fails."""
    for twin in twins.values():
        row = twin.telemetry()
        assert set(row) == set(TELEMETRY_FIELDS), (
            f"{twin.twin_id}: telemetry does not match TELEMETRY_FIELDS"
        )


def test_telemetry_values_are_json_safe(twins):
    import json
    for twin in twins.values():
        twin.tick(dt=1.0)
        json.dumps(twin.telemetry())  # must not raise


def test_motor_room_delta_is_a_real_gradient(twins):
    lab = twins["f1/lab-a"]
    lab.tick(dt=1.0)
    row = lab.telemetry()
    assert row["motor_room_delta"] == pytest.approx(
        row["motor_temp"] - row["room_temp"], abs=0.01)


def test_electrical_load_is_zero_when_off(twins):
    lab = twins["f1/lab-b"]
    lab.state = lab.state.__class__(hvac_on=False)
    assert lab.electrical_load_w() == 0.0


def test_electrical_load_rises_with_ac_power(twins):
    lab = twins["f1/lab-a"]
    lab.state = lab.state.__class__(hvac_on=True, ac_power_pct=0.25)
    low = lab.electrical_load_w()
    lab.state = lab.state.__class__(hvac_on=True, ac_power_pct=1.0)
    assert lab.electrical_load_w() > low
