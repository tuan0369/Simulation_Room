"""Orchestrator: runs every twin in the facility and bridges them to MQTT.

One process, one MQTT client, one loop. Each room twin owns its own physics and
control; this module only sequences them, routes commands, and publishes.

Command handling lives in `commands.py` and is re-exported here so existing
imports (and Project 1's test suite) keep working unchanged.
"""
import json
import math
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
from building_twin import BuildingTwin
from floor_twin import FloorTwin
from ml_inference import SAMPLE_INTERVAL_S, RiskScorer
from occupancy_twin import OccupancyTwin
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
OCCUPANCY_TOPIC = f"{TOPIC_ROOT}/building/occupancy"
ADVISORY_TOPIC = f"{TOPIC_ROOT}/building/advisory"
NOISE = 0.1

# Tiered loop rates: rooms react fast, supervisors coordinate slowly. The gap
# is deliberate — it is what keeps supervision advisory rather than a hidden
# outer control loop fighting each room's PID.
FLOOR_INTERVAL = 10
BUILDING_INTERVAL = 30
RISK_INTERVAL = 30

# The ML features need a 6-hour trailing window (72 samples at 5-minute
# spacing). Waiting for that in real time would leave the dashboard blank for
# 36 minutes even at x10, so the simulator advances the physics headlessly at
# startup to give every unit a plausible operating history. This is warm-up,
# not fabrication: the history is produced by the same physics as the live run.
WARMUP_HOURS = 8.0

# Demos should not start at midnight in an empty building.
START_HOUR = 8.5


