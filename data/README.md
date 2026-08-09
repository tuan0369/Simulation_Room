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

Produced by `simulator/dataset_generator.py` (Task 6); git-ignored because it is
large and fully reproducible. Regenerate with:

```bash
docker compose run --rm sim python simulator/dataset_generator.py \
    --days 90 --seed 42 --out data/building_telemetry.csv
```

Statistics for the committed run will be recorded here once Task 6 lands, so
results stay auditable without committing the file itself.

> **The limitation this project does not hide:** the models are trained on
> simulated telemetry. AI4I constrains the failure *physics* so the thresholds
> are not invented, but a real deployment still requires recalibration against
> at least three months of real building telemetry before any autonomous action.
> This is stated in the model card and is a Phase-1 entry criterion in the
> roadmap.
