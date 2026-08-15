from collections import deque

import pytest

from ..telemetry import (
    apply_message,
    correlate_command_result,
    decode_payload,
    new_command,
    new_store,
    reconcile_pending_commands,
    set_transport_state,
    snapshot_store,
)


def test_decode_payload_accepts_objects_and_rejects_malformed_or_non_objects():
    assert decode_payload(b'{"value": 24.5}') == {"value": 24.5}
    assert decode_payload("not json") is None
    assert decode_payload(b"[1, 2]") is None
    assert decode_payload(b"\xff") is None


def test_apply_message_stores_room_telemetry_state_and_plain_status():
    store = new_store(("lab",), sensor_history=2)

    assert apply_message(
        store,
        "twin/lab/temperature",
        b'{"sensor":"temperature","value":24.5,"unit":"C","timestamp":"2026-08-14T10:00:00Z"}',
    )
    assert apply_message(store, "twin/lab/status", b"running")
    assert apply_message(store, "twin/lab/hvac/state", b'{"hvac_on":true}')
    assert apply_message(store, "twin/lab/ac/detail", b'{"mode":"auto"}')
    assert apply_message(store, "twin/lab/hvac/allocation", b'{"allocation_pct":0.8}')
    assert apply_message(store, "twin/lab/energy", b'{"power_kw":1.2}')

    room = snapshot_store(store)["rooms"]["lab"]
    assert room["temperature"][0][1] == 24.5
    assert room["status"] == "running"
    assert room["hvac"] == {"hvac_on": True}
    assert room["detail"] == {"mode": "auto"}
    assert room["allocation"] == {"allocation_pct": 0.8}
    assert room["energy"] == {"power_kw": 1.2}


def test_sensor_history_is_bounded_and_invalid_values_do_not_replace_data():
    store = new_store(("lab",), sensor_history=2)
    for minute, value in enumerate((20, 21, 22)):
        assert apply_message(
            store,
            "twin/lab/temperature",
            f'{{"value":{value},"timestamp":"2026-08-14T10:0{minute}:00Z"}}',
        )

    assert not apply_message(
        store,
        "twin/lab/temperature",
        b'{"value":true,"timestamp":"2026-08-14T10:04:00Z"}',
    )
    assert [point[1] for point in snapshot_store(store)["rooms"]["lab"]["temperature"]] == [21, 22]


def test_apply_message_stores_ahu_ecosystem_and_risk_history():
    store = new_store(("lab",))
    assert apply_message(store, "twin/ecosystem/status", b"healthy")
    assert apply_message(store, "twin/ecosystem/scenario/state", b'{"name":"baseline"}')
    assert apply_message(
        store,
        "twin/ecosystem/presentation/state",
        b'{"snapshot_id":7,"scenario":{"name":"baseline"}}',
    )
    assert apply_message(
        store,
        "twin/ecosystem/command/result",
        b'{"command_id":"cmd-1","accepted":true}',
    )
    assert apply_message(store, "twin/ahu/state", b'{"fan_speed_pct":50}')
    assert apply_message(store, "twin/ahu/coordinator/decision", b'{"constrained":false}')
    assert apply_message(
        store,
        "twin/ahu/fan/health",
        b'{"failure_risk":0.25,"timestamp":"2026-08-14T10:00:00Z"}',
    )

    snapshot = snapshot_store(store)
    assert snapshot["ecosystem_status"] == "healthy"
    assert snapshot["scenario"] == {"name": "baseline"}
    assert snapshot["presentation"]["snapshot_id"] == 7
    assert snapshot["command_result"]["command_id"] == "cmd-1"
    assert snapshot["ahu"]["state"] == {"fan_speed_pct": 50}
    assert snapshot["ahu"]["decision"] == {"constrained": False}
    assert snapshot["risk_history"][0][1] == 0.25


def test_unknown_or_malformed_messages_leave_store_unchanged():
    store = new_store(("lab",))
    before = snapshot_store(store)
    assert not apply_message(store, "twin/unknown/temperature", b'{"value":1}')
    assert not apply_message(store, "twin/lab/energy", b"null")
    assert not apply_message(store, "not/a/topic", b"{}")
    assert snapshot_store(store) == before


def test_snapshot_is_detached_and_excludes_lock():
    store = new_store(("lab",))
    assert isinstance(store["rooms"]["lab"]["temperature"], deque)
    snapshot = snapshot_store(store)
    snapshot["rooms"]["lab"]["hvac"]["changed"] = True
    snapshot["rooms"]["lab"]["temperature"].append(("fake", 1))

    assert "lock" not in snapshot
    assert store["rooms"]["lab"]["hvac"] == {}
    assert len(store["rooms"]["lab"]["temperature"]) == 0


