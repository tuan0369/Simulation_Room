"""Dashboard Streamlit: real-time display + dynamic HVAC control with AI assistant.

Optimized layout: No sidebar, compact metrics cards, central control panel,
and side-by-side temperature chart & 3D room view.
"""
import json
import os
import threading
from collections import deque
from datetime import datetime

import numpy as np
import paho.mqtt.client as mqtt
import plotly.graph_objects as go
import streamlit as st

# In Docker the broker is the `mosquitto` service, not localhost. The localhost
# default keeps host-side runs working. Note: the st.iframe URL below and the 3D
# view's ws://localhost:9001 stay `localhost` — those resolve in the user's
# browser against published ports, not inside a container.
BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
BASE = "twin/room1"
SENSORS = ("temperature", "humidity", "occupancy")
MANUAL_ALERT_ON, MANUAL_ALERT_OFF = 30.0, 29.5  # manual: fixed 30°C overheat (hysteresis)


@st.cache_resource
def get_mqtt():
    """Single client + buffer for the entire app — survives reruns."""
    store = {
        "temperature": deque(maxlen=100),  # ~5 min @ 3s
        "humidity": deque(maxlen=60),
        "occupancy": deque(maxlen=150),
        "hvac_on": None,
        "ac_power_pct": 0.0,
        "ac_temp_output": None,
        "setpoint": 25.0,
        "mode": "off",
        "status": "unknown",
        "lock": threading.Lock(),
    }

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe([(f"{BASE}/{s}", 0) for s in SENSORS]
                         + [(f"{BASE}/hvac/state", 0),
                            (f"{BASE}/ac/detail", 0),
                            (f"{BASE}/status", 0)])

    def on_message(client, userdata, msg):
        with store["lock"]:
            if msg.topic == f"{BASE}/status":
                store["status"] = msg.payload.decode()
                return
            try:
                data = json.loads(msg.payload)
            except json.JSONDecodeError:
                return
            if msg.topic == f"{BASE}/hvac/state":
                store["hvac_on"] = data.get("hvac_on")
                store["ac_power_pct"] = data.get("ac_power_pct", 0.0)
                store["setpoint"] = data.get("setpoint", 25.0)
            elif msg.topic == f"{BASE}/ac/detail":
                store["ac_power_pct"] = data.get("ac_power_pct", 0.0)
                store["ac_temp_output"] = data.get("ac_temp_output")
                store["setpoint"] = data.get("setpoint", 25.0)
                store["mode"] = data.get("mode", "off")
            else:
                sensor = msg.topic.rsplit("/", 1)[-1]
                ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
                store[sensor].append((ts, data["value"]))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()
    return client, store


def latest(store, sensor):
    with store["lock"]:
        return store[sensor][-1][1] if store[sensor] else None


# Page setup
st.set_page_config(page_title="Smart Lab Digital Twin", layout="wide")

