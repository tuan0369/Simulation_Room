"""Pure command parsing and application-result contracts for the simulator."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAX_COMMAND_BYTES = 16_384
MAX_IDENTIFIER_LENGTH = 128


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class CommandEnvelope:
    """Validated JSON object plus optional application-correlation metadata."""

    values: dict[str, Any]
    command_id: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class CommandOutcome:
    """Application-level acknowledgement, distinct from MQTT transport PUBACK."""

    topic: str
    target: str
    command: str
    accepted: bool
    changed: bool
    reason: str
    command_id: str | None = None
    source: str = "unknown"
    applied_values: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now_iso)

    def as_payload(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "source": self.source,
            "topic": self.topic,
            "target": self.target,
            "command": self.command,
            "accepted": self.accepted,
            "changed": self.changed,
            "reason": self.reason,
            "applied_values": self.applied_values,
            "timestamp": self.timestamp,
        }


def command_target(topic: str) -> tuple[str, str]:
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "twin" and parts[2] == "cmd":
        return parts[1], parts[3]
    return "unknown", "unknown"


def rejected_outcome(
    topic: str,
    reason: str,
    *,
    command_id: str | None = None,
    source: str = "unknown",
) -> CommandOutcome:
    target, command = command_target(topic)
    return CommandOutcome(
        topic=topic,
        target=target,
        command=command,
        accepted=False,
        changed=False,
        reason=reason,
        command_id=command_id,
        source=source,
    )


def decode_command_payload(
    topic: str, payload: bytes
) -> tuple[CommandEnvelope | None, CommandOutcome | None]:
    """Decode strict JSON, rejecting non-standard numeric constants and bad metadata."""
    if len(payload) > MAX_COMMAND_BYTES:
        return None, rejected_outcome(topic, "payload_too_large")

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        data = json.loads(payload, parse_constant=reject_constant)
    except UnicodeDecodeError:
        return None, rejected_outcome(topic, "invalid_utf8")
    except (json.JSONDecodeError, ValueError):
        return None, rejected_outcome(topic, "invalid_json")
    if not isinstance(data, dict):
        return None, rejected_outcome(topic, "payload_must_be_object")

    command_id = data.get("command_id")
    source = data.get("source", "unknown")
    if command_id is not None and (
        not isinstance(command_id, str)
        or not command_id.strip()
        or len(command_id) > MAX_IDENTIFIER_LENGTH
    ):
        return None, rejected_outcome(topic, "invalid_command_id")
    if not isinstance(source, str) or not source.strip() or len(source) > MAX_IDENTIFIER_LENGTH:
        return None, rejected_outcome(
            topic, "invalid_source", command_id=command_id if isinstance(command_id, str) else None
        )
    return CommandEnvelope(values=data, command_id=command_id, source=source), None


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def exact_integer_choice(value: object, allowed: set[int]) -> int | None:
    converted = finite_number(value)
    if converted is None or not converted.is_integer():
        return None
    integer = int(converted)
    return integer if integer in allowed else None
