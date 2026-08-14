"""Guided Smart Lab Intelligent Ecosystem dashboard.

The dashboard is deliberately organised by task. Operators can run a safe
simulation scenario, assessors can inspect the predictive evidence, executives
can review the illustrative strategy case, and both rooms remain available in a
dedicated simultaneous 3D comparison workspace.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import plotly.graph_objects as go
import streamlit as st

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The parent is added only for Streamlit's documented script entry point.
from dashboard.presentation import (
    RISK_THRESHOLDS,
    allocation_explanation,
    comfort_status,
    data_freshness,
    illustrative_roi,
    maintenance_recommendation,
)

BROKER_HOST = os.getenv("ECOHVAC_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("ECOHVAC_BROKER_PORT", "1883"))
ROOM3D_BASE_URL = os.getenv("ECOHVAC_3D_URL", "http://localhost:8000").rstrip("/")
ROOM_IDS = ("room1", "room2")
ROOM_LABELS = {"room1": "Room 1", "room2": "Room 2"}
ROOM_COLORS = {"room1": "#2a78d6", "room2": "#eb6834"}
AHU_BASE = "twin/ahu"
ECOSYSTEM_BASE = "twin/ecosystem"
ESTIMATED_TARIFF_SGD_PER_KWH = 0.30
MODEL_ARTIFACT_PATH = Path(__file__).resolve().parents[1] / "simulator" / "models" / "fan_risk_logistic.json"
MODEL_METRICS_PATH = MODEL_ARTIFACT_PATH.with_suffix(".metrics.json")


@st.cache_data
def load_model_evidence() -> tuple[dict, dict]:
    """Load checked-in, reproducible synthetic-model evidence for display only."""
    try:
        artifact = json.loads(MODEL_ARTIFACT_PATH.read_text(encoding="utf-8"))
        metrics = json.loads(MODEL_METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    return artifact, metrics


@st.cache_resource
def get_mqtt():
    """Create one MQTT client and a lock-protected multi-twin telemetry store."""
    store = {
        "rooms": {
            room_id: {
                "temperature": deque(maxlen=180),
                "humidity": deque(maxlen=120),
                "occupancy": deque(maxlen=180),
                "hvac": {},
                "detail": {},
                "allocation": {},
                "energy": {},
                "status": "unknown",
            }
            for room_id in ROOM_IDS
        },
        "ahu": {"state": {}, "energy": {}, "fan_health": {}, "decision": {}},
        "ecosystem_status": "unknown",
        "command_result": {},
        "scenario": {},
        "risk_history": deque(maxlen=180),
        "lock": threading.Lock(),
    }

    def on_connect(client, userdata, flags, reason_code, properties):
        subscriptions = []
        for room_id in ROOM_IDS:
            base = f"twin/{room_id}"
            subscriptions.extend(
                [
                    (f"{base}/temperature", 0),
                    (f"{base}/humidity", 0),
                    (f"{base}/occupancy", 0),
                    (f"{base}/hvac/state", 0),
                    (f"{base}/ac/detail", 0),
                    (f"{base}/hvac/allocation", 0),
                    (f"{base}/energy", 0),
                    (f"{base}/status", 0),
                ]
            )
        subscriptions.extend(
            [
                (f"{ECOSYSTEM_BASE}/status", 0),
                (f"{ECOSYSTEM_BASE}/command/result", 0),
                (f"{ECOSYSTEM_BASE}/scenario/state", 0),
                (f"{AHU_BASE}/state", 0),
                (f"{AHU_BASE}/energy", 0),
                (f"{AHU_BASE}/fan/health", 0),
                (f"{AHU_BASE}/coordinator/decision", 0),
            ]
        )
        client.subscribe(subscriptions)

    def decode_payload(payload):
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def on_message(client, userdata, msg):
        topic = msg.topic
        with store["lock"]:
            if topic == f"{ECOSYSTEM_BASE}/status":
                store["ecosystem_status"] = msg.payload.decode(errors="replace")
                return
            if topic == f"{ECOSYSTEM_BASE}/command/result":
                data = decode_payload(msg.payload)
                if data is not None:
                    store["command_result"] = data
                return
            if topic == f"{ECOSYSTEM_BASE}/scenario/state":
                data = decode_payload(msg.payload)
                if data is not None:
                    store["scenario"] = data
                return
            parts = topic.split("/")
            if len(parts) >= 3 and parts[0] == "twin" and parts[1] in ROOM_IDS:
                room_id = parts[1]
                room = store["rooms"][room_id]
                if parts[2] == "status":
                    room["status"] = msg.payload.decode(errors="replace")
                    return
                data = decode_payload(msg.payload)
                if data is None:
                    return
                if parts[2] in ("temperature", "humidity", "occupancy"):
                    timestamp = data.get("timestamp")
                    value = data.get("value")
                    if timestamp is None or not isinstance(value, (int, float)):
                        return
                    try:
                        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        return
                    room[parts[2]].append((ts, float(value)))
                elif parts[2] == "hvac" and len(parts) == 4:
                    if parts[3] == "state":
                        room["hvac"] = data
                    elif parts[3] == "allocation":
                        room["allocation"] = data
                elif parts[2] == "ac" and len(parts) == 4 and parts[3] == "detail":
                    room["detail"] = data
                elif parts[2] == "energy":
                    room["energy"] = data
                return
            if topic.startswith(f"{AHU_BASE}/"):
                data = decode_payload(msg.payload)
                if data is None:
                    return
                key = {
                    f"{AHU_BASE}/state": "state",
                    f"{AHU_BASE}/energy": "energy",
                    f"{AHU_BASE}/fan/health": "fan_health",
                    f"{AHU_BASE}/coordinator/decision": "decision",
                }.get(topic)
                if key:
                    store["ahu"][key] = data
                    if key == "fan_health":
                        timestamp = data.get("timestamp")
                        risk = data.get("failure_risk")
                        if isinstance(timestamp, str) and isinstance(risk, (int, float)):
                            try:
                                store["risk_history"].append(
                                    (datetime.fromisoformat(timestamp.replace("Z", "+00:00")), float(risk))
                                )
                            except ValueError:
                                pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()
    return client, store


def latest(room: dict, sensor: str):
    points = room[sensor]
    return points[-1][1] if points else None


def number(value, decimals: int = 1, suffix: str = "—") -> str:
    return f"{float(value):.{decimals}f}" if isinstance(value, (int, float)) else suffix


def human_reason(reasons: list[str] | tuple[str, ...]) -> str:
    labels = {
        "occupied": "Occupied room",
        "unoccupied_lower_priority": "Unoccupied / lower priority",
        "above_setpoint": "Above target",
        "at_or_below_setpoint": "At or below target",
        "full_request_granted": "Full request granted",
        "capacity_limited": "Shared capacity limited",
        "higher_comfort_priority_applied": "Comfort priority applied",
        "zone_disabled": "Zone disabled",
        "no_airflow_requested": "No airflow requested",
    }
    return " · ".join(labels.get(reason, reason.replace("_", " ")) for reason in reasons)


def command_payload(**values) -> str:
    """Attach a correlation ID so the simulator's demo trace can confirm a command."""
    return json.dumps({**values, "command_id": uuid.uuid4().hex, "source": "dashboard"})


