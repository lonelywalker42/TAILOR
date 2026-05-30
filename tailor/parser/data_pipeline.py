"""Data pipeline: channel selection, time windowing, resampling, coordinate transform."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd
from scipy import signal as sp_signal

from tailor.parser.coordinate import (
    CoordFrame,
    CoordinateTransformer,
    TailSitterCoordinateManager,
    quat_to_rotation,
)


class ResampleMethod(Enum):
    INTERPOLATE = "interpolate"    # Linear interpolation
    NEAREST = "nearest"            # Nearest neighbor
    ZERO_ORDER_HOLD = "zoh"        # Zero-order hold (step)


@dataclass
class ChannelSpec:
    """Specification for a single data channel."""
    message: str           # uORB message name, e.g. "vehicle_attitude"
    field: str             # Field name, e.g. "q[0]"
    display_name: str      # Human-readable name, e.g. "Attitude Qw"
    unit: str = ""         # Physical unit
    category: str = ""     # "state", "control", "derived"
    coord_frame: str = CoordFrame.FRD


@dataclass
class PipelineConfig:
    """Configuration for a data pipeline run."""
    channels: list[ChannelSpec] = field(default_factory=list)
    t_start: Optional[float] = None          # Time window start (seconds)
    t_end: Optional[float] = None            # Time window end (seconds)
    target_frame: CoordFrame = CoordFrame.FRD
    resample_rate: Optional[float] = None    # Hz, None = keep original
    resample_method: ResampleMethod = ResampleMethod.INTERPOLATE
    flight_phase: Optional[str] = None       # "multirotor", "fixedwing", "transition"
    apply_lowpass: bool = False
    lowpass_cutoff: Optional[float] = None   # Hz
    lowpass_order: int = 4
    detrend: bool = False


@dataclass
class PipelineResult:
    """Result of a data pipeline run."""
    data: pd.DataFrame           # Columns = channel display names, index = timestamp_s
    metadata: dict               # Pipeline config summary
    channel_specs: list[ChannelSpec]


class DataPipeline:
    """Processes raw parsed data into aligned, transformed, analysis-ready datasets.

    Typical flow:
    1. Load raw message DataFrames from UlogParser
    2. Select channels per PipelineConfig
    3. Apply time windowing
    4. Apply coordinate transforms (if needed)
    5. Resample to uniform time base
    6. Apply optional filtering / detrending
    7. Return unified DataFrame
    """

    def __init__(self):
        self.transformer = CoordinateTransformer()
        self.ts_manager = TailSitterCoordinateManager()

    def run(
        self,
        raw_data: dict[str, pd.DataFrame],
        config: PipelineConfig,
        attitude_quat: Optional[pd.DataFrame] = None,
        flight_mode_segments: Optional[list[dict]] = None,
    ) -> PipelineResult:
        """Execute the pipeline.

        Args:
            raw_data: Dict of message_name -> DataFrame from UlogParser.
            config: Pipeline configuration.
            attitude_quat: vehicle_attitude DataFrame with q[0..3] columns (for coord transforms).
            flight_mode_segments: Output of UlogParser.get_flight_mode_segments().

        Returns:
            PipelineResult with aligned DataFrame.
        """
        # Step 1: Extract requested channels
        series_list = []
        valid_specs = []
        for ch in config.channels:
            s = self._extract_channel(raw_data, ch)
            if s is not None:
                series_list.append(s)
                valid_specs.append(ch)

        if not series_list:
            return PipelineResult(
                data=pd.DataFrame(),
                metadata={"error": "No valid channels found"},
                channel_specs=[],
            )

        # Step 2: Merge into a single DataFrame on timestamp
        merged = self._merge_series(series_list)

        # Step 3: Time windowing
        if config.t_start is not None or config.t_end is not None:
            merged = self._apply_time_window(merged, config.t_start, config.t_end)

        if merged.empty:
            return PipelineResult(
                data=pd.DataFrame(),
                metadata={"error": "No data in selected time window"},
                channel_specs=[],
            )

        # Step 4: Coordinate transforms
        if config.target_frame != CoordFrame.FRD and attitude_quat is not None:
            merged = self._apply_coordinate_transform(
                merged, valid_specs, attitude_quat, config, flight_mode_segments
            )

        # Step 5: Resample
        if config.resample_rate is not None:
            merged = self._resample(merged, config.resample_rate, config.resample_method)

        # Step 6: Filtering
        if config.detrend:
            merged = self._detrend(merged)

        if config.apply_lowpass and config.lowpass_cutoff is not None:
            merged = self._apply_lowpass(
                merged, config.lowpass_cutoff,
                config.resample_rate or self._estimate_rate(merged),
                config.lowpass_order,
            )

        return PipelineResult(
            data=merged,
            metadata={
                "n_channels": len(valid_specs),
                "n_samples": len(merged),
                "t_start": float(merged.index[0]) if len(merged) > 0 else 0,
                "t_end": float(merged.index[-1]) if len(merged) > 0 else 0,
                "target_frame": config.target_frame.value,
                "resample_rate": config.resample_rate,
            },
            channel_specs=valid_specs,
        )

    def _extract_channel(
        self, raw_data: dict[str, pd.DataFrame], ch: ChannelSpec
    ) -> Optional[pd.Series]:
        """Extract a single channel from raw data."""
        df = raw_data.get(ch.message)
        if df is None or df.empty:
            return None

        # Handle multi-instance data (instance column)
        if "instance" in df.columns:
            df = df[df["instance"] == 0]

        if ch.field not in df.columns:
            # Try common aliases
            aliases = {
                "q[0]": ["q[0]", "q_0", "q0"],
                "q[1]": ["q[1]", "q_1", "q1"],
                "q[2]": ["q[2]", "q_2", "q2"],
                "q[3]": ["q[3]", "q_3", "q3"],
            }
            found = False
            for canonical, alts in aliases.items():
                if ch.field == canonical:
                    for alt in alts:
                        if alt in df.columns:
                            ch.field = alt
                            found = True
                            break
                if found:
                    break
            if not found:
                return None

        if "timestamp_s" not in df.columns:
            return None

        s = pd.Series(
            data=df[ch.field].values,
            index=df["timestamp_s"].values,
            name=ch.display_name,
        )
        # Drop NaN
        s = s.dropna()
        return s

    def _merge_series(self, series_list: list[pd.Series]) -> pd.DataFrame:
        """Merge multiple series into a single DataFrame, aligning by index."""
        if len(series_list) == 1:
            return series_list[0].to_frame()

        # Use merge_asof for tolerant alignment, then interpolate gaps
        dfs = [s.to_frame() for s in series_list]
        result = dfs[0]
        for df in dfs[1:]:
            result = result.join(df, how="outer")

        # Sort by time
        result = result.sort_index()

        # Interpolate small gaps (up to 0.1s)
        result = result.interpolate(method="index", limit_area="inside")

        # Drop rows that are still all NaN
        result = result.dropna(how="all")

        return result

    def _apply_time_window(
        self, df: pd.DataFrame, t_start: Optional[float], t_end: Optional[float]
    ) -> pd.DataFrame:
        """Filter data to a time window."""
        mask = pd.Series(True, index=df.index)
        if t_start is not None:
            mask &= df.index >= t_start
        if t_end is not None:
            mask &= df.index <= t_end
        return df[mask]

    def _apply_coordinate_transform(
        self,
        merged: pd.DataFrame,
        specs: list[ChannelSpec],
        attitude_df: pd.DataFrame,
        config: PipelineConfig,
        flight_mode_segments: Optional[list[dict]],
    ) -> pd.DataFrame:
        """Apply coordinate transforms to channels that need it."""
        # Get quaternion data aligned to merged timestamps
        quat_cols = ["q[0]", "q[1]", "q[2]", "q[3]"]
        available_quat_cols = [c for c in quat_cols if c in attitude_df.columns]
        if len(available_quat_cols) < 4:
            return merged  # Can't transform without quaternion

        quat_ts = attitude_df["timestamp_s"].values
        quat_data = attitude_df[available_quat_cols].values

        # Interpolate quaternion to match merged timestamps
        merged_t = merged.index.values
        quat_interp = np.zeros((len(merged_t), 4))
        for i in range(4):
            quat_interp[:, i] = np.interp(merged_t, quat_ts, quat_data[:, i])

        # Normalize quaternions
        norms = np.linalg.norm(quat_interp, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        quat_interp = quat_interp / norms

        # Determine flight mode for each timestamp
        modes = self._get_mode_per_timestamp(merged_t, flight_mode_segments)

        # Transform channels that are in body frame
        for spec in specs:
            if spec.coord_frame != CoordFrame.FRD:
                continue
            col_name = spec.display_name
            if col_name not in merged.columns:
                continue

            vec_body = merged[col_name].values

            # Determine if this channel is part of a 3D vector
            # Look for sibling channels
            vec3 = self._try_get_vector3(merged, col_name, specs)
            if vec3 is not None:
                transformed = self._transform_vector3_batch(
                    vec3, quat_interp, modes, config.target_frame
                )
                # Write back
                base_name = col_name.rsplit("_", 1)[0] if "_" in col_name else col_name
                suffixes = ["_x", "_y", "_z"]
                for i, suffix in enumerate(suffixes):
                    col = f"{base_name}{suffix}"
                    if col in merged.columns:
                        merged[col] = transformed[:, i]
            else:
                # Scalar, no transform needed
                pass

        return merged

    def _try_get_vector3(
        self, df: pd.DataFrame, col_name: str, specs: list[ChannelSpec]
    ) -> Optional[np.ndarray]:
        """Try to find x/y/z sibling columns for a 3D vector."""
        # Common patterns: accel_x/accel_y/accel_z, vx/vy/vz
        base_candidates = []
        for suffix in ["_x", "_y", "_z", "[0]", "[1]", "[2]"]:
            if col_name.endswith(suffix):
                base_candidates.append(col_name[: -len(suffix)])

        for base in base_candidates:
            for x_suf, y_suf, z_suf in [
                ("_x", "_y", "_z"),
                ("[0]", "[1]", "[2]"),
                ("_0", "_1", "_2"),
            ]:
                cx, cy, cz = f"{base}{x_suf}", f"{base}{y_suf}", f"{base}{z_suf}"
                if cx in df.columns and cy in df.columns and cz in df.columns:
                    return np.column_stack([df[cx].values, df[cy].values, df[cz].values])

        return None

    def _transform_vector3_batch(
        self,
        vec3: np.ndarray,
        quat: np.ndarray,
        modes: np.ndarray,
        target_frame: CoordFrame,
    ) -> np.ndarray:
        """Transform a batch of 3D vectors based on mode."""
        result = np.zeros_like(vec3)
        unique_modes = np.unique(modes)

        for mode in unique_modes:
            mask = modes == mode
            if not np.any(mask):
                continue
            vec_subset = vec3[mask]
            quat_subset = quat[mask]

            if target_frame == CoordFrame.THRUST_VERT:
                for i in range(len(vec_subset)):
                    result[mask][i] = self.ts_manager.transform_for_mode(
                        vec_subset[i], quat_subset[i], mode,
                        target_frame=CoordFrame.THRUST_VERT,
                    )
            elif target_frame == CoordFrame.NED:
                for i in range(len(vec_subset)):
                    result[mask][i] = self.transformer.frd_to_ned(vec_subset[i], quat_subset[i])
            elif target_frame == CoordFrame.ENU:
                for i in range(len(vec_subset)):
                    ned = self.transformer.frd_to_ned(vec_subset[i], quat_subset[i])
                    result[mask][i] = self.transformer.ned_to_enu(ned)

        return result

    def _get_mode_per_timestamp(
        self, timestamps: np.ndarray, segments: Optional[list[dict]]
    ) -> np.ndarray:
        """Map each timestamp to its flight mode classification."""
        modes = np.full(len(timestamps), "multirotor", dtype=object)
        if not segments:
            return modes

        for seg in segments:
            mask = (timestamps >= seg["t_start"]) & (timestamps <= seg["t_end"])
            modes[mask] = seg["classification"]

        return modes

    def _resample(
        self, df: pd.DataFrame, target_rate: float, method: ResampleMethod
    ) -> pd.DataFrame:
        """Resample DataFrame to uniform time base."""
        if df.empty:
            return df

        t_start = df.index[0]
        t_end = df.index[-1]
        n_samples = int((t_end - t_start) * target_rate) + 1
        new_index = np.linspace(t_start, t_end, n_samples)

        if method == ResampleMethod.INTERPOLATE:
            result = pd.DataFrame(index=new_index)
            for col in df.columns:
                result[col] = np.interp(new_index, df.index.values, df[col].values)
            return result
        elif method == ResampleMethod.NEAREST:
            return df.reindex(new_index, method="nearest")
        elif method == ResampleMethod.ZERO_ORDER_HOLD:
            return df.reindex(new_index, method="ffill")

        return df

    def _detrend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove linear trend from all channels."""
        result = df.copy()
        for col in result.columns:
            values = result[col].to_numpy().copy()
            if len(values) > 1 and not np.all(np.isnan(values)):
                valid = ~np.isnan(values)
                if np.sum(valid) > 1:
                    values[valid] = sp_signal.detrend(values[valid])
                    result[col] = values
        return result

    def _apply_lowpass(
        self, df: pd.DataFrame, cutoff_hz: float, sample_rate: float, order: int
    ) -> pd.DataFrame:
        """Apply Butterworth low-pass filter."""
        if sample_rate <= 0 or cutoff_hz <= 0 or cutoff_hz >= sample_rate / 2:
            return df

        nyquist = sample_rate / 2
        normalized_cutoff = cutoff_hz / nyquist
        if normalized_cutoff >= 1.0 or normalized_cutoff <= 0:
            return df

        b, a = sp_signal.butter(order, normalized_cutoff, btype="low")

        result = df.copy()
        for col in result.columns:
            values = result[col].to_numpy().copy()
            valid = ~np.isnan(values)
            if np.sum(valid) > order * 3:
                filtered = sp_signal.filtfilt(b, a, values[valid])
                values[valid] = filtered
                result[col] = values

        return result

    def _estimate_rate(self, df: pd.DataFrame) -> float:
        """Estimate the sampling rate from the data."""
        if len(df) < 2:
            return 0.0
        dt = np.diff(df.index.values)
        median_dt = np.median(dt[dt > 0])
        return 1.0 / median_dt if median_dt > 0 else 0.0


