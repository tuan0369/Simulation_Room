# Datasets

Three datasets underpin this project. They serve different purposes and it
matters which claim rests on which.

| File | Origin | Role | Committed |
|---|---|---|---|
| `building_layout.json` | Authored | Facility description — the single source of truth for geometry, thermal constants and adjacency | Yes |
| `ai4i2020.csv` | UCI (real) | Calibration reference for the equipment failure taxonomy and thresholds | Yes (510 KB) |
| `building_telemetry.csv` | Generated | Labeled training data for the ML models | No — regenerate it |

---

## `building_layout.json`

Machine-readable description of a 2-floor, 6-room facility. Read by
`simulator/building.py`, the Streamlit dashboard and the Three.js view, so room
geometry cannot drift from room physics.

`f1/lab-a` is the Project-1 room and keeps its exact calibrated constants
(25 000 J/°C, 3500 W, k = 0.05, 30 occupants). `simulator/tests/test_building.py`
locks this as the regression guard for the multi-room refactor.

Floor power budgets (22 + 22 kW) deliberately over-subscribe the building
budget (40 kW). That conflict is what the building twin exists to arbitrate; a
test asserts the over-subscription so the arbitration cannot quietly become
dead code.

---

## `ai4i2020.csv` — UCI AI4I 2020 Predictive Maintenance Dataset

**Source:** UCI Machine Learning Repository, dataset 601.
<https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset>
**Citation:** Matzka, S. (2020). *Explainable Artificial Intelligence for
Predictive Maintenance Applications.* Third International Conference on
Artificial Intelligence for Industries (AI4I 2020).
**Licence:** CC BY 4.0.

**Verified contents** (reproduced in-container, not taken on trust):

- 10 000 rows, 14 columns
- 339 failures — 3.39 %
- By mode: TWF 46, HDF 115, PWF 95, OSF 98, RNF 19

Re-download with:

```bash
docker compose run --rm sim python -c "import urllib.request,zipfile,io; z=zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip').read())); z.extract('ai4i2020.csv','data')"
```

### Why this dataset is here

The obvious weakness of a simulated twin is that its failure thresholds are
whatever the author chose. AI4I removes that: it is real published
predictive-maintenance data whose failure rules are *documented*, and we
verified they reproduce exactly. Filtering for the published heat-dissipation
rule — `(process_temp − air_temp) < 8.6 K AND rotational_speed < 1380 rpm` —
selects **115 rows, and all 115 are flagged HDF**. A perfect 1:1 match, so the
rules are load-bearing rather than approximate.

### Mapping onto our fan motor

`simulator/hvac_health.py` inherits AI4I's failure taxonomy and rescales its
envelope to HVAC units:

| AI4I mode | AI4I rule | Our analogue | Constant |
|---|---|---|---|
| **HDF** heat dissipation | (process − air) < 8.6 K **and** rpm < 1380 | Motor cannot shed heat into room air; airflow collapses as the filter clogs and wear drags speed down | `HDF_DELTA_K = 8.6`, `HDF_RPM_MIN = 1380` |
| **PWF** power | torque × ω outside [3500, 9000] W | Draw outside the band expected for the commanded duty | `PWF_MIN_FRACTION = 0.56`, `PWF_MAX_FRACTION = 1.43` |
| **OSF** overstrain | tool_wear × torque > 11 000 min·Nm | runtime × torque past rated duty | `OSF_LIMIT_HR_NM = 183.3` |
| **TWF** tool wear | wear ∈ [200, 240] min | Filter exhausted → airflow failure | `CLOG_FAILURE = 0.85` |

**Rescaling arithmetic, stated so it can be checked:**

- *PWF band.* AI4I's nominal operating point is ≈ 40 Nm × 1500 rpm ≈ 6283 W.
  Its band [3500, 9000] W is therefore [0.56, 1.43] × nominal. We apply those
  same fractions to the draw expected at the commanded duty. Normalising by
  *expected* draw rather than rated draw matters: a healthy unit idling at 25 %
  duty legitimately draws a quarter of rated power, and comparing against rated
  would flag it as a power failure.
- *OSF limit.* 11 000 min·Nm ÷ 60 = 183.3 h·Nm, used unchanged. At a healthy
  unit's ≈ 1.8 Nm this puts servicing due after ≈ 100 running hours — aggressive
  against real HVAC practice (2000–8000 h), but it is what keeps run-to-failure
  trajectories inside a 90-day accelerated simulation. `service_motor` resets it.
- *HDF envelope.* Used directly. Our `base_rpm = 1500` sits above AI4I's
  1380 rpm threshold, so healthy units run outside the envelope and bearing wear
  drags them through it — asserted by
  `test_worn_bearings_drag_fan_speed_into_the_ai4i_envelope`.

### Thresholds that do *not* come from AI4I

Stated separately so the citation is not overclaimed:

- `MOTOR_TEMP_ALARM = 85 °C` — Class-F winding insulation (155 °C rating),
  standard 85 °C alarm on winding rise.
- `VIBRATION_ALARM = 7.1 mm/s`, `VIBRATION_FAILURE = 11.2 mm/s` — ISO 10816-1
  velocity bands for small machines (zone C/D boundary, and unacceptable).
  The alarm must precede the failure or there is no lead time to predict into;
  `test_vibration_alarm_leads_bearing_failure` enforces it.
