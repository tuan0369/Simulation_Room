"""Predictive intelligence and proactive demand forecasting for the digital twin ecosystem.

Calculates forward-looking sensible thermal loads and required airflows before
room temperatures climb, identifies equipment and comfort risks, and generates
targeted mitigation action recommendations with support for autonomous closed-loop execution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

try:
    from .ahu import AIR_DENSITY_KG_M3, AIR_SPECIFIC_HEAT_J_KG_C, DEFAULT_SUPPLY_AIR_TEMP_C
    from .physics import HEAT_PER_PERSON_W, ROOM_HEAT_CAPACITY, T_OUTDOOR, WALL_K, clamp
except ImportError:
    from ahu import AIR_DENSITY_KG_M3, AIR_SPECIFIC_HEAT_J_KG_C, DEFAULT_SUPPLY_AIR_TEMP_C
    from physics import HEAT_PER_PERSON_W, ROOM_HEAT_CAPACITY, T_OUTDOOR, WALL_K, clamp

ActionType = Literal[
    "PREEMPTIVE_PRECOOL",
    "PROACTIVE_FAN_DERATE",
    "COMFORT_DEBT_SHIELD",
    "PREEMPTIVE_FILTER_SERVICE",
    "BALANCED_LOAD_DISPATCH",
    "EQUIPMENT_RETROFIT_ADVISORY",
]


@dataclass(frozen=True)
class RoomDemandForecast:
    """Predicted thermal load and required cooling airflow for a single zone."""

    room_id: str
    current_temp_c: float
    setpoint_c: float
    occupancy: int
    predicted_internal_heat_w: float
    predicted_envelope_heat_w: float
    total_thermal_load_w: float
    required_airflow_m3_s: float
    projected_temp_5min_c: float
    projected_temp_15min_c: float
    urgency: Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class EcosystemDemandForecast:
    """Combined predictive demand forecast across all zones and the shared AHU."""

    timestamp: str
    rooms: dict[str, RoomDemandForecast]
    total_required_airflow_m3_s: float
    available_airflow_m3_s: float
    capacity_shortfall_m3_s: float
    is_capacity_deficit_projected: bool


@dataclass(frozen=True)
class RecommendedAction:
    """Actionable mitigation recommendation produced by predictive intelligence."""

    action_id: str
    action_type: ActionType
    title: str
    target: str  # e.g., "room1", "room2", "ahu", "ecosystem"
    description: str
    rationale: str
    confidence: float  # 0.0 - 1.0
    parameters: dict
    severity: Literal["low", "medium", "high", "critical"]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def forecast_room_demand(
    room_id: str,
    current_temp_c: float,
    setpoint_c: float,
    occupancy: int,
    current_airflow_m3_s: float = 0.0,
    supply_air_temp_c: float = DEFAULT_SUPPLY_AIR_TEMP_C,
    horizon_seconds: float = 300.0,
) -> RoomDemandForecast:
    """Predict thermal cooling demand and projected temperatures ahead of time."""
    t_curr = float(current_temp_c)
    t_set = float(setpoint_c)
    occ = max(0, int(occupancy))

    # Heat sources
    q_people = occ * HEAT_PER_PERSON_W
    q_envelope = WALL_K * (T_OUTDOOR - t_curr)
    total_heat = q_people + q_envelope

    # Target pull-down load to reach/maintain setpoint over a 600-second target window
    pull_down_w = max(0.0, (t_curr - t_set) * ROOM_HEAT_CAPACITY / 600.0)
    target_cooling_w = total_heat + pull_down_w

    # Required airflow to deliver target cooling: Q = rho * Cp * V * (T_room - T_supply)
    delta_t = max(1.0, t_curr - supply_air_temp_c)
    req_airflow = target_cooling_w / (AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_C * delta_t)
    req_airflow = clamp(req_airflow, 0.0, 0.20)

    # Current cooling delivered
    current_cooling_w = AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_C * max(0.0, current_airflow_m3_s) * delta_t
    net_heat_rate_w = total_heat - current_cooling_w

    # Projected temperatures if current conditions continue
    proj_5m = clamp(t_curr + (net_heat_rate_w / ROOM_HEAT_CAPACITY) * 300.0, 15.0, 40.0)
    proj_15m = clamp(t_curr + (net_heat_rate_w / ROOM_HEAT_CAPACITY) * 900.0, 15.0, 40.0)

    # Urgency assessment
    error = t_curr - t_set
    if error > 2.0 or proj_5m > t_set + 2.5 or (occ > 15 and req_airflow > 0.12):
        urgency = "critical"
    elif error > 1.0 or proj_5m > t_set + 1.2 or occ > 10:
        urgency = "high"
    elif error > 0.4 or occ > 4:
        urgency = "medium"
    else:
        urgency = "low"

    return RoomDemandForecast(
        room_id=room_id,
        current_temp_c=round(t_curr, 2),
        setpoint_c=round(t_set, 1),
        occupancy=occ,
        predicted_internal_heat_w=round(q_people, 1),
        predicted_envelope_heat_w=round(q_envelope, 1),
        total_thermal_load_w=round(total_heat, 1),
        required_airflow_m3_s=round(req_airflow, 4),
        projected_temp_5min_c=round(proj_5m, 2),
        projected_temp_15min_c=round(proj_15m, 2),
        urgency=urgency,
    )


def forecast_ecosystem_demand(
    rooms_data: dict[str, dict],
    available_ahu_airflow_m3_s: float,
    supply_air_temp_c: float = DEFAULT_SUPPLY_AIR_TEMP_C,
) -> EcosystemDemandForecast:
    """Aggregate demand forecasts across both rooms and compare with shared AHU capacity."""
    forecasts: dict[str, RoomDemandForecast] = {}
    total_req_airflow = 0.0

    for room_id, rdata in rooms_data.items():
        forecast = forecast_room_demand(
            room_id=room_id,
            current_temp_c=rdata.get("temperature", 24.0),
            setpoint_c=rdata.get("setpoint", 24.0),
            occupancy=rdata.get("occupancy", 0),
            current_airflow_m3_s=rdata.get("delivered_airflow_m3_s", 0.0),
            supply_air_temp_c=supply_air_temp_c,
        )
        forecasts[room_id] = forecast
        total_req_airflow += forecast.required_airflow_m3_s

    avail = max(0.0, float(available_ahu_airflow_m3_s))
    shortfall = max(0.0, total_req_airflow - avail)
    is_deficit = shortfall > 0.005

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return EcosystemDemandForecast(
        timestamp=now_iso,
        rooms=forecasts,
        total_required_airflow_m3_s=round(total_req_airflow, 4),
        available_airflow_m3_s=round(avail, 4),
        capacity_shortfall_m3_s=round(shortfall, 4),
        is_capacity_deficit_projected=is_deficit,
    )


def generate_recommendations(
    forecast: EcosystemDemandForecast,
    fan_health_data: dict,
    ahu_data: dict,
    rooms_data: dict[str, dict],
) -> list[RecommendedAction]:
    """Analyze current telemetry and forward forecasts to formulate targeted mitigation actions."""
    recommendations: list[RecommendedAction] = []
    failure_risk = fan_health_data.get("failure_risk")
    risk_num = float(failure_risk) if isinstance(failure_risk, (int, float)) and math.isfinite(failure_risk) else 0.0
    filter_clog = float(ahu_data.get("filter_clog_pct", 0.05))
    fan_wear = float(fan_health_data.get("wear_pct", 0.03))

    # 1. Equipment Risk: Proactive Fan Derate / Speed Limit
    if risk_num >= 0.50 or fan_wear > 0.60:
        recommendations.append(
            RecommendedAction(
                action_id=f"ACT-DERATE-{int(datetime.now(timezone.utc).timestamp())}",
                action_type="PROACTIVE_FAN_DERATE",
                title="Proactive Fan Load Derating",
                target="ahu",
                description="Derate peak fan speed to 70% to alleviate bearing stress and prolong equipment MTBF.",
                rationale=f"Predictive fan failure risk is at {risk_num:.0%} (wear: {fan_wear:.0%}). Throttling protects mechanical integrity.",
                confidence=min(0.95, 0.70 + risk_num * 0.25),
                parameters={"fan_speed_cap_pct": 0.70, "duration_seconds": 600},
                severity="critical" if risk_num >= 0.65 else "high",
            )
        )

    # 2. Equipment Condition: Preemptive Filter Service
    if filter_clog >= 0.65:
        recommendations.append(
            RecommendedAction(
                action_id=f"ACT-FLT-{int(datetime.now(timezone.utc).timestamp())}",
                action_type="PREEMPTIVE_FILTER_SERVICE",
                title="Preemptive Filter Replacement",
                target="ahu",
                description="Dispatch simulated filter cleaning to restore full AHU aerodynamic flow capacity.",
                rationale=f"Filter clog is at {filter_clog:.0%}, causing aerodynamic resistance and cutting supply airflow.",
                confidence=0.92,
                parameters={"filter_clog_target_pct": 0.05},
                severity="high" if filter_clog >= 0.80 else "medium",
            )
        )

    # 3. Occupancy Surge & Thermal Load: Preemptive Pre-Cooling across all 4 zones
    zone_capacities = {"room1": 30, "room2": 20, "room3": 15, "room4": 20}
    for room_id, rforecast in forecast.rooms.items():
        cap = zone_capacities.get(room_id, 20)
        occ_ratio = rforecast.occupancy / max(1, cap)
        is_high_occ = rforecast.occupancy >= 8 or occ_ratio >= 0.40
        is_thermal_threat = rforecast.projected_temp_5min_c > rforecast.setpoint_c + 0.2 or rforecast.total_thermal_load_w >= 1000.0
        
        if (is_high_occ and rforecast.current_temp_c >= rforecast.setpoint_c - 0.5) or is_thermal_threat:
            recommendations.append(
                RecommendedAction(
                    action_id=f"ACT-COOL-{room_id}-{int(datetime.now(timezone.utc).timestamp())}",
                    action_type="PREEMPTIVE_PRECOOL",
                    title=f"Preemptive Pre-Cooling for {room_id.upper()}",
                    target=room_id,
                    description=f"Lower setpoint by 1.5°C in {room_id} to absorb incoming occupant & equipment thermal load ({rforecast.total_thermal_load_w:.0f} W).",
                    rationale=f"Zone {room_id.upper()} has {rforecast.occupancy} occupants ({occ_ratio:.0%} capacity) with {rforecast.total_thermal_load_w:.0f} W sensible load, risking thermal overshoot.",
                    confidence=min(0.95, 0.75 + occ_ratio * 0.20),
                    parameters={"room_id": room_id, "temp_offset_c": -1.5, "setpoint": max(18.0, rforecast.setpoint_c - 1.5)},
                    severity="high" if (rforecast.occupancy >= cap * 0.70 or is_thermal_threat) else "medium",
                )
            )

    # 4. Capacity Deficit: Comfort Debt Shielding & Balanced Dispatch
    if forecast.is_capacity_deficit_projected:
        recommendations.append(
            RecommendedAction(
                action_id=f"ACT-SHIELD-{int(datetime.now(timezone.utc).timestamp())}",
                action_type="COMFORT_DEBT_SHIELD",
                title="Comfort-Debt Fairness Shielding",
                target="ecosystem",
                description="Enforce strict occupied-comfort allocation and shield high-debt zones from starvation.",
                rationale=f"Total required airflow ({forecast.total_required_airflow_m3_s:.3f} m³/s) exceeds available AHU supply ({forecast.available_airflow_m3_s:.3f} m³/s) by {forecast.capacity_shortfall_m3_s:.3f} m³/s.",
                confidence=0.90,
                parameters={"enforce_debt_cap": True, "stagger_demand": True},
                severity="high",
            )
        )

    # 5. Long-term Equipment Sizing & CapEx Procurement Advisory
    # When software optimization reaches the physical thermodynamic capacity limit of the installed equipment:
    if forecast.total_required_airflow_m3_s > 0.48 * 1.15 or (forecast.is_capacity_deficit_projected and filter_clog <= 0.20 and risk_num > 0.60):
        recommendations.append(
            RecommendedAction(
                action_id=f"ACT-CAPEX-{int(datetime.now(timezone.utc).timestamp())}",
                action_type="EQUIPMENT_RETROFIT_ADVISORY",
                title="Capital Equipment Retrofit Advisory (CapEx Upgrade)",
                target="ahu",
                description="Physical cooling demand exceeds the 0.48 m³/s maximum design ceiling of the current AHU. Software optimization alone cannot eliminate the thermal deficit during full occupancy. Recommend upgrading to a 0.75 m³/s VAV AHU or installing a dedicated 3.5 kW auxiliary split-unit in high-heat zones (Computing Hub / Robotics Lab).",
                rationale=f"Thermodynamic saturation reached: 4-zone total peak demand is {forecast.total_required_airflow_m3_s:.3f} m³/s vs installed max capacity 0.480 m³/s. Estimated payback period: 1.8 years via energy efficiency & prevented fan breakdown.",
                confidence=0.96,
                parameters={"recommended_capacity_m3_s": 0.75, "estimated_cost_sgd": 12500, "estimated_payback_years": 1.8},
                severity="critical" if forecast.total_required_airflow_m3_s > 0.48 * 1.25 else "high",
            )
        )

    return recommendations
