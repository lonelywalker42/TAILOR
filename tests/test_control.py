"""Tests for PID controller, optimizer, and report generator."""

from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path

from tailor.control.pid_controller import (
    PIDController,
    PIDGains,
    PIDStructure,
    ControlAxis,
    AxisConfig,
    ControllerParams,
    default_rate_gains,
    extract_px4_params,
)
from tailor.control.optimizer import (
    PIDOptimizer,
    TuningMethod,
    TuningObjective,
    TuningResult,
    quick_tune,
)
from tailor.control.report import ReportGenerator


@pytest.fixture
def plant_tf():
    """Simple 2nd-order plant."""
    return (np.array([0.0, 0.05, 0.04]), np.array([1.0, -1.5, 0.7]))


@pytest.fixture
def stable_plant():
    """Stable 1st-order plant."""
    return (np.array([0.0, 0.5]), np.array([1.0, -0.5]))


class TestPIDGains:
    def test_defaults(self):
        g = PIDGains()
        assert g.kp == 0.0
        assert g.ki == 0.0
        assert g.kd == 0.0
        assert g.kff == 0.0

    def test_serialization(self):
        g = PIDGains(kp=0.15, ki=0.2, kd=0.003, kff=0.01)
        d = g.to_dict()
        g2 = PIDGains.from_dict(d)
        assert g2.kp == g.kp
        assert g2.ki == g.ki


class TestControllerParams:
    def test_to_px4_params(self):
        params = ControllerParams(axes={
            "roll": AxisConfig(
                axis=ControlAxis.ROLL,
                structure=PIDStructure.PID_FF,
                gains=PIDGains(kp=0.15, ki=0.2, kd=0.003),
            )
        })
        px4 = params.to_px4_params()
        assert "MC_ROLL_P" in px4
        assert "MC_ROLL_I" in px4
        assert "MC_ROLL_D" in px4

    def test_serialization(self):
        params = ControllerParams(axes={
            "roll": AxisConfig(
                axis=ControlAxis.ROLL,
                structure=PIDStructure.PI_FF,
                gains=PIDGains(kp=0.1, ki=0.05),
            )
        })
        d = params.to_dict()
        restored = ControllerParams.from_dict(d)
        assert restored.roll.gains.kp == 0.1


class TestPIDController:
    def test_pi_ff_tf(self, plant_tf):
        ctrl = PIDController(PIDStructure.PI_FF)
        gains = PIDGains(kp=0.15, ki=0.2)
        num, den = ctrl._controller_tf(gains)
        assert len(num) == 3  # [kff, kp, ki]
        assert len(den) == 2  # [1, 0]

    def test_pid_ff_tf(self, plant_tf):
        ctrl = PIDController(PIDStructure.PID_FF)
        gains = PIDGains(kp=0.15, ki=0.2, kd=0.003)
        num, den = ctrl._controller_tf(gains)
        assert len(num) == 3
        assert len(den) == 3

    def test_closed_loop_stable(self, stable_plant):
        ctrl = PIDController(PIDStructure.PI_FF)
        gains = PIDGains(kp=0.3, ki=0.5)
        perf = ctrl.evaluate_performance(gains, stable_plant, dt=0.01)
        assert perf["is_stable"]

    def test_simulate(self, stable_plant):
        ctrl = PIDController(PIDStructure.PI_FF)
        gains = PIDGains(kp=0.3, ki=0.5)
        ref = np.ones(500)
        t, y, u = ctrl.simulate_closed_loop(gains, stable_plant, ref, dt=0.01)
        assert len(y) == 500
        assert len(u) == 500

    def test_evaluate_performance(self, plant_tf):
        ctrl = PIDController(PIDStructure.PI_FF)
        gains = PIDGains(kp=0.15, ki=0.2)
        perf = ctrl.evaluate_performance(gains, plant_tf, dt=0.01)
        assert "bandwidth_hz" in perf
        assert "phase_margin_deg" in perf
        assert "overshoot_pct" in perf


class TestPIDOptimizer:
    def test_simc_tuning(self, plant_tf):
        optimizer = PIDOptimizer()
        result = optimizer.optimize(
            plant_tf=plant_tf,
            initial_gains=PIDGains(kp=0.1, ki=0.1),
            objective=TuningObjective(),
            axis="roll",
            dt=0.01,
            method=TuningMethod.SIMC,
        )
        assert isinstance(result, TuningResult)
        assert result.optimized_gains.kp > 0

    def test_ziegler_nichols(self, plant_tf):
        optimizer = PIDOptimizer()
        result = optimizer.optimize(
            plant_tf=plant_tf,
            initial_gains=PIDGains(kp=0.1, ki=0.1),
            objective=TuningObjective(),
            method=TuningMethod.ZIEGLER_NICHOLS,
        )
        assert result.optimized_gains.kp > 0

    def test_optimizer(self, stable_plant):
        optimizer = PIDOptimizer()
        result = optimizer.optimize(
            plant_tf=stable_plant,
            initial_gains=PIDGains(kp=0.3, ki=0.5),
            objective=TuningObjective(target_bandwidth_hz=3.0),
            method=TuningMethod.OPTIMIZER,
        )
        assert result.optimized_gains.kp > 0
        assert result.after_bandwidth_hz > 0

    def test_quick_tune(self, stable_plant):
        result = quick_tune(stable_plant, method=TuningMethod.SIMC, axis="roll")
        assert result.optimized_gains.kp > 0

    def test_result_improvement_summary(self, plant_tf):
        optimizer = PIDOptimizer()
        result = optimizer.optimize(
            plant_tf=plant_tf,
            initial_gains=PIDGains(kp=0.1, ki=0.1),
            objective=TuningObjective(),
            method=TuningMethod.SIMC,
        )
        summary = result.improvement_summary()
        assert "Bandwidth" in summary
        assert "Phase margin" in summary


class TestReportGenerator:
    def test_generate_html(self):
        gen = ReportGenerator()
        html = gen.generate_html(
            title="Test Report",
            flight_info={"File": "test.ulg", "Duration": "60s"},
            key_metrics=[{"label": "Duration", "value": "60s"}],
        )
        assert "Test Report" in html
        assert "test.ulg" in html
        assert "Duration" in html

    def test_html_with_charts(self):
        gen = ReportGenerator()
        html = gen.generate_html(
            title="Chart Report",
            charts=[{"title": "Test Chart", "image": "", "description": "A test chart"}],
        )
        assert "Test Chart" in html

    def test_html_with_recommendations(self):
        gen = ReportGenerator()
        html = gen.generate_html(
            title="Rec Report",
            recommendations=["Increase Kp", "Add derivative term"],
        )
        assert "Increase Kp" in html

    def test_html_to_file(self, tmp_path):
        gen = ReportGenerator()
        out = tmp_path / "report.html"
        html = gen.generate_html(title="File Report", output_path=out)
        assert out.exists()
        assert "File Report" in out.read_text(encoding="utf-8")

    def test_plot_time_series(self):
        gen = ReportGenerator()
        t = np.linspace(0, 5, 500)
        signals = {"sin": np.sin(t), "cos": np.cos(t)}
        b64 = gen.plot_time_series(t, signals, title="Test Plot")
        # b64 may be empty if matplotlib not available
        assert isinstance(b64, str)
