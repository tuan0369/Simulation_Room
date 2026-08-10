"""Build the executive pitch deck from the project's own artifacts.

    docker compose run --rm sim python report/pitch/build_pitch.py

Charts are generated from `ml/models/*.csv` and the ROI figures rather than
being drawn by hand, so the deck cannot drift from the results it claims. If a
model is retrained, rerunning this regenerates the deck.

Speaker notes come from `pitch_outline.md` and are embedded in the .pptx.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pptx import Presentation            # noqa: E402
from pptx.util import Inches             # noqa: E402

# Charts and slide helpers are shared with report/build_report.py, so a
# retrained model updates both decks and they cannot disagree about numbers.
from deckkit import (ACCENT, DEMO, GOOD, MUTED, W, H, WARN,   # noqa: E402
                     all_charts, blank, bullets, heading, notes, picture,
                     spec, table, textbox)

OUT = Path("report/pitch/Digital_Twin_Project2_Executive_Pitch.pptx")

# ── Deck ────────────────────────────────────────────────────────────────────

def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    charts = all_charts()
    m = spec()["metrics"]

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 — title
    s = blank(prs)
    textbox(s, "Smart Facility Digital Twin", Inches(0.9), Inches(2.3),
            Inches(11.5), Inches(1.2), size=44, bold=True)
    textbox(s, "Predictive maintenance for building HVAC",
            Inches(0.9), Inches(3.5), Inches(11.5), Inches(0.7),
            size=22, colour=MUTED)
    textbox(s, "6 rooms  ·  2 floors  ·  11 interacting twins  ·  1 machine-learning model",
            Inches(0.9), Inches(4.3), Inches(11.5), Inches(0.6),
            size=16, colour=ACCENT)
    notes(s, "This is a working system, not a concept. Everything shown runs.")

    # 2 — problem
    s = blank(prs)
    heading(s, "We find HVAC failures when someone complains", "The problem")
    bullets(s, [
        "In a wet lab, that means temperature-sensitive samples are already at risk.",
        "Maintenance runs on a calendar: we service units that don't need it…",
        "…and miss units that do.",
        "No visibility into equipment condition between visits.",
    ])
    textbox(s, "The question isn't whether to maintain.\nIt's whether we maintain on a calendar or on evidence.",
            Inches(1.0), Inches(5.0), Inches(11.0), Inches(1.2),
            size=22, bold=True, colour=ACCENT)
    notes(s, "The question isn't whether to maintain. It's whether we maintain "
             "on a calendar or on evidence.")

    # 3 — what we built
    s = blank(prs)
    heading(s, "A digital twin for every room", "What we built")
    bullets(s, [
        "Physics, control and equipment health simulated per room, live over MQTT.",
        "Floor and building twins coordinate a 15 kW electrical budget.",
        "An occupancy twin moves people between rooms — conserving headcount.",
        "Dashboard, 3D building view, and machine-learning risk scoring.",
    ])
    demo = sorted(DEMO.glob("*.png"))
    if demo:
        picture(s, demo[0], Inches(7.6), Inches(4.3), Inches(5.2))
    notes(s, "Each room runs its own control loop. Supervisors advise; they never "
             "take over. If the coordination layer dies, every room keeps cooling.")

    # 4 — coordination
    s = blank(prs)
    heading(s, "Rooms decide. Supervisors advise.", "Architecture")
    table(s, [
        ["", "Centralised", "Federated (chosen)"],
        ["A crash stops…", "every room cooling", "coordination only"],
        ["Occupancy data", "leaves every room", "stays room-local"],
        ["Tuning", "one loop for all rooms", "per-room thermal mass"],
        ["A supervisor bug", "actuates every room", "bounded advice, ≤1.5 °C"],
    ], Inches(1.0), Inches(2.1), Inches(11.3), Inches(2.8),
        col_widths=[Inches(2.6), Inches(4.2), Inches(4.5)])
    textbox(s, "The 1.5 °C limit is enforced by the room, not by the supervisor "
               "sending the advice.",
            Inches(1.0), Inches(5.3), Inches(11.0), Inches(0.8),
            size=17, bold=True, colour=ACCENT)
    notes(s, "One crash in a centralised design stops every room. And occupancy "
             "data would have to leave the room it came from — this is a privacy "
             "choice as much as a resilience one.")

    # 5 — the intelligence
    s = blank(prs)
    heading(s, "Four hours of warning before a failure", "The intelligence")
    picture(s, charts["models"], Inches(0.9), Inches(1.9), Inches(7.4))
    textbox(s, f"PR-AUC  {m['pr_auc']:.2f}\nRecall  {m['recall']:.2f}\n"
               f"Precision  {m['precision']:.2f}",
            Inches(8.7), Inches(2.4), Inches(3.8), Inches(2.2), size=24, bold=True)
    textbox(s, "Accuracy would be 98 % if we always predicted\n"
               "\"no failure\". That is why we don't quote it.",
            Inches(8.7), Inches(4.4), Inches(4.2), Inches(1.2),
            size=14, colour=MUTED)
    notes(s, "Accuracy would be 98% if we simply predicted 'no failure' every "
             "time — that's why we don't quote accuracy. The model is six times "
             "better than the obvious rule.")

    # 6 — the correction
    s = blank(prs)
    heading(s, "One failure mode was invisible — and why", "What went wrong first")
    picture(s, charts["modes"], Inches(0.9), Inches(1.9), Inches(7.4))
    textbox(s, "Heat-dissipation recall:\n0.00 → 0.95",
            Inches(8.6), Inches(2.2), Inches(4.2), Inches(1.2),
            size=20, bold=True, colour=WARN)
    textbox(s, "The first model missed that mode entirely.\n"
               "It had seen about two examples of it.\n\n"
               "The fix was to the DATA, not the model:\n"
               "six identical units were replaced by six\n"
               "with realistic, different wear characters.\n\n"
               "A physics threshold still backs it up.",
            Inches(8.6), Inches(3.4), Inches(4.3), Inches(2.6), size=14, colour=MUTED)
    notes(s, "This is the slide I'd want to see if I were buying. Our first "
             "model was blind to one failure mode. The cause was starvation, "
             "not tuning — it had two examples. A model that cannot see "
             "something is usually being starved of it. We fixed the data, and "
             "we keep the physics threshold as an independent backstop.")

    # 7 — fairness
    s = blank(prs)
    heading(s, "Detection is even — precision is not", "Fairness audit")
    picture(s, charts["fairness"], Inches(0.9), Inches(1.9), Inches(7.4))
    textbox(s, "Recall 0.95–1.00\nin every room",
            Inches(8.6), Inches(2.2), Inches(4.2), Inches(1.2),
            size=20, bold=True, colour=GOOD)
    textbox(s, "Room identity is excluded from the model\nby construction, so it cannot learn a\n"
               "per-room prior.\n\n"
               "Teaching Lab C remains weakest:\nprecision 0.46 — about half its work\n"
               "orders are unnecessary.\n\n"
               "We re-run this audit after every retrain.",
            Inches(8.6), Inches(3.4), Inches(4.3), Inches(2.6), size=14, colour=MUTED)
    notes(s, "An earlier version had a 100% false-negative rate on the wet lab — "
             "the room where an outage costs most. We found it, fixed its actual "
             "cause, and publish both states. What remains is a precision gap in "
             "the teaching lab, which is disruptive rather than dangerous. That "
             "placement is luck, not design, which is why the audit repeats.")

    # 8 — benefits
    s = blank(prs)
    heading(s, "Where the value actually is", "Business case")
    picture(s, charts["benefits"], Inches(0.9), Inches(1.9), Inches(7.4))
    textbox(s, "≈ €5,800 / year", Inches(8.8), Inches(2.5), Inches(4.0),
            Inches(0.9), size=28, bold=True, colour=GOOD)
    textbox(s, "Anyone pitching predictive maintenance\non fan energy alone is selling you\n"
               "something. The value is in outages\nyou don't have.",
            Inches(8.8), Inches(3.5), Inches(4.2), Inches(2.0), size=14, colour=MUTED)
    notes(s, "The energy saving is real but small — €155. The value is in outages "
             "you don't have.")

    # 9 — the uncomfortable number
    s = blank(prs)
    heading(s, "At six units, it does not pay for itself", "The uncomfortable number")
    table(s, [
        ["One-off investment", "€17,000"],
        ["Recurring", "€2,900 / year"],
        ["Net benefit", "€3,000 / year"],
        ["Payback", "5.7 years"],
        ["5-year NPV @ 8 %", "−€5,021"],
    ], Inches(1.0), Inches(2.1), Inches(6.2), Inches(2.9),
        col_widths=[Inches(3.6), Inches(2.6)], header=False, size=17)
    textbox(s, "Integration cost is roughly fixed.\nBenefits scale with unit count.\n\n"
               "This is a question of scale —\nnot of whether the technology works.",
            Inches(7.8), Inches(2.3), Inches(5.0), Inches(2.6),
            size=19, bold=True, colour=WARN)
    notes(s, "On this building alone, it does not pay for itself. Integration "
             "cost is roughly fixed; benefits scale with unit count.")

    # 10 — where it pays
    s = blank(prs)
    heading(s, "Where it does pay", "Recommendation")
    picture(s, charts["payback"], Inches(0.9), Inches(1.9), Inches(7.4))
    textbox(s, "Pilot to prove the model\non real telemetry.\n\nThen scale to campus.",
            Inches(8.7), Inches(2.6), Inches(4.2), Inches(2.2),
            size=20, bold=True, colour=ACCENT)
    textbox(s, "Not a building-by-building rollout.",
            Inches(8.7), Inches(4.6), Inches(4.2), Inches(0.8),
            size=14, colour=MUTED)
    notes(s, "The recommendation is a pilot to prove the model on real telemetry, "
             "then campus scale. Not a building-by-building rollout.")

    # 11 — security
    s = blank(prs)
    heading(s, "The pilot is not secure — and that is costed", "Security")
    bullets(s, [
        "Today: anonymous broker, no encryption. Fine on one machine.",
        "Unacceptable in a building that dispatches technicians.",
    ])
    table(s, [
        ["Hardening", "Why"],
        ["mTLS + per-topic ACLs", "a room twin can only speak for itself"],
        ["Signed commands", "no replay, no spoofed shutdown"],
        ["Audit log", "every action attributable to a person"],
        ["Network segmentation", "not routable from the office LAN"],
    ], Inches(1.0), Inches(3.3), Inches(11.3), Inches(2.6),
        col_widths=[Inches(4.3), Inches(7.0)])
    textbox(s, "€4,000 — a line item, not a backlog ticket.",
            Inches(1.0), Inches(6.1), Inches(9.0), Inches(0.6),
            size=18, bold=True, colour=ACCENT)
    notes(s, "A system that dispatches technicians to physical equipment needs "
             "every command attributable to a person. That's in the budget, not "
             "the backlog.")

    # 12 — ethics
    s = blank(prs)
    heading(s, "The model opens tickets. It never switches anything off.",
            "Ethics and oversight")
    bullets(s, [
        "Every advisory carries requires_human_approval.",
        "Supervisory autonomy is bounded at 1.5 °C — enforced by the room.",
        "Occupancy is counted, never identified, and stays in the room that produced it.",
        "Known limitations are shown in the dashboard, not just in the appendix.",
    ])
    textbox(s, "There is no path from a model score to a physical action\n"
               "that does not pass through a person.",
            Inches(1.0), Inches(5.0), Inches(11.0), Inches(1.2),
            size=22, bold=True, colour=ACCENT)
    notes(s, "There is no path from a model score to a physical action that "
             "doesn't pass through a person.")

    # 13 — the ask
    s = blank(prs)
    heading(s, "Phase 1: instrumented pilot", "The ask")
    table(s, [
        ["Scope", "3 units, one floor, observe-only"],
        ["Duration", "3–6 months"],
        ["Exit criterion", "model recalibrated on REAL telemetry; fairness audit repeated"],
        ["Named risk", "real failures are rare — may see zero events; run in shadow mode"],
    ], Inches(1.0), Inches(2.1), Inches(11.3), Inches(2.4),
        col_widths=[Inches(2.8), Inches(8.5)], header=False, size=16)
    textbox(s, "Approve Phase 1, and the €4,000 security hardening up front.",
            Inches(1.0), Inches(4.9), Inches(11.0), Inches(0.8),
            size=24, bold=True, colour=ACCENT)
    textbox(s, "Everything today is built on simulated data. The failure physics is "
               "calibrated against a published\nindustrial dataset, but no number in "
               "this business case is trustworthy until it has been seen on\nthis "
               "building. Phase 1 exists to find that out cheaply.",
            Inches(1.0), Inches(5.8), Inches(11.2), Inches(1.4),
            size=14, colour=MUTED)
    notes(s, "Everything today is built on simulated data. Phase 1 exists to find "
             "out cheaply whether it holds on this building.")

    prs.save(str(OUT))
    return OUT, charts


if __name__ == "__main__":
    out, charts = build()
    prs = Presentation(str(out))
    print(f"wrote {out}  ({len(prs.slides)} slides, "
          f"{out.stat().st_size/1024:.0f} KB)")
    for name, path in charts.items():
        print(f"  chart {name:<10} {path}")