def room_snapshot_copy(room: dict) -> dict:
    return {
        **{
            key: list(value) if isinstance(value, deque) else value.copy() if isinstance(value, dict) else value
            for key, value in room.items()
        }
    }


def snapshot_store(store: dict) -> tuple[dict, dict, str, dict, dict, list]:
    with store["lock"]:
        rooms = {room_id: room_snapshot_copy(room) for room_id, room in store["rooms"].items()}
        ahu = {key: value.copy() for key, value in store["ahu"].items()}
        return (
            rooms,
            ahu,
            store["ecosystem_status"],
            store["command_result"].copy(),
            store["scenario"].copy(),
            list(store["risk_history"]),
        )


def room_airflow(room: dict) -> tuple[float, float, float]:
    hvac = room["hvac"]
    allocation = room["allocation"]
    requested = float(allocation.get("requested_airflow_m3_s", hvac.get("requested_airflow_m3_s", 0.0)))
    granted = float(allocation.get("granted_airflow_m3_s", hvac.get("delivered_airflow_m3_s", 0.0)))
    ratio = granted / requested if requested > 1e-9 else 1.0
    return requested, granted, ratio


def publish_room_policy(client, room_id: str, *, setpoint: float, mode: str, occupancy: int, timescale: int) -> None:
    """Send validated individual commands through the established MQTT contract."""
    client.publish(f"twin/{room_id}/cmd/mode", command_payload(mode=mode))
    client.publish(f"twin/{room_id}/cmd/setpoint", command_payload(value=setpoint))
    client.publish(f"twin/{room_id}/cmd/occupancy", command_payload(value=occupancy))
    client.publish(f"twin/{room_id}/cmd/timescale", command_payload(value=timescale))


