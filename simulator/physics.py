"""Physics model for a room. Constants are locked by tests/test_physics.py.

Project 2 parameterises this by `building.RoomConfig` so six rooms can have
different thermal masses, AC sizes and envelopes. Every added argument is
OPTIONAL and defaults to Project 1's single-room constants, so the Project-1
test suite exercises this file unchanged — that is the regression guard for the
whole multi-room refactor.
"""
import random
from dataclasses import dataclass

HEAT_PER_PERSON_W = 100.0     # each person emits ~100W of heat
WALL_K = 0.05                 # heat transfer through walls (W/°C)
AC_POWER_W = 3500.0           # max cooling power of AC (variable-speed)
ROOM_HEAT_CAPACITY = 25000.0  # J/°C
T_OUTDOOR = 32.0
HUMIDITY_PER_PERSON = 0.06    # %/s per person
AC_DRY_RATE = 0.5             # max %/s dehumidification when AC at full power

TEMP_MIN, TEMP_MAX = 15.0, 40.0
HUM_MIN, HUM_MAX = 15.0, 80.0
OCC_MIN, OCC_MAX = 0, 30

# AC output temperature mapping: power% -> output air temperature
AC_TEMP_MAX = 28.0   # output temp at 0% power (just fan, no cooling)
AC_TEMP_MIN = 16.0   # output temp at 100% power (max cooling)

# Heat exchanged with each adjacent room through a shared wall or floor slab.
# Sized from a real partition: ~20 m2 of uninsulated internal wall at
# U ~= 1.25 W/m2K. A 15 C gap between rooms then moves ~375 W — the same order
# as a room full of people, and ~11% of a 3.5 kW AC, so neighbours genuinely
# influence each other without overpowering local control.
#
# An earlier value of 2.0 was chosen to be conservative and was ~20x below any
# plausible partition conductance; it made inter-room coupling invisible in
# practice, which would have left the ecosystem's central claim unobservable.
COUPLING_K = 25.0    # W/°C per neighbour


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass
class RoomState:
    temperature: float = 24.0
    humidity: float = 45.0
    occupancy: int = 2
    hvac_on: bool = False
    ac_power_pct: float = 0.0    # 0.0 - 1.0 (0% - 100% of max AC power)
    setpoint: float = 25.0       # desired room temperature (°C)
    time_scale: float = 1.0      # simulation speed multiplier
    mode: str = "manual"         # "manual" (user on/off) or "auto" (thermostat)


def auto_hvac_decision(temp: float, setpoint: float, occupancy: int,
                       currently_on: bool, always_on: bool = False) -> bool:
    """Thermostat decision for auto mode (occupancy-driven).

    - `always_on` room (server room): never shuts off. Its load is equipment,
      not people, so the empty-room rule below would strand it with 4 kW of
      running hardware and no cooling.
    - Empty room (occupancy == 0): always off — nobody to cool for.
    - Occupied and warmer than the target: engage the AC.
    - Occupied but at/below target: hold current state. While people are
      present the AC is never switched off; the PID simply modulates power
      (down to 0%) to keep the room comfortable.
    """
    if always_on:
        return True              # critical load -> 24/7 cooling
    if occupancy <= 0:
        return False             # empty room -> auto shut off
    if temp > setpoint:
        return True              # occupied & above target -> engage AC
    return currently_on          # occupied & comfortable -> hold (PID modulates)


def ac_output_temperature(power_pct: float) -> float:
    """Calculate the AC output air temperature based on power percentage.

    At 0% power: 28°C (just fan, no cooling)
    At 100% power: 16°C (max cooling)
    """
    pct = clamp(power_pct, 0.0, 1.0)
    return AC_TEMP_MAX - (AC_TEMP_MAX - AC_TEMP_MIN) * pct


def step_temperature(state: RoomState, dt: float, config=None,
                     neighbour_temps: dict | None = None,
                     outdoor_temp: float | None = None) -> float:
    """Advance room temperature by dt seconds.

    Heat sources: people + equipment + outdoor transfer + adjacent rooms
    Heat sink: AC cooling (proportional to ac_power_pct when hvac_on)

    With `config=None` and no neighbours this is exactly Project 1's model.
    """
    capacity = config.heat_capacity if config else ROOM_HEAT_CAPACITY
    ac_max = config.hvac_max_power_w if config else AC_POWER_W
    insulation = config.insulation_k if config else WALL_K
    equipment_w = config.base_equipment_w if config else 0.0
    solar = config.solar_gain if config else 1.0
    t_outdoor = outdoor_temp if outdoor_temp is not None else T_OUTDOOR

    q_people = state.occupancy * HEAT_PER_PERSON_W
    q_equipment = equipment_w
    q_outdoor = insulation * solar * (t_outdoor - state.temperature)
    q_ac = -ac_max * state.ac_power_pct if state.hvac_on else 0.0

    # Conduction to adjacent rooms. Signed by the gradient, so a room always
    # loses exactly the energy its neighbour gains.
    q_neighbours = 0.0
    if neighbour_temps:
        q_neighbours = COUPLING_K * sum(
            t - state.temperature for t in neighbour_temps.values()
        )

    t_next = state.temperature + (dt / capacity) * (
        q_people + q_equipment + q_outdoor + q_ac + q_neighbours
    )
    return clamp(t_next, TEMP_MIN, TEMP_MAX)


def step_humidity(state: RoomState, dt: float) -> float:
    """Advance room humidity by dt seconds.

    Humidity rises with people, falls with AC (proportional to power).
    """
    ac_dry = AC_DRY_RATE * state.ac_power_pct if state.hvac_on else 0.0
    rate = state.occupancy * HUMIDITY_PER_PERSON - ac_dry
    return clamp(state.humidity + rate * dt, HUM_MIN, HUM_MAX)


def step_occupancy(state: RoomState, rng: random.Random, config=None) -> int:
    """Random walk for occupancy, with wider steps at higher counts.

    At low occupancy (< 10): ±1 steps, biased toward staying
    At medium occupancy (10-20): ±1 to ±2 steps
    At high occupancy (> 20): ±1 to ±3 steps

    Superseded by `occupancy_twin.py` in the full ecosystem, which moves people
    between rooms instead of inventing and destroying them per room.
    """
    occ_max = config.max_occupancy if config else OCC_MAX
    if state.occupancy > 20:
        delta = rng.choice([-3, -2, -1, 0, 0, 1, 2, 3])
    elif state.occupancy > 10:
        delta = rng.choice([-2, -1, 0, 0, 1, 2])
    else:
        delta = rng.choice([-1, 0, 0, 1])  # biased toward staying still
    return clamp(state.occupancy + delta, OCC_MIN, occ_max)
