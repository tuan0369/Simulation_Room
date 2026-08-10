"""Building overview — the whole facility at a glance."""
import streamlit as st

from lib.mqtt_client import get_mqtt, latest, snapshot
from lib.ui import FLOOR_NAMES, fmt, risk_band, room_name

client, store = get_mqtt()

st.subheader("Building overview")

BADGE = {"red": ":red-badge[Action needed]", "orange": ":orange-badge[Watch]",
         "green": ":green-badge[Healthy]", "grey": ":gray-badge[No score]"}


@st.fragment(run_every=2.0)
def live():
    data = snapshot(store)
    rooms, building = data["rooms"], data["building"]

    if data["status"] == "offline":
        st.warning("Simulator offline — showing the last values received.",
                   icon=":material/cloud_off:")
    elif not rooms:
        st.info("Waiting for telemetry from the simulator…",
                icon=":material/hourglass:")
        return

    at_risk = sum(1 for r in rooms.values() if r["risk"].get("alert"))
    load = building.get("total_load_kw")
    budget = building.get("power_budget_kw")

    with st.container(horizontal=True):
        st.metric("People in building", building.get("occupancy", "—"),
                  border=True)
        st.metric("Electrical load", f"{fmt(load, '{:.1f}')} kW",
                  delta=(f"{load - budget:+.1f} kW vs budget"
                         if load is not None and budget else None),
                  delta_color="inverse", border=True)
        st.metric("Rooms needing action", at_risk,
                  delta="all clear" if at_risk == 0 else "review maintenance",
                  delta_color="off", border=True)
        st.metric("Simulated time",
                  f"{fmt(building.get('sim_hour'), '{:.1f}')} h", border=True)

    for floor_id in sorted({tid.split("/")[0] for tid in rooms}):
        summary = data["floors"].get(floor_id, {})
        header = FLOOR_NAMES.get(floor_id, floor_id)
        allocated = summary.get("allocated_kw")
        st.markdown(
            f"**{header}** — {fmt(summary.get('total_load_kw'), '{:.1f}')} kW"
            + (f" of {allocated:.1f} kW allocated" if allocated else "")
            + (f" · {len(summary.get('nudges', {}))} setpoint nudges active"
               if summary.get("nudges") else "")
        )

        floor_rooms = sorted(t for t in rooms if t.startswith(f"{floor_id}/"))
        for col, twin_id in zip(st.columns(len(floor_rooms), border=True),
                                floor_rooms):
            room = rooms[twin_id]
            label, colour = risk_band(room["risk"])
            temp = latest(room["temperature"])
            occ = latest(room["occupancy"])
            hvac = room["hvac"]
            with col:
                st.markdown(f"**{room_name(twin_id)}**  {BADGE.get(colour, '')}")
                st.metric("Temperature", f"{fmt(temp)} °C",
                          delta=(f"{temp - hvac['setpoint']:+.1f} vs target"
                                 if temp is not None and hvac.get("setpoint")
                                 else None),
                          delta_color="off")
                st.caption(
                    f":material/group: {occ if occ is not None else '—'} people"
                    f" · :material/mode_fan: "
                    f"{round((hvac.get('ac_power_pct') or 0) * 100)}% AC"
                    f" · {hvac.get('mode', '—')}"
                )


live()

with st.container(border=True):
    st.markdown("**3D view**")
    st.caption("Floor colour follows room temperature; a pulsing halo marks a "
               "room the maintenance model has flagged.")
    st.iframe("http://localhost:8000/building3d.html", height=420)