def sync_room_control_state(room_id: str, room: dict) -> None:
    """Seed room-scoped controls from confirmed telemetry when selection changes."""
    key_prefix = f"control_{room_id}"
    hvac, detail = room["hvac"], room["detail"]
    st.session_state[f"{key_prefix}_setpoint"] = float(hvac.get("setpoint", 24.0))
    st.session_state[f"{key_prefix}_mode"] = detail.get("mode", "auto")
    st.session_state[f"{key_prefix}_occupancy"] = int(latest(room, "occupancy") or 0)
    st.session_state[f"{key_prefix}_timescale"] = int(hvac.get("time_scale", 1) or 1)


def render_status_strip(rooms: dict, ahu: dict, status: str) -> None:
    fan_health = ahu["fan_health"]
    decision = ahu["decision"]
    constrained = bool(decision.get("constrained"))
    risk_band = str(fan_health.get("risk_band", "unknown")).upper()
    temperatures = []
    for room_id in ROOM_IDS:
        room = rooms[room_id]
        requested, granted, ratio = room_airflow(room)
        label, _ = comfort_status(latest(room, "temperature"), room["hvac"].get("setpoint"), ratio)
        temperatures.append(f"{ROOM_LABELS[room_id]}: {label}")
    columns = st.columns([0.9, 1.4, 1.2, 1.2])
    columns[0].metric("Simulator", status.upper())
    columns[1].metric("Shared capacity", "CONSTRAINED" if constrained else "AVAILABLE")
    columns[2].metric("Fan risk", f"{float(fan_health.get('failure_risk', 0.0)):.0%}", risk_band)
    columns[3].metric("Rooms", " · ".join(temperatures))


def render_room_cards(rooms: dict) -> None:
    room_columns = st.columns(2)
    for column, room_id in zip(room_columns, ROOM_IDS):
        room = rooms[room_id]
        hvac, allocation = room["hvac"], room["allocation"]
        temp, occ = latest(room, "temperature"), latest(room, "occupancy")
        requested, granted, ratio = room_airflow(room)
        state_label, detail = comfort_status(temp, hvac.get("setpoint"), ratio)
        with column.container(border=True):
            st.markdown(f"### {ROOM_LABELS[room_id]} · {state_label}")
            a, b, c = st.columns(3)
            a.metric("Temperature", f"{number(temp)} °C")
            b.metric("Occupancy", f"{int(occ)} people" if occ is not None else "—")
            c.metric("Target", f"{number(hvac.get('setpoint'))} °C")
            d, e, f = st.columns(3)
            d.metric("Cooling", "ON" if hvac.get("hvac_on") else "OFF")
            e.metric("Requested", f"{requested:.3f} m³/s")
            f.metric("Granted", f"{granted:.3f} m³/s")
            st.progress(min(1.0, max(0.0, ratio)), text=f"Shared airflow delivered: {ratio:.0%}")
            st.caption(detail)


def render_guided_scenarios(client, scenario: dict, command_result: dict) -> None:
    with st.container(border=True):
        st.markdown("### Guided simulation scenarios")
        st.caption(
            "Run the complete two-room story without a terminal. These presets change simulated state only; "
            "they are not building-control commands."
        )
        left, middle, right = st.columns([1, 1.5, 1.2])
        with left:
            if st.button("Restore safe baseline", key="scenario_baseline", use_container_width=True):
                client.publish(f"{ECOSYSTEM_BASE}/cmd/scenario", command_payload(command="baseline"))
                st.session_state["scenario_pending"] = "baseline"
        with middle:
            if st.button("Run shared-capacity stress test", key="scenario_stress", use_container_width=True):
                client.publish(f"{ECOSYSTEM_BASE}/cmd/scenario", command_payload(command="shared_capacity_stress"))
                st.session_state["scenario_pending"] = "shared_capacity_stress"
        with right:
            if scenario:
                st.metric("Active scenario", str(scenario.get("name", "custom")).replace("_", " ").title())
            else:
                st.metric("Active scenario", "Custom / waiting")
        st.info(
            "Stress-test path: competing occupancy and cooling demand → degraded shared airflow → explainable allocation → "
            "fan condition, energy, and simulated maintenance risk."
        )
        if command_result:
            result = "accepted" if command_result.get("accepted") else "rejected"
            st.caption(
                f"Latest simulator command: **{result}** · {command_result.get('reason', 'waiting for detail')} "
                f"· {command_result.get('timestamp', 'no timestamp')}"
            )


