"""Simulator: publish sensor data and receive control commands (closed-loop).

Upgraded with:
- Variable-speed AC (0-100% power via PID controller)
- Configurable setpoint and time scale
- Occupancy up to 30 people
"""
import json
import os
import random
import time
from dataclasses import replace
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from physics import (OCC_MAX, OCC_MIN, RoomState, ac_output_temperature,
                     auto_hvac_decision, clamp, step_humidity, step_occupancy,
                     step_temperature)
from pid_controller import PIDController

# In Docker the broker is the `mosquitto` service, not localhost. The localhost
# default keeps host-side runs working.
BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
BASE = "twin/room1"
CMD_HVAC = f"{BASE}/cmd/hvac"
CMD_OCCUPANCY = f"{BASE}/cmd/occupancy"
CMD_SETPOINT = f"{BASE}/cmd/setpoint"
CMD_TIMESCALE = f"{BASE}/cmd/timescale"
CMD_MODE = f"{BASE}/cmd/mode"
STATUS_TOPIC = f"{BASE}/status"
HVAC_STATE_TOPIC = f"{BASE}/hvac/state"
AC_DETAIL_TOPIC = f"{BASE}/ac/detail"

INTERVALS = {"temperature": 3, "humidity": 5, "occupancy": 2}
NOISE = 0.1

# Valid time scale values
VALID_TIME_SCALES = {1, 2, 5, 10}
SETPOINT_MIN, SETPOINT_MAX = 18.0, 30.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_payload(sensor: str, value, unit: str, timestamp: str | None = None) -> str:
    return json.dumps({"sensor": sensor, "value": value, "unit": unit,
                       "timestamp": timestamp or utc_now_iso()})


def handle_command(state: RoomState, topic: str, payload: bytes) -> RoomState:
    """Apply control command to state; malformed commands are ignored."""
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
        v = data.get("value")
        if isinstance(v, int) and not isinstance(v, bool):
            return replace(state, occupancy=clamp(v, OCC_MIN, OCC_MAX))
    elif topic == CMD_SETPOINT:
        v = data.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return replace(state, setpoint=clamp(float(v), SETPOINT_MIN, SETPOINT_MAX))
    elif topic == CMD_TIMESCALE:
        v = data.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = int(v)
            if v in VALID_TIME_SCALES:
                return replace(state, time_scale=float(v))
    elif topic == CMD_MODE:
        m = data.get("mode")
        if m in ("auto", "manual"):
            return replace(state, mode=m)
    return state


class Simulator:
    def __init__(self):
        self.state = RoomState()
        self.rng = random.Random()
        self.pid = PIDController()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe([
            (CMD_HVAC, 0), (CMD_OCCUPANCY, 0),
            (CMD_SETPOINT, 0), (CMD_TIMESCALE, 0), (CMD_MODE, 0),
        ])
        client.publish(STATUS_TOPIC, "online", retain=True)
        self.publish_hvac_state()
        self.publish_ac_detail()
        print("connected, subscribed to cmd topics")

    def on_message(self, client, userdata, msg):
        before_hvac = self.state.hvac_on
        before_mode = self.state.mode
        self.state = handle_command(self.state, msg.topic, msg.payload)
        print(f"cmd {msg.topic}: {msg.payload!r} -> mode={self.state.mode}, "
              f"hvac_on={self.state.hvac_on}, occupancy={self.state.occupancy}, "
              f"setpoint={self.state.setpoint}, time_scale={self.state.time_scale}")

        # Reset PID when HVAC is turned off
        if before_hvac and not self.state.hvac_on:
            self.pid.reset()
            self.state = replace(self.state, ac_power_pct=0.0)

        if self.state.hvac_on != before_hvac or self.state.mode != before_mode:
            self.publish_hvac_state()
            self.publish_ac_detail()

    def publish_hvac_state(self):
        self.client.publish(HVAC_STATE_TOPIC,
                            json.dumps({
                                "hvac_on": self.state.hvac_on,
                                "ac_power_pct": round(self.state.ac_power_pct, 2),
                                "setpoint": self.state.setpoint,
                                "timestamp": utc_now_iso(),
                            }),
                            retain=True)

    def publish_ac_detail(self):
        ac_temp = ac_output_temperature(self.state.ac_power_pct)
        mode = self.state.mode
        self.client.publish(AC_DETAIL_TOPIC,
                            json.dumps({
                                "ac_power_pct": round(self.state.ac_power_pct, 2),
                                "ac_temp_output": round(ac_temp, 1),
                                "setpoint": self.state.setpoint,
                                "mode": mode,
                                "timestamp": utc_now_iso(),
                            }),
                            retain=True)

    def publish_sensor(self, sensor: str):
        if sensor == "temperature":
            value, unit = round(self.state.temperature + self.rng.uniform(-NOISE, NOISE), 2), "C"
        elif sensor == "humidity":
            value, unit = round(self.state.humidity + self.rng.uniform(-NOISE, NOISE), 2), "%"
        else:
            value, unit = self.state.occupancy, "people"
        self.client.publish(f"{BASE}/{sensor}", make_payload(sensor, value, unit), retain=True)
        ac_pct_display = round(self.state.ac_power_pct * 100)
        print(f"{sensor}={value}{unit} hvac={'on' if self.state.hvac_on else 'off'} "
              f"ac_power={ac_pct_display}% setpoint={self.state.setpoint}°C "
              f"x{int(self.state.time_scale)}")

    def run(self):
        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()  # cmd processing on paho's separate thread
        tick = 0
        try:
            while True:
                # Apply time_scale: each tick simulates time_scale seconds of physics
                dt = self.state.time_scale

                # Auto mode: engage when occupied & above target, off when empty
                if self.state.mode == "auto":
                    desired_on = auto_hvac_decision(
                        self.state.temperature, self.state.setpoint,
                        self.state.occupancy, self.state.hvac_on
                    )
                    if desired_on != self.state.hvac_on:
                        self.state = replace(self.state, hvac_on=desired_on)
                        if not desired_on:  # auto shut-off: stop cooling cleanly
                            self.pid.reset()
                            self.state = replace(self.state, ac_power_pct=0.0)
                        self.publish_hvac_state()
                        self.publish_ac_detail()

                # PID controller: auto-adjust AC power when HVAC is on
                if self.state.hvac_on:
                    new_pct = self.pid.compute(
                        self.state.temperature, self.state.setpoint, dt
                    )
                    self.state = replace(self.state, ac_power_pct=new_pct)

                # Advance physics by dt seconds
                self.state = replace(
                    self.state,
                    temperature=step_temperature(self.state, dt=dt),
                    humidity=step_humidity(self.state, dt=dt),
                )
                if tick % INTERVALS["occupancy"] == 0:
                    self.state = replace(self.state,
                                         occupancy=step_occupancy(self.state, self.rng))

                # Publish sensors and AC details at regular intervals
                for sensor, interval in INTERVALS.items():
                    if tick % interval == 0:
                        self.publish_sensor(sensor)

                # Publish AC detail every 2 ticks when HVAC is running
                if self.state.hvac_on and tick % 2 == 0:
                    self.publish_hvac_state()
                    self.publish_ac_detail()

                tick += 1
                time.sleep(1)
        except KeyboardInterrupt:
            self.client.publish(STATUS_TOPIC, "offline", retain=True)
            self.client.loop_stop()


if __name__ == "__main__":
    Simulator().run()
