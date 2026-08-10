"""MQTT payload formatting and command handling.

Split out of publisher.py so `room_twin` can use it without importing the
orchestrator that owns room twins (which would be an import cycle).
`publisher` re-exports everything here, so its existing tests are unaffected.

Command topics are matched by SUFFIX, not equality, because each of the six
rooms has its own topic subtree: `twin/f1/lab-a/cmd/hvac`,
`twin/f2/office/cmd/hvac`, and so on.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from physics import OCC_MAX, OCC_MIN, RoomState, clamp

TOPIC_ROOT = "twin"

# Command suffixes (see module docstring: matched with str.endswith)
CMD_HVAC = "cmd/hvac"
CMD_OCCUPANCY = "cmd/occupancy"
CMD_SETPOINT = "cmd/setpoint"
CMD_TIMESCALE = "cmd/timescale"
CMD_MODE = "cmd/mode"
CMD_AUTOFIX = "cmd/autofix"
CMD_MAINTENANCE = "cmd/maintenance"

VALID_TIME_SCALES = {1, 2, 5, 10}
SETPOINT_MIN, SETPOINT_MAX = 18.0, 30.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_payload(sensor: str, value, unit: str, timestamp: str | None = None) -> str:
    return json.dumps({"sensor": sensor, "value": value, "unit": unit,
                       "timestamp": timestamp or utc_now_iso()})


def parse_command_topic(topic: str) -> tuple[str, str] | None:
    """Split `twin/<floor>/<room>/cmd/<kind>` into (twin_id, "cmd/<kind>").

    Returns None for anything that is not a room command, so the orchestrator
    can ignore unrelated traffic rather than guessing at it.
    """
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != TOPIC_ROOT or parts[3] != "cmd":
        return None
    return f"{parts[1]}/{parts[2]}", f"{parts[3]}/{parts[4]}"


def handle_command(state: RoomState, topic: str, payload: bytes,
                   config=None) -> RoomState:
    """Apply a control command to room state; malformed commands are ignored.

    Ignoring rather than raising is deliberate: a bad MQTT payload — including
    a hostile one — must never be able to stop a room's cooling.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return state
    if not isinstance(data, dict):
        return state

    occ_max = config.max_occupancy if config else OCC_MAX

    if topic.endswith(CMD_HVAC):
        cmd = data.get("command")
        if cmd in ("on", "off"):
            return replace(state, hvac_on=(cmd == "on"))
    elif topic.endswith(CMD_OCCUPANCY):
        v = data.get("value")
        if isinstance(v, int) and not isinstance(v, bool):
            return replace(state, occupancy=clamp(v, OCC_MIN, occ_max))
    elif topic.endswith(CMD_SETPOINT):
        v = data.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return replace(state, setpoint=clamp(float(v), SETPOINT_MIN, SETPOINT_MAX))
    elif topic.endswith(CMD_TIMESCALE):
        v = data.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = int(v)
            if v in VALID_TIME_SCALES:
                return replace(state, time_scale=float(v))
    elif topic.endswith(CMD_MODE):
        m = data.get("mode")
        if m in ("auto", "manual"):
            return replace(state, mode=m)
    return state


def parse_maintenance(payload: bytes) -> str | None:
    """Extract a maintenance action, or None if the payload is unusable."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    return action if isinstance(action, str) else None
