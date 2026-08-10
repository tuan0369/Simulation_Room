# Executive pitch — outline and speaker notes

Audience: facilities director, IT/security lead, finance. **Not** engineers.
Target: 12 minutes plus questions.

Every figure traces to [`docs/roi_roadmap.md`](../../docs/roi_roadmap.md),
[`docs/governance.md`](../../docs/governance.md) or
[`ml/models/model_card.md`](../../ml/models/model_card.md). The deck is generated
from those sources by `build_pitch.py`, so it cannot quietly drift from them.

**The narrative arc is deliberate:** what we built → what it can do → *what it
cannot do* → what it costs → what we recommend. Slides 6 and 9 are the ones that
make the rest credible. A pitch that only claims wins invites the audience to go
looking for the losses.

---

### 1. Title
Smart Facility Digital Twin — predictive maintenance for building HVAC.
6 rooms, 2 floors, 11 interacting twins, one machine-learning model.

> **Say:** This is a working system, not a concept. Everything shown runs.

### 2. The problem
HVAC failures are found when someone complains. In a wet lab that means
temperature-sensitive samples are already at risk. Maintenance is calendar-based:
we service units that don't need it and miss units that do.

> **Say:** The question isn't whether to maintain. It's whether we maintain on a
> calendar or on evidence.

### 3. What we built
A digital twin per room — physics, control and equipment health — coordinated by
floor and building twins. Live telemetry, a 3D view, a dashboard.

> **Say:** Each room runs its own control loop. Supervisors advise; they never
> take over. If the coordination layer dies, every room keeps cooling.

### 4. Coordination: federated, not centralised
Rooms decide, supervisors advise, authority is bounded at 1.5 °C and the *room*
enforces the limit.

> **Say:** One crash in a centralised design stops every room. And occupancy data
> would have to leave the room it came from — this is a privacy choice as much as
> a resilience one.

### 5. The intelligence
Predicts equipment failure four hours ahead. PR-AUC **0.92** against **0.16** for
the best single-threshold rule. Recall 0.95, precision 0.66.

> **Say:** Accuracy would be 98 % if we simply predicted "no failure" every time —
> that's why we don't quote accuracy. The model is six times better than the
> obvious rule.

### 6. What it *cannot* do — the honesty slide
The model is **blind to heat-dissipation failure** (recall 0.000 alone). Roughly
two such events existed in the training data; no model learns from two examples.
A physics threshold covers it, raising recall to 0.59.

> **Say:** This is the slide I'd want to see if I were buying. ML is not
> uniformly better than rules — it beats thresholds on cumulative wear and loses
> to a thermostat on a fault with a direct physical precursor. We ship both.

### 7. Where it is weakest is where it matters most
Wet Lab A: **100 % false-negative rate** from the model channel. All of its
failures are the one mode the model can't see.

> **Say:** The room the model covers worst is the room where failure costs most.
> We found it, published it, and mitigate it with the thermal guard — but keep
> calendar servicing on that unit. We are not asking you to trust it there.

### 8. Business case — where the value is
| Stream | €/year | Basis |
|---|---|---|
| Fan energy from clogged filters | 155 | **Measured** |
| Avoided unplanned outages | 3,876 | Assumed rate × measured recall |
| Condition-based servicing | 1,800 | Assumed |
| **Total** | **≈ 5,800** | |

> **Say:** The energy saving is real but small — €155. Anyone pitching
> predictive maintenance on fan energy alone is selling you something. The value
> is in outages you don't have.

### 9. The uncomfortable number
One-off €17,000, recurring €2,900/yr. At six units: payback **5.9 years**,
5-year NPV **−€5,420**.

> **Say:** On this building alone, it does not pay for itself. Integration cost
> is roughly fixed; benefits scale with unit count. This is a question of scale,
> not of whether the technology works.

### 10. Where it does pay
| Units | Payback |
|---|---|
| 6 | 5.9 yr |
| 12 | 2.3 yr |
| 24 | 1.3 yr |
| 50 | **0.8 yr** |

> **Say:** The recommendation is a pilot to prove the model on real telemetry,
> then campus scale. Not a building-by-building rollout.

### 11. Security — the honest posture
The pilot broker is anonymous and unencrypted. That is fine on one machine and
unacceptable in a building. Hardening (mTLS, per-topic ACLs, signed commands,
audit log) is a **costed line item**: €4,000.

> **Say:** A system that dispatches technicians to physical equipment needs every
> command attributable to a person. That's in the budget, not the backlog.

### 12. Ethics and human oversight
The model opens tickets. It never switches anything off. Every advisory carries
`requires_human_approval`. Occupancy is counted, never identified, and stays in
the room that produced it.

> **Say:** There is no path from a model score to a physical action that doesn't
> pass through a person.

### 13. Roadmap and the ask
Phase 1 — instrumented pilot, 3 units, observe-only, 3–6 months. Exit criterion:
the model **recalibrated on real telemetry** and the fairness audit repeated.

**The ask:** approval for Phase 1, and the €4,000 security hardening up front.

> **Say:** Everything today is built on simulated data. The failure physics is
> calibrated against a published industrial dataset, but no number in the
> business case is trustworthy until it's been seen on this building. Phase 1
> exists to find that out cheaply.

---

## Numbers appearing in the deck

| Claim | Source |
|---|---|
| PR-AUC 0.92 vs 0.16 baseline | `ml/models/model_comparison.csv` |
| Recall 0.950, precision 0.664 | `ml/models/feature_spec.json` |
| HDF recall 0.000 → 0.588 | `ml/models/recall_by_fault_mode.csv` |
| Lab A false-negative rate 1.000 | `ml/models/fairness_audit.csv` |
| 620 kWh, €155/yr fan energy | `docs/roi_roadmap.md` §1a (measured) |
| Payback 5.9 yr, NPV −€5,420 | `docs/roi_roadmap.md` §3 |
| Security hardening €4,000 | `docs/roi_roadmap.md` §2 |

## Demo screenshots

`build_pitch.py` generates its charts from the model artifacts. Live dashboard
and 3D screenshots must be captured by hand into `report/demo/` and are
referenced on slide 3 if present — there is no browser automation in this
environment, so the build does not fake them.
