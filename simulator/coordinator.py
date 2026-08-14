"""Transparent shared-AHU allocation policy for the intelligent ecosystem."""
from dataclasses import dataclass


POLICY_NAME = "occupied-comfort-v1"


@dataclass(frozen=True)
class RoomDemand:
    """A room's requested supply airflow and comfort context."""

    room_id: str
    requested_airflow_m3_s: float
    occupancy: int
    temperature_c: float
    setpoint_c: float
    enabled: bool

    @property
    def temperature_error_c(self) -> float:
        return max(0.0, self.temperature_c - self.setpoint_c)


@dataclass(frozen=True)
class AllocationDecision:
    """Explainable airflow allocation for one room."""

    room_id: str
    requested_airflow_m3_s: float
    granted_airflow_m3_s: float
    priority_score: tuple[int, float, int, str]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class CoordinationResult:
    """The complete, deterministic result of one shared-capacity allocation."""

    available_airflow_m3_s: float
    requested_airflow_m3_s: float
    constrained: bool
    decisions: tuple[AllocationDecision, ...]


def _priority(demand: RoomDemand) -> tuple[int, float, int, str]:
    """Rank occupied, uncomfortable rooms first with stable tie-breaking."""
    return (
        1 if demand.occupancy > 0 else 0,
        demand.temperature_error_c,
        demand.occupancy,
        demand.room_id,
    )


def coordinate(
    demands: list[RoomDemand], available_airflow_m3_s: float
) -> CoordinationResult:
    """Allocate finite AHU airflow using the occupied-comfort-v1 policy.

    The function is deliberately pure and deterministic so that every allocation
    can be explained, tested, and replayed from a telemetry snapshot.
    """
    available = max(0.0, available_airflow_m3_s)
    requested = sum(
        max(0.0, demand.requested_airflow_m3_s)
        for demand in demands
        if demand.enabled
    )
    constrained = requested > available + 1e-9
    remaining = available
    by_room: dict[str, AllocationDecision] = {}

    ordered = sorted(
        demands,
        key=lambda demand: (
            -_priority(demand)[0],
            -_priority(demand)[1],
            -_priority(demand)[2],
            _priority(demand)[3],
        ),
    )

    for demand in ordered:
        request = max(0.0, demand.requested_airflow_m3_s) if demand.enabled else 0.0
        score = _priority(demand)
        reasons: list[str] = []
        if not demand.enabled:
            reasons.append("zone_disabled")
        elif demand.occupancy > 0:
            reasons.append("occupied")
        else:
            reasons.append("unoccupied_lower_priority")

        if demand.temperature_error_c > 0:
            reasons.append("above_setpoint")
        else:
            reasons.append("at_or_below_setpoint")

        granted = min(request, remaining)
        remaining -= granted
        if request <= 1e-9:
            reasons.append("no_airflow_requested")
        elif granted + 1e-9 >= request:
            reasons.append("full_request_granted")
        else:
            reasons.append("capacity_limited")
            if demand.occupancy > 0:
                reasons.append("higher_comfort_priority_applied")

        by_room[demand.room_id] = AllocationDecision(
            room_id=demand.room_id,
            requested_airflow_m3_s=request,
            granted_airflow_m3_s=granted,
            priority_score=score,
            reason_codes=tuple(reasons),
        )

    return CoordinationResult(
        available_airflow_m3_s=available,
        requested_airflow_m3_s=requested,
        constrained=constrained,
        decisions=tuple(by_room[demand.room_id] for demand in demands),
    )
