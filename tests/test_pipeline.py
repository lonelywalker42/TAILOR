"""Tests for data pipeline and export."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tailor.parser.data_pipeline import (
    DataPipeline,
    PipelineConfig,
    PipelineResult,
    ChannelSpec,
    ResampleMethod,
    BASIC_CHANNELS,
    RATE_CONTROL_CHANNELS,
)
from tailor.parser.export import DataExporter
from tailor.parser.coordinate import CoordFrame


@pytest.fixture
def sample_raw_data():
    """Create sample raw data mimicking UlogParser output."""
    t = np.linspace(0, 10, 1000)
    return {
        "sensor_gyro": pd.DataFrame({
            "timestamp_s": t,
            "x": np.sin(t),
            "y": np.cos(t),
            "z": np.sin(2 * t),
        }),
        "sensor_accel": pd.DataFrame({
            "timestamp_s": t,
            "x": np.sin(t) * 9.8,
            "y": np.cos(t) * 9.8,
            "z": -9.8 + np.sin(t) * 0.5,
        }),
        "vehicle_attitude": pd.DataFrame({
            "timestamp_s": t,
            "q[0]": np.ones(1000) * np.cos(0.1),
            "q[1]": np.zeros(1000),
            "q[2]": np.ones(1000) * np.sin(0.1),
            "q[3]": np.zeros(1000),
        }),
        "actuator_controls": pd.DataFrame({
            "timestamp_s": t,
            "control[0]": np.sin(t) * 0.5,
            "control[1]": np.cos(t) * 0.5,
            "control[2]": np.ones(1000) * 0.6,
            "control[3]": np.zeros(1000),
        }),
    }


class TestDataPipeline:
    def test_basic_extraction(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
                ChannelSpec("sensor_gyro", "y", "Gyro_Y", category="state"),
            ]
        )
        result = pipeline.run(sample_raw_data, config)
        assert not result.data.empty
        assert "Gyro_X" in result.data.columns
        assert "Gyro_Y" in result.data.columns
        assert len(result.data) == 1000

    def test_missing_channel(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("nonexistent", "x", "Missing", category="state"),
            ]
        )
        result = pipeline.run(sample_raw_data, config)
        assert result.data.empty

    def test_time_windowing(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
            ],
            t_start=2.0,
            t_end=8.0,
        )
        result = pipeline.run(sample_raw_data, config)
        assert result.data.index[0] >= 2.0
        assert result.data.index[-1] <= 8.0

    def test_resample(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
            ],
            resample_rate=100.0,
        )
        result = pipeline.run(sample_raw_data, config)
        # 10 seconds at 100 Hz = ~1001 samples
        assert len(result.data) == 1001

    def test_detrend(self, sample_raw_data):
        # Add a trend to the data
        sample_raw_data["sensor_gyro"]["x"] = np.linspace(0, 100, 1000) + np.sin(np.linspace(0, 10, 1000))

        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
            ],
            detrend=True,
        )
        result = pipeline.run(sample_raw_data, config)
        # After detrending, mean should be near zero
        assert abs(result.data["Gyro_X"].mean()) < 1.0

    def test_lowpass(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
            ],
            resample_rate=100.0,
            apply_lowpass=True,
            lowpass_cutoff=5.0,
        )
        result = pipeline.run(sample_raw_data, config)
        assert not result.data.empty

    def test_multi_channel_merge(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
                ChannelSpec("sensor_accel", "x", "Accel_X", category="state"),
                ChannelSpec("actuator_controls", "control[0]", "Ctrl_Roll", category="control"),
            ]
        )
        result = pipeline.run(sample_raw_data, config)
        assert len(result.data.columns) == 3
        assert set(result.data.columns) == {"Gyro_X", "Accel_X", "Ctrl_Roll"}

    def test_metadata(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
            ],
            target_frame=CoordFrame.NED,
        )
        result = pipeline.run(sample_raw_data, config)
        assert result.metadata["n_channels"] == 1
        assert result.metadata["target_frame"] == "ned"
        assert result.metadata["n_samples"] > 0


class TestDataExporter:
    @pytest.fixture
    def pipeline_result(self, sample_raw_data):
        pipeline = DataPipeline()
        config = PipelineConfig(
            channels=[
                ChannelSpec("sensor_gyro", "x", "Gyro_X", category="state"),
                ChannelSpec("sensor_gyro", "y", "Gyro_Y", category="state"),
            ],
            resample_rate=100.0,
        )
        return pipeline.run(sample_raw_data, config)

    def test_csv_export(self, pipeline_result, tmp_path):
        exporter = DataExporter()
        out = exporter.export_csv(pipeline_result, tmp_path / "test.csv")
        assert out.exists()
        content = out.read_text()
        assert "TAILOR Data Export" in content
        assert "Gyro_X" in content

    def test_csv_no_header(self, pipeline_result, tmp_path):
        exporter = DataExporter()
        out = exporter.export_csv(pipeline_result, tmp_path / "test.csv", include_header=False)
        content = out.read_text()
        assert "TAILOR" not in content
        assert "Gyro_X" in content.split("\n")[0]  # Header row

    def test_mat_export(self, pipeline_result, tmp_path):
        exporter = DataExporter()
        out = exporter.export_mat(pipeline_result, tmp_path / "test.mat")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_parquet_export(self, pipeline_result, tmp_path):
        exporter = DataExporter()
        out = exporter.export_parquet(pipeline_result, tmp_path / "test.parquet")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_auto_detect_format(self, pipeline_result, tmp_path):
        exporter = DataExporter()

        csv_out = exporter.export(pipeline_result, tmp_path / "auto.csv")
        assert csv_out.exists()

        mat_out = exporter.export(pipeline_result, tmp_path / "auto.mat")
        assert mat_out.exists()

        pq_out = exporter.export(pipeline_result, tmp_path / "auto.parquet")
        assert pq_out.exists()
