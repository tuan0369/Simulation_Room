"""Generate labeled HVAC telemetry for model training.

Runs the full twin ecosystem headless — no MQTT, no sleeping — through the same
`Simulator.step()` the live system uses, so training data and production
telemetry come from one physics path.

Labels are computed in a SECOND PASS, backwards from observed failure events.
Labelling forwards would require guessing the future; here every positive label
is justified by a failure that actually happened later in the same trace, which
is what makes `test_positive_labels_are_followed_by_a_real_failure` meaningful
rather than circular.

Each room gets a different maintenance discipline, from well-serviced to
neglected. That is deliberate: it produces both healthy and run-to-failure
trajectories, and it gives the fairness audit in Task 7 real distribution shift
to detect instead of an assumed-clean dataset.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from hvac_health import apply_maintenance, failure_flags
from publisher import Simulator

# Physics/control timestep. NOT a free parameter: the server room's explicit
# stability limit is ~1.7 s (8333 J/°C against 5000 W), and even with the
# implicit integrator a 60 s PID control period leaves it oscillating and
# clamped ~24% of the time. 15 s holds every room at setpoint.
SIM_DT = 15.0
SAMPLE_EVERY = 20        # record a row every 20 steps = 5 simulated minutes
# Two positive-label horizons are emitted.
#   30 min  - the window named in the project plan. Very rare (~0.3% of rows)
#             and, operationally, too short to dispatch a technician into.
#   4 h     - the primary training target: ~2% positives, comparable to AI4I's
#             3.39%, and actually actionable. The notebook compares both.
WARN_HORIZON_H = 0.5
WARN_HORIZON_LONG_H = 4.0
RUL_HORIZON_H = 168.0    # right-censoring limit for remaining-useful-life

START_HOUR = 7.0

# Days between planned servicing. None = neglected, run to failure.
# The spread is the point: it produces both healthy and run-to-failure
# trajectories and gives the Task 7 fairness audit real per-room distribution
# shift to detect, instead of an assumed-clean dataset.
MAINTENANCE_POLICY = {
    "f1/lab-a":        {"filter": 10, "motor": 6},    # well maintained
    "f1/lab-b":        {"filter": 14, "motor": 10},   # good
    "f1/server-room":  {"filter": 7, "motor": 4},     # critical, runs 24/7
    "f2/lab-c":        {"filter": 18, "motor": 14},   # moderate
    "f2/office":       {"filter": 25, "motor": 20},   # lax
    "f2/meeting-room": {"filter": None, "motor": None},  # neglected
}

# Reported when several conditions trip at once, most actionable first.
FAULT_PRIORITY = ("hdf", "bearing", "airflow", "pwf", "osf")

COLUMNS = [
    "timestamp_s", "sim_hour", "day", "twin_id", "floor", "room_profile",
    "occupancy", "room_temp", "humidity", "setpoint", "outdoor_temp",
    "hvac_on", "ac_power_pct",
    "motor_temp", "motor_room_delta", "fan_rpm", "vibration_mm_s",
    "filter_clog", "power_draw_w", "runtime_hours", "torque_nm",
    "label_failure_within_30min", "label_failure_within_4h",
    "label_failure_type", "label_rul_hours",
]


def _fault_name(flags: dict) -> str:
    for name in FAULT_PRIORITY:
        if flags.get(name):
            return name
    return "none"


def generate(days: int = 90, seed: int = 42, sample_every: int = SAMPLE_EVERY,
             dt: float = SIM_DT, progress: bool = False) -> tuple[list[dict], dict]:
    """Simulate `days` and return (rows, statistics).

    Deterministic for a given seed — the CSV is byte-reproducible.
    """
    sim = Simulator(seed=seed)
    sim.sim_time_s = START_HOUR * 3600.0

    # Auto mode throughout: with the AC left in manual-off, every room would
    # simply cook to the 40 C clamp and the dataset would carry no control
    # behaviour to learn from.
    for twin in sim.twins.values():
        twin.state = twin.state.__class__(
            temperature=24.0, humidity=45.0, occupancy=0,
            hvac_on=twin.config.always_on, mode="auto", setpoint=23.0)

    rng = random.Random(seed)          # jitters service dates only
    steps_per_day = int(round(86400.0 / dt))
    total_steps = int(days * steps_per_day)
    next_service = {
        tid: {
            "filter": (policy["filter"] * steps_per_day) if policy["filter"] else None,
            "motor": (policy["motor"] * steps_per_day) if policy["motor"] else None,
        }
        for tid, policy in MAINTENANCE_POLICY.items()
    }

    rows: list[dict] = []
    events: dict[str, list[int]] = {tid: [] for tid in sim.twins}
    fault_at: dict[tuple[str, int], str] = {}
    was_failed = {tid: False for tid in sim.twins}
    corrective = {tid: 0 for tid in sim.twins}
    planned = {tid: 0 for tid in sim.twins}

    steps_per_hour = 3600.0 / dt
    jitter_steps = int(12 * steps_per_hour)        # +/- 12 h on service dates

    for step_i in range(total_steps):
        sim.step(dt)

        for tid, twin in sim.twins.items():
            flags = twin.failure_flags()
            failed = any(flags.values())

            # Rising edge only: a unit that stays broken is one failure, not
            # one per minute. Counting every minute would inflate the positive
            # rate and teach the model to predict "still broken".
            if failed and not was_failed[tid]:
                events[tid].append(step_i)
                fault_at[(tid, step_i)] = _fault_name(flags)
                twin.health = apply_maintenance(
                    apply_maintenance(twin.health, "replace_filter"),
                    "service_motor")
                corrective[tid] += 1
                # Planned work stays on its own calendar. Rescheduling it from
                # each repair meant corrective always arrived first and planned
                # service NEVER fired, collapsing every room into run-to-failure
                # and erasing the maintenance-discipline gradient the fairness
                # audit depends on.
                failed = False
            was_failed[tid] = failed

            for kind, action in (("filter", "replace_filter"),
                                 ("motor", "service_motor")):
                due = next_service[tid][kind]
                if due is not None and step_i >= due:
                    twin.health = apply_maintenance(twin.health, action)
                    planned[tid] += 1
                    interval = MAINTENANCE_POLICY[tid][kind] * steps_per_day
                    jitter = rng.randint(-jitter_steps, jitter_steps)
                    next_service[tid][kind] = step_i + interval + jitter

        if step_i % sample_every == 0:
            outdoor = sim.outdoor_temp()
            hour = (sim.sim_time_s / 3600.0) % 24.0
            for tid, twin in sim.twins.items():
                t = twin.telemetry()
                rows.append({
                    "timestamp_s": int(sim.sim_time_s),
                    "sim_hour": round(hour, 3),
                    "day": step_i // steps_per_day,
                    "twin_id": tid,
                    "floor": t["floor"],
                    "room_profile": t["room_profile"],
                    "occupancy": t["occupancy"],
                    "room_temp": t["room_temp"],
                    "humidity": t["humidity"],
                    "setpoint": t["setpoint"],
                    "outdoor_temp": round(outdoor, 3),
                    "hvac_on": int(t["hvac_on"]),
                    "ac_power_pct": t["ac_power_pct"],
                    "motor_temp": t["motor_temp"],
                    "motor_room_delta": t["motor_room_delta"],
                    "fan_rpm": t["fan_rpm"],
                    "vibration_mm_s": t["vibration_mm_s"],
                    "filter_clog": t["filter_clog"],
                    "power_draw_w": t["power_draw_w"],
                    "runtime_hours": t["runtime_hours"],
                    "torque_nm": t["torque_nm"],
                    "_step": step_i,
                })

        if progress and step_i % steps_per_day == 0:
            done = sum(len(v) for v in events.values())
            print(f"  day {step_i // steps_per_day:>3}/{days}  "
                  f"failures so far: {done}", file=sys.stderr)

    _label(rows, events, fault_at, dt)
    stats = _stats(rows, events, corrective, planned)
    return rows, stats


def _label(rows: list[dict], events: dict[str, list[int]],
           fault_at: dict[tuple[str, int], str], dt: float) -> None:
    """Second pass: attach labels by looking forward to real failures."""
    hours_per_step = dt / 3600.0
    for row in rows:
        tid = row["twin_id"]
        step = row.pop("_step")
        upcoming = next((e for e in events[tid] if e >= step), None)

        if upcoming is None:
            # Right-censored: no failure observed before the trace ended. Held
            # at the horizon rather than left blank, so the column has no NaNs.
            row["label_rul_hours"] = round(RUL_HORIZON_H, 3)
            row["label_failure_within_30min"] = 0
            row["label_failure_within_4h"] = 0
            row["label_failure_type"] = "none"
            continue

        hours_to_failure = (upcoming - step) * hours_per_step
        row["label_rul_hours"] = round(
            min(hours_to_failure, RUL_HORIZON_H), 3)
        row["label_failure_within_30min"] = int(hours_to_failure <= WARN_HORIZON_H)
        row["label_failure_within_4h"] = int(hours_to_failure <= WARN_HORIZON_LONG_H)
        row["label_failure_type"] = (
            fault_at.get((tid, upcoming), "unknown")
            if row["label_failure_within_4h"] else "none")


def _stats(rows, events, corrective, planned) -> dict:
    positives = sum(r["label_failure_within_30min"] for r in rows)
    positives_4h = sum(r["label_failure_within_4h"] for r in rows)
    per_room = {}
    for tid in events:
        room_rows = [r for r in rows if r["twin_id"] == tid]
        pos = sum(r["label_failure_within_4h"] for r in room_rows)
        per_room[tid] = {
            "rows": len(room_rows),
            "positives": pos,
            "positive_rate": round(pos / len(room_rows) * 100, 2) if room_rows else 0.0,
            "failures": len(events[tid]),
            "corrective": corrective[tid],
            "planned": planned[tid],
        }
    n = len(rows) or 1
    return {
        "rows": len(rows),
        "positives": positives,
        "positives_4h": positives_4h,
        "positive_rate_pct": round(positives / n * 100, 3),
        "positive_rate_4h_pct": round(positives_4h / n * 100, 3),
        "failure_events": sum(len(v) for v in events.values()),
        "per_room": per_room,
    }


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-every", type=int, default=SAMPLE_EVERY,
                    help="record a row every N simulated minutes")
    ap.add_argument("--out", type=Path, default=Path("data/building_telemetry.csv"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    rows, stats = generate(days=args.days, seed=args.seed,
                           sample_every=args.sample_every,
                           progress=not args.quiet)
    write_csv(rows, args.out)

    print(f"\nwrote {stats['rows']} rows -> {args.out}")
    print(f"failure events:      {stats['failure_events']}")
    print(f"positive rate (30m): {stats['positive_rate_pct']}%")
    print(f"positive rate (4h):  {stats['positive_rate_4h_pct']}%  <- primary target")
    print(f"\n{'room':<18}{'rows':>8}{'pos4h':>7}{'pos%':>8}{'fails':>7}"
          f"{'corrective':>12}{'planned':>9}")
    for tid, s in stats["per_room"].items():
        print(f"{tid:<18}{s['rows']:>8}{s['positives']:>7}{s['positive_rate']:>8}"
              f"{s['failures']:>7}{s['corrective']:>12}{s['planned']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
