"""Building-wide occupancy twin: people flow, not per-room noise.

Project 1 gave each room an independent random walk. That is not a twin — it
invents and destroys people, so a room emptying tells you nothing about where
anyone went. This twin keeps a single population and *moves* it: rooms exchange
people with their floor corridor, corridors exchange across the stairwell, and
only the ground-floor entrance changes the building total.

That conservation is what lets the energy twin and the occupancy twin genuinely
interact: a class ending in `f1/lab-a` puts load into `f2/meeting-room` a few
minutes later, and the thermal consequence follows the people.

Deterministic given a seeded `random.Random` — the dataset generator depends on
byte-reproducible traces.
"""
from __future__ import annotations

import random

from building import BuildingConfig, RoomConfig

# Only the ground-floor corridor touches the street; everyone enters and leaves
# through it, which is what makes the conservation check meaningful.
ENTRANCE_NODE = "f1/corridor"

# People crossing one graph edge per second. Integer people with fractional
# rates would stall, so each edge moves at least one person per step.
MOVE_RATE_PER_S = 0.5        # room <-> its floor corridor
STAIR_RATE_PER_S = 0.5       # corridor <-> corridor
ENTRANCE_RATE_PER_S = 1.0    # street <-> ground corridor

OPEN_HOUR, CLOSE_HOUR = 7.0, 22.0


def _edge_capacity(rate_per_s: float, dt: float) -> int:
    return max(1, int(rate_per_s * dt))


# ── Schedules ───────────────────────────────────────────────────────────────

def _class_schedule(hour: float) -> float:
    for start, end in ((9.0, 11.0), (13.0, 15.0), (16.0, 18.0)):
        if start <= hour < end:
            return 1.0
    return 0.15 if 8.0 <= hour < 18.0 else 0.0      # stragglers between classes


def _steady_daytime(hour: float) -> float:
    if 8.0 <= hour < 9.0:
        return 0.85 * (hour - 8.0)                  # arrival ramp
    if 9.0 <= hour < 17.0:
        return 0.85
    if 17.0 <= hour < 18.0:
        return 0.85 * (18.0 - hour)                 # departure ramp
    return 0.0


def _bursty(hour: float) -> float:
    for start, end in ((10.0, 11.0), (14.0, 15.0)):
        if start <= hour < end:
            return 0.9
    return 0.05 if 8.0 <= hour < 18.0 else 0.0


_PROFILES = {
    "class_schedule": _class_schedule,
    "steady_daytime": _steady_daytime,
    "bursty": _bursty,
    "unoccupied": lambda hour: 0.0,
}


def target_fraction(profile: str, hour: float) -> float:
    """Fraction of capacity this profile wants at this hour.

    Unknown profiles return 0.0 rather than raising: a typo in the layout
    should leave a room empty, not crash the simulator.
    """
    return _PROFILES.get(profile, lambda h: 0.0)(hour)


def target_occupancy(room: RoomConfig, hour: float, bias: float = 1.0) -> int:
    frac = target_fraction(room.occupancy_profile, hour) * bias
    return max(0, min(room.max_occupancy, int(round(frac * room.max_occupancy))))


# ── The twin ────────────────────────────────────────────────────────────────

