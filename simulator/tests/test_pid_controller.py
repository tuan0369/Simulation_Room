"""Tests for the PID controller module."""
from pid_controller import PIDController


def test_output_clamped_to_unit_range():
    """PID output must always be in [0.0, 1.0]."""
    pid = PIDController()
    # Very hot room should produce output clamped at 1.0
    out = pid.compute(current_temp=40.0, setpoint=22.0, dt=1.0)
    assert 0.0 <= out <= 1.0

    pid.reset()
    # Very cold room should produce output clamped at 0.0
    out = pid.compute(current_temp=18.0, setpoint=28.0, dt=1.0)
    assert 0.0 <= out <= 1.0
    assert out == 0.0  # room is cooler than setpoint, no cooling needed


def test_positive_error_increases_output():
    """When room is hotter than setpoint, output should be positive."""
    pid = PIDController()
    out = pid.compute(current_temp=30.0, setpoint=25.0, dt=1.0)
    assert out > 0.0


def test_negative_error_zero_output():
    """When room is cooler than setpoint, output should be 0."""
    pid = PIDController()
    out = pid.compute(current_temp=20.0, setpoint=25.0, dt=1.0)
    assert out == 0.0


def test_output_proportional_to_error():
    """Larger error should produce larger output."""
    pid1 = PIDController()
    out_small = pid1.compute(current_temp=26.0, setpoint=25.0, dt=1.0)

    pid2 = PIDController()
    out_large = pid2.compute(current_temp=30.0, setpoint=25.0, dt=1.0)

    assert out_large > out_small


def test_reset_clears_state():
    """After reset, PID should behave as if freshly initialized."""
    pid = PIDController()
    # Build up some integral
    for _ in range(20):
        pid.compute(current_temp=30.0, setpoint=25.0, dt=1.0)

    pid.reset()
    assert pid._integral == 0.0
    assert pid._prev_error == 0.0
    assert pid._initialized is False


def test_integral_anti_windup():
    """Integral should be bounded by INTEGRAL_MAX."""
    pid = PIDController()
    # Many iterations with constant error to saturate integral
    for _ in range(1000):
        pid.compute(current_temp=40.0, setpoint=20.0, dt=1.0)

    assert abs(pid._integral) <= pid.INTEGRAL_MAX


def test_zero_dt_no_crash():
    """dt=0 should not cause division by zero."""
    pid = PIDController()
    pid.compute(current_temp=28.0, setpoint=25.0, dt=1.0)
    out = pid.compute(current_temp=29.0, setpoint=25.0, dt=0.0)
    assert 0.0 <= out <= 1.0


def test_actuator_feedback_reduces_integral_under_shared_capacity_limit():
    constrained = PIDController()
    unconstrained = PIDController()
    for _ in range(20):
        requested = constrained.compute(current_temp=27.0, setpoint=24.0, dt=1.0)
        constrained.apply_actuator_feedback(requested, requested * 0.25, dt=1.0)
        unconstrained.compute(current_temp=27.0, setpoint=24.0, dt=1.0)
    assert constrained._integral < unconstrained._integral


def test_actuator_feedback_ignores_full_delivery():
    pid = PIDController()
    requested = pid.compute(current_temp=27.0, setpoint=24.0, dt=1.0)
    before = pid._integral
    pid.apply_actuator_feedback(requested, requested, dt=1.0)
    assert pid._integral == before


def test_steady_state_at_setpoint():
    """When temperature equals setpoint, output should be near zero."""
    pid = PIDController()
    out = pid.compute(current_temp=25.0, setpoint=25.0, dt=1.0)
    assert out == 0.0