# Predefined channel sets for common analysis scenarios
BASIC_CHANNELS = [
    ChannelSpec("vehicle_attitude", "q[0]", "Att_Qw", category="state"),
    ChannelSpec("vehicle_attitude", "q[1]", "Att_Qx", category="state"),
    ChannelSpec("vehicle_attitude", "q[2]", "Att_Qy", category="state"),
    ChannelSpec("vehicle_attitude", "q[3]", "Att_Qz", category="state"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[0]", "SP_Qw", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[1]", "SP_Qx", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[2]", "SP_Qy", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[3]", "SP_Qz", category="control"),
    ChannelSpec("vehicle_local_position", "vx", "Vel_N", unit="m/s", category="state", coord_frame=CoordFrame.NED),
    ChannelSpec("vehicle_local_position", "vy", "Vel_E", unit="m/s", category="state", coord_frame=CoordFrame.NED),
    ChannelSpec("vehicle_local_position", "vz", "Vel_D", unit="m/s", category="state", coord_frame=CoordFrame.NED),
    ChannelSpec("sensor_accel", "x", "Accel_X", unit="m/s²", category="state"),
    ChannelSpec("sensor_accel", "y", "Accel_Y", unit="m/s²", category="state"),
    ChannelSpec("sensor_accel", "z", "Accel_Z", unit="m/s²", category="state"),
    ChannelSpec("sensor_gyro", "x", "Gyro_X", unit="rad/s", category="state"),
    ChannelSpec("sensor_gyro", "y", "Gyro_Y", unit="rad/s", category="state"),
    ChannelSpec("sensor_gyro", "z", "Gyro_Z", unit="rad/s", category="state"),
]

