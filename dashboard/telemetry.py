"""Pure MQTT message parsing, telemetry storage, and command correlation helpers."""
from __future__ import annotations

import copy
import json
import math
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

DEFAULT_ROOM_IDS = ("room1", "room2", "room3", "room4")
AHU_BASE = "twin/ahu"
ECOSYSTEM_BASE = "twin/ecosystem"


def new_store(
    room_ids: Iterable[str] = DEFAULT_ROOM_IDS,
    *,
    sensor_history: int = 180,
    humidity_history: int | None = None,
    risk_history: int = 180,
) -> dict[str, Any]:
    """Create the dashboard's lock-protected, broker-independent telemetry store."""
    humidity_history = sensor_history if humidity_history is None else humidity_history
    if sensor_history < 1 or humidity_history < 1 or risk_history < 1:
        raise ValueError("history limits must be positive")
    rooms = tuple(room_ids)
    if not rooms or any(not isinstance(room, str) or not room for room in rooms):
        raise ValueError("room_ids must contain non-empty strings")
    return {
        "rooms": {
            room_id: {
                "temperature": deque(maxlen=sensor_history),
                "humidity": deque(maxlen=humidity_history),
                "occupancy": deque(maxlen=sensor_history),
                "hvac": {},
                "detail": {},
                "allocation": {},
                "energy": {},
                "status": "unknown",
            }
            for room_id in rooms
        },
        "ahu": {"state": {}, "energy": {}, "fan_health": {}, "decision": {}},
        "broker_status": "connecting",
        "broker_error": None,
        "ecosystem_status": "unknown",
        "presentation": {},
        "command_result": {},
        "command_results": deque(maxlen=100),
        "command_result_count": 0,
        "scenario": {},
        "risk_history": deque(maxlen=risk_history),
        "demand_forecast": {},
        "actions": {},
        "knowledge": {"entries": [], "active_evaluation": None, "auto_action_enabled": False},
        "lock": threading.Lock(),
    }


def decode_payload(payload: bytes | bytearray | memoryview | str) -> dict[str, Any] | None:
    """Decode a UTF-8 JSON object; malformed or non-object values return ``None``."""
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def apply_message(store: MutableMapping[str, Any], topic: str, payload: bytes | str) -> bool:
    """Apply one MQTT-shaped message, returning whether the store accepted it."""
    lock = store.get("lock")
    if lock is None:
        return _apply_message_unlocked(store, topic, payload)
    with lock:
        return _apply_message_unlocked(store, topic, payload)


def _apply_message_unlocked(store: MutableMapping[str, Any], topic: str, payload: bytes | str) -> bool:
    if topic == f"{ECOSYSTEM_BASE}/status":
        text = _decode_text(payload)
        if text is None:
            return False
        store["ecosystem_status"] = text
        return True

    ecosystem_key = {
        f"{ECOSYSTEM_BASE}/command/result": "command_result",
        f"{ECOSYSTEM_BASE}/scenario/state": "scenario",
        f"{ECOSYSTEM_BASE}/presentation/state": "presentation",
        f"{ECOSYSTEM_BASE}/intelligence/demand": "demand_forecast",
        f"{ECOSYSTEM_BASE}/intelligence/actions": "actions",
        f"{ECOSYSTEM_BASE}/knowledge/state": "knowledge",
    }.get(topic)
    if ecosystem_key:
        data = decode_payload(payload)
        if data is None:
            return False
        store[ecosystem_key] = data
        if ecosystem_key == "command_result":
            store.setdefault("command_results", deque(maxlen=100)).append(data)
            store["command_result_count"] = int(store.get("command_result_count", 0)) + 1
        return True

    parts = topic.split("/")
    rooms = store.get("rooms", {})
    if len(parts) >= 3 and parts[0] == "twin" and (parts[1] in rooms or parts[1].startswith("room")):
        if parts[1] not in rooms:
            rooms[parts[1]] = {
                "temperature": deque(maxlen=180),
                "humidity": deque(maxlen=120),
                "occupancy": deque(maxlen=180),
                "hvac": {},
                "detail": {},
                "allocation": {},
                "energy": {},
                "status": "unknown",
            }
        room = rooms[parts[1]]
        channel = parts[2]
        if channel == "status" and len(parts) == 3:
            text = _decode_text(payload)
            if text is None:
                return False
            room["status"] = text
            return True

        data = decode_payload(payload)
        if data is None:
            return False
        if channel in ("temperature", "humidity", "occupancy") and len(parts) == 3:
            point = _telemetry_point(data)
            if point is None:
                return False
            room[channel].append(point)
            return True
        target = {
            ("hvac", "state"): "hvac",
            ("hvac", "allocation"): "allocation",
            ("ac", "detail"): "detail",
        }.get(tuple(parts[2:4])) if len(parts) == 4 else None
        if target:
            room[target] = data
            return True
        if channel == "energy" and len(parts) == 3:
            room["energy"] = data
            return True
        return False

    ahu_key = {
        f"{AHU_BASE}/state": "state",
        f"{AHU_BASE}/energy": "energy",
        f"{AHU_BASE}/fan/health": "fan_health",
        f"{AHU_BASE}/coordinator/decision": "decision",
    }.get(topic)
    if ahu_key:
        data = decode_payload(payload)
        if data is None:
            return False
        store["ahu"][ahu_key] = data
        if ahu_key == "fan_health":
            point = _risk_point(data)
            if point is not None:
                store["risk_history"].append(point)
        return True
    return False


