"""One autonomous room twin: state + local control + equipment health.

Each room owns its physics, its PID loop and its HVAC condition, and keeps
running correctly with no floor or building twin present. That autonomy is the
whole federated argument: supervisors advise, rooms decide. A centralized
design would put all six control loops in one process, where a single crash
stops cooling everywhere.
"""
from __future__ import annotations

from dataclasses import replace

from building import RoomConfig
from commands import (CMD_MAINTENANCE, TOPIC_ROOT, handle_command,
                      parse_maintenance)
from hvac_health import HVACHealth, apply_maintenance, failure_flags, step_health
from physics import (T_OUTDOOR, RoomState, ac_output_temperature,
                     auto_hvac_decision, step_humidity, step_temperature)
from pid_controller import PIDController

# The ML feature contract. `telemetry()` must supply exactly these keys — a
# test asserts it, so the training pipeline (ml/features.py) and the live
# scorer cannot silently drift apart from the simulator.
TELEMETRY_FIELDS = (
    "twin_id", "floor", "room_id", "room_profile",
    "occupancy", "room_temp", "humidity", "setpoint", "outdoor_temp",
    "hvac_on", "ac_power_pct",
    "motor_temp", "fan_rpm", "vibration_mm_s", "filter_clog",
    "power_draw_w", "runtime_hours", "torque_nm",
    "motor_room_delta",
)

# The most a room will let a supervisor push its setpoint. Enforced HERE, by
# the room, not by the floor twin that sends the advice — a supervisor bug or a
# spoofed advisory must not be able to make a room unsafe.
ADVISORY_LIMIT_C = 1.5

# Unoccupied setback ceiling. An empty room may drift up to here, but no
# further — standing equipment load would otherwise cook it overnight.
UNOCCUPIED_SETBACK_C = 28.0

# Defaults for a freshly built twin. These are NOT arbitrary: the model was
# trained on telemetry generated with auto mode and this setpoint, so a live
# system starting in manual-off would be a distribution shift — and would also
# cook every room to the 40 °C clamp, since equipment load runs regardless.
# Project 1 defaulted to manual because its demo was "watch one room overheat,
# then intervene"; a six-room building with predictive maintenance wants the
# plant running. Operators can still switch any room to manual.
DEFAULT_MODE = "auto"
DEFAULT_SETPOINT_C = 23.0