def test_new_command_and_result_correlation_support_mapping_or_encoded_result():
    command = new_command({"value": 22.5}, command_id="cmd-123")
    assert command == {"value": 22.5, "command_id": "cmd-123", "source": "dashboard"}
    assert correlate_command_result(command, {"command_id": "cmd-123", "accepted": True})
    assert correlate_command_result("cmd-123", b'{"command_id":"cmd-123","accepted":false}')
    assert not correlate_command_result("cmd-123", {"command_id": "other"})
    assert not correlate_command_result(None, {"command_id": "cmd-123"})


def test_new_command_generates_unique_ids_and_validates_metadata():
    first = new_command(command="on")
    second = new_command(command="on")
    assert first["command_id"] != second["command_id"]
    assert len(first["command_id"]) == 32
    with pytest.raises(ValueError):
        new_command(command_id="")
    with pytest.raises(ValueError):
        new_command(source="")


def test_command_results_are_retained_in_order_with_monotonic_count():
    store = new_store(("lab",))
    for command_id in ("cmd-1", "cmd-2"):
        assert apply_message(
            store,
            "twin/ecosystem/command/result",
            f'{{"command_id":"{command_id}","accepted":true}}',
        )

    snapshot = snapshot_store(store)
    assert [result["command_id"] for result in snapshot["command_results"]] == [
        "cmd-1",
        "cmd-2",
    ]
    assert snapshot["command_result_count"] == 2
    assert snapshot["command_result"]["command_id"] == "cmd-2"


def test_reconcile_pending_commands_matches_batch_results_without_mutating_inputs():
    pending = {
        "cmd-mode": {"topic": "twin/lab/cmd/mode"},
        "cmd-setpoint": {"topic": "twin/lab/cmd/setpoint"},
        "cmd-occupancy": {"topic": "twin/lab/cmd/occupancy"},
        "cmd-timescale": {"topic": "twin/lab/cmd/timescale"},
    }
    results = [
        {"command_id": "unrelated", "accepted": True},
        {"command_id": "cmd-timescale", "accepted": True, "reason": "applied"},
        {"command_id": "cmd-mode", "accepted": False, "reason": "invalid"},
    ]

    remaining, matched = reconcile_pending_commands(pending, results)

    assert set(remaining) == {"cmd-setpoint", "cmd-occupancy"}
    assert [result["command_id"] for result in matched] == ["cmd-timescale", "cmd-mode"]
    assert matched[0]["topic"] == "twin/lab/cmd/timescale"
    assert matched[1]["accepted"] is False
    assert set(pending) == {"cmd-mode", "cmd-setpoint", "cmd-occupancy", "cmd-timescale"}


def test_transport_state_is_independent_from_simulator_status():
    store = new_store(("lab",))
    assert store["broker_status"] == "connecting"
    assert store["ecosystem_status"] == "unknown"

    set_transport_state(store, "unavailable", "connection refused")

    snapshot = snapshot_store(store)
    assert snapshot["broker_status"] == "unavailable"
    assert snapshot["broker_error"] == "connection refused"
    assert snapshot["ecosystem_status"] == "unknown"


def test_new_store_can_preserve_distinct_sensor_history_limits():
    store = new_store(("lab",), sensor_history=3, humidity_history=2)

    assert store["rooms"]["lab"]["temperature"].maxlen == 3
    assert store["rooms"]["lab"]["occupancy"].maxlen == 3
    assert store["rooms"]["lab"]["humidity"].maxlen == 2


def test_apply_message_stores_intelligence_and_knowledge():
    store = new_store(("lab",))
    assert apply_message(
        store,
        "twin/ecosystem/intelligence/demand",
        b'{"total_required_airflow_m3_s": 0.25, "is_capacity_deficit_projected": true}',
    )
    assert apply_message(
        store,
        "twin/ecosystem/intelligence/actions",
        b'{"auto_action_enabled": true, "recommendations": [{"action_type": "PREEMPTIVE_PRECOOL"}]}',
    )
    assert apply_message(
        store,
        "twin/ecosystem/knowledge/state",
        b'{"entries": [{"id": "KB-1", "status": "HUMAN_APPROVED"}]}',
    )

    snapshot = snapshot_store(store)
    assert snapshot["demand_forecast"]["total_required_airflow_m3_s"] == 0.25
    assert snapshot["actions"]["auto_action_enabled"] is True
    assert snapshot["knowledge"]["entries"][0]["id"] == "KB-1"

