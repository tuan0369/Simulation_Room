"""Train and serialize an interpretable NumPy logistic fan-risk model."""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .fan_health import ARTIFACT_TYPE, FEATURE_NAMES, MODEL_VERSION
    from .generate_fan_data import DEFAULT_SEED, generate_rows, write_csv
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from fan_health import ARTIFACT_TYPE, FEATURE_NAMES, MODEL_VERSION
    from generate_fan_data import DEFAULT_SEED, generate_rows, write_csv

DEFAULT_ARTIFACT = Path(__file__).with_name("models") / "fan_risk_logistic.json"
DEFAULT_DATASET = Path(__file__).with_name("data") / "fan_failure_synthetic.csv"


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50.0, 50.0)))


def _matrix(rows: list[dict[str, float | int]]) -> tuple[np.ndarray, np.ndarray]:
    features = np.array([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float)
    labels = np.array([float(row["failure_within_7d"]) for row in rows], dtype=float)
    return features, labels


def _roc_auc(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """Compute deterministic ROC AUC using pairwise positive/negative ordering."""
    positive = probabilities[labels == 1]
    negative = probabilities[labels == 0]
    if len(positive) == 0 or len(negative) == 0:
        return 0.0
    comparisons = positive[:, None] - negative[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)


def _metrics(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, float | int]:
    predicted = probabilities >= 0.5
    truth = labels.astype(bool)
    true_positive = int(np.sum(predicted & truth))
    false_positive = int(np.sum(predicted & ~truth))
    false_negative = int(np.sum(~predicted & truth))
    true_negative = int(np.sum(~predicted & ~truth))
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    specificity = true_negative / max(1, true_negative + false_positive)
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    return {
        "holdout_rows": int(len(labels)),
        "positive_prevalence": round(float(labels.mean()), 4),
        "accuracy": round((true_positive + true_negative) / max(1, len(labels)), 4),
        "balanced_accuracy": round((recall + specificity) / 2.0, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "f1_score": round(2.0 * precision * recall / max(1e-12, precision + recall), 4),
        "roc_auc": round(_roc_auc(probabilities, labels), 4),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4),
        "log_loss": round(float(-np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped))), 4),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
    }


def fit_model(
    rows: list[dict[str, float | int]],
    *,
    seed: int = DEFAULT_SEED,
    iterations: int = 2400,
    learning_rate: float = 0.08,
) -> tuple[dict, dict]:
    """Fit a deterministic standardized logistic regression and return metrics."""
    if len(rows) < 10:
        raise ValueError("At least ten synthetic rows are required to train the model")
    features, labels = _matrix(rows)
    rng = np.random.default_rng(seed)
    indices = rng.permutation(len(rows))
    split = max(1, int(len(rows) * 0.8))
    train_idx, test_idx = indices[:split], indices[split:]
    train_x, test_x = features[train_idx], features[test_idx]
    train_y, test_y = labels[train_idx], labels[test_idx]
    means = train_x.mean(axis=0)
    scales = train_x.std(axis=0)
    scales[scales < 1e-9] = 1.0
    x = (train_x - means) / scales
    weights = np.zeros(x.shape[1], dtype=float)
    intercept = 0.0
    for _ in range(iterations):
        probabilities = _sigmoid(x @ weights + intercept)
        error = probabilities - train_y
        weights -= learning_rate * (x.T @ error / len(train_y))
        intercept -= learning_rate * float(error.mean())
    test_probabilities = _sigmoid(((test_x - means) / scales) @ weights + intercept)
    domain_padding_fraction = 0.30
    domain_mins = train_x.min(axis=0)
    domain_maxs = train_x.max(axis=0)
    domain_padding = (domain_maxs - domain_mins) * domain_padding_fraction
    physical_limits = {
        "filter_clog_pct": (0.0, 1.0),
        "fan_speed_pct": (0.0, 1.0),
        "vibration_mm_s": (0.0, math.inf),
        "bearing_temp_c": (0.0, math.inf),
        "run_hours": (0.0, math.inf),
    }
    feature_domain = {}
    for index, feature in enumerate(FEATURE_NAMES):
        physical_min, physical_max = physical_limits[feature]
        feature_domain[feature] = {
            "min": round(max(physical_min, float(domain_mins[index] - domain_padding[index])), 8),
            "max": round(min(physical_max, float(domain_maxs[index] + domain_padding[index])), 8),
        }
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "model_version": MODEL_VERSION,
        "description": "Synthetic-data fan failure risk model. It estimates simulated failure risk, not real-world equipment failure probability.",
        "feature_names": list(FEATURE_NAMES),
        "means": [round(float(value), 8) for value in means],
        "scales": [round(float(value), 8) for value in scales],
        "coefficients": [round(float(value), 8) for value in weights],
        "feature_domain": feature_domain,
        "feature_domain_method": "physical_limits_and_training_min_max_with_30pct_range_padding",
        "intercept": round(float(intercept), 8),
        "medium_threshold": 0.35,
        "high_threshold": 0.65,
        "generator_seed": seed,
        "training_rows": int(len(train_idx)),
        "holdout_rows": int(len(test_idx)),
    }
    return artifact, _metrics(test_probabilities, test_y)


def write_artifact(path: str | Path, artifact: dict, metrics: dict) -> Path:
    """Persist an inspectable artifact and a colocated metric summary."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.with_suffix(".metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def _read_csv(path: Path) -> list[dict[str, float | int]]:
    with path.open(newline="", encoding="utf-8") as file:
        return [
            {
                **{feature: float(row[feature]) for feature in FEATURE_NAMES},
                "failure_within_7d": int(row["failure_within_7d"]),
            }
            for row in csv.DictReader(file)
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--rows", type=int, default=2400)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--iterations", type=int, default=2400)
    args = parser.parse_args()
    rows = generate_rows(args.rows, args.seed)
    write_csv(args.dataset, rows)
    artifact, metrics = fit_model(rows, seed=args.seed, iterations=args.iterations)
    path = write_artifact(args.artifact, artifact, metrics)
    print(f"Saved model artifact to {path}")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
