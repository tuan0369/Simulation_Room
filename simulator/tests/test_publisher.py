import json
from dataclasses import replace

from audit import AuditJournal
from fan_health import RiskPrediction
from physics import RoomState
from publisher import (
    AHU_BASE,
    COMMAND_RESULT_TOPIC,
    PRESENTATION_STATE_TOPIC,
    SCENARIO_COMMAND_TOPIC,
    SCENARIO_STATE_TOPIC,
    CMD_HVAC,
    CMD_MODE,
    CMD_OCCUPANCY,
    CMD_SETPOINT,
    CMD_TIMESCALE,
    Simulator,
    handle_command,
    make_payload,
)


def test_make_payload_matches_spec_format():
    p = json.loads(make_payload("temperature", 24.7, "C", "2026-07-16T20:14:03Z"))
    assert p == {"sensor": "temperature", "value": 24.7, "unit": "C",
                 "timestamp": "2026-07-16T20:14:03Z"}


def test_make_payload_default_timestamp_is_utc_iso_z():
    p = json.loads(make_payload("humidity", 45.2, "%"))
    assert p["timestamp"].endswith("Z") and "T" in p["timestamp"]


def test_hvac_command_on_off():
    s = RoomState(hvac_on=False)
    s2 = handle_command(s, CMD_HVAC, b'{"command": "on"}')
    assert s2.hvac_on is True
    s3 = handle_command(s2, CMD_HVAC, b'{"command": "off"}')
    assert s3.hvac_on is False


def test_occupancy_override_range_checked():
    s = handle_command(RoomState(), CMD_OCCUPANCY, b'{"value": 8}')
    assert s.occupancy == 8
    s = handle_command(RoomState(occupancy=2), CMD_OCCUPANCY, b'{"value": 99}')
    assert s.occupancy == 2


def test_malformed_command_is_ignored():
    s = RoomState(hvac_on=True)
    assert handle_command(s, CMD_HVAC, b"not json").hvac_on is True
    assert handle_command(s, CMD_HVAC, b'{"command": "banana"}').hvac_on is True


def test_non_object_json_command_is_ignored():
    s = RoomState(hvac_on=True, occupancy=5)
    assert handle_command(s, CMD_HVAC, b"null").hvac_on is True
    assert handle_command(s, CMD_HVAC, b"5").hvac_on is True
    assert handle_command(s, CMD_HVAC, b'"on"').hvac_on is True
    assert handle_command(s, CMD_OCCUPANCY, b"[1, 2]").occupancy == 5


def test_occupancy_bool_value_is_rejected():
    s = RoomState(occupancy=5)
    result = handle_command(s, CMD_OCCUPANCY, b'{"value": true}')
    assert result.occupancy == 5


# ─── New command tests ───────────────────────────────────

def test_setpoint_command():
    s = RoomState(setpoint=25.0)
    s2 = handle_command(s, CMD_SETPOINT, b'{"value": 22.5}')
    assert s2.setpoint == 22.5


def test_setpoint_command_out_of_range_rejected():
    s = RoomState(setpoint=25.0)
    assert handle_command(s, CMD_SETPOINT, b'{"value": 10.0}').setpoint == 25.0
    assert handle_command(s, CMD_SETPOINT, b'{"value": 35.0}').setpoint == 25.0


def test_setpoint_bool_rejected():
    s = RoomState(setpoint=25.0)
    assert handle_command(s, CMD_SETPOINT, b'{"value": true}').setpoint == 25.0


def test_timescale_command():
    s = RoomState(time_scale=1.0)
    s2 = handle_command(s, CMD_TIMESCALE, b'{"value": 5}')
    assert s2.time_scale == 5.0


def test_timescale_invalid_value_rejected():
    s = RoomState(time_scale=1.0)
    # Value 3 is not in valid set {1, 2, 5, 10}
    s2 = handle_command(s, CMD_TIMESCALE, b'{"value": 3}')
    assert s2.time_scale == 1.0  # unchanged


def test_timescale_bool_rejected():
    s = RoomState(time_scale=1.0)
    assert handle_command(s, CMD_TIMESCALE, b'{"value": true}').time_scale == 1.0