class Simulator:
    """Drives all six room twins from a single loop."""

    def __init__(self, seed: int | None = None, quiet: bool = False):
        self.building = load_building()
        self.twins = {r.twin_id: RoomTwin(r) for r in self.building.all_rooms()}
        self.rng = random.Random(seed)
        self.occupancy = OccupancyTwin(self.building, rng=random.Random(seed))
        self.floors = {f.floor_id: FloorTwin(f) for f in self.building.floors}
        self.coordinator = BuildingTwin(self.building)
        self.budgets = {f.floor_id: f.power_budget_kw for f in self.building.floors}
        self.active_nudges: dict[str, float] = {}
        self.scorer = RiskScorer(quiet=quiet)
        self.latest_risk: dict[str, dict] = {}
        self.sim_time_s = START_HOUR * 3600.0
        self.manual_occupancy: set[str] = set()
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

        # An explicit occupancy override pins that room: the occupancy twin
        # stops driving it, otherwise the schedule would immediately undo what
        # the operator just asked for. Demos rely on the override sticking.
        if kind == CMD_OCCUPANCY:
            self.manual_occupancy.add(twin_id)
            self.occupancy.occupancy[twin_id] = twin.state.occupancy

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
            "sim_hour": round((self.sim_time_s / 3600.0) % 24.0, 2),
            "timestamp": utc_now_iso(),
        }
        self.client.publish(BUILDING_SUMMARY_TOPIC, json.dumps(payload), retain=True)

    def publish_occupancy_flow(self):
        """People per node, corridors included — makes the conservation
        property visible instead of merely asserted in tests."""
        payload = {
            "nodes": dict(self.occupancy.occupancy),
            "total_in_building": self.occupancy.total_in_building,
            "entrance_flow": self.occupancy.last_entrance_flow,
            "sim_hour": round((self.sim_time_s / 3600.0) % 24.0, 2),
            "timestamp": utc_now_iso(),
        }
        self.client.publish(OCCUPANCY_TOPIC, json.dumps(payload), retain=True)

    # ── Supervision ────────────────────────────────────────────────────────

    def run_floor_supervision(self):
        """Aggregate each floor and publish any recommended nudges.

        Nudges are published as advice on the floor's own topic. Rooms are not
        mutated here — applying a nudge is the room's decision, which is what
        keeps a dead supervisor from stopping anyone's cooling.
        """
        summaries = {}
        self.active_nudges = {}
        for fid, floor in self.floors.items():
            summary = floor.aggregate(self.twins)
            nudges = floor.arbitrate(self.twins, self.budgets.get(
                fid, floor.config.power_budget_kw))
            self.active_nudges.update(nudges)
            # Offer the advice; each room clamps it to its own safety limit.
            for tid in floor._mine(self.twins):
                if tid in nudges:
                    self.twins[tid].accept_advisory(nudges[tid])
                else:
                    self.twins[tid].clear_advisory()
            summary |= {
                "allocated_kw": round(self.budgets.get(fid, 0.0), 3),
                "nudges": nudges,
                "timestamp": utc_now_iso(),
            }
            summaries[fid] = summary
            self.client.publish(floor.topic("summary"),
                                json.dumps(summary), retain=True)
        return summaries

    def run_building_coordination(self, summaries):
        self.budgets = self.coordinator.allocate_budgets(summaries)
        for fid, kw in self.budgets.items():
            self.client.publish(f"{TOPIC_ROOT}/{fid}/cmd/power_budget",
                                json.dumps({"budget_kw": kw}))

        summary = self.coordinator.summary(summaries) | {
            "allocations_kw": self.budgets,
            "timestamp": utc_now_iso(),
        }
        self.client.publish(self.coordinator.topic("summary"),
                            json.dumps(summary), retain=True)

        # Risk scores arrive from ml_inference in Task 8; until then this is
        # empty and the coordinator simply raises no work orders.
        for order in self.coordinator.advisories(self.risk_scores()):
            self.client.publish(ADVISORY_TOPIC,
                                json.dumps(order | {"timestamp": utc_now_iso()}))
            print(f"WORK ORDER {order['twin_id']}: {order['action']} "
                  f"(p={order['failure_prob']}, {order['top_factor']})")

    def risk_scores(self) -> dict:
        """Latest scores, consumed by the building twin into work orders."""
        return self.latest_risk

    def warm_up(self, hours: float = WARMUP_HOURS):
        """Advance the physics headlessly so the scorer has a full window.

        No MQTT, no sleeping — this runs in a couple of seconds. It also leaves
        the building in a realistic mid-morning state instead of every room
        sitting at exactly 24.0 C.
        """
        steps = int(hours * 3600 / 1.0)
        for _ in range(steps):
            self.step(dt=1.0)
        ready = sum(1 for tid in self.twins if self.scorer.ready(tid))
        return ready

    def publish_risk(self):
        """Publish a risk score per room; honest placeholder when not scorable."""
        for tid in self.twins:
            result = self.scorer.score(tid)
            if result is None:
                payload = self.scorer.warming_up_payload(tid)
                self.latest_risk.pop(tid, None)
            else:
                payload = result
                self.latest_risk[tid] = result
            self.client.publish(f"{TOPIC_ROOT}/{tid}/health/risk",
                                json.dumps(payload | {"timestamp": utc_now_iso()}),
                                retain=True)

    # ── Loop ───────────────────────────────────────────────────────────────

    def neighbour_temps(self, twin: RoomTwin) -> dict[str, float]:
        """Temperatures of adjacent rooms. Corridor nodes are skipped — they
        are circulation paths for people, not thermal masses we model."""
        return {
            n: self.twins[n].state.temperature
            for n in twin.config.neighbours
            if n in self.twins
        }

    def outdoor_temp(self) -> float:
        """Diurnal outdoor temperature, peaking mid-afternoon."""
        p = self.building.outdoor_profile
        hour = (self.sim_time_s / 3600.0) % 24.0
        peak = p.get("peak_hour", 15)
        return p["base_temp_c"] + p["diurnal_amplitude_c"] * math.cos(
            2.0 * math.pi * (hour - peak) / 24.0)

    def step(self, dt: float):
        """One simulation step across the whole facility.

        This is the single canonical stepper: the live orchestrator and the
        offline dataset generator both drive it, so training data cannot come
        from a different physics path than production telemetry.

        Neighbour temperatures are snapshotted before any room advances, so
        every twin sees the same instant. Updating in place would make results
        depend on dictionary order.
        """
        self.sim_time_s += dt
        room_occupancy = self.occupancy.step(self.sim_time_s, dt)
        for tid, count in room_occupancy.items():
            if tid not in self.manual_occupancy:
                self.twins[tid].set_occupancy(count)

        outdoor = self.outdoor_temp()
        snapshot = {tid: t.state.temperature for tid, t in self.twins.items()}
        for twin in self.twins.values():
            neighbours = {n: snapshot[n] for n in twin.config.neighbours
                          if n in snapshot}
            twin.tick(dt=dt, neighbour_temps=neighbours, outdoor_temp=outdoor)

        # Feed the scorer on its own 5-minute cadence, matching how the
        # training data was sampled.
        for tid, twin in self.twins.items():
            self.scorer.observe(tid, twin.telemetry(), self.sim_time_s)

    def run(self):
        if self.scorer.available:
            print(f"warming up {WARMUP_HOURS:.0f} simulated hours "
                  f"so risk scores are available immediately...")
            ready = self.warm_up()
            print(f"  {ready}/{len(self.twins)} rooms scorable")

        self.client.connect(BROKER_HOST, BROKER_PORT)
        self.client.loop_start()
        tick = 0
        try:
            while True:
                dt = self.time_scale
                self.step(dt)

                for sensor, interval in INTERVALS.items():
                    if tick % interval == 0:
                        for twin in self.twins.values():
                            self.publish_sensor(twin, sensor)

                if tick % HEALTH_INTERVAL == 0:
                    for twin in self.twins.values():
                        self.publish_health(twin)
                    self.publish_building_summary()
                    self.publish_occupancy_flow()

                if tick % RISK_INTERVAL == 0:
                    self.publish_risk()

                if tick % FLOOR_INTERVAL == 0:
                    self.floor_summaries = self.run_floor_supervision()

                if tick % BUILDING_INTERVAL == 0:
                    self.run_building_coordination(
                        getattr(self, "floor_summaries", {}))

                if tick % 2 == 0:
                    for twin in self.twins.values():
                        if twin.state.hvac_on:
                            self.publish_hvac_state(twin)
                            self.publish_ac_detail(twin)

                if tick % 10 == 0:
                    hot = max(self.twins.values(),
                              key=lambda t: t.state.temperature)
                    nudged = f" nudges={len(self.active_nudges)}" if self.active_nudges else ""
                    print(f"t={tick} {(self.sim_time_s/3600)%24:05.2f}h "
                          f"people={self.occupancy.total_in_building} "
                          f"hottest={hot.twin_id} {hot.state.temperature:.2f}C "
                          f"load={sum(t.electrical_load_w() for t in self.twins.values())/1000:.2f}kW "
                          f"x{int(self.time_scale)}{nudged}")

                tick += 1
                time.sleep(1)
        except KeyboardInterrupt:
            self.client.publish(STATUS_TOPIC, "offline", retain=True)
            self.client.loop_stop()


if __name__ == "__main__":
    Simulator().run()
