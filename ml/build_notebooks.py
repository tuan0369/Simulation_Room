"""Build the two deliverable notebooks and execute them.

Notebooks are generated from this script rather than hand-edited so their
analysis stays in step with `ml/train.py` and `ml/features.py`, and so the
committed .ipynb always contains real executed output rather than stale cells.

Run:
    docker compose run --rm sim python ml/build_notebooks.py
"""
from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient

OUT = Path("ml/notebooks")


def md(text):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text):
    return nbf.v4.new_code_cell(text.strip())


# ── 01: data exploration ────────────────────────────────────────────────────

EXPLORATION = [
    md("""
# 01 — Data exploration: real failure physics, then our building

This notebook does one job: **justify the failure thresholds** used everywhere
else in the project. It does not train anything.

The obvious weakness of a simulated digital twin is that its failure thresholds
are whatever the author chose. We remove that by inheriting them from the **UCI
AI4I 2020 Predictive Maintenance Dataset** — real, published, with *documented*
failure rules — and verifying those rules reproduce exactly before reusing them.
"""),
    code("""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
pd.set_option("display.width", 120)
plt.rcParams["figure.figsize"] = (10, 4)
"""),
    md("## 1. The reference dataset (UCI AI4I 2020)"),
    code("""
ai4i = pd.read_csv("data/ai4i2020.csv")
print(f"rows: {len(ai4i):,}")
print(f"machine failures: {int(ai4i['Machine failure'].sum())} "
      f"({100*ai4i['Machine failure'].mean():.2f}%)")
ai4i[["Air temperature [K]","Process temperature [K]","Rotational speed [rpm]",
      "Torque [Nm]","Tool wear [min]"]].describe().round(2)
"""),
    code("""
modes = {c: int(ai4i[c].sum()) for c in ["TWF","HDF","PWF","OSF","RNF"]}
print("failures by mode:", modes)
ax = pd.Series(modes).plot.bar(color="#3b82f6")
ax.set_title("AI4I 2020 — failures by mode"); ax.set_ylabel("count"); plt.show()
"""),
    md("""
### Verifying the documented rule

AI4I documents heat-dissipation failure as: *(process temperature − air
temperature) < 8.6 K **and** rotational speed < 1380 rpm*.

If that rule is real, filtering on it should select exactly the HDF rows. This
is the check that turns "we picked some thresholds" into "we inherited
published ones".
"""),
    code("""
selected = ai4i[(ai4i["Process temperature [K]"] - ai4i["Air temperature [K]"] < 8.6)
                & (ai4i["Rotational speed [rpm]"] < 1380)]
print(f"rows matching the documented HDF rule : {len(selected)}")
print(f"of those, flagged HDF in the dataset  : {int(selected['HDF'].sum())}")
print(f"total HDF rows in the dataset         : {int(ai4i['HDF'].sum())}")
assert len(selected) == int(selected["HDF"].sum()) == int(ai4i["HDF"].sum())
print("\\nEXACT 1:1 match - the published rule is load-bearing, not approximate.")
"""),
    md("""
### How the rules map onto an HVAC fan motor

| AI4I mode | AI4I rule | Our analogue | Constant |
|---|---|---|---|
| **HDF** | (process − air) < 8.6 K and rpm < 1380 | Motor cannot shed heat into room air | `HDF_DELTA_K=8.6`, `HDF_RPM_MIN=1380` |
| **PWF** | torque × ω outside [3500, 9000] W | Draw outside the band expected for the commanded duty | `[0.56, 1.43] ×` expected |
| **OSF** | tool_wear × torque > 11000 min·Nm | runtime × torque past rated duty | `183.3 h·Nm` |
| **TWF** | wear ∈ [200, 240] min | Filter exhausted → airflow failure | `clog > 0.85` |

Rescaling arithmetic is in `data/README.md`. Thresholds that do **not** come
from AI4I (the 85 °C Class-F insulation limit, ISO 10816 vibration bands) are
listed there separately, so the citation is not overclaimed.
"""),
    md("## 2. Our building's telemetry"),
    code("""
df = pd.read_csv("data/building_telemetry.csv", parse_dates=["timestamp_iso"])
print(f"rows: {len(df):,}   span: {df.timestamp_iso.min().date()} -> {df.timestamp_iso.max().date()}")
print(f"failure events (segments ending in failure): {df.segment_id.nunique()} segments")
print(f"positive rate  4h: {100*df.label_failure_within_4h.mean():.3f}%"
      f"   30min: {100*df.label_failure_within_30min.mean():.3f}%")
"""),
    md("""
**Why the event count matters more than the row count.** Rows five minutes
apart inside one degradation segment are near-duplicates. A dataset of 630k
rows containing 228 events is a *228-sample* problem. This is why the trace is
a full year rather than the 90 days first generated, which held only 53 events.
"""),
    code("""
per_room = df.groupby("twin_id").agg(
    rows=("twin_id","size"),
    positives_4h=("label_failure_within_4h","sum"),
    segments=("segment_id","nunique"),
    mean_temp=("room_temp","mean"),
    max_motor_temp=("motor_temp","max"),
).assign(positive_rate_pct=lambda d: (100*d.positives_4h/d.rows).round(3))
per_room.round(2)
"""),
    code("""
pos = df[df.label_failure_within_4h == 1]
mix = pd.crosstab(pos.twin_id, pos.label_failure_type)
print("failure MODE mix per room:"); display(mix)
mix.plot.bar(stacked=True); plt.title("Failure modes are segregated by room")
plt.ylabel("positive rows"); plt.show()
"""),
    md("""
**This chart is the single most important finding in the project.**

Failure modes are almost perfectly segregated by room. `f1/lab-a` fails only by
heat dissipation; the server room only by overstrain. Overstrain accounts for
roughly 10k of ~11k positive rows.

Two consequences follow, and both are dealt with in notebook 02:

1. A binary classifier optimises for the majority mode and goes **blind** to the
   others. We predict the fault *type* instead.
2. Per-room performance disparity is really per-*mode* disparity. A fairness
   audit that stops at "lab-a scores badly" would miss the cause.
"""),
    md("## 3. Degradation over time"),
    code("""
room = df[df.twin_id == "f2/meeting-room"].set_index("timestamp_iso")
fig, axes = plt.subplots(3, 1, figsize=(11, 7), sharex=True)
room["filter_clog"].plot(ax=axes[0], color="#f59e0b"); axes[0].set_ylabel("filter clog")
room["motor_temp"].plot(ax=axes[1], color="#ef4444"); axes[1].set_ylabel("motor °C")
axes[1].axhline(85, ls="--", c="k", lw=1, label="85 °C insulation limit"); axes[1].legend()
room["vibration_mm_s"].plot(ax=axes[2], color="#8b5cf6"); axes[2].set_ylabel("vibration mm/s")
axes[2].axhline(7.1, ls="--", c="k", lw=1)
fig.suptitle("f2/meeting-room — never serviced, so it runs to failure repeatedly")
plt.tight_layout(); plt.show()
"""),
    code("""
served = df[df.twin_id == "f1/lab-a"].set_index("timestamp_iso")
ax = served["filter_clog"].plot(color="#22c55e", label="f1/lab-a (serviced every 10 days)")
room["filter_clog"].plot(ax=ax, color="#f59e0b", alpha=.7, label="f2/meeting-room (never)")
ax.set_ylabel("filter clog"); ax.legend(); ax.set_title("Maintenance discipline is visible in the data")
plt.show()
"""),
    md("""
The sawtooth is planned servicing. The contrast between these two rooms is the
**deliberate distribution shift** the fairness audit needs — without it, a
finding of "no disparity" would be vacuous.
"""),
    md("## 4. Class imbalance"),
    code("""
counts = df.label_failure_within_4h.value_counts()
print(counts.to_string())
print(f"\\nA model predicting 'no failure' always would score "
      f"{100*counts[0]/len(df):.2f}% accuracy and be worthless.")
print("This is why PR-AUC, not accuracy, is the headline metric in notebook 02.")
"""),
]

