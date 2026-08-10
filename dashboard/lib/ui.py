"""Shared presentation helpers.

Kept small and free of Streamlit layout so pages stay readable as scripts.
"""
from __future__ import annotations

ROOM_NAMES = {
    "f1/lab-a": "Wet lab A",
    "f1/lab-b": "Dry lab B",
    "f1/server-room": "Server room",
    "f2/lab-c": "Teaching lab C",
    "f2/meeting-room": "Meeting room",
    "f2/office": "Open office",
}

FLOOR_NAMES = {"f1": "Ground floor", "f2": "First floor"}

FAULT_NAMES = {
    "hdf": "Heat dissipation",
    "osf": "Overstrain",
    "pwf": "Power",
    "airflow": "Airflow",
    "bearing": "Bearing",
    "none": "None",
    "unknown": "Unknown",
}


def room_name(twin_id: str) -> str:
    return ROOM_NAMES.get(twin_id, twin_id)


def risk_band(risk: dict) -> tuple[str, str]:
    """(label, colour) for a risk payload — never a bare number.

    A probability shown without its provenance is the transparency failure the
    governance section exists to prevent, so an unscorable unit says so.
    """
    if not risk:
        return "No data", "grey"
    if risk.get("status") == "unavailable":
        return "Model unavailable", "grey"
    if risk.get("status") == "warming_up":
        return "Establishing baseline", "grey"
    prob = risk.get("failure_prob")
    if prob is None:
        return "No score", "grey"
    if risk.get("alert"):
        return "Action needed", "red"
    threshold = risk.get("threshold") or 0.005
    if prob >= threshold * 0.5:
        return "Watch", "orange"
    return "Healthy", "green"


def temp_delta(current: float | None, setpoint: float | None) -> str | None:
    if current is None or setpoint is None:
        return None
    return f"{current - setpoint:+.1f} °C vs target"


def fmt(value, spec="{:.1f}", dash="—"):
    return dash if value is None else spec.format(value)
