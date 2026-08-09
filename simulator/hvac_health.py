"""HVAC equipment degradation: fan motor overheating and filter clogging.

This is the physical process the ML model in `ml/` learns to predict. Four
coupled degradation states drive it:

    filter_clog  -> restricts airflow, so the fan spins faster and draws more
                    power (wasted energy) while cooling the motor less
    bearing_wear -> adds friction, drags fan speed down, raises vibration
    motor_temp   -> heat balance between motor losses and airflow-dependent
                    rejection; runs away once dissipation is impaired
    runtime      -> drives the overstrain limit

Thresholds are NOT invented. The failure taxonomy (HDF / PWF / OSF / TWF) and
its envelope come from the UCI AI4I 2020 Predictive Maintenance Dataset, whose
published rules we verified reproduce exactly against `data/ai4i2020.csv`
(115/115 rows). Insulation and vibration limits come from standard practice.
The full mapping and its rescaling arithmetic are documented in data/README.md.

Deterministic by construction: no RNG anywhere, because the dataset generator
(Task 6) has to be byte-reproducible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

# ── Calibration constants ───────────────────────────────────────────────────

# AI4I 2020 heat-dissipation envelope (published rule: process-air < 8.6 K and
# rpm < 1380). Healthy units run above HDF_RPM_MIN; wear drags them through it.
HDF_DELTA_K = 8.6
HDF_RPM_MIN = 1380.0

# AI4I power-failure band [3500, 9000] W around its ~6283 W nominal
# (40 Nm x 1500 rpm), normalised to fractions of expected draw.
PWF_MIN_FRACTION = 0.56
PWF_MAX_FRACTION = 1.43

# AI4I overstrain limit 11000 min*Nm -> 183.3 h*Nm.
OSF_LIMIT_HR_NM = 183.3

# Class-F motor insulation: 155 C rating, 85 C alarm on winding rise.
MOTOR_TEMP_ALARM = 85.0
MOTOR_TEMP_MAX = 150.0

# ISO 10816-1 velocity bands for small machines: 7.1 mm/s is the zone C/D
# boundary (alarm), 11.2 mm/s is unacceptable (failure). The alarm must lead
# the failure or there is no lead time to predict into.
VIBRATION_ALARM = 7.1
VIBRATION_FAILURE = 11.2
VIBRATION_BASE = 0.8
VIBRATION_GAIN = 11.0

# Airflow failure: AI4I's tool-wear analogue for a filter.
CLOG_FAILURE = 0.85

# Degradation rates (per running hour)
CLOG_RATE_PER_HOUR = 0.004
DUST_PER_PERSON = 0.05
WEAR_RATE_PER_HOUR = 0.0015
WEAR_THERMAL_STRESS = 0.15   # extra wear per 10 C above WEAR_THERMAL_KNEE
WEAR_THERMAL_KNEE = 70.0

# Fan and motor characteristics
CLOG_RPM_GAIN = 0.25         # fan compensates for restriction by spinning up
BEARING_RPM_LOSS = 0.40      # friction drags speed down
CLOG_POWER_GAIN = 0.60       # restricted duct raises shaft load
FRICTION_POWER_GAIN = 0.50
MOTOR_EFFICIENCY = 0.85      # 15% of draw becomes heat in the windings

# Motor thermal model
MOTOR_THERMAL_MASS = 1200.0  # J/C
H_NATURAL = 0.30             # W/C with the fan stopped
H_FORCED = 1.38              # W/C at full clean airflow

# A fan motor is a small fraction of the AC unit's rated cooling power.
FAN_POWER_FRACTION = 0.08
DEFAULT_BASE_RPM = 1500.0
DEFAULT_RATED_POWER_W = 280.0   # 8% of Project 1's 3500 W unit

MAINTENANCE_ACTIONS = ("replace_filter", "service_motor")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class HVACHealth:
    """Condition of one room's HVAC unit.

    The first four fields are cumulative state; the rest are derived readings
    recomputed each step (they are stored so telemetry can publish them
    directly). `base_rpm` and `rated_power_w` are the unit's nameplate spec,
    carried alongside so `step_health` needs no separate config argument.
    """

    filter_clog: float = 0.0        # 0..1
    bearing_wear: float = 0.0       # 0..1
    runtime_hours: float = 0.0
    motor_temp: float = 25.0        # C

    fan_rpm: float = 0.0
    vibration_mm_s: float = VIBRATION_BASE
    power_draw_w: float = 0.0
    torque_nm: float = 0.0

    base_rpm: float = DEFAULT_BASE_RPM
    rated_power_w: float = DEFAULT_RATED_POWER_W

    @classmethod
    def for_room(cls, room) -> "HVACHealth":
        """Build a fresh unit matching a RoomConfig's nameplate."""
        return cls(
            base_rpm=room.base_rpm,
            rated_power_w=room.hvac_max_power_w * FAN_POWER_FRACTION,
        )


def fan_speed(health: HVACHealth, duty: float) -> float:
    """Fan speed for a commanded duty.

    Clogging makes the fan spin up to hold airflow; bearing friction drags it
    back down. A worn, clogged unit ends up below AI4I's 1380 rpm envelope.
    """
    if duty <= 0.0:
        return 0.0
    clog_boost = 1.0 + CLOG_RPM_GAIN * health.filter_clog
    wear_loss = 1.0 - BEARING_RPM_LOSS * health.bearing_wear
    return health.base_rpm * duty * clog_boost * max(0.0, wear_loss)


