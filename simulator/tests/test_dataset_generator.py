"""Tests for the labeled telemetry generator.

The label-correctness tests matter most: everything the ML work concludes rests
on these labels being right. A positive label that is not actually followed by
a failure would make the model look good while learning nothing.
"""
import math

import pytest

from dataset_generator import (COLUMNS, RUL_HORIZON_H, WARN_HORIZON_H,
                               WARN_HORIZON_LONG_H, generate, write_csv)

# Long enough to contain real failures and at least one planned service round.
# Filter clogging takes ~17 days and the shortest service interval is 7, so a
# 3-day window produced a dataset with zero failures — nothing to assert on.
# The shipped dataset uses 90 days.
DAYS = 21


@pytest.fixture(scope="module")
def dataset():
    rows, stats = generate(days=DAYS, seed=42, progress=False)
    return rows, stats


# ── Shape ───────────────────────────────────────────────────────────────────

def test_produces_rows(dataset):
    rows, _ = dataset
    assert len(rows) > 0


def test_every_row_has_exactly_the_declared_columns(dataset):
    rows, _ = dataset
    for row in rows[:200]:
        assert set(row) == set(COLUMNS)


def test_all_six_rooms_are_present(dataset):
    rows, _ = dataset
    assert len({r["twin_id"] for r in rows}) == 6


def test_no_missing_values(dataset):
    rows, _ = dataset
    for row in rows:
        for key, value in row.items():
            assert value is not None, f"{key} is None"
            if isinstance(value, float):
                assert not math.isnan(value), f"{key} is NaN"


def test_rows_are_grouped_by_timestamp(dataset):
    """Every sample instant carries all six rooms, so time-based splits cannot
    accidentally cut a room in half."""
    rows, _ = dataset
    counts = {}
    for row in rows:
        counts[row["timestamp_s"]] = counts.get(row["timestamp_s"], 0) + 1
    assert set(counts.values()) == {6}


# ── Physical plausibility ───────────────────────────────────────────────────

def test_temperatures_stay_in_range(dataset):
    rows, _ = dataset
    for row in rows:
        assert 15.0 <= row["room_temp"] <= 40.0
        assert 0.0 <= row["filter_clog"] <= 1.0
        assert row["motor_temp"] <= 150.0
        assert row["occupancy"] >= 0
        assert row["fan_rpm"] >= 0


def test_auto_control_actually_engages(dataset):
    """If the AC never runs, the dataset carries no control behaviour and the
    model would just be reading a thermometer."""
    rows, _ = dataset
    assert any(row["hvac_on"] for row in rows)
    assert any(row["ac_power_pct"] > 0 for row in rows)


def test_rooms_are_not_all_pinned_at_the_clamp(dataset):
    rows, _ = dataset
    clamped = sum(1 for r in rows if r["room_temp"] >= 39.9)
    assert clamped / len(rows) < 0.25


def test_outdoor_temperature_varies_diurnally(dataset):
    rows, _ = dataset
    temps = {r["outdoor_temp"] for r in rows}
    assert max(temps) - min(temps) > 1.0


# ── Labels ──────────────────────────────────────────────────────────────────

def test_dataset_contains_failures(dataset):
    _, stats = dataset
    assert stats["failure_events"] > 0, "no failures: nothing to learn"


def test_failure_rate_per_day_supports_a_useful_sample():
    """What limits the model is INDEPENDENT events, not rows.

    Rows inside a degradation segment are autocorrelated, so a dataset with
    600k rows and 50 events is a 50-sample problem. This pins the event rate so
    the shipped 365-day run yields a sample big enough to split temporally.
    """
    _, stats = generate(days=DAYS, seed=42, progress=False)
    per_day = stats["failure_events"] / DAYS
    assert per_day >= 0.2, (
        f"{per_day:.2f} events/day gives only {per_day * 365:.0f} events in a "
        f"year — too few to hold out a meaningful test set"
    )


