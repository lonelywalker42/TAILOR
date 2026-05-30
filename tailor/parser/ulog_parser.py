"""PX4 uLog parser built on pyulog."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from pyulog import ULog
    from pyulog.px4 import PX4ULog
except ImportError:
    ULog = None
    PX4ULog = None

from tailor.core.config import CORE_UORB_MESSAGES, NavState


class UlogParser:
    """Parse PX4 .ulg files and extract structured data."""

    def __init__(self, file_path: Path):
        if ULog is None:
            raise ImportError("pyulog is required: pip install pyulog")
        self.file_path = Path(file_path)
        self._ulog: Optional[ULog] = None
        self._px4_ulog: Optional[PX4ULog] = None

    def open(self):
        """Open and parse the .ulg file."""
        self._ulog = ULog(str(self.file_path))
        try:
            self._px4_ulog = PX4ULog(self._ulog)
        except Exception:
            self._px4_ulog = None

    @property
    def ulog(self) -> ULog:
        if self._ulog is None:
            self.open()
        return self._ulog

    @property
    def px4_ulog(self):
        if self._ulog is None:
            self.open()
        return self._px4_ulog

    def get_metadata(self) -> dict:
        """Extract basic metadata from the log."""
        ulog = self.ulog
        start_time = datetime.fromtimestamp(ulog.start_timestamp / 1e6, tz=timezone.utc)
        duration_s = (ulog.last_timestamp - ulog.start_timestamp) / 1e6

        # Count total messages
        msg_count = sum(m.size for m in ulog.data_list)

        # Drop count
        drop_count = ulog.drop_count if hasattr(ulog, 'drop_count') else 0

        meta = {
            "firmware_version": ulog.get_info("ver_sw", ""),
            "firmware_version_full": ulog.get_info("ver_sw_release", ""),
            "airframe_type": ulog.get_info("sys_autostart", ""),
            "airframe_name": ulog.get_info("sys_autostart", ""),
            "hardware": ulog.get_info("ver_hw", ""),
            "uuid": ulog.get_info("mav_sys_id", ""),
            "duration_s": duration_s,
            "start_time": start_time,
            "end_time": datetime.fromtimestamp(ulog.last_timestamp / 1e6, tz=timezone.utc),
            "start_timestamp_us": ulog.start_timestamp,
            "end_timestamp_us": ulog.last_timestamp,
            "message_count": msg_count,
            "drop_count": drop_count,
            "drop_rate": drop_count / max(msg_count, 1),
            "message_types": [m.name for m in ulog.data_list],
        }
        return meta

    def get_available_messages(self) -> list[str]:
        """Return list of message type names present in the log."""
        return list(set(m.name for m in self.ulog.data_list))

    def get_message_data(self, message_name: str) -> pd.DataFrame:
        """Extract a single message type as a DataFrame.

        Returns DataFrame with columns for each field and a 'timestamp' column in seconds.
        """
        ulog = self.ulog
        datasets = [d for d in ulog.data_list if d.name == message_name]
        if not datasets:
            raise KeyError(f"Message '{message_name}' not found in log")

        frames = []
        for dataset in datasets:
            data = dataset.data
            # Convert timestamp to seconds relative to start
            if "timestamp" in data:
                t_sec = (data["timestamp"] - ulog.start_timestamp) / 1e6
                df = pd.DataFrame(data)
                df["timestamp_s"] = t_sec
                frames.append(df)

        if not frames:
            return pd.DataFrame()

        # Handle multiple instances (e.g., sensor_accel_0, sensor_accel_1)
        if len(frames) == 1:
            return frames[0]

        # For multiple instances, add instance column and concatenate
        for i, df in enumerate(frames):
            df["instance"] = i
        return pd.concat(frames, ignore_index=True)

    def get_core_data(self) -> dict[str, pd.DataFrame]:
        """Extract all core uORB messages as DataFrames keyed by message name."""
        data = {}
        for msg_name in CORE_UORB_MESSAGES:
            try:
                df = self.get_message_data(msg_name)
                if not df.empty:
                    data[msg_name] = df
            except KeyError:
                continue
        return data

    def get_flight_mode_segments(self) -> list[dict]:
        """Extract flight mode segments from vehicle_status.

        Returns list of dicts: [{nav_state, label, t_start, t_end, duration}, ...]
        """
        try:
            df = self.get_message_data("vehicle_status")
        except KeyError:
            return []

        if df.empty or "nav_state" not in df.columns:
            return []

        segments = []
        t = df["timestamp_s"].values
        nav_states = df["nav_state"].values

        # Find segment boundaries
        change_idx = np.where(np.diff(nav_states) != 0)[0]
        boundaries = np.concatenate([[0], change_idx + 1, [len(nav_states)]])

        for i in range(len(boundaries) - 1):
            idx_start = boundaries[i]
            idx_end = boundaries[i + 1] - 1
            ns = int(nav_states[idx_start])
            segments.append({
                "nav_state": ns,
                "classification": NavState.classify(ns),
                "t_start": float(t[idx_start]),
                "t_end": float(t[idx_end]),
                "duration": float(t[idx_end] - t[idx_start]),
            })

        return segments

    def get_actuator_data(self) -> pd.DataFrame:
        """Merge actuator outputs with controls for a unified actuator DataFrame."""
        frames = {}

        for msg in ["actuator_outputs", "actuator_controls", "actuator_motors", "actuator_servos"]:
            try:
                df = self.get_message_data(msg)
                if not df.empty:
                    frames[msg] = df
            except KeyError:
                continue

        return frames  # Return as dict since they have different structures

    def get_sensor_data(self) -> dict[str, pd.DataFrame]:
        """Get raw sensor data (accel, gyro, mag)."""
        sensors = {}
        for msg in ["sensor_accel", "sensor_gyro", "sensor_mag"]:
            try:
                df = self.get_message_data(msg)
                if not df.empty:
                    sensors[msg] = df
            except KeyError:
                continue
        return sensors

    def get_attitude_data(self) -> dict[str, pd.DataFrame]:
        """Get attitude-related data."""
        att = {}
        for msg in ["vehicle_attitude", "vehicle_attitude_setpoint", "vehicle_rates_setpoint"]:
            try:
                df = self.get_message_data(msg)
                if not df.empty:
                    att[msg] = df
            except KeyError:
                continue
        return att

    def get_position_data(self) -> dict[str, pd.DataFrame]:
        """Get position-related data."""
        pos = {}
        for msg in ["vehicle_local_position", "vehicle_global_position", "vehicle_local_position_setpoint"]:
            try:
                df = self.get_message_data(msg)
                if not df.empty:
                    pos[msg] = df
            except KeyError:
                continue
        return pos

    def get_parameter_changes(self) -> pd.DataFrame:
        """Extract parameter changes during the flight."""
        try:
            return self.get_message_data("parameter_update")
        except KeyError:
            return pd.DataFrame()


def extract_metadata_quick(file_path: Path) -> dict:
    """Quick metadata extraction for import preview without full parsing."""
    try:
        parser = UlogParser(file_path)
        return parser.get_metadata()
    except Exception as e:
        return {"error": str(e)}
