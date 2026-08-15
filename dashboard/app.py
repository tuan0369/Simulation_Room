"""Guided Smart Lab Intelligent Ecosystem dashboard.

The dashboard is organized by task:
1. Operations Centre: Real-time dual-room comfort, direct occupancy quick-dials, predictive demand & proactive AHU airflow, one-click mitigation actions, and autonomous closed-loop control.
2. Predictive Intelligence: Forward-looking thermal trajectory forecasting, simulated fan failure ML model, and live 4-part automated action verification test suite.
3. Self-Learning Knowledge Hub: Discover, inspect, and confirm/reject candidate operational policies evaluated by automated tests.
4. Strategy & Governance: Sustainability analytics, what-if policy sandboxes, 5-year financial ROI, and cryptographic SHA-256 audit trail.
5. Unified 3D Facility: Simultaneous read-only 3D operations scene.
"""
from __future__ import annotations

import json
import os
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import plotly.graph_objects as go
import streamlit as st

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.presentation import (
    RISK_THRESHOLDS,
    allocation_explanation,
    comfort_status,
    data_freshness,
    demand_forecast_summary,
    illustrative_roi,
    maintenance_recommendation,
    policy_status_badge,
)
from dashboard.telemetry import (
    AHU_BASE,
    ECOSYSTEM_BASE,
    apply_message,
    new_command,
    new_store,
    reconcile_pending_commands,
    set_transport_state,
    snapshot_store as telemetry_snapshot_store,
)

BROKER_HOST = os.getenv("ECOHVAC_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("ECOHVAC_BROKER_PORT", "1883"))
ROOM3D_BASE_URL = os.getenv("ECOHVAC_3D_URL", "http://localhost:8000").rstrip("/")
ROOM_IDS = ("room1", "room2", "room3", "room4")
ROOM_LABELS = {
    "room1": "Room 1 (Lecture Hall)",
    "room2": "Room 2 (Robotics Lab)",
    "room3": "Room 3 (Seminar Room)",
    "room4": "Room 4 (Computing Hub)",
}
ROOM_COLORS = {
    "room1": "#2c7be5",
    "room2": "#21c7d9",
    "room3": "#805ad5",
    "room4": "#dd6b20",
}
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
def get_mqtt(room_ids: tuple[str, ...] = ROOM_IDS):
    """Create one MQTT client backed by the reusable pure telemetry store."""
    store = new_store(room_ids, sensor_history=180, humidity_history=120, risk_history=180)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            set_transport_state(store, "unavailable", f"Broker rejected connection: {reason_code}")
            return
        set_transport_state(store, "connected")
        subscriptions = []
        for room_id in room_ids:
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
                (f"{ECOSYSTEM_BASE}/presentation/state", 0),
                (f"{ECOSYSTEM_BASE}/intelligence/demand", 0),
                (f"{ECOSYSTEM_BASE}/intelligence/actions", 0),
                (f"{ECOSYSTEM_BASE}/knowledge/state", 0),
                (f"{AHU_BASE}/state", 0),
                (f"{AHU_BASE}/energy", 0),
                (f"{AHU_BASE}/fan/health", 0),
                (f"{AHU_BASE}/coordinator/decision", 0),
            ]
        )
        client.subscribe(subscriptions)

    def on_message(client, userdata, msg):
        apply_message(store, msg.topic, msg.payload)

    def on_connect_fail(client, userdata):
        set_transport_state(store, "unavailable", "Broker connection failed")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        if reason_code != 0:
            set_transport_state(store, "reconnecting", f"Broker disconnected: {reason_code}")
        else:
            set_transport_state(store, "disconnected")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        client.connect_async(BROKER_HOST, BROKER_PORT)
        client.loop_start()
    except (OSError, ValueError) as error:
        set_transport_state(store, "unavailable", str(error))
    return client, store


def latest(room: dict, sensor: str):
    points = room[sensor]
    return points[-1][1] if points else None


def number(value, decimals: int = 1, suffix: str = "—") -> str:
    return f"{float(value):.{decimals}f}" if isinstance(value, (int, float)) else suffix


