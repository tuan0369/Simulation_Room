"""Orchestrator: runs every twin in the facility and bridges them to MQTT.

One process, one MQTT client, one loop. Each room twin owns its own physics and
control; this module only sequences them, routes commands, and publishes.

Command handling lives in `commands.py` and is re-exported here so existing
imports (and Project 1's test suite) keep working unchanged.
"""
import json
import os
import random
import time

import paho.mqtt.client as mqtt

from building import load_building
# Re-exported for backwards compatibility with tests/test_publisher.py
from commands import (CMD_HVAC, CMD_MAINTENANCE, CMD_MODE,  # noqa: F401
                      CMD_OCCUPANCY, CMD_SETPOINT, CMD_TIMESCALE,
                      SETPOINT_MAX, SETPOINT_MIN, TOPIC_ROOT,
                      VALID_TIME_SCALES, handle_command, make_payload,
                      parse_command_topic, utc_now_iso)
from physics import step_occupancy
from room_twin import RoomTwin

# In Docker the broker is the `mosquitto` service, not localhost. The localhost
# default keeps host-side runs working.
BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

STATUS_TOPIC = f"{TOPIC_ROOT}/building/status"
BUILDING_SUMMARY_TOPIC = f"{TOPIC_ROOT}/building/summary"
CMD_WILDCARD = f"{TOPIC_ROOT}/+/+/cmd/#"

INTERVALS = {"temperature": 3, "humidity": 5, "occupancy": 2}
HEALTH_INTERVAL = 5
NOISE = 0.1


class Simulator:
    """Drives all six room twins from a single loop."""

    def __init__(self, seed: int | None = None):
        self.building = load_building()
        self.twins = {r.twin_id: RoomTwin(r) for r in self.building.all_rooms()}
        self.rng = random.Random(seed)
        self.time_scale = 1.0
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    # ── MQTT ───────────────────────────────────────────────────────────────

    def on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(CMD_WILDCARD)
        client.publish(STATUS_TOPIC, "online", retain=True)
        for twin in self.twins.values():
            self.publish_hvac_state(twin)
            self.publish_ac_detail(twin)
        print(f"connected; {len(self.twins)} room twins on {CMD_WILDCARD}")

    def on_message(self, client, userdata, msg):
        parsed = parse_command_topic(msg.topic)
        if parsed is None:
            return
        twin_id, kind = parsed
        twin = self.twins.get(twin_id)
        if twin is None:
            print(f"command for unknown twin {twin_id!r} ignored")
            return

        twin.handle_command(msg.topic, msg.payload)

        # Time scale is global: one room cannot run at a different clock rate
        # from the building it sits in.
        if kind == CMD_TIMESCALE:
            self.time_scale = twin.state.time_scale

        print(f"cmd {msg.topic}: {msg.payload!r} -> "
              f"hvac={twin.state.hvac_on} occ={twin.state.occupancy} "
              f"sp={twin.state.setpoint} mode={twin.state.mode}")
        self.publish_hvac_state(twin)
        self.publish_ac_detail(twin)

    # ── Publishing ─────────────────────────────────────────────────────────

    def publish_hvac_state(self, twin: RoomTwin):
        payload = twin.hvac_state_payload() | {"timestamp": utc_now_iso()}
        self.client.publish(twin.topic("hvac/state"), json.dumps(payload), retain=True)

    def publish_ac_detail(self, twin: RoomTwin):
        payload = twin.ac_detail_payload() | {"timestamp": utc_now_iso()}
        self.client.publish(twin.topic("ac/detail"), json.dumps(payload), retain=True)

    def publish_sensor(self, twin: RoomTwin, sensor: str):
        if sensor == "temperature":
            value = round(twin.state.temperature + self.rng.uniform(-NOISE, NOISE), 2)
            unit = "C"
        elif sensor == "humidity":
            value = round(twin.state.humidity + self.rng.uniform(-NOISE, NOISE), 2)
            unit = "%"
        else:
            value, unit = twin.state.occupancy, "people"
        self.client.publish(twin.topic(sensor),
                            make_payload(sensor, value, unit), retain=True)

    def publish_health(self, twin: RoomTwin):
        payload = twin.telemetry() | {
            "timestamp": utc_now_iso(),
            "failure_flags": twin.failure_flags(),
        }
        self.client.publish(twin.topic("health/telemetry"),
                            json.dumps(payload), retain=True)

    def publish_building_summary(self):
        total_kw = sum(t.electrical_load_w() for t in self.twins.values()) / 1000.0
        payload = {
            "total_load_kw": round(total_kw, 3),
            "power_budget_kw": self.building.power_budget_kw,
            "occupancy": sum(t.state.occupancy for t in self.twins.values()),
            "rooms": len(self.twins),
            "timestamp": utc_now_iso(),
        }
        self.client.publish(BUILDING_SUMMARY_TOPIC, json.dumps(payload), retain=True)

    # ── Loop ───────────────────────────────────────────────────────────────

    def neighbour_temps(self, twin: RoomTwin) -> dict[str, float]:
        """Temperatures of adjacent rooms. Corridor nodes are skipped — they
        are circulation paths for people, not thermal masses we model."""
        return {
            n: self.twins[n].state.temperature
            for n in twin.config.neighbours
            if n in self.twins
        }

    def step(self, dt: float):
        """One simulation step across the whole facility.

        Neighbour temperatures are snapshotted before any room advances, so
        every twin sees the same instant. Updating in place would make results
        depend on dictionary order.
        """
        snapshot = {tid: t.state.temperature for tid, t in self.twins.items()}
        for twin in self.twins.values():
            neighbours = {n: snapshot[n] for n in twin.config.neighbours
                          if n in snapshot}
            twin.tick(dt=dt, neighbour_temps=neighbours)

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()
        tick = 0
        try:
            while True:
                dt = self.time_scale
                self.step(dt)

                if tick % INTERVALS["occupancy"] == 0:
                    for twin in self.twins.values():
                        if twin.config.occupancy_profile == "unoccupied":
                            continue
                        twin.set_occupancy(
                            step_occupancy(twin.state, self.rng, twin.config))

                for sensor, interval in INTERVALS.items():
                    if tick % interval == 0:
                        for twin in self.twins.values():
                            self.publish_sensor(twin, sensor)

                if tick % HEALTH_INTERVAL == 0:
                    for twin in self.twins.values():
                        self.publish_health(twin)
                    self.publish_building_summary()

                if tick % 2 == 0:
                    for twin in self.twins.values():
                        if twin.state.hvac_on:
                            self.publish_hvac_state(twin)
                            self.publish_ac_detail(twin)

                if tick % 10 == 0:
                    hot = max(self.twins.values(),
                              key=lambda t: t.state.temperature)
                    print(f"t={tick} hottest={hot.twin_id} "
                          f"{hot.state.temperature:.2f}C "
                          f"load={sum(t.electrical_load_w() for t in self.twins.values())/1000:.2f}kW "
                          f"x{int(self.time_scale)}")

                tick += 1
                time.sleep(1)
        except KeyboardInterrupt:
            self.client.publish(STATUS_TOPIC, "offline", retain=True)
            self.client.loop_stop()


if __name__ == "__main__":
    Simulator().run()
