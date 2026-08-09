"""Tests for the building layout dataset and its loader.

data/building_layout.json is the single source of truth for the facility: the
simulator, the dashboard and the 3D renderer all read it, so geometry can never
drift from physics. These tests lock the invariants that the rest of the
ecosystem depends on.
"""
import json

import pytest

from building import BuildingConfig, FloorConfig, RoomConfig, load_building

# Project 1 ran a single room with these exact constants. f1/lab-a is that room's
# successor, so it must keep them or every migrated Project-1 physics test breaks.
PROJECT1_HEAT_CAPACITY = 25000.0
PROJECT1_AC_POWER_W = 3500.0
PROJECT1_INSULATION_K = 0.05
PROJECT1_MAX_OCCUPANCY = 30


@pytest.fixture(scope="module")
def building():
    return load_building()


def test_loads_two_floors_and_six_rooms(building):
    assert len(building.floors) == 2
    assert len(building.all_rooms()) == 6


def test_floor_ids_are_f1_and_f2(building):
    assert [f.floor_id for f in building.floors] == ["f1", "f2"]


def test_every_floor_has_three_rooms(building):
    for floor in building.floors:
        assert len(floor.rooms) == 3, f"{floor.floor_id} should have 3 rooms"


def test_twin_ids_are_unique_and_floor_prefixed(building):
    ids = [r.twin_id for r in building.all_rooms()]
    assert len(ids) == len(set(ids)), "duplicate twin_id"
    for room in building.all_rooms():
        assert room.twin_id == f"{room.floor}/{room.room_id}"


def test_lab_a_preserves_project1_constants(building):
    """The regression guard for the whole multi-room refactor."""
    lab_a = building.room("f1/lab-a")
    assert lab_a.heat_capacity == PROJECT1_HEAT_CAPACITY
    assert lab_a.hvac_max_power_w == PROJECT1_AC_POWER_W
    assert lab_a.insulation_k == PROJECT1_INSULATION_K
    assert lab_a.max_occupancy == PROJECT1_MAX_OCCUPANCY


def test_unknown_twin_id_raises_keyerror(building):
    with pytest.raises(KeyError):
        building.room("f9/does-not-exist")


def test_room_returns_roomconfig_instances(building):
    assert isinstance(building.room("f2/office"), RoomConfig)
    assert isinstance(building.floors[0], FloorConfig)
    assert isinstance(building, BuildingConfig)


def test_all_neighbours_resolve(building):
    """No dangling adjacency: every neighbour is a real room or corridor node."""
    room_ids = {r.twin_id for r in building.all_rooms()}
    corridor_ids = {f.corridor_id for f in building.floors}
    known = room_ids | corridor_ids
    for room in building.all_rooms():
        for neighbour in room.neighbours:
            assert neighbour in known, (
                f"{room.twin_id} lists unknown neighbour {neighbour!r}"
            )


def test_adjacency_is_symmetric(building):
    """If A borders B then B borders A — otherwise heat flows one way only."""
    room_ids = {r.twin_id for r in building.all_rooms()}
    for room in building.all_rooms():
        for neighbour in room.neighbours:
            if neighbour not in room_ids:
                continue  # corridor nodes are checked separately
            back = building.room(neighbour).neighbours
            assert room.twin_id in back, (
                f"{room.twin_id} -> {neighbour} is not mirrored back"
            )


def test_every_room_connects_to_its_own_floor_corridor(building):
    """People must be able to reach every room; the occupancy twin relies on it."""
    for room in building.all_rooms():
        corridor = f"{room.floor}/corridor"
        assert corridor in room.neighbours, f"{room.twin_id} has no corridor access"


def test_floors_are_vertically_coupled(building):
    """At least one room pair spans floors, or 'multi-floor' is decorative."""
    cross = [
        (r.twin_id, n)
        for r in building.all_rooms()
        for n in r.neighbours
        if "/" in n and not n.endswith("/corridor") and n.split("/")[0] != r.floor
    ]
    assert cross, "no vertical (inter-floor) adjacency found"


def test_volume_matches_area_times_height(building):
    for room in building.all_rooms():
        assert room.volume_m3 == pytest.approx(room.area_m2 * room.height_m)