def render_room_controls(client, rooms: dict) -> None:
    with st.container(border=True):
        st.markdown("### Advanced room controls")
        st.caption("Use these only when you want to alter an individual room rather than run a guided scenario.")
        if "selected_room" not in st.session_state:
            st.session_state.selected_room = "room1"
        selected_room = st.selectbox(
            "Room to configure",
            ROOM_IDS,
            format_func=lambda room_id: ROOM_LABELS[room_id],
            key="selected_room",
        )
        room = rooms[selected_room]
        prefix = f"control_{selected_room}"
        if f"{prefix}_setpoint" not in st.session_state:
            sync_room_control_state(selected_room, room)
        current_mode = str(room["detail"].get("mode", "auto"))
        confirmed_manual = current_mode == "manual"
        controls, actions = st.columns([2.2, 1])
        with controls:
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                setpoint = st.slider(
                    "Target (°C)", 18.0, 30.0, 24.0, 0.5, key=f"{prefix}_setpoint"
                )
            with p2:
                mode = st.selectbox("Control mode", ("auto", "manual"), key=f"{prefix}_mode")
            with p3:
                occupancy = st.slider("Occupancy", 0, 30, 0, 1, key=f"{prefix}_occupancy")
            with p4:
                timescale = st.select_slider("Simulation speed", options=(1, 2, 5, 10), key=f"{prefix}_timescale")
        with actions:
            if st.button("Apply room settings", key=f"apply_{selected_room}", use_container_width=True):
                publish_room_policy(
                    client,
                    selected_room,
                    setpoint=setpoint,
                    mode=mode,
                    occupancy=occupancy,
                    timescale=timescale,
                )
                st.session_state["room_command_pending"] = selected_room
            if not confirmed_manual:
                st.caption("Manual cooling is disabled until the simulator confirms Manual mode.")
            elif st.button("Toggle manual cooling", key=f"manual_{selected_room}", use_container_width=True):
                now_on = bool(room["hvac"].get("hvac_on", False))
                client.publish(
                    f"twin/{selected_room}/cmd/hvac",
                    command_payload(command="off" if now_on else "on"),
                )
        st.caption(
            f"Confirmed simulator state: **{current_mode.title()}**. Manual cooling changes only this room's request; "
            "the shared-AHU coordinator still enforces finite capacity and its safety policy."
        )


def render_ahu_controls(client, ahu: dict) -> None:
    with st.expander("Advanced shared-AHU condition controls", expanded=False):
        st.caption("Use separate actions so changing one degradation mechanism never silently changes the other.")
        state, fan = ahu["state"], ahu["fan_health"]
        left, right = st.columns(2)
        with left:
            clog = st.slider(
                "Filter clog (%)",
                0,
                95,
                int(float(state.get("filter_clog_pct", 0.05)) * 100),
                5,
                key="filter_clog_pct",
            )
            if st.button("Apply filter condition", key="apply_filter", use_container_width=True):
                client.publish(f"{AHU_BASE}/cmd/filter_clog", command_payload(value=clog / 100))
        with right:
            wear = st.slider(
                "Fan wear (%)",
                0,
                100,
                int(float(fan.get("wear_pct", 0.03)) * 100),
                5,
                key="fan_wear_pct",
            )
            if st.button("Apply fan condition", key="apply_wear", use_container_width=True):
                client.publish(f"{AHU_BASE}/cmd/fan_wear", command_payload(value=wear / 100))


