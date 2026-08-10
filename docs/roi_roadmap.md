# ROI and Deployment Roadmap

Every figure below is either **measured** in the simulation or **assumed** for a
real building, and each is labelled. Unsourced numbers are worse than none.

> **The caveat that governs everything here:** the system is built on simulated
> telemetry. The failure *physics* is calibrated against the real UCI AI4I 2020
> dataset, but degradation *rates* were chosen so failures occur inside a
> simulated year. Every benefit figure must be revalidated against real
> telemetry before it is committed to a budget. This is a Phase-1 exit criterion,
> not a footnote.

---

## 1. Where the value actually is

Three candidate benefits. One of them is much smaller than the pitch would like,
and saying so is the point.

### 1a. Fan energy from clogged filters — **small**

Measured directly from the 365-day trace (`data/building_telemetry.csv`):

| Measured | Value |
|---|---|
| Mean fan draw, filter < 10 % clogged | 216.7 W |
| Mean fan draw, filter > 60 % clogged | 239.2 W |
| Penalty | **+10.4 %** |
| Excess fan energy, whole building, 1 year | **620 kWh** |

At €0.25/kWh that is **≈ €155/year**. Negligible against any plausible project
cost, and a pitch that leads with "energy savings from predictive maintenance"
would be overselling it.

**What is *not* modelled and is probably larger:** a restricted filter also
reduces cooling *capacity*, so the compressor runs longer to hit the same
setpoint. Our physics models the fan-power penalty but not that capacity loss.
Published HVAC field studies attribute several percent of total cooling energy to
filter condition — on this building's cooling load that would dominate the fan
term. **We do not claim it, because we did not measure it.**

### 1b. Avoided unplanned outages — **the dominant term**

The simulation records 391 failure events per year across six units, but that
rate is accelerated by design and must not be used as a business input. For the
ROI we use a conservative real-world rate.

| Input | Value | Source |
|---|---|---|
| Unplanned HVAC failures per unit per year | 0.5 | **Assumed** — conservative for commercial units on mixed maintenance |
| Units | 6 | Measured (layout) |
| Baseline unplanned failures/year | 3.0 | Derived |
| Model recall, in-distribution | **0.990** | Measured (`feature_spec.json`) |
| Fraction convertible to planned work | 0.80 | **Assumed** — not every early warning gives usable lead time |
| Cost per unplanned outage | €2,000 | **Assumed** — emergency callout, overtime, at-risk lab samples |
| Cost of the planned service that replaces it | €300 | **Assumed** |

Avoided cost = 3.0 × 0.99 × 0.80 × (€2,000 − €300) ≈ **€4,039/year**.

### 1c. Calendar-based → condition-based servicing — **moderate**

| Input | Value | Source |
|---|---|---|
| Planned services per unit per year, calendar-based | 4 | **Assumed** (quarterly) |
| Units | 6 | Measured |
| Reduction from condition-based scheduling | 25 % | **Assumed** — typical range 20–30 % |
| Cost per service visit | €300 | **Assumed** |

Saving = 24 × 0.25 × €300 = **€1,800/year**.

The simulation cannot validate this one at all: its maintenance intervals are
compressed to force failures inside a year (Lab A receives 95 services), so the
service-count reduction is an industry assumption, not a result.

### Benefit summary

| Stream | €/year | Confidence |
|---|---|---|
| Fan energy | 155 | **Measured** in simulation |
| Avoided unplanned outages | 4,039 | Assumed rate × measured recall |
| Condition-based servicing | 1,800 | Assumed |
| **Total** | **≈ €5,994** | |
| *Cooling capacity loss* | *unquantified* | *Not modelled — likely additional* |

---

## 2. Costs

| Item | Cost | Basis |
|---|---|---|
| Sensors per unit (vibration, winding temp, current) | €400 × 6 = €2,400 | **Assumed**, commodity industrial IoT |
| Gateway / broker hardware | €600 | **Assumed** |
| Integration and commissioning | €10,000 | **Assumed**, ~15 engineer-days |
| Security hardening (mTLS, ACLs, audit log — see governance §1) | €4,000 | **Assumed** |
| **One-off total** | **€17,000** | |
| Model monitoring and annual recalibration | €2,500/year | **Assumed**, ~4 engineer-days |
| Broker/compute hosting | €400/year | **Assumed** |
| **Recurring total** | **€2,900/year** | |

Security hardening is a line item rather than an afterthought, because the pilot
posture in governance §1 is explicitly not deployable.

---

## 3. Payback and NPV

Net annual benefit = €5,994 − €2,900 ≈ **€3,100/year**.

| | Value |
|---|---|
| Simple payback | €17,000 ÷ €3,100 ≈ **5.5 years** |
| 3-year NPV @ 8 % | €3,100 × 2.577 − €17,000 = **−€9,011** |
| 5-year NPV @ 8 % | €3,100 × 3.993 − €17,000 = **−€4,622** |

