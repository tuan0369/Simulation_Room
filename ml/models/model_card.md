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

| Model | PR-AUC | ROC-AUC | Recall | Precision |
|---|---|---|---|---|
| Always predict "no failure" | 0.033 | 0.500 | 0.000 | — |
| Single threshold `motor_temp > 80` | 0.092 | 0.650 | 0.053 | — |
| Logistic regression | 0.738 | 0.992 | 0.967 | — |
| Random forest | 0.947 | 0.998 | 0.987 | — |
| **Gradient boosting (shipped)** | **0.964** | **0.998** | **0.990** | **0.713** |

**Accuracy is not reported as a headline.** At a 1.7 % positive rate, predicting
"no failure" every time scores 98.3 % accuracy and is worthless. PR-AUC is the
primary metric.

**The model earns its place**: PR-AUC 0.92 against 0.16 for the best single
threshold. But see §4 — that headline is not true of every failure mode.

Random forest ranks marginally higher on PR-AUC (0.934 vs 0.924); gradient
boosting is shipped because it is ~17 % cheaper at its own best operating point,
and cost is the stated decision criterion.

### Decision threshold

**0.0264**, chosen by minimising expected cost, not left at 0.5.

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

## 4. All five failure modes are now detected

| Fault mode | Test positives | Recall, model alone | Recall, with physics guard |
|---|---|---|---|
| `osf` overstrain | 1,393 | 1.000 | 1.000 |
| `pwf` power | 1,392 | 0.999 | 0.999 |
| `airflow` filter exhausted | 1,057 | 0.992 | 0.992 |
| `bearing` vibration | 568 | 0.998 | 0.998 |
| `hdf` heat dissipation | 816 | **0.950** | **0.991** |

### This is a corrected result, and the correction is the interesting part

An earlier version of this model had **0.000 recall on heat-dissipation
failure**. The diagnosis was that the training set contained only ~96 HDF rows —
about two events — and no model generalises a failure mode from two examples.

That was a **data** problem, not a model problem, and the fix was to the data.
All six HVAC units had been given identical wear characteristics, so they all
degraded the same way and one mode (overstrain) accounted for ~90 % of positives.
Real buildings do not contain six identical units. Each unit now has its own wear
character — a wet lab that loads filters with particulates, an older unit with
tired bearings, one boxed into a poorly ventilated ceiling void — and every
failure mode now has hundreds of training examples instead of two.

HDF recall went from 0.000 to 0.950. **The lesson worth carrying: a model that
cannot see a failure mode is usually being starved of it, not badly tuned.**

### The physics guard is retained anyway

A thermal ramp (0 at 70 °C → 1 at the 85 °C insulation limit) still runs as an
**independent alarm channel**, lifting HDF recall from 0.950 to 0.991.

It is kept for two reasons even though the model no longer needs rescuing:
heat-dissipation failure has a *direct physical precursor*, so a threshold is the
right instrument regardless of what the model can do; and it provides a detection
path that does not depend on the model being correctly trained at all.

It is deliberately **not** blended into the risk score. Folding it in previously
dragged server-room precision from 0.81 to 0.33, because it fires on any hot
motor regardless of the actual fault.

---

## 5. Fairness audit

Per-room performance on the test period, model channel only.

| Room | Dominant fault | Positive rate | PR-AUC | Recall | Precision | FN rate |
|---|---|---|---|---|---|---|
| `f1/lab-a` | airflow | 3.34 % | 0.980 | 0.992 | 0.700 | 0.008 |
| `f1/lab-b` | bearing | 1.79 % | 0.995 | 0.998 | 0.836 | 0.002 |
| `f1/server-room` | overstrain | 4.25 % | 0.978 | 1.000 | 0.849 | 0.000 |
| `f2/lab-c` | heat dissipation | 2.73 % | **0.679** | 0.953 | 0.462 | 0.048 |
| `f2/meeting-room` | power | 4.39 % | 0.995 | 0.999 | 0.812 | 0.001 |

**Recall is now 0.95–1.00 across every room.** The earlier version of this model
had a 100 % false-negative rate on `f1/lab-a`; that has been corrected, and §4
explains how (the cause was mode starvation in the training data, not room
identity).

**The remaining disparity is in precision and ranking quality, not detection.**
`f2/lab-c` is the weakest room on every measure — PR-AUC 0.679 against 0.98–0.99
elsewhere, and precision 0.46, meaning more than half its alerts are false. It is
the heat-dissipation room, and HDF remains the hardest mode to rank even now that
there is enough data to detect it.

**Who is affected.** `f2/lab-c` is a teaching lab, so a missed failure is
disruptive rather than dangerous — a better place to carry the weakness than the
wet lab, where the earlier version was blind. That is fortunate, not designed;
the assignment of weakness to consequence is not something this model controls.

**Mitigations in place:**
1. The HDF physics guard raises heat-dissipation recall from 0.950 to 0.991,
   independent of the model.
2. The per-room table is published here and surfaced in the dashboard rather
   than averaged into one headline number.
3. Room identity is excluded from the features by construction (§6), so the
   model cannot learn a per-room prior.

**Still outstanding:** at `f2/lab-c`'s precision of 0.46, roughly half of that
room's work orders will be unnecessary. Whether that is acceptable is a dispatch-
cost question, and the threshold should be re-derived against real callout costs
before this room's alerts are acted on automatically.

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
   telemetry before any output is trusted. This remains the largest limitation
   by a wide margin.
2. **Degrades badly on unseen equipment** — PR-AUC 0.26 against 0.96 on units it
   has seen (recall holds up better, 0.91). A newly commissioned unit should not
   be trusted to the same degree until it has contributed its own history. **This
   is now the most serious technical limitation.**
3. **Heat dissipation is still the hardest mode.** `f2/lab-c` scores PR-AUC 0.679
   and precision 0.462 — about half its alerts are false.
4. **Schedule-dependent.** `hour_cos` is the *second* most important feature
   (importance 0.176). The model has partly learned when this building is busy,
   and that will not transfer to a site on a different timetable.
5. **Cannot extrapolate to unseen maintenance regimes** — a never-serviced unit
   runs beyond the training range of `runtime_hours`.
6. **RUL is coarser than before**: MAE 20.3 h against a 33.2 h baseline, down
   from 14.6 h. Five failure modes with different time courses are harder to
   regress onto a single remaining-life number than three were.
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
