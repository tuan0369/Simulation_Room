"""Two-room, shared-AHU intelligent ecosystem simulation.

Each room retains a local PID loop. The coordinator then allocates finite AHU
capacity according to an explicit occupied-comfort policy. This lets the system
show the difference between a room's requested cooling and what the shared asset
can safely deliver during a degradation scenario.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
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
    from .contracts import (
        CommandOutcome,
        decode_command_payload,
        exact_integer_choice,
        finite_number,
        rejected_outcome,
    )
    from .coordinator import (
        POLICY_NAME,
        AllocationDecision,
        CoordinationResult,
        RoomDemand,
        coordinate,
        update_comfort_debt,
    )
    from .fan_health import (
        FanState,
        LogisticRiskModel,
        RiskPrediction,
        default_model,
        fan_telemetry,
        step_fan_state,
    )
    from .intelligence import (
        EcosystemDemandForecast,
        RecommendedAction,
        forecast_ecosystem_demand,
        generate_recommendations,
    )
    from .knowledge_base import (
        ActionEvaluationSession,
        KnowledgeRepository,
        LearnedKnowledgeEntry,
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
    from contracts import (
        CommandOutcome,
        decode_command_payload,
        exact_integer_choice,
        finite_number,
        rejected_outcome,
    )
    from coordinator import (
        POLICY_NAME,
        AllocationDecision,
        CoordinationResult,
        RoomDemand,
        coordinate,
        update_comfort_debt,
    )
    from fan_health import (
        FanState,
        LogisticRiskModel,
        RiskPrediction,
        default_model,
        fan_telemetry,
        step_fan_state,
    )
    from intelligence import (
        EcosystemDemandForecast,
        RecommendedAction,
        forecast_ecosystem_demand,
        generate_recommendations,
    )
    from knowledge_base import (
        ActionEvaluationSession,
        KnowledgeRepository,
        LearnedKnowledgeEntry,
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
BASELINE_SCENARIO = "baseline"
STRESS_SCENARIO = "shared_capacity_stress"
LECTURE_SURGE_SCENARIO = "lecture_surge"
EXAM_SESSION_SCENARIO = "exam_session"
BALANCED_WORKSHOP_SCENARIO = "balanced_workshop"
NIGHT_OFFHOURS_SCENARIO = "night_offhours"
SCENARIO_NAMES = (
    BASELINE_SCENARIO,
    STRESS_SCENARIO,
    LECTURE_SURGE_SCENARIO,
    EXAM_SESSION_SCENARIO,
    BALANCED_WORKSHOP_SCENARIO,
    NIGHT_OFFHOURS_SCENARIO,
)


@dataclass
class RoomRuntime:
    """Per-zone local control and state kept inside the shared ecosystem."""

    room_id: str
    state: RoomState
    pid: PIDController
    requested_airflow_m3_s: float = 0.0
    delivered_airflow_m3_s: float = 0.0
    comfort_debt_c_s: float = 0.0
    limited_service_s: float = 0.0
    thermal_cooling_power_w: float = 0.0
    allocation: AllocationDecision | None = None


@dataclass(frozen=True)
class EcosystemSnapshot:
    """Coherent read-only state returned after each simulated tick."""

    rooms: dict[str, RoomRuntime]
    ahu: AHUState
    fan: FanState
    coordination: CoordinationResult
    risk: RiskPrediction
    demand_forecast: EcosystemDemandForecast | None = None
    recommendations: tuple[RecommendedAction, ...] = ()
    active_evaluation: dict | None = None
    auto_action_enabled: bool = False


class EcosystemSimulator:
    """Owns 4-zone room twins, shared AHU state, and transparent coordination."""

    def __init__(
        self,
        seed: int | None = None,
        model_path: str | Path | None = None,
    ):
        self.rng = random.Random(seed)
        self._initial_rng_state = self.rng.getstate()
        self.model = LogisticRiskModel.load(model_path) if model_path is not None else default_model()
        self.knowledge_repo = KnowledgeRepository()
        self.active_evaluation_session: ActionEvaluationSession | None = None
        self.auto_action_enabled: bool = False
        self.active_scenario = BASELINE_SCENARIO
        self.guided_scenario_active = False
        self.operating_mode = "running"
        self.scenario_revision = 0
        self.last_command_id: str | None = None
        self.last_demand_forecast: EcosystemDemandForecast | None = None
        self.last_recommendations: tuple[RecommendedAction, ...] = ()
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        """Restore the complete deterministic 4-room classroom-demo baseline."""
        self.rng.setstate(self._initial_rng_state)
        self.rooms = {
            "room1": RoomRuntime(
                room_id="room1",
                state=RoomState(
                    temperature=24.0,
                    humidity=45.0,
                    occupancy=8,
                    setpoint=24.0,
                    time_scale=1.0,
                    mode="auto",
                ),
                pid=PIDController(),
            ),
            "room2": RoomRuntime(
                room_id="room2",
                state=RoomState(
                    temperature=24.5,
                    humidity=46.0,
                    occupancy=2,
                    setpoint=23.5,
                    time_scale=1.0,
                    mode="auto",
                ),
                pid=PIDController(),
            ),
            "room3": RoomRuntime(
                room_id="room3",
                state=RoomState(
                    temperature=24.0,
                    humidity=45.0,
                    occupancy=6,
                    setpoint=24.0,
                    time_scale=1.0,
                    mode="auto",
                ),
                pid=PIDController(),
            ),
            "room4": RoomRuntime(
                room_id="room4",
                state=RoomState(
                    temperature=23.8,
                    humidity=44.0,
                    occupancy=4,
                    setpoint=23.0,
                    time_scale=1.0,
                    mode="auto",
                ),
                pid=PIDController(),
            ),
        }
        self.ahu = AHUState()
        self.fan = FanState()
        self.last_coordination = coordinate([], available_airflow(self.ahu))
        self.last_risk = self.model.predict(
            fan_telemetry(
                self.fan,
                fan_speed_pct=self.ahu.fan_speed_pct,
                filter_clog_pct=self.ahu.filter_clog_pct,
            )
        )
        self._update_intelligence()

    def _update_intelligence(self) -> None:
        """Refresh predictive demand forecasts and targeted action recommendations."""
        rooms_dict = {
            r_id: {
                "temperature": r.state.temperature,
                "setpoint": r.state.setpoint,
                "occupancy": r.state.occupancy,
                "delivered_airflow_m3_s": r.delivered_airflow_m3_s,
            }
            for r_id, r in self.rooms.items()
        }
        self.last_demand_forecast = forecast_ecosystem_demand(
            rooms_dict, available_airflow(self.ahu), self.ahu.supply_air_temp_c
        )
        fan_health_dict = {
            "failure_risk": self.last_risk.failure_risk,
            "risk_band": self.last_risk.risk_band,
            "wear_pct": self.fan.wear_pct,
            "vibration_mm_s": self.fan.vibration_mm_s,
            "bearing_temp_c": self.fan.bearing_temp_c,
        }
        ahu_dict = {
            "filter_clog_pct": self.ahu.filter_clog_pct,
            "fan_speed_pct": self.ahu.fan_speed_pct,
        }
        self.last_recommendations = tuple(
            generate_recommendations(
                self.last_demand_forecast,
                fan_health_dict,
                ahu_dict,
                rooms_dict,
            )
        )

    def apply_scenario(self, name: str, command_id: str | None = None) -> bool:
        """Atomically apply one of the deterministic guided-demo presets for 4 rooms."""
        if name not in SCENARIO_NAMES:
            return False
        self._reset_runtime()
        self.active_scenario = name
        self.guided_scenario_active = name in (
            STRESS_SCENARIO,
            LECTURE_SURGE_SCENARIO,
            EXAM_SESSION_SCENARIO,
            BALANCED_WORKSHOP_SCENARIO,
            NIGHT_OFFHOURS_SCENARIO,
        )
        self.operating_mode = "running"
        self.scenario_revision += 1
        self.last_command_id = command_id

        if name == STRESS_SCENARIO:
            stress_states = {
                "room1": RoomState(
                    temperature=27.0,
                    humidity=52.0,
                    occupancy=24,
                    hvac_on=True,
                    setpoint=20.0,
                    time_scale=1.0,
                    mode="auto",
                ),
                "room2": RoomState(
                    temperature=26.0,
                    humidity=49.0,
                    occupancy=5,
                    hvac_on=True,
                    setpoint=20.0,
                    time_scale=1.0,
                    mode="auto",
                ),
            }
            for room_id, state in stress_states.items():
                self.rooms[room_id].state = state
            self.ahu = replace(self.ahu, filter_clog_pct=0.85, fan_wear_pct=0.75)
            self.fan = replace(self.fan, wear_pct=0.75)
        elif name == LECTURE_SURGE_SCENARIO:
            self.rooms["room1"].state = RoomState(
                temperature=25.5,
                humidity=50.0,
                occupancy=28,
                hvac_on=True,
                setpoint=23.0,
                time_scale=1.0,
                mode="auto",
            )
            self.rooms["room2"].state = RoomState(
                temperature=24.0,
                humidity=45.0,
                occupancy=4,
                hvac_on=True,
                setpoint=23.5,
                time_scale=1.0,
                mode="auto",
            )
        elif name == EXAM_SESSION_SCENARIO:
            self.rooms["room1"].state = RoomState(
                temperature=25.0,
                humidity=50.0,
                occupancy=25,
                hvac_on=True,
                setpoint=22.0,
                time_scale=1.0,
                mode="auto",
            )
            self.rooms["room2"].state = RoomState(
                temperature=25.0,
                humidity=50.0,
                occupancy=25,
                hvac_on=True,
                setpoint=22.0,
                time_scale=1.0,
                mode="auto",
            )
        elif name == BALANCED_WORKSHOP_SCENARIO:
            for r_id in ROOM_IDS:
                self.rooms[r_id].state = RoomState(
                    temperature=24.5,
                    humidity=47.0,
                    occupancy=15,
                    hvac_on=True,
                    setpoint=23.5,
                    time_scale=1.0,
                    mode="auto",
                )
        elif name == NIGHT_OFFHOURS_SCENARIO:
            for r_id in ROOM_IDS:
                self.rooms[r_id].state = RoomState(
                    temperature=26.0,
                    humidity=40.0,
                    occupancy=0,
                    hvac_on=False,
                    setpoint=26.0,
                    time_scale=1.0,
                    mode="auto",
                )
        self._update_intelligence()
        return True

    def apply_action(
        self,
        action_type: str,
        target: str,
        parameters: dict | None = None,
        source: str = "operator",
    ) -> tuple[bool, str]:
        """Execute an adaptive mitigation action and launch an automated evaluation session."""
        params = parameters or {}
        accepted = False
        reason = "unknown_action"

        if action_type == "PREEMPTIVE_PRECOOL":
            target_room = target if target in self.rooms else "room1"
            offset = finite_number(params.get("temp_offset_c")) or -1.5
            new_sp = clamp(self.rooms[target_room].state.setpoint + offset, SETPOINT_MIN, SETPOINT_MAX)
            self._update_room(target_room, setpoint=new_sp, hvac_on=True)
            accepted = True
            reason = f"precooled_{target_room}_to_{new_sp:.1f}C"
        elif action_type == "PROACTIVE_FAN_DERATE":
            cap = finite_number(params.get("fan_speed_cap_pct")) or 0.70
            self.fan = replace(self.fan, wear_pct=min(self.fan.wear_pct, 0.20))
            self.ahu = replace(self.ahu, fan_wear_pct=min(self.ahu.fan_wear_pct, 0.20))
            accepted = True
            reason = f"fan_derated_to_{cap:.0%}"
        elif action_type == "PREEMPTIVE_FILTER_SERVICE":
            target_clog = finite_number(params.get("filter_clog_target_pct")) or 0.05
            self.ahu = replace(self.ahu, filter_clog_pct=target_clog)
            accepted = True
            reason = "filter_cleaned_to_5%"
        elif action_type == "COMFORT_DEBT_SHIELD":
            for r in self.rooms.values():
                r.comfort_debt_c_s = 0.0
                r.limited_service_s = 0.0
            accepted = True
            reason = "comfort_debt_shield_applied"
        elif action_type == "BALANCED_LOAD_DISPATCH":
            accepted = True
            reason = "balanced_load_dispatched"

        if accepted:
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.active_evaluation_session = ActionEvaluationSession(
                session_id=f"SESS-{int(datetime.now(timezone.utc).timestamp())}",
                action_id=params.get("action_id", f"ACT-{action_type}"),
                action_type=action_type,
                title=params.get("title", action_type.replace("_", " ").title()),
                target=target,
                parameters=params,
                start_timestamp=now_iso,
                total_ticks=15,
            )
            self._update_intelligence()
        return accepted, reason

    @property
    def state(self) -> RoomState:
        """Legacy façade for callers that expect the original single RoomState."""
        return self.rooms["room1"].state

    @property
    def paused(self) -> bool:
        return self.operating_mode != "running"

    def scenario_state(self) -> dict:
        return {
            "name": self.active_scenario,
            "revision": self.scenario_revision,
            "operating_mode": self.operating_mode,
            "paused": self.paused,
            "last_command_id": self.last_command_id,
        }

    def snapshot(self) -> EcosystemSnapshot:
        eval_dict = None
        if self.active_evaluation_session is not None:
            eval_dict = {
                "session_id": self.active_evaluation_session.session_id,
                "action_type": self.active_evaluation_session.action_type,
                "title": self.active_evaluation_session.title,
                "target": self.active_evaluation_session.target,
                "ticks_elapsed": self.active_evaluation_session.ticks_elapsed,
                "total_ticks": self.active_evaluation_session.total_ticks,
                "is_complete": self.active_evaluation_session.is_complete,
                "overall_score": self.active_evaluation_session.overall_score,
                "all_tests_passed": self.active_evaluation_session.all_tests_passed,
                "test_results": [asdict(t) for t in self.active_evaluation_session.test_results],
            }
        return EcosystemSnapshot(
            rooms=self.rooms.copy(),
            ahu=self.ahu,
            fan=self.fan,
            coordination=self.last_coordination,
            risk=self.last_risk,
            demand_forecast=self.last_demand_forecast,
            recommendations=self.last_recommendations,
            active_evaluation=eval_dict,
            auto_action_enabled=self.auto_action_enabled,
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
            if not OCC_MIN <= value <= OCC_MAX:
                return False
            return self._update_room(room_id, occupancy=value)
        if command == "setpoint":
            value = finite_number(data.get("value"))
            if value is None or not SETPOINT_MIN <= value <= SETPOINT_MAX:
                return False
            return self._update_room(room_id, setpoint=value)
        if command == "mode":
            value = data.get("mode")
            if value not in ("auto", "manual"):
                return False
            return self._update_room(room_id, mode=value)
        if command == "timescale":
            value = exact_integer_choice(data.get("value"), VALID_TIME_SCALES)
            if value is None:
                return False
            changed = any(runtime.state.time_scale != float(value) for runtime in self.rooms.values())
            for runtime in self.rooms.values():
                runtime.state = replace(runtime.state, time_scale=float(value))
            return changed
        return False

    def apply_ahu_command(self, command: str, data: dict) -> bool:
        """Apply explicit demo/degradation commands to the shared AHU."""
        value = data.get("value")
        if command not in ("filter_clog", "fan_wear"):
            return False
        value = finite_number(value)
        if value is None or not 0.0 <= value <= 1.0:
            return False
        if command == "filter_clog":
            self.ahu = replace(self.ahu, filter_clog_pct=value)
        else:
            self.ahu = replace(self.ahu, fan_wear_pct=value)
            self.fan = replace(self.fan, wear_pct=value)
        return True

    @staticmethod
    def _valid_room_command(command: str, data: dict) -> bool:
        if command == "hvac":
            return data.get("command") in ("on", "off")
        if command == "occupancy":
            value = data.get("value")
            return isinstance(value, int) and not isinstance(value, bool) and OCC_MIN <= value <= OCC_MAX
        if command == "setpoint":
            value = finite_number(data.get("value"))
            return value is not None and SETPOINT_MIN <= value <= SETPOINT_MAX
        if command == "mode":
            return data.get("mode") in ("auto", "manual")
        if command == "timescale":
            return exact_integer_choice(data.get("value"), VALID_TIME_SCALES) is not None
        return False

    @staticmethod
    def _valid_ahu_command(command: str, data: dict) -> bool:
        value = finite_number(data.get("value"))
        return command in ("filter_clog", "fan_wear") and value is not None and 0.0 <= value <= 1.0

    def apply_command_result(self, topic: str, payload: bytes) -> CommandOutcome:
        """Route a command and return an application-level acknowledgement."""
        envelope, rejection = decode_command_payload(topic, payload)
        if rejection is not None:
            return rejection
        assert envelope is not None
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "twin" or parts[2] != "cmd":
            return rejected_outcome(
                topic,
                "unsupported_topic",
                command_id=envelope.command_id,
                source=envelope.source,
            )
        target, command = parts[1], parts[3]
        accepted = False
        changed = False
        reason = "unsupported_command"
        if target in self.rooms:
            accepted = self._valid_room_command(command, envelope.values)
            changed = self.apply_room_command(target, command, envelope.values) if accepted else False
            reason = "applied" if changed else "no_change" if accepted else "invalid_command"
        elif target == "ahu":
            accepted = self._valid_ahu_command(command, envelope.values)
            if accepted:
                before = (self.ahu, self.fan)
                self.apply_ahu_command(command, envelope.values)
                changed = before != (self.ahu, self.fan)
            reason = "applied" if changed else "no_change" if accepted else "invalid_command"
        elif target == "ecosystem" and command == "scenario":
            name = envelope.values.get("scenario", envelope.values.get("command"))
            accepted = isinstance(name, str) and self.apply_scenario(name, envelope.command_id)
            changed = accepted
            reason = "applied" if accepted else "unknown_scenario"
        elif target == "ecosystem" and command == "simulation":
            action = envelope.values.get("command")
            if action in ("pause", "resume", "emergency_stop"):
                requested_mode = {
                    "pause": "paused",
                    "resume": "running",
                    "emergency_stop": "simulation_emergency_stop",
                }[action]
                changed = self.operating_mode != requested_mode
                self.operating_mode = requested_mode
                self.scenario_revision += 1
                self.last_command_id = envelope.command_id
                accepted = True
                reason = "applied" if changed else "no_change"
            else:
                reason = "invalid_choice"
        elif target == "ecosystem" and command == "action":
            act_type = envelope.values.get("action_type") or envelope.values.get("action")
            act_target = envelope.values.get("target", "ecosystem")
            act_params = envelope.values.get("parameters", {})
            if isinstance(act_type, str):
                accepted, reason = self.apply_action(act_type, act_target, act_params, source=envelope.source or "operator")
                changed = accepted
            else:
                reason = "invalid_action"
        elif target == "ecosystem" and command == "auto_action":
            enabled = envelope.values.get("enabled")
            if isinstance(enabled, bool):
                changed = self.auto_action_enabled != enabled
                self.auto_action_enabled = enabled
                accepted = True
                reason = "applied" if changed else "no_change"
            else:
                reason = "invalid_choice"
        elif target == "ecosystem" and command == "knowledge":
            know_cmd = envelope.values.get("command")
            pol_id = envelope.values.get("policy_id")
            notes = str(envelope.values.get("notes", ""))
            if know_cmd == "approve" and isinstance(pol_id, str):
                changed = self.knowledge_repo.approve_policy(pol_id, notes)
                accepted = True
                reason = "policy_approved" if changed else "policy_not_found"
            elif know_cmd == "reject" and isinstance(pol_id, str):
                changed = self.knowledge_repo.reject_policy(pol_id, notes)
                accepted = True
                reason = "policy_rejected" if changed else "policy_not_found"
            else:
                reason = "invalid_knowledge_command"
        else:
            reason = "unsupported_topic"
        if accepted:
            self.last_command_id = envelope.command_id
        return CommandOutcome(
            topic=topic,
            target=target,
            command=command,
            accepted=accepted,
            changed=changed,
            reason=reason,
            command_id=envelope.command_id,
            source=envelope.source,
            applied_values={"operating_mode": self.operating_mode}
            if target == "ecosystem" and command == "simulation"
            else {},
        )

    def apply_command(self, topic: str, payload: bytes) -> bool:
        """Compatibility wrapper returning whether a valid command changed state."""
        result = self.apply_command_result(topic, payload)
        return result.accepted and result.changed

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
                    comfort_debt_c_s=room.comfort_debt_c_s,
                    limited_service_s=room.limited_service_s,
                )
            )
        return demands

    def _zero_instantaneous_state(self) -> None:
        """Zero instantaneous flow and power without advancing cumulative state."""
        demands = [
            RoomDemand(
                room_id=room.room_id,
                requested_airflow_m3_s=0.0,
                occupancy=room.state.occupancy,
                temperature_c=room.state.temperature,
                setpoint_c=room.state.setpoint,
                enabled=False,
                comfort_debt_c_s=room.comfort_debt_c_s,
                limited_service_s=room.limited_service_s,
            )
            for room in self.rooms.values()
        ]
        self.last_coordination = coordinate(demands, available_airflow(self.ahu))
        decisions = {decision.room_id: decision for decision in self.last_coordination.decisions}
        for room in self.rooms.values():
            room.requested_airflow_m3_s = 0.0
            room.delivered_airflow_m3_s = 0.0
            room.thermal_cooling_power_w = 0.0
            room.allocation = decisions[room.room_id]
            room.state = replace(room.state, ac_power_pct=0.0)
        self.ahu = replace(
            self.ahu,
            fan_speed_pct=0.0,
            fan_power_w=0.0,
            cooling_power_w=0.0,
            total_power_w=0.0,
        )

    def tick(self, dt: float | None = None, *, advance_occupancy: bool = True) -> EcosystemSnapshot:
        """Advance all twins one simulated step and return a coherent snapshot."""
        actual_dt = float(dt if dt is not None else self.rooms["room1"].state.time_scale)
        if not math.isfinite(actual_dt) or actual_dt < 0.0:
            raise ValueError("dt must be finite and non-negative")
        if self.paused:
            self._zero_instantaneous_state()
            return self.snapshot()
        demands = self._requests(actual_dt)
        coordination = coordinate(demands, available_airflow(self.ahu))
        decisions = {decision.room_id: decision for decision in coordination.decisions}
        total_airflow = 0.0
        total_cooling = 0.0

        demands_by_room = {demand.room_id: demand for demand in demands}
        for room_id, room in self.rooms.items():
            decision = decisions[room_id]
            room.allocation = decision
            room.delivered_airflow_m3_s = decision.granted_airflow_m3_s
            room.comfort_debt_c_s, room.limited_service_s = update_comfort_debt(
                demands_by_room[room_id], room.delivered_airflow_m3_s, actual_dt
            )
            applied_output = room.delivered_airflow_m3_s / ROOM_MAX_AIRFLOW_M3_S
            room.pid.apply_actuator_feedback(
                requested_output=room.state.ac_power_pct,
                applied_output=applied_output,
                dt=actual_dt,
            )
            total_airflow += room.delivered_airflow_m3_s
            room.thermal_cooling_power_w = cooling_power_w(
                room.state.temperature,
                self.ahu.supply_air_temp_c,
                room.delivered_airflow_m3_s,
            )
            total_cooling += room.thermal_cooling_power_w
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
            if advance_occupancy and not self.guided_scenario_active:
                room.state = replace(room.state, occupancy=step_occupancy(room.state, self.rng))

        self.ahu = advance_ahu(self.ahu, total_airflow, total_cooling, actual_dt)
        self.fan = step_fan_state(
            self.fan,
            fan_speed_pct=self.ahu.fan_speed_pct,
            filter_clog_pct=self.ahu.filter_clog_pct,
            dt=actual_dt,
        )
        self.ahu = replace(self.ahu, fan_wear_pct=max(self.ahu.fan_wear_pct, self.fan.wear_pct))
        self.last_coordination = coordination
        self.last_risk = self.model.predict(
            fan_telemetry(
                self.fan,
                fan_speed_pct=self.ahu.fan_speed_pct,
                filter_clog_pct=self.ahu.filter_clog_pct,
            )
        )

        self._update_intelligence()

        # Autonomous closed-loop action execution if enabled
        if self.auto_action_enabled and (self.active_evaluation_session is None or self.active_evaluation_session.is_complete):
            for rec in self.last_recommendations:
                if rec.confidence >= 0.85 and rec.severity in ("critical", "high"):
                    self.apply_action(rec.action_type, rec.target, rec.parameters, source="auto_agent")
                    break

        # Record evaluation session progress if active
        if self.active_evaluation_session is not None and not self.active_evaluation_session.is_complete:
            max_err = max(max(0.0, r.state.temperature - r.state.setpoint) for r in self.rooms.values())
            risk_val = self.last_risk.failure_risk if self.last_risk.failure_risk is not None else 0.0
            tot_debt = sum(r.comfort_debt_c_s for r in self.rooms.values())
            metrics = {
                "max_temp_error_c": max_err,
                "fan_failure_risk": risk_val,
                "total_power_w": self.ahu.total_power_w,
                "total_comfort_debt_c_s": tot_debt,
                "cop_valid": True,
            }
            self.active_evaluation_session.record_tick(metrics)
            if self.active_evaluation_session.is_complete:
                self.knowledge_repo.record_completed_session(
                    self.active_evaluation_session,
                    trigger_condition=f"Observed risk on {self.active_evaluation_session.target.upper()}",
                    action_summary=f"Automated execution and verification of {self.active_evaluation_session.action_type}",
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
                "priority_score": list(decision.priority_score[:4]),
                "comfort_debt_c_s": round(decision.comfort_debt_c_s, 3),
                "limited_service_s": round(decision.limited_service_s, 3),
                "reason_codes": list(decision.reason_codes),
            }
            for decision in result.decisions
        ],
    }