RATE_CONTROL_CHANNELS = [
    ChannelSpec("sensor_gyro", "x", "Gyro_Roll", unit="rad/s", category="state"),
    ChannelSpec("sensor_gyro", "y", "Gyro_Pitch", unit="rad/s", category="state"),
    ChannelSpec("sensor_gyro", "z", "Gyro_Yaw", unit="rad/s", category="state"),
    ChannelSpec("vehicle_rates_setpoint", "roll", "SP_RollRate", unit="rad/s", category="control"),
    ChannelSpec("vehicle_rates_setpoint", "pitch", "SP_PitchRate", unit="rad/s", category="control"),
    ChannelSpec("vehicle_rates_setpoint", "yaw", "SP_YawRate", unit="rad/s", category="control"),
    ChannelSpec("actuator_controls", "control[0]", "Ctrl_Roll", category="control"),
    ChannelSpec("actuator_controls", "control[1]", "Ctrl_Pitch", category="control"),
    ChannelSpec("actuator_controls", "control[2]", "Ctrl_Throttle", category="control"),
    ChannelSpec("actuator_controls", "control[3]", "Ctrl_Yaw", category="control"),
]

ATTITUDE_CHANNELS = [
    ChannelSpec("vehicle_attitude", "q[0]", "Att_Qw", category="state"),
    ChannelSpec("vehicle_attitude", "q[1]", "Att_Qx", category="state"),
    ChannelSpec("vehicle_attitude", "q[2]", "Att_Qy", category="state"),
    ChannelSpec("vehicle_attitude", "q[3]", "Att_Qz", category="state"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[0]", "SP_Qw", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[1]", "SP_Qx", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[2]", "SP_Qy", category="control"),
    ChannelSpec("vehicle_attitude_setpoint", "q_d[3]", "SP_Qz", category="control"),
]
