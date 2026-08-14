"""Interpretable fan-health risk model used by the ecosystem simulator.

The runtime model is intentionally small and JSON-serializable. It estimates
simulated fan-failure risk from physical telemetry and exposes the biggest
log-odds contributors so operators can inspect every alert.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path

try:  # Supports both `python -m simulator...` and legacy script launches.
    from .physics import clamp
except ImportError:  # pragma: no cover - exercised by direct script entry points.
    from physics import clamp

FEATURE_NAMES = (
    "filter_clog_pct",
    "fan_speed_pct",
    "vibration_mm_s",
    "bearing_temp_c",
    "run_hours",
)
MODEL_VERSION = "fan-risk-logistic-v1"
DEFAULT_MODEL_PATH = Path(__file__).with_name("models") / "fan_risk_logistic.json"


@dataclass(frozen=True)
class FanState:
    """Simulated condition-monitoring state for the shared AHU fan."""

    run_hours: float = 40.0
    wear_pct: float = 0.03
    vibration_mm_s: float = 1.15
    bearing_temp_c: float = 38.0
    health_pct: float = 97.0


@dataclass(frozen=True)
class RiskPrediction:
    """A human-readable result of the fan failure-risk calculation."""

    failure_risk: float
    risk_band: str
    top_drivers: tuple[tuple[str, float], ...]
    model_version: str


@dataclass(frozen=True)
class LogisticRiskModel:
    """A standardized binary logistic model persisted as inspectable JSON."""

    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    medium_threshold: float
    high_threshold: float
    model_version: str

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LogisticRiskModel":
        """Load the checked-in, versioned model artifact."""
        artifact_path = Path(path) if path is not None else DEFAULT_MODEL_PATH
        with artifact_path.open(encoding="utf-8") as file:
            data = json.load(file)
        feature_names = tuple(data["feature_names"])
        if feature_names != FEATURE_NAMES:
            raise ValueError("Unexpected fan-risk model feature schema")
        values = (
            tuple(float(value) for value in data["means"]),
            tuple(float(value) for value in data["scales"]),
            tuple(float(value) for value in data["coefficients"]),
        )
        if any(len(value) != len(feature_names) for value in values):
            raise ValueError("Fan-risk model arrays do not match its feature schema")
        return cls(
            feature_names=feature_names,
            means=values[0],
            scales=values[1],
            coefficients=values[2],
            intercept=float(data["intercept"]),
            medium_threshold=float(data.get("medium_threshold", 0.35)),
            high_threshold=float(data.get("high_threshold", 0.65)),
            model_version=str(data.get("model_version", MODEL_VERSION)),
        )

    def predict(self, telemetry: dict[str, float]) -> RiskPrediction:
        """Return probability, band, and sorted positive driver contributions."""
        contributions: list[tuple[str, float]] = []
        logit = self.intercept
        for feature, mean, scale, coefficient in zip(
            self.feature_names, self.means, self.scales, self.coefficients
        ):
            raw = float(telemetry[feature])
            standardized = (raw - mean) / max(scale, 1e-9)
            contribution = coefficient * standardized
            logit += contribution
            contributions.append((feature, contribution))
        clipped_logit = max(-50.0, min(50.0, logit))
        risk = 1.0 / (1.0 + math.exp(-clipped_logit))
        if risk >= self.high_threshold:
            band = "high"
        elif risk >= self.medium_threshold:
            band = "medium"
        else:
            band = "low"
        return RiskPrediction(
            failure_risk=risk,
            risk_band=band,
            top_drivers=tuple(
                sorted(contributions, key=lambda item: item[1], reverse=True)[:3]
            ),
            model_version=self.model_version,
        )


def step_fan_state(
    fan: FanState,
    *,
    fan_speed_pct: float,
    filter_clog_pct: float,
    dt: float,
) -> FanState:
    """Advance fan wear, bearing temperature, vibration, and health."""
    speed = clamp(fan_speed_pct, 0.0, 1.0)
    clog = clamp(filter_clog_pct, 0.0, 1.0)
    duration = max(0.0, dt)
    wear = clamp(fan.wear_pct + duration * speed * (0.0000008 + clog * 0.0000015), 0.0, 1.0)
    target_temp = 31.0 + 23.0 * speed + 13.0 * clog + 12.0 * wear
    bearing_temp = fan.bearing_temp_c + (target_temp - fan.bearing_temp_c) * min(1.0, duration / 45.0)
    vibration = 0.8 + 4.0 * wear + 1.4 * clog * speed
    health = clamp(100.0 - 72.0 * wear - 20.0 * clog, 0.0, 100.0)
    return FanState(
        run_hours=fan.run_hours + duration * speed / 3600.0,
        wear_pct=wear,
        vibration_mm_s=vibration,
        bearing_temp_c=bearing_temp,
        health_pct=health,
    )


def fan_telemetry(fan: FanState, *, fan_speed_pct: float, filter_clog_pct: float) -> dict[str, float]:
    """Map simulation state to the stable model feature contract."""
    return {
        "filter_clog_pct": clamp(filter_clog_pct, 0.0, 1.0),
        "fan_speed_pct": clamp(fan_speed_pct, 0.0, 1.0),
        "vibration_mm_s": fan.vibration_mm_s,
        "bearing_temp_c": fan.bearing_temp_c,
        "run_hours": fan.run_hours,
    }


def default_model() -> LogisticRiskModel:
    """Load the default model artifact bundled with the simulator."""
    return LogisticRiskModel.load()
