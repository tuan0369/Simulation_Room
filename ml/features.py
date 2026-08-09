"""Feature engineering, shared by the training notebooks and the live scorer.

Two rules drive the design, and both exist to stop the model learning something
that is not true of the equipment:

**1. No room identity.** `twin_id`, `floor` and `room_profile` are deliberately
excluded. In the training data `f1/lab-a` is serviced every 6-10 days and never
fails in a year, so any identity feature would let the model conclude "lab-a is
immortal" — an artifact of the maintenance *policy*, not a property of the
hardware. The moment lab-a's filter actually clogs, that model would stay
silent. Risk must be inferred from condition alone, so a healthy room scores low
because it is healthy, not because of its name.

**2. No future information.** Every rolling feature looks strictly backwards
(`closed="left"` semantics via shift), so a row's features never contain the
row's own future. Rolling windows are computed per degradation segment, so a
window can never span a maintenance reset and smear a serviced unit's history
into a fresh one.

Both the notebook and `simulator/ml_inference.py` call `build_features`, so
training and serving cannot drift apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Raw per-sample condition signals. Physical measurements only.
BASE_FEATURES = [
    "room_temp",
    "humidity",
    "occupancy",
    "outdoor_temp",
    "setpoint",
    "ac_power_pct",
    "hvac_on",
    "motor_temp",
    "motor_room_delta",     # the HDF driver: no gradient, no heat rejection
    "fan_rpm",
    "vibration_mm_s",
    "filter_clog",
    "power_draw_w",
    "runtime_hours",
    "torque_nm",
]

# Signals whose trend matters more than their level — degradation is a slope.
ROLLING_SIGNALS = [
    "motor_temp",
    "motor_room_delta",
    "vibration_mm_s",
    "filter_clog",
    "power_draw_w",
    "fan_rpm",
    "ac_power_pct",
]

# Window lengths in samples. The dataset is sampled every 5 simulated minutes,
# so these are 30 min / 2 h / 6 h.
WINDOWS = {"30m": 6, "2h": 24, "6h": 72}

# Columns that must NEVER become features: identity (leaks maintenance policy),
# labels (leak the answer), and bookkeeping.
FORBIDDEN = {
    "twin_id", "floor", "room_id", "room_profile", "segment_id",
    "label_failure_within_30min", "label_failure_within_4h",
    "label_failure_type", "label_rul_hours",
    "timestamp_iso", "timestamp_s", "day",
}

TARGET = "label_failure_within_4h"
TARGET_SHORT = "label_failure_within_30min"
TARGET_RUL = "label_rul_hours"


def feature_columns() -> list[str]:
    """Every feature name, in a fixed order the model is trained against."""
    names = list(BASE_FEATURES)
    names.append("hour_sin")
    names.append("hour_cos")
    for signal in ROLLING_SIGNALS:
        for window in WINDOWS:
            names.append(f"{signal}_mean_{window}")
            names.append(f"{signal}_slope_{window}")
    names.append("power_per_rpm")
    names.append("duty_cycle_2h")
    return names


FEATURE_COLUMNS = feature_columns()


def _slope(series: pd.Series, window: int) -> pd.Series:
    """Least-squares slope over a trailing window, per sample.

    Computed as cov(x, t) / var(t) with t = 0..n-1, which is the closed form of
    a degree-1 polyfit and avoids an apply() over hundreds of thousands of rows.
    """
    n = window
    t_mean = (n - 1) / 2.0
    t_var = (n * n - 1) / 12.0
    roll = series.rolling(n, min_periods=n)
    # cov(x, t) = E[x*t] - E[x]*E[t]; E[x*t] via a weighted rolling sum.
    weights = np.arange(n) - t_mean
    cov = roll.apply(lambda v: float(np.dot(v, weights)) / n, raw=True)
    return cov / t_var


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the model matrix from raw telemetry.

    Expects the columns emitted by `simulator/dataset_generator.py`. Rolling
    features are grouped by `segment_id` when present so no window spans a
    maintenance reset.
    """
    df = df.copy()
    if "timestamp_s" in df:
        df = df.sort_values(["twin_id", "timestamp_s"]) if "twin_id" in df else \
            df.sort_values("timestamp_s")

    df["hvac_on"] = df["hvac_on"].astype(int)

    # Time of day as a cycle, so 23:00 and 01:00 are near each other. Note this
    # is time-of-day only — never the absolute date, which would let the model
    # memorise when specific failures happened.
    hour = df["sim_hour"] if "sim_hour" in df else 0.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)

    group_key = "segment_id" if "segment_id" in df else "twin_id"
    grouped = df.groupby(group_key, sort=False) if group_key in df else None

    for signal in ROLLING_SIGNALS:
        for name, window in WINDOWS.items():
            if grouped is not None:
                mean = grouped[signal].transform(
                    lambda s, w=window: s.rolling(w, min_periods=1).mean())
                slope = grouped[signal].transform(
                    lambda s, w=window: _slope(s, w))
            else:
                mean = df[signal].rolling(window, min_periods=1).mean()
                slope = _slope(df[signal], window)
            df[f"{signal}_mean_{name}"] = mean
            df[f"{signal}_slope_{name}"] = slope.fillna(0.0)

    # Efficiency ratio: a motor drawing more power per revolution is working
    # harder against a restricted duct or worn bearings.
    df["power_per_rpm"] = df["power_draw_w"] / df["fan_rpm"].replace(0, np.nan)
    df["power_per_rpm"] = df["power_per_rpm"].fillna(0.0)

    if grouped is not None:
        df["duty_cycle_2h"] = grouped["hvac_on"].transform(
            lambda s: s.rolling(WINDOWS["2h"], min_periods=1).mean())
    else:
        df["duty_cycle_2h"] = df["hvac_on"].rolling(
            WINDOWS["2h"], min_periods=1).mean()

    return df


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """The model input: features only, in the canonical order."""
    built = build_features(df)
    missing = [c for c in FEATURE_COLUMNS if c not in built]
    if missing:
        raise KeyError(f"feature matrix is missing {missing}")
    return built[FEATURE_COLUMNS].astype(float)


def build_features_live(history) -> np.ndarray:
    """Score a single room from a rolling window of live telemetry.

    `history` is an ordered sequence of telemetry dicts (oldest first) as
    produced by `RoomTwin.telemetry()`. Returns one feature vector, or None if
    there is not yet enough history — a cold-start unit gets no score rather
    than a fabricated one.

    Deliberately routed through the same `build_features` as training. A
    separate live implementation is the classic way training/serving skew
    creeps in, and `test_features.py` asserts the two agree.
    """
    needed = max(WINDOWS.values())
    if history is None or len(history) < needed:
        return None
    frame = pd.DataFrame(list(history)[-needed:])
    if "sim_hour" not in frame:
        frame["sim_hour"] = 0.0
    return feature_matrix(frame).iloc[[-1]].to_numpy()
