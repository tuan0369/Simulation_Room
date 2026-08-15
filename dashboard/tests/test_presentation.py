from datetime import datetime, timezone
from math import inf, nan

import pytest

from ..presentation import (
    allocation_explanation,
    comfort_status,
    data_freshness,
    illustrative_roi,
    maintenance_recommendation,
)


@pytest.mark.parametrize(
    ("risk_band", "expected_severity", "expected_title", "expected_action"),
    [
        ("high", "high", "Prioritise simulated AHU inspection", "Inspect the filter"),
        ("medium", "medium", "Schedule a simulated condition inspection", "Inspect filter loading"),
        ("low", "low", "Continue simulated monitoring", "No maintenance action is generated"),
    ],
)
def test_maintenance_recommendation_returns_actionable_band_guidance(
    risk_band, expected_severity, expected_title, expected_action
):
    recommendation = maintenance_recommendation(
        risk_band,
        drivers=[{"feature": "bearing_temp_c"}, {"feature": "vibration_mm_s"}],
    )

    assert recommendation.severity == expected_severity
    assert recommendation.title == expected_title
    assert expected_action in recommendation.action
    assert "bearing temp c, vibration mm s" in recommendation.rationale


@pytest.mark.parametrize(
    ("risk_band", "expected_rationale"),
    [
        ("out_of_distribution", "outside the model training domain"),
        ("abstained", "could not be scored safely"),
        ("unavailable", "model is unavailable"),
        ("unexpected", "must not be interpreted as low risk"),
        (None, "must not be interpreted as low risk"),
    ],
)
def test_maintenance_recommendation_never_treats_non_predictions_as_low_risk(
    risk_band, expected_rationale
):
    recommendation = maintenance_recommendation(risk_band)

    assert recommendation.severity == "unknown"
    assert recommendation.title == "Fan-risk assessment unavailable"
    assert "Do not infer low risk" in recommendation.action
    assert expected_rationale in recommendation.rationale


def test_maintenance_recommendation_uses_telemetry_fallback_for_missing_drivers():
    recommendation = maintenance_recommendation("LOW", drivers=[None, {}, {"other": "ignored"}])

    assert recommendation.severity == "low"
    assert "current fan-condition telemetry" in recommendation.rationale


@pytest.mark.parametrize(
    ("temperature", "setpoint", "allocation_pct", "expected_status", "expected_detail"),
    [
        (None, 24.0, 1.0, "Waiting for telemetry", "No confirmed temperature/setpoint pair"),
        (25.0, 24.0, 0.6, "Capacity constrained", "+1.0 °C above target"),
        (25.1, 24.0, 1.0, "Comfort attention", "+1.1 °C above target"),
        (22.9, 24.0, 1.0, "Below target", "1.1 °C below target"),
        (24.5, 24.0, 1.0, "Comfort on track", "0.5 °C from target"),
    ],
)
def test_comfort_status_describes_telemetry_capacity_and_temperature_states(
    temperature, setpoint, allocation_pct, expected_status, expected_detail
):
    status, detail = comfort_status(temperature, setpoint, allocation_pct)

    assert status == expected_status
    assert expected_detail in detail


def test_data_freshness_distinguishes_missing_invalid_fresh_and_stale_timestamps():
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)

    assert data_freshness(None, now=now) == ("Unknown", "No telemetry timestamp is available.")
    assert data_freshness("not-a-timestamp", now=now) == ("Unknown", "Telemetry timestamp is invalid.")

    fresh_status, fresh_detail = data_freshness("2026-08-05T11:59:55Z", now=now)
    assert fresh_status == "Fresh"
    assert fresh_detail == "Last telemetry 5s ago."

    stale_status, stale_detail = data_freshness("2026-08-05T11:59:49+00:00", now=now)
    assert stale_status == "Stale"
    assert stale_detail == "Last telemetry 11s ago; do not treat it as live control confirmation."


