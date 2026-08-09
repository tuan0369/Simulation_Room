"""Building-level coordination: budget allocation and maintenance work orders.

Two jobs:

1. Resolve the over-subscription the layout deliberately contains — the floors
   declare 22 + 22 kW against a 40 kW building — by allocating each floor a
   share of the real budget in proportion to demand, with a floor share so a
   quiet floor still covers its critical loads.
2. Turn ML risk scores into maintenance work orders, deduplicated so an alert
   that fires every 30 s does not become an alert nobody reads.

Like the floor twin, it advises. Every work order carries
`requires_human_approval`: the model opens tickets, a person approves anything
that takes equipment down.
"""
from __future__ import annotations

from building import BuildingConfig

RISK_THRESHOLD = 0.70        # matches the decision threshold in the model card
RECOVERY_THRESHOLD = 0.40    # risk must fall below this to re-arm an alert
MIN_FLOOR_SHARE = 0.15       # fraction of the budget every floor keeps

# Which factor drove the risk -> what a technician should actually do.
ACTION_FOR_FACTOR = {
    "filter_clog": "replace_filter",
    "power_draw_w": "replace_filter",
    "motor_temp": "service_motor",
    "motor_room_delta": "service_motor",
    "vibration_mm_s": "service_motor",
    "fan_rpm": "service_motor",
    "runtime_hours": "service_motor",
}


class BuildingTwin:
    """Coordinates floors and raises maintenance advisories."""

    def __init__(self, config: BuildingConfig):
        self.config = config
        self._known_rooms = {r.twin_id for r in config.all_rooms()}
        # twin_id -> fault signature currently raised, for dedupe
        self._open_orders: dict[str, str] = {}

    def topic(self, suffix: str) -> str:
        return f"twin/building/{suffix}"

    # ── Budget allocation ──────────────────────────────────────────────────

    def allocate_budgets(self, floor_summaries: dict) -> dict[str, float]:
        """Split the building budget across floors in proportion to demand."""
        if not floor_summaries:
            return {}

        budget = self.config.power_budget_kw
        demands = {fid: max(0.0, s.get("total_load_kw", 0.0))
                   for fid, s in floor_summaries.items()}
        total_demand = sum(demands.values())

        # Every floor is reserved a share before anything is distributed by
        # demand. A floor drawing nothing right now still has critical loads
        # that may start at any moment; allocating it 0 kW would put it over
        # budget the instant its server room called for cooling.
        floor_share = budget * MIN_FLOOR_SHARE
        divisible = max(0.0, budget - floor_share * len(demands))

        if total_demand <= 0:
            equal = floor_share + divisible / len(demands)
            return {fid: round(equal, 3) for fid in demands}

        if total_demand <= divisible:
            # Plenty to go round: cover demand and split the slack, rather than
            # inventing scarcity that would trigger pointless load shedding.
            headroom = (divisible - total_demand) / len(demands)
            return {fid: round(floor_share + d + headroom, 3)
                    for fid, d in demands.items()}

        return {
            fid: round(floor_share + divisible * (d / total_demand), 3)
            for fid, d in demands.items()
        }

    # ── Maintenance advisories ─────────────────────────────────────────────

    def advisories(self, risk_scores: dict) -> list[dict]:
        """Convert risk scores into deduplicated work orders.

        A room re-alerts when the driving factor changes, or when it recovers
        below RECOVERY_THRESHOLD and later relapses. Without the recovery gate
        a serviced-then-degraded unit would stay silent forever.
        """
        orders = []
        for twin_id, score in (risk_scores or {}).items():
            if twin_id not in self._known_rooms or not isinstance(score, dict):
                continue
            prob = score.get("failure_prob")
            if not isinstance(prob, (int, float)):
                continue

            if prob < RECOVERY_THRESHOLD:
                self._open_orders.pop(twin_id, None)
                continue
            if prob < RISK_THRESHOLD:
                continue

            factor = score.get("top_factor") or "unknown"
            if self._open_orders.get(twin_id) == factor:
                continue          # already raised for this fault
            self._open_orders[twin_id] = factor

            orders.append({
                "twin_id": twin_id,
                "failure_prob": round(float(prob), 4),
                "top_factor": factor,
                "action": ACTION_FOR_FACTOR.get(factor, "inspect"),
                "rul_hours": score.get("rul_hours"),
                "requires_human_approval": True,
            })
        return orders

    # ── Summary ────────────────────────────────────────────────────────────

    def summary(self, floor_summaries: dict) -> dict:
        total = sum(s.get("total_load_kw", 0.0)
                    for s in (floor_summaries or {}).values())
        return {
            "name": self.config.name,
            "floors": len(floor_summaries or {}),
            "total_load_kw": round(total, 3),
            "power_budget_kw": self.config.power_budget_kw,
            "over_budget": total > self.config.power_budget_kw,
            "open_work_orders": len(self._open_orders),
        }
