"""MQTT publisher for the two-room intelligent HVAC ecosystem.

The legacy Room 1 topics are preserved so the original dashboard and 3D room
view continue to work. Room 2, the shared AHU, fan health, energy, and
coordinator topics extend that contract without replacing it.
"""
import json
import queue
import random
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

try:  # Supports both `python -m simulator.publisher` and `python simulator/publisher.py`.
    from .ecosystem import EcosystemSimulator, ROOM_IDS, decision_payload
    from .physics import OCC_MAX, OCC_MIN, RoomState, clamp
except ImportError:  # pragma: no cover - exercised by the documented script command.
    from ecosystem import EcosystemSimulator, ROOM_IDS, decision_payload
    from physics import OCC_MAX, OCC_MIN, RoomState, clamp

BROKER_HOST = "localhost"
BROKER_PORT = 1883

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
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return state
    if not isinstance(data, dict):
        return state
    if topic == CMD_HVAC:
        cmd = data.get("command")
        if cmd in ("on", "off"):
            return replace(state, hvac_on=(cmd == "on"))
    elif topic == CMD_OCCUPANCY:
        value = data.get("value")
        if isinstance(value, int) and not isinstance(value, bool):
            return replace(state, occupancy=clamp(value, OCC_MIN, OCC_MAX))
    elif topic == CMD_SETPOINT:
        value = data.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return replace(state, setpoint=clamp(float(value), SETPOINT_MIN, SETPOINT_MAX))
    elif topic == CMD_TIMESCALE:
        value = data.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = int(value)
            if value in VALID_TIME_SCALES:
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
        self._commands: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self._state_lock = threading.Lock()
        self._force_publish = threading.Event()

    @property
    def state(self) -> RoomState:
        """Expose Room 1 state for legacy code that used ``Simulator.state``."""
        with self._state_lock:
            return self.ecosystem.state

    def on_connect(self, client, userdata, flags, reason_code, properties):
        room_commands = [(f"{room_base(room_id)}/cmd/+", 0) for room_id in ROOM_IDS]
        client.subscribe(room_commands + [(f"{AHU_BASE}/cmd/+", 0)])
        client.publish(ECOSYSTEM_STATUS_TOPIC, "online", retain=True)
        for room_id in ROOM_IDS:
            client.publish(f"{room_base(room_id)}/status", "online", retain=True)
        self._force_publish.set()
        print("connected, subscribed to room and shared-AHU command topics")

    def on_message(self, client, userdata, msg):
        """Queue commands so callback threads never mutate simulation state."""
        self._commands.put((msg.topic, msg.payload))

    def _drain_commands(self) -> bool:
        changed = False
        while True:
            try:
                topic, payload = self._commands.get_nowait()
            except queue.Empty:
                return changed
            applied = self.ecosystem.apply_command(topic, payload)
            changed = changed or applied
            print(f"cmd {topic}: {payload!r} -> {'applied' if applied else 'ignored'}")

    def _publish(self, topic: str, payload: dict | str) -> None:
        serialized = payload if isinstance(payload, str) else json.dumps(payload)
        self.client.publish(topic, serialized, retain=True)

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
                "priority_score": list(allocation.priority_score[:3]) if allocation else [],
                "reason_codes": list(allocation.reason_codes) if allocation else [],
                "timestamp": timestamp,
            },
        )
        room_cooling = max(0.0, state.temperature - self.ecosystem.ahu.supply_air_temp_c)
        room_cooling *= delivered * 1206.0
        self._publish(
            f"{room_base(room_id)}/energy",
            {
                "estimated_cooling_power_w": round(room_cooling, 2),
                "unit": "W",
                "timestamp": timestamp,
            },
        )

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
                "fan_power_w": round(ahu.fan_power_w, 2),
                "cooling_power_w": round(ahu.cooling_power_w, 2),
                "total_power_w": round(ahu.total_power_w, 2),
                "energy_kwh": round(ahu.energy_kwh, 6),
                "estimated_cost_sgd": round(ahu.energy_kwh * ESTIMATED_TARIFF_SGD_PER_KWH, 4),
                "tariff_sgd_per_kwh": ESTIMATED_TARIFF_SGD_PER_KWH,
                "timestamp": timestamp,
            },
        )
        self._publish(
            AHU_FAN_HEALTH_TOPIC,
            {
                "health_pct": round(fan.health_pct, 2),
                "wear_pct": round(fan.wear_pct, 4),
                "failure_risk": round(snapshot.risk.failure_risk, 4),
                "risk_band": snapshot.risk.risk_band,
                "model_version": snapshot.risk.model_version,
                "top_drivers": [
                    {"feature": feature, "contribution": round(contribution, 3)}
                    for feature, contribution in snapshot.risk.top_drivers
                ],
                "telemetry": telemetry,
                "timestamp": timestamp,
            },
        )
        payload = decision_payload(snapshot.coordination)
        payload["timestamp"] = timestamp
        self._publish(COORDINATOR_DECISION_TOPIC, payload)

    def publish_snapshot(self, snapshot) -> None:
        """Publish all state channels from a single ecosystem snapshot."""
        timestamp = utc_now_iso()
        for room_id, runtime in snapshot.rooms.items():
            self._publish_room_state(room_id, runtime, timestamp)
        self._publish_shared_state(snapshot, timestamp)

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()
        tick = 0
        try:
            while True:
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

                tick += 1
                time.sleep(1)
        except KeyboardInterrupt:
            self.client.publish(ECOSYSTEM_STATUS_TOPIC, "offline", retain=True)
            for room_id in ROOM_IDS:
                self.client.publish(f"{room_base(room_id)}/status", "offline", retain=True)
            self.client.loop_stop()


if __name__ == "__main__":
    Simulator().run()
