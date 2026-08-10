"""Tests for the shared feature pipeline.

Three properties carry the weight here:

* **No room identity** — the training data's best-maintained room never fails,
  so an identity feature would teach the model that that room is immortal.
* **No future leakage** — a row's features must not depend on rows after it.
* **No training/serving skew** — the notebook and the live scorer must produce
  identical vectors from identical input.
"""
import pandas as pd
import pytest

from dataset_generator import generate
from features import (BASE_FEATURES, FEATURE_COLUMNS, FORBIDDEN, TARGET,
                      WINDOWS, build_features, build_features_live,
                      feature_matrix)


@pytest.fixture(scope="module")
def raw():
    rows, _ = generate(days=4, seed=11, progress=False)
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def built(raw):
    return build_features(raw)


# ── No room identity ────────────────────────────────────────────────────────

def test_no_identity_column_is_a_feature():
    """The central guard. f1/lab-a is serviced so often it never fails in a
    year; any identity feature would let the model conclude that room cannot
    fail, and stay silent when its filter finally clogs."""
    for name in FEATURE_COLUMNS:
        assert name not in FORBIDDEN, f"{name} leaks identity or label"
    for banned in ("twin_id", "floor", "room_id", "room_profile", "segment_id"):
        assert not any(banned in name for name in FEATURE_COLUMNS), (
            f"{banned} appears in a feature name"
        )


def test_no_label_column_is_a_feature():
    for name in FEATURE_COLUMNS:
        assert "label" not in name


def test_absolute_time_is_not_a_feature():
    """Time-of-day is legitimate seasonality; the absolute date would let the
    model memorise when particular failures happened."""
    for banned in ("timestamp", "day", "year", "date"):
        assert not any(name == banned or name.startswith(f"{banned}_")
                       for name in FEATURE_COLUMNS)


def test_two_rooms_in_identical_condition_get_identical_features(built):
    """Condition determines the vector, nothing else."""
    row = built.iloc[[0]].copy()
    twin_a = row.copy()
    twin_a["twin_id"] = "f1/lab-a"
    twin_a["segment_id"] = "f1/lab-a#0"
    twin_b = row.copy()
    twin_b["twin_id"] = "f2/meeting-room"
    twin_b["segment_id"] = "f2/meeting-room#3"

    va = feature_matrix(twin_a).to_numpy()
    vb = feature_matrix(twin_b).to_numpy()
    assert (va == vb).all()


# ── No future leakage ───────────────────────────────────────────────────────

def test_features_do_not_depend_on_later_rows(raw):
    """Truncating the future must not change a row's features."""
    one_room = raw[raw["twin_id"] == "f1/lab-b"].sort_values("timestamp_s")
    cutoff = 400
    full = feature_matrix(one_room).iloc[cutoff]
    truncated = feature_matrix(one_room.iloc[:cutoff + 1]).iloc[cutoff]
    pd.testing.assert_series_equal(full, truncated, check_names=False)


def test_rolling_windows_do_not_span_a_maintenance_reset(raw):
    """A window crossing a reset would smear a worn unit's history into a
    freshly serviced one and invent degradation that never happened."""
    room = raw[raw["twin_id"] == "f2/lab-c"].sort_values("timestamp_s")
    built = build_features(room)
    for _, seg in built.groupby("segment_id"):
        first = seg.iloc[0]
        # At a segment's first sample there is no history, so the trailing mean
        # can only be the current value.
        assert first["filter_clog_mean_6h"] == pytest.approx(
            first["filter_clog"], abs=1e-9)


# ── No training/serving skew ────────────────────────────────────────────────

def test_live_and_batch_paths_agree(raw):
    """The classic way a working model silently breaks in production."""
    room = raw[raw["twin_id"] == "f1/lab-a"].sort_values("timestamp_s")
    window = max(WINDOWS.values())
    slice_ = room.iloc[:window]

    batch = feature_matrix(slice_).iloc[[-1]].to_numpy()
    live = build_features_live(slice_.to_dict("records"))
    assert live is not None
    assert live.shape == batch.shape
    assert (abs(live - batch) < 1e-9).all()


def test_live_path_refuses_to_score_without_enough_history():
    """Cold start must return None, not a fabricated vector."""
    assert build_features_live([]) is None
    assert build_features_live(None) is None


def test_live_path_rejects_incomplete_telemetry():
    """A truncated record must return None rather than raise: a malformed
    message must not be able to take risk reporting down with it."""
    assert build_features_live([{"room_temp": 24.0}] * 3) is None
    assert build_features_live([{}]) is None


# ── Shape and hygiene ───────────────────────────────────────────────────────

def test_feature_matrix_has_the_declared_columns(raw):
    matrix = feature_matrix(raw)
    assert list(matrix.columns) == FEATURE_COLUMNS


def test_feature_names_are_unique():
    assert len(FEATURE_COLUMNS) == len(set(FEATURE_COLUMNS))


def test_no_nans_or_infinities(raw):
    import numpy as np
    matrix = feature_matrix(raw)
    assert not matrix.isna().any().any()
    assert np.isfinite(matrix.to_numpy()).all()


def test_base_signals_are_all_present():
    for signal in BASE_FEATURES:
        assert signal in FEATURE_COLUMNS


def test_target_is_available_in_the_raw_data(raw):
    assert TARGET in raw.columns
    assert set(raw[TARGET].unique()) <= {0, 1}


def test_slope_features_detect_a_rising_trend():
    """A degrading unit must show a positive motor-temperature slope."""
    n = max(WINDOWS.values()) + 5
    frame = pd.DataFrame({
        "sim_hour": [12.0] * n,
        "twin_id": ["x"] * n,
        "segment_id": ["x#0"] * n,
        "hvac_on": [1] * n,
        "room_temp": [24.0] * n,
        "humidity": [45.0] * n,
        "occupancy": [10] * n,
        "outdoor_temp": [32.0] * n,
        "setpoint": [23.0] * n,
        "ac_power_pct": [1.0] * n,
        "motor_temp": [40.0 + i * 0.5 for i in range(n)],
        "motor_room_delta": [16.0 + i * 0.5 for i in range(n)],
        "fan_rpm": [1500.0] * n,
        "vibration_mm_s": [1.0] * n,
        "filter_clog": [0.1] * n,
        "power_draw_w": [280.0] * n,
        "runtime_hours": [float(i) for i in range(n)],
        "torque_nm": [1.8] * n,
    })
    matrix = feature_matrix(frame)
    assert matrix["motor_temp_slope_30m"].iloc[-1] > 0
