"""Integration tests — cross-module pipeline verification.

Tests the full flow: data → pipeline → identification → PID tuning → report,
without requiring real .ulg files. Uses synthetic data matching module interfaces.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from scipy import signal as sp_signal

from tailor.parser.data_pipeline import (
    DataPipeline,
    PipelineConfig,
    ChannelSpec,
)
from tailor.parser.export import DataExporter
from tailor.dynamics.identifier import SystemIdentifier, TransferFunctionModel, IdentificationMethod
from tailor.dynamics.excitation import find_identification_segments
from tailor.dynamics.validation import ModelValidator, compute_step_response_data, compute_frequency_response_data
from tailor.control.pid_controller import (
    PIDController,
    PIDGains,
    PIDStructure,
    ControlAxis,
    AxisConfig,
    ControllerParams,
    default_rate_gains,
)
from tailor.control.optimizer import PIDOptimizer, TuningObjective, TuningMethod, quick_tune
from tailor.control.report import ReportGenerator, build_flight_report


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def raw_data_dict():
    """Create synthetic raw_data dict mimicking UlogParser output.

    Returns dict of message_name -> DataFrame, matching UlogParser.get_core_data() format.
    Uses PRBS-like random excitation for persistently exciting input.
    """
    n = 2000
    t = np.arange(n) * 0.01  # 20 seconds at 100 Hz
    np.random.seed(42)

    # Simulate system response with random excitation
    num = np.array([0.0, 0.0, 0.5])
    den = np.array([1.0, -1.5, 0.7])
    sys = sp_signal.dlti(num, den, dt=0.01)
    u_rand = np.random.randn(n)
    result = sp_signal.dlsim(sys, u_rand, t=t)
    y_clean = result[1].flatten()
    y_noisy = y_clean + 0.01 * np.random.randn(n)

    return {
        "actuator_controls_0": pd.DataFrame({
            "timestamp_s": t,
            "control[0]": u_rand,
            "control[1]": np.zeros(n),
        }),
        "vehicle_attitude": pd.DataFrame({
            "timestamp_s": t,
            "roll": y_noisy,
            "pitch": y_noisy * 0.8,
            "yaw": np.cumsum(np.random.randn(n) * 0.001),
        }),
        "sensor_accel": pd.DataFrame({
            "timestamp_s": t,
            "x": np.random.randn(n) * 0.5,
            "y": np.random.randn(n) * 0.3,
            "z": -9.8 + np.random.randn(n) * 0.2,
        }),
    }


@pytest.fixture
def identification_data():
    """Create synthetic u, y arrays for direct identification testing.

    Uses PRBS-like random excitation for persistently exciting input.
    """
    n = 2000
    t = np.arange(n) * 0.01
    np.random.seed(42)

    num = np.array([0.0, 0.0, 0.5])
    den = np.array([1.0, -1.5, 0.7])
    sys = sp_signal.dlti(num, den, dt=0.01)
    u = np.random.randn(n)
    result = sp_signal.dlsim(sys, u, t=t)
    y = result[1].flatten() + 0.01 * np.random.randn(n)

    return u, y, 0.01


# ── Data Pipeline → Identification ─────────────────────────────────────────

class TestPipelineToIdentification:
    """Test that pipeline output feeds correctly into identification."""

    def test_pipeline_output_shape(self, raw_data_dict):
        """Pipeline produces correct output structure."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator Input"),
                ChannelSpec("vehicle_attitude", "roll", "Roll Angle"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)
        assert not result.data.empty
        assert "Actuator Input" in result.data.columns
        assert "Roll Angle" in result.data.columns

    def test_pipeline_to_arx_identification(self, raw_data_dict):
        """Pipeline data feeds into ARX identification correctly."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        u = result.data["Actuator"].values
        y = result.data["Roll"].values

        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="actuator", output_channel="roll",
        )

        assert isinstance(model, TransferFunctionModel)
        assert model.fit_percent > 30
        assert model.order_den == 2

    def test_pipeline_to_oe_identification(self, raw_data_dict):
        """Pipeline data feeds into OE identification (ARX → OE refinement)."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        u = result.data["Actuator"].values
        y = result.data["Roll"].values

        identifier = SystemIdentifier()
        model = identifier.identify_oe(
            u, y, nf=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        assert isinstance(model, TransferFunctionModel)
        assert model.fit_percent > 0

    def test_pipeline_to_frequency_identification(self, raw_data_dict):
        """Pipeline data feeds into frequency-domain identification."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        u = result.data["Actuator"].values
        y = result.data["Roll"].values

        identifier = SystemIdentifier()
        model = identifier.identify_frequency(
            u, y, order=4, dt=0.01,
            input_channel="act", output_channel="att",
        )

        assert isinstance(model, TransferFunctionModel)


# ── Identification → Validation ────────────────────────────────────────────

class TestIdentificationToValidation:
    """Test that identification results feed into validation correctly."""

    def test_model_validation_metrics(self, identification_data):
        """Identified model produces valid step/frequency metrics."""
        u, y, dt = identification_data

        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        # Step response metrics
        step = ModelValidator.step_response_metrics(model)
        assert step.rise_time_s > 0
        assert step.settling_time_s > 0

        # Frequency metrics
        freq = ModelValidator.frequency_metrics(model)
        assert freq.bandwidth_hz > 0

    def test_residual_analysis(self, identification_data):
        """Residual analysis works on identified model."""
        u, y, dt = identification_data

        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        residuals = ModelValidator.residual_analysis(model, u, y)
        assert "acf" in residuals
        assert "std" in residuals
        assert residuals["std"] > 0

    def test_model_comparison(self, identification_data):
        """Compare multiple models identified from same data."""
        u, y, dt = identification_data

        identifier = SystemIdentifier()
        model1 = identifier.identify_arx(
            u, y, na=1, nb=1, nk=1,
            input_channel="act", output_channel="att",
        )
        model2 = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        comparison = ModelValidator.compare_models([model1, model2])
        assert len(comparison.models) == 2
        assert comparison.best_index in [0, 1]
        assert len(comparison.fit_percents) == 2


# ── Identification → PID Tuning ────────────────────────────────────────────

class TestIdentificationToPID:
    """Test that identified models feed into PID optimization."""

    def test_model_to_pid_tuning(self, identification_data):
        """TransferFunctionModel can be loaded into PID optimizer."""
        u, y, dt = identification_data

        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        # Use model for PID tuning
        plant_tf = (model.num, model.den)
        result = quick_tune(plant_tf, method=TuningMethod.SIMC, axis="roll", dt=model.dt)

        assert isinstance(result.optimized_gains, PIDGains)
        assert result.optimized_gains.kp > 0

    def test_model_to_optimizer(self, identification_data):
        """Identified model works with numeric optimizer."""
        u, y, dt = identification_data

        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        plant_tf = (model.num, model.den)
        optimizer = PIDOptimizer()
        tuning_result = optimizer.optimize(
            plant_tf=plant_tf,
            initial_gains=PIDGains(kp=0.1, ki=0.1),
            objective=TuningObjective(target_bandwidth_hz=3.0),
            axis="roll",
            dt=model.dt,
            method=TuningMethod.SIMC,
        )

        assert tuning_result.optimized_gains.kp > 0
        assert tuning_result.after_bandwidth_hz > 0


# ── Full Pipeline → Report ─────────────────────────────────────────────────

class TestFullPipelineReport:
    """Test end-to-end: data → identify → tune → report."""

    def test_full_report_generation(self, identification_data, tmp_path):
        """Generate report from identification + tuning results."""
        u, y, dt = identification_data

        # Identify
        identifier = SystemIdentifier()
        model = identifier.identify_arx(
            u, y, na=2, nb=2, nk=1,
            input_channel="act", output_channel="att",
        )

        # Tune
        plant_tf = (model.num, model.den)
        tuning = quick_tune(plant_tf=plant_tf, method=TuningMethod.SIMC, axis="roll", dt=model.dt)

        # Report
        metadata = {
            "file_name": "test.ulg",
            "firmware_version": "v1.14.0",
            "duration_s": 20.0,
            "message_count": 2000,
            "drop_rate": 0.0,
        }
        t = np.arange(len(y)) * dt
        channels = {"vehicle_attitude.roll": y}

        out_path = tmp_path / "report.html"
        html = build_flight_report(
            log_metadata=metadata,
            channels=channels,
            time=t,
            identification_results=[model],
            tuning_result=tuning,
            output_path=out_path,
        )

        assert out_path.exists()
        assert "飞行分析报告" in html
        assert "KP" in html  # PID comparison table
        assert "test.ulg" in html  # Flight info

    def test_report_with_px4_export(self, tmp_path):
        """Generate PX4 parameter file from tuning result."""
        plant_tf = (np.array([0.0, 0.05]), np.array([1.0, -0.8]))
        result = quick_tune(plant_tf, method=TuningMethod.SIMC, axis="roll")

        gains = result.optimized_gains
        params = f"""# TAILOR PID Export
MC_ROLLRATE_P {gains.kp:.6f}
MC_ROLLRATE_I {gains.ki:.6f}
MC_ROLLRATE_D {gains.kd:.6f}
MC_ROLLRATE_FF {gains.kff:.6f}
"""
        out = tmp_path / "params.params"
        out.write_text(params, encoding="utf-8")

        content = out.read_text(encoding="utf-8")
        assert "MC_ROLLRATE_P" in content


# ── Export Integration ──────────────────────────────────────────────────────

class TestExportIntegration:
    """Test data export from pipeline results."""

    def test_csv_export_roundtrip(self, raw_data_dict, tmp_path):
        """Export pipeline result to CSV and verify."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        exporter = DataExporter()
        out_path = tmp_path / "export.csv"
        exporter.export_csv(result, out_path)

        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "Actuator" in content

    def test_parquet_export(self, raw_data_dict, tmp_path):
        """Export pipeline result to Parquet."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Actuator"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        exporter = DataExporter()
        out_path = tmp_path / "export.parquet"
        try:
            exporter.export_parquet(result, out_path)
            assert out_path.exists()
        except ImportError:
            pytest.skip("pyarrow not available")


# ── Excitation → Identification ────────────────────────────────────────────

class TestExcitationToIdentification:
    """Test that excitation detection feeds into identification."""

    def test_find_segments_and_identify(self):
        """Detect excitation in signal, then identify from those segments."""
        n = 5000
        t = np.arange(n) * 0.01
        np.random.seed(123)

        # Create signal with clear step excitation
        y = np.zeros(n)
        y[500:1500] = 1.0
        y[2000:3000] = -0.5
        y[3500:4500] = 0.8
        y += 0.02 * np.random.randn(n)

        segments = find_identification_segments(t, {"test_channel": y})
        # Should find at least one segment
        assert len(segments) >= 1

    def test_excitation_with_identification(self):
        """Use excitation detection to guide identification."""
        n = 2000
        t = np.arange(n) * 0.01
        np.random.seed(42)

        # Simulate step response
        num = np.array([0.0, 0.5])
        den = np.array([1.0, -0.8])
        sys = sp_signal.dlti(num, den, dt=0.01)
        u = np.zeros(n)
        u[100:1000] = 1.0
        result = sp_signal.dlsim(sys, u, t=t)
        y = result[1].flatten() + 0.01 * np.random.randn(n)

        # Find segments
        segments = find_identification_segments(t, {"input": u, "output": y})
        assert len(segments) >= 1

        # Use first segment for identification
        seg = segments[0]
        start_idx = int(seg.t_start / 0.01)
        end_idx = int(seg.t_end / 0.01)
        u_seg = u[start_idx:end_idx]
        y_seg = y[start_idx:end_idx]

        if len(u_seg) > 50:
            identifier = SystemIdentifier()
            model = identifier.identify_arx(
                u_seg, y_seg, na=1, nb=1, nk=1,
                input_channel="u", output_channel="y",
            )
            assert model.fit_percent > 0


# ── Auto Order Selection ───────────────────────────────────────────────────

class TestAutoOrderSelection:
    """Test automatic model order selection across the pipeline."""

    def test_auto_order_with_identification(self):
        """Auto-select order, then identify with selected order."""
        n = 2000
        t = np.arange(n) * 0.01
        np.random.seed(42)

        num = np.array([0.0, 0.0, 0.5])
        den = np.array([1.0, -1.5, 0.7])
        sys = sp_signal.dlti(num, den, dt=0.01)
        u = np.random.randn(n)
        result = sp_signal.dlsim(sys, u, t=t)
        y = result[1].flatten() + 0.01 * np.random.randn(n)

        identifier = SystemIdentifier()
        best_order, best_model = identifier.auto_select_order(
            u, y, max_order=4,
        )

        assert 1 <= best_order <= 4
        assert isinstance(best_model, TransferFunctionModel)
        assert best_model.order_den == best_order


# ── Multi-Axis PID ─────────────────────────────────────────────────────────

class TestMultiAxisPID:
    """Test PID tuning across multiple axes."""

    def test_optimize_all_axes(self):
        """Optimize PID for roll, pitch, yaw simultaneously."""
        plant_tf = (np.array([0.0, 0.05]), np.array([1.0, -0.8]))

        params = ControllerParams(axes={
            "roll": AxisConfig(
                axis=ControlAxis.ROLL,
                structure=PIDStructure.PI_FF,
                gains=PIDGains(kp=0.1, ki=0.05),
            ),
            "pitch": AxisConfig(
                axis=ControlAxis.PITCH,
                structure=PIDStructure.PI_FF,
                gains=PIDGains(kp=0.1, ki=0.05),
            ),
            "yaw": AxisConfig(
                axis=ControlAxis.YAW,
                structure=PIDStructure.PI_FF,
                gains=PIDGains(kp=0.2, ki=0.1),
            ),
        })

        optimizer = PIDOptimizer()
        results = optimizer.optimize_all_axes(
            plant_tfs={"roll": plant_tf, "pitch": plant_tf, "yaw": plant_tf},
            initial_params=params,
            objective=TuningObjective(),
            method=TuningMethod.SIMC,
        )

        assert len(results) == 3
        assert all(r.optimized_gains.kp > 0 for r in results.values())

    def test_px4_params_export_all_axes(self):
        """Export PX4 params for all axes."""
        params = ControllerParams(axes={
            "roll": AxisConfig(
                axis=ControlAxis.ROLL,
                structure=PIDStructure.PID_FF,
                gains=PIDGains(kp=0.15, ki=0.2, kd=0.003),
            ),
            "pitch": AxisConfig(
                axis=ControlAxis.PITCH,
                structure=PIDStructure.PID_FF,
                gains=PIDGains(kp=0.12, ki=0.18, kd=0.002),
            ),
        })

        px4 = params.to_px4_params()
        assert "MC_ROLL_P" in px4
        assert "MC_PITCH_P" in px4
        assert px4["MC_ROLL_P"] == 0.15


# ── Pipeline + Coord Transform ─────────────────────────────────────────────

class TestPipelineCoordTransform:
    """Test pipeline with coordinate transforms."""

    def test_pipeline_with_quaternion(self, raw_data_dict):
        """Pipeline handles quaternion-based attitude data."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
                ChannelSpec("vehicle_attitude", "pitch", "Pitch"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        assert not result.data.empty
        assert "Roll" in result.data.columns
        assert "Pitch" in result.data.columns

    def test_pipeline_channel_merging(self, raw_data_dict):
        """Pipeline correctly merges multiple channels."""
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("actuator_controls_0", "control[0]", "Input"),
                ChannelSpec("vehicle_attitude", "roll", "Roll"),
                ChannelSpec("vehicle_attitude", "pitch", "Pitch"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(raw_data_dict, config)

        assert not result.data.empty
        assert len(result.data.columns) == 3
        # All channels should have same length (aligned)
        for col in result.data.columns:
            assert len(result.data[col]) == len(result.data["Input"])
