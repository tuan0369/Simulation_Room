"""Room detail — Project 1's single-room experience, per room, plus health."""
import altair as alt
import pandas as pd
import streamlit as st

from lib.mqtt_client import get_mqtt, latest, publish, snapshot
from lib.ui import ROOM_NAMES, fmt, risk_band, room_name

client, store = get_mqtt()
data = snapshot(store)
rooms = data["rooms"]

if not rooms:
    st.info("Waiting for telemetry from the simulator…",
            icon=":material/hourglass:")
    st.stop()

known = [t for t in ROOM_NAMES if t in rooms] or sorted(rooms)
if st.session_state.selected_room not in known:
    st.session_state.selected_room = known[0]

twin_id = st.selectbox("Room", known, key="selected_room",
                       format_func=room_name)
room = rooms[twin_id]

st.subheader(room_name(twin_id))

# ── Controls ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("**Controls**")
    confirmed_mode = room["hvac"].get("mode", "auto")
    mode = st.segmented_control(
        "Control mode", ["auto", "manual"],
        default=confirmed_mode if confirmed_mode in ("auto", "manual") else "auto",
        key=f"mode_{twin_id}",
    )
    if mode and mode != confirmed_mode:
        publish(client, twin_id, "cmd/mode", {"mode": mode})
        st.toast(f"{room_name(twin_id)} → {mode}")

    if mode == "manual":
        with st.container(horizontal=True):
            if st.button("AC on", icon=":material/ac_unit:", width="stretch"):
                publish(client, twin_id, "cmd/hvac", {"command": "on"})
            if st.button("AC off", width="stretch"):
                publish(client, twin_id, "cmd/hvac", {"command": "off"})
    else:
        st.caption("The thermostat is controlling this room.")

    with st.form(f"targets_{twin_id}", border=False):
        setpoint = st.slider("Target temperature (°C)", 18.0, 30.0,
                             float(room["hvac"].get("setpoint", 23.0)), 0.5)
        occupancy = st.slider("Occupancy override", 0, 30,
                              int(latest(room["occupancy"]) or 0))
        if st.form_submit_button("Apply", width="stretch"):
            publish(client, twin_id, "cmd/setpoint", {"value": setpoint})
            publish(client, twin_id, "cmd/occupancy", {"value": occupancy})
            st.toast("Sent to the twin")

    speed = st.select_slider("Simulation speed", [1, 2, 5, 10],
                             value=1, format_func=lambda x: f"×{x}")
    if st.button("Apply speed", width="stretch"):
        publish(client, twin_id, "cmd/timescale", {"value": speed})

    st.divider()
    st.markdown("**Maintenance**")
    with st.container(horizontal=True):
        if st.button("Replace filter", width="stretch"):
            publish(client, twin_id, "cmd/maintenance",
                    {"action": "replace_filter"})
            st.toast("Filter replaced")
        if st.button("Service motor", width="stretch"):
            publish(client, twin_id, "cmd/maintenance",
                    {"action": "service_motor"})
            st.toast("Motor serviced")


# ── Live view ───────────────────────────────────────────────────────────────

@st.fragment(run_every=2.0)
def live():
    current = snapshot(store)["rooms"].get(twin_id, {})
    if not current:
        return
    hvac, ac, health, risk = (current["hvac"], current["ac"],
                              current["health"], current["risk"])
    temp = latest(current["temperature"])
    setpoint = hvac.get("setpoint")

    with st.container(horizontal=True):
        st.metric("Temperature", f"{fmt(temp)} °C",
                  delta=(f"{temp - setpoint:+.1f} vs target"
                         if temp is not None and setpoint else None),
                  delta_color="off", border=True)
        st.metric("Humidity", f"{fmt(latest(current['humidity']))} %",
                  border=True)
        st.metric("Occupancy", latest(current["occupancy"]) if
                  current["occupancy"] else "—", border=True)
        st.metric("AC power",
                  f"{round((hvac.get('ac_power_pct') or 0) * 100)} %",
                  border=True)
        st.metric("Vent temperature", f"{fmt(ac.get('ac_temp_output'))} °C",
                  border=True)

    left, right = st.columns([3, 2])

    with left, st.container(border=True):
        st.markdown("**Temperature**")
        points = current["temperature"]
        if len(points) < 2:
            st.caption("Collecting…")
        else:
            frame = pd.DataFrame(points, columns=["time", "temperature"])
            line = alt.Chart(frame).mark_line(color="#3b82f6").encode(
                x=alt.X("time:T", title=None),
                y=alt.Y("temperature:Q", title="°C",
                        scale=alt.Scale(zero=False)),
                tooltip=["time:T", "temperature:Q"])
            layers = [line]
            if setpoint:
                layers.append(
                    alt.Chart(pd.DataFrame({"y": [setpoint]}))
                    .mark_rule(color="#22c55e", strokeDash=[4, 4])
                    .encode(y="y:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=260),
                            use_container_width=False, width="stretch")

    with right, st.container(border=True):
        st.markdown("**Equipment health**")
        label, colour = risk_band(risk)
        st.markdown({"red": ":red-badge[Action needed]",
                     "orange": ":orange-badge[Watch]",
                     "green": ":green-badge[Healthy]"}.get(
                         colour, f":gray-badge[{label}]"))
        if risk.get("status") == "warming_up":
            st.caption(f"Re-establishing a baseline after service "
                       f"({risk.get('samples', 0)}/"
                       f"{risk.get('samples_required', '?')} samples).")
        elif risk.get("failure_prob") is not None:
            st.caption(f"{risk['failure_prob']:.1%} chance of failure within "
                       f"4 h · {risk.get('explanation', '')}")
            if risk.get("rul_hours") is not None:
                st.caption(f"Estimated {risk['rul_hours']:.0f} h of useful life "
                           f"remaining")
            st.caption(f"model {risk.get('model_version', '?')}")

        st.progress(min(float(health.get("filter_clog") or 0), 1.0),
                    text=f"Filter load {(health.get('filter_clog') or 0):.0%}")
        st.progress(min((health.get("motor_temp") or 0) / 100.0, 1.0),
                    text=f"Motor {fmt(health.get('motor_temp'))} °C "
                         f"(85 °C limit)")
        st.progress(min((health.get("vibration_mm_s") or 0) / 11.2, 1.0),
                    text=f"Vibration {fmt(health.get('vibration_mm_s'), '{:.2f}')}"
                         f" mm/s (7.1 alarm)")
        st.caption(f"Running hours since service: "
                   f"{fmt(health.get('runtime_hours'), '{:.1f}')}")


live()
