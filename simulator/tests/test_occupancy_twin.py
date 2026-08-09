"""Tests for the building-wide occupancy twin.

Project 1 gave each room an independent random walk, which is noise rather than
a twin: people appeared and vanished per room. This twin *conserves headcount* —
people move between rooms through corridors and stairs — which is what makes
"an energy twin interacting with an occupancy twin" a real claim rather than a
diagram label.
"""
import random

import pytest

from building import load_building
from occupancy_twin import (ENTRANCE_NODE, OccupancyTwin, target_fraction,
                            target_occupancy)

HOUR = 3600.0


@pytest.fixture(scope="module")
def building():
    return load_building()


@pytest.fixture
def twin(building):
    return OccupancyTwin(building, rng=random.Random(42))


def at(hour):
    """Simulated seconds since midnight."""
    return hour * HOUR


def run_until(twin, start_hour, hours, dt=60.0):
    t = at(start_hour)
    end = at(start_hour + hours)
    while t < end:
        twin.step(t, dt)
        t += dt
    return twin


# ── Conservation ────────────────────────────────────────────────────────────

def test_headcount_changes_only_through_the_entrance(twin):
    """The defining property: interior movement neither creates nor destroys
    people. Only the entrance changes the building total."""
    t = at(7.0)
    for _ in range(600):
        before = twin.total_in_building
        twin.step(t, 60.0)
        after = twin.total_in_building
        assert after - before == twin.last_entrance_flow, (
            f"headcount moved by {after - before} but entrance flow was "
            f"{twin.last_entrance_flow} at t={t/3600:.2f}h"
        )
        t += 60.0


def test_interior_movement_alone_conserves_exactly(building):
    """With the entrance closed, the total is invariant no matter how much
    people shuffle between rooms."""
    twin = OccupancyTwin(building, rng=random.Random(7))
    run_until(twin, 9.0, 1.0)          # populate the building
    seeded = twin.total_in_building
    assert seeded > 0

    twin.entrance_open = False
    t = at(10.0)
    for _ in range(300):
        twin.step(t, 60.0)
        assert twin.total_in_building == seeded
        t += 60.0


def test_node_counts_sum_to_the_building_total(twin):
    run_until(twin, 8.0, 3.0)
    assert sum(twin.occupancy.values()) == twin.total_in_building


# ── Bounds ──────────────────────────────────────────────────────────────────

def test_no_room_exceeds_its_capacity(building, twin):
    t = at(6.0)
    for _ in range(900):
        twin.step(t, 60.0)
        for room in building.all_rooms():
            assert twin.occupancy[room.twin_id] <= room.max_occupancy, (
                f"{room.twin_id} over capacity at t={t/3600:.2f}h"
            )
        t += 60.0


def test_occupancy_is_never_negative(twin):
    t = at(0.0)
    for _ in range(1440):
        twin.step(t, 60.0)
        assert all(v >= 0 for v in twin.occupancy.values())
        t += 60.0


# ── Schedules ───────────────────────────────────────────────────────────────

def test_class_rooms_fill_during_class_and_empty_between(twin):
    run_until(twin, 8.0, 1.5)                       # into the 09:00 class
    during = twin.occupancy["f1/lab-a"]
    run_until(twin, 9.5, 2.0)                       # 11:00-11:30, between classes
    after = twin.occupancy["f1/lab-a"]
    assert during > 0
    assert after < during


def test_office_holds_a_daytime_plateau(twin):
    run_until(twin, 7.0, 3.0)                       # 10:00
    midday = twin.occupancy["f2/office"]
    run_until(twin, 10.0, 4.0)                      # 14:00
    afternoon = twin.occupancy["f2/office"]
    assert midday > 0
    assert afternoon > 0
    assert abs(afternoon - midday) <= 8             # a plateau, not a spike


def test_server_room_stays_empty(building, twin):
    t = at(0.0)
    for _ in range(1440):
        twin.step(t, 60.0)
        assert twin.occupancy["f1/server-room"] == 0
        t += 60.0


def test_building_empties_overnight(twin):
    run_until(twin, 9.0, 14.0)                      # 09:00 -> 23:00
    run_until(twin, 23.0, 4.0)                      # into the small hours
    assert twin.total_in_building == 0


def test_building_is_empty_before_opening(twin):
    run_until(twin, 3.0, 2.0)
    assert twin.total_in_building == 0


# ── Movement respects the building graph ────────────────────────────────────

def test_upper_floor_is_reached_only_through_its_corridor(building):
    """Nobody teleports between floors: the f2 corridor must be occupied before
    any f2 room can be."""
    twin = OccupancyTwin(building, rng=random.Random(3))
    first_corridor_step = None
    first_room_step = None

    t = at(7.0)
    for i in range(600):
        twin.step(t, 30.0)
        if first_corridor_step is None and twin.occupancy["f2/corridor"] > 0:
            first_corridor_step = i
        if first_room_step is None and any(
                twin.occupancy[r.twin_id] > 0
                for r in building.all_rooms() if r.floor == "f2"):
            first_room_step = i
        if first_room_step is not None:
            break
        t += 30.0

    assert first_room_step is not None, "f2 never populated"
    assert first_corridor_step is not None, "f2 rooms filled without a corridor"
    assert first_corridor_step <= first_room_step


def test_people_leaving_a_room_land_in_its_own_corridor(building):
    twin = OccupancyTwin(building, rng=random.Random(11))
    run_until(twin, 8.0, 2.0)
    for node, count in twin.occupancy.items():
        if count:
            assert node in twin.nodes


# ── Interface ───────────────────────────────────────────────────────────────

def test_step_returns_room_occupancy_only(building, twin):
    result = twin.step(at(10.0), 60.0)
    assert set(result) == {r.twin_id for r in building.all_rooms()}
    assert all(isinstance(v, int) for v in result.values())


def test_corridors_are_tracked_but_not_returned(twin):
    result = twin.step(at(10.0), 60.0)
    assert "f1/corridor" not in result
    assert "f1/corridor" in twin.occupancy


# ── Determinism ─────────────────────────────────────────────────────────────

def test_same_seed_reproduces_the_same_trace(building):
    def trace(seed):
        tw = OccupancyTwin(building, rng=random.Random(seed))
        out = []
        t = at(7.0)
        for _ in range(400):
            out.append(tuple(sorted(tw.step(t, 60.0).items())))
            t += 60.0
        return out

    assert trace(2026) == trace(2026)


def test_different_seeds_differ(building):
    def trace(seed):
        tw = OccupancyTwin(building, rng=random.Random(seed))
        out = []
        t = at(7.0)
        for _ in range(400):
            out.append(tuple(sorted(tw.step(t, 60.0).items())))
            t += 60.0
        return out

    assert trace(1) != trace(999)


# ── Schedule helpers ────────────────────────────────────────────────────────

def test_target_fraction_is_bounded():
    for profile in ("class_schedule", "steady_daytime", "bursty", "unoccupied"):
        for tenth_hour in range(240):
            f = target_fraction(profile, tenth_hour / 10.0)
            assert 0.0 <= f <= 1.0


def test_unoccupied_profile_is_always_zero():
    for tenth_hour in range(240):
        assert target_fraction("unoccupied", tenth_hour / 10.0) == 0.0


def test_target_occupancy_respects_capacity(building):
    room = building.room("f2/meeting-room")
    for tenth_hour in range(240):
        t = target_occupancy(room, tenth_hour / 10.0, bias=1.0)
        assert 0 <= t <= room.max_occupancy


def test_unknown_profile_falls_back_to_empty():
    assert target_fraction("mystery", 12.0) == 0.0
