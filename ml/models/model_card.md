# Model Card — HVAC Failure Prediction

**Version** 1.0.0 · **Date** 2026-08-10 · **Owner** Smart Lab Digital Twin project

Reproduce with:
```bash
docker compose run --rm sim python simulator/dataset_generator.py   # 365-day trace
docker compose run --rm sim python ml/train.py
```

---

## 1. What this is

Two models plus one rule, serving the maintenance planning of a 2-floor,
6-room smart facility.

| Component | Type | Job |
|---|---|---|
| `failure_classifier.joblib` | HistGradientBoosting, 4-class | Predict the *fault type* (`none` / `hdf` / `osf` / `pwf`) within 4 hours. Risk = 1 − P(none) |
| `rul_regressor.joblib` | Linear regression | Estimate remaining useful life in hours |
| HDF physics guard | Threshold rule | Independent alarm on motor temperature approaching its insulation limit |

**Intended use.** Raising *maintenance work orders* for human approval. It ranks
which HVAC unit needs attention next and roughly when.

**Out of scope.** It must not command equipment. Nothing in this system shuts
down a unit or changes a setpoint on a model score — the building twin emits
advisories carrying `requires_human_approval: true`, and a technician decides.

---

## 2. Training data

`data/building_telemetry.csv` — a 365-day simulated trace of six HVAC units:
630,720 rows, 228 failure events, 1.74 % positive rate on the 4-hour horizon.
See [`data/README.md`](../../data/README.md) for full statistics.

**It is simulated.** This is the single most important limitation and it is not
hedged: the models have never seen a real building. What makes the physics
non-arbitrary is that the failure thresholds are inherited from the **UCI AI4I
2020 Predictive Maintenance Dataset**, whose published rules were verified to
reproduce exactly against the real data (the documented heat-dissipation rule
selects 115 rows, and all 115 are labelled HDF). Degradation *rates*, however,
were chosen so failures occur within a simulated year — they are the most
arbitrary numbers in the model.

**Deployment therefore requires recalibration** against at least three months of
real telemetry before any output is trusted. This is a Phase-1 entry criterion
in the roadmap, not a footnote.

### Splits

| Split | Definition | Rows | Positives |
|---|---|---|---|
| Train | Days 0–255, five rooms | 367,200 | 6,726 |
| Test (time) | Days 256–365, same five rooms | 158,400 | 3,026 |
| Test (unseen room) | Days 256–365, `f2/office`, never trained on | 31,680 | 529 |

Splits are **temporal**, never a random shuffle. Rows five minutes apart are
near-duplicates; a shuffled split would place a row's own neighbours in the
training set and inflate scores to a meaningless ~0.99.

---

## 3. Results

Evaluated on the held-out final 30 % of the year.

| Model | PR-AUC | ROC-AUC | Recall | Precision | Recall @ 90 % precision |
|---|---|---|---|---|---|
| Always predict "no failure" | 0.018 | 0.500 | 0.000 | — | — |
| Single threshold `motor_temp > 80` | 0.163 | 0.760 | 0.009 | 0.248 | — |
| Logistic regression | 0.509 | 0.974 | 0.904 | 0.256 | 0.043 |
| Random forest | 0.934 | 0.992 | 0.947 | 0.585 | 0.856 |
| **Gradient boosting (shipped)** | **0.924** | **0.996** | **0.950** | **0.664** | **0.841** |

**Accuracy is not reported as a headline.** At a 1.7 % positive rate, predicting
"no failure" every time scores 98.3 % accuracy and is worthless. PR-AUC is the
primary metric.

**The model earns its place**: PR-AUC 0.92 against 0.16 for the best single
threshold. But see §4 — that headline is not true of every failure mode.

Random forest ranks marginally higher on PR-AUC (0.934 vs 0.924); gradient
boosting is shipped because it is ~17 % cheaper at its own best operating point,
and cost is the stated decision criterion.

### Decision threshold

