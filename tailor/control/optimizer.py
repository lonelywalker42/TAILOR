"""PID optimizer — multi-objective gain tuning with constraints.

Supports:
- Numeric optimization (SLSQP, Nelder-Mead)
- Classical tuning rules (Ziegler-Nichols, SIMC)
- Constraint-based search (stability, margins, actuator limits)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

import numpy as np
from scipy.optimize import minimize, differential_evolution

from tailor.control.pid_controller import (
    PIDGains,
    PIDStructure,
    ControlAxis,
    AxisConfig,
    ControllerParams,
    PIDController,
)


class TuningMethod(Enum):
    ZIEGLER_NICHOLS = "ziegler_nichols"
    SIMC = "simc"
    OPTIMIZER = "optimizer"
    MANUAL = "manual"


@dataclass
class TuningObjective:
    """User-defined tuning objectives and constraints."""
    target_bandwidth_hz: float = 5.0        # Desired closed-loop bandwidth
    min_phase_margin_deg: float = 35.0      # Minimum phase margin
    max_overshoot_pct: float = 15.0         # Maximum overshoot %
    max_settling_time_s: float = 0.5        # Maximum settling time
    max_control_effort: float = 1.0         # Max normalized control effort
    weight_bandwidth: float = 1.0           # Objective weights
    weight_margin: float = 1.0
    weight_overshoot: float = 1.0
    weight_settling: float = 0.5

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class TuningResult:
    """Result of an optimization run."""
    method: TuningMethod
    original_gains: PIDGains
    optimized_gains: PIDGains
    axis: str
    plant_tf: tuple  # (num, den)

    # Performance before
    before_bandwidth_hz: float = 0.0
    before_phase_margin_deg: float = 0.0
    before_overshoot_pct: float = 0.0

    # Performance after
    after_bandwidth_hz: float = 0.0
    after_phase_margin_deg: float = 0.0
    after_overshoot_pct: float = 0.0

    cost: float = 0.0                    # Final optimization cost
    iterations: int = 0
    converged: bool = False
    metadata: dict = field(default_factory=dict)

    def improvement_summary(self) -> str:
        bw_gain = self.after_bandwidth_hz / max(self.before_bandwidth_hz, 0.001)
        return (
            f"Bandwidth: {self.before_bandwidth_hz:.2f} → {self.after_bandwidth_hz:.2f} Hz ({bw_gain:.1f}x)\n"
            f"Phase margin: {self.before_phase_margin_deg:.1f} → {self.after_phase_margin_deg:.1f}°\n"
            f"Overshoot: {self.before_overshoot_pct:.1f} → {self.after_overshoot_pct:.1f}%"
        )


class PIDOptimizer:
    """Optimize PID gains to meet user-specified performance objectives."""

    def __init__(self):
        self.controller = PIDController()

    def optimize(
        self,
        plant_tf: tuple[np.ndarray, np.ndarray],
        initial_gains: PIDGains,
        objective: TuningObjective,
        axis: str = "roll",
        structure: PIDStructure = PIDStructure.PI_FF,
        dt: float = 0.01,
        method: TuningMethod = TuningMethod.OPTIMIZER,
    ) -> TuningResult:
        """Run PID optimization.

        Args:
            plant_tf: Plant transfer function (num, den).
            initial_gains: Starting PID gains.
            objective: Tuning targets and constraints.
            axis: Control axis name.
            structure: PID structure.
            dt: Sample time.
            method: Tuning method.

        Returns:
            TuningResult with optimized gains and performance comparison.
        """
        self.controller = PIDController(structure=structure)

        # Evaluate initial performance
        before = self.controller.evaluate_performance(initial_gains, plant_tf, dt)

        if method == TuningMethod.ZIEGLER_NICHOLS:
            optimized = self._ziegler_nichols(plant_tf, initial_gains, dt)
        elif method == TuningMethod.SIMC:
            optimized = self._simc(plant_tf, initial_gains, dt)
        elif method == TuningMethod.OPTIMIZER:
            optimized = self._numeric_optimize(plant_tf, initial_gains, objective, dt)
        else:
            optimized = initial_gains

        # Evaluate optimized performance
        after = self.controller.evaluate_performance(optimized, plant_tf, dt)

        result = TuningResult(
            method=method,
            original_gains=initial_gains,
            optimized_gains=optimized,
            axis=axis,
            plant_tf=plant_tf,
            before_bandwidth_hz=before.get("bandwidth_hz", 0),
            before_phase_margin_deg=before.get("phase_margin_deg", 0),
            before_overshoot_pct=before.get("overshoot_pct", 0),
            after_bandwidth_hz=after.get("bandwidth_hz", 0),
            after_phase_margin_deg=after.get("phase_margin_deg", 0),
            after_overshoot_pct=after.get("overshoot_pct", 0),
        )

        return result

    def optimize_all_axes(
        self,
        plant_tfs: dict[str, tuple[np.ndarray, np.ndarray]],
        initial_params: ControllerParams,
        objective: TuningObjective,
        dt: float = 0.01,
        method: TuningMethod = TuningMethod.OPTIMIZER,
    ) -> dict[str, TuningResult]:
        """Optimize PID for multiple axes.

        Returns:
            Dict of axis_name -> TuningResult.
        """
        results = {}
        for axis_name, cfg in initial_params.axes.items():
            plant = plant_tfs.get(axis_name)
            if plant is None:
                continue
            result = self.optimize(
                plant_tf=plant,
                initial_gains=cfg.gains,
                objective=objective,
                axis=axis_name,
                structure=cfg.structure,
                dt=dt,
                method=method,
            )
            results[axis_name] = result
        return results

    # ─── Numeric Optimization ─────────────────────────────────────────

    def _numeric_optimize(
        self,
        plant_tf: tuple[np.ndarray, np.ndarray],
        initial_gains: PIDGains,
        objective: TuningObjective,
        dt: float,
    ) -> PIDGains:
        """Numeric multi-objective optimization using SLSQP."""
        # Parameter vector: [kp, ki, kd, kff]
        x0 = np.array([
            initial_gains.kp or 0.1,
            initial_gains.ki or 0.01,
            initial_gains.kd or 0.001,
            initial_gains.kff or 0.0,
        ])

        # Bounds: gains must be non-negative, with reasonable upper limits
        bounds = [
            (1e-6, 100.0),   # kp
            (0.0, 50.0),     # ki
            (0.0, 10.0),     # kd
            (0.0, 10.0),     # kff
        ]

        def cost_function(x):
            gains = PIDGains(kp=x[0], ki=x[1], kd=x[2], kff=x[3])
            try:
                perf = self.controller.evaluate_performance(gains, plant_tf, dt)
            except Exception:
                return 1e6

            if not perf.get("is_stable", False):
                return 1e6

            # Multi-objective cost
            cost = 0.0

            # Bandwidth tracking
            bw_error = abs(perf.get("bandwidth_hz", 0) - objective.target_bandwidth_hz)
            cost += objective.weight_bandwidth * bw_error / max(objective.target_bandwidth_hz, 0.01)

            # Phase margin constraint
            pm = perf.get("phase_margin_deg", 0)
            if pm < objective.min_phase_margin_deg:
                cost += objective.weight_margin * (objective.min_phase_margin_deg - pm) / 10.0

            # Overshoot constraint
            os = perf.get("overshoot_pct", 100)
            if os > objective.max_overshoot_pct:
                cost += objective.weight_overshoot * (os - objective.max_overshoot_pct) / 10.0

            # Settling time constraint
            ts = perf.get("settling_time_s", 100)
            if ts > objective.max_settling_time_s:
                cost += objective.weight_settling * (ts - objective.max_settling_time_s)

            # Regularization: prefer smaller gains
            cost += 0.001 * np.sum(np.array(x) ** 2)

            return cost

        # Run optimization
        result = minimize(
            cost_function,
            x0,
            method='SLSQP',
            bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-8},
        )

        # Also try differential evolution for global search
        try:
            de_result = differential_evolution(
                cost_function,
                bounds=bounds,
                maxiter=200,
                seed=42,
                tol=1e-6,
            )
            if de_result.fun < result.fun:
                result = de_result
        except Exception:
            pass

        return PIDGains(
            kp=float(result.x[0]),
            ki=float(result.x[1]),
            kd=float(result.x[2]),
            kff=float(result.x[3]),
        )

    # ─── Ziegler-Nichols ──────────────────────────────────────────────

    def _ziegler_nichols(
        self,
        plant_tf: tuple[np.ndarray, np.ndarray],
        initial_gains: PIDGains,
        dt: float,
    ) -> PIDGains:
        """Ziegler-Nichols open-loop (step response) method.

        Identifies process gain K, dead time L, and time constant T
        from a step response, then applies Z-N tuning rules.
        """
        # Simulate open-loop step response
        p_num, p_den = plant_tf
        n = 1000
        t = np.arange(n) * dt
        u = np.ones(n)

        try:
            sys = sp_signal.dlti(p_num, p_den, dt=dt)
            result = sp_signal.dlsim(sys, u, t=t)
            y = result[1].flatten()
        except Exception:
            return initial_gains

        # Identify K (process gain), L (dead time), T (time constant)
        K = float(y[-1]) if len(y) > 0 else 1.0
        if abs(K) < 1e-6:
            return initial_gains

        # Dead time: time to reach 5% of final value
        threshold_05 = 0.05 * K
        idx_05 = np.where(np.abs(y) >= abs(threshold_05))[0]
        L = float(t[idx_05[0]]) if len(idx_05) > 0 else dt

        # Time constant: time to reach 63.2% of final value
        threshold_63 = 0.632 * K
        idx_63 = np.where(np.abs(y) >= abs(threshold_63))[0]
        T_raw = float(t[idx_63[0]]) if len(idx_63) > 0 else 1.0
        T = max(T_raw - L, dt)

        # Z-N tuning rules for PID
        kp = 1.2 * T / (K * L) if K * L > 0 else initial_gains.kp
        ki = kp / (2.0 * L) if L > 0 else initial_gains.ki
        kd = kp * 0.5 * L if L > 0 else initial_gains.kd

        return PIDGains(kp=kp, ki=ki, kd=kd, kff=initial_gains.kff)

    # ─── SIMC (Skogestad IMC) ─────────────────────────────────────────

    def _simc(
        self,
        plant_tf: tuple[np.ndarray, np.ndarray],
        initial_gains: PIDGains,
        dt: float,
    ) -> PIDGains:
        """SIMC (Skogestad IMC) tuning rules.

        Uses a first-order-plus-dead-time (FOPDT) model approximation.
        """
        # Identify FOPDT parameters from step response
        p_num, p_den = plant_tf
        n = 1000
        t = np.arange(n) * dt
        u = np.ones(n)

        try:
            sys = sp_signal.dlti(p_num, p_den, dt=dt)
            result = sp_signal.dlsim(sys, u, t=t)
            y = result[1].flatten()
        except Exception:
            return initial_gains

        K = float(y[-1]) if len(y) > 0 else 1.0
        if abs(K) < 1e-6:
            return initial_gains

        # Dead time
        threshold_05 = 0.05 * K
        idx_05 = np.where(np.abs(y) >= abs(threshold_05))[0]
        L = float(t[idx_05[0]]) if len(idx_05) > 0 else dt

        # Time constant
        threshold_63 = 0.632 * K
        idx_63 = np.where(np.abs(y) >= abs(threshold_63))[0]
        T_raw = float(t[idx_63[0]]) if len(idx_63) > 0 else 1.0
        T = max(T_raw - L, dt)

        # SIMC tuning: tau_c = max(L, T/3) for aggressive, L for moderate
        tau_c = max(L, T / 3)

        # SIMC PI rules
        kp = T / (K * (tau_c + L)) if K * (tau_c + L) > 0 else initial_gains.kp
        ki = kp / T if T > 0 else initial_gains.ki

        # SIMC PID adds derivative
        kd = kp * L  # Simplified SIMC derivative

        return PIDGains(kp=kp, ki=ki, kd=kd, kff=initial_gains.kff)


def quick_tune(
    plant_tf: tuple[np.ndarray, np.ndarray],
    method: TuningMethod = TuningMethod.SIMC,
    axis: str = "roll",
    dt: float = 0.01,
) -> TuningResult:
    """Convenience function for quick PID tuning.

    Args:
        plant_tf: Plant transfer function (num, den).
        method: Tuning method.
        axis: Control axis name.
        dt: Sample time.

    Returns:
        TuningResult with tuned gains.
    """
    from tailor.control.pid_controller import default_rate_gains, ControlAxis

    try:
        axis_enum = ControlAxis(axis.lower())
    except ValueError:
        axis_enum = ControlAxis.ROLL
    cfg = default_rate_gains(axis_enum)

    optimizer = PIDOptimizer()
    return optimizer.optimize(
        plant_tf=plant_tf,
        initial_gains=cfg.gains,
        objective=TuningObjective(),
        axis=axis,
        structure=cfg.structure,
        dt=dt,
        method=method,
    )