# ── 02: failure prediction ─────────────────────────────────────────────────

PREDICTION = [
    md("""
# 02 — Failure prediction

Trains and audits the models. The pipeline itself lives in `ml/train.py` so it
is testable and shared with live inference; this notebook runs it and
interprets the results.

Four decisions shape everything below:

1. **Split temporally and by room.** Rows five minutes apart are near-duplicates;
   a random shuffle would inflate scores to a meaningless ~0.99.
2. **Predict the fault *type*, not just failure.** The positive class is a
   mixture of three physically distinct faults dominated by one.
3. **Report a trivial baseline.** If a single threshold matches the model, the
   model earned nothing.
4. **Pick the threshold from a cost curve.** A missed failure and a wasted
   callout are not equally expensive.
"""),
    code("""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from sklearn.metrics import precision_recall_curve, average_precision_score
import train as T
from features import FEATURE_COLUMNS
plt.rcParams["figure.figsize"] = (10, 4)
print(f"{len(FEATURE_COLUMNS)} features")
"""),
    md("""
## Features exclude room identity — on purpose

`twin_id`, `floor`, `room_profile` and `segment_id` are all excluded, enforced
by test. In this data `f1/lab-a` fails 30× less often than the server room
purely because of its maintenance *policy*. An identity-aware model would learn
"lab-a is safe" and stay silent when its filter finally clogs.

Rolling windows are computed **per degradation segment**, so no window spans a
maintenance reset and smears a worn unit's history into a freshly serviced one.
"""),
    code("""
print("excluded from features:", sorted(T_FORBIDDEN := __import__("features").FORBIDDEN))
print("\\nexample features:", FEATURE_COLUMNS[:8], "...")
"""),
    md("## Load and split"),
    code("""
df = T.load()
train, test_time, test_room, cutoff_day = T.split(df)
print(f"train      days 0-{cutoff_day}   {len(train):,} rows  {int(train[T.TARGET].sum()):,} positives")
print(f"test time  days {cutoff_day+1}+  {len(test_time):,} rows  {int(test_time[T.TARGET].sum()):,} positives")
print(f"test room  {T.HELD_OUT_ROOM} (never trained on)  {len(test_room):,} rows")
"""),
    code("""
x_train, y_train, f_train, m_train = T._matrix(train)
x_test,  y_test,  f_test,  m_test  = T._matrix(test_time)
x_room,  y_room,  f_room,  m_room  = T._matrix(test_room)
print("fault mix in training positives:")
print(pd.Series(f_train[f_train != "none"]).value_counts().to_string())
"""),
    md("""
Only ~96 HDF rows — about **two events**. Remember that number; it explains the
model's one serious blind spot.
"""),
    md("## Train and compare"),
    code("""
models = T.train_models(x_train, f_train)
rows = []
for name, m in models.items():
    s = T.binary_scores(m, x_test)
    thr, cost = T.cost_optimal_threshold(y_test, s)
    ev = T.evaluate(name, y_test, s, thr)
    r90, _ = T.recall_at_precision(y_test, s, 0.90)
    rows.append(dict(model=name, pr_auc=round(ev.pr_auc,4), roc_auc=round(ev.roc_auc,4),
                     recall=round(ev.recall_at_threshold,4),
                     precision=round(ev.precision_at_threshold,4),
                     recall_at_p90=round(r90,4), threshold=round(thr,4),
                     expected_cost=round(cost)))
base_s, base_t = T.trivial_baseline(test_time)
be = T.evaluate("threshold motor_temp>80", y_test, base_s, base_t)
rows.insert(0, dict(model="threshold motor_temp>80", pr_auc=round(be.pr_auc,4),
                    roc_auc=round(be.roc_auc,4), recall=round(be.recall_at_threshold,4),
                    precision=round(be.precision_at_threshold,4)))
rows.insert(0, dict(model="always 'no failure'", pr_auc=round(float(y_test.mean()),4),
                    roc_auc=0.5, recall=0.0))
comparison = pd.DataFrame(rows); comparison
"""),
    md("""
**Accuracy is absent from that table deliberately.** At a 1.7 % positive rate,
"always no failure" scores 98.3 % accuracy — the second row shows its PR-AUC is
0.018, which is the honest number.

The model beats the best single threshold by roughly 6× on PR-AUC, so it earns
its place. §"Per fault mode" below shows where that headline does *not* hold.
"""),
    code("""
best_name = min([r["model"] for r in rows if "expected_cost" in r],
                key=lambda n: [r for r in rows if r["model"]==n][0]["expected_cost"])
best = models[best_name]
best_scores = T.binary_scores(best, x_test)
best_thr = [r for r in rows if r["model"]==best_name][0]["threshold"]
print(f"shipped model: {best_name}  threshold {best_thr}")

p, r, _ = precision_recall_curve(y_test, best_scores)
plt.plot(r, p, label=f"{best_name} (AP={average_precision_score(y_test,best_scores):.3f})")
pb, rb, _ = precision_recall_curve(y_test, base_s)
plt.plot(rb, pb, "--", label=f"motor_temp threshold (AP={average_precision_score(y_test,base_s):.3f})")
plt.axhline(y_test.mean(), color="grey", ls=":", label=f"base rate ({y_test.mean():.3f})")
plt.xlabel("recall"); plt.ylabel("precision"); plt.legend(); plt.title("Precision-recall"); plt.show()
"""),
    md("## Cost curve — where the threshold comes from"),
    code("""
prec, rec, thr = precision_recall_curve(y_test, best_scores)
P = int(y_test.sum()); costs=[]
for i,t in enumerate(thr):
    tp = rec[i]*P; fn = P-tp
    fp = (tp/prec[i]-tp) if prec[i]>0 else len(y_test)-P
    costs.append(fn*T.COST_FALSE_NEGATIVE + fp*T.COST_FALSE_POSITIVE)
plt.semilogx(thr, costs); plt.axvline(best_thr, c="r", ls="--", label=f"chosen {best_thr}")
plt.xlabel("threshold"); plt.ylabel("expected cost (EUR)")
plt.title(f"FN=EUR{T.COST_FALSE_NEGATIVE:.0f}  FP=EUR{T.COST_FALSE_POSITIVE:.0f} (assumptions)")
plt.legend(); plt.show()
"""),
    md("""
A 13:1 cost ratio pushes the threshold very low: the system is deliberately
tuned to over-call rather than miss. These costs are **assumptions**, and the
ROI case inherits that caveat.
"""),
    md("## Per fault mode — the model's blind spot"),
    code("""
modes = T.per_fault_report(best, x_test, y_test, f_test, best_thr, m_test)
modes
"""),
    md("""
**The model has 0.00 recall on heat-dissipation failure.**

It cannot be tuned away: there were ~2 HDF events in training. But HDF is
*defined* by motor temperature crossing the 85 °C insulation limit, so it has a
direct physical precursor — a threshold problem, not a learning problem.

The shipped system therefore runs a **physics guard** as an independent alarm
channel (a ramp from 70 °C to 85 °C), recovering recall to ~0.59. It is not
blended into the ML score: doing that dragged server-room precision from 0.81 to
0.33, because it fires on any hot motor regardless of fault.

**ML is not uniformly better than rules.** It beats any single threshold for
cumulative faults and loses to a thermostat for one with a direct precursor.
"""),
    md("## Explainability"),
    code("""
imp = T.explain(best, x_test, f_test)
top = imp.head(12).iloc[::-1]
plt.barh(top.feature, top.importance, xerr=top["std"], color="#3b82f6")
plt.xlabel("drop in average precision when shuffled"); plt.title("Permutation importance")
plt.tight_layout(); plt.show()
imp.head(12).round(4)
"""),
    md("""
Readable and consistent with the AI4I rules the physics was calibrated against:
`runtime_hours` is the overstrain driver, `motor_room_delta` is the
heat-dissipation driver, `vibration` is bearing condition.

`hour_cos` ranking highly is a caveat worth stating: the model has partly
learned *when the building is busy*, which will not transfer to a site on a
different schedule.
"""),
    md("## Fairness audit"),
    code("""
audit = T.fairness_audit(test_time, best, best_thr)
audit
"""),
    code("""
a = audit.dropna(subset=["recall"])
plt.bar(a.twin_id, a.recall, color=["#ef4444" if v<0.5 else "#22c55e" for v in a.recall])
plt.ylabel("recall"); plt.xticks(rotation=30, ha="right")
plt.title("Recall per room — disparity is severe, not marginal"); plt.tight_layout(); plt.show()
"""),
    md("""
`f1/lab-a` has a **100 % false-negative rate**: every one of its failures is
missed.

The cause is not room identity — that is excluded from the features. It is that
lab-a is the most aggressively serviced unit, so it never accumulates the
runtime that produces overstrain; all its failures are HDF, the mode the model
cannot see. **Per-room disparity is per-mode disparity wearing a different hat.**

Who this harms matters: a wet lab holds temperature-sensitive samples, so the
model is blindest exactly where an outage costs most. Mitigation is the physics
guard (recall 0.000 → 0.536) plus publishing this table rather than averaging it
away. Even so, lab-a remains **inadequately covered** and should keep
calendar-based servicing.
"""),
    md("## Generalisation to unseen equipment"),
    code("""
room_scores = T.binary_scores(best, x_room)
ev = T.evaluate("unseen room", y_room, room_scores, best_thr)
print(f"{T.HELD_OUT_ROOM}: PR-AUC {ev.pr_auc:.4f}  recall {ev.recall_at_threshold:.4f}")
print(f"(seen rooms, same period: PR-AUC {average_precision_score(y_test, best_scores):.4f})")
"""),
    md("""
Markedly worse on equipment it has never seen. A newly commissioned unit should
not be trusted to the same degree until it has contributed its own history.
"""),
    md("## Remaining useful life"),
    code("""
rul_model, rul_metrics = T.train_rul(train, test_time)
print(rul_metrics)
print(f"\\nvs predict-the-mean baseline: {rul_metrics['baseline_mae_hours']} h")
"""),
    md("""
MAE ≈ 15 hours against a 38-hour baseline. Trained only on uncensored rows —
rows pinned at the 168-hour censoring horizon are not observations of a real
remaining life, and training on them teaches the model to predict the censoring
constant.
"""),
    md("""
## Conclusions

* The model earns its place for cumulative faults: PR-AUC 0.92 vs 0.16 for the
  best single threshold.
* It is **blind to heat-dissipation failure** (~2 training events) and needs a
  physics guard to cover it.
* Severe per-room disparity, driven by per-mode segregation, in the room where
  failure costs most.
* Everything here is trained on **simulated** telemetry. AI4I constrains the
  failure physics so the thresholds are not invented, but real deployment needs
  recalibration on ≥ 3 months of real data first.

Full limitations: [`ml/models/model_card.md`](../models/model_card.md).
"""),
]


def build(cells, path, timeout=1800):
    nb = nbf.v4.new_notebook(cells=cells)
    nb.metadata.kernelspec = {"name": "python3", "display_name": "Python 3",
                              "language": "python"}
    client = NotebookClient(nb, timeout=timeout, kernel_name="python3",
                            resources={"metadata": {"path": "."}})
    print(f"executing {path} ...")
    client.execute()
    path.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, str(path))
    print(f"  wrote {path}")


if __name__ == "__main__":
    build(EXPLORATION, OUT / "01_data_exploration.ipynb")
    build(PREDICTION, OUT / "02_failure_prediction.ipynb")