def test_mode_command_auto_and_manual():
    s = RoomState(mode="manual")
    s2 = handle_command(s, CMD_MODE, b'{"mode": "auto"}')
    assert s2.mode == "auto"
    s3 = handle_command(s2, CMD_MODE, b'{"mode": "manual"}')
    assert s3.mode == "manual"


def test_mode_command_invalid_rejected():
    s = RoomState(mode="auto")
    assert handle_command(s, CMD_MODE, b'{"mode": "banana"}').mode == "auto"
    assert handle_command(s, CMD_MODE, b'{"value": "manual"}').mode == "auto"
    assert handle_command(s, CMD_MODE, b"not json").mode == "auto"


class FakeClient:
    def __init__(self):
        self.subscriptions = []
        self.published = []

    def subscribe(self, topics):
        self.subscriptions.extend(topics)

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))


def test_simulator_subscribes_to_scenario_command():
    simulator = Simulator(seed=3)
    client = FakeClient()

    simulator.on_connect(client, None, None, 0, None)

    assert (SCENARIO_COMMAND_TOPIC, 0) in client.subscriptions
    assert (f"{AHU_BASE}/cmd/+", 0) in client.subscriptions


def test_queued_scenario_is_applied_with_correlated_non_retained_result():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client
    payload = b'{"command": "shared_capacity_stress", "command_id": "demo-1"}'

    class Message:
        topic = SCENARIO_COMMAND_TOPIC
        retain = False

    message = Message()
    message.payload = payload
    simulator.on_message(client, None, message)
    assert simulator.ecosystem.active_scenario == "baseline"
    assert simulator._drain_commands()
    assert simulator.ecosystem.active_scenario == "shared_capacity_stress"

    topic, serialized, retained = next(
        published for published in client.published if published[0] == COMMAND_RESULT_TOPIC
    )
    result = json.loads(serialized)
    assert topic == COMMAND_RESULT_TOPIC
    assert retained is False
    assert result["accepted"] is True
    assert result["changed"] is True
    assert result["command_id"] == "demo-1"
    assert result["source"] == "unknown"
    assert result["reason"] == "applied"


def test_scenario_and_presentation_state_are_retained_and_coherent():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client
    simulator._apply_scenario_command(
        b'{"command": "shared_capacity_stress", "command_id": "demo-2"}'
    )
    snapshot = simulator.ecosystem.tick(dt=1.0)

    simulator.publish_snapshot(snapshot)

    scenario_record = next(
        published for published in client.published if published[0] == SCENARIO_STATE_TOPIC
    )
    presentation_record = next(
        published for published in client.published if published[0] == PRESENTATION_STATE_TOPIC
    )
    assert scenario_record[2] is True
    assert presentation_record[2] is True
    presentation = json.loads(presentation_record[1])
    assert presentation["scenario"]["name"] == "shared_capacity_stress"
    assert presentation["rooms"]["room1"]["occupancy"] == 24
    assert presentation["rooms"]["room2"]["occupancy"] == 5
    total_grant = sum(
        room["granted_airflow_m3_s"] for room in presentation["rooms"].values()
    )
    assert abs(total_grant - presentation["ahu"]["delivered_airflow_m3_s"]) < 1e-9
    assert presentation["snapshot_id"] == 1


def test_abstained_risk_is_published_explicitly_without_a_numeric_score():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client
    snapshot = simulator.ecosystem.tick(dt=1.0, advance_occupancy=False)
    abstained = RiskPrediction(
        failure_risk=None,
        risk_band="unavailable",
        top_drivers=(),
        model_version="fan-risk-logistic-v1",
        prediction_status="unavailable",
        status_reason="artifact missing",
        available=False,
        abstained=True,
    )

    simulator.publish_snapshot(replace(snapshot, risk=abstained))

    presentation_record = next(
        published for published in client.published if published[0] == PRESENTATION_STATE_TOPIC
    )
    presentation = json.loads(presentation_record[1])
    assert presentation["risk"]["failure_risk"] is None
    assert presentation["risk"]["available"] is False
    assert presentation["risk"]["abstained"] is True
    assert presentation["risk"]["status_reason"] == "artifact missing"


