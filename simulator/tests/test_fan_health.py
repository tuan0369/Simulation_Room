from fan_health import default_model
from generate_fan_data import generate_rows


def test_synthetic_generator_is_reproducible_with_same_seed():
    assert generate_rows(rows=8, seed=7) == generate_rows(rows=8, seed=7)


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
