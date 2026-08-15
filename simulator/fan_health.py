"""Interpretable fan-health risk model used by the ecosystem simulator.

The runtime model is intentionally small and JSON-serializable. It estimates
simulated fan-failure risk from physical telemetry and exposes the biggest
log-odds contributors so operators can inspect every alert.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
ARTIFACT_TYPE = "standardized_logistic_regression"
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

    failure_risk: float | None
    risk_band: str
    top_drivers: tuple[tuple[str, float], ...]
    model_version: str
    prediction_status: str = "in_distribution"
    status_reason: str | None = None
    available: bool = True
    abstained: bool = False
    out_of_distribution: bool = False


class RiskModel(Protocol):
    """Common prediction interface for loaded and unavailable model states."""

    model_version: str

    def predict(self, telemetry: dict[str, float]) -> RiskPrediction:
        """Return a fan-risk prediction or an explicit non-prediction state."""


@dataclass(frozen=True)
class UnavailableRiskModel:
    """Safe fallback that reports unavailable risk without affecting control."""

    status_reason: str
    model_version: str = MODEL_VERSION

    def predict(self, telemetry: dict[str, float]) -> RiskPrediction:
        del telemetry
        return RiskPrediction(
            failure_risk=None,
            risk_band="unavailable",
            top_drivers=(),
            model_version=self.model_version,
            prediction_status="unavailable",
            status_reason=self.status_reason,
            available=False,
            abstained=True,
        )


def _finite_number(value: object, field: str) -> float:
    """Parse one artifact value while rejecting booleans and NaN/Infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Fan-risk model {field} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Fan-risk model {field} must be a finite number")
    return parsed


def _numeric_array(data: dict, field: str, expected_length: int) -> tuple[float, ...]:
    values = data.get(field)
    if not isinstance(values, list) or len(values) != expected_length:
        raise ValueError("Fan-risk model arrays do not match its feature schema")
    return tuple(_finite_number(value, f"{field}[{index}]") for index, value in enumerate(values))


@dataclass(frozen=True)
class LogisticRiskModel:
    """A standardized binary logistic model persisted as inspectable JSON."""

    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    feature_mins: tuple[float, ...]
    feature_maxs: tuple[float, ...]
    intercept: float
    medium_threshold: float
    high_threshold: float
    model_version: str

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LogisticRiskModel":
        """Load and fully validate the checked-in, versioned model artifact."""
        artifact_path = Path(path) if path is not None else DEFAULT_MODEL_PATH
        with artifact_path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("Fan-risk model artifact must be a JSON object")
        if data.get("artifact_type") != ARTIFACT_TYPE:
            raise ValueError("Unexpected fan-risk model artifact type")
        if data.get("model_version") != MODEL_VERSION:
            raise ValueError("Unexpected fan-risk model version")

        feature_names_value = data.get("feature_names")
        if not isinstance(feature_names_value, list):
            raise ValueError("Unexpected fan-risk model feature schema")
        feature_names = tuple(feature_names_value)
        if feature_names != FEATURE_NAMES:
            raise ValueError("Unexpected fan-risk model feature schema")

        expected_length = len(feature_names)
        means = _numeric_array(data, "means", expected_length)
        scales = _numeric_array(data, "scales", expected_length)
        coefficients = _numeric_array(data, "coefficients", expected_length)
        if any(scale <= 0.0 for scale in scales):
            raise ValueError("Fan-risk model scales must be positive")

        domain = data.get("feature_domain")
        if not isinstance(domain, dict) or set(domain) != set(feature_names):
            raise ValueError("Fan-risk model feature domain does not match its feature schema")
        feature_mins: list[float] = []
        feature_maxs: list[float] = []
        for index, feature in enumerate(feature_names):
            bounds = domain.get(feature)
            if not isinstance(bounds, dict) or set(bounds) != {"min", "max"}:
                raise ValueError(f"Fan-risk model domain for {feature} is invalid")
            minimum = _finite_number(bounds["min"], f"feature_domain.{feature}.min")
            maximum = _finite_number(bounds["max"], f"feature_domain.{feature}.max")
            if minimum >= maximum:
                raise ValueError(f"Fan-risk model domain for {feature} is invalid")
            if not minimum <= means[index] <= maximum:
                raise ValueError(f"Fan-risk model mean for {feature} is outside its domain")
            feature_mins.append(minimum)
            feature_maxs.append(maximum)

        intercept = _finite_number(data.get("intercept"), "intercept")
        medium_threshold = _finite_number(data.get("medium_threshold"), "medium_threshold")
        high_threshold = _finite_number(data.get("high_threshold"), "high_threshold")
        if not 0.0 < medium_threshold < high_threshold < 1.0:
            raise ValueError("Fan-risk model thresholds must satisfy 0 < medium < high < 1")

        return cls(
            feature_names=feature_names,
            means=means,
            scales=scales,
            coefficients=coefficients,
            feature_mins=tuple(feature_mins),
            feature_maxs=tuple(feature_maxs),
            intercept=intercept,
            medium_threshold=medium_threshold,
            high_threshold=high_threshold,
            model_version=MODEL_VERSION,
        )

    def predict(self, telemetry: dict[str, float]) -> RiskPrediction:
        """Return a scored prediction or explicitly abstain on unsafe input."""
        if not isinstance(telemetry, dict):
            return self._abstained("Telemetry must be a feature mapping")

        raw_values: list[float] = []
        for feature in self.feature_names:
            value = telemetry.get(feature)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return self._abstained(f"Missing or nonnumeric telemetry feature: {feature}")
            parsed = float(value)
            if not math.isfinite(parsed):
                return self._abstained(f"Non-finite telemetry feature: {feature}")
            raw_values.append(parsed)

        outside = tuple(
            feature
            for feature, raw, minimum, maximum in zip(
                self.feature_names, raw_values, self.feature_mins, self.feature_maxs
            )
            if raw < minimum or raw > maximum
        )
        if outside:
            return RiskPrediction(
                failure_risk=None,
                risk_band="out_of_distribution",
                top_drivers=(),
                model_version=self.model_version,
                prediction_status="out_of_distribution",
                status_reason=f"Telemetry outside training domain: {', '.join(outside)}",
                abstained=True,
                out_of_distribution=True,
            )

        contributions: list[tuple[str, float]] = []
        logit = self.intercept
        for feature, raw, mean, scale, coefficient in zip(
            self.feature_names, raw_values, self.means, self.scales, self.coefficients
        ):
            contribution = coefficient * ((raw - mean) / scale)
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

    def _abstained(self, reason: str) -> RiskPrediction:
        return RiskPrediction(
            failure_risk=None,
            risk_band="abstained",
            top_drivers=(),
            model_version=self.model_version,
            prediction_status="abstained",
            status_reason=reason,
            abstained=True,
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


def default_model() -> RiskModel:
    """Load the bundled model or expose an unavailable non-predicting fallback."""
    try:
        return LogisticRiskModel.load()
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        return UnavailableRiskModel(f"Fan-risk model unavailable: {type(error).__name__}")
