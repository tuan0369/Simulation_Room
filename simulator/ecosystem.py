"""Two-room, shared-AHU intelligent ecosystem simulation.

Each room retains a local PID loop. The coordinator then allocates finite AHU
capacity according to an explicit occupied-comfort policy. This lets the system
show the difference between a room's requested cooling and what the shared asset
can safely deliver during a degradation scenario.
"""
import json
import random
from dataclasses import dataclass, replace
from pathlib import Path

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .ahu import (
        AHUState,
        advance_ahu,
        available_airflow,
        cooling_power_w,
        step_humidity_from_supply_air,
        step_temperature_from_supply_air,
    )
    from .coordinator import (
        POLICY_NAME,
        AllocationDecision,
        CoordinationResult,
        RoomDemand,
        coordinate,
    )
    from .fan_health import (
        FanState,
        LogisticRiskModel,
        RiskPrediction,
        default_model,
        fan_telemetry,
        step_fan_state,
    )
    from .physics import (
        OCC_MAX,
        OCC_MIN,
        RoomState,
        auto_hvac_decision,
        clamp,
        step_occupancy,
    )
    from .pid_controller import PIDController
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from ahu import (
        AHUState,
        advance_ahu,
        available_airflow,
        cooling_power_w,
        step_humidity_from_supply_air,
        step_temperature_from_supply_air,
    )
    from coordinator import (
        POLICY_NAME,
        AllocationDecision,
        CoordinationResult,
        RoomDemand,
        coordinate,
    )
    from fan_health import (
        FanState,
        LogisticRiskModel,
        RiskPrediction,
        default_model,
        fan_telemetry,
        step_fan_state,
    )
    from physics import (
        OCC_MAX,
        OCC_MIN,
        RoomState,
        auto_hvac_decision,
        clamp,
        step_occupancy,
    )
    from pid_controller import PIDController

ROOM_IDS = ("room1", "room2")
ROOM_MAX_AIRFLOW_M3_S = 0.16
SETPOINT_MIN, SETPOINT_MAX = 18.0, 30.0
VALID_TIME_SCALES = {1, 2, 5, 10}


@dataclass
class RoomRuntime:
    """Per-zone local control and state kept inside the shared ecosystem."""

    room_id: str
    state: RoomState
    pid: PIDController
    requested_airflow_m3_s: float = 0.0
    delivered_airflow_m3_s: float = 0.0
    allocation: AllocationDecision | None = None


@dataclass(frozen=True)
class EcosystemSnapshot:
    """Coherent read-only state returned after each simulated tick."""

    rooms: dict[str, RoomRuntime]
    ahu: AHUState
    fan: FanState
    coordination: CoordinationResult
    risk: RiskPrediction


