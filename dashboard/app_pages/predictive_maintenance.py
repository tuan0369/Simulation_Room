"""Predictive maintenance — ranked risk, work orders, and the model's limits.

The limitations are shown in the UI, not just in the model card. A dashboard
that prints a probability without saying what the model cannot see is the
transparency failure the governance section exists to prevent.
"""
import json

import pandas as pd
import streamlit as st

from lib.mqtt_client import get_mqtt, publish, snapshot
from lib.ui import FAULT_NAMES, fmt, risk_band, room_name

client, store = get_mqtt()

st.subheader("Predictive maintenance")

with st.sidebar:
    st.markdown("**Autonomous remediation**")
    auto = st.toggle(
        "Auto-fix predicted failures", value=False, key="autofix",
        help="When on, the building twin dispatches filter replacement and "
             "motor servicing itself instead of waiting for approval. Limited "
             "to those two preventive actions, at most one per unit per 24 h. "
             "It can never stop cooling or change a setpoint.",
    )
    if auto != st.session_state.get("_autofix_sent"):
        client.publish("twin/building/cmd/autofix", json.dumps({"enabled": auto}))
        st.session_state._autofix_sent = auto
        st.toast(f"Auto-fix {'enabled' if auto else 'disabled'}")
    if auto:
        st.warning("Preventive servicing will be dispatched without approval.",
                   icon=":material/bolt:")
    else:
        st.caption("Off — every work order needs human approval.")


@st.fragment(run_every=3.0)
def live():
    data = snapshot(store)
    rooms = data["rooms"]
    if not rooms:
        st.info("Waiting for telemetry…", icon=":material/hourglass:")
        return

    rows = []
    for twin_id, room in sorted(rooms.items()):
        risk, health = room["risk"], room["health"]
        label, _ = risk_band(risk)
        rows.append({
            "Room": room_name(twin_id),
            "Status": label,
            "Failure risk": risk.get("failure_prob"),
            "Likely fault": FAULT_NAMES.get(risk.get("likely_fault"), "—"),
            "Driver": risk.get("explanation", "—"),
            "Life left (h)": risk.get("rul_hours"),
            "Motor °C": health.get("motor_temp"),
            "Filter": health.get("filter_clog"),
            "Vibration": health.get("vibration_mm_s"),
        })
    frame = pd.DataFrame(rows).sort_values(
        "Failure risk", ascending=False, na_position="last")

    st.dataframe(
        frame, hide_index=True, width="stretch",
        column_config={
            "Failure risk": st.column_config.ProgressColumn(
                "Failure risk (4 h)", min_value=0.0, max_value=1.0,
                format="percent"),
            "Filter": st.column_config.ProgressColumn(
                "Filter load", min_value=0.0, max_value=1.0, format="percent"),
            "Motor °C": st.column_config.NumberColumn(format="%.1f"),
            "Vibration": st.column_config.NumberColumn(
                "Vibration (mm/s)", format="%.2f"),
            "Life left (h)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    st.markdown("**Open work orders**")
    advisories = data["advisories"]
    if not advisories:
        st.caption("None. The coordinator raises one when a unit crosses the "
                   "model's decision threshold or the thermal guard trips.")
    else:
        for order in advisories[:8]:
            twin_id = order.get("twin_id", "?")
            with st.container(border=True):
                st.markdown(
                    f"**{room_name(twin_id)}** — {order.get('action', '?').replace('_', ' ')}"
                    f"  :orange-badge[Needs approval]")
                st.caption(
                    f"{FAULT_NAMES.get(order.get('top_factor'), order.get('top_factor', '—'))}"
                    f" · risk {fmt(order.get('failure_prob'), '{:.1%}')}"
                    f" · raised {order.get('timestamp', '')}")
                if st.button("Approve and dispatch",
                             key=f"approve_{twin_id}_{order.get('timestamp')}"):
                    publish(client, twin_id, "cmd/maintenance",
                            {"action": order.get("action", "inspect")})
                    st.toast(f"Dispatched to {room_name(twin_id)}")


live()

with st.container(border=True):
    st.markdown("**What this model can and cannot do**")
    st.markdown(
        "- Trained on **simulated** telemetry. Failure thresholds are inherited "
        "from the UCI AI4I 2020 dataset, so they are not invented, but a real "
        "deployment needs recalibration on ≥3 months of real data first.\n"
        "- Detects all five failure modes, recall 0.95–1.00 in every room. An "
        "earlier version was blind to heat-dissipation failure; the cause was "
        "too few training examples of it, not tuning.\n"
        "- **Teaching lab C is the weakest room**: precision 0.46, so roughly "
        "half of its work orders are unnecessary.\n"
        "- Much weaker on equipment it has never seen (PR-AUC 0.26 vs 0.96) — "
        "a newly commissioned unit is not covered until it has its own history.\n"
        "- The model opens tickets. **It never switches anything off.** With "
        "auto-fix off, every order needs approval; with it on, the twin may "
        "dispatch filter and motor servicing only, once per unit per 24 h."
    )
    st.caption("Full detail: ml/models/model_card.md")
