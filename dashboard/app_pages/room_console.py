"""Room console — Project 1's single-room layout, now for any of six rooms.

Deliberately mirrors the Project-1 dashboard: two status cards side by side, a
full-width central control panel, then the temperature trend beside the 3D view.
That layout reads as one console rather than a report, which is why it is the
landing page.

Built with native Streamlit containers rather than Project 1's injected CSS, and
with `st.segmented_control` in place of a horizontal radio, per the
developing-with-streamlit skill. The one addition is an equipment-health metric
in the HVAC card — Project 2's whole point, and the card had room for it.
"""
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

with st.sidebar:
    st.selectbox("Room", known, key="selected_room", format_func=room_name)
    st.caption("Every room runs its own control loop. Switching rooms here does "
               "not disturb the others.")

twin_id = st.session_state.selected_room

with st.container(horizontal_alignment="center"):
    st.subheader(f"Smart Facility Digital Twin — {room_name(twin_id)}")

top_left, top_right = st.columns(2)
mid = st.container(border=True)
bottom_left, bottom_right = st.columns(2)


# ── Central control panel (static; reads confirmed state each rerun) ────────

room_now = rooms[twin_id]
with mid:
    st.markdown("##### :material/tune: Central control panel")
    c1, c2, c3, c4 = st.columns([1.2, 2, 2, 2])

    with c1:
        st.markdown("**AC mode**")
        confirmed = room_now["hvac"].get("mode", "auto")
        mode = st.segmented_control(
            "AC mode", ["Auto", "Manual"],
            default="Auto" if confirmed == "auto" else "Manual",
            key=f"mode_{twin_id}", label_visibility="collapsed")
        if mode and mode.lower() != confirmed:
            publish(client, twin_id, "cmd/mode", {"mode": mode.lower()})
            st.toast(f"{room_name(twin_id)} → {mode}")
        if mode == "Manual":
            if st.button("AC on", icon=":material/ac_unit:", width="stretch"):
                publish(client, twin_id, "cmd/hvac", {"command": "on"})
            if st.button("AC off", width="stretch"):
                publish(client, twin_id, "cmd/hvac", {"command": "off"})
        else:
            st.caption("The thermostat controls the AC automatically.")

    with c2:
        st.markdown("**Target temperature**")
        sp = st.slider("Setpoint (°C)", 18.0, 30.0,
                       float(room_now["hvac"].get("setpoint", 23.0)), 0.5,
                       key=f"sp_{twin_id}")
        if st.button("Apply setpoint", width="stretch", key=f"bsp_{twin_id}"):
            publish(client, twin_id, "cmd/setpoint", {"value": sp})
            st.toast(f"Target set to {sp} °C")

    with c3:
        st.markdown("**Simulation speed**")
        ts = st.select_slider("Time multiplier", [1, 2, 5, 10], value=1,
                              format_func=lambda x: f"×{x}", key=f"ts_{twin_id}")
        if st.button("Apply speed", width="stretch", key=f"bts_{twin_id}"):
            publish(client, twin_id, "cmd/timescale", {"value": ts})
            st.toast(f"Simulation speed ×{ts}")

    with c4:
        st.markdown("**Occupancy override**")
        occ = st.slider("Occupancy", 0, 30,
                        int(latest(room_now["occupancy"]) or 0),
                        key=f"occ_{twin_id}")
        if st.button("Apply occupancy", width="stretch", key=f"bocc_{twin_id}"):
            publish(client, twin_id, "cmd/occupancy", {"value": occ})
            st.toast(f"Occupancy set to {occ}")


with bottom_right:
    with st.container(border=True):
        st.markdown("##### :material/view_in_ar: 3D building view")
        st.iframe("http://localhost:8000/room3d/building3d.html", height=430)


# ── Live panels ─────────────────────────────────────────────────────────────

@st.fragment(run_every=1.5)
def live():
    current = snapshot(store)["rooms"].get(twin_id)
    if not current:
        return
    hvac, ac, health, risk = (current["hvac"], current["ac"],
                              current["health"], current["risk"])
    temp = latest(current["temperature"])
    setpoint = hvac.get("setpoint")
    label, colour = risk_band(risk)

    with top_left, st.container(border=True):
        st.markdown("##### :material/monitor_heart: Room parameters")
        a, b, c = st.columns(3)
        a.metric("Temperature", f"{fmt(temp)} °C",
                 delta=(f"{temp - setpoint:+.1f} vs target"
                        if temp is not None and setpoint else None),
                 delta_color="off")
        b.metric("Humidity", f"{fmt(latest(current['humidity']))} %")
        c.metric("Occupants",
                 f"{latest(current['occupancy'])} people"
                 if current["occupancy"] else "—")
        if data["status"] == "offline":
            st.warning("Simulator offline — showing last known values.",
                       icon=":material/cloud_off:")

    with top_right, st.container(border=True):
        st.markdown("##### :material/hvac: HVAC status")
        d, e, f, g, h = st.columns(5)
        d.metric("Mode", (hvac.get("mode") or "—").title())
        on = hvac.get("hvac_on")
        e.metric("AC", "—" if on is None else ("On" if on else "Off"))
        f.metric("AC power", f"{round((hvac.get('ac_power_pct') or 0) * 100)}%")
        g.metric("Vent temp", f"{fmt(ac.get('ac_temp_output'))} °C")
        h.metric("Target", f"{fmt(setpoint)} °C")
        st.markdown(
            {"red": ":red-badge[Maintenance needed]",
             "orange": ":orange-badge[Watch]",
             "green": ":green-badge[Equipment healthy]"}.get(
                colour, f":gray-badge[{label}]")
            + (f" &nbsp; {risk['explanation']}"
               if risk.get("explanation") and risk.get("alert") else ""))

    with bottom_left, st.container(border=True):
        st.markdown("##### :material/show_chart: Temperature trend")
        points = current["temperature"]
        if len(points) < 2:
            st.caption("Collecting telemetry…")
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
            st.altair_chart(alt.layer(*layers).properties(height=330),
                            width="stretch")
            st.caption(f"Dashed line: target {fmt(setpoint)} °C · "
                       f"filter {(health.get('filter_clog') or 0):.0%} loaded · "
                       f"motor {fmt(health.get('motor_temp'))} °C")


live()