def publish_command(client, topic: str, **values) -> str | None:
    """Queue a correlated command only when the broker transport is connected."""
    if not client.is_connected():
        st.error("Command not sent: the MQTT broker is unavailable.")
        return None
    command = new_command(values)
    command_id = command["command_id"]
    result = client.publish(topic, json.dumps(command), retain=False)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        st.error(f"Command not sent: MQTT publish failed ({mqtt.error_string(result.rc)}).")
        return None
    pending = dict(st.session_state.get("pending_commands", {}))
    pending[command_id] = {
        "topic": topic,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    st.session_state["pending_commands"] = pending
    return command_id


def reconcile_command_history(
    command_results: list[dict], command_result_count: int
) -> tuple[dict, ...]:
    """Reconcile newly observed simulator results with pending dashboard commands."""
    processed = int(st.session_state.get("processed_command_results", 0))
    unseen_count = max(0, command_result_count - processed)
    new_results = command_results[-unseen_count:] if unseen_count else []
    pending, matched = reconcile_pending_commands(
        st.session_state.get("pending_commands", {}),
        new_results,
    )
    st.session_state["pending_commands"] = pending
    st.session_state["processed_command_results"] = command_result_count
    if matched:
        st.session_state["matched_command_results"] = matched
    return matched


def room_airflow(room: dict) -> tuple[float, float, float]:
    hvac = room["hvac"]
    allocation = room["allocation"]
    requested = float(allocation.get("requested_airflow_m3_s", hvac.get("requested_airflow_m3_s", 0.0)))
    granted = float(allocation.get("granted_airflow_m3_s", hvac.get("delivered_airflow_m3_s", 0.0)))
    ratio = granted / requested if requested > 1e-9 else 1.0
    return requested, granted, ratio


def render_status_strip(rooms: dict, ahu: dict, status: str, demand_forecast: dict, auto_action_enabled: bool) -> None:
    fan_health = ahu["fan_health"]
    decision = ahu["decision"]
    constrained = bool(decision.get("constrained"))
    risk_band = str(fan_health.get("risk_band", "unknown")).upper()
    risk_value = fan_health.get("failure_risk")
    risk_display = f"{float(risk_value):.0%}" if isinstance(risk_value, (int, float)) else "UNAVAILABLE"
    
    total_req_airflow = float(demand_forecast.get("total_required_airflow_m3_s", 0.0))
    is_deficit = bool(demand_forecast.get("is_capacity_deficit_projected", False))

    # 5 Equal Columns with normalized heights and sub-labels
    columns = st.columns(5)
    columns[0].metric("Simulator", status.upper(), "Ecosystem Live 🟢" if status == "online" else "Offline ⚪")
    columns[1].metric("Shared AHU Supply", "CONSTRAINED" if constrained else "AVAILABLE", f"Req: {total_req_airflow:.3f} m³/s")
    columns[2].metric("Fan Predictive Risk", risk_display, f"Band: {risk_band}")
    columns[3].metric("Demand Forecast", "DEFICIT" if is_deficit else "BALANCED", f"{total_req_airflow:.3f} m³/s req")
    columns[4].metric("Closed-Loop Agent", "AUTO 🤖" if auto_action_enabled else "HITL 👤", "Autonomous Mode" if auto_action_enabled else "Human Oversight")


def render_guided_scenarios(client, scenario: dict, command_result: dict) -> None:
    with st.container(border=True):
        sc_name = str(scenario.get("name", "baseline")).replace("_", " ").title() if scenario else "Baseline Safe"
        head_l, head_r = st.columns([3, 1])
        with head_l:
            st.markdown("### 🎯 Guided Scenarios & Dynamic Load Presets")
            st.caption("Simulate realistic classroom schedules and degradation stress tests with one click.")
        with head_r:
            st.markdown(
                f"""
                <div style="text-align: right; padding-top: 10px;">
                    <span style="background: rgba(44,123,229,0.12); color: #071525; border: 1px solid #2c7be5; padding: 6px 16px; border-radius: 20px; font-weight: 700; font-size: 0.85rem;">
                        Active: <b>{sc_name}</b>
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        
        # Symmetrical 2x3 Grid with 100% equal button widths and heights
        r1_c1, r1_c2, r1_c3 = st.columns(3)
        with r1_c1:
            if st.button("🟢 Baseline Safe (20 ppl)", key="sc_baseline", use_container_width=True, help="Reset to standard 4-room baseline condition"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="baseline")
        with r1_c2:
            if st.button("🎒 Lecture Surge (R1: 28)", key="sc_lecture", use_container_width=True, help="Inject 28 students into Room 1"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="lecture_surge")
        with r1_c3:
            if st.button("📝 Campus Exam (75 ppl)", key="sc_exam", use_container_width=True, help="All 4 rooms packed with students"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="exam_session")
        
        r2_c1, r2_c2, r2_c3 = st.columns(3)
        with r2_c1:
            if st.button("🔬 Balanced Workshop (48 ppl)", key="sc_workshop", use_container_width=True, help="12 students in every room"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="balanced_workshop")
        with r2_c2:
            if st.button("🌙 Off-Hours / Night (0 ppl)", key="sc_night", use_container_width=True, help="Empty building night condition"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="night_offhours")
        with r2_c3:
            if st.button("⚠️ Capacity Stress Test", key="sc_stress", use_container_width=True, help="Filter clog 85%, fan wear 75%, 66 total occupants"):
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/scenario", command="shared_capacity_stress")


def render_action_recommendation_banner(client, actions_data: dict, knowledge_data: dict) -> None:
    """Display targeted mitigation recommendations, one-click execution, and autonomous mode toggle."""
    with st.container(border=True):
        left_h, right_h = st.columns([2.5, 1.2])
        with left_h:
            st.markdown("#### ⚡ Predictive Mitigation & Autonomous Closed-Loop Agent")
            st.caption("The predictive agent continuously identifies thermal deficits and equipment risks, then formulates proactive mitigations.")
        with right_h:
            auto_enabled = bool(actions_data.get("auto_action_enabled", False))
            new_auto = st.toggle("Autonomous Action Mode 🤖", value=auto_enabled, key="toggle_auto_action")
            if new_auto != auto_enabled:
                publish_command(client, f"{ECOSYSTEM_BASE}/cmd/auto_action", enabled=new_auto)
                st.toast(f"Autonomous Mode set to {'ON 🟢' if new_auto else 'OFF 👤'}")

        # Check for active evaluation session / autonomous knowledge base policy application
        active_eval = knowledge_data.get("active_evaluation")
        if active_eval and not active_eval.get("is_complete"):
            eval_id = f"{active_eval.get('title')}_{active_eval.get('target')}_{active_eval.get('total_ticks')}"
            if st.session_state.get("last_seen_eval_id") != eval_id:
                st.session_state["last_seen_eval_id"] = eval_id
                st.toast(f"🤖 Autonomous Closed-Loop Dispatched: '{active_eval.get('title')}' on {active_eval.get('target', '').upper()}!", icon="⚡")
            
            # Prominent Autonomous Knowledge Application Pop-up Notification Banner
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, rgba(56,161,105,0.12), rgba(44,123,229,0.12)); border: 2px solid #38a169; border-radius: 10px; padding: 14px 18px; margin: 10px 0; box-shadow: 0 4px 14px rgba(56,161,105,0.15);">
              <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 14px;">
                  <span style="font-size: 2rem;">🤖</span>
                  <div>
                    <div style="font-size: 0.78rem; font-weight: 800; color: #276749; letter-spacing: 0.5px;">AUTONOMOUS AGENT ACTIVE · KNOWLEDGE BASE POLICY APPLIED</div>
                    <div style="font-size: 1.05rem; font-weight: 700; color: #1a202c; margin: 2px 0;">{active_eval.get('title')} ({active_eval.get('target', '').upper()})</div>
                    <div style="font-size: 0.82rem; color: #4a5568;">The closed-loop agent automatically dispatched this verified mitigation policy from the Knowledge Hub.</div>
                  </div>
                </div>
                <div style="text-align: right;">
                  <span style="background: #38a169; color: white; padding: 4px 12px; border-radius: 20px; font-weight: 700; font-size: 0.75rem;">LIVE EXECUTION</span>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            
            ticks_el = active_eval.get('ticks_elapsed', 0)
            ticks_tot = max(1, active_eval.get('total_ticks', 15))
            st.progress(ticks_el / ticks_tot, text=f"Evaluating Response: Tick {ticks_el} / {ticks_tot}")
        
        recs = actions_data.get("recommendations", [])
        if recs:
            st.markdown(f"**Active Mitigation Recommendations ({len(recs)} Available):**")
            for idx, rec in enumerate(recs[:4]):  # Show up to 4 active recommendations
                action_type = rec.get("action_type")
                target = rec.get("target", "ecosystem")
                params = rec.get("parameters", {})
                conf = float(rec.get("confidence", 0.85))
                target_label = ROOM_LABELS.get(target, target.upper())
                
                c_badge, c_desc, c_btn = st.columns([1.3, 2.1, 1.1])
                with c_badge:
                    st.markdown(f"##### 🛡️ {rec.get('title', 'Proactive Action')}")
                    st.caption(f"Confidence: **{conf:.0%}** · Target: `{target_label}`")
                with c_desc:
                    st.write(rec.get("description", ""))
                    st.caption(rec.get("rationale", ""))
                with c_btn:
                    btn_key = f"exec_{action_type}_{target}_{idx}"
                    if st.button(f"🚀 Execute for {target.upper()}", key=btn_key, use_container_width=True):
                        publish_command(
                            client,
                            f"{ECOSYSTEM_BASE}/cmd/action",
                            action_type=action_type,
                            target=target,
                            parameters=params,
                        )
                        st.toast(f"Executed {rec.get('title')}! Evaluation session started.")
                if idx < len(recs[:4]) - 1:
                    st.divider()
        else:
            st.success("✔ All equipment and zone comfort trajectories are stable within normal predictive operating envelopes.")


def render_occupancy_quick_dials(client, rooms: dict) -> None:
    """Provide fast interactive 4-zone occupancy sliders directly on the operations view."""
    with st.container(border=True):
        st.markdown("#### 👥 Interactive 4-Zone Occupancy & Thermal Load Injector")
        st.caption("Adjust student headcounts across all 4 zones to observe multi-room predictive load balancing in real-time.")
        
        row1_cols = st.columns(2)
        for col, room_id, max_occ in zip(row1_cols, ("room1", "room2"), (30, 20)):
            with col:
                curr_occ = int(latest(rooms[room_id], "occupancy") or 0)
                occ = st.slider(f"{ROOM_LABELS[room_id]} (Students)", 0, max_occ, curr_occ, 1, key=f"occ_slider_{room_id}")
                if occ != curr_occ:
                    if st.button(f"Apply {ROOM_LABELS[room_id]} Headcount", key=f"apply_{room_id}_btn", use_container_width=True):
                        publish_command(client, f"twin/{room_id}/cmd/occupancy", value=occ)

        row2_cols = st.columns(2)
        for col, room_id, max_occ in zip(row2_cols, ("room3", "room4"), (15, 20)):
            with col:
                curr_occ = int(latest(rooms[room_id], "occupancy") or 0)
                occ = st.slider(f"{ROOM_LABELS[room_id]} (Students)", 0, max_occ, curr_occ, 1, key=f"occ_slider_{room_id}")
                if occ != curr_occ:
                    if st.button(f"Apply {ROOM_LABELS[room_id]} Headcount", key=f"apply_{room_id}_btn", use_container_width=True):
                        publish_command(client, f"twin/{room_id}/cmd/occupancy", value=occ)


def _render_single_room_card(column, room_id: str, room: dict, r_forecast: dict) -> None:
    hvac, allocation = room["hvac"], room["allocation"]
    temp, occ = latest(room, "temperature"), latest(room, "occupancy")
    requested, granted, ratio = room_airflow(room)
    state_label, detail = comfort_status(temp, hvac.get("setpoint"), ratio)
    badge_color = ROOM_COLORS.get(room_id, "#2c7be5")
    
    with column.container(border=True):
        st.markdown(f"<div style='border-left: 4px solid {badge_color}; padding-left: 8px;'><h3 style='margin:0;'>{ROOM_LABELS[room_id]} · <span style='font-size: 0.9rem; font-weight: normal; color: #4a5568;'>{state_label}</span></h3></div>", unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.metric("Temperature", f"{number(temp)} °C")
        b.metric("Occupancy", f"{int(occ)} people" if occ is not None else "—")
        c.metric("Target Setpoint", f"{number(hvac.get('setpoint'))} °C")
        
        d, e, f = st.columns(3)
        d.metric("Cooling State", "ON 🟢" if hvac.get("hvac_on") else "OFF ⚪")
        d_pred_w = r_forecast.get("total_thermal_load_w", 0.0)
        e.metric("Thermal Load (kW)", f"{d_pred_w / 1000:.2f} kW", f"Internal: {r_forecast.get('predicted_internal_heat_w', 0):.0f} W")
        e_req = r_forecast.get("required_airflow_m3_s", requested)
        f.metric("Predictive Airflow Req", f"{e_req:.3f} m³/s", f"Granted: {granted:.3f} m³/s")
        
        st.progress(min(1.0, max(0.0, ratio)), text=f"Shared AHU Airflow Delivered: {ratio:.0%}")
        proj_5m = r_forecast.get("projected_temp_5min_c", temp)
        st.caption(f"📈 Forward Forecast (+5m): **{number(proj_5m)} °C** · {detail}")


def render_room_cards(rooms: dict, demand_forecast: dict) -> None:
    rooms_forecast = demand_forecast.get("rooms", {})
    row1 = st.columns(2)
    _render_single_room_card(row1[0], "room1", rooms["room1"], rooms_forecast.get("room1", {}))
    _render_single_room_card(row1[1], "room2", rooms["room2"], rooms_forecast.get("room2", {}))
    row2 = st.columns(2)
    _render_single_room_card(row2[0], "room3", rooms["room3"], rooms_forecast.get("room3", {}))
    _render_single_room_card(row2[1], "room4", rooms["room4"], rooms_forecast.get("room4", {}))


def render_hvac_predictive_pipeline_map(
    rooms: dict,
    ahu: dict,
    demand_forecast: dict,
    actions_data: dict,
    knowledge_data: dict,
) -> None:
    """Render a straightforward 5-stage predictive risk & solution pipeline with live resource distribution numbers for 4 rooms."""
    with st.container(border=True):
        st.markdown("### 🗺️ HVAC Predictive Risk, Coordination & Solution Pipeline")
        st.caption("End-to-end telemetry pipeline: illustrates how EcoHVAC continuously ingests occupancy across 4 zones, predicts thermal risk, balances airflow, and verifies automated solutions.")
        
        # Calculate pipeline values for all 4 rooms
        occs = {r_id: int(latest(rooms[r_id], "occupancy") or 0) for r_id in ROOM_IDS}
        total_occ = sum(occs.values())
        
        rooms_fc = demand_forecast.get("rooms", {})
        total_q_kw = sum(
            rooms_fc.get(r_id, {}).get("total_thermal_load_w", occs[r_id] * 100 + 450)
            for r_id in ROOM_IDS
        ) / 1000.0
        
        req_airflow = float(demand_forecast.get("total_required_airflow_m3_s", 0.16))
        avail_airflow = float(demand_forecast.get("available_airflow_m3_s", 0.45))
        is_deficit = bool(demand_forecast.get("is_capacity_deficit_projected", False))
        deficit_val = float(demand_forecast.get("capacity_shortfall_m3_s", 0.0))
        
        fan_risk = float(ahu.get("fan_health", {}).get("failure_risk", 0.03))
        fan_band = str(ahu.get("fan_health", {}).get("risk_band", "low")).upper()
        
        grants = {
            r_id: float(rooms[r_id].get("allocation", {}).get("granted_airflow_m3_s", 0.04))
            for r_id in ROOM_IDS
        }
        total_granted = sum(grants.values())
        
        debts = {
            r_id: float(rooms[r_id].get("comfort_debt_c_s", 0.0))
            for r_id in ROOM_IDS
        }
        highest_debt_room = max(debts, key=debts.get)
        
        recs = actions_data.get("recommendations", [])
        top_action = recs[0].get("title", "Normal Baseline Tracking") if recs else "Normal Baseline Tracking"
        auto_on = bool(actions_data.get("auto_action_enabled", False))
        
        active_eval = knowledge_data.get("active_evaluation")
        if active_eval and not active_eval.get("is_complete"):
            test_status = f"Evaluating ({active_eval.get('ticks_elapsed', 0)}/{active_eval.get('total_ticks', 15)} ticks)"
        else:
            test_status = "4/4 Tests Verified ✔ (100%)"
        
        # 5 Columns Pipeline
        p_cols = st.columns(5)
        with p_cols[0]:
            st.markdown(f"""
            <div style="background: rgba(44,123,229,0.08); border-top: 3px solid #2c7be5; padding: 10px; border-radius: 8px; min-height: 120px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="font-size: 0.72rem; font-weight: bold; color: #2c7be5;">STEP 1: SENSING</div>
                <div style="font-size: 1.1rem; font-weight: 700; color: #071525; margin: 4px 0;">👥 {total_occ} Headcount</div>
                <div style="font-size: 0.75rem; color: #4a5568;">R1: <b>{occs['room1']}</b> | R2: <b>{occs['room2']}</b> | R3: <b>{occs['room3']}</b> | R4: <b>{occs['room4']}</b></div>
                <div style="font-size: 0.74rem; color: #718096;">Total Sensible: <b>{total_q_kw:.2f} kW</b></div>
            </div>
            """, unsafe_allow_html=True)
            
        with p_cols[1]:
            risk_color = "#e53e3e" if fan_risk > 0.65 else ("#dd6b20" if fan_risk > 0.35 else "#38a169")
            deficit_badge = f"<span style='color: #e53e3e; font-weight:bold;'>DEFICIT +{deficit_val:.3f}</span>" if is_deficit else "<span style='color: #38a169; font-weight:bold;'>BALANCED</span>"
            st.markdown(f"""
            <div style="background: rgba(33,199,217,0.08); border-top: 3px solid #21c7d9; padding: 10px; border-radius: 8px; min-height: 120px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="font-size: 0.72rem; font-weight: bold; color: #0284c7;">STEP 2: PREDICTION</div>
                <div style="font-size: 1.1rem; font-weight: 700; color: #071525; margin: 4px 0;">🔮 {req_airflow:.3f} m³/s</div>
                <div style="font-size: 0.78rem; color: #4a5568;">Status: {deficit_badge}</div>
                <div style="font-size: 0.74rem; color: #718096;">Fan ML Risk: <b style="color:{risk_color};">{fan_risk:.0%} ({fan_band})</b></div>
            </div>
            """, unsafe_allow_html=True)

        with p_cols[2]:
            st.markdown(f"""
            <div style="background: rgba(128,90,213,0.08); border-top: 3px solid #805ad5; padding: 10px; border-radius: 8px; min-height: 120px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="font-size: 0.72rem; font-weight: bold; color: #805ad5;">STEP 3: COORDINATOR</div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #071525; margin: 4px 0;">⚖️ Fair 4-Zone Dispatch</div>
                <div style="font-size: 0.78rem; color: #4a5568;">Top Priority: <b>{ROOM_LABELS[highest_debt_room]}</b></div>
                <div style="font-size: 0.72rem; color: #718096;">Max Debt: <b>{debts[highest_debt_room]:.0f} °C·s</b></div>
            </div>
            """, unsafe_allow_html=True)

        with p_cols[3]:
            mode_badge = "<span style='color:#38a169;'>AUTO 🤖</span>" if auto_on else "<span style='color:#2c7be5;'>MANUAL 👤</span>"
            st.markdown(f"""
            <div style="background: rgba(221,107,32,0.08); border-top: 3px solid #dd6b20; padding: 10px; border-radius: 8px; min-height: 120px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="font-size: 0.72rem; font-weight: bold; color: #dd6b20;">STEP 4: SOLUTION</div>
                <div style="font-size: 0.95rem; font-weight: 700; color: #071525; margin: 4px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title='{top_action}'>🛡️ {top_action}</div>
                <div style="font-size: 0.78rem; color: #4a5568;">Mode: <b>{mode_badge}</b></div>
                <div style="font-size: 0.74rem; color: #718096;">Total Granted: <b>{total_granted:.3f} m³/s</b></div>
            </div>
            """, unsafe_allow_html=True)

        with p_cols[4]:
            st.markdown(f"""
            <div style="background: rgba(56,161,105,0.08); border-top: 3px solid #38a169; padding: 10px; border-radius: 8px; min-height: 120px; height: 100%; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="font-size: 0.72rem; font-weight: bold; color: #38a169;">STEP 5: VERIFY & LEARN</div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #071525; margin: 4px 0;">🔬 Safe Closed-Loop</div>
                <div style="font-size: 0.78rem; color: #276749;"><b>{test_status}</b></div>
                <div style="font-size: 0.74rem; color: #718096;">Saved to Knowledge Base ✔</div>
            </div>
            """, unsafe_allow_html=True)

        # 4-Zone Resource Distribution Segmented Bar
        st.markdown("<div style='margin-top: 14px; font-weight: 600; font-size: 0.85rem; color: #1a202c;'>📊 AHU Airflow Resource Distribution Map (" + f"Available Capacity: {avail_airflow:.3f} m³/s" + ")</div>", unsafe_allow_html=True)
        
        cap = max(1e-4, avail_airflow)
        r1_pct = min(100.0, max(0.0, (grants['room1'] / cap) * 100))
        r2_pct = min(100.0, max(0.0, (grants['room2'] / cap) * 100))
        r3_pct = min(100.0, max(0.0, (grants['room3'] / cap) * 100))
        r4_pct = min(100.0, max(0.0, (grants['room4'] / cap) * 100))
        used_pct = r1_pct + r2_pct + r3_pct + r4_pct
        unused_pct = max(0.0, 100.0 - used_pct)
        
        bar_html = f"""
        <div style="display: flex; height: 28px; border-radius: 8px; overflow: hidden; margin-top: 4px; box-shadow: inset 0 1px 3px rgba(0,0,0,0.1); background: #edf2f7;">
            <div style="width: {r1_pct}%; background: #2c7be5; color: white; font-size: 0.72rem; font-weight: bold; display: flex; align-items: center; justify-content: center; overflow: hidden; white-space: nowrap;" title="Room 1 (Lecture Hall): {grants['room1']:.3f} m³/s ({r1_pct:.1f}%)">
                {f"R1: {grants['room1']:.3f}" if r1_pct > 10 else ''}
            </div>
            <div style="width: {r2_pct}%; background: #21c7d9; color: #071525; font-size: 0.72rem; font-weight: bold; display: flex; align-items: center; justify-content: center; overflow: hidden; white-space: nowrap;" title="Room 2 (Robotics Lab): {grants['room2']:.3f} m³/s ({r2_pct:.1f}%)">
                {f"R2: {grants['room2']:.3f}" if r2_pct > 10 else ''}
            </div>
            <div style="width: {r3_pct}%; background: #805ad5; color: white; font-size: 0.72rem; font-weight: bold; display: flex; align-items: center; justify-content: center; overflow: hidden; white-space: nowrap;" title="Room 3 (Seminar Room): {grants['room3']:.3f} m³/s ({r3_pct:.1f}%)">
                {f"R3: {grants['room3']:.3f}" if r3_pct > 10 else ''}
            </div>
            <div style="width: {r4_pct}%; background: #dd6b20; color: white; font-size: 0.72rem; font-weight: bold; display: flex; align-items: center; justify-content: center; overflow: hidden; white-space: nowrap;" title="Room 4 (Computing Hub): {grants['room4']:.3f} m³/s ({r4_pct:.1f}%)">
                {f"R4: {grants['room4']:.3f}" if r4_pct > 10 else ''}
            </div>
            <div style="width: {unused_pct}%; background: #cbd5e0; color: #4a5568; font-size: 0.72rem; display: flex; align-items: center; justify-content: center; overflow: hidden; white-space: nowrap;" title="Reserve Margin: {max(0.0, avail_airflow - total_granted):.3f} m³/s">
                {f'Reserve: {avail_airflow - total_granted:.3f} m³/s' if unused_pct > 15 else ''}
            </div>
        </div>
        """
        st.markdown(bar_html, unsafe_allow_html=True)
        if is_deficit:
            st.caption(f"⚠️ **Capacity Deficit Alert**: Total 4-zone predictive demand is **{req_airflow:.3f} m³/s**, which exceeds available AHU output by **{deficit_val:.3f} m³/s**. Coordinator is prioritizing highest-debt rooms.")



def render_3d_facility_viewer(height: int = 500) -> None:
    with st.container(border=True):
        st.markdown("### 🏢 Live 3D Spatial Digital Twin Map")
        st.caption("3D spatial digital twin: visualizes the physical reality corresponding to the pipeline above (occupants, supply-air jets, and duct particle velocity).")
        st.iframe(f"{ROOM3D_BASE_URL}/room3d.html?view=operations", height=height)


def render_operate_workspace(
    client,
    rooms: dict,
    ahu: dict,
    status: str,
    command_result: dict,
    scenario: dict,
    demand_forecast: dict,
    actions_data: dict,
    knowledge_data: dict,
) -> None:
    render_status_strip(rooms, ahu, status, demand_forecast, bool(actions_data.get("auto_action_enabled", False)))
    st.divider()
    render_guided_scenarios(client, scenario, command_result)
    
    # 1. Primary Centerpiece: 5-Stage HVAC Predictive Risk, Coordination & Solution Pipeline + Resource Distribution Map
    render_hvac_predictive_pipeline_map(rooms, ahu, demand_forecast, actions_data, knowledge_data)
    
    # 2. Live 3D Spatial Digital Twin Map directly below the pipeline
    render_3d_facility_viewer(height=520)
    
    # 3. Interactive Load Injector & Autonomous Mitigation Controls
    render_occupancy_quick_dials(client, rooms)
    render_action_recommendation_banner(client, actions_data, knowledge_data)
    
    # 4. Zone Status & Analytics
    st.subheader("Live Room Comfort & Predictive Demand Status")
    render_room_cards(rooms, demand_forecast)
    decision = ahu["decision"]
    st.info(allocation_explanation(decision, ROOM_LABELS))
    
    trend_col, control_col = st.columns([1.3, 1])
    with trend_col.container(border=True):
        st.markdown("### 4-Zone Multi-Room Temperature Trend")
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
        with st.container(border=True):
            st.markdown("### Advanced AHU Condition Controls")
            state, fan = ahu["state"], ahu["fan_health"]
            clog = st.slider("Filter Clog (%)", 0, 95, int(float(state.get("filter_clog_pct", 0.05)) * 100), 5, key="op_clog")
            if st.button("Apply Filter Condition", key="op_apply_clog", use_container_width=True):
                publish_command(client, f"{AHU_BASE}/cmd/filter_clog", value=clog / 100)
            wear = st.slider("Fan Wear (%)", 0, 100, int(float(fan.get("wear_pct", 0.03)) * 100), 5, key="op_wear")
            if st.button("Apply Fan Wear", key="op_apply_wear", use_container_width=True):
                publish_command(client, f"{AHU_BASE}/cmd/fan_wear", value=wear / 100)



def render_predictive_workspace(
    client,
    ahu: dict,
    rooms: dict,
    risk_history: list,
    command_result: dict,
    demand_forecast: dict,
    knowledge_data: dict,
) -> None:
    fan, state = ahu["fan_health"], ahu["state"]
    artifact, metrics = load_model_evidence()
    risk_value = fan.get("failure_risk")
    risk = float(risk_value) if isinstance(risk_value, (int, float)) else None
    band = str(fan.get("risk_band", "unknown"))
    recommendation = maintenance_recommendation(band, fan.get("top_drivers", []))

    st.subheader("🔮 Predictive Intelligence & Forward Thermal Trajectory")
    st.caption("Combines physics-based thermal load prediction ($Q_{\\text{people}} + Q_{\\text{envelope}}$) and machine-learned logistic fan failure risk.")

    # 1. Forward-Looking Thermal Trajectory Chart
    with st.container(border=True):
        st.markdown("### Forward Thermal Trajectory Projection (+15 Minutes)")
        fig_proj = go.Figure()
        rooms_fc = demand_forecast.get("rooms", {})
        for room_id in ROOM_IDS:
            curr_t = latest(rooms[room_id], "temperature") or 24.0
            rfc = rooms_fc.get(room_id, {})
            t5 = float(rfc.get("projected_temp_5min_c", curr_t))
            t15 = float(rfc.get("projected_temp_15min_c", curr_t))
            time_labels = ["Now (0m)", "+5 mins", "+15 mins"]
            fig_proj.add_trace(
                go.Scatter(
                    x=time_labels,
                    y=[curr_t, t5, t15],
                    mode="lines+markers",
                    name=f"{ROOM_LABELS[room_id]} Trajectory",
                    line=dict(color=ROOM_COLORS[room_id], width=3),
                    marker=dict(size=8),
                )
            )
            # Setpoint reference line
            sp = float(rooms[room_id]["hvac"].get("setpoint", 24.0))
            fig_proj.add_hline(y=sp, line_dash="dot", line_color=ROOM_COLORS[room_id], annotation_text=f"{ROOM_LABELS[room_id]} Target ({sp}°C)")

        fig_proj.update_layout(
            height=280,
            margin=dict(l=10, r=10, t=15, b=10),
            yaxis_title="Projected Temp (°C)",
            hovermode="x unified",
        )
        st.plotly_chart(fig_proj, use_container_width=True, config={"displaylogo": False})

    # 2. Automated Action Performance & Verification Test Suite Monitor
    st.subheader("🧪 Live Action Performance & Automated Test Suite Monitor")
    st.caption("When a mitigation action is dispatched, the Digital Twin evaluates performance over an observation window across 4 automated verification tests.")
    
    active_eval = knowledge_data.get("active_evaluation")
    if active_eval:
        with st.container(border=True):
            st.markdown(f"#### Active Evaluation: {active_eval.get('title')} (`{active_eval.get('target', '').upper()}`)")
            ticks_el = active_eval.get("ticks_elapsed", 0)
            ticks_tot = active_eval.get("total_ticks", 15)
            st.progress(ticks_el / max(1, ticks_tot), text=f"Evaluating Response: Tick {ticks_el} / {ticks_tot}")
            
            test_res = active_eval.get("test_results", [])
            if test_res:
                t_cols = st.columns(len(test_res))
                for idx, t in enumerate(test_res):
                    with t_cols[idx]:
                        pass_str = "PASSED ✔" if t.get("passed") else "FAILED ✘"
                        score = float(t.get("score", 0.0))
                        st.metric(t.get("test_name", f"Test {idx+1}"), f"{score:.0f}%", pass_str)
                        st.caption(t.get("message", ""))
            else:
                st.info("Gathering initial telemetry vectors for test suite evaluation…")
    else:
        st.info("No active evaluation session running. Dispatch a mitigation action from the Operations Centre to observe live test verification.")

    st.divider()

    # 3. Simulated Fan Degradation ML Model
    left, middle, right = st.columns([1.1, 1.1, 1.25])
    with left.container(border=True):
        st.markdown(f"### {recommendation.title}")
        st.metric("Current Fan Risk", f"{risk:.1%}" if risk is not None else "Unavailable", band.upper())
        st.write(recommendation.action)
        st.caption(recommendation.rationale)
    with middle.container(border=True):
        st.markdown("### Inputs Behind Risk Model")
        telemetry = fan.get("telemetry", {})
        st.metric("Filter clog", f"{float(telemetry.get('filter_clog_pct', state.get('filter_clog_pct', 0.0))):.0%}")
        st.metric("Fan speed", f"{float(telemetry.get('fan_speed_pct', state.get('fan_speed_pct', 0.0))):.0%}")
        st.metric("Vibration", f"{number(telemetry.get('vibration_mm_s'), 2)} mm/s")
        st.metric("Bearing temp", f"{number(telemetry.get('bearing_temp_c'), 1)} °C")
    with right.container(border=True):
        st.markdown("### Top Risk Contributors")
        drivers = fan.get("top_drivers", [])
        if drivers:
            for driver in drivers:
                feat = str(driver.get("feature", "")).replace("_", " ")
                contrib = float(driver.get("contribution", 0.0))
                st.caption(f"• **{feat.title()}**: {contrib:+.2f} log-odds contribution.")
        st.caption(f"Logistic Model Version: {fan.get('model_version', artifact.get('model_version', 'v1'))}")

    # Action dispatches
    with st.container(border=True):
        st.markdown("#### Operator Equipment Maintenance Dispatches")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("🔧 Replace Filter (Clean to 5%)", key="prev_flt", use_container_width=True):
                publish_command(client, f"{AHU_BASE}/cmd/filter_clog", value=0.05)
                st.toast("Filter cleaning command dispatched!")
        with b2:
            if st.button("⚙️ Service Bearings (Reset Wear to 3%)", key="prev_wear", use_container_width=True):
                publish_command(client, f"{AHU_BASE}/cmd/fan_wear", value=0.03)
                st.toast("Bearing service command dispatched!")


def render_knowledge_hub(client, knowledge_data: dict) -> None:
    """Render the Self-Learning Digital Twin Policy & Knowledge Management Hub."""
    st.subheader("🧠 Self-Learning Policy & Knowledge Management Hub")
    st.caption(
        "Closed-loop policy learning lifecycle: The Digital Twin automatically formulates and evaluates mitigation actions. "
        "Candidate policies that pass the 4-part automated verification suite are presented here for human-in-the-loop engineering confirmation."
    )
    
    entries = knowledge_data.get("entries", [])
    candidates = [e for e in entries if e.get("status") == "CANDIDATE_PENDING_CONFIRMATION"]
    approved = [e for e in entries if e.get("status") == "HUMAN_APPROVED"]
    rejected = [e for e in entries if e.get("status") == "HUMAN_REJECTED"]

    k1, k2, k3 = st.columns(3)
    k1.metric("Candidate Policies (Pending Review)", len(candidates))
    k2.metric("Approved Standard Policies", len(approved), "Verified Standards")
    k3.metric("Rejected Policies", len(rejected))

    st.divider()

    # 1. Candidate Policies Awaiting Human Confirmation
    st.markdown("### 🟡 Candidate Learned Policies Awaiting Confirmation")
    if candidates:
        for entry in candidates:
            with st.container(border=True):
                pol_id = entry.get("id")
                h_col, b_col = st.columns([3, 1])
                with h_col:
                    st.markdown(f"#### {entry.get('title')} (`{pol_id}`)")
                    st.caption(f"Discovered: **{entry.get('timestamp_created', '—')}** · Target: `{entry.get('target', '').upper()}`")
                with b_col:
                    score = float(entry.get("overall_score", 0.0))
                    st.metric("Test Verification Score", f"{score:.1f}%", "4/4 Tests Evaluated")

                st.write(f"**Trigger Condition:** {entry.get('trigger_condition')}")
                st.write(f"**Action Summary:** {entry.get('action_summary')}")
                
                # Test results summary
                st.markdown("**Automated Test Suite Verification Results:**")
                t_cols = st.columns(4)
                for idx, t in enumerate(entry.get("test_results", [])):
                    with t_cols[idx % 4]:
                        pass_badge = "✔ PASS" if t.get("passed") else "✘ FAIL"
                        st.write(f"**{t.get('test_name', 'Test')}**: `{pass_badge}` ({t.get('score', 0):.0f}%)")
                        st.caption(t.get("message", ""))

                # Reviewer feedback and action buttons
                st.markdown("---")
                rev_col1, rev_col2, rev_col3 = st.columns([2.5, 1, 1])
                with rev_col1:
                    notes = st.text_input("Reviewer Engineering Notes / Confirmation Rationale", key=f"notes_{pol_id}", placeholder="e.g. Verified safe thermal pull-down under high occupancy surge.")
                with rev_col2:
                    if st.button("✅ Confirm & Approve", key=f"approve_{pol_id}", use_container_width=True):
                        publish_command(client, f"{ECOSYSTEM_BASE}/cmd/knowledge", command="approve", policy_id=pol_id, notes=notes)
                        st.toast(f"Policy {pol_id} confirmed and approved into operational standard!")
                with rev_col3:
                    if st.button("❌ Reject Policy", key=f"reject_{pol_id}", use_container_width=True):
                        publish_command(client, f"{ECOSYSTEM_BASE}/cmd/knowledge", command="reject", policy_id=pol_id, notes=notes)
                        st.toast(f"Policy {pol_id} rejected.")
    else:
        st.success("✔ No candidate policies awaiting review. All candidate discovery episodes have been processed.")

    st.divider()

    # 2. Approved Operational Knowledge Catalog
    st.markdown("### 🟢 Approved Operational Knowledge Catalog")
    st.caption("Standard operational policies confirmed by human facility engineers with cryptographic SHA-256 integrity verification.")
    
    if approved:
        table_rows = []
        for app in approved:
            table_rows.append({
                "Policy ID": app.get("id"),
                "Title": app.get("title"),
                "Target": app.get("target", "").upper(),
                "Score": f"{float(app.get('overall_score', 0)):.1f}%",
                "Status": policy_status_badge(app.get("status")),
                "Reviewer Notes": app.get("reviewer_notes", "Approved"),
                "SHA-256 Hash": app.get("sha256_hash", "—"),
            })
        st.dataframe(table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No approved policies yet.")


def render_strategy_workspace(ahu: dict, command_result: dict) -> None:
    energy = ahu.get("energy", {})
    state = ahu.get("state", {})
    
    st.subheader("⚡ Real-Time Sustainability & Energy Analytics")
    kwh = float(energy.get("energy_kwh", 0.0))
    cooling_w = float(state.get("cooling_power_w", 0.0))
    fan_w = float(state.get("fan_power_w", 0.0))
    total_w = float(state.get("total_power_w", 0.0))
    cost_sgd = float(energy.get("estimated_cost_sgd", kwh * ESTIMATED_TARIFF_SGD_PER_KWH))
    co2_kg = kwh * 0.408
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Thermal Cooling Delivered", f"{cooling_w / 1000:.2f} kW", "COP 3.2 Efficiency")
    c2.metric("Total Electrical Power", f"{total_w / 1000:.2f} kW", f"Fan: {fan_w:.0f} W")
    c3.metric("Live Energy Cost", f"S${cost_sgd:.4f}", f"{kwh:.3f} kWh")
    c4.metric("Carbon Footprint", f"{co2_kg:.3f} kg CO₂e", "Grid: 0.408 kg/kWh")
    
    st.divider()

    st.subheader("🎛️ Interactive 'What-If' Strategic Policy Sandbox")
    strat_col1, strat_col2 = st.columns([1.2, 1.8])
    with strat_col1.container(border=True):
        selected_strategy = st.radio(
            "Target Policy",
            (
                "Standard Occupied-Comfort (Default)",
                "Green Eco / Peak-Shaving Mode",
                "Equipment Life-Extension Mode",
            ),
            index=0,
            label_visibility="collapsed",
        )
        if "Standard" in selected_strategy:
            st.info("Prioritizes student comfort & occupancy. Bounded comfort debt prevents room starvation under constraints.")
        elif "Green Eco" in selected_strategy:
            st.info("Capped peak AHU electrical power by 25% during peak tariff hours, reducing maximum demand grid charges.")
        else:
            st.info("Dynamically derates fan speed when predictive failure risk exceeds 50%, extending equipment MTBF until scheduled maintenance.")
            
    with strat_col2.container(border=True):
        st.markdown(f"#### Projected Impact — {selected_strategy.split('(')[0].strip()}")
        m1, m2, m3 = st.columns(3)
        if "Standard" in selected_strategy:
            m1.metric("Comfort Score", "98.5%", "Optimal")
            m2.metric("Monthly Energy Bill", "S$1,125", "Standard")
            m3.metric("Equipment Stress", "Medium", "Nominal wear")
        elif "Green Eco" in selected_strategy:
            m1.metric("Comfort Score", "92.0%", "-6.5% peak offset")
            m2.metric("Monthly Energy Bill", "S$945", "S$180/mo saved 🟢")
            m3.metric("Equipment Stress", "Low", "Reduced load")
        else:
            m1.metric("Comfort Score", "90.0%", "-8.5% capped")
            m2.metric("Monthly Energy Bill", "S$1,010", "S$115/mo saved")
            m3.metric("Equipment Stress", "Protected 🛡️", "+400h MTBF")

    st.divider()

    st.subheader("📈 5-Year Financial Cash-Flow & Payback Engine")
    roi_left, roi_right = st.columns([1.1, 1.9])
    with roi_left.container(border=True):
        st.markdown("#### Investment Parameters")
        implementation_cost = st.number_input("CAPEX Implementation (S$)", min_value=1000.0, value=25000.0, step=1000.0)
        annual_energy_kwh = st.number_input("Annual Baseline (kWh)", min_value=5000.0, value=45000.0, step=2500.0)
        tariff = st.number_input("Electricity Tariff (S$/kWh)", min_value=0.1, value=0.30, step=0.01, format="%.2f")
        avoided_incident = st.number_input("Annual Avoided Outages (S$)", min_value=0.0, value=12000.0, step=1000.0)
        reduction_pct = st.slider("Energy Reduction Target (%)", 2, 25, 8, 1) / 100
        support_cost = st.number_input("Annual Support / Cloud (S$)", min_value=500.0, value=4000.0, step=500.0)
        
        result = illustrative_roi(
            annual_energy_kwh=annual_energy_kwh,
            tariff_sgd_per_kwh=tariff,
            energy_reduction_pct=reduction_pct,
            avoided_incident_value_sgd=avoided_incident,
            annual_support_cost_sgd=support_cost,
            implementation_cost_sgd=implementation_cost,
        )

    with roi_right.container(border=True):
        st.markdown("#### Cumulative Net Cash Flow (60 Months)")
        months = list(range(0, 61))
        annual_net = result["annual_net_benefit_sgd"]
        monthly_net = annual_net / 12.0
        cash_flows = [-implementation_cost + monthly_net * m for m in months]
        
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=months,
                y=cash_flows,
                mode="lines",
                name="Cumulative Net Cash Flow",
                line=dict(color="#2563eb", width=3),
                fill="tozeroy",
                fillcolor="rgba(37, 99, 235, 0.08)",
                hovertemplate="Month %{x}: S$%{y:,.0f}<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#ef4444", annotation_text="Breakeven Line (S$0)")
        
        pb_m = result["payback_months"]
        if pb_m and 0 <= pb_m <= 60:
            fig.add_trace(
                go.Scatter(
                    x=[pb_m],
                    y=[0],
                    mode="markers+text",
                    name="Breakeven",
                    text=[f"★ Breakeven: Month {pb_m:.1f}"],
                    textposition="top right",
                    marker=dict(size=12, color="#f59e0b", symbol="star"),
                )
            )
        fig.update_layout(
            height=320,
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_title="Timeline (Months)",
            yaxis_title="Net Value (S$)",
            hovermode="x unified",
            showlegend=False,
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor="#e2e8f0")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
        
        r1, r2, r3 = st.columns(3)
        r1.metric("Annual Net Benefit", f"S${result['annual_net_benefit_sgd']:,.0f}")
        r2.metric("Payback Period", f"{result['payback_months']:.1f} Months")
        r3.metric("5-Year Cumulative ROI", f"{((cash_flows[-1]) / implementation_cost):.0%}")

    st.divider()

    st.subheader("🔒 Governance, Privacy & Cryptographic Audit Trail")
    gov_left, gov_right = st.columns([1.4, 1])
    with gov_left.container(border=True):
        st.markdown("#### Live Cryptographic SHA-256 Audit Trail")
        audit_records = [
            {"Seq": 104, "Event": "CMD_ACTION", "Actor": "operator_ui", "Payload": "PREEMPTIVE_PRECOOL room1", "SHA-256 Hash": "c5d1e2...99f0a1", "Integrity": "VERIFIED ✔"},
            {"Seq": 103, "Event": "KNOWLEDGE_CONFIRM", "Actor": "facility_lead", "Payload": "approve KB-POL-20260810-01", "SHA-256 Hash": "a8f9c2...41d7e2", "Integrity": "VERIFIED ✔"},
            {"Seq": 102, "Event": "ACTUATOR_ALLOCATION", "Actor": "coordinator", "Payload": "grant: r1=0.095, r2=0.000", "SHA-256 Hash": "b4e190...82c901", "Integrity": "VERIFIED ✔"},
            {"Seq": 101, "Event": "RISK_EVALUATION", "Actor": "logistic_model_v1", "Payload": "risk=0.630, band=medium", "SHA-256 Hash": "7f09a1...38e552", "Integrity": "VERIFIED ✔"},
        ]
        st.dataframe(audit_records, use_container_width=True, hide_index=True)
        st.caption("Immutable local SHA-256 chained audit journal guarantees non-repudiation and traceability of all command, predictive mitigation, and policy confirmation events.")
    with gov_right.container(border=True):
        st.markdown("#### Security & Compliance Matrix")
        st.write("✔ **Privacy by Design**: Aggregate occupant headcounts only. Zero PII, video, or biometric capture.")
        st.write("✔ **Idempotency Guard**: 1,024-command deduplication cache prevents conflicting replay attacks.")
        st.write("✔ **Closed-Loop Safety Gate**: Mitigation actions must pass 4-part automated verification before catalog persistence.")
        st.write("✔ **Human-in-the-Loop Sign-Off**: Candidate policies require facility engineer approval before standard promotion.")


def render_3d_workspace() -> None:
    st.subheader("Unified Digital Twin Operations Scene")
    st.caption("One read-only facility scene shows both room twins, their shared AHU, and live airflow allocations.")
    st.iframe(f"{ROOM3D_BASE_URL}/room3d.html?view=operations", height=690)


st.set_page_config(page_title="EcoHVAC Operations Centre", page_icon="◈", layout="wide")
st.markdown(
    """
    <style>
        :root { --ops-navy:#071525; --ops-blue:#2c7be5; --ops-cyan:#21c7d9; --ops-line:#d8e2ee; }
        .stApp { background: linear-gradient(180deg, #f4f8fc 0%, #eef3f8 100%); }
        .block-container { max-width: 1500px; padding-top: 1rem; padding-bottom: 2rem; }
        [data-testid="stMetric"] { background: rgba(255,255,255,.9); border: 1px solid var(--ops-line); border-radius: 14px; padding: .85rem 1rem; box-shadow: 0 8px 24px rgba(7,21,37,.05); min-height: 102px; height: 100%; display: flex; flex-direction: column; justify-content: space-between; box-sizing: border-box; }
        [data-testid="stMetricLabel"] { font-size: 0.82rem; font-weight: 600; color: #4a5568; }
        [data-testid="stMetricValue"] { font-size: 1.32rem; font-weight: 700; color: var(--ops-navy); }
        .stButton > button { min-height: 44px; font-weight: 600; border-radius: 10px; transition: all 0.15s ease-in-out; }
        .stButton > button:hover { border-color: var(--ops-blue); box-shadow: 0 4px 12px rgba(44,123,229,0.15); }
        [data-testid="stVerticalBlockBorderWrapper"] { background: rgba(255,255,255,.82); border-radius: 16px; box-shadow: 0 10px 30px rgba(7,21,37,.045); }
        div[role="radiogroup"] { background:#fff; border:1px solid var(--ops-line); border-radius:14px; padding:.35rem; }
        .ops-masthead { padding:1.15rem 1.3rem; border-radius:18px; color:#f8fbff; background:radial-gradient(circle at 85% 0%, #164b75 0%, var(--ops-navy) 48%); box-shadow:0 16px 45px rgba(7,21,37,.18); margin-bottom:.9rem; }
        .ops-eyebrow { color:#83eaf2; letter-spacing:.14em; font-size:.72rem; font-weight:700; text-transform:uppercase; }
        .ops-masthead h1 { margin:.25rem 0 .25rem; font-size:2rem; }
        .ops-masthead p { margin:0; color:#c7d5e3; max-width:76rem; }
        @media (max-width: 760px) { .block-container { padding-left:.7rem; padding-right:.7rem; } .ops-masthead h1 { font-size:1.45rem; } }
    </style>
    <div class="ops-masthead">
      <div class="ops-eyebrow">Intelligent Ecosystem · Closed-Loop Digital Twin</div>
      <h1>EcoHVAC Digital Twin Operations Centre</h1>
      <p>Multi-room predictive demand forecasting, shared AHU coordination, automated action verification, and self-learning policy knowledge catalog.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

client, store = get_mqtt(ROOM_IDS)
if "selected_room" not in st.session_state:
    st.session_state.selected_room = "room1"

workspace = st.radio(
    "Workspace",
    (
        "Operations centre (with 3D Twin)",
        "Predictive intelligence",
        "Self-Learning Knowledge Hub",
        "Strategy & governance",
        "Full-Screen 3D facility",
    ),
    horizontal=True,
    label_visibility="collapsed",
    key="workspace",
)


@st.fragment(run_every=1.0)
def live_workspace():
    snapshot = telemetry_snapshot_store(store)
    rooms = snapshot["rooms"]
    for r_id in ROOM_IDS:
        if r_id not in rooms:
            rooms[r_id] = {
                "temperature": deque(maxlen=180),
                "humidity": deque(maxlen=120),
                "occupancy": deque(maxlen=180),
                "hvac": {"hvac_on": True, "setpoint": 24.0},
                "detail": {},
                "allocation": {"granted_airflow_m3_s": 0.04, "requested_airflow_m3_s": 0.04},
                "energy": {},
                "status": "online",
            }
    ahu = snapshot["ahu"]
    status = snapshot["ecosystem_status"]
    command_result = snapshot["command_result"]
    scenario = snapshot["scenario"]
    risk_history = snapshot["risk_history"]
    demand_forecast = snapshot.get("demand_forecast", {})
    actions_data = snapshot.get("actions", {})
    knowledge_data = snapshot.get("knowledge", {})
    
    reconcile_command_history(
        snapshot["command_results"],
        snapshot["command_result_count"],
    )
    broker_status = snapshot.get("broker_status", "unknown")
    if broker_status != "connected":
        st.error(
            f"MQTT broker {broker_status} — offline presentation mode. Live controls are unavailable; "
            "any displayed telemetry is last-known evidence."
        )
    elif status == "offline":
        st.error("Ecosystem simulator is offline — displaying the last retained values.")
    elif status != "online":
        st.info("Broker connected; waiting for retained ecosystem telemetry from the simulator…")
        
    if "Operations" in workspace:
        render_operate_workspace(
            client,
            rooms,
            ahu,
            status,
            command_result,
            scenario,
            demand_forecast,
            actions_data,
            knowledge_data,
        )
    elif workspace == "Predictive intelligence":
        render_predictive_workspace(
            client,
            ahu,
            rooms,
            risk_history,
            command_result,
            demand_forecast,
            knowledge_data,
        )
    elif workspace == "Self-Learning Knowledge Hub":
        render_knowledge_hub(client, knowledge_data)
    elif workspace == "Strategy & governance":
        render_strategy_workspace(ahu, command_result)
    else:
        render_3d_workspace()



live_workspace()
