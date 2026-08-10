"""Live failure-risk scoring for each room twin.

Two independent detectors, reported side by side rather than merged:

* the **model** — a multiclass fault-type classifier; risk = 1 − P(none). Strong
  on cumulative faults (overstrain, power), PR-AUC 0.92.
* the **HDF physics guard** — a thermal threshold. The model is blind to
  heat-dissipation failure (~2 training events), and that mode has a direct
  physical precursor, so a rule covers it. See `ml/models/model_card.md` §4.

Two things this module is careful about:

**Sampling cadence.** Rolling features are defined in *samples* (6 / 24 / 72),
and the training data was sampled every 5 simulated minutes. Feeding live
telemetry at the tick rate would make a "6 h" window mean six minutes, so
history is appended on a fixed 5-simulated-minute cadence to match.

**Cold start.** With less than a full window the scorer returns `None` and the
twin publishes `status: "warming_up"`. A fabricated score for a unit we have no
history on is worse than no score.

If the model files are missing the scorer degrades to unavailable and the
simulator keeps running: a broken model must never stop the cooling.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from hvac_health import hdf_guard_score

MODEL_DIR = Path("ml/models")

# Must match the dataset generator's sampling: SAMPLE_EVERY(20) * SIM_DT(15s).
SAMPLE_INTERVAL_S = 300.0

# Maps the model's predicted fault class to the telemetry signal a technician
# should look at. building_twin.ACTION_FOR_FACTOR turns these into work orders.
FACTOR_FOR_FAULT = {
    "hdf": "motor_temp",
    "osf": "runtime_hours",
    "pwf": "power_draw_w",
    "airflow": "filter_clog",
    "bearing": "vibration_mm_s",
}

PLAIN_LANGUAGE = {
    "motor_temp": "fan motor running hot",
    "runtime_hours": "running hours past the rated service interval",
    "power_draw_w": "drawing more power than the duty cycle warrants",
    "filter_clog": "airflow restricted by a loaded filter",
    "vibration_mm_s": "bearing vibration rising",
}


class RiskScorer:
    """Scores each room from a rolling window of its own telemetry."""

    def __init__(self, model_dir: Path | str = MODEL_DIR, quiet: bool = False):
        self.model_dir = Path(model_dir)
        self.model = None
        self.rul_model = None
        self.spec: dict = {}
        self.threshold = 0.5
        self.model_version = "unavailable"
        self.unavailable_reason = ""
        self._history: dict[str, deque] = {}
        self._last_sample_s: dict[str, float] = {}
        self._load(quiet)

    # ── Loading ────────────────────────────────────────────────────────────

    def _load(self, quiet: bool) -> None:
        classifier = self.model_dir / "failure_classifier.joblib"
        spec_path = self.model_dir / "feature_spec.json"
        if not classifier.exists() or not spec_path.exists():
            self.unavailable_reason = f"no model in {self.model_dir}"
            if not quiet:
                print(f"WARNING: {self.unavailable_reason}; risk scoring disabled. "
                      f"Train one with: python ml/train.py")
            return
        try:
            import joblib
            self.model = joblib.load(classifier)
            self.spec = json.loads(spec_path.read_text())
            self.threshold = float(self.spec.get("decision_threshold", 0.5))
            self.model_version = self.spec.get("model_version", "unknown")
            rul = self.model_dir / "rul_regressor.joblib"
            if rul.exists():
                self.rul_model = joblib.load(rul)
        except Exception as exc:                      # corrupt or version-skewed
            self.model = None
            self.unavailable_reason = f"could not load model: {exc}"
            if not quiet:
                print(f"WARNING: {self.unavailable_reason}; risk scoring disabled.")

    @property
    def available(self) -> bool:
        return self.model is not None

    # ── History ────────────────────────────────────────────────────────────

    def observe(self, twin_id: str, telemetry: dict, sim_time_s: float) -> bool:
        """Record a sample if the 5-minute cadence has elapsed.

        Returns True when the sample was taken, so callers can tell how full
        the buffer is.
        """
        last = self._last_sample_s.get(twin_id)
        if last is not None and sim_time_s - last < SAMPLE_INTERVAL_S:
            return False
        self._last_sample_s[twin_id] = sim_time_s

        buffer = self._history.setdefault(twin_id, deque(maxlen=self.window))
        row = dict(telemetry)
        row["sim_hour"] = (sim_time_s / 3600.0) % 24.0
        buffer.append(row)
        return True

    @property
    def window(self) -> int:
        from features import WINDOWS
        return max(WINDOWS.values())

    def samples(self, twin_id: str) -> int:
        return len(self._history.get(twin_id, ()))

    def ready(self, twin_id: str) -> bool:
        return self.samples(twin_id) >= self.window

    # ── Scoring ────────────────────────────────────────────────────────────

    def score(self, twin_id: str) -> dict | None:
        """Risk for one room, or None if it cannot be scored honestly."""
        if not self.available or not self.ready(twin_id):
            return None

        from features import build_features_live
        x = build_features_live(self._history[twin_id])
        if x is None:
            return None

        proba = self.model.predict_proba(x)[0]
        classes = list(self.model.classes_)
        by_class = {c: float(proba[i]) for i, c in enumerate(classes)}
        failure_prob = 1.0 - by_class.get("none", 0.0)

        faults = {c: p for c, p in by_class.items() if c != "none"}
        likely_fault = max(faults, key=faults.get) if faults else "unknown"
        factor = FACTOR_FOR_FAULT.get(likely_fault, "unknown")

        latest = self._history[twin_id][-1]
        guard = hdf_guard_score(latest.get("motor_temp", 0.0))

        rul_hours = None
        if self.rul_model is not None:
            try:
                rul_hours = float(max(0.0, min(self.rul_model.predict(x)[0], 168.0)))
            except Exception:
                rul_hours = None

        # The two channels stay separate; `alert` is their OR, and `source`
        # says which one fired so the alert is never an unexplained number.
        model_alert = failure_prob >= self.threshold
        guard_alert = guard >= 0.5
        if model_alert and guard_alert:
            source = "model+thermal"
        elif guard_alert:
            source = "thermal_guard"
        elif model_alert:
            source = "model"
        else:
            source = "none"

        # When only the guard fires, it is the whole story. When both fire, keep
        # the model's root-cause attribution — with a 0.95-clogged filter the
        # right work order is "replace filter", not "service motor", even though
        # the motor is what is overheating — and carry the thermal warning
        # alongside so it is never lost behind the root cause.
        if guard_alert and not model_alert:
            factor = "motor_temp"
            likely_fault = "hdf"

        thermal_note = None
        if guard_alert:
            thermal_note = (
                f"motor at {latest.get('motor_temp', 0):.0f} °C, approaching the "
                f"85 °C insulation limit")

        return {
            "twin_id": twin_id,
            "status": "ok",
            "failure_prob": round(failure_prob, 5),
            "fault_probabilities": {c: round(p, 5) for c, p in by_class.items()},
            "likely_fault": likely_fault,
            "top_factor": factor,
            "explanation": PLAIN_LANGUAGE.get(factor, "condition degrading"),
            "thermal_guard": round(guard, 4),
            "thermal_note": thermal_note,
            "alert": bool(model_alert or guard_alert),
            "alert_source": source,
            "rul_hours": round(rul_hours, 2) if rul_hours is not None else None,
            "threshold": self.threshold,
            "model_version": self.model_version,
        }

    def warming_up_payload(self, twin_id: str) -> dict:
        """Honest placeholder while the buffer fills."""
        return {
            "twin_id": twin_id,
            "status": "unavailable" if not self.available else "warming_up",
            "failure_prob": None,
            "alert": False,
            "samples": self.samples(twin_id),
            "samples_required": self.window,
            "model_version": self.model_version,
            "reason": self.unavailable_reason or "insufficient history",
        }

    def score_all(self, twin_ids) -> dict:
        """Scores for every room that can be scored; absent otherwise."""
        out = {}
        for twin_id in twin_ids:
            result = self.score(twin_id)
            if result is not None:
                out[twin_id] = result
        return out