def test_floor_budgets_oversubscribe_the_building(building):
    """Deliberate: the building twin must arbitrate, so give it a real conflict.

    If the floors ever fit inside the building budget, Task 5's arbitration
    becomes dead code and its tests stop proving anything.
    """
    floor_total = sum(f.power_budget_kw for f in building.floors)
    assert floor_total > building.power_budget_kw


def test_building_budget_is_reachable(building):
    """The budget must sit BELOW total installed cooling capacity.

    If every unit at 100% still fits inside the budget, it can never be
    breached, the floor/building arbitration never runs, and Task 5 is dead
    code whose tests only pass against fabricated inputs. An earlier 40 kW
    budget against 21.2 kW of installed plant had exactly that problem.
    """
    installed_kw = sum(r.hvac_max_power_w for r in building.all_rooms()) / 1000.0
    assert building.power_budget_kw < installed_kw, (
        f"budget {building.power_budget_kw} kW >= installed {installed_kw} kW: "
        f"coordination can never trigger"
    )


def test_each_floor_can_outgrow_its_own_budget(building):
    """Same argument one level down: a floor budget the floor cannot exceed
    would make its arbitration unreachable too."""
    for floor in building.floors:
        installed_kw = sum(r.hvac_max_power_w for r in floor.rooms) / 1000.0
        assert floor.power_budget_kw < installed_kw, (
            f"{floor.floor_id}: budget {floor.power_budget_kw} kW >= "
            f"installed {installed_kw} kW"
        )


def test_server_room_is_always_on_with_constant_it_load(building):
    """Its AC must not follow the 'empty room -> off' rule."""
    server = building.room("f1/server-room")
    assert server.always_on is True
    assert server.base_equipment_w >= 4000
    assert server.occupancy_profile == "unoccupied"


def test_only_the_server_room_is_always_on(building):
    always_on = [r.twin_id for r in building.all_rooms() if r.always_on]
    assert always_on == ["f1/server-room"]


def test_upper_floor_gets_more_solar_gain(building):
    f1, f2 = building.floors
    assert f2.solar_gain > f1.solar_gain


def test_physical_quantities_are_positive(building):
    for room in building.all_rooms():
        assert room.area_m2 > 0
        assert room.height_m > 0
        assert room.heat_capacity > 0
        assert room.hvac_max_power_w > 0
        assert room.insulation_k > 0
        assert room.base_rpm > 0
        assert room.max_occupancy > 0
        assert room.base_equipment_w >= 0


def test_heat_capacity_scales_with_volume(building):
    """A bigger room must not be easier to heat than a smaller one."""
    by_volume = sorted(building.all_rooms(), key=lambda r: r.volume_m3)
    capacities = [r.heat_capacity for r in by_volume]
    assert capacities == sorted(capacities)


def test_ac_can_overcome_a_full_room(building):
    """Every unit must beat its own worst-case internal load, or it can never
    reach setpoint and the PID integral just winds up against a wall."""
    for room in building.all_rooms():
        peak_load = room.max_occupancy * 100.0 + room.base_equipment_w
        assert room.hvac_max_power_w > peak_load, (
            f"{room.twin_id}: AC {room.hvac_max_power_w}W cannot overcome "
            f"{peak_load}W of internal gain"
        )


def test_occupancy_profiles_are_known(building):
    valid = {"class_schedule", "steady_daytime", "bursty", "unoccupied"}
    for room in building.all_rooms():
        assert room.occupancy_profile in valid


def test_outdoor_profile_present(building):
    assert building.outdoor_profile["base_temp_c"] > 0
    assert building.outdoor_profile["diurnal_amplitude_c"] > 0


def test_layout_json_is_valid_and_matches_loader(building):
    """The 3D view fetches this JSON directly, so its raw shape matters too."""
    with open(load_building.default_path(), encoding="utf-8") as fh:
        raw = json.load(fh)
    assert len(raw["floors"]) == len(building.floors)
    raw_rooms = sum(len(f["rooms"]) for f in raw["floors"])
    assert raw_rooms == len(building.all_rooms())
