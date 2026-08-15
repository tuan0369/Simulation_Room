import copy
import csv
import io
import json
from math import inf, nan

import pytest

import fan_health
from fan_health import LogisticRiskModel, default_model, step_fan_state, FanState
from generate_fan_data import DEFAULT_OUTPUT, DEFAULT_ROWS, DEFAULT_SEED, generate_rows
from train_fan_model import DEFAULT_ARTIFACT, fit_model


def test_synthetic_generator_is_reproducible_with_same_seed():
    assert generate_rows(rows=8, seed=7) == generate_rows(rows=8, seed=7)


def test_default_dataset_model_and_metrics_reproduce_exactly():
    rows = generate_rows(rows=DEFAULT_ROWS, seed=DEFAULT_SEED)
    with DEFAULT_OUTPUT.open(newline="", encoding="utf-8") as dataset_file:
        stored_rows = [
            {
                **{name: float(record[name]) for name in fan_health.FEATURE_NAMES},
                "failure_within_7d": int(record["failure_within_7d"]),
            }
            for record in csv.DictReader(dataset_file)
        ]

    fieldnames = [*fan_health.FEATURE_NAMES, "failure_within_7d"]
    generated_csv = io.StringIO(newline="")
    writer = csv.DictWriter(generated_csv, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    artifact, metrics = fit_model(rows, seed=DEFAULT_SEED, iterations=2400)

    assert stored_rows == rows
    assert DEFAULT_OUTPUT.read_bytes() == generated_csv.getvalue().encode("utf-8")
    assert artifact == json.loads(DEFAULT_ARTIFACT.read_text(encoding="utf-8"))
    assert metrics == json.loads(
        DEFAULT_ARTIFACT.with_suffix(".metrics.json").read_text(encoding="utf-8")
    )


def test_fan_model_has_expected_feature_schema():
    model = default_model()
    assert model.feature_names == (
        "filter_clog_pct",
        "fan_speed_pct",
        "vibration_mm_s",
        "bearing_temp_c",
        "run_hours",
    )


def test_degraded_fan_has_more_risk_than_a_clean_low_load_fan():
    model = default_model()
    healthy = model.predict(
        {
            "filter_clog_pct": 0.05,
            "fan_speed_pct": 0.1,
            "vibration_mm_s": 1.0,
            "bearing_temp_c": 35.0,
            "run_hours": 40.0,
        }
    )
    degraded = model.predict(
        {
            "filter_clog_pct": 0.9,
            "fan_speed_pct": 1.0,
            "vibration_mm_s": 5.5,
            "bearing_temp_c": 82.0,
            "run_hours": 8000.0,
        }
    )
    assert degraded.failure_risk > healthy.failure_risk
    assert degraded.risk_band == "high"
    assert degraded.top_drivers[0][0] in {"bearing_temp_c", "vibration_mm_s", "filter_clog_pct"}


def test_driver_contributions_are_ordered_descending():
    model = default_model()
    prediction = model.predict(
        {
            "filter_clog_pct": 0.7,
            "fan_speed_pct": 0.8,
            "vibration_mm_s": 4.0,
            "bearing_temp_c": 70.0,
            "run_hours": 5000.0,
        }
    )
    contributions = [value for _, value in prediction.top_drivers]
    assert contributions == sorted(contributions, reverse=True)


def _artifact():
    return json.loads(fan_health.DEFAULT_MODEL_PATH.read_text(encoding="utf-8"))


def _write_artifact(tmp_path, update):
    artifact = copy.deepcopy(_artifact())
    update(artifact)
    path = tmp_path / "fan-model.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("update", "message"),
    [
        (lambda data: data.update(artifact_type="other"), "artifact type"),
        (lambda data: data.update(model_version="fan-risk-logistic-v0"), "model version"),
        (lambda data: data.update(feature_names=list(reversed(data["feature_names"]))), "feature schema"),
        (lambda data: data.update(coefficients=data["coefficients"][:-1]), "arrays"),
        (lambda data: data["scales"].__setitem__(0, 0.0), "scales must be positive"),
        (lambda data: data["means"].__setitem__(0, nan), "finite number"),
        (lambda data: data.update(medium_threshold=0.8, high_threshold=0.6), "thresholds"),
        (lambda data: data["feature_domain"]["run_hours"].update(min=10.0, max=5.0), "domain"),
    ],
)
def test_model_load_rejects_malformed_or_incompatible_artifacts(tmp_path, update, message):
    with pytest.raises(ValueError, match=message):
        LogisticRiskModel.load(_write_artifact(tmp_path, update))


