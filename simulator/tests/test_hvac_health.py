"""Tests for the HVAC equipment degradation model.

These lock the physical claims the report makes about fan-motor overheating and
filter clogging. Thresholds trace to UCI AI4I 2020 (failure taxonomy and
envelope) and to standard HVAC engineering (Class-F insulation, ISO 10816),
not to invention — see data/README.md.
"""
import pytest

from hvac_health import (HDF_RPM_MIN, MOTOR_TEMP_ALARM, VIBRATION_ALARM,
                         VIBRATION_FAILURE, HVACHealth, apply_maintenance,
                         failure_flags, step_health)

ROOM_TEMP = 24.0
HOUR = 3600.0


def run(health, seconds, duty=1.0, occupancy=10, room_temp=ROOM_TEMP, dt=1.0):
    """Advance the health model for `seconds` of simulated time."""
    steps = int(seconds / dt)
    for _ in range(steps):
        health = step_health(health, ac_power_pct=duty, occupancy=occupancy,
                             room_temp=room_temp, dt=dt)
    return health


# ── Healthy hardware ────────────────────────────────────────────────────────

def test_new_unit_has_no_failure_flags_at_any_duty():
    """No false alarms on brand-new hardware, whatever the load."""
    for duty in (0.0, 0.25, 0.5, 0.75, 1.0):
        flags = failure_flags(HVACHealth(), duty)
        assert not any(flags.values()), f"new unit flagged at duty={duty}: {flags}"


def test_clean_unit_holds_motor_temp_below_70c():
    """A healthy motor reaches a steady state — it does not run away."""
    h = run(HVACHealth(), seconds=4 * HOUR, duty=0.6, occupancy=5, dt=10.0)
    assert h.motor_temp < 70.0
    assert not failure_flags(h, 0.6)["hdf"]


def test_clean_unit_at_full_duty_also_stays_safe():
    h = run(HVACHealth(), seconds=4 * HOUR, duty=1.0, occupancy=5, dt=10.0)
    assert h.motor_temp < 70.0


def test_idle_motor_cools_toward_room_temperature():
    hot = HVACHealth(motor_temp=80.0)
    cooled = run(hot, seconds=2 * HOUR, duty=0.0, occupancy=0, dt=10.0)
    assert cooled.motor_temp < 40.0
    assert cooled.fan_rpm == 0.0


# ── Filter clogging ─────────────────────────────────────────────────────────

def test_filter_clog_accumulates_monotonically():
    h = HVACHealth()
    previous = h.filter_clog
    for _ in range(20):
        h = run(h, seconds=HOUR, duty=1.0, occupancy=10, dt=60.0)
        assert h.filter_clog >= previous
        previous = h.filter_clog
    assert h.filter_clog > 0.0


def test_filter_clogs_faster_in_a_crowded_room():
    """Dust load scales with occupancy."""
    quiet = run(HVACHealth(), seconds=10 * HOUR, duty=1.0, occupancy=0, dt=60.0)
    busy = run(HVACHealth(), seconds=10 * HOUR, duty=1.0, occupancy=30, dt=60.0)
    assert busy.filter_clog > quiet.filter_clog


def test_filter_clog_never_exceeds_one():
    h = run(HVACHealth(filter_clog=0.98), seconds=200 * HOUR,
            duty=1.0, occupancy=30, dt=60.0)
    assert h.filter_clog <= 1.0


def test_clogging_raises_fan_speed_and_power_draw():
    """The fan compensates for restricted airflow: the ROI hook, since the
    extra power is wasted energy the building pays for."""
    clean = step_health(HVACHealth(filter_clog=0.0), 1.0, 10, ROOM_TEMP, 1.0)
    dirty = step_health(HVACHealth(filter_clog=0.8), 1.0, 10, ROOM_TEMP, 1.0)
    assert dirty.fan_rpm > clean.fan_rpm
    assert dirty.power_draw_w > clean.power_draw_w


def test_clogging_alone_eventually_trips_the_airflow_flag():
    h = run(HVACHealth(filter_clog=0.80), seconds=40 * HOUR,
            duty=1.0, occupancy=20, dt=60.0)
    assert failure_flags(h, 1.0)["airflow"]


# ── Fan motor overheating (the brief's named failure mode) ──────────────────

def test_degraded_unit_overheats_within_30_minutes():
    """The headline scenario: a clogged filter plus worn bearings drives the
    motor past its Class-F insulation limit."""
    h = HVACHealth(filter_clog=0.9, bearing_wear=0.7)
    h = run(h, seconds=1800, duty=1.0, occupancy=20, dt=1.0)
    assert h.motor_temp >= MOTOR_TEMP_ALARM
    assert failure_flags(h, 1.0)["hdf"] is True


def test_overheating_needs_degradation_not_just_load():
    """A clean unit under identical load must NOT overheat, or the model is
    just reporting duty cycle rather than equipment health."""
    h = run(HVACHealth(), seconds=1800, duty=1.0, occupancy=20, dt=1.0)
    assert h.motor_temp < MOTOR_TEMP_ALARM
    assert not failure_flags(h, 1.0)["hdf"]


def test_worn_bearings_drag_fan_speed_into_the_ai4i_envelope():
    """AI4I's heat-dissipation envelope is rpm < 1380; a healthy unit runs
    above it and wear pulls it down through it."""
    healthy = step_health(HVACHealth(), 1.0, 10, ROOM_TEMP, 1.0)
    assert healthy.fan_rpm > HDF_RPM_MIN
    worn = step_health(HVACHealth(filter_clog=0.9, bearing_wear=0.7),
                       1.0, 10, ROOM_TEMP, 1.0)
    assert worn.fan_rpm < HDF_RPM_MIN