class RoomTwin:
    """A single room's digital twin."""

    def __init__(self, config: RoomConfig, state: RoomState | None = None):
        self.config = config
        self.pid = PIDController()
        self.health = HVACHealth.for_room(config)
        self.advisory_offset = 0.0
        # Remembered from the last tick so telemetry() is self-contained. The
        # ML feature set needs outdoor_temp, and having the caller attach it
        # separately let the training and live paths diverge.
        self.outdoor_temp = T_OUTDOOR
        if state is not None:
            self.state = state
        else:
            self.state = RoomState(
                temperature=24.0,
                humidity=45.0,
                occupancy=0 if config.occupancy_profile == "unoccupied" else 2,
                hvac_on=config.always_on,
                mode=DEFAULT_MODE,
                setpoint=DEFAULT_SETPOINT_C,
            )

    # ── Topics ─────────────────────────────────────────────────────────────

    @property
    def twin_id(self) -> str:
        return self.config.twin_id

    def topic(self, suffix: str) -> str:
        return f"{TOPIC_ROOT}/{self.config.twin_id}/{suffix}"

    # ── Supervision ────────────────────────────────────────────────────────

    @property
    def effective_setpoint(self) -> float:
        """The target this room is actually controlling to, including any
        advisory nudge it has chosen to accept."""
        return self.state.setpoint + self.advisory_offset

    def accept_advisory(self, delta_c: float) -> None:
        """Accept a supervisor's setpoint nudge, clamped to this room's own
        limit. A room only ever runs WARMER on advice, never colder, so load
        shedding cannot be inverted into a demand spike."""
        try:
            delta = float(delta_c)
        except (TypeError, ValueError):
            return
        self.advisory_offset = max(0.0, min(delta, ADVISORY_LIMIT_C))

    def clear_advisory(self) -> None:
        self.advisory_offset = 0.0

    # ── Simulation ─────────────────────────────────────────────────────────

    def tick(self, dt: float, neighbour_temps: dict[str, float] | None = None,
             outdoor_temp: float | None = None) -> None:
        """Advance this room by `dt` simulated seconds.

        `neighbour_temps` maps adjacent twin_id -> temperature. Absent or empty
        means no coupling, which reproduces Project 1's isolated-room physics.
        """
        if outdoor_temp is not None:
            self.outdoor_temp = outdoor_temp
        target = self.effective_setpoint

        if self.state.mode == "auto":
            desired = auto_hvac_decision(
                self.state.temperature, target,
                self.state.occupancy, self.state.hvac_on,
                always_on=self.config.always_on,
                setback_c=UNOCCUPIED_SETBACK_C,
            )
            if desired != self.state.hvac_on:
                self.state = replace(self.state, hvac_on=desired)
                if not desired:
                    self._stop_cooling()

        if self.state.hvac_on:
            self.state = replace(self.state, ac_power_pct=self.pid.compute(
                self.state.temperature, target, dt))
        elif self.state.ac_power_pct:
            self.state = replace(self.state, ac_power_pct=0.0)

        self.state = replace(
            self.state,
            temperature=step_temperature(
                self.state, dt=dt, config=self.config,
                neighbour_temps=neighbour_temps, outdoor_temp=outdoor_temp),
            humidity=step_humidity(self.state, dt=dt),
        )

        # Equipment only degrades while it is actually running.
        duty = self.state.ac_power_pct if self.state.hvac_on else 0.0
        self.health = step_health(
            self.health, ac_power_pct=duty, occupancy=self.state.occupancy,
            room_temp=self.state.temperature, dt=dt)

    def _stop_cooling(self) -> None:
        self.pid.reset()
        self.state = replace(self.state, ac_power_pct=0.0)

    def set_occupancy(self, value: int) -> None:
        """Used by the occupancy twin, which owns people flow building-wide."""
        self.state = replace(
            self.state, occupancy=max(0, min(int(value), self.config.max_occupancy)))

    # ── Commands ───────────────────────────────────────────────────────────

    def handle_command(self, topic: str, payload: bytes) -> None:
        """Apply a command addressed to this room. Unknown or malformed
        payloads leave the twin untouched."""
        if topic.endswith(CMD_MAINTENANCE):
            action = parse_maintenance(payload)
            if action:
                self.health = apply_maintenance(self.health, action)
            return

        before_on = self.state.hvac_on
        self.state = handle_command(self.state, topic, payload, config=self.config)
        if before_on and not self.state.hvac_on:
            self._stop_cooling()

    # ── Reporting ──────────────────────────────────────────────────────────

    def telemetry(self) -> dict:
        """One flat record — the row shape the ML pipeline trains on."""
        return {
            "twin_id": self.config.twin_id,
            "floor": self.config.floor,
            "room_id": self.config.room_id,
            "room_profile": self.config.occupancy_profile,
            "occupancy": self.state.occupancy,
            "room_temp": round(self.state.temperature, 3),
            "humidity": round(self.state.humidity, 3),
            "setpoint": self.state.setpoint,
            "outdoor_temp": round(self.outdoor_temp, 3),
            "hvac_on": self.state.hvac_on,
            "ac_power_pct": round(self.state.ac_power_pct, 4),
            "motor_temp": round(self.health.motor_temp, 3),
            "fan_rpm": round(self.health.fan_rpm, 1),
            "vibration_mm_s": round(self.health.vibration_mm_s, 4),
            "filter_clog": round(self.health.filter_clog, 5),
            "power_draw_w": round(self.health.power_draw_w, 2),
            "runtime_hours": round(self.health.runtime_hours, 4),
            "torque_nm": round(self.health.torque_nm, 4),
            # The HDF driver: without a gradient the motor cannot shed heat.
            "motor_room_delta": round(
                self.health.motor_temp - self.state.temperature, 3),
        }

    def failure_flags(self) -> dict[str, bool]:
        duty = self.state.ac_power_pct if self.state.hvac_on else 0.0
        return failure_flags(self.health, duty)

    def electrical_load_w(self) -> float:
        """Cooling draw plus fan draw — what the floor twin budgets against."""
        if not self.state.hvac_on:
            return 0.0
        return (self.config.hvac_max_power_w * self.state.ac_power_pct
                + self.health.power_draw_w)

    def hvac_state_payload(self) -> dict:
        return {
            "hvac_on": self.state.hvac_on,
            "ac_power_pct": round(self.state.ac_power_pct, 2),
            "setpoint": self.state.setpoint,
            "mode": self.state.mode,
        }

    def ac_detail_payload(self) -> dict:
        return {
            "ac_power_pct": round(self.state.ac_power_pct, 2),
            "ac_temp_output": round(ac_output_temperature(self.state.ac_power_pct), 1),
            "setpoint": self.state.setpoint,
            "mode": self.state.mode,
        }