def set_transport_state(
    store: MutableMapping[str, Any],
    status: str,
    error: str | None = None,
) -> None:
    """Update broker transport state without conflating it with simulator status."""
    lock = store.get("lock")
    if lock is None:
        store["broker_status"] = status
        store["broker_error"] = error
        return
    with lock:
        store["broker_status"] = status
        store["broker_error"] = error


def snapshot_store(store: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep, lock-free snapshot suitable for rendering or assertions."""
    lock = store.get("lock")
    if lock is None:
        return _snapshot_unlocked(store)
    with lock:
        return _snapshot_unlocked(store)


def _snapshot_unlocked(store: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = {key: value for key, value in store.items() if key != "lock"}
    return _copy_value(snapshot)


def new_command(
    values: Mapping[str, Any] | None = None,
    *,
    command_id: str | None = None,
    source: str = "dashboard",
    **fields: Any,
) -> dict[str, Any]:
    """Build a command object carrying stable application-level correlation metadata."""
    if values is not None and not isinstance(values, Mapping):
        raise TypeError("values must be a mapping or None")
    identifier = uuid.uuid4().hex if command_id is None else command_id
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("command_id must be a non-empty string")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source must be a non-empty string")
    command = dict(values or {})
    command.update(fields)
    command["command_id"] = identifier
    command["source"] = source
    return command


def reconcile_pending_commands(
    pending: Mapping[str, Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], tuple[dict[str, Any], ...]]:
    """Remove correlated pending commands and return newly matched result records."""
    remaining = {command_id: dict(metadata) for command_id, metadata in pending.items()}
    matched: list[dict[str, Any]] = []
    for result in results:
        command_id = result.get("command_id") if isinstance(result, Mapping) else None
        if isinstance(command_id, str) and command_id in remaining:
            metadata = remaining.pop(command_id)
            matched.append({**metadata, **dict(result), "command_id": command_id})
    return remaining, tuple(matched)


def correlate_command_result(
    expected_command_id: str | Mapping[str, Any] | None,
    result: Mapping[str, Any] | bytes | str | None,
) -> bool:
    """Return true only when a well-formed result matches the expected command ID."""
    if isinstance(expected_command_id, Mapping):
        expected_command_id = expected_command_id.get("command_id")
    if not isinstance(expected_command_id, str) or not expected_command_id:
        return False
    if isinstance(result, (bytes, str)):
        result = decode_payload(result)
    if not isinstance(result, Mapping):
        return False
    return result.get("command_id") == expected_command_id


def _decode_text(payload: bytes | str) -> str | None:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, bytes):
        return payload.decode(errors="replace")
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _telemetry_point(data: Mapping[str, Any]) -> tuple[datetime, float] | None:
    timestamp = _parse_timestamp(data.get("timestamp"))
    value = _finite_number(data.get("value"))
    return (timestamp, value) if timestamp is not None and value is not None else None


def _risk_point(data: Mapping[str, Any]) -> tuple[datetime, float] | None:
    timestamp = _parse_timestamp(data.get("timestamp"))
    risk = _finite_number(data.get("failure_risk"))
    return (timestamp, risk) if timestamp is not None and risk is not None else None


def _copy_value(value: Any) -> Any:
    if isinstance(value, deque):
        return list(value)
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_value(item) for item in value)
    return copy.deepcopy(value)