def test_model_abstains_on_missing_nonnumeric_or_nonfinite_telemetry():
    model = default_model()
    baseline = {
        "filter_clog_pct": 0.5,
        "fan_speed_pct": 0.5,
        "vibration_mm_s": 2.0,
        "bearing_temp_c": 50.0,
        "run_hours": 4000.0,
    }
    for update in (
        {"run_hours": None},
        {"run_hours": "4000"},
        {"run_hours": nan},
        {"run_hours": inf},
    ):
        prediction = model.predict({**baseline, **update})
        assert prediction.failure_risk is None
        assert prediction.risk_band == "abstained"
        assert prediction.prediction_status == "abstained"
        assert prediction.abstained
        assert not prediction.out_of_distribution


def test_model_abstains_and_labels_out_of_distribution_telemetry():
    model = default_model()
    prediction = model.predict(
        {
            "filter_clog_pct": 0.5,
            "fan_speed_pct": 0.5,
            "vibration_mm_s": 2.0,
            "bearing_temp_c": 50.0,
            "run_hours": model.feature_maxs[-1] + 1.0,
        }
    )
    assert prediction.failure_risk is None
    assert prediction.risk_band == "out_of_distribution"
    assert prediction.prediction_status == "out_of_distribution"
    assert prediction.available
    assert prediction.abstained
    assert prediction.out_of_distribution
    assert "run_hours" in prediction.status_reason


@pytest.mark.parametrize("feature", ["filter_clog_pct", "fan_speed_pct", "vibration_mm_s", "bearing_temp_c", "run_hours"])
def test_model_treats_physically_impossible_negative_telemetry_as_ood(feature):
    model = default_model()
    telemetry = {
        "filter_clog_pct": 0.5,
        "fan_speed_pct": 0.5,
        "vibration_mm_s": 2.0,
        "bearing_temp_c": 50.0,
        "run_hours": 4000.0,
    }
    telemetry[feature] = -1.0

    prediction = model.predict(telemetry)
    assert prediction.risk_band == "out_of_distribution"
    assert prediction.failure_risk is None
    assert feature in prediction.status_reason


def test_default_model_falls_back_to_unavailable_without_affecting_fan_control(monkeypatch):
    before = step_fan_state(FanState(), fan_speed_pct=0.7, filter_clog_pct=0.4, dt=5.0)
    monkeypatch.setattr(fan_health, "DEFAULT_MODEL_PATH", fan_health.DEFAULT_MODEL_PATH.with_name("missing.json"))
    model = default_model()
    prediction = model.predict({})
    after = step_fan_state(FanState(), fan_speed_pct=0.7, filter_clog_pct=0.4, dt=5.0)

    assert before == after
    assert prediction.failure_risk is None
    assert prediction.risk_band == "unavailable"
    assert prediction.prediction_status == "unavailable"
    assert not prediction.available
    assert prediction.abstained


def test_training_emits_domain_metadata_and_expanded_metrics():
    artifact, metrics = fit_model(generate_rows(rows=80, seed=7), seed=7, iterations=20)

    assert set(artifact["feature_domain"]) == set(artifact["feature_names"])
    assert all(bounds["min"] < bounds["max"] for bounds in artifact["feature_domain"].values())
    assert all(bounds["min"] >= 0.0 for bounds in artifact["feature_domain"].values())
    assert artifact["feature_domain"]["filter_clog_pct"]["max"] <= 1.0
    assert artifact["feature_domain"]["fan_speed_pct"]["max"] <= 1.0
    assert {
        "holdout_rows",
        "positive_prevalence",
        "balanced_accuracy",
        "specificity",
        "f1_score",
        "roc_auc",
        "brier_score",
        "log_loss",
    } <= set(metrics)