def expected_power_w(health: HVACHealth, duty: float) -> float:
    """Draw a healthy unit would show at this duty — the PWF reference."""
    return health.rated_power_w * duty


def power_draw(health: HVACHealth, duty: float) -> float:
    if duty <= 0.0:
        return 0.0
    return (expected_power_w(health, duty)
            * (1.0 + CLOG_POWER_GAIN * health.filter_clog)
            * (1.0 + FRICTION_POWER_GAIN * health.bearing_wear))


def vibration(health: HVACHealth) -> float:
    """Monotone in bearing wear so the alarm always precedes the failure."""
    return VIBRATION_BASE + VIBRATION_GAIN * health.bearing_wear ** 1.5


def _torque_nm(power_w: float, rpm: float) -> float:
    if rpm <= 0.0:
        return 0.0
    omega = 2.0 * math.pi * rpm / 60.0
    return power_w / omega


def step_health(health: HVACHealth, ac_power_pct: float, occupancy: int,
                room_temp: float, dt: float) -> HVACHealth:
    """Advance equipment condition by `dt` seconds.

    `ac_power_pct` is the commanded duty in [0, 1] — 0 when the HVAC is off.
    """
    duty = _clamp(ac_power_pct, 0.0, 1.0)
    hours = dt / 3600.0
    running = duty > 0.0

    # Filter loads with dust in proportion to airflow and how many people are
    # shedding particulates into the room.
    clog = health.filter_clog
    if running:
        clog += (CLOG_RATE_PER_HOUR * hours * duty
                 * (1.0 + DUST_PER_PERSON * max(0, occupancy)))
    clog = _clamp(clog, 0.0, 1.0)

    # Bearings wear with running hours, accelerated by heat: this coupling is
    # why a neglected filter eventually destroys the motor instead of merely
    # wasting energy.
    wear = health.bearing_wear
    if running:
        thermal = 1.0 + WEAR_THERMAL_STRESS * max(
            0.0, health.motor_temp - WEAR_THERMAL_KNEE) / 10.0
        wear += WEAR_RATE_PER_HOUR * hours * duty * thermal
    wear = _clamp(wear, 0.0, 1.0)

    runtime = health.runtime_hours + (hours if running else 0.0)

    interim = replace(health, filter_clog=clog, bearing_wear=wear,
                      runtime_hours=runtime)

    rpm = fan_speed(interim, duty)
    power_w = power_draw(interim, duty)

    # Motor heat balance. Rejection depends on airflow, which clogging destroys
    # even as the higher shaft load generates more heat — that asymmetry is what
    # produces runaway rather than a hotter steady state.
    q_generated = power_w * (1.0 - MOTOR_EFFICIENCY)
    airflow = (rpm / interim.base_rpm) * (1.0 - clog) if interim.base_rpm else 0.0
    h_total = H_NATURAL + H_FORCED * max(0.0, airflow)
    q_rejected = h_total * (health.motor_temp - room_temp)
    motor_temp = health.motor_temp + dt * (q_generated - q_rejected) / MOTOR_THERMAL_MASS
    motor_temp = _clamp(motor_temp, room_temp, MOTOR_TEMP_MAX)

    return replace(
        interim,
        motor_temp=motor_temp,
        fan_rpm=rpm,
        power_draw_w=power_w,
        torque_nm=_torque_nm(power_w, rpm),
        vibration_mm_s=vibration(interim),
    )


def failure_flags(health: HVACHealth, ac_power_pct: float) -> dict[str, bool]:
    """Current failure conditions, named after their AI4I 2020 counterparts.

    hdf     heat dissipation failure — motor past its insulation limit
    pwf     power failure — draw outside the band expected for this duty
    osf     overstrain failure — runtime x torque past the rated duty
    airflow filter exhausted (AI4I's tool-wear analogue)
    bearing vibration in ISO 10816's unacceptable zone

    Derived readings are recomputed from cumulative state rather than read off
    the stored fields, so this stays a pure function of (clog, wear, runtime,
    motor_temp, duty). Trusting the stored fields would misreport a unit that
    has not been stepped yet: its power_draw_w is still 0, which reads as a
    seized fan and trips PWF on brand-new hardware.
    """
    duty = _clamp(ac_power_pct, 0.0, 1.0)
    expected = expected_power_w(health, duty)
    if duty > 0.0 and expected > 0.0:
        ratio = power_draw(health, duty) / expected
        pwf = ratio < PWF_MIN_FRACTION or ratio > PWF_MAX_FRACTION
    else:
        pwf = False  # a stopped motor cannot have a power failure

    torque = _torque_nm(power_draw(health, duty), fan_speed(health, duty))

    return {
        "hdf": health.motor_temp >= MOTOR_TEMP_ALARM,
        "pwf": pwf,
        "osf": health.runtime_hours * torque > OSF_LIMIT_HR_NM,
        "airflow": health.filter_clog > CLOG_FAILURE,
        "bearing": vibration(health) >= VIBRATION_FAILURE,
    }


def any_failure(health: HVACHealth, ac_power_pct: float) -> bool:
    return any(failure_flags(health, ac_power_pct).values())


def apply_maintenance(health: HVACHealth, action: str) -> HVACHealth:
    """Apply a work order. Unknown actions are ignored rather than raising, so
    a malformed MQTT command can never take a unit down."""
    if action == "replace_filter":
        return replace(health, filter_clog=0.0)
    if action == "service_motor":
        return replace(health, bearing_wear=0.0, runtime_hours=0.0)
    return health
