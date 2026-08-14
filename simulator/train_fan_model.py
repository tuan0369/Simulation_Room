"""Train and serialize an interpretable NumPy logistic fan-risk model."""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .fan_health import FEATURE_NAMES, MODEL_VERSION
    from .generate_fan_data import DEFAULT_SEED, generate_rows, write_csv
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from fan_health import FEATURE_NAMES, MODEL_VERSION
    from generate_fan_data import DEFAULT_SEED, generate_rows, write_csv

DEFAULT_ARTIFACT = Path(__file__).with_name("models") / "fan_risk_logistic.json"
DEFAULT_DATASET = Path(__file__).with_name("data") / "fan_failure_synthetic.csv"


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50.0, 50.0)))


def _matrix(rows: list[dict[str, float | int]]) -> tuple[np.ndarray, np.ndarray]:
    features = np.array([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float)
    labels = np.array([float(row["failure_within_7d"]) for row in rows], dtype=float)
    return features, labels


def _metrics(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    predicted = probabilities >= 0.5
    truth = labels.astype(bool)
    true_positive = int(np.sum(predicted & truth))
    false_positive = int(np.sum(predicted & ~truth))
    false_negative = int(np.sum(~predicted & truth))
    true_negative = int(np.sum(~predicted & ~truth))
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    return {
        "accuracy": round((true_positive + true_negative) / max(1, len(labels)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
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
    artifact = {
        "artifact_type": "standardized_logistic_regression",
        "model_version": MODEL_VERSION,
        "description": "Synthetic-data fan failure risk model. It estimates simulated failure risk, not real-world equipment failure probability.",
        "feature_names": list(FEATURE_NAMES),
        "means": [round(float(value), 8) for value in means],
        "scales": [round(float(value), 8) for value in scales],
        "coefficients": [round(float(value), 8) for value in weights],
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