**0.0053**, chosen by minimising expected cost, not left at 0.5.

| Assumption | Value |
|---|---|
| Cost of a missed failure (unplanned outage, emergency callout, lab risk) | €2,000 |
| Cost of a false alarm (unnecessary inspection) | €150 |

These are **assumptions, not measurements**. The ROI analysis reuses them and
must carry the same caveat. A 13:1 cost ratio pushes the threshold very low —
the model is deliberately tuned to over-call rather than miss.

### Remaining useful life

| Metric | Value |
|---|---|
| MAE | 14.6 hours |
| R² | 0.812 |
| Predict-the-mean baseline MAE | 38.1 hours |

Trained only on uncensored rows. Rows pinned at the 168-hour censoring horizon
are not observations of a real remaining life, and training on them would teach
the model to predict the censoring constant.

---

## 4. Known failure: the model cannot see heat-dissipation failures

| Fault mode | Test positives | Recall, model alone | Recall, with physics guard |
|---|---|---|---|
| `osf` overstrain | 2,640 | 0.983 | 0.983 |
| `pwf` power | 96 | 1.000 | 1.000 |
| **`hdf` heat dissipation** | **97** | **0.000** | **0.588** |

The training set contains ~96 HDF rows — about **two events**. No model
generalises a failure mode from two examples, and this one does not.

This is not a tuning problem to be papered over. Heat-dissipation failure is
*defined* by motor temperature crossing the 85 °C Class-F insulation limit, so
it has a direct physical precursor: the temperature climbing toward it. That is
a threshold problem, not a learning problem.

**Mitigation.** A physics guard runs as an **independent alarm channel**: a ramp
from 0 at 70 °C to 1 at the 85 °C limit. It recovers HDF recall to 0.59.

It is deliberately *not* blended into the ML risk score. Folding it in raised
HDF recall but dragged server-room precision from 0.81 to 0.33, because it fires
on any hot motor regardless of the actual fault. Two independent detectors,
each reported on its own terms, is both more honest and more useful to whoever
reads the alert.

**The general lesson, which the executive pitch should not omit: ML is not
uniformly better than rules.** It substantially beats any single threshold for
cumulative faults, and loses to a thermostat for a fault with a direct physical
precursor.

---

## 5. Fairness audit

Per-room performance on the test period, model channel only.

| Room | Positive rate | PR-AUC | Recall | Precision | FN rate |
|---|---|---|---|---|---|
| `f1/lab-a` | 0.31 % | 0.014 | **0.000** | 0.000 | **1.000** |
| `f1/lab-b` | 0.91 % | 0.822 | 1.000 | 0.447 | 0.000 |
| `f1/server-room` | 4.24 % | 0.997 | 1.000 | 0.836 | 0.000 |
| `f2/lab-c` | 2.42 % | 0.882 | 0.945 | 0.558 | 0.055 |
| `f2/meeting-room` | 1.06 % | 0.989 | 0.994 | 0.717 | 0.006 |

**There is severe disparity, and it is not subtle.** `f1/lab-a` has a 100 %
false-negative rate: the model misses every one of its failures.

**Why.** Not because of the room's identity — room identity is excluded from
the features by construction (§6). The cause is that *failure modes are
segregated by room*. `f1/lab-a` is the most aggressively maintained unit
(serviced every 6–10 days), so it never accumulates the runtime or wear that
produces overstrain failures. All three of its failures in a year are HDF — the
one mode the model cannot see. The per-room disparity is a per-*mode* disparity
wearing a different hat.

**Who is harmed.** A wet lab is the worst room in the building to lose cooling
in: it holds temperature-sensitive samples and reagents. The model is blindest
precisely where an outage costs most.

**Mitigation now in place:**
1. The HDF physics guard raises `f1/lab-a` recall from 0.000 to 0.536.
2. The disparity is published here and surfaced in the dashboard, rather than
   being averaged away into a single headline number.

