"""Tests for floor-level supervision.

A floor twin ADVISES: it nudges setpoints and never seizes a room's control
loop. These tests pin the properties that make that claim true — bounded
nudges, silence when there is no problem, critical-load exemption, and a fair
spread of the burden.
"""
import pytest

from building import load_building
from floor_twin import MAX_NUDGE_C, FloorTwin
from room_twin import RoomTwin


@pytest.fixture(scope="module")
def building():
    return load_building()


@pytest.fixture
def floor1(building):
    floor = building.floor("f1")
    twins = {r.twin_id: RoomTwin(r) for r in floor.rooms}
    return FloorTwin(floor), twins


def load_up(twins, ac_power_pct=1.0, occupancy=20):
    """Put every room under full cooling load."""
    for twin in twins.values():
        twin.state = twin.state.__class__(
            temperature=30.0, humidity=50.0,
            occupancy=min(occupancy, twin.config.max_occupancy),
            hvac_on=True, ac_power_pct=ac_power_pct, setpoint=22.0, mode="auto")


# ── Aggregation ─────────────────────────────────────────────────────────────

def test_aggregate_reports_the_floor(floor1):
    floor, twins = floor1
    load_up(twins)
    summary = floor.aggregate(twins)
    assert summary["rooms"] == 3
    assert summary["total_load_kw"] > 0
    assert summary["occupancy"] > 0
    assert summary["floor_id"] == "f1"


def test_aggregate_of_idle_floor_draws_nothing(floor1):
    floor, twins = floor1
    for twin in twins.values():
        twin.state = twin.state.__class__(hvac_on=False)
    assert floor.aggregate(twins)["total_load_kw"] == 0.0


def test_aggregate_handles_an_empty_floor(floor1):
    """Degrade to a summary, not a crash, if every room twin disappears."""
    floor, _ = floor1
    summary = floor.aggregate({})
    assert summary["rooms"] == 0
    assert summary["total_load_kw"] == 0.0


# ── Arbitration ─────────────────────────────────────────────────────────────

def test_no_nudges_when_within_budget(floor1):
    """Supervisors stay silent when there is no problem. This is what makes
    the design federated rather than centralized."""
    floor, twins = floor1
    for twin in twins.values():
        twin.state = twin.state.__class__(hvac_on=False)
    assert floor.arbitrate(twins, budget_kw=22.0) == {}


def test_over_budget_produces_nudges(floor1):
    floor, twins = floor1
    load_up(twins)
    nudges = floor.arbitrate(twins, budget_kw=1.0)   # brutally tight
    assert nudges, "floor over budget produced no nudges"


def test_nudges_are_bounded(floor1):
    """A supervisor must never be able to make a room unsafe."""
    floor, twins = floor1
    load_up(twins)
    for budget in (0.0, 0.5, 1.0, 3.0, 6.0):
        for delta in floor.arbitrate(twins, budget_kw=budget).values():
            assert 0 < delta <= MAX_NUDGE_C, f"nudge {delta} exceeds cap"


def test_nudges_raise_setpoints_never_lower_them(floor1):
    """Shedding load means letting rooms run warmer, never colder."""
    floor, twins = floor1
    load_up(twins)
    assert all(d > 0 for d in floor.arbitrate(twins, budget_kw=1.0).values())


def test_critical_load_is_exempt(floor1):
    """The server room protects hardware, not comfort — it is never shed."""
    floor, twins = floor1
    load_up(twins)
    assert "f1/server-room" not in floor.arbitrate(twins, budget_kw=0.0)


def test_shedding_reduces_predicted_load_toward_the_cap(floor1):
    floor, twins = floor1
    load_up(twins)
    before = floor.aggregate(twins)["total_load_kw"]
    nudges = floor.arbitrate(twins, budget_kw=before * 0.6)
    assert floor.predicted_load_kw(twins, nudges) < before


def test_burden_is_shared_not_dumped_on_one_room(floor1):
    """Distributional fairness: under sustained scarcity no single room absorbs
    every nudge. The control-side counterpart of the ML bias audit."""
    floor, twins = floor1
    load_up(twins)
    nudges = floor.arbitrate(twins, budget_kw=0.0)
    sheddable = [t for t in twins.values() if not t.config.always_on]
    assert len(nudges) == len(sheddable), (
        "load shedding fell on a subset of the eligible rooms"
    )
    assert max(nudges.values()) - min(nudges.values()) <= MAX_NUDGE_C / 2


def test_arbitration_does_not_mutate_room_state(floor1):
    """Advice, not control: arbitrate() returns a recommendation and must not
    reach into a room twin and change it."""
    floor, twins = floor1
    load_up(twins)
    before = {tid: t.state for tid, t in twins.items()}
    floor.arbitrate(twins, budget_kw=0.0)
    assert {tid: t.state for tid, t in twins.items()} == before


def test_arbitration_is_deterministic(floor1):
    floor, twins = floor1
    load_up(twins)
    assert floor.arbitrate(twins, budget_kw=2.0) == floor.arbitrate(twins, budget_kw=2.0)