### The finding this project will not hide

**On six HVAC units, this does not pay for itself.** NPV is negative over five
years. The one-off integration cost is close to fixed regardless of building
size, while benefits scale with the number of units — so the economics are a
question of scale, not of whether the technology works.

Break-even unit count, holding the one-off cost fixed and scaling benefits and
per-unit hardware linearly:

| Units | Benefit/yr | Recurring/yr | One-off | Payback |
|---|---|---|---|---|
| 6 | €5,994 | €2,900 | €17,000 | 5.5 yr |
| 12 | €11,988 | €3,300 | €19,400 | 2.2 yr |
| 24 | €23,976 | €4,100 | €24,200 | 1.2 yr |
| 50 | €49,950 | €5,700 | €34,600 | **0.8 yr** |

**The honest recommendation: do not deploy this on one building for the savings.
Deploy the pilot to prove the model on real telemetry, then scale to the campus
where the economics work.** That is what the roadmap below is shaped around.

### Sensitivity

Payback at 6 units, varying the two most uncertain assumptions:

| Outage cost ↓ / Failures per unit → | 0.25/yr | 0.5/yr | 1.0/yr |
|---|---|---|---|
| €1,000 | 10.6 yr | 8.0 yr | 5.4 yr |
| €2,000 | 7.1 yr | **5.5 yr** | 3.9 yr |
| €5,000 | 4.5 yr | 3.4 yr | 2.3 yr |

Even the most favourable cell at this scale is 2.3 years. The conclusion is
robust to the assumptions: **scale, not tuning, is what makes this pay.**

---

## 4. Roadmap

### Phase 0 — Pilot *(complete: this project)*

Six simulated twins with distinct wear characters, federated coordination, a
five-class fault model, and the governance analysis.

- **Exit criteria met:** full suite green; closed loop verified end to end;
  fairness audit published and a severe early finding corrected at its root;
  limitations documented.
- **Risk carried forward:** everything rests on simulated data.

### Phase 1 — Instrumented pilot, one floor *(3–6 months)*

Put real sensors on three units and run the twin alongside existing controls,
**observe-only**.

- **Entry:** Phase 0 complete; security hardening from governance §1 implemented;
  broker on mTLS with ACLs and an audit log.
- **Exit:** ≥3 months of real telemetry; model **recalibrated** on it; the
  fairness audit repeated on real data; measured failure rate and outage cost
  replacing the assumptions in §1b.
- **Named risk:** the real failure rate is far below the simulated one, so three
  months may contain **zero** events. Mitigation: run the model in shadow mode
  and evaluate on precursor agreement rather than waiting for failures.

### Phase 2 — Full building *(6–12 months)*

All units on one building; work orders enter the real maintenance workflow.

- **Entry:** Phase 1 recalibration accepted; per-mode recall acceptable *or* the
  physics guard proven to cover the gap.
- **Exit:** work orders actioned by facilities for one full maintenance cycle;
  measured reduction in unplanned outages.
- **Named risk:** alert fatigue. The threshold is deliberately tuned to over-call
  (13:1 cost ratio), so precision is 0.66 — a third of work orders will be
  unnecessary. Mitigation: review the cost ratio against real dispatch costs and
  re-derive the threshold.

### Phase 3 — Campus *(12–24 months)*

Multiple buildings; this is where the economics become positive (§3).

- **Entry:** Phase 2 shows measured benefit; ≥24 units in scope.
- **Exit:** positive measured NPV.
- **Named risk:** models will not transfer between buildings — measured PR-AUC
  drops from 0.92 to 0.26 on unseen equipment, and the model is partly
  schedule-dependent (`hour_cos`). Mitigation: per-building calibration, or
  federated learning that shares model weights without sharing occupancy data
  (which also preserves the privacy property in governance §4).

### Phase 4 — Bounded autonomy *(24 months+)*

Only after Phase 3.

- **Entry:** ≥12 months of work orders where model recommendations matched
  technician findings at an agreed rate.
- **Scope:** automatic scheduling of *planned* servicing. **Never** automatic
  shutdown — the human-approval requirement in governance §5 is permanent.
- **Named risk:** automation complacency. Mitigation: periodic blind audits where
  technicians assess units without seeing the model's score.

---

## 5. What would change this analysis

| If | Then |
|---|---|
| Cooling-capacity loss from clogging were measured | Energy benefit could rise from €155 to a materially larger figure; §1a says why we did not claim it |
| Real outage cost exceeds €5,000 (labs with irreplaceable samples) | Payback falls under 3.5 years even at 6 units |
| Real failure rate is under 0.25/unit/year | The case collapses at this scale; go straight to campus or stop |
| The HDF blind spot is closed with more data | Coverage of the highest-consequence room improves — currently the weakest link |
