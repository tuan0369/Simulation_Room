import json
import sqlite3

import pytest

from audit import AuditJournal, GENESIS_HASH


def test_append_persists_canonical_hash_chain_across_reopen(tmp_path):
    path = tmp_path / "audit.db"
    with AuditJournal(path) as journal:
        first = journal.append(
            "command.received",
            {"z": 2, "a": 1},
            actor="dashboard",
            correlation_id="cmd-1",
            timestamp="2026-08-14T10:00:00Z",
        )
        second = journal.append(
            "command.applied",
            {"accepted": True},
            actor="simulator",
            correlation_id="cmd-1",
            timestamp="2026-08-14T10:00:01Z",
        )

        assert first.sequence == 1
        assert first.previous_hash == GENESIS_HASH
        assert second.previous_hash == first.entry_hash
        assert journal.verify().valid is True

    with AuditJournal(path) as reopened:
        assert [entry.payload for entry in reopened] == [
            {"a": 1, "z": 2},
            {"accepted": True},
        ]
        assert reopened.verify().entries_checked == 2


def test_same_event_material_produces_same_hash(tmp_path):
    details = dict(
        event_type="state.changed",
        actor="simulator",
        correlation_id="fixed",
        timestamp="2026-08-14T10:00:00Z",
    )
    with AuditJournal(tmp_path / "one.db") as first, AuditJournal(tmp_path / "two.db") as second:
        left = first.append(payload={"b": 2, "a": 1}, **details)
        right = second.append(payload={"a": 1, "b": 2}, **details)
    assert left.entry_hash == right.entry_hash


@pytest.mark.parametrize(
    ("statement", "expected_reason"),
    [
        ("UPDATE audit_entries SET payload_json = '{\"accepted\":false}' WHERE sequence = 1", "entry_hash_mismatch"),
        ("UPDATE audit_entries SET previous_hash = 'broken' WHERE sequence = 2", "previous_hash_mismatch"),
        ("DELETE FROM audit_entries WHERE sequence = 1", "sequence_gap"),
    ],
)
def test_verification_reports_first_tampered_row(tmp_path, statement, expected_reason):
    path = tmp_path / "audit.db"
    with AuditJournal(path) as journal:
        journal.append("first", {"value": 1}, timestamp="2026-08-14T10:00:00Z")
        journal.append("second", {"value": 2}, timestamp="2026-08-14T10:00:01Z")

    with sqlite3.connect(path) as connection:
        connection.execute(statement)

    with AuditJournal(path) as journal:
        result = journal.verify()
    assert result.valid is False
    assert result.reason == expected_reason


def test_verification_detects_deleted_tail_through_chain_head(tmp_path):
    path = tmp_path / "audit.db"
    with AuditJournal(path) as journal:
        journal.append("first", {})
        journal.append("second", {})

    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM audit_entries WHERE sequence = 2")

    with AuditJournal(path) as journal:
        result = journal.verify()
    assert result.valid is False
    assert result.reason == "chain_head_mismatch"


def test_invalid_payload_is_rejected_without_partial_append(tmp_path):
    with AuditJournal(tmp_path / "audit.db") as journal:
        with pytest.raises(ValueError):
            journal.append("invalid", {"not_finite": float("nan")})
        assert journal.entries() == ()
        assert journal.verify().valid is True
