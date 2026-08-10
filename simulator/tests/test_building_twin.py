"""Tests for building-level coordination.

The building twin resolves the deliberate over-subscription baked into the
layout (22 + 22 kW of floor budget against a 40 kW building) and turns ML risk
scores into maintenance work orders. It advises; it never actuates.
"""
import pytest

from building import load_building
from building_twin import ACTION_FOR_FACTOR, BuildingTwin
from floor_twin import FloorTwin
from room_twin import RoomTwin


@pytest.fixture(scope="module")
def building():
    return load_building()


@pytest.fixture
def coordinator(building):
    twin = BuildingTwin(building)
    floors = {f.floor_id: FloorTwin(f) for f in building.floors}
    rooms = {r.twin_id: RoomTwin(r) for r in building.all_rooms()}
    return twin, floors, rooms


def summaries(floors, rooms, load_kw):
    """Fabricate floor summaries with a chosen load per floor."""
    return {
        fid: {"floor_id": fid, "total_load_kw": load_kw, "rooms": 3,
              "occupancy": 10, "peak_risk": 0.0}
        for fid in floors
    }


# ── Budget allocation ───────────────────────────────────────────────────────

def test_allocations_never_exceed_the_building_budget(coordinator, building):
    twin, floors, rooms = coordinator
    for load in (1.0, 5.0, 15.0, 30.0):
        alloc = twin.allocate_budgets(summaries(floors, rooms, load))
        assert sum(alloc.values()) <= building.power_budget_kw + 1e-9


def test_oversubscription_is_actually_resolved(coordinator, building):
    """The layout gives floors 22 + 22 kW against a 40 kW building. Under heavy
    demand the twin must hand out less than the floors asked for."""
    twin, floors, rooms = coordinator
    declared = sum(f.power_budget_kw for f in building.floors)
    assert declared > building.power_budget_kw, "layout is no longer oversubscribed"

    alloc = twin.allocate_budgets(summaries(floors, rooms, 25.0))
    assert sum(alloc.values()) < declared


def test_light_demand_is_not_throttled(coordinator):
    """No artificial scarcity: a quiet building gets what it asks for."""
    twin, floors, rooms = coordinator
    alloc = twin.allocate_budgets(summaries(floors, rooms, 2.0))
    assert all(v >= 2.0 for v in alloc.values())


def test_allocation_follows_demand(coordinator):
    twin, floors, _ = coordinator
    lopsided = {
        "f1": {"floor_id": "f1", "total_load_kw": 30.0, "rooms": 3,
               "occupancy": 40, "peak_risk": 0.0},
        "f2": {"floor_id": "f2", "total_load_kw": 2.0, "rooms": 3,
               "occupancy": 2, "peak_risk": 0.0},
    }
    alloc = twin.allocate_budgets(lopsided)
    assert alloc["f1"] > alloc["f2"]


def test_every_floor_keeps_a_floor_share(coordinator):
    """Even a quiet floor keeps enough headroom for its critical loads."""
    twin, floors, _ = coordinator
    lopsided = {
        "f1": {"floor_id": "f1", "total_load_kw": 40.0, "rooms": 3,
               "occupancy": 40, "peak_risk": 0.0},
        "f2": {"floor_id": "f2", "total_load_kw": 0.0, "rooms": 3,
               "occupancy": 0, "peak_risk": 0.0},
    }
    assert twin.allocate_budgets(lopsided)["f2"] > 0.0


def test_no_floors_degrades_quietly(coordinator):
    twin, _, _ = coordinator
    assert twin.allocate_budgets({}) == {}


# ── Maintenance advisories ──────────────────────────────────────────────────

def test_high_risk_raises_one_work_order(coordinator):
    twin, _, _ = coordinator
    orders = twin.advisories({"f1/lab-a": {"failure_prob": 0.91,
                                           "top_factor": "motor_temp"}})
    assert len(orders) == 1
    assert orders[0]["twin_id"] == "f1/lab-a"
    assert orders[0]["top_factor"] == "motor_temp"


def test_low_risk_raises_nothing(coordinator):
    twin, _, _ = coordinator
    assert twin.advisories({"f1/lab-a": {"failure_prob": 0.05}}) == []


