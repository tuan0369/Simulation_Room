"""PID Controller for automatic HVAC temperature regulation.

Acts as the 'AI assistant' that continuously measures room temperature
and adjusts AC power to maintain the desired setpoint.
"""
from dataclasses import dataclass, field


@dataclass
class PIDController:
    """Proportional-Integral-Derivative controller for AC power output.

    Input: error = current_temperature - setpoint
        (positive error means room is too hot)
    Output: ac_power_pct in [0.0, 1.0]
        0.0 = AC off / minimum power
        1.0 = AC at full power (max cooling)
    """

    kp: float = 0.40     # proportional gain: 100% power at ~2.5°C error
    ki: float = 0.05     # integral gain: eliminate steady-state error faster
    kd: float = 0.05     # derivative gain: dampen oscillations

    _integral: float = field(default=0.0, repr=False)
    _prev_error: float = field(default=0.0, repr=False)
    _initialized: bool = field(default=False, repr=False)

    # Anti-windup: limit integral accumulation (ki * INTEGRAL_MAX = 1.0)
    INTEGRAL_MAX: float = field(default=20.0, repr=False)

    def compute(self, current_temp: float, setpoint: float, dt: float) -> float:
        """Compute AC power percentage based on temperature error.

        Args:
            current_temp: Current room temperature in °C
            setpoint: Desired room temperature in °C
            dt: Time step in seconds

        Returns:
            ac_power_pct: Float in [0.0, 1.0] representing AC power level
        """
        error = current_temp - setpoint  # positive = too hot

        if not self._initialized:
            self._prev_error = error
            self._initialized = True

        # Proportional term
        p_term = self.kp * error

        # Integral term with anti-windup
        self._integral += error * dt
        self._integral = max(-self.INTEGRAL_MAX, min(self.INTEGRAL_MAX, self._integral))
        i_term = self.ki * self._integral

        # Derivative term
        if dt > 0:
            d_term = self.kd * (error - self._prev_error) / dt
        else:
            d_term = 0.0
        self._prev_error = error

        # Sum and clamp output to [0, 1]
        output = p_term + i_term + d_term
        return max(0.0, min(1.0, output))

    def apply_actuator_feedback(
        self,
        requested_output: float,
        applied_output: float,
        dt: float,
    ) -> None:
        """Bleed integral state when the shared actuator cannot meet a request."""
        duration = max(0.0, float(dt))
        requested = max(0.0, min(1.0, float(requested_output)))
        applied = max(0.0, min(requested, float(applied_output)))
        if duration <= 0.0 or requested <= applied + 1e-9 or self.ki <= 0.0:
            return
        tracking_error = requested - applied
        self._integral -= tracking_error * duration / max(self.ki * 10.0, 1e-9)
        self._integral = max(-self.INTEGRAL_MAX, min(self.INTEGRAL_MAX, self._integral))

    def reset(self):
        """Reset controller state. Call when HVAC is turned off."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._initialized = False
