"""Transparent shared-AHU allocation policy for the intelligent ecosystem."""
import math
from dataclasses import dataclass


POLICY_NAME = "occupied-comfort-debt-v2"
MAX_COMFORT_DEBT_C_S = 3_600.0
COMFORT_DEBT_RECOVERY_RATE = 2.0


@dataclass(frozen=True)
class RoomDemand:
    """A room's requested supply airflow and comfort context."""

    room_id: str
    requested_airflow_m3_s: float
    occupancy: int
    temperature_c: float
    setpoint_c: float
    enabled: bool
    comfort_debt_c_s: float = 0.0
    limited_service_s: float = 0.0

    @property
    def temperature_error_c(self) -> float:
        return max(0.0, self.temperature_c - self.setpoint_c)


@dataclass(frozen=True)
class AllocationDecision:
    """Explainable airflow allocation for one room."""

    room_id: str
    requested_airflow_m3_s: float
    granted_airflow_m3_s: float
    priority_score: tuple[int, float, float, int, str]
    reason_codes: tuple[str, ...]
    comfort_debt_c_s: float = 0.0
    limited_service_s: float = 0.0


@dataclass(frozen=True)
class CoordinationResult:
    """The complete, deterministic result of one shared-capacity allocation."""

    available_airflow_m3_s: float
    requested_airflow_m3_s: float
    constrained: bool
    decisions: tuple[AllocationDecision, ...]


def _finite_nonnegative(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Coordinator inputs must be finite")
    return max(0.0, numeric)


def _priority(demand: RoomDemand) -> tuple[int, float, float, int, str]:
    """Rank occupancy and current comfort need before debt-based tie recovery."""
    return (
        1 if demand.occupancy > 0 else 0,
        demand.temperature_error_c,
        _finite_nonnegative(demand.comfort_debt_c_s),
        demand.occupancy,
        demand.room_id,
    )


def update_comfort_debt(
    demand: RoomDemand,
    granted_airflow_m3_s: float,
    dt: float,
) -> tuple[float, float]:
    """Return bounded comfort debt and consecutive limited-service time."""
    duration = _finite_nonnegative(dt)
    request = _finite_nonnegative(demand.requested_airflow_m3_s) if demand.enabled else 0.0
    granted = min(request, _finite_nonnegative(granted_airflow_m3_s))
    debt = _finite_nonnegative(demand.comfort_debt_c_s)
    limited = _finite_nonnegative(demand.limited_service_s)
    if not demand.enabled or demand.occupancy <= 0 or request <= 1e-9:
        return max(0.0, debt - COMFORT_DEBT_RECOVERY_RATE * duration), 0.0
    if granted + 1e-9 < request:
        unmet_ratio = (request - granted) / request
        debt += demand.temperature_error_c * unmet_ratio * duration
        limited += duration
    else:
        debt -= COMFORT_DEBT_RECOVERY_RATE * duration
        limited = 0.0
    return min(MAX_COMFORT_DEBT_C_S, max(0.0, debt)), limited


def coordinate(
    demands: list[RoomDemand], available_airflow_m3_s: float
) -> CoordinationResult:
    """Allocate finite AHU airflow using the occupied-comfort-debt-v2 policy.

    The function is deliberately pure and deterministic so that every allocation
    can be explained, tested, and replayed from a telemetry snapshot.
    """
    available = _finite_nonnegative(available_airflow_m3_s)
    requested = sum(
        _finite_nonnegative(demand.requested_airflow_m3_s)
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
            -_priority(demand)[3],
            _priority(demand)[4],
        ),
    )

    for demand in ordered:
        request = _finite_nonnegative(demand.requested_airflow_m3_s) if demand.enabled else 0.0
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
        if demand.comfort_debt_c_s > 1e-9:
            reasons.append("comfort_debt_priority")

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
            comfort_debt_c_s=_finite_nonnegative(demand.comfort_debt_c_s),
            limited_service_s=_finite_nonnegative(demand.limited_service_s),
        )

    return CoordinationResult(
        available_airflow_m3_s=available,
        requested_airflow_m3_s=requested,
        constrained=constrained,
        decisions=tuple(by_room[demand.room_id] for demand in demands),
    )