def test_repeated_risk_does_not_spam_duplicates(coordinator):
    """An alert that repeats every 30 s is an alert nobody reads."""
    twin, _, _ = coordinator
    risk = {"f1/lab-a": {"failure_prob": 0.91, "top_factor": "motor_temp"}}
    assert len(twin.advisories(risk)) == 1
    for _ in range(10):
        assert twin.advisories(risk) == []


def test_a_new_fault_on_the_same_room_still_raises(coordinator):
    twin, _, _ = coordinator
    assert twin.advisories({"f1/lab-a": {"failure_prob": 0.9,
                                         "top_factor": "motor_temp"}})
    assert twin.advisories({"f1/lab-a": {"failure_prob": 0.9,
                                         "top_factor": "filter_clog"}})


def test_recovery_rearms_the_alert(coordinator):
    """Once a unit is serviced and risk falls, a later relapse must alert
    again rather than being suppressed forever by the dedupe."""
    twin, _, _ = coordinator
    risk = {"f1/lab-a": {"failure_prob": 0.9, "top_factor": "motor_temp"}}
    assert twin.advisories(risk)
    assert twin.advisories({"f1/lab-a": {"failure_prob": 0.02}}) == []
    assert twin.advisories(risk), "relapse was suppressed"


def test_the_models_own_threshold_is_honoured(coordinator):
    """The model derives its threshold from a cost curve and ships it with each
    score. A hardcoded default here meant a room scoring 0.495 against the
    model's 0.0053 threshold raised no work order at all."""
    twin, _, _ = coordinator
    orders = twin.advisories({"f1/lab-a": {"failure_prob": 0.4954,
                                           "threshold": 0.0053,
                                           "top_factor": "runtime_hours"}})
    assert len(orders) == 1, "calibrated threshold was ignored"


def test_a_nonsense_threshold_falls_back_to_the_default(coordinator):
    twin, _, _ = coordinator
    assert twin.advisories({"f1/lab-a": {"failure_prob": 0.1,
                                         "threshold": 0.0}}) == []
    assert twin.advisories({"f1/lab-b": {"failure_prob": 0.9,
                                         "threshold": "high"}})


def test_thermal_guard_raises_a_work_order_on_its_own(coordinator):
    """The model cannot see heat-dissipation failure. Gating the guard behind
    the model score would reinstate exactly the blind spot it exists to cover.
    """
    twin, _, _ = coordinator
    orders = twin.advisories({"f1/lab-a": {"failure_prob": 0.001,
                                           "threshold": 0.0053,
                                           "thermal_guard": 0.8,
                                           "top_factor": "motor_temp"}})
    assert len(orders) == 1
    # An overheating winding calls for a thermal derate, not a strip-down.
    assert orders[0]["action"] == "thermal_derate"


def test_every_failure_mode_has_a_remedy():
    """The system predicted five faults but could only fix two, so three had no
    action anyone could take. Every mode must map to something."""
    from hvac_health import REMEDY_FOR_FAULT
    from ml_inference import FACTOR_FOR_FAULT
    for fault in ("hdf", "osf", "pwf", "airflow", "bearing"):
        assert fault in REMEDY_FOR_FAULT, f"{fault} has no remedy"
        factor = FACTOR_FOR_FAULT[fault]
        assert factor in ACTION_FOR_FACTOR, f"{factor} maps to no action"
        assert ACTION_FOR_FACTOR[factor] != "inspect", (
            f"{fault} falls through to a manual inspection")


def test_remedies_agree_between_the_two_mappings():
    """hvac_health.REMEDY_FOR_FAULT and the factor->action table must not
    disagree about how a fault is fixed."""
    from hvac_health import REMEDY_FOR_FAULT
    from ml_inference import FACTOR_FOR_FAULT
    for fault, remedy in REMEDY_FOR_FAULT.items():
        via_factor = ACTION_FOR_FACTOR[FACTOR_FOR_FAULT[fault]]
        assert via_factor == remedy, (
            f"{fault}: REMEDY_FOR_FAULT says {remedy}, factor table says "
            f"{via_factor}")


def test_auto_fix_is_off_by_default(coordinator):
    """The default posture is that a human approves anything touching physical
    equipment. Autonomy must be opted into, never inherited."""
    twin, _, _ = coordinator
    assert twin.auto_fix is False
    order = twin.advisories({"f1/lab-a": {"failure_prob": 0.9,
                                          "threshold": 0.005,
                                          "top_factor": "filter_clog"}})[0]
    assert order["requires_human_approval"] is True
    assert order["auto_dispatched"] is False