class EcosystemSimulator:
    """Owns both room twins, shared AHU state, and transparent coordination."""

    def __init__(
        self,
        seed: int | None = None,
        model_path: str | Path | None = None,
    ):
        self.rng = random.Random(seed)
        self.rooms = {
            "room1": RoomRuntime(
                room_id="room1",
                state=RoomState(temperature=24.0, humidity=45.0, occupancy=8, setpoint=24.0, mode="auto"),
                pid=PIDController(),
            ),
            "room2": RoomRuntime(
                room_id="room2",
                state=RoomState(temperature=24.5, humidity=46.0, occupancy=2, setpoint=25.0, mode="auto"),
                pid=PIDController(),
            ),
        }
        self.ahu = AHUState()
        self.fan = FanState()
        self.model = LogisticRiskModel.load(model_path) if model_path is not None else default_model()
        self.last_coordination = coordinate([], available_airflow(self.ahu))
        self.last_risk = self.model.predict(
            fan_telemetry(
                self.fan,
                fan_speed_pct=self.ahu.fan_speed_pct,
                filter_clog_pct=self.ahu.filter_clog_pct,
            )
        )

    @property
    def state(self) -> RoomState:
        """Legacy façade for callers that expect the original single RoomState."""
        return self.rooms["room1"].state

    def snapshot(self) -> EcosystemSnapshot:
        return EcosystemSnapshot(
            rooms=self.rooms.copy(),
            ahu=self.ahu,
            fan=self.fan,
            coordination=self.last_coordination,
            risk=self.last_risk,
        )

    def _update_room(self, room_id: str, **changes) -> bool:
        room = self.rooms[room_id]
        updated = replace(room.state, **changes)
        changed = updated != room.state
        room.state = updated
        return changed

    def apply_room_command(self, room_id: str, command: str, data: dict) -> bool:
        """Validate and apply a room command without touching MQTT details."""
        if room_id not in self.rooms:
            return False
        room = self.rooms[room_id]
        if command == "hvac":
            value = data.get("command")
            if value not in ("on", "off"):
                return False
            was_on = room.state.hvac_on
            changed = self._update_room(room_id, hvac_on=(value == "on"))
            if was_on and value == "off":
                room.pid.reset()
                self._update_room(room_id, ac_power_pct=0.0)
            return changed
        if command == "occupancy":
            value = data.get("value")
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            return self._update_room(room_id, occupancy=clamp(value, OCC_MIN, OCC_MAX))
        if command == "setpoint":
            value = data.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            return self._update_room(
                room_id, setpoint=clamp(float(value), SETPOINT_MIN, SETPOINT_MAX)
            )
        if command == "mode":
            value = data.get("mode")
            if value not in ("auto", "manual"):
                return False
            return self._update_room(room_id, mode=value)
        if command == "timescale":
            value = data.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            value = int(value)
            if value not in VALID_TIME_SCALES:
                return False
            for runtime in self.rooms.values():
                runtime.state = replace(runtime.state, time_scale=float(value))
            return True
        return False

    def apply_ahu_command(self, command: str, data: dict) -> bool:
        """Apply explicit demo/degradation commands to the shared AHU."""
        value = data.get("value")
        if command not in ("filter_clog", "fan_wear"):
            return False
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        value = clamp(float(value), 0.0, 1.0)
        if command == "filter_clog":
            self.ahu = replace(self.ahu, filter_clog_pct=value)
        else:
            self.ahu = replace(self.ahu, fan_wear_pct=value)
            self.fan = replace(self.fan, wear_pct=value)
        return True

    def apply_command(self, topic: str, payload: bytes) -> bool:
        """Route an MQTT-like topic/payload pair to its validated domain command."""
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(data, dict):
            return False
        parts = topic.split("/")
        if len(parts) == 4 and parts[0] == "twin" and parts[1] in self.rooms and parts[2] == "cmd":
            return self.apply_room_command(parts[1], parts[3], data)
        if len(parts) == 4 and parts[:3] == ["twin", "ahu", "cmd"]:
            return self.apply_ahu_command(parts[3], data)
        return False

    def _set_auto_mode(self, room: RoomRuntime) -> None:
        if room.state.mode != "auto":
            return
        desired_on = auto_hvac_decision(
            room.state.temperature,
            room.state.setpoint,
            room.state.occupancy,
            room.state.hvac_on,
        )
        if desired_on != room.state.hvac_on:
            room.state = replace(room.state, hvac_on=desired_on)
            if not desired_on:
                room.pid.reset()
                room.state = replace(room.state, ac_power_pct=0.0)

    def _requests(self, dt: float) -> list[RoomDemand]:
        demands: list[RoomDemand] = []
        for room in self.rooms.values():
            self._set_auto_mode(room)
            if room.state.hvac_on:
                pid_output = room.pid.compute(room.state.temperature, room.state.setpoint, dt)
                room.state = replace(room.state, ac_power_pct=pid_output)
                room.requested_airflow_m3_s = ROOM_MAX_AIRFLOW_M3_S * pid_output
            else:
                room.requested_airflow_m3_s = 0.0
                room.delivered_airflow_m3_s = 0.0
            demands.append(
                RoomDemand(
                    room_id=room.room_id,
                    requested_airflow_m3_s=room.requested_airflow_m3_s,
                    occupancy=room.state.occupancy,
                    temperature_c=room.state.temperature,
                    setpoint_c=room.state.setpoint,
                    enabled=room.state.hvac_on,
                )
            )
        return demands

    def tick(self, dt: float | None = None, *, advance_occupancy: bool = True) -> EcosystemSnapshot:
        """Advance all twins one simulated step and return a coherent snapshot."""
        actual_dt = float(dt if dt is not None else self.rooms["room1"].state.time_scale)
        actual_dt = max(0.0, actual_dt)
        demands = self._requests(actual_dt)
        coordination = coordinate(demands, available_airflow(self.ahu))
        decisions = {decision.room_id: decision for decision in coordination.decisions}
        total_airflow = 0.0
        total_cooling = 0.0

        for room_id, room in self.rooms.items():
            decision = decisions[room_id]
            room.allocation = decision
            room.delivered_airflow_m3_s = decision.granted_airflow_m3_s
            total_airflow += room.delivered_airflow_m3_s
            total_cooling += cooling_power_w(
                room.state.temperature,
                self.ahu.supply_air_temp_c,
                room.delivered_airflow_m3_s,
            )
            room.state = replace(
                room.state,
                temperature=step_temperature_from_supply_air(
                    room.state.temperature,
                    room.state.occupancy,
                    room.delivered_airflow_m3_s,
                    self.ahu.supply_air_temp_c,
                    actual_dt,
                ),
                humidity=step_humidity_from_supply_air(
                    room.state.humidity,
                    room.state.occupancy,
                    room.delivered_airflow_m3_s,
                    actual_dt,
                ),
            )
            if advance_occupancy:
                room.state = replace(room.state, occupancy=step_occupancy(room.state, self.rng))

        self.ahu = advance_ahu(self.ahu, total_airflow, total_cooling, actual_dt)
        self.fan = step_fan_state(
            self.fan,
            fan_speed_pct=self.ahu.fan_speed_pct,
            filter_clog_pct=self.ahu.filter_clog_pct,
            dt=actual_dt,
        )
        # Keep direct degradation commands and naturally evolving health aligned.
        self.ahu = replace(self.ahu, fan_wear_pct=max(self.ahu.fan_wear_pct, self.fan.wear_pct))
        self.last_coordination = coordination
        self.last_risk = self.model.predict(
            fan_telemetry(
                self.fan,
                fan_speed_pct=self.ahu.fan_speed_pct,
                filter_clog_pct=self.ahu.filter_clog_pct,
            )
        )
        return self.snapshot()


def decision_payload(result: CoordinationResult) -> dict:
    """Convert a coordination result into the shared MQTT payload contract."""
    return {
        "policy": POLICY_NAME,
        "available_airflow_m3_s": round(result.available_airflow_m3_s, 4),
        "requested_airflow_m3_s": round(result.requested_airflow_m3_s, 4),
        "constrained": result.constrained,
        "rooms": [
            {
                "room_id": decision.room_id,
                "requested_airflow_m3_s": round(decision.requested_airflow_m3_s, 4),
                "granted_airflow_m3_s": round(decision.granted_airflow_m3_s, 4),
                "priority_score": list(decision.priority_score[:3]),
                "reason_codes": list(decision.reason_codes),
            }
            for decision in result.decisions
        ],
    }
