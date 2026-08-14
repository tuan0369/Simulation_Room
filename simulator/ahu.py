"""Shared-AHU state and lightweight physical models for the ecosystem twin."""
from dataclasses import dataclass

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .physics import ROOM_HEAT_CAPACITY, clamp
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from physics import ROOM_HEAT_CAPACITY, clamp

AIR_DENSITY_KG_M3 = 1.2
AIR_SPECIFIC_HEAT_J_KG_C = 1005.0
DEFAULT_SUPPLY_AIR_TEMP_C = 16.0
DEFAULT_MAX_AIRFLOW_M3_S = 0.24
MAX_FILTER_CLOG_PCT = 0.95


@dataclass(frozen=True)
class AHUState:
    """State for the AHU shared by both simulated rooms."""

    max_airflow_m3_s: float = DEFAULT_MAX_AIRFLOW_M3_S
    supply_air_temp_c: float = DEFAULT_SUPPLY_AIR_TEMP_C
    filter_clog_pct: float = 0.05
    fan_wear_pct: float = 0.03
    fan_speed_pct: float = 0.0
    fan_power_w: float = 0.0
    cooling_power_w: float = 0.0
    total_power_w: float = 0.0
    energy_kwh: float = 0.0


@dataclass(frozen=True)
class AHUEnergy:
    """A calculated power snapshot before it is integrated into AHU state."""

    fan_power_w: float
    cooling_power_w: float
    total_power_w: float


def available_airflow(ahu: AHUState) -> float:
    """Return capacity after filter resistance and fan wear are applied.

    A severely clogged filter reduces delivered flow. Fan wear adds a smaller
    independent derating, so the simulation can distinguish the two causes.
    """
    filter_factor = 1.0 - 0.65 * clamp(ahu.filter_clog_pct, 0.0, MAX_FILTER_CLOG_PCT)
    wear_factor = 1.0 - 0.15 * clamp(ahu.fan_wear_pct, 0.0, 1.0)
    return max(0.0, ahu.max_airflow_m3_s * filter_factor * wear_factor)


def cooling_power_w(
    room_temp_c: float, supply_air_temp_c: float, airflow_m3_s: float
) -> float:
    """Return sensible cooling delivered to a room by supplied air."""
    delta_c = max(0.0, room_temp_c - supply_air_temp_c)
    return AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_C * max(0.0, airflow_m3_s) * delta_c


def step_temperature_from_supply_air(
    current_temp_c: float,
    occupancy: int,
    delivered_airflow_m3_s: float,
    supply_air_temp_c: float,
    dt: float,
    *,
    outdoor_temp_c: float = 32.0,
    wall_k_w_c: float = 0.05,
    heat_per_person_w: float = 100.0,
) -> float:
    """Advance a room using a supply-air cooling term, not direct AC capacity."""
    q_people = max(0, occupancy) * heat_per_person_w
    q_outdoor = wall_k_w_c * (outdoor_temp_c - current_temp_c)
    q_cooling = cooling_power_w(current_temp_c, supply_air_temp_c, delivered_airflow_m3_s)
    next_temp = current_temp_c + dt * (q_people + q_outdoor - q_cooling) / ROOM_HEAT_CAPACITY
    return clamp(next_temp, 15.0, 40.0)


def step_humidity_from_supply_air(
    current_humidity_pct: float,
    occupancy: int,
    delivered_airflow_m3_s: float,
    dt: float,
) -> float:
    """Advance humidity using occupancy moisture and airflow-driven drying."""
    humidity_gain = max(0, occupancy) * 0.06
    drying_rate = max(0.0, delivered_airflow_m3_s) * 2.1
    next_humidity = current_humidity_pct + (humidity_gain - drying_rate) * dt
    return clamp(next_humidity, 15.0, 80.0)


def calculate_energy(
    ahu: AHUState,
    total_delivered_airflow_m3_s: float,
    room_cooling_w: float,
) -> AHUEnergy:
    """Calculate estimated fan and cooling electrical load for this tick.

    The values are simulation estimates, not billing-grade energy measurements.
    """
    capacity = max(ahu.max_airflow_m3_s, 1e-9)
    speed = clamp(total_delivered_airflow_m3_s / capacity, 0.0, 1.0)
    resistance = 1.0 + 1.8 * clamp(ahu.filter_clog_pct, 0.0, MAX_FILTER_CLOG_PCT)
    wear_penalty = 1.0 + 0.25 * clamp(ahu.fan_wear_pct, 0.0, 1.0)
    fan_power = 180.0 * speed**3 * resistance * wear_penalty
    # COP 3.2 means every 3.2 W of cooling needs approximately 1 W electric.
    cooling_power = max(0.0, room_cooling_w) / 3.2
    return AHUEnergy(
        fan_power_w=fan_power,
        cooling_power_w=cooling_power,
        total_power_w=fan_power + cooling_power,
    )


def advance_ahu(
    ahu: AHUState,
    total_delivered_airflow_m3_s: float,
    room_cooling_w: float,
    dt: float,
) -> AHUState:
    """Advance filter loading and energy over simulated time."""
    energy = calculate_energy(ahu, total_delivered_airflow_m3_s, room_cooling_w)
    capacity = max(ahu.max_airflow_m3_s, 1e-9)
    speed = clamp(total_delivered_airflow_m3_s / capacity, 0.0, 1.0)
    filter_growth = 0.0000025 * speed * max(dt, 0.0)
    return AHUState(
        max_airflow_m3_s=ahu.max_airflow_m3_s,
        supply_air_temp_c=ahu.supply_air_temp_c,
        filter_clog_pct=clamp(ahu.filter_clog_pct + filter_growth, 0.0, MAX_FILTER_CLOG_PCT),
        fan_wear_pct=ahu.fan_wear_pct,
        fan_speed_pct=speed,
        fan_power_w=energy.fan_power_w,
        cooling_power_w=energy.cooling_power_w,
        total_power_w=energy.total_power_w,
        energy_kwh=ahu.energy_kwh + energy.total_power_w * max(dt, 0.0) / 3_600_000.0,
    )