def render_operate_workspace(client, rooms: dict, ahu: dict, status: str, command_result: dict, scenario: dict) -> None:
    render_status_strip(rooms, ahu, status)
    st.divider()
    render_guided_scenarios(client, scenario, command_result)
    st.subheader("Live room comfort and shared capacity")
    render_room_cards(rooms)
    decision = ahu["decision"]
    st.info(allocation_explanation(decision, ROOM_LABELS))
    trend_col, control_col = st.columns([1.25, 1])
    with trend_col.container(border=True):
        st.markdown("### Both-room temperature trend")
        fig = go.Figure()
        for room_id in ROOM_IDS:
            points = rooms[room_id]["temperature"]
            if not points:
                continue
            xs, ys = zip(*points)
            fig.add_trace(
                go.Scatter(
                    x=list(xs),
                    y=list(ys),
                    mode="lines",
                    name=ROOM_LABELS[room_id],
                    line=dict(color=ROOM_COLORS[room_id], width=2),
                    hovertemplate=f"{ROOM_LABELS[room_id]}<br>%{{x}}<br>%{{y:.2f}} °C<extra></extra>",
                )
            )
        if fig.data:
            fig.update_layout(
                height=315,
                margin=dict(l=10, r=10, t=20, b=10),
                yaxis_title="Temperature (°C)",
                xaxis_title="Time",
                hovermode="x unified",
                showlegend=True,
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(gridcolor="#e2e8f0")
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
        else:
            st.info("Waiting for room telemetry…")
    with control_col:
        render_room_controls(client, rooms)
        render_ahu_controls(client, ahu)


def render_predictive_workspace(ahu: dict, risk_history: list, command_result: dict) -> None:
    fan, state = ahu["fan_health"], ahu["state"]
    artifact, metrics = load_model_evidence()
    risk = float(fan.get("failure_risk", 0.0))
    band = str(fan.get("risk_band", "unknown"))
    recommendation = maintenance_recommendation(band, fan.get("top_drivers", []))
    freshness_label, freshness_text = data_freshness(fan.get("timestamp"))

    st.subheader("Predictive intelligence — simulated fan failure within 7 days")
    st.caption(
        "This is an interpretable synthetic-data pilot model. It is not a real-facility maintenance probability or an autonomous work-order system."
    )
    left, middle, right = st.columns([1.1, 1.1, 1.25])
    with left.container(border=True):
        st.markdown(f"### {recommendation.title}")
        st.metric("Current simulated risk", f"{risk:.1%}", band.upper())
        st.write(recommendation.action)
        st.caption(recommendation.rationale)
        st.caption(f"Telemetry: **{freshness_label}** — {freshness_text}")
    with middle.container(border=True):
        st.markdown("### Inputs behind this prediction")
        telemetry = fan.get("telemetry", {})
        st.metric("Filter clog", f"{float(telemetry.get('filter_clog_pct', state.get('filter_clog_pct', 0.0))):.0%}")
        st.metric("Fan speed", f"{float(telemetry.get('fan_speed_pct', state.get('fan_speed_pct', 0.0))):.0%}")
        st.metric("Vibration", f"{number(telemetry.get('vibration_mm_s'), 2)} mm/s")
        st.metric("Bearing temperature", f"{number(telemetry.get('bearing_temp_c'), 1)} °C")
        st.metric("Runtime", f"{number(telemetry.get('run_hours'), 1)} h")
    with right.container(border=True):
        st.markdown("### Explainable threshold policy")
        st.write(
            f"- Low: below {RISK_THRESHOLDS['medium']:.0%}\n"
            f"- Medium: {RISK_THRESHOLDS['medium']:.0%}–{RISK_THRESHOLDS['high']:.0%}\n"
            f"- High: {RISK_THRESHOLDS['high']:.0%} or higher"
        )
        drivers = fan.get("top_drivers", [])
        if drivers:
            st.markdown("**Top model contributors**")
            for driver in drivers:
                feature = str(driver.get("feature", "")).replace("_", " ")
                contribution = float(driver.get("contribution", 0.0))
                direction = "raises" if contribution >= 0 else "reduces"
                st.caption(f"{feature.title()} {direction} model risk ({contribution:+.2f} log-odds).")
        st.caption(f"Model: {fan.get('model_version', artifact.get('model_version', '—'))}")

    if risk_history:
        with st.container(border=True):
            st.markdown("### Risk trajectory")
            xs, ys = zip(*risk_history)
            fig = go.Figure(
                go.Scatter(
                    x=list(xs),
                    y=list(ys),
                    mode="lines+markers",
                    name="Simulated risk",
                    line=dict(color="#be123c", width=2),
                    hovertemplate="%{x}<br>%{y:.1%}<extra></extra>",
                )
            )
            fig.add_hline(y=RISK_THRESHOLDS["medium"], line_dash="dot", line_color="#ca8a04", annotation_text="medium")
            fig.add_hline(y=RISK_THRESHOLDS["high"], line_dash="dot", line_color="#be123c", annotation_text="high")
            fig.update_layout(height=290, margin=dict(l=10, r=10, t=15, b=10), yaxis_tickformat=".0%", hovermode="x unified")
            fig.update_yaxes(range=[0, 1], gridcolor="#e2e8f0")
            fig.update_xaxes(showgrid=False)
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})

    evidence_col, action_col = st.columns([1.3, 1])
    with evidence_col.container(border=True):
        st.markdown("### Model evidence and boundary")
        if artifact and metrics:
            a, b, c, d = st.columns(4)
            a.metric("Training episodes", str(artifact.get("training_rows", "—")))
            b.metric("Holdout episodes", str(artifact.get("holdout_rows", "—")))
            c.metric("Synthetic precision", f"{float(metrics.get('precision', 0.0)):.1%}")
            d.metric("Synthetic recall", f"{float(metrics.get('recall', 0.0)):.1%}")
            st.caption(
                f"Held-out synthetic accuracy: {float(metrics.get('accuracy', 0.0)):.1%}; "
                f"false negatives: {int(metrics.get('false_negative', 0))}. Seed: {artifact.get('generator_seed', '—')}."
            )
        st.warning(
            "Synthetic simulation evidence only. Production use requires sensor-quality checks, calibration, drift monitoring, "
            "missing-data handling, cyber-security review, and facilities safety approval."
        )
    with action_col.container(border=True):
        st.markdown("### Simulated recommendation trace")
        st.caption("Record an operator response for the classroom demo; this is not a real work-order system.")
        action = st.selectbox("Operator response", ("Acknowledge", "Defer for review"), key="recommendation_action")
        if st.button("Record response", key="record_recommendation", use_container_width=True):
            st.session_state["recommendation_trace"] = {
                "action": action,
                "risk_band": band,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        trace = st.session_state.get("recommendation_trace")
        if trace:
            st.success(f"{trace['action']} recorded locally at {trace['timestamp']} for {trace['risk_band'].upper()} simulated risk.")
        if command_result:
            st.caption(f"Latest simulator command trace: {command_result.get('reason', '—')}")


def render_strategy_workspace(ahu: dict, command_result: dict) -> None:
    st.subheader("Strategy, governance, and scale readiness")
    st.caption(
        "The system is a simulated-pilot Digital Twin. The business case below is an assumption sandbox, not a savings claim from this demo."
    )
    roi_col, governance_col = st.columns([1.35, 1])
    with roi_col.container(border=True):
        st.markdown("### Illustrative ROI sandbox")
        c1, c2, c3 = st.columns(3)
        with c1:
            annual_energy_kwh = st.number_input("Annual HVAC baseline (kWh)", min_value=0.0, value=45000.0, step=1000.0)
            tariff = st.number_input("Electricity tariff (S$/kWh)", min_value=0.0, value=0.30, step=0.01, format="%.2f")
        with c2:
            reduction_pct = st.slider("Illustrative energy reduction", 0, 30, 8, 1) / 100
            avoided_incident = st.number_input("Illustrative avoided incident value (S$/year)", min_value=0.0, value=12000.0, step=500.0)
        with c3:
            implementation_cost = st.number_input("Implementation cost (S$)", min_value=0.0, value=25000.0, step=500.0)
            support_cost = st.number_input("Annual support cost (S$)", min_value=0.0, value=4000.0, step=500.0)
        result = illustrative_roi(
            annual_energy_kwh=annual_energy_kwh,
            tariff_sgd_per_kwh=tariff,
            energy_reduction_pct=reduction_pct,
            avoided_incident_value_sgd=avoided_incident,
            annual_support_cost_sgd=support_cost,
            implementation_cost_sgd=implementation_cost,
        )
        a, b, c, d = st.columns(4)
        a.metric("Baseline energy cost", f"S${result['baseline_energy_cost_sgd']:,.0f}")
        b.metric("Illustrative energy saving", f"S${result['energy_savings_sgd']:,.0f}")
        c.metric("Annual net benefit", f"S${result['annual_net_benefit_sgd']:,.0f}")
        d.metric("Payback", f"{result['payback_months']:.1f} months" if result["payback_months"] else "Not positive")
        st.caption(
            f"First-year ROI: {result['roi_pct']:.1f}%. Formula: (annual net benefit − implementation cost) / implementation cost. "
            "Replace all inputs with measured facility baselines, incident costs, and confidence ranges before a business decision."
        )
        simulated_cost = ahu["energy"].get("estimated_cost_sgd")
        if isinstance(simulated_cost, (int, float)):
            st.caption(f"Current run's simulated energy cost: S${float(simulated_cost):.4f}; this is separate from the annual ROI assumptions.")
    with governance_col.container(border=True):
        st.markdown("### Trust and control boundary")
        st.write(
            "- **Current mode:** simulation and non-automated recommendations\n"
            "- **Control scope:** room-local manual request; it cannot bypass shared capacity or safety policy\n"
            "- **Privacy:** aggregate occupancy only—no identities, video, or biometric data\n"
            "- **Broker today:** local classroom MQTT/WSS with anonymous plaintext access; not production-ready\n"
            "- **Production target:** TLS/WSS, device credentials, ACLs, segmentation, schema validation, acknowledged commands, immutable audit trails, monitoring, and human approval for high-impact changes"
        )
        if command_result:
            st.caption(
                f"Latest demo trace: {command_result.get('target', '—')} · "
                f"{'accepted' if command_result.get('accepted') else 'rejected'} · {command_result.get('timestamp', '—')}"
            )

    st.markdown("### Staged deployment roadmap")
    stages = [
        ("1. Simulated pilot", "Current prototype", "Tests pass; causal decisions are explainable", "Teaching/demo owner", "Return to safe baseline"),
        ("2. Digital shadow", "Read-only real telemetry", "Sensor quality, data governance, model calibration accepted", "Facilities + data owner", "Stop ingestion / revert to monitoring"),
        ("3. Human-in-the-loop", "Recommendations and work-order drafts", "Operators validate alert usefulness and response workflow", "Facilities operator", "Defer recommendation"),
        ("4. Constrained automation", "Bounded setpoint/airflow recommendations", "Safety, cybersecurity, override, and rollback audited", "Safety + cyber owner", "Manual override / rollback"),
        ("5. Federated scale", "Multiple AHUs/buildings", "Local resilience and cross-site governance proven", "Platform owner", "Isolate site gateway"),
    ]
    for stage, scope, gate, owner, rollback in stages:
        with st.expander(stage, expanded=stage.startswith("1.")):
            st.markdown(f"**Scope:** {scope}\n\n**Advance gate:** {gate}\n\n**Owner category:** {owner}\n\n**Rollback/safety response:** {rollback}")


def render_3d_workspace() -> None:
    st.subheader("3D room comparison")
    st.caption(
        "Both room twins are visible simultaneously for visual comparison. These are read-only views using the same retained MQTT topic contract; "
        "use Operate & demo for commands."
    )
    columns = st.columns(2)
    for column, room_id in zip(columns, ROOM_IDS):
        with column.container(border=True):
            st.markdown(f"### {ROOM_LABELS[room_id]}")
            st.iframe(f"{ROOM3D_BASE_URL}/room3d.html?room={room_id}", height=420)


st.set_page_config(page_title="EcoHVAC Guardian", layout="wide")
st.markdown(
    """
    <style>
        .block-container { padding-top: 1.25rem; padding-bottom: 1.5rem; }
        [data-testid="stMetricValue"] { font-size: 1.4rem; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("EcoHVAC Guardian")
st.caption(
    "A two-room intelligent Digital Twin ecosystem: transparent shared-AHU coordination, simulated fan-risk prediction, "
    "and a governed path from classroom pilot to safe facility deployment."
)

client, store = get_mqtt()
if "selected_room" not in st.session_state:
    st.session_state.selected_room = "room1"

workspace = st.radio(
    "Workspace",
    ("Operate & demo", "Predictive intelligence", "Strategy & governance", "3D room comparison"),
    horizontal=True,
    label_visibility="collapsed",
    key="workspace",
)


@st.fragment(run_every=1.0)
def live_workspace():
    rooms, ahu, status, command_result, scenario, risk_history = snapshot_store(store)
    if status == "offline":
        st.error("Ecosystem simulator is offline — displaying the last retained values.")
    elif status != "online":
        st.info("Waiting for retained ecosystem telemetry from the simulator…")
    if workspace == "Operate & demo":
        render_operate_workspace(client, rooms, ahu, status, command_result, scenario)
    elif workspace == "Predictive intelligence":
        render_predictive_workspace(ahu, risk_history, command_result)
    elif workspace == "Strategy & governance":
        render_strategy_workspace(ahu, command_result)
    else:
        render_3d_workspace()


live_workspace()
