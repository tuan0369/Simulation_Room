"""Tests for action evaluation session, test verification suite, and knowledge repository."""
import json
import pytest
from pathlib import Path
from simulator.knowledge_base import (
    ActionEvaluationSession,
    KnowledgeRepository,
    LearnedKnowledgeEntry,
)


def test_action_evaluation_session_flow():
    session = ActionEvaluationSession(
        session_id="SESS-001",
        action_id="ACT-COOL-001",
        action_type="PREEMPTIVE_PRECOOL",
        title="Preemptive Pre-Cooling",
        target="room1",
        parameters={"temp_offset_c": -1.5},
        start_timestamp="2026-08-15T12:00:00Z",
        total_ticks=5,
    )
    assert not session.is_complete
    assert session.ticks_elapsed == 0

    # Feed 5 ticks
    for i in range(5):
        session.record_tick({
            "max_temp_error_c": max(0.0, 1.2 - i * 0.2),
            "fan_failure_risk": 0.15,
            "total_power_w": 1800.0,
            "total_comfort_debt_c_s": 0.0,
            "cop_valid": True,
        })

    assert session.is_complete
    assert len(session.test_results) == 4
    assert session.all_tests_passed is True
    assert session.overall_score >= 80.0


def test_knowledge_repository_lifecycle(tmp_path: Path):
    kb_file = tmp_path / "test_knowledge.json"
    repo = KnowledgeRepository(file_path=kb_file)
    assert len(repo.entries) >= 2  # Seed policies

    # Create a completed session
    session = ActionEvaluationSession(
        session_id="SESS-TEST",
        action_id="ACT-TEST",
        action_type="PREEMPTIVE_PRECOOL",
        title="Test Pre-Cool",
        target="room1",
        parameters={"temp_offset_c": -1.5},
        start_timestamp="2026-08-15T12:00:00Z",
        total_ticks=3,
    )
    for _ in range(3):
        session.record_tick({
            "max_temp_error_c": 0.5,
            "fan_failure_risk": 0.10,
            "total_power_w": 1500.0,
            "total_comfort_debt_c_s": 0.0,
            "cop_valid": True,
        })

    entry = repo.record_completed_session(session, trigger_condition="Test condition")
    assert entry.status == "CANDIDATE_PENDING_CONFIRMATION"
    assert entry.sha256_hash != ""

    # Approve policy
    approved = repo.approve_policy(entry.id, reviewer_notes="Approved in test")
    assert approved is True
    assert entry.status == "HUMAN_APPROVED"
    assert entry.reviewer_notes == "Approved in test"

    # Reload from disk
    repo_reloaded = KnowledgeRepository(file_path=kb_file)
    reloaded_entry = [e for e in repo_reloaded.entries if e.id == entry.id][0]
    assert reloaded_entry.status == "HUMAN_APPROVED"
    assert reloaded_entry.reviewer_notes == "Approved in test"

    # Reject policy
    rejected = repo.reject_policy(entry.id, reviewer_notes="Reject in test")
    assert rejected is True
    assert entry.status == "HUMAN_REJECTED"
