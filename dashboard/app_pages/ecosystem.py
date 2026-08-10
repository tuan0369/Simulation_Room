"""Ecosystem — the federated hierarchy, live."""
import pandas as pd
import streamlit as st

from lib.mqtt_client import get_mqtt, snapshot
from lib.ui import FLOOR_NAMES, fmt, room_name

client, store = get_mqtt()

st.subheader("Twin ecosystem")


@st.fragment(run_every=3.0)
def live():
    data = snapshot(store)
    building, floors, rooms = data["building"], data["floors"], data["rooms"]
    if not rooms:
        st.info("Waiting for telemetry…", icon=":material/hourglass:")
        return

    load = building.get("total_load_kw")
    budget = building.get("power_budget_kw")
    over = building.get("over_budget")
    with st.container(horizontal=True):
        st.metric("Building load", f"{fmt(load)} kW", border=True)
        st.metric("Budget", f"{fmt(budget)} kW",
                  delta="exceeded" if over else "within",
                  delta_color="inverse" if over else "normal", border=True)
        st.metric("Broker messages", f"{data['messages']:,}", border=True)
        st.metric("Simulator", data["status"], border=True)

    st.markdown("**Floor supervision**")
    for floor_id, summary in sorted(floors.items()):
        nudges = summary.get("nudges", {})
        with st.container(border=True):
            st.markdown(f"**{FLOOR_NAMES.get(floor_id, floor_id)}** — "
                        f"{fmt(summary.get('total_load_kw'))} kW drawn, "
                        f"{fmt(summary.get('allocated_kw'))} kW allocated")
            if not nudges:
                st.caption("Within budget — the floor twin is silent. "
                           "Supervisors only speak when there is a problem.")
            else:
                st.caption("Over budget. Recommending setpoint nudges "
                           "(rooms apply them; each clamps to its own 1.5 °C limit):")
                st.dataframe(
                    pd.DataFrame([{"Room": room_name(t), "Nudge (°C)": f"+{v}"}
                                  for t, v in sorted(nudges.items())]),
                    hide_index=True, width="stretch")

    occupancy = data["occupancy"]
    if occupancy.get("nodes"):
        st.markdown("**Occupancy twin — people flow**")
        nodes = occupancy["nodes"]
        frame = pd.DataFrame(
            [{"Node": room_name(k) if "/corridor" not in k else
              f"{FLOOR_NAMES.get(k.split('/')[0], k)} corridor",
              "People": v} for k, v in nodes.items()])
        st.bar_chart(frame.set_index("Node"), height=220)
        st.caption(
            f"{occupancy.get('total_in_building', 0)} people in the building; "
            f"net flow through the entrance this step: "
            f"{occupancy.get('entrance_flow', 0):+d}. Interior movement "
            "conserves headcount exactly — people move between rooms rather "
            "than appearing and vanishing.")


live()

with st.container(border=True):
    st.markdown("**Why federated, not centralised**")
    st.markdown("""
```mermaid
flowchart TD
    B["Building twin<br/>30 s · budget + work orders"]
    F1["Floor twin f1<br/>10 s · aggregate + nudge"]
    F2["Floor twin f2<br/>10 s · aggregate + nudge"]
    R1["3 room twins<br/>1 s · own PID"]
    R2["3 room twins<br/>1 s · own PID"]
    O["Occupancy twin<br/>people flow"]
    B -- "kW allocation" --> F1 & F2
    F1 -- "setpoint advice" --> R1
    F2 -- "setpoint advice" --> R2
    R1 & R2 -- "load + risk" --> F1 & F2
    F1 & F2 -- "summaries" --> B
    O -- "occupancy" --> R1 & R2
```
""")
    st.markdown(
        "Rooms decide; supervisors advise. Every room keeps running its own "
        "control loop if the floor and building twins stop — a dead supervisor "
        "costs coordination, not cooling. Nudges are capped at 1.5 °C and the "
        "cap is enforced **by the room**, not by the supervisor sending the "
        "advice, so a supervisor fault cannot make a room unsafe.\n\n"
        "A centralised design would put all six control loops in one process: "
        "one crash stops every room, and every occupancy record would have to "
        "leave the room it came from. Here rooms publish counts, and floors "
        "publish only aggregates."
    )