def test_motor_temp_is_clamped():
    h = run(HVACHealth(filter_clog=1.0, bearing_wear=1.0, motor_temp=140.0),
            seconds=10 * HOUR, duty=1.0, occupancy=30, dt=10.0)
    assert h.motor_temp <= 150.0


# ── Bearing wear and vibration ──────────────────────────────────────────────

def test_vibration_is_monotone_in_bearing_wear():
    previous = -1.0
    for wear in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        h = step_health(HVACHealth(bearing_wear=wear), 1.0, 10, ROOM_TEMP, 1.0)
        assert h.vibration_mm_s > previous
        previous = h.vibration_mm_s


def test_vibration_alarm_leads_bearing_failure():
    """ISO 10816: the 7.1 mm/s alarm must trip before the failure threshold,
    otherwise there is no lead time and nothing to predict."""
    assert VIBRATION_ALARM < VIBRATION_FAILURE

    alarming = None
    failing = None
    for wear_pct in range(0, 101):
        wear = wear_pct / 100.0
        h = step_health(HVACHealth(bearing_wear=wear), 1.0, 10, ROOM_TEMP, 1.0)
        if alarming is None and h.vibration_mm_s >= VIBRATION_ALARM:
            alarming = wear
        if failing is None and failure_flags(h, 1.0)["bearing"]:
            failing = wear
    assert alarming is not None, "vibration never reaches the alarm band"
    assert failing is not None, "bearing failure is unreachable"
    assert alarming < failing


def test_bearing_wear_accumulates_and_is_bounded():
    h = run(HVACHealth(), seconds=50 * HOUR, duty=1.0, occupancy=10, dt=60.0)
    assert h.bearing_wear > 0.0
    assert h.bearing_wear <= 1.0


def test_overheating_accelerates_bearing_wear():
    """Thermal stress shortens bearing life — this coupling is why a clogged
    filter eventually destroys the motor rather than just wasting energy."""
    cool = run(HVACHealth(), seconds=5 * HOUR, duty=1.0, occupancy=5, dt=60.0)
    hot = run(HVACHealth(filter_clog=0.9, motor_temp=95.0),
              seconds=5 * HOUR, duty=1.0, occupancy=5, dt=60.0)
    assert hot.bearing_wear > cool.bearing_wear


# ── Runtime, power and the remaining AI4I failure modes ─────────────────────

def test_runtime_accrues_only_while_running():
    idle = run(HVACHealth(), seconds=5 * HOUR, duty=0.0, occupancy=0, dt=60.0)
    assert idle.runtime_hours == pytest.approx(0.0)
    busy = run(HVACHealth(), seconds=5 * HOUR, duty=1.0, occupancy=0, dt=60.0)
    assert busy.runtime_hours == pytest.approx(5.0, rel=0.02)


def test_power_failure_flag_trips_on_excess_draw():
    """AI4I PWF: power outside the expected band for the commanded duty."""
    degraded = step_health(HVACHealth(filter_clog=0.95, bearing_wear=0.8),
                           1.0, 10, ROOM_TEMP, 1.0)
    assert failure_flags(degraded, 1.0)["pwf"] is True


def test_power_flag_is_relative_to_duty_not_absolute():
    """A healthy unit idling at low duty draws little power; that is normal
    operation, not a power failure."""
    low = step_health(HVACHealth(), 0.25, 5, ROOM_TEMP, 1.0)
    assert not failure_flags(low, 0.25)["pwf"]


def test_overstrain_flag_trips_after_sustained_runtime():
    h = run(HVACHealth(runtime_hours=100.0), seconds=60 * HOUR,
            duty=1.0, occupancy=10, dt=60.0)
    assert failure_flags(h, 1.0)["osf"] is True


# ── Maintenance ─────────────────────────────────────────────────────────────

def test_replace_filter_resets_only_the_filter():
    h = HVACHealth(filter_clog=0.9, bearing_wear=0.6, runtime_hours=120.0)
    after = apply_maintenance(h, "replace_filter")
    assert after.filter_clog == 0.0
    assert after.bearing_wear == 0.6
    assert after.runtime_hours == 120.0


def test_service_motor_resets_bearing_and_runtime_only():
    h = HVACHealth(filter_clog=0.9, bearing_wear=0.6, runtime_hours=120.0)
    after = apply_maintenance(h, "service_motor")
    assert after.bearing_wear == 0.0
    assert after.runtime_hours == 0.0
    assert after.filter_clog == 0.9


def test_maintenance_is_idempotent():
    h = HVACHealth(filter_clog=0.9)
    once = apply_maintenance(h, "replace_filter")
    twice = apply_maintenance(once, "replace_filter")
    assert once == twice


def test_unknown_maintenance_action_is_ignored():
    h = HVACHealth(filter_clog=0.9, bearing_wear=0.6)
    assert apply_maintenance(h, "polish_it") == h


# ── Determinism ─────────────────────────────────────────────────────────────

def test_health_evolution_is_deterministic():
    """No hidden RNG: the dataset generator depends on exact reproducibility."""
    a = run(HVACHealth(), seconds=3 * HOUR, duty=0.8, occupancy=12, dt=30.0)
    b = run(HVACHealth(), seconds=3 * HOUR, duty=0.8, occupancy=12, dt=30.0)
    assert a == b