**Still outstanding:** even with the guard, `f1/lab-a` recall (0.54) is far
below the server room's (1.00). Anyone relying on this system should treat
well-maintained, HDF-prone units as **not adequately covered** and keep
calendar-based servicing for them. Closing the gap needs more HDF examples,
which means either a longer observation window or deliberate run-to-failure
testing.

### Generalisation to unseen equipment

On `f2/office`, held out of training entirely: **PR-AUC 0.261, recall 0.563**.

Substantially worse than on rooms it has seen — a new unit should not be trusted
to the same degree until it has contributed its own history.

An earlier configuration held out `f2/meeting-room` instead and scored 0.08. That
number was misleading: meeting-room is the only never-serviced unit, so its
`runtime_hours` reaches 132 h against a 113 h training maximum. That measured
extrapolation to an unseen *maintenance regime*, not room-to-room transfer.
Both limits are real; they are different limits.

---

## 6. Transparency

### What drives a prediction

Permutation importance (top features, test period):

| Feature | Importance | Physical reading |
|---|---|---|
| `runtime_hours` | 0.281 | Hours since the last motor service — the overstrain driver |
| `motor_room_delta_mean_2h` | 0.254 | Motor-to-room temperature gap: without a gradient the motor cannot shed heat |
| `vibration_mm_s_mean_6h` | 0.158 | Bearing condition (ISO 10816) |
| `hour_cos` | 0.058 | Time of day, a proxy for the occupancy-driven duty cycle |
| `torque_nm` | 0.051 | Shaft load; combined with runtime this is the AI4I overstrain rule |

These are consistent with the AI4I failure rules the physics was calibrated
against, which is a sanity check on both.

`hour_cos` ranking fourth deserves a caveat: the model has partly learned *when*
the building is busy, not only how worn the equipment is. That will not transfer
to a building on a different schedule.

### What is deliberately excluded

`twin_id`, `floor`, `room_id`, `room_profile`, `segment_id` — all identity
columns — are excluded from the feature set, enforced by test.

The reason is concrete. In this data `f1/lab-a` fails 30× less often than the
server room purely because of its maintenance *policy*. An identity-aware model
would learn "lab-a is safe" and stay silent when its filter finally does clog.
Risk must follow condition, so two rooms in identical condition receive
identical scores — also enforced by test.

Absolute date is excluded for the same reason: it would let the model memorise
when particular failures happened.

### Runtime transparency

Every risk message carries `model_version`, so a stale retained MQTT message is
identifiable. The dashboard shows the driving factor alongside the probability;
a bare number with no provenance is exactly the transparency failure this
section exists to prevent.

---

## 7. Limitations, in one place

1. **Trained on simulated data.** Requires recalibration on ≥ 3 months of real
   telemetry before any output is trusted.
2. **Blind to heat-dissipation failure** (recall 0.000 alone, 0.588 with the
   physics guard). ~2 training events.
3. **`f1/lab-a` is inadequately covered** — a 100 % false-negative rate from the
   model channel, in the room where an outage is most costly.
4. **Degrades on unseen equipment** (PR-AUC 0.26 vs 0.92).
5. **Cannot extrapolate to unseen maintenance regimes** — a never-serviced unit
   runs beyond the training range of `runtime_hours`.
6. **Partly schedule-dependent** (`hour_cos`); will not transfer unchanged to a
   building with different occupancy patterns.
7. **Cost figures are assumptions**, not measurements. The threshold, and the
   ROI case built on it, move if the real ratio differs.
8. **No concept-drift monitoring yet.** Equipment replacement or a maintenance
   policy change invalidates the model silently.

---

## 8. Human oversight

The model opens tickets; it never turns anything off. Every advisory carries
`requires_human_approval: true`. Autonomy elsewhere in the system is separately
bounded: supervisory twins may nudge a room's setpoint by at most 1.5 °C, and
that limit is enforced by the room itself rather than by the supervisor sending
the advice — so no software decision, model or otherwise, can make a room unsafe.
