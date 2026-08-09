"""Floor-level supervision: aggregate, then advise.

A floor twin never touches a room's control loop. When the floor exceeds its
electrical allocation it returns *setpoint nudges* — recommendations the room
twins are free to apply — and it returns nothing at all when there is no
problem. That is the difference between federated supervision and a
centralized controller: the rooms keep deciding, and a dead floor twin costs
coordination, not cooling.
"""
from __future__ import annotations

from building import FloorConfig

# A supervisor can ask a room to run warmer, but only slightly. Bounding this
# is what stops load shedding from ever making a room unsafe.
MAX_NUDGE_C = 1.5

# Below this, a nudge is not worth the message.
MIN_NUDGE_C = 0.1

# Raising a setpoint by 1 C sheds roughly this share of a room's cooling draw.
SHED_PER_DEGREE = 0.25


class FloorTwin:
    """Aggregates one floor and arbitrates its power budget."""

    def __init__(self, config: FloorConfig):
        self.config = config

    @property
    def floor_id(self) -> str:
        return self.config.floor_id

    def topic(self, suffix: str = "summary") -> str:
        return f"twin/{self.config.floor_id}/{suffix}"

    # ── Aggregation ────────────────────────────────────────────────────────

    def aggregate(self, room_twins: dict) -> dict:
        """Roll the floor's rooms up into one record.

        Publishes counts and totals only — never per-person detail. Occupancy
        is personal-adjacent data, and keeping it room-local is the privacy
        argument in docs/governance.md.
        """
        mine = self._mine(room_twins)
        load_kw = sum(t.electrical_load_w() for t in mine.values()) / 1000.0
        temps = [t.state.temperature for t in mine.values()]
        return {
            "floor_id": self.config.floor_id,
            "name": self.config.name,
            "rooms": len(mine),
            "total_load_kw": round(load_kw, 3),
            "power_budget_kw": self.config.power_budget_kw,
            "occupancy": sum(t.state.occupancy for t in mine.values()),
            "mean_temp": round(sum(temps) / len(temps), 2) if temps else None,
            "rooms_cooling": sum(1 for t in mine.values() if t.state.hvac_on),
        }

    def _mine(self, room_twins: dict) -> dict:
        """Only this floor's rooms, so a caller can pass the whole building."""
        ids = {r.twin_id for r in self.config.rooms}
        return {tid: t for tid, t in room_twins.items() if tid in ids}

    # ── Arbitration ────────────────────────────────────────────────────────

    def arbitrate(self, room_twins: dict, budget_kw: float) -> dict[str, float]:
        """Recommend setpoint nudges to bring the floor under `budget_kw`.

        Returns {} when the floor already fits — supervisors stay quiet. Never
        mutates a room twin: the return value is advice, and applying it is the
        room's decision.
        """
        mine = self._mine(room_twins)
        load_kw = sum(t.electrical_load_w() for t in mine.values()) / 1000.0
        excess_kw = load_kw - budget_kw
        if excess_kw <= 0:
            return {}

        # Critical loads are exempt: the server room protects hardware, not
        # comfort, so shedding it would defeat the point of cooling it.
        sheddable = {
            tid: t for tid, t in mine.items()
            if not t.config.always_on and t.state.hvac_on
        }
        if not sheddable:
            return {}

        # Spread the burden evenly rather than shedding the largest room to
        # zero. Concentrating it would make one room permanently uncomfortable
        # whenever the floor is busy.
        shed_kw_each = excess_kw / len(sheddable)
        nudges: dict[str, float] = {}
        for tid, twin in sorted(sheddable.items()):
            room_kw = twin.electrical_load_w() / 1000.0
            if room_kw <= 0:
                continue
            needed_c = shed_kw_each / (room_kw * SHED_PER_DEGREE)
            nudge = min(MAX_NUDGE_C, max(MIN_NUDGE_C, needed_c))
            nudges[tid] = round(nudge, 2)
        return nudges

    def predicted_load_kw(self, room_twins: dict, nudges: dict) -> float:
        """Estimated floor load after the nudges are applied."""
        mine = self._mine(room_twins)
        total_w = 0.0
        for tid, twin in mine.items():
            load = twin.electrical_load_w()
            if tid in nudges:
                load *= max(0.0, 1.0 - SHED_PER_DEGREE * nudges[tid])
            total_w += load
        return total_w / 1000.0