class OccupancyTwin:
    """Tracks and moves the building's population."""

    def __init__(self, building: BuildingConfig, rng: random.Random | None = None):
        self.building = building
        self.rng = rng or random.Random()
        self.entrance_open = True
        self.last_entrance_flow = 0

        self.rooms = {r.twin_id: r for r in building.all_rooms()}
        self.corridors = [f.corridor_id for f in building.floors]
        self.nodes = list(self.rooms) + self.corridors
        self.occupancy: dict[str, int] = {n: 0 for n in self.nodes}

        # Per-room bias, redrawn when a room's schedule block changes, so
        # targets vary between days without thrashing every step.
        self._bias = {tid: self._draw_bias() for tid in self.rooms}
        self._last_fraction = {tid: None for tid in self.rooms}

    def _draw_bias(self) -> float:
        return self.rng.uniform(0.75, 1.0)

    @property
    def total_in_building(self) -> int:
        return sum(self.occupancy.values())

    def corridor_of(self, room: RoomConfig) -> str:
        return f"{room.floor}/corridor"

    # ── Movement primitives ────────────────────────────────────────────────

    def _move(self, src: str, dst: str, count: int) -> int:
        """Move up to `count` people along one edge. Returns how many moved."""
        moved = max(0, min(count, self.occupancy[src]))
        if moved:
            self.occupancy[src] -= moved
            self.occupancy[dst] += moved
        return moved

    def _targets(self, hour: float) -> dict[str, int]:
        targets = {}
        for tid, room in self.rooms.items():
            frac = target_fraction(room.occupancy_profile, hour)
            if frac != self._last_fraction[tid]:
                self._bias[tid] = self._draw_bias()
                self._last_fraction[tid] = frac
            targets[tid] = target_occupancy(room, hour, self._bias[tid])
        return targets

    # ── Step ───────────────────────────────────────────────────────────────

    def step(self, sim_time_s: float, dt: float) -> dict[str, int]:
        """Advance people flow by `dt` seconds; returns room occupancy only."""
        hour = (sim_time_s / 3600.0) % 24.0
        targets = self._targets(hour)
        room_cap = _edge_capacity(MOVE_RATE_PER_S, dt)
        stair_cap = _edge_capacity(STAIR_RATE_PER_S, dt)
        door_cap = _edge_capacity(ENTRANCE_RATE_PER_S, dt)
        self.last_entrance_flow = 0

        # 1. Rooms shed anyone above target into their own corridor. Done first
        #    so leavers are available to fill other rooms this same step.
        for tid, room in self.rooms.items():
            surplus = self.occupancy[tid] - targets[tid]
            if surplus > 0:
                self._move(tid, self.corridor_of(room), min(surplus, room_cap))

        # 2. Entrance. Admit or release to track total demand, so the building
        #    fills in the morning and empties at night.
        demand = sum(targets.values())
        gap = demand - self.total_in_building
        if self.entrance_open:
            if OPEN_HOUR <= hour < CLOSE_HOUR and gap > 0:
                admitted = min(gap, door_cap)
                self.occupancy[ENTRANCE_NODE] += admitted
                self.last_entrance_flow = admitted
            elif gap < 0:
                # Only people already standing in the ground-floor corridor can
                # leave — you cannot exit a building from the second floor.
                leaving = min(-gap, self.occupancy[ENTRANCE_NODE], door_cap)
                self.occupancy[ENTRANCE_NODE] -= leaving
                self.last_entrance_flow = -leaving

        # 3. Rooms pull from their own corridor toward target. A room can only
        #    take people already standing on its floor — that is what stops
        #    anyone teleporting between floors.
        for tid, room in self.rooms.items():
            deficit = targets[tid] - self.occupancy[tid]
            if deficit > 0:
                self._move(self.corridor_of(room), tid, min(deficit, room_cap))

        # 4. Stairs last, so people who cross a floor boundary spend at least
        #    one step in the corridor before entering a room. Balancing before
        #    the pull let them traverse stairwell and doorway in a single step,
        #    which made transit instantaneous and unobservable.
        self._balance_corridors(targets, stair_cap)

        return {tid: self.occupancy[tid] for tid in self.rooms}

    def _balance_corridors(self, targets: dict[str, int], cap: int) -> None:
        """Move people up or down the stairwell toward unmet demand."""
        if len(self.corridors) < 2:
            return
        ground, upper = ENTRANCE_NODE, next(
            c for c in self.corridors if c != ENTRANCE_NODE)

        upper_need = sum(
            targets[tid] - self.occupancy[tid]
            for tid, room in self.rooms.items()
            if self.corridor_of(room) == upper
        ) - self.occupancy[upper]

        if upper_need > 0:
            self._move(ground, upper, min(upper_need, cap))
        elif upper_need < 0:
            self._move(upper, ground, min(-upper_need, cap))
