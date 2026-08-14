"""Pure display decisions for the EcoHVAC Guardian dashboard.

Keeping these decisions independent of Streamlit makes the dashboard's safety,
predictive-intelligence, and business-value language easy to test.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite


RISK_THRESHOLDS = {"medium": 0.35, "high": 0.65}


@dataclass(frozen=True)
class MaintenanceRecommendation:
    """Non-automated, simulation-only maintenance guidance."""

    severity: str
    title: str
    action: str
    rationale: str


def maintenance_recommendation(risk_band: str, drivers: list[dict] | tuple = ()) -> MaintenanceRecommendation:
    """Return a clear human recommendation without pretending to create a work order."""
    driver_names = [
        str(driver.get("feature", "")).replace("_", " ")
        for driver in drivers
        if isinstance(driver, dict) and driver.get("feature")
    ]
    evidence = ", ".join(driver_names[:2]) or "current fan-condition telemetry"
    band = risk_band.lower()
    if band == "high":
        return MaintenanceRecommendation(
            severity="high",
            title="Prioritise simulated AHU inspection",
            action="Inspect the filter, bearing temperature, and vibration before the next high-load period.",
            rationale=f"High simulated risk is driven by {evidence}.",
        )
    if band == "medium":
        return MaintenanceRecommendation(
            severity="medium",
            title="Schedule a simulated condition inspection",
            action="Inspect filter loading and bearing condition; continue monitoring during the next demand peak.",
            rationale=f"Medium simulated risk is driven by {evidence}.",
        )
    return MaintenanceRecommendation(
        severity="low",
        title="Continue simulated monitoring",
        action="No maintenance action is generated. Reassess if condition telemetry or risk rises.",
        rationale=f"Current simulated condition is stable; review {evidence} if it changes.",
    )


def comfort_status(temperature: float | None, setpoint: float | None, allocation_pct: float) -> tuple[str, str]:
    """Summarise a room's actionable comfort state without relying on colour alone."""
    if not isinstance(temperature, (int, float)) or not isinstance(setpoint, (int, float)):
        return "Waiting for telemetry", "No confirmed temperature/setpoint pair is available yet."
    error = float(temperature) - float(setpoint)
    if allocation_pct < 0.7 and error > 0.5:
        return "Capacity constrained", f"{error:+.1f} °C above target with limited shared airflow."
    if error > 1.0:
        return "Comfort attention", f"{error:+.1f} °C above target."
    if error < -1.0:
        return "Below target", f"{abs(error):.1f} °C below target."
    return "Comfort on track", f"{abs(error):.1f} °C from target."


def data_freshness(timestamp: str | None, *, now: datetime | None = None, stale_after_seconds: float = 10.0) -> tuple[str, str]:
    """Classify ISO timestamps for a telemetry freshness label."""
    if not timestamp:
        return "Unknown", "No telemetry timestamp is available."
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Unknown", "Telemetry timestamp is invalid."
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (reference - observed).total_seconds())
    if age_seconds <= stale_after_seconds:
        return "Fresh", f"Last telemetry {age_seconds:.0f}s ago."
    return "Stale", f"Last telemetry {age_seconds:.0f}s ago; do not treat it as live control confirmation."


def illustrative_roi(
    *,
    annual_energy_kwh: float,
    tariff_sgd_per_kwh: float,
    energy_reduction_pct: float,
    avoided_incident_value_sgd: float,
    annual_support_cost_sgd: float,
    implementation_cost_sgd: float,
) -> dict[str, float]:
    """Calculate transparent illustrative business-case values.

    These values are inputs for a pitch sandbox; they are not measurements or
    predictions from the simulation.
    """
    inputs = (
        annual_energy_kwh,
        tariff_sgd_per_kwh,
        energy_reduction_pct,
        avoided_incident_value_sgd,
        annual_support_cost_sgd,
        implementation_cost_sgd,
    )
    if not all(isinstance(value, (int, float)) and isfinite(float(value)) for value in inputs):
        raise ValueError("ROI inputs must be finite numbers")
    baseline_energy_cost = max(0.0, annual_energy_kwh) * max(0.0, tariff_sgd_per_kwh)
    energy_savings = baseline_energy_cost * min(1.0, max(0.0, energy_reduction_pct))
    annual_benefit = energy_savings + max(0.0, avoided_incident_value_sgd)
    annual_net_benefit = annual_benefit - max(0.0, annual_support_cost_sgd)
    implementation_cost = max(0.0, implementation_cost_sgd)
    roi_pct = (
        (annual_net_benefit - implementation_cost) / implementation_cost * 100.0
        if implementation_cost > 0
        else 0.0
    )
    monthly_net_benefit = annual_net_benefit / 12.0
    payback_months = implementation_cost / monthly_net_benefit if monthly_net_benefit > 0 else 0.0
    return {
        "baseline_energy_cost_sgd": baseline_energy_cost,
        "energy_savings_sgd": energy_savings,
        "annual_benefit_sgd": annual_benefit,
        "annual_net_benefit_sgd": annual_net_benefit,
        "roi_pct": roi_pct,
        "payback_months": payback_months,
    }


def allocation_explanation(decision: dict, room_labels: dict[str, str]) -> str:
    """Turn coordinator data into one plain-language capacity explanation."""
    if not decision:
        return "Waiting for the shared-AHU coordinator decision."
    if not decision.get("constrained"):
        return "Shared AHU capacity is sufficient: all current cooling requests can be granted."
    rooms = decision.get("rooms", [])
    if not isinstance(rooms, list):
        return "Shared capacity is constrained; review the latest coordinator decision."
    limited = []
    granted = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        label = room_labels.get(str(room.get("room_id")), str(room.get("room_id", "room")))
        requested = float(room.get("requested_airflow_m3_s", 0.0))
        delivered = float(room.get("granted_airflow_m3_s", 0.0))
        if delivered + 1e-9 < requested:
            limited.append(label)
        elif requested > 0:
            granted.append(label)
    if limited and granted:
        return (
            f"Shared airflow is scarce: {', '.join(granted)} received the higher comfort priority; "
            f"{', '.join(limited)} received less than requested."
        )
    if limited:
        return f"Shared airflow is scarce: {', '.join(limited)} received less than requested."
    return "Shared capacity is constrained; the coordinator has distributed the currently available airflow."
