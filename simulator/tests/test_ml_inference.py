"""Tests for live risk scoring.

The load-bearing ones here are about honesty and safety rather than accuracy:
a scorer with no history must say so, and a missing or broken model must never
be able to stop the cooling.
"""
import json

import pytest

from building import load_building
from hvac_health import (HDF_GUARD_HIGH, HDF_GUARD_LOW, MOTOR_TEMP_ALARM,
                         HVACHealth, hdf_guard_score)
from ml_inference import SAMPLE_INTERVAL_S, RiskScorer
from room_twin import RoomTwin

MODEL_DIR = "ml/models"


@pytest.fixture(scope="module")
def building():
    return load_building()


@pytest.fixture
def scorer():
    return RiskScorer(MODEL_DIR, quiet=True)


def feed(scorer, twin_id, twin, samples, start=0.0, mutate=None):
    """Push `samples` observations at the scorer's own cadence."""
    t = start
    for i in range(samples):
        if mutate:
            mutate(twin, i)
        scorer.observe(twin_id, twin.telemetry(), t)
        t += SAMPLE_INTERVAL_S
    return t


# ── Graceful degradation ────────────────────────────────────────────────────

def test_missing_model_disables_scoring_without_raising(tmp_path):
    """A broken model must never stop the simulator: no cooling depends on it."""
    s = RiskScorer(tmp_path / "nope", quiet=True)
    assert s.available is False
    assert s.score("f1/lab-a") is None
    payload = s.warming_up_payload("f1/lab-a")
    assert payload["status"] == "unavailable"
    assert payload["failure_prob"] is None
    assert payload["alert"] is False


def test_corrupt_model_is_handled(tmp_path):
    (tmp_path / "failure_classifier.joblib").write_bytes(b"not a joblib file")
    (tmp_path / "feature_spec.json").write_text("{}")
    s = RiskScorer(tmp_path, quiet=True)
    assert s.available is False
    assert "could not load" in s.unavailable_reason


def test_unavailable_payload_still_names_a_version(tmp_path):
    s = RiskScorer(tmp_path / "nope", quiet=True)
    assert s.warming_up_payload("f1/lab-a")["model_version"] == "unavailable"


# ── Cold start ──────────────────────────────────────────────────────────────

def test_no_history_returns_none(scorer, building):
    assert scorer.score("f1/lab-a") is None


def test_partial_history_still_returns_none(scorer, building):
    twin = RoomTwin(building.room("f1/lab-a"))
    feed(scorer, "f1/lab-a", twin, scorer.window - 1)
    assert scorer.samples("f1/lab-a") == scorer.window - 1
    assert scorer.ready("f1/lab-a") is False
    assert scorer.score("f1/lab-a") is None, "scored a unit it has no window for"


def test_warming_up_payload_reports_progress(scorer, building):
    twin = RoomTwin(building.room("f1/lab-a"))
    feed(scorer, "f1/lab-a", twin, 10)
    payload = scorer.warming_up_payload("f1/lab-a")
    assert payload["status"] == "warming_up"
    assert payload["samples"] == 10
    assert payload["samples_required"] == scorer.window
    assert payload["failure_prob"] is None


# ── Sampling cadence ────────────────────────────────────────────────────────

def test_observations_respect_the_five_minute_cadence(scorer, building):
    """Rolling windows are defined in samples. Feeding at tick rate would make a
    '6 hour' window mean six minutes and silently break training/serving parity.
    """
    twin = RoomTwin(building.room("f1/lab-b"))
    t = 0.0
    taken = 0
    for _ in range(200):                 # 200 ticks one second apart
        if scorer.observe("f1/lab-b", twin.telemetry(), t):
            taken += 1
        t += 1.0
    assert taken == 1, f"took {taken} samples in 200 s; expected 1"


def test_samples_are_taken_once_per_interval(scorer, building):
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, 12)
    assert scorer.samples("f1/lab-b") == 12


def test_history_is_bounded(scorer, building):
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, scorer.window * 3)
    assert scorer.samples("f1/lab-b") == scorer.window