def test_auto_fix_dispatches_preventive_work(building):
    twin = BuildingTwin(building, auto_fix=True)
    order = twin.advisories({"f1/lab-a": {"failure_prob": 0.9,
                                          "threshold": 0.005,
                                          "top_factor": "filter_clog"}}, now_h=10.0)[0]
    assert order["auto_dispatched"] is True
    assert order["requires_human_approval"] is False
    assert order["action"] == "replace_filter"


def test_auto_fix_never_dispatches_a_non_preventive_action(building):
    """`inspect` needs a person — the twin cannot inspect anything. Only the
    two servicing actions are ever eligible."""
    from building_twin import AUTO_FIX_ACTIONS
    twin = BuildingTwin(building, auto_fix=True)
    assert "inspect" not in AUTO_FIX_ACTIONS
    order = twin.advisories({"f1/lab-a": {"failure_prob": 0.9,
                                          "threshold": 0.005,
                                          "top_factor": "mystery"}}, now_h=10.0)[0]
    assert order["action"] == "inspect"
    assert order["auto_dispatched"] is False
    assert order["requires_human_approval"] is True


def test_auto_fix_respects_a_cooldown(building):
    """Without this, a unit that keeps scoring high would be serviced over and
    over."""
    from building_twin import AUTO_FIX_COOLDOWN_H
    twin = BuildingTwin(building, auto_fix=True)
    score = {"f1/lab-a": {"failure_prob": 0.9, "threshold": 0.005,
                          "top_factor": "filter_clog"}}
    assert twin.advisories(score, now_h=0.0)[0]["auto_dispatched"] is True

    twin._open_orders.clear()          # simulate the fault recurring
    soon = twin.advisories(score, now_h=AUTO_FIX_COOLDOWN_H / 2)[0]
    assert soon["auto_dispatched"] is False
    assert soon["requires_human_approval"] is True

    twin._open_orders.clear()
    later = twin.advisories(score, now_h=AUTO_FIX_COOLDOWN_H + 1)[0]
    assert later["auto_dispatched"] is True


def test_auto_fix_can_be_switched_off_again(building):
    twin = BuildingTwin(building, auto_fix=True)
    twin.auto_fix = False
    order = twin.advisories({"f1/lab-b": {"failure_prob": 0.9,
                                          "threshold": 0.005,
                                          "top_factor": "vibration_mm_s"}},
                            now_h=99.0)[0]
    assert order["auto_dispatched"] is False


def test_advisories_are_recommendations_not_actions(coordinator):
    twin, _, _ = coordinator
    order = twin.advisories({"f2/office": {"failure_prob": 0.95,
                                           "top_factor": "vibration_mm_s"}})[0]
    assert order["action"] in ("replace_filter", "service_motor", "inspect")
    assert order["requires_human_approval"] is True


def test_missing_risk_scores_are_tolerated(coordinator):
    """A scorer that has not warmed up yet must not take the twin down."""
    twin, _, _ = coordinator
    assert twin.advisories({}) == []
    assert twin.advisories({"f1/lab-a": {}}) == []
    assert twin.advisories({"f1/lab-a": None}) == []


def test_unknown_twin_id_is_ignored(coordinator):
    twin, _, _ = coordinator
    assert twin.advisories({"f9/ghost": {"failure_prob": 0.99}}) == []


# ── Summary ─────────────────────────────────────────────────────────────────

def test_summary_reports_budget_and_load(coordinator, building):
    twin, floors, rooms = coordinator
    summary = twin.summary(summaries(floors, rooms, 6.0))
    assert summary["total_load_kw"] == pytest.approx(12.0)
    assert summary["power_budget_kw"] == building.power_budget_kw
    assert summary["over_budget"] is False


def test_summary_flags_going_over_budget(coordinator, building):
    twin, floors, rooms = coordinator
    over = building.power_budget_kw          # per floor, so two floors exceed it
    assert twin.summary(summaries(floors, rooms, over))["over_budget"] is True


def test_summary_without_floors_is_still_valid(coordinator):
    twin, _, _ = coordinator
    summary = twin.summary({})
    assert summary["total_load_kw"] == 0.0
    assert summary["over_budget"] is False