def test_data_freshness_treats_future_telemetry_as_current_and_handles_naive_now():
    status, detail = data_freshness(
        "2026-08-05T12:00:05+00:00",
        now=datetime(2026, 8, 5, 12, 0, 0),
    )

    assert status == "Fresh"
    assert detail == "Last telemetry 0s ago."


def test_allocation_explanation_handles_waiting_sufficient_and_invalid_decisions():
    labels = {"r1": "Room One"}

    assert allocation_explanation({}, labels) == "Waiting for the shared-AHU coordinator decision."
    assert (
        allocation_explanation({"constrained": False}, labels)
        == "Shared AHU capacity is sufficient: all current cooling requests can be granted."
    )
    assert (
        allocation_explanation({"constrained": True, "rooms": "invalid"}, labels)
        == "Shared capacity is constrained; review the latest coordinator decision."
    )


def test_allocation_explanation_identifies_prioritized_and_limited_rooms():
    explanation = allocation_explanation(
        {
            "constrained": True,
            "rooms": [
                {"room_id": "r1", "requested_airflow_m3_s": 0.12, "granted_airflow_m3_s": 0.12},
                {"room_id": "r2", "requested_airflow_m3_s": 0.12, "granted_airflow_m3_s": 0.04},
            ],
        },
        {"r1": "Room One", "r2": "Room Two"},
    )

    assert explanation == (
        "Shared airflow is scarce: Room One received the higher comfort priority; "
        "Room Two received less than requested."
    )


def test_allocation_explanation_handles_all_limited_and_fully_distributed_capacity():
    labels = {"r1": "Room One"}

    assert allocation_explanation(
        {
            "constrained": True,
            "rooms": [{"room_id": "r1", "requested_airflow_m3_s": 0.1, "granted_airflow_m3_s": 0.0}],
        },
        labels,
    ) == "Shared airflow is scarce: Room One received less than requested."
    assert allocation_explanation(
        {
            "constrained": True,
            "rooms": [{"room_id": "r1", "requested_airflow_m3_s": 0.1, "granted_airflow_m3_s": 0.1}],
        },
        labels,
    ) == "Shared capacity is constrained; the coordinator has distributed the currently available airflow."


def test_illustrative_roi_returns_transparent_calculation_breakdown():
    roi = illustrative_roi(
        annual_energy_kwh=100_000,
        tariff_sgd_per_kwh=0.30,
        energy_reduction_pct=0.10,
        avoided_incident_value_sgd=2_000,
        annual_support_cost_sgd=1_000,
        implementation_cost_sgd=4_000,
    )

    assert roi == {
        "baseline_energy_cost_sgd": 30_000.0,
        "energy_savings_sgd": 3_000.0,
        "annual_benefit_sgd": 5_000.0,
        "annual_net_benefit_sgd": 4_000.0,
        "roi_pct": 0.0,
        "payback_months": 12.0,
    }


def test_illustrative_roi_clamps_negative_and_out_of_range_business_inputs():
    roi = illustrative_roi(
        annual_energy_kwh=-100,
        tariff_sgd_per_kwh=-0.30,
        energy_reduction_pct=2.0,
        avoided_incident_value_sgd=-50,
        annual_support_cost_sgd=-20,
        implementation_cost_sgd=-10,
    )

    assert roi == {
        "baseline_energy_cost_sgd": 0.0,
        "energy_savings_sgd": 0.0,
        "annual_benefit_sgd": 0.0,
        "annual_net_benefit_sgd": 0.0,
        "roi_pct": 0.0,
        "payback_months": 0.0,
    }


@pytest.mark.parametrize("invalid_value", ["100", None, nan, inf, -inf])
def test_illustrative_roi_rejects_non_finite_or_non_numeric_inputs(invalid_value):
    with pytest.raises(ValueError, match="ROI inputs must be finite numbers"):
        illustrative_roi(
            annual_energy_kwh=100_000,
            tariff_sgd_per_kwh=0.30,
            energy_reduction_pct=0.10,
            avoided_incident_value_sgd=2_000,
            annual_support_cost_sgd=1_000,
            implementation_cost_sgd=invalid_value,
        )
