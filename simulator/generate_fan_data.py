"""Generate deterministic synthetic condition-monitoring data for the fan model.

This is deliberately a simulator-training workflow: labels represent a simulated
failure within a maintenance horizon, not an empirical claim about real fans.
"""
import argparse
import csv
import math
import random
from pathlib import Path

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .fan_health import FEATURE_NAMES
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from fan_health import FEATURE_NAMES

DEFAULT_SEED = 20260805
DEFAULT_ROWS = 2400
DEFAULT_OUTPUT = Path(__file__).with_name("data") / "fan_failure_synthetic.csv"


def _sigmoid(value: float) -> float:
    value = max(-50.0, min(50.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def generate_rows(rows: int = DEFAULT_ROWS, seed: int = DEFAULT_SEED) -> list[dict[str, float | int]]:
    """Generate varied, seeded episodes with a hidden causal risk relationship."""
    rng = random.Random(seed)
    generated: list[dict[str, float | int]] = []
    for _ in range(rows):
        clog = rng.uniform(0.0, 0.95)
        speed = rng.uniform(0.08, 1.0)
        run_hours = rng.uniform(0.0, 9000.0)
        wear = min(1.0, 0.05 + run_hours / 15000.0 + rng.uniform(-0.08, 0.08))
        vibration = max(0.4, 0.7 + 3.9 * wear + 1.35 * clog * speed + rng.gauss(0.0, 0.22))
        bearing_temp = 30.0 + 22.0 * speed + 15.0 * clog + 15.0 * wear + rng.gauss(0.0, 1.4)
        logit = (
            -6.3
            + 1.6 * clog
            + 0.9 * speed
            + 0.75 * (vibration - 1.0)
            + 0.105 * (bearing_temp - 35.0)
            + 0.00014 * run_hours
        )
        probability = _sigmoid(logit)
        generated.append(
            {
                "filter_clog_pct": round(clog, 6),
                "fan_speed_pct": round(speed, 6),
                "vibration_mm_s": round(vibration, 6),
                "bearing_temp_c": round(bearing_temp, 6),
                "run_hours": round(run_hours, 6),
                "failure_within_7d": int(rng.random() < probability),
            }
        )
    return generated


def write_csv(path: str | Path, rows: list[dict[str, float | int]]) -> Path:
    """Write generated data with an explicit, stable schema."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*FEATURE_NAMES, "failure_within_7d"]
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = write_csv(args.output, generate_rows(args.rows, args.seed))
    print(f"Wrote {args.rows} deterministic synthetic rows to {path}")


if __name__ == "__main__":
    main()
