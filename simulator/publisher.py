"""MQTT publisher for the two-room intelligent HVAC ecosystem.

The legacy Room 1 topics are preserved so the original dashboard and 3D room
view continue to work. Room 2, the shared AHU, fan health, energy, and
coordinator topics extend that contract without replacing it.
"""
import hashlib
import json
import os
import queue
import random
import sys
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

try:  # Supports both `python -m simulator.publisher` and `python simulator/publisher.py`.
    from .audit import AuditJournal
    from .contracts import (
        decode_command_payload,
        exact_integer_choice,
        finite_number,
        rejected_outcome,
    )
    from .ecosystem import EcosystemSimulator, ROOM_IDS, decision_payload
    from .physics import OCC_MAX, OCC_MIN, RoomState, clamp
except ImportError:  # pragma: no cover - exercised by the documented script command.
    from audit import AuditJournal
    from contracts import (
        decode_command_payload,
        exact_integer_choice,
        finite_number,
        rejected_outcome,
    )
    from ecosystem import EcosystemSimulator, ROOM_IDS, decision_payload
    from physics import OCC_MAX, OCC_MIN, RoomState, clamp

BROKER_HOST = os.getenv("ECOHVAC_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("ECOHVAC_BROKER_PORT", "1883"))

# Legacy public topic constants: tests and existing external commands import these.
BASE = "twin/room1"
CMD_HVAC = f"{BASE}/cmd/hvac"
CMD_OCCUPANCY = f"{BASE}/cmd/occupancy"
CMD_SETPOINT = f"{BASE}/cmd/setpoint"
CMD_TIMESCALE = f"{BASE}/cmd/timescale"
CMD_MODE = f"{BASE}/cmd/mode"
STATUS_TOPIC = f"{BASE}/status"
HVAC_STATE_TOPIC = f"{BASE}/hvac/state"
AC_DETAIL_TOPIC = f"{BASE}/ac/detail"

ECOSYSTEM_STATUS_TOPIC = "twin/ecosystem/status"
AHU_BASE = "twin/ahu"
AHU_STATE_TOPIC = f"{AHU_BASE}/state"
AHU_ENERGY_TOPIC = f"{AHU_BASE}/energy"
AHU_FAN_HEALTH_TOPIC = f"{AHU_BASE}/fan/health"
COORDINATOR_DECISION_TOPIC = f"{AHU_BASE}/coordinator/decision"
SCENARIO_COMMAND_TOPIC = "twin/ecosystem/cmd/scenario"
SIMULATION_COMMAND_TOPIC = "twin/ecosystem/cmd/simulation"
COMMAND_RESULT_TOPIC = "twin/ecosystem/command/result"
SCENARIO_STATE_TOPIC = "twin/ecosystem/scenario/state"
PRESENTATION_STATE_TOPIC = "twin/ecosystem/presentation/state"
ESTIMATED_TARIFF_SGD_PER_KWH = 0.30

INTERVALS = {"temperature": 3, "humidity": 5, "occupancy": 2}
NOISE = 0.1
VALID_TIME_SCALES = {1, 2, 5, 10}
SETPOINT_MIN, SETPOINT_MAX = 18.0, 30.0


def room_base(room_id: str) -> str:
    return f"twin/{room_id}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_payload(sensor: str, value, unit: str, timestamp: str | None = None) -> str:
    """Build the legacy retained sensor payload shape."""
    return json.dumps(
        {
            "sensor": sensor,
            "value": value,
            "unit": unit,
            "timestamp": timestamp or utc_now_iso(),
        }
    )


def handle_command(state: RoomState, topic: str, payload: bytes) -> RoomState:
    """Apply a legacy Room 1 command to a standalone RoomState.

    This pure compatibility helper remains available to clients and unit tests.
    The live multi-room simulator validates equivalent commands through
    ``EcosystemSimulator.apply_command`` on its simulation thread.
    """
    envelope, rejection = decode_command_payload(topic, payload)
    if rejection is not None or envelope is None:
        return state
    data = envelope.values
    if topic == CMD_HVAC:
        cmd = data.get("command")
        if cmd in ("on", "off"):
            return replace(state, hvac_on=(cmd == "on"))
    elif topic == CMD_OCCUPANCY:
        value = data.get("value")
        if isinstance(value, int) and not isinstance(value, bool) and OCC_MIN <= value <= OCC_MAX:
            return replace(state, occupancy=value)
    elif topic == CMD_SETPOINT:
        value = finite_number(data.get("value"))
        if value is not None and SETPOINT_MIN <= value <= SETPOINT_MAX:
            return replace(state, setpoint=value)
    elif topic == CMD_TIMESCALE:
        value = exact_integer_choice(data.get("value"), VALID_TIME_SCALES)
        if value is not None:
            return replace(state, time_scale=float(value))
    elif topic == CMD_MODE:
        mode = data.get("mode")
        if mode in ("auto", "manual"):
            return replace(state, mode=mode)
    return state


class Simulator:
    """Run the shared-AHU ecosystem and publish a coherent MQTT telemetry stream."""

    def __init__(self, seed: int | None = None):
        self.ecosystem = EcosystemSimulator(seed=seed)
        self.rng = random.Random(seed)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.will_set(ECOSYSTEM_STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self._commands: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=256)
        self._command_results: dict[str, tuple[str, dict]] = {}
        self._state_lock = threading.Lock()
        self._force_publish = threading.Event()
        self.run_id = uuid.uuid4().hex
        self.snapshot_id = 0
        self.scenario_state = self._scenario_state("baseline", command_id=None)
        self.audit_journal: AuditJournal | None = None
        self.audit_error: str | None = None
        audit_path = os.environ.get("ECOHVAC_AUDIT_PATH")
        if audit_path:
            try:
                self.audit_journal = AuditJournal(audit_path)
            except Exception as exc:  # Startup remains visible instead of silently unaudited.
                self.audit_error = f"{type(exc).__name__}: {exc}"
                print(f"audit journal unavailable: {self.audit_error}", file=sys.stderr)

    @property
    def state(self) -> RoomState:
        """Expose Room 1 state for legacy code that used ``Simulator.state``."""
        with self._state_lock:
            return self.ecosystem.state

    @staticmethod
    def _scenario_state(name: str, command_id: str | None) -> dict:
        """Build the retained, single-phase guided-scenario state contract."""
        timestamp = utc_now_iso()
        stress = name == "shared_capacity_stress"
        return {
            "scenario_id": command_id or f"startup-{name}",
            "name": name,
            "status": "active" if stress else "ready",
            "phase": "stress_state_applied" if stress else "safe_baseline",
            "phase_index": 1,
            "phase_count": 1,
            "started_at": timestamp,
            "updated_at": timestamp,
            "narrative": (
                "Both rooms request cooling while degraded shared capacity prioritises Room 1."
                if stress
                else "Canonical two-room baseline restored; guided degradation is not active."
            ),
            "error": None,
        }

    def on_connect(self, client, userdata, flags, reason_code, properties):
        room_commands = [(f"{room_base(room_id)}/cmd/+", 0) for room_id in ROOM_IDS]
        client.subscribe(
            room_commands
            + [
                (f"{AHU_BASE}/cmd/+", 0),
                (SCENARIO_COMMAND_TOPIC, 0),
                (SIMULATION_COMMAND_TOPIC, 0),
            ]
        )
        client.publish(ECOSYSTEM_STATUS_TOPIC, "online", retain=True)
        for room_id in ROOM_IDS:
            client.publish(f"{room_base(room_id)}/status", "online", retain=True)
        self._force_publish.set()
        print("connected, subscribed to room and shared-AHU command topics")

    def on_message(self, client, userdata, msg):
        """Queue non-retained commands so callback threads never mutate state."""
        if bool(getattr(msg, "retain", False)):
            envelope, rejection = decode_command_payload(msg.topic, msg.payload)
            result = (
                rejection
                if rejection is not None
                else rejected_outcome(
                    msg.topic,
                    "retained_command_rejected",
                    command_id=envelope.command_id if envelope else None,
                    source=envelope.source if envelope else "unknown",
                )
            )
            payload = result.as_payload()
            self._audit_command(msg.topic, msg.payload, payload, retained=True)
            self._publish(COMMAND_RESULT_TOPIC, payload, retain=False)
            return
        try:
            self._commands.put_nowait((msg.topic, msg.payload))
        except queue.Full:
            result = {
                "accepted": False,
                "changed": False,
                "topic": msg.topic,
                "reason": "command_queue_full",
                "timestamp": utc_now_iso(),
            }
            self._audit_command(msg.topic, msg.payload, result, retained=False)
            self._publish(COMMAND_RESULT_TOPIC, result, retain=False)

    @staticmethod
    def _request_fingerprint(topic: str, payload: bytes) -> str:
        digest = hashlib.sha256()
        digest.update(topic.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(payload)
        return digest.hexdigest()

    def _audit_command(self, topic: str, payload: bytes, result: dict, *, retained: bool) -> None:
        """Append sanitized command metadata and result, surfacing write failures."""
        if self.audit_journal is None:
            return
        envelope, _ = decode_command_payload(topic, payload)
        sanitized_request = {
            "topic": topic,
            "command_id": envelope.command_id if envelope else result.get("command_id"),
            "source": envelope.source if envelope else result.get("source", "unknown"),
            "retained": retained,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_bytes": len(payload),
        }
        try:
            self.audit_journal.append(
                "command_result",
                {"request": sanitized_request, "result": result},
                actor=str(sanitized_request["source"]),
                correlation_id=sanitized_request["command_id"],
            )
            self.audit_error = None
        except Exception as exc:
            self.audit_error = f"{type(exc).__name__}: {exc}"
            result["audit_write_failed"] = True
            result["audit_error"] = self.audit_error
            print(f"audit write failed: {self.audit_error}", file=sys.stderr)

    def _drain_commands(self) -> bool:
        changed = False
        while True:
            try:
                topic, payload = self._commands.get_nowait()
            except queue.Empty:
                return changed
            envelope, rejection = decode_command_payload(topic, payload)
            fingerprint = self._request_fingerprint(topic, payload)
            cached = self._command_results.get(envelope.command_id) if envelope and envelope.command_id else None
            if cached is not None:
                cached_fingerprint, prior_result = cached
                result = prior_result.copy()
                result["duplicate"] = True
                result["replayed"] = cached_fingerprint == fingerprint
                if cached_fingerprint != fingerprint:
                    result.update(
                        {
                            "accepted": False,
                            "changed": False,
                            "reason": "command_id_conflict",
                            "timestamp": utc_now_iso(),
                        }
                    )
            else:
                outcome = rejection or self.ecosystem.apply_command_result(topic, payload)
                result = outcome.as_payload()
                if outcome.command_id:
                    self._command_results[outcome.command_id] = (fingerprint, result.copy())
                    while len(self._command_results) > 1024:
                        self._command_results.pop(next(iter(self._command_results)))
                if outcome.accepted and outcome.target == "ecosystem" and outcome.command == "scenario":
                    self.scenario_state = self._scenario_state(
                        self.ecosystem.active_scenario, outcome.command_id
                    )
            self._audit_command(topic, payload, result, retained=False)
            self._publish(COMMAND_RESULT_TOPIC, result, retain=False)
            changed = changed or bool(result["accepted"] and result["changed"] and not result.get("duplicate"))
            print(f"cmd {topic}: {payload!r} -> {result['reason']}")

    def _apply_scenario_command(self, payload: bytes) -> bool:
        """Apply a scenario through the canonical command parser and acknowledge it."""
        outcome = self.ecosystem.apply_command_result(SCENARIO_COMMAND_TOPIC, payload)
        self._publish(COMMAND_RESULT_TOPIC, outcome.as_payload(), retain=False)
        if outcome.accepted:
            self.scenario_state = self._scenario_state(
                self.ecosystem.active_scenario,
                outcome.command_id,
            )
        return outcome.accepted and outcome.changed

    def _publish(self, topic: str, payload: dict | str, *, retain: bool = True) -> None:
        serialized = payload if isinstance(payload, str) else json.dumps(payload)
        self.client.publish(topic, serialized, retain=retain)

    def _publish_sensor(self, room_id: str, sensor: str, state: RoomState) -> None:
        if sensor == "temperature":
            value, unit = round(state.temperature + self.rng.uniform(-NOISE, NOISE), 2), "C"
        elif sensor == "humidity":
            value, unit = round(state.humidity + self.rng.uniform(-NOISE, NOISE), 2), "%"
        else:
            value, unit = state.occupancy, "people"
        self.client.publish(
            f"{room_base(room_id)}/{sensor}",
            make_payload(sensor, value, unit),
            retain=True,
        )

    def _publish_room_state(self, room_id: str, runtime, timestamp: str) -> None:
        state = runtime.state
        allocation = runtime.allocation
        requested = runtime.requested_airflow_m3_s
        delivered = runtime.delivered_airflow_m3_s
        allocation_pct = delivered / requested if requested > 1e-9 else 1.0
        self._publish(
            f"{room_base(room_id)}/hvac/state",
            {
                "hvac_on": state.hvac_on,
                "ac_power_pct": round(state.ac_power_pct, 4),
                "setpoint": state.setpoint,
                "requested_airflow_m3_s": round(requested, 4),
                "delivered_airflow_m3_s": round(delivered, 4),
                "allocation_pct": round(allocation_pct, 4),
                "time_scale": state.time_scale,
                "timestamp": timestamp,
            },
        )
        self._publish(
            f"{room_base(room_id)}/ac/detail",
            {
                "ac_power_pct": round(state.ac_power_pct, 4),
                "ac_temp_output": round(self.ecosystem.ahu.supply_air_temp_c, 1),
                "setpoint": state.setpoint,
                "mode": state.mode,
                "timestamp": timestamp,
            },
        )
        self._publish(
            f"{room_base(room_id)}/hvac/allocation",
            {
                "requested_airflow_m3_s": round(requested, 4),
                "granted_airflow_m3_s": round(delivered, 4),
                "allocation_pct": round(allocation_pct, 4),
                "comfort_debt_c_s": round(runtime.comfort_debt_c_s, 3),
                "limited_service_s": round(runtime.limited_service_s, 3),
                "priority_score": list(allocation.priority_score[:4]) if allocation else [],
                "reason_codes": list(allocation.reason_codes) if allocation else [],
                "timestamp": timestamp,
            },
        )
        self._publish(
            f"{room_base(room_id)}/energy",
            {
                "thermal_cooling_power_w": round(runtime.thermal_cooling_power_w, 2),
                "estimated_cooling_power_w": round(runtime.thermal_cooling_power_w, 2),
                "unit": "W",
                "timestamp": timestamp,
            },
        )

    @staticmethod
    def _risk_payload(risk) -> dict:
        """Serialize scored and abstained predictions without inventing a risk value."""
        failure_risk = (
            round(risk.failure_risk, 4)
            if risk.failure_risk is not None
            else None
        )
        return {
            "failure_risk": failure_risk,
            "risk_band": risk.risk_band,
            "model_version": risk.model_version,
            "prediction_status": risk.prediction_status,
            "status_reason": risk.status_reason,
            "available": risk.available,
            "abstained": risk.abstained,
            "out_of_distribution": risk.out_of_distribution,
            "top_drivers": [
                {"feature": feature, "contribution": round(contribution, 3)}
                for feature, contribution in risk.top_drivers
            ],
        }

    def _publish_shared_state(self, snapshot, timestamp: str) -> None:
        ahu = snapshot.ahu
        fan = snapshot.fan
        telemetry = {
            "filter_clog_pct": round(ahu.filter_clog_pct, 4),
            "fan_speed_pct": round(ahu.fan_speed_pct, 4),
            "vibration_mm_s": round(fan.vibration_mm_s, 3),
            "bearing_temp_c": round(fan.bearing_temp_c, 2),
            "run_hours": round(fan.run_hours, 3),
        }
        self._publish(
            AHU_STATE_TOPIC,
            {
                "max_airflow_m3_s": round(ahu.max_airflow_m3_s, 4),
                "available_airflow_m3_s": round(snapshot.coordination.available_airflow_m3_s, 4),
                "delivered_airflow_m3_s": round(
                    sum(room.delivered_airflow_m3_s for room in snapshot.rooms.values()), 4
                ),
                "supply_air_temp_c": round(ahu.supply_air_temp_c, 1),
                "filter_clog_pct": round(ahu.filter_clog_pct, 4),
                "fan_speed_pct": round(ahu.fan_speed_pct, 4),
                "timestamp": timestamp,
            },
        )
        self._publish(
            AHU_ENERGY_TOPIC,
            {
                "thermal_cooling_power_w": round(
                    sum(room.thermal_cooling_power_w for room in snapshot.rooms.values()), 2
                ),
                "fan_electrical_power_w": round(ahu.fan_power_w, 2),
                "cooling_electrical_power_w": round(ahu.cooling_power_w, 2),
                "total_electrical_power_w": round(ahu.total_power_w, 2),
                "fan_power_w": round(ahu.fan_power_w, 2),
                "cooling_power_w": round(ahu.cooling_power_w, 2),
                "total_power_w": round(ahu.total_power_w, 2),
                "electrical_energy_kwh": round(ahu.energy_kwh, 6),
                "energy_kwh": round(ahu.energy_kwh, 6),
                "estimated_cost_sgd": round(ahu.energy_kwh * ESTIMATED_TARIFF_SGD_PER_KWH, 4),
                "tariff_sgd_per_kwh": ESTIMATED_TARIFF_SGD_PER_KWH,
                "timestamp": timestamp,
            },
        )
        health_payload = {
            "health_pct": round(fan.health_pct, 2),
            "wear_pct": round(fan.wear_pct, 4),
            "telemetry": telemetry,
            "timestamp": timestamp,
        }
        health_payload.update(self._risk_payload(snapshot.risk))
        self._publish(AHU_FAN_HEALTH_TOPIC, health_payload)
        payload = decision_payload(snapshot.coordination)
        payload["timestamp"] = timestamp
        self._publish(COORDINATOR_DECISION_TOPIC, payload)

    def _presentation_payload(self, snapshot, timestamp: str) -> dict:
        """Create one coherent retained payload for presentation clients."""
        rooms = {}
        for room_id, runtime in snapshot.rooms.items():
            requested = runtime.requested_airflow_m3_s
            granted = runtime.delivered_airflow_m3_s
            allocation = runtime.allocation
            rooms[room_id] = {
                "temperature_c": round(runtime.state.temperature, 3),
                "humidity_pct": round(runtime.state.humidity, 3),
                "occupancy": runtime.state.occupancy,
                "setpoint_c": runtime.state.setpoint,
                "mode": runtime.state.mode,
                "hvac_on": runtime.state.hvac_on,
                "ac_power_pct": round(runtime.state.ac_power_pct, 4),
                "time_scale": runtime.state.time_scale,
                "requested_airflow_m3_s": round(requested, 4),
                "granted_airflow_m3_s": round(granted, 4),
                "allocation_pct": round(granted / requested if requested > 1e-9 else 1.0, 4),
                "comfort_debt_c_s": round(runtime.comfort_debt_c_s, 3),
                "limited_service_s": round(runtime.limited_service_s, 3),
                "thermal_cooling_power_w": round(runtime.thermal_cooling_power_w, 2),
                "reason_codes": list(allocation.reason_codes) if allocation else [],
            }
        fan = snapshot.fan
        ahu = snapshot.ahu
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "snapshot_id": self.snapshot_id,
            "timestamp": timestamp,
            "scenario": self.scenario_state.copy(),
            "rooms": rooms,
            "ahu": {
                "max_airflow_m3_s": round(ahu.max_airflow_m3_s, 4),
                "available_airflow_m3_s": round(snapshot.coordination.available_airflow_m3_s, 4),
                "delivered_airflow_m3_s": round(sum(room.delivered_airflow_m3_s for room in snapshot.rooms.values()), 4),
                "supply_air_temp_c": round(ahu.supply_air_temp_c, 1),
                "filter_clog_pct": round(ahu.filter_clog_pct, 4),
                "fan_wear_pct": round(ahu.fan_wear_pct, 4),
                "fan_speed_pct": round(ahu.fan_speed_pct, 4),
                "thermal_cooling_power_w": round(
                    sum(room.thermal_cooling_power_w for room in snapshot.rooms.values()), 2
                ),
                "cooling_electrical_power_w": round(ahu.cooling_power_w, 2),
                "total_electrical_power_w": round(ahu.total_power_w, 2),
                "electrical_energy_kwh": round(ahu.energy_kwh, 6),
                "energy_kwh": round(ahu.energy_kwh, 6),
                "total_power_w": round(ahu.total_power_w, 2),
                "health_pct": round(fan.health_pct, 2),
            },
            "risk": self._risk_payload(snapshot.risk),
            "coordination": {
                "policy": decision_payload(snapshot.coordination)["policy"],
                "constrained": snapshot.coordination.constrained,
                "requested_airflow_m3_s": round(snapshot.coordination.requested_airflow_m3_s, 4),
                "available_airflow_m3_s": round(snapshot.coordination.available_airflow_m3_s, 4),
            },
        }

    def publish_snapshot(self, snapshot) -> None:
        """Publish all state channels from a single ecosystem snapshot."""
        timestamp = utc_now_iso()
        self.snapshot_id += 1
        self.scenario_state["updated_at"] = timestamp
        for room_id, runtime in snapshot.rooms.items():
            self._publish_room_state(room_id, runtime, timestamp)
        self._publish_shared_state(snapshot, timestamp)
        scenario_payload = self.scenario_state.copy()
        scenario_payload.update(self.ecosystem.scenario_state())
        self._publish(SCENARIO_STATE_TOPIC, scenario_payload)
        self._publish(
            PRESENTATION_STATE_TOPIC,
            self._presentation_payload(snapshot, timestamp),
        )

    def process_once(self, tick: int = 0):
        """Process one finite simulation/publish iteration for integration tests."""
        with self._state_lock:
            command_applied = self._drain_commands()
            snapshot = self.ecosystem.tick()

        for room_id, runtime in snapshot.rooms.items():
            for sensor, interval in INTERVALS.items():
                if tick % interval == 0:
                    self._publish_sensor(room_id, sensor, runtime.state)

        if tick % 2 == 0 or command_applied or self._force_publish.is_set():
            self.publish_snapshot(snapshot)
            self._force_publish.clear()
        return snapshot

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()
        tick = 0
        try:
            while True:
                self.process_once(tick)
                tick += 1
                time.sleep(1)
        except KeyboardInterrupt:
            self.client.publish(ECOSYSTEM_STATUS_TOPIC, "offline", retain=True)
            for room_id in ROOM_IDS:
                self.client.publish(f"{room_base(room_id)}/status", "offline", retain=True)
            self.client.loop_stop()
        finally:
            if self.audit_journal is not None:
                self.audit_journal.close()


if __name__ == "__main__":
    Simulator().run()
