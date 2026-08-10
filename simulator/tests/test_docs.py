"""Consistency checks on the written deliverables.

Documentation that cites numbers goes stale silently. These tests fail when a
document's claims stop matching the code, the layout or the trained model.
"""
import json
import re
from pathlib import Path

import pytest

DOCS = {name: Path(f"docs/{name}.md").read_text(encoding="utf-8")
        for name in ("architecture", "ecosystem", "governance", "roi_roadmap")}
CARD = Path("ml/models/model_card.md").read_text(encoding="utf-8")
SPEC = json.loads(Path("ml/models/feature_spec.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(DOCS))
def test_document_exists_and_is_substantial(name):
    assert len(DOCS[name]) > 2000, f"{name}.md looks like a stub"


# ── Mermaid ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(DOCS))
def test_mermaid_uses_br_not_backslash_n(name):
    """A literal \\n renders as the characters, not a line break. This bit us
    in Project 1."""
    for block in re.findall(r"```mermaid(.*?)```", DOCS[name], re.S):
        assert "\\n" not in block, f"{name}.md has a literal backslash-n in mermaid"


@pytest.mark.parametrize("name", list(DOCS))
def test_mermaid_blocks_are_closed(name):
    assert DOCS[name].count("```mermaid") <= DOCS[name].count("```") / 2


def test_ecosystem_has_the_required_diagrams():
    """The brief asks for an integrated ecosystem diagram showing the
    coordination strategy."""
    text = DOCS["ecosystem"]
    assert "```mermaid" in text
    assert "flowchart" in text and "sequenceDiagram" in text
    assert "Centralised vs federated" in text or "centralised" in text.lower()


# ── Claims must match the code ──────────────────────────────────────────────

def test_cited_tests_actually_exist():
    """Every test named as evidence in the ecosystem doc must be real,
    otherwise the argument rests on nothing."""
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", DOCS["ecosystem"] + DOCS["governance"]))
    assert named, "no tests are cited as evidence"
    source = "\n".join(p.read_text(encoding="utf-8")
                       for p in Path("simulator/tests").glob("test_*.py"))
    for name in named:
        assert f"def {name}(" in source, f"{name} is cited but does not exist"


def test_topics_in_docs_match_the_code():
    from commands import TOPIC_ROOT
    for name in ("ecosystem", "architecture"):
        assert f"{TOPIC_ROOT}/" in DOCS[name]


def test_layout_numbers_match_the_docs():
    from building import load_building
    b = load_building()
    installed = sum(r.hvac_max_power_w for r in b.all_rooms()) / 1000.0
    assert f"{b.power_budget_kw:.0f} kW" in DOCS["ecosystem"] + DOCS["governance"] \
        or str(b.power_budget_kw) in DOCS["roi_roadmap"] + DOCS["ecosystem"]
    assert f"{installed:.1f}" in Path("data/building_layout.json").read_text(
        encoding="utf-8")


def test_nudge_cap_is_quoted_correctly():
    from floor_twin import MAX_NUDGE_C
    for name in ("ecosystem", "governance"):
        assert f"{MAX_NUDGE_C}" in DOCS[name], (
            f"{name}.md does not quote the real nudge cap {MAX_NUDGE_C}")


def test_governance_does_not_claim_the_pilot_is_secure():
    """The broker really is anonymous and unencrypted. Saying otherwise would
    be the most damaging possible inaccuracy in this document."""
    text = DOCS["governance"]
    assert "allow_anonymous" in text
    assert "not secure" in text.lower() or "pilot posture" in text.lower()
    conf = Path("mosquitto/config/mosquitto.conf").read_text(encoding="utf-8")
    if "allow_anonymous true" in conf:
        assert "anonymous" in text.lower()


def test_roi_labels_measured_versus_assumed():
    """Unsourced numbers are worse than none."""
    text = DOCS["roi_roadmap"]
    assert "Measured" in text and "Assumed" in text
    assert "simulated" in text.lower()


def test_roi_admits_the_negative_npv():
    """The analysis finds a negative NPV at six units. Burying that would make
    the whole document untrustworthy."""
    text = DOCS["roi_roadmap"]
    assert "NPV" in text
    assert "negative" in text.lower() or "−€" in text or "-€" in text


def test_model_metrics_are_quoted_consistently():
    """Docs cite PR-AUC and recall; they must match feature_spec.json."""
    pr_auc = SPEC["metrics"]["pr_auc"]
    recall = SPEC["metrics"]["recall"]
    text = DOCS["roi_roadmap"] + DOCS["governance"] + CARD
    assert f"{pr_auc:.2f}" in text or f"{pr_auc}" in text
    assert f"{recall:.3f}" in text or f"{recall}" in text


def test_fairness_finding_is_stated_in_governance():
    """The 100% false-negative rate on the wet lab is the most important
    ethical finding; it must not be softened away."""
    text = DOCS["governance"]
    assert "lab-a" in text
    assert "1.000" in text or "100 %" in text or "100%" in text


def test_human_approval_is_documented_everywhere_it_matters():
    for name in ("ecosystem", "governance"):
        assert "approval" in DOCS[name].lower()
    assert "requires_human_approval" in DOCS["governance"]


def test_docs_cross_reference_each_other():
    assert "ecosystem.md" in DOCS["architecture"]
    assert "governance.md" in DOCS["architecture"]
    assert "model_card.md" in DOCS["governance"]