- Degradation *rates* (`CLOG_RATE_PER_HOUR`, `WEAR_RATE_PER_HOUR`) are chosen so
  a 90-day accelerated run contains enough failures to train on. They are the
  most arbitrary numbers in the model and are called out as such in the model
  card.

---

## `building_telemetry.csv` — generated

Produced by `simulator/dataset_generator.py`; git-ignored because it is 22 MB
and fully reproducible. Regenerate with:

```bash
docker compose run --rm sim python simulator/dataset_generator.py \
    --days 90 --seed 42 --out data/building_telemetry.csv
```

### Statistics of the reference run (`--days 365 --seed 42`)

| | |
|---|---|
| Rows | 630,720 (105,120 per room × 6 rooms), 114 MB |
| Simulated span | 365 days from 2026-01-01 UTC |
| Sampling | one row per room per 5 simulated minutes |
| Physics timestep | 15 s |
| **Failure events** | **228** |
| Degradation segments | 612 |
| Positive rate, 4 h horizon | **1.737 %** (primary target) |
| Positive rate, 30 min horizon | 0.218 % |

| Room | Failures | Planned services | 4 h positives | Rate |
|---|---|---|---|---|
| `f1/lab-a` | 3 | 95 | 145 | 0.14 % |
| `f1/lab-b` | 22 | 61 | 1056 | 1.00 % |
| `f1/server-room` | 92 | 144 | 4418 | 4.20 % |
| `f2/lab-c` | 49 | 46 | 2353 | 2.24 % |
| `f2/meeting-room` | 25 | 0 | 1201 | 1.14 % |
| `f2/office` | 37 | 32 | 1780 | 1.69 % |

### Why a year, not 90 days

An earlier 90-day run produced 155,520 rows but only **53 failure events**, and
the event count is what actually constrains the model: rows inside one
degradation segment are heavily autocorrelated, so that was a 53-sample problem
wearing a 155k-row costume. A temporal split would have left ~15 events to test
on, far too few for a stable PR-AUC.

A full year gives 228 events (~68 in a held-out final third) and, as a side
effect, fixed a subtler problem: at 90 days `f1/lab-a` recorded **zero**
failures, so its per-room recall was undefined and any identity-aware model
would have learned that room cannot fail. Over a year it fails 3 times. No room
is immortal; the short window just had not observed it yet.

### Time-series structure

This is temporal data and the columns say so explicitly:

- `timestamp_iso` — timezone-aware ISO-8601, so the notebook can build a real
  `DatetimeIndex` rather than treating a row counter as time.
- `segment_id` — `"<twin_id>#<n>"`, one degradation run from a reset (planned
  service or failure repair) to the next. This is the correct grouping unit for
  cross-validation: splitting a segment across train and test leaks the future,
  and rolling features are computed per segment so no window spans a
  maintenance reset.
- Rows are emitted in chronological order, six rooms per timestamp.

Splits must be **temporal** (and, for the generalisation check, by held-out
room). A random row shuffle would put a row's own neighbours five minutes either
side of it into the training set and inflate scores to a meaningless ~0.99.

### Two label horizons, and why

`label_failure_within_30min` is the window named in the project plan, but it
yields only 0.2 % positives and — operationally — half an hour is too short to
dispatch a technician into. `label_failure_within_4h` is the primary training
target: 1.6 % positives, the same order as AI4I's 3.39 %, and actually
actionable. Both are emitted so the notebook can compare them.

`label_rul_hours` is right-censored at 168 h rather than left blank, so no
column contains NaNs.

Labels are assigned in a **second pass, backwards from observed failures**.
Every positive is therefore justified by a failure that actually occurred later
in the same trace, which is what makes the label-correctness tests meaningful
instead of circular.

### Deliberate distribution shift

Maintenance discipline varies by room, from `f1/lab-a` (serviced every 6–10
days) to `f2/meeting-room` (never serviced). This is not incidental — it gives
the Task 7 fairness audit real per-room shift to detect rather than an
assumed-clean dataset.

Two consequences to carry into that audit:

**Room identity is never a feature.** `ml/features.py` excludes `twin_id`,
`floor`, `room_profile` and `segment_id` by construction, and a test enforces
it. `f1/lab-a` has 30× fewer positives than the server room purely because of
its maintenance *policy*, not because its hardware is different — an
identity-aware model would learn "lab-a is safe" and stay silent when its filter
finally does clog. Risk is inferred from condition alone, so a healthy room
scores low because it is healthy, not because of its name.

**The per-room positive rate spans 0.14 % to 4.20 %.** That is real
distribution shift, and the audit should expect worse recall on the sparse rooms
rather than treating uniform performance as the default.

> **The limitation this project does not hide:** the models are trained on
> simulated telemetry. AI4I constrains the failure *physics* so the thresholds
> are not invented, but a real deployment still requires recalibration against
> at least three months of real building telemetry before any autonomous action.
> This is stated in the model card and is a Phase-1 entry criterion in the
> roadmap.

> **The limitation this project does not hide:** the models are trained on
> simulated telemetry. AI4I constrains the failure *physics* so the thresholds
> are not invented, but a real deployment still requires recalibration against
> at least three months of real building telemetry before any autonomous action.
> This is stated in the model card and is a Phase-1 entry criterion in the
> roadmap.