def _command_results(client):
    return [
        json.loads(payload)
        for topic, payload, _ in client.published
        if topic == COMMAND_RESULT_TOPIC
    ]


def test_duplicate_command_id_is_replayed_before_mutation():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    class Message:
        topic = CMD_OCCUPANCY
        retain = False

    first = Message()
    first.payload = b'{"value": 7, "command_id": "once"}'
    duplicate = Message()
    duplicate.payload = first.payload
    simulator.on_message(client, None, first)
    simulator.on_message(client, None, duplicate)
    assert simulator._drain_commands() is True

    results = _command_results(client)
    assert simulator.ecosystem.state.occupancy == 7
    assert results[0]["reason"] == "applied"
    assert results[1]["accepted"] is True
    assert results[1]["duplicate"] is True
    assert results[1]["replayed"] is True
    assert results[1]["reason"] == "applied"


def test_reused_command_id_with_different_request_is_rejected_without_mutation():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    class Message:
        topic = CMD_OCCUPANCY
        retain = False

    first = Message()
    first.payload = b'{"value": 7, "command_id": "conflict"}'
    conflict = Message()
    conflict.payload = b'{"value": 20, "command_id": "conflict"}'
    simulator.on_message(client, None, first)
    simulator.on_message(client, None, conflict)
    simulator._drain_commands()

    result = _command_results(client)[-1]
    assert simulator.ecosystem.state.occupancy == 7
    assert result["accepted"] is False
    assert result["reason"] == "command_id_conflict"
    assert result["duplicate"] is True


def test_retained_command_is_rejected_before_queue_or_mutation():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    class Message:
        topic = CMD_OCCUPANCY
        payload = b'{"value": 20, "command_id": "retained"}'
        retain = True

    simulator.on_message(client, None, Message())

    assert simulator.ecosystem.state.occupancy == 8
    assert simulator._commands.empty()
    result = _command_results(client)[-1]
    assert result["accepted"] is False
    assert result["reason"] == "retained_command_rejected"


def test_configured_audit_journal_records_sanitized_request_and_result(tmp_path, monkeypatch):
    audit_path = tmp_path / "commands.db"
    monkeypatch.setenv("ECOHVAC_AUDIT_PATH", str(audit_path))
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    class Message:
        topic = CMD_SETPOINT
        payload = b'{"value": 22.5, "command_id": "audit-1", "source": "operator"}'
        retain = False

    simulator.on_message(client, None, Message())
    simulator._drain_commands()
    assert simulator.audit_journal is not None
    simulator.audit_journal.close()

    with AuditJournal(audit_path) as journal:
        entry = journal.entries()[0]
        assert journal.verify().valid
    assert entry.correlation_id == "audit-1"
    assert entry.actor == "operator"
    assert entry.payload["request"]["topic"] == CMD_SETPOINT
    assert "value" not in entry.payload["request"]
    assert entry.payload["result"]["accepted"] is True


def test_audit_write_failure_is_visible_in_published_result():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    class BrokenJournal:
        def append(self, *args, **kwargs):
            raise OSError("disk full")

    simulator.audit_journal = BrokenJournal()

    class Message:
        topic = CMD_SETPOINT
        payload = b'{"value": 22.5, "command_id": "audit-fail"}'
        retain = False

    simulator.on_message(client, None, Message())
    simulator._drain_commands()
    result = _command_results(client)[-1]
    assert result["audit_write_failed"] is True
    assert "disk full" in result["audit_error"]
    assert simulator.audit_error == result["audit_error"]


def test_process_once_is_a_finite_iteration_seam():
    simulator = Simulator(seed=3)
    client = FakeClient()
    simulator.client = client

    snapshot = simulator.process_once(tick=0)

    assert snapshot.rooms.keys() == simulator.ecosystem.rooms.keys()
    assert simulator.snapshot_id == 1
    assert any(topic == PRESENTATION_STATE_TOPIC for topic, _, _ in client.published)
