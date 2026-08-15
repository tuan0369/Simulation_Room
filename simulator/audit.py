"""Local SQLite-backed, hash-chained audit journal.

The journal makes accidental or unsophisticated row tampering evident.  It does
not replace an externally anchored signature: an attacker who can rewrite the
entire database and recompute every hash can forge a new chain.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

GENESIS_HASH = "0" * 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _entry_hash(
    sequence: int,
    timestamp: str,
    event_type: str,
    actor: str,
    correlation_id: str | None,
    payload_json: str,
    previous_hash: str,
) -> str:
    material = _canonical_json(
        {
            "sequence": sequence,
            "timestamp": timestamp,
            "event_type": event_type,
            "actor": actor,
            "correlation_id": correlation_id,
            "payload": json.loads(payload_json),
            "previous_hash": previous_hash,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    timestamp: str
    event_type: str
    actor: str
    correlation_id: str | None
    payload: Any
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    entries_checked: int
    broken_sequence: int | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.valid


class AuditJournal:
    """Append-only journal with deterministic SHA-256 links between SQLite rows."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_entries (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    correlation_id TEXT,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS audit_chain_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    last_sequence INTEGER NOT NULL,
                    last_hash TEXT NOT NULL
                );
                INSERT OR IGNORE INTO audit_chain_state(singleton, last_sequence, last_hash)
                VALUES (1, 0, '0000000000000000000000000000000000000000000000000000000000000000');
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "AuditJournal":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def append(
        self,
        event_type: str,
        payload: Any,
        *,
        actor: str = "system",
        correlation_id: str | None = None,
        timestamp: str | None = None,
    ) -> AuditEntry:
        """Atomically append one JSON-serializable event and return its stored entry."""
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor must be a non-empty string")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ValueError("correlation_id must be a string or None")
        timestamp = timestamp or _utc_now()
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError("timestamp must be a non-empty string")
        payload_json = _canonical_json(payload)

        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                state = connection.execute(
                    "SELECT last_sequence, last_hash FROM audit_chain_state WHERE singleton = 1"
                ).fetchone()
                if state is None:
                    raise RuntimeError("audit chain state is missing")
                sequence = int(state["last_sequence"]) + 1
                previous_hash = str(state["last_hash"])
                entry_hash = _entry_hash(
                    sequence,
                    timestamp,
                    event_type,
                    actor,
                    correlation_id,
                    payload_json,
                    previous_hash,
                )
                connection.execute(
                    """INSERT INTO audit_entries
                       (sequence, timestamp, event_type, actor, correlation_id,
                        payload_json, previous_hash, entry_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sequence,
                        timestamp,
                        event_type,
                        actor,
                        correlation_id,
                        payload_json,
                        previous_hash,
                        entry_hash,
                    ),
                )
                connection.execute(
                    "UPDATE audit_chain_state SET last_sequence = ?, last_hash = ? WHERE singleton = 1",
                    (sequence, entry_hash),
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

        return AuditEntry(
            sequence=sequence,
            timestamp=timestamp,
            event_type=event_type,
            actor=actor,
            correlation_id=correlation_id,
            payload=json.loads(payload_json),
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )

    def entries(self) -> tuple[AuditEntry, ...]:
        """Return an immutable snapshot of entries in chain order."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_entries ORDER BY sequence"
            ).fetchall()
        return tuple(self._row_to_entry(row) for row in rows)

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self.entries())

    def verify(self) -> VerificationResult:
        """Verify row continuity, links, hashes, and the persisted chain head."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_entries ORDER BY sequence"
            ).fetchall()
            state = self._connection.execute(
                "SELECT last_sequence, last_hash FROM audit_chain_state WHERE singleton = 1"
            ).fetchone()

        previous_hash = GENESIS_HASH
        checked = 0
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            if sequence != expected_sequence:
                return VerificationResult(False, checked, expected_sequence, "sequence_gap")
            if row["previous_hash"] != previous_hash:
                return VerificationResult(False, checked, sequence, "previous_hash_mismatch")
            try:
                expected_hash = _entry_hash(
                    sequence,
                    row["timestamp"],
                    row["event_type"],
                    row["actor"],
                    row["correlation_id"],
                    row["payload_json"],
                    row["previous_hash"],
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                return VerificationResult(False, checked, sequence, "invalid_stored_payload")
            if row["entry_hash"] != expected_hash:
                return VerificationResult(False, checked, sequence, "entry_hash_mismatch")
            previous_hash = expected_hash
            checked += 1

        if state is None:
            return VerificationResult(False, checked, None, "missing_chain_state")
        if int(state["last_sequence"]) != checked or state["last_hash"] != previous_hash:
            broken = checked + 1 if int(state["last_sequence"]) > checked else checked or None
            return VerificationResult(False, checked, broken, "chain_head_mismatch")
        return VerificationResult(True, checked)

    @staticmethod
    def _row_to_entry(row: Mapping[str, Any]) -> AuditEntry:
        return AuditEntry(
            sequence=int(row["sequence"]),
            timestamp=str(row["timestamp"]),
            event_type=str(row["event_type"]),
            actor=str(row["actor"]),
            correlation_id=row["correlation_id"],
            payload=json.loads(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            entry_hash=str(row["entry_hash"]),
        )