# Custom CSS to reduce spacing, margins, and push elements upwards
st.markdown("""
    <style>
        /* Reduce padding around main container */
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 0rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }
        /* Make headings tight */
        h1, h2, h3, h4, h5, h6 {
            margin-top: 0rem !important;
            margin-bottom: 0.4rem !important;
            padding-top: 0rem !important;
        }
        /* Spacing adjustments for columns */
        [data-testid="column"] {
            padding-top: 0rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# Main Title (centered and pushed up)
st.markdown("<h2 style='text-align: center; margin-bottom: 15px;'>Smart Lab Digital Twin — Room 1</h2>", unsafe_allow_html=True)

client, store = get_mqtt()
if "alert_on" not in st.session_state:
    st.session_state.alert_on = False

# ─── Top Row: Metrics (Side-by-side) ──────────────────────────
top_col_left, top_col_right = st.columns(2)

with top_col_left:
    top_left_box = st.container(border=True)

with top_col_right:
    top_right_box = st.container(border=True)


# ─── Middle Row: Controls (Horizontal Box) ─────────────────────
with st.container(border=True):
    st.markdown("<h4 style='margin-bottom: 10px;'>🎛️ Central Control Panel</h4>", unsafe_allow_html=True)
    
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1.2, 2, 2, 2])
    
    with ctrl_col1:
        st.markdown("**AC Mode**")
        confirmed_mode = store["mode"] if store["mode"] in ("auto", "manual") else "manual"
        mode_sel = st.radio(
            "Control mode", ["Auto", "Manual"],
            index=0 if confirmed_mode == "auto" else 1,
            horizontal=True, key="mode_sel", label_visibility="collapsed",
        )
        desired_mode = mode_sel.lower()
        if desired_mode != confirmed_mode:
            client.publish(f"{BASE}/cmd/mode", json.dumps({"mode": desired_mode}))
            st.toast(f"AC mode → {mode_sel}")
        if desired_mode == "manual":
            if st.button("❄️ AC ON", key="btn_on", width="stretch"):
                client.publish(f"{BASE}/cmd/hvac", json.dumps({"command": "on"}))
                st.toast("Sent AC ON command")
            if st.button("AC OFF", key="btn_off", width="stretch"):
                client.publish(f"{BASE}/cmd/hvac", json.dumps({"command": "off"}))
                st.toast("Sent AC OFF command")
        else:
            st.caption("🤖 System controls the AC automatically.")
            
    with ctrl_col2:
        st.markdown("**Target Temperature**")
        sp_val = st.slider("Setpoint (°C)", min_value=18.0, max_value=30.0, value=25.0, step=0.5, key="sp_slider_val")
        if st.button("Apply Setpoint", key="btn_sp", width="stretch"):
            client.publish(f"{BASE}/cmd/setpoint", json.dumps({"value": sp_val}))
            st.toast(f"Setpoint set to: {sp_val}°C")
            
    with ctrl_col3:
        st.markdown("**Simulation Speed**")
        ts_val = st.select_slider("Time Multiplier", options=[1, 2, 5, 10], value=1, format_func=lambda x: f"x{x}", key="ts_slider_val")
        if st.button("Apply Speed", key="btn_ts", width="stretch"):
            client.publish(f"{BASE}/cmd/timescale", json.dumps({"value": ts_val}))
            st.toast(f"Simulation speed set to: x{ts_val}")
            
    with ctrl_col4:
        st.markdown("**Occupancy Override**")
        occ_val = st.slider("Occupancy", min_value=0, max_value=30, value=2, step=1, key="occ_slider_val")
        if st.button("Apply Occupancy", key="btn_occ", width="stretch"):
            client.publish(f"{BASE}/cmd/occupancy", json.dumps({"value": occ_val}))
            st.toast(f"Occupancy set to: {occ_val}")


# ─── Bottom Row: Visualizations (Side-by-side containers) ──────
bottom_col_left, bottom_col_right = st.columns(2)

with bottom_col_left:
    bottom_left_box = st.container(border=True)

with bottom_col_right:
    bottom_right_box = st.container(border=True)
    with bottom_right_box:
        st.markdown("### 🧊 3D Room View")
        st.iframe("http://localhost:8000/room3d.html", height=380)


# ─── Live Update Loop (using st.fragment) ─────────────────────
@st.fragment(run_every=1.0)
def live_view():
    temp = latest(store, "temperature")
    hum = latest(store, "humidity")
    occ = latest(store, "occupancy")
    hvac = store["hvac_on"]
    ac_pct = store["ac_power_pct"]
    ac_temp = store["ac_temp_output"]
    sp = store["setpoint"]
    status = store["status"]
    mode = store["mode"] if store["mode"] in ("auto", "manual") else "manual"

    # Warning logic is mode-dependent:
    #   manual -> persistent banner at the fixed 30°C overheat ceiling (hysteresis)
    #   auto   -> NO persistent banner; a single toast fires on each on/off event
    if mode == "manual":
        if temp is not None:
            if temp > MANUAL_ALERT_ON:
                st.session_state.alert_on = True
            elif temp < MANUAL_ALERT_OFF:
                st.session_state.alert_on = False
        manual_overheat = st.session_state.alert_on and temp is not None
        limit_line = MANUAL_ALERT_ON
    else:  # auto
        manual_overheat = False
        limit_line = None

    # Auto-mode notifications: one toast per auto on/off transition (edge-triggered)
    prev_hvac = st.session_state.get("prev_hvac_on")
    if mode == "auto" and hvac is not None and prev_hvac is not None and hvac != prev_hvac:
        if hvac:
            who = f"{occ} people, " if occ else ""
            st.toast(f"⚠️ {who}above target {sp:.0f}°C — AC auto ON", icon="🔥")
        else:
            st.toast("Room empty — AC auto OFF", icon="❄️")
    st.session_state.prev_hvac_on = hvac

    # 1. Update Top Left Box (Room status metrics)
    with top_left_box:
        header_col, alert_col = st.columns([1.2, 2.0])
        with header_col:
            st.markdown("### 📊 Room Parameters")
        with alert_col:
            alert_placeholder = st.empty()
            
        if status == "offline":
            st.warning("Simulator offline — displaying last cached values.")
            
        # Persistent overheat banner (manual mode only; auto uses toasts)
        if manual_overheat:
            alert_placeholder.error(
                f"⚠️ OVERHEATING: {temp:.1f}°C (limit {MANUAL_ALERT_ON:.0f}°C)")
            
        c1, c2, c3 = st.columns(3)
        c1.metric("🌡 Temperature", f"{temp:.1f} °C" if temp is not None else "—")
        c2.metric("💧 Humidity", f"{hum:.1f} %" if hum is not None else "—")
        c3.metric("👥 Occupants", f"{occ} people" if occ is not None else "—")

    # 2. Update Top Right Box (AC status metrics)
    with top_right_box:
        st.markdown("### ❄️ HVAC Status")
        h0, h1, h2, h3, h4 = st.columns(5)
        h0.metric("🤖 Mode", "Auto" if mode == "auto" else "Manual")
        if hvac is None:
            h1.metric("AC", "Unknown")
        else:
            h1.metric("AC", "🟢 ON" if hvac else "⚪ OFF")
        h2.metric("⚡ AC Power", f"{round(ac_pct * 100)}%")
        h3.metric("🌬️ AC Vent Temp", f"{ac_temp:.1f}°C" if ac_temp is not None else "—")
        h4.metric("🎯 Target", f"{sp}°C")

    # 3. Update Bottom Left Box (Temperature chart + Prediction)
    with bottom_left_box:
        st.markdown("### 📈 Temperature Trend")
        with store["lock"]:
            points = list(store["temperature"])
        if points:
            xs, ys = zip(*points)

            fig = go.Figure()
            # Room temperature line
            fig.add_trace(go.Scatter(
                x=list(xs), y=list(ys), mode="lines",
                name="Room Temperature", line=dict(color="#3b82f6", width=2)
            ))

            # Overheat ceiling line (manual mode only; auto uses the target line)
            if limit_line is not None:
                fig.add_hline(y=limit_line, line_dash="dash", line_color="red",
                              annotation_text=f"limit {limit_line:.0f}°C")

            # Setpoint line
            fig.add_hline(y=sp, line_dash="dot", line_color="#22c55e",
                          annotation_text=f"setpoint {sp}°C",
                          annotation_position="bottom right")

            fig.update_layout(
                height=300, margin=dict(l=10, r=10, t=10, b=10),
                yaxis_title="°C",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Waiting for simulator telemetry...")

        # Predictive alert: linear fit over last 60s
        if len(points) >= 5:
            now = xs[-1]
            recent = [(x, y) for x, y in points if (now - x).total_seconds() <= 60]
            if len(recent) >= 5:
                t0 = recent[0][0]
                sec = np.array([(x - t0).total_seconds() for x, _ in recent])
                vals = np.array([y for _, y in recent])
                slope, _ = np.polyfit(sec, vals, 1)
                if mode == "manual" and slope > 0.001 and vals[-1] < MANUAL_ALERT_ON:
                    eta = (MANUAL_ALERT_ON - vals[-1]) / slope
                    if eta < 300:
                        st.warning(f"📈 Predicted to reach {MANUAL_ALERT_ON:.0f}°C in ~{eta:.0f}s "
                                   f"(rate +{slope*60:.2f}°C/min)")


live_view()