# ── Scoring ─────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_healthy_unit_scores_a_valid_probability(scorer, building):
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, scorer.window)
    result = scorer.score("f1/lab-b")
    assert result is not None
    assert 0.0 <= result["failure_prob"] <= 1.0
    assert result["status"] == "ok"


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_payload_carries_provenance(scorer, building):
    """A probability with no provenance is the transparency failure the
    governance section exists to prevent."""
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, scorer.window)
    result = scorer.score("f1/lab-b")
    for key in ("model_version", "top_factor", "explanation", "threshold",
                "alert_source", "fault_probabilities"):
        assert key in result, f"missing {key}"
    assert result["model_version"] != "unavailable"


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_overheating_unit_triggers_the_thermal_guard(scorer, building):
    """The model is blind to HDF, so the guard must catch it."""
    twin = RoomTwin(building.room("f1/lab-a"))

    def degrade(t, i):
        t.health = HVACHealth(filter_clog=0.95, bearing_wear=0.8,
                              motor_temp=min(40.0 + i * 1.5, 120.0),
                              runtime_hours=90.0)

    feed(scorer, "f1/lab-a", twin, scorer.window, mutate=degrade)
    result = scorer.score("f1/lab-a")
    assert result["thermal_guard"] > 0.5
    assert result["alert"] is True
    assert "thermal" in result["alert_source"]
    # The thermal warning must survive even when the model also fires and wins
    # the root-cause attribution.
    assert result["thermal_note"] is not None
    assert "insulation limit" in result["thermal_note"]


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_thermal_only_alert_names_the_motor(scorer, building):
    """A hot motor with everything else healthy is HDF: the mode the model
    cannot see, so the guard alone must produce a usable work order."""
    twin = RoomTwin(building.room("f1/lab-b"))

    def heat_only(t, i):
        t.health = HVACHealth(filter_clog=0.02, bearing_wear=0.02,
                              motor_temp=min(60.0 + i * 0.4, 84.0),
                              runtime_hours=5.0)

    feed(scorer, "f1/lab-b", twin, scorer.window, mutate=heat_only)
    result = scorer.score("f1/lab-b")
    assert result["thermal_guard"] > 0.5
    if result["alert_source"] == "thermal_guard":
        assert result["top_factor"] == "motor_temp"
        assert result["likely_fault"] == "hdf"


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_healthy_unit_does_not_trip_the_guard(scorer, building):
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, scorer.window)
    assert scorer.score("f1/lab-b")["thermal_guard"] == 0.0


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_score_all_omits_unscorable_rooms(scorer, building):
    lab_b = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", lab_b, scorer.window)
    feed(scorer, "f2/office", RoomTwin(building.room("f2/office")), 5)
    scores = scorer.score_all(["f1/lab-b", "f2/office"])
    assert "f1/lab-b" in scores
    assert "f2/office" not in scores, "scored a room without enough history"


@pytest.mark.skipif(not RiskScorer(MODEL_DIR, quiet=True).available,
                    reason="model not trained yet")
def test_payload_is_json_serialisable(scorer, building):
    twin = RoomTwin(building.room("f1/lab-b"))
    feed(scorer, "f1/lab-b", twin, scorer.window)
    json.dumps(scorer.score("f1/lab-b"))


# ── The physics guard itself ────────────────────────────────────────────────

def test_guard_ramps_between_its_bounds():
    assert hdf_guard_score(HDF_GUARD_LOW - 10) == 0.0
    assert hdf_guard_score(HDF_GUARD_LOW) == 0.0
    assert hdf_guard_score(HDF_GUARD_HIGH) == 1.0
    assert hdf_guard_score(HDF_GUARD_HIGH + 50) == 1.0
    mid = hdf_guard_score((HDF_GUARD_LOW + HDF_GUARD_HIGH) / 2)
    assert 0.4 < mid < 0.6


def test_guard_fires_before_the_alarm_temperature():
    """It must warn on the way up, not confirm the failure after the fact."""
    assert hdf_guard_score(MOTOR_TEMP_ALARM - 5) > 0.5


def test_guard_is_monotone():
    previous = -1.0
    for temp in range(40, 120, 2):
        score = hdf_guard_score(temp)
        assert score >= previous
        previous = score