def test_timestamps_are_iso_and_ordered(dataset):
    """Time-series data needs a real time axis, not a row counter."""
    rows, _ = dataset
    from datetime import datetime
    stamps = [datetime.fromisoformat(r["timestamp_iso"]) for r in rows]
    assert stamps == sorted(stamps), "rows are not in chronological order"
    assert stamps[0].tzinfo is not None, "timestamps must be timezone-aware"


def test_segments_never_span_a_maintenance_reset(dataset):
    """A segment_id must cover exactly one degradation run. Grouped CV relies
    on this: splitting a segment across train and test leaks the future."""
    rows, _ = dataset
    by_segment = {}
    for row in rows:
        by_segment.setdefault(row["segment_id"], []).append(row)

    for seg, seg_rows in by_segment.items():
        seg_rows.sort(key=lambda r: r["timestamp_s"])
        # Runtime and clog only ever reset at a segment boundary, so within one
        # segment runtime_hours must be non-decreasing.
        runtimes = [r["runtime_hours"] for r in seg_rows]
        assert runtimes == sorted(runtimes), f"{seg}: runtime went backwards"


def test_each_segment_belongs_to_one_room(dataset):
    rows, _ = dataset
    owner = {}
    for row in rows:
        seg, tid = row["segment_id"], row["twin_id"]
        assert owner.setdefault(seg, tid) == tid


def test_positive_labels_are_followed_by_a_real_failure(dataset):
    """Label correctness, verified by construction rather than trusted.

    Every positive row must carry an RUL inside its own horizon, which is only
    possible if a real failure follows it in the same trace.
    """
    rows, _ = dataset
    for row in rows:
        if row["label_failure_within_30min"] == 1:
            assert row["label_rul_hours"] <= WARN_HORIZON_H + 1e-9, (
                f"{row['twin_id']} flagged at 30min but RUL is "
                f"{row['label_rul_hours']}h away"
            )
        if row["label_failure_within_4h"] == 1:
            assert row["label_rul_hours"] <= WARN_HORIZON_LONG_H + 1e-9
            assert row["label_failure_type"] != "none"


def test_the_short_horizon_implies_the_long_one(dataset):
    """A failure within 30 minutes is necessarily one within 4 hours."""
    rows, _ = dataset
    for row in rows:
        if row["label_failure_within_30min"] == 1:
            assert row["label_failure_within_4h"] == 1


def test_rows_outside_the_horizon_are_negative(dataset):
    rows, _ = dataset
    for row in rows:
        if row["label_rul_hours"] > WARN_HORIZON_LONG_H:
            assert row["label_failure_within_30min"] == 0
            assert row["label_failure_within_4h"] == 0
            assert row["label_failure_type"] == "none"


def test_positive_rate_is_realistic(dataset):
    """The 4h target is the one models train on; AI4I's rate is 3.39%. Near 0
    means nothing to learn, near 50% means the degradation constants are wrong.
    """
    _, stats = dataset
    assert 0.3 <= stats["positive_rate_4h_pct"] <= 15.0, (
        f"4h positive rate {stats['positive_rate_4h_pct']}% is implausible"
    )
    assert stats["positive_rate_pct"] < stats["positive_rate_4h_pct"]


def test_rul_is_never_negative_and_is_capped(dataset):
    rows, _ = dataset
    for row in rows:
        assert 0.0 <= row["label_rul_hours"] <= RUL_HORIZON_H


def test_rul_decreases_within_a_run_to_failure_segment(dataset):
    """Inside one degradation segment RUL must count down; it may only jump up
    when a failure is repaired and a new segment starts."""
    rows, _ = dataset
    by_room = {}
    for row in rows:
        by_room.setdefault(row["twin_id"], []).append(row)

    for tid, room_rows in by_room.items():
        room_rows.sort(key=lambda r: r["timestamp_s"])
        for prev, curr in zip(room_rows, room_rows[1:]):
            if curr["label_rul_hours"] > prev["label_rul_hours"]:
                # Only legal at a segment boundary: the previous row was at or
                # near failure, or both sit at the censoring horizon.
                assert (prev["label_rul_hours"] <= 0.2
                        or curr["label_rul_hours"] >= RUL_HORIZON_H - 1e-6), (
                    f"{tid}: RUL rose from {prev['label_rul_hours']} to "
                    f"{curr['label_rul_hours']} mid-segment"
                )


def test_failure_types_are_known(dataset):
    rows, _ = dataset
    valid = {"none", "hdf", "bearing", "airflow", "pwf", "osf"}
    assert {r["label_failure_type"] for r in rows} <= valid


# ── Maintenance discipline creates distribution shift ───────────────────────

def test_maintenance_discipline_differs_between_rooms(dataset):
    """The fairness audit in Task 7 needs real per-room shift to detect. If
    every room behaved identically, a 'no disparity' finding would be vacuous."""
    _, stats = dataset
    planned = {tid: s["planned"] for tid, s in stats["per_room"].items()}
    assert planned["f2/meeting-room"] == 0, "the neglected room was serviced"
    assert any(v > 0 for v in planned.values()), "nobody was serviced"


def test_the_neglected_room_runs_to_failure_unassisted(dataset):
    """It receives no planned servicing at all, so every reset it gets is a
    corrective one. Note this does NOT make it the most failure-prone room:
    wear character matters as much as discipline, and f1/lab-a fails more
    often because its dust load is punishing."""
    _, stats = dataset
    room = stats["per_room"]["f2/meeting-room"]
    assert room["planned"] == 0
    assert room["failures"] > 0
    assert room["corrective"] == room["failures"]


def test_maintenance_actually_happens_where_it_is_scheduled(dataset):
    """Failure counts are now driven by TWO things: maintenance discipline and
    each unit's wear character. f1/lab-a is serviced most aggressively but also
    has the harshest dust load, so it is no longer the most reliable room — the
    dust wins. What must hold is that scheduled servicing really occurs, or the
    discipline gradient would be cosmetic."""
    _, stats = dataset
    assert stats["per_room"]["f1/lab-a"]["planned"] > 0
    assert stats["per_room"]["f2/meeting-room"]["planned"] == 0


def test_every_room_has_a_dominant_failure_mode(dataset):
    """Each unit has its own wear character, so the fault mix differs by room.
    Without this the classification task collapses to one class plus noise."""
    rows, _ = dataset
    by_room = {}
    for row in rows:
        if row["label_failure_within_4h"] == 1:
            by_room.setdefault(row["twin_id"], set()).add(row["label_failure_type"])
    assert len(by_room) >= 4, "too few rooms failed to judge mode variety"
    modes = set()
    for room_modes in by_room.values():
        modes |= room_modes
    assert len(modes) >= 3, f"only {modes} appear; units are too alike"


def test_failure_counts_vary_across_rooms(dataset):
    """Real distribution shift for the fairness audit to find."""
    _, stats = dataset
    counts = [s["failures"] for s in stats["per_room"].values()]
    assert max(counts) > min(counts)


# ── Reproducibility ─────────────────────────────────────────────────────────

def test_same_seed_reproduces_identical_rows():
    a, _ = generate(days=1, seed=7, progress=False)
    b, _ = generate(days=1, seed=7, progress=False)
    assert a == b


def test_different_seeds_differ():
    a, _ = generate(days=1, seed=1, progress=False)
    b, _ = generate(days=1, seed=2, progress=False)
    assert a != b


def test_csv_round_trips(tmp_path, dataset):
    import csv as _csv
    rows, _ = dataset
    out = tmp_path / "telemetry.csv"
    write_csv(rows, out)
    with open(out, encoding="utf-8") as fh:
        read_back = list(_csv.DictReader(fh))
    assert len(read_back) == len(rows)
    assert list(read_back[0]) == COLUMNS


def test_one_day_generates_quickly():
    """Keeps the suite usable; the full 90-day run is a manual step."""
    import time
    start = time.monotonic()
    generate(days=1, seed=42, progress=False)
    assert time.monotonic() - start < 60.0
