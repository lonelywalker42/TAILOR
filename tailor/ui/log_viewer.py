"""Log viewer widget with pyqtgraph time series plots and mode indicator."""

from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QComboBox,
    QLabel,
    QCheckBox,
    QDoubleSpinBox,
    QToolBar,
    QSizePolicy,
    QFrame,
    QScrollArea,
    QGroupBox,
    QGridLayout,
    QLineEdit,
)

from tailor.core.config import NavState
from tailor.parser.data_pipeline import (
    DataPipeline,
    PipelineConfig,
    PipelineResult,
    ChannelSpec,
    ResampleMethod,
    BASIC_CHANNELS,
    RATE_CONTROL_CHANNELS,
    ATTITUDE_CHANNELS,
)


# Color palette for flight modes
MODE_COLORS = {
    "multirotor": QColor(70, 130, 180, 80),    # Steel blue
    "fixedwing": QColor(60, 179, 113, 80),      # Medium sea green
    "transition": QColor(255, 165, 0, 80),       # Orange
    "unknown": QColor(128, 128, 128, 60),        # Gray
}

# Plot color cycle for channels
PLOT_COLORS = [
    (228, 26, 28),    # Red
    (55, 126, 184),   # Blue
    (77, 175, 74),    # Green
    (152, 78, 163),   # Purple
    (255, 127, 0),    # Orange
    (0, 126, 126),    # Teal
    (166, 86, 40),    # Brown
    (247, 129, 191),  # Pink
]


class StatisticsPanel(QWidget):
    """Panel displaying real-time statistics for the hovered time range."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._stats_data: dict[str, np.ndarray] = {}

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Title
        title = QLabel("统计信息")
        title.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(title)

        # Statistics display
        self.stats_label = QLabel("悬停在图表上查看统计")
        self.stats_label.setWordWrap(True)
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.stats_label)

        # Cursor position display
        self.cursor_label = QLabel("")
        self.cursor_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.cursor_label)

        layout.addStretch()

    def update_statistics(self, time_pos: float, data: dict[str, pd.DataFrame]):
        """Update statistics for the current cursor position."""
        if not data:
            return

        stats_text = []
        for name, df in data.items():
            if df.empty or "timestamp_s" not in df.columns:
                continue

            # Find nearest point
            time_arr = df["timestamp_s"].values
            idx = np.argmin(np.abs(time_arr - time_pos))
            nearest_time = time_arr[idx]

            # Get numeric columns
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            numeric_cols = [c for c in numeric_cols if c != "timestamp_s"]

            if not numeric_cols:
                continue

            stats_text.append(f"<b>{name}</b>")
            for col in numeric_cols[:5]:  # Limit to 5 columns per message
                val = df[col].iloc[idx]
                if isinstance(val, (int, float)):
                    stats_text.append(f"  {col}: {val:.3f}")

        if stats_text:
            self.stats_label.setText("<br>".join(stats_text))
            self.cursor_label.setText(f"时间: {time_pos:.3f}s")


class ModeIndicatorBar(QWidget):
    """Horizontal bar showing flight mode segments with color coding."""

    # Signal emitted when user clicks on a time position
    time_clicked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: list[dict] = []
        self._t_start: float = 0.0
        self._t_end: float = 0.0
        self._cursor_pos: float = -1.0
        self.setMinimumHeight(28)
        self.setMaximumHeight(28)
        self.setMouseTracking(True)

    def set_segments(self, segments: list[dict], t_start: float, t_end: float):
        """Set flight mode segments for display."""
        self._segments = segments
        self._t_start = t_start
        self._t_end = t_end
        self.update()

    def set_cursor_position(self, t: float):
        """Update the cursor position on the mode bar."""
        self._cursor_pos = t
        self.update()

    def mousePressEvent(self, event):
        """Handle mouse click to set time position."""
        if event.button() == Qt.MouseButton.LeftButton:
            w = self.width()
            total_duration = self._t_end - self._t_start
            if total_duration > 0 and w > 0:
                t = self._t_start + (event.position().x() / w) * total_duration
                self.time_clicked.emit(t)

    def paintEvent(self, event):
        """Draw the mode indicator bar."""
        from PySide6.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        total_duration = self._t_end - self._t_start

        if total_duration <= 0:
            painter.fillRect(0, 0, w, h, QColor(200, 200, 200))
            painter.end()
            return

        # Draw background
        painter.fillRect(0, 0, w, h, QColor(240, 240, 240))

        # Draw mode segments
        for seg in self._segments:
            x_start = int((seg["t_start"] - self._t_start) / total_duration * w)
            x_end = int((seg["t_end"] - self._t_start) / total_duration * w)
            x_start = max(0, min(x_start, w))
            x_end = max(0, min(x_end, w))

            classification = seg.get("classification", "unknown")
            color = MODE_COLORS.get(classification, MODE_COLORS["unknown"])
            painter.fillRect(x_start, 0, x_end - x_start, h, color)

            # Draw border
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            painter.drawLine(x_start, 0, x_start, h)

        # Draw labels
        painter.setPen(QColor(50, 50, 50))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for seg in self._segments:
            duration = seg["t_end"] - seg["t_start"]
            if duration < total_duration * 0.05:
                continue  # Skip very short segments for label clarity

            x_start = int((seg["t_start"] - self._t_start) / total_duration * w)
            x_end = int((seg["t_end"] - self._t_start) / total_duration * w)
            x_mid = (x_start + x_end) // 2

            label = seg.get("classification", "?")
            if label == "multirotor":
                label = "MR"
            elif label == "fixedwing":
                label = "FW"
            elif label == "transition":
                label = "Trans"

            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label)
            if tw < (x_end - x_start):
                painter.drawText(x_mid - tw // 2, h - 6, label)

        # Draw time axis ticks
        painter.setPen(QPen(QColor(80, 80, 80), 1))
        num_ticks = min(10, max(4, w // 100))
        for i in range(num_ticks + 1):
            t = self._t_start + (i / num_ticks) * total_duration
            x = int((t - self._t_start) / total_duration * w)
            painter.drawLine(x, h - 8, x, h)
            if i % 2 == 0:  # Label every other tick
                painter.drawText(x + 2, h - 10, f"{t:.1f}s")

        # Draw cursor position
        if self._cursor_pos >= self._t_start and self._cursor_pos <= self._t_end:
            x = int((self._cursor_pos - self._t_start) / total_duration * w)
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.drawLine(x, 0, x, h)

        painter.end()


class ChannelSelector(QWidget):
    """Tree widget for selecting data channels grouped by category."""

    channel_toggled = Signal(str, str, bool)  # message, field, enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channel_items: dict[str, QTreeWidgetItem] = {}
        self._all_channels: list[str] = []  # For search
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Search/filter box
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("输入关键词过滤通道...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_box)
        layout.addLayout(search_layout)

        # Preset selector with more options
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("预设:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("基础状态量", "basic")
        self.preset_combo.addItem("角速率控制", "rate_control")
        self.preset_combo.addItem("姿态跟踪", "attitude")
        self.preset_combo.addItem("位置控制", "position_control")
        self.preset_combo.addItem("传感器原始", "sensor_raw")
        self.preset_combo.addItem("执行器控制", "actuator")
        self.preset_combo.addItem("执行器输出", "actuator_output")
        self.preset_combo.addItem("自定义", "custom")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        layout.addLayout(preset_layout)

        # Quick action buttons
        action_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("全不选")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(self.deselect_all_btn)

        self.expand_all_btn = QPushButton("展开")
        self.expand_all_btn.clicked.connect(self._expand_all)
        action_layout.addWidget(self.expand_all_btn)

        self.collapse_all_btn = QPushButton("折叠")
        self.collapse_all_btn.clicked.connect(self._collapse_all)
        action_layout.addWidget(self.collapse_all_btn)

        layout.addLayout(action_layout)

        # Tree widget with improved display
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["通道", "类型", "单位"])
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, stretch=1)

        # Status label showing selection count
        self.status_label = QLabel("未选择通道")
        self.status_label.setStyleSheet("font-size: 10px; color: #666;")
        layout.addWidget(self.status_label)

    def populate_from_log(self, available_messages: list[str], message_fields: dict[str, list[str]]):
        """Populate the tree with available channels from a log file.

        Args:
            available_messages: List of message names present in the log.
            message_fields: Dict of message_name -> list of field names.
        """
        self.tree.clear()
        self._channel_items.clear()
        self._all_channels.clear()

        # Group by category with better organization
        categories = [
            ("处理通道 (Derived)", [m for m in available_messages if m.startswith("derived_")]),
            ("角速度 (Angular Rate)", ["vehicle_rates_setpoint", "sensor_gyro"]),
            ("姿态 (Attitude)", ["vehicle_attitude", "vehicle_attitude_setpoint"]),
            ("位置 (Position)", ["vehicle_local_position", "vehicle_local_position_setpoint", "vehicle_global_position"]),
            ("速度 (Velocity)", ["vehicle_local_position", "vehicle_local_position_setpoint"]),  # Overlaps with position
            ("传感器 (Sensor)", ["sensor_accel", "sensor_gyro", "sensor_mag", "airspeed"]),
            ("执行器 (Actuator)", ["actuator_outputs", "actuator_controls", "actuator_motors", "actuator_servos"]),
            ("状态 (Status)", ["vehicle_status", "manual_control_setpoint", "battery_status"]),
            ("其他 (Other)", []),
        ]

        # Track which messages have been assigned to avoid duplicates
        assigned = set()
        category_items = {}  # Store category items for later reference

        for cat_name, msg_list in categories:
            # Check if any messages in this category exist
            existing_msgs = [m for m in msg_list if m in available_messages and m not in assigned]
            if not existing_msgs and cat_name != "其他 (Other)":
                continue

            cat_item = QTreeWidgetItem(self.tree, [cat_name, "", ""])
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            cat_item.setCheckState(0, Qt.CheckState.Unchecked)
            cat_item.setExpanded(True)
            category_items[cat_name] = cat_item

            # Use a set to avoid duplicate messages in this category
            seen_in_cat = set()
            for msg_name in msg_list:
                if msg_name not in available_messages or msg_name in assigned or msg_name in seen_in_cat:
                    continue
                assigned.add(msg_name)
                seen_in_cat.add(msg_name)

                fields = message_fields.get(msg_name, [])
                # Determine message type for display
                msg_type = self._get_message_type(msg_name)
                msg_item = QTreeWidgetItem(cat_item, [msg_name, msg_type, ""])
                msg_item.setFlags(msg_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                msg_item.setCheckState(0, Qt.CheckState.Unchecked)

                for field_name in fields:
                    if field_name in ("timestamp", "timestamp_s", "instance"):
                        continue
                    ch_key = f"{msg_name}.{field_name}"
                    # Get field unit
                    unit = self._get_field_unit(msg_name, field_name)
                    field_item = QTreeWidgetItem(msg_item, [field_name, "", unit])
                    field_item.setCheckState(0, Qt.CheckState.Unchecked)
                    field_item.setFlags(field_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    self._channel_items[ch_key] = field_item
                    self._all_channels.append(ch_key)

        # Add unassigned messages to "Other"
        other_item = None
        for msg_name in available_messages:
            if msg_name not in assigned:
                if other_item is None:
                    other_item = QTreeWidgetItem(self.tree, ["其他 (Other)", "", ""])
                    other_item.setFlags(other_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                    other_item.setCheckState(0, Qt.CheckState.Unchecked)
                    other_item.setExpanded(False)  # Collapse by default
                    category_items["其他 (Other)"] = other_item

                fields = message_fields.get(msg_name, [])
                msg_type = self._get_message_type(msg_name)
                msg_item = QTreeWidgetItem(other_item, [msg_name, msg_type, ""])
                msg_item.setFlags(msg_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                msg_item.setCheckState(0, Qt.CheckState.Unchecked)

                for field_name in fields:
                    if field_name in ("timestamp", "timestamp_s", "instance"):
                        continue
                    ch_key = f"{msg_name}.{field_name}"
                    unit = self._get_field_unit(msg_name, field_name)
                    field_item = QTreeWidgetItem(msg_item, [field_name, "", unit])
                    field_item.setCheckState(0, Qt.CheckState.Unchecked)
                    field_item.setFlags(field_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    self._channel_items[ch_key] = field_item
                    self._all_channels.append(ch_key)

        # Update status
        self._update_status()

    def _get_message_type(self, msg_name: str) -> str:
        """Get a short type description for a message."""
        type_map = {
            "sensor_gyro": "陀螺仪",
            "sensor_accel": "加速度计",
            "sensor_mag": "磁力计",
            "airspeed": "空速",
            "vehicle_attitude": "姿态四元数",
            "vehicle_attitude_setpoint": "姿态指令",
            "vehicle_rates_setpoint": "角速率指令",
            "vehicle_local_position": "本地位置",
            "vehicle_local_position_setpoint": "位置指令",
            "vehicle_global_position": "全局位置",
            "actuator_outputs": "PWM输出",
            "actuator_controls": "控制量",
            "actuator_motors": "电机输出",
            "actuator_servos": "舵机输出",
            "vehicle_status": "飞行状态",
            "manual_control_setpoint": "遥控输入",
            "battery_status": "电池状态",
        }
        if msg_name.startswith("derived_"):
            if "motor" in msg_name:
                return "电机输出"
            if "servo" in msg_name:
                return "舵机输出"
            if "pwm" in msg_name:
                return "PWM输出"
            if "angular_velocity" in msg_name:
                return "滤波角速度"
            return "计算量"
        return type_map.get(msg_name, "")

    def _get_field_unit(self, msg_name: str, field_name: str) -> str:
        """Get the unit for a specific field."""
        # Common field units
        unit_map = {
            "timestamp_s": "s",
            "x": "m", "y": "m", "z": "m",
            "vx": "m/s", "vy": "m/s", "vz": "m/s",
            "roll": "rad", "pitch": "rad", "yaw": "rad",
            "roll_deg": "deg", "pitch_deg": "deg", "yaw_deg": "deg",
            "roll_rate_sp": "rad/s", "pitch_rate_sp": "rad/s", "yaw_rate_sp": "rad/s",
            "gyro_x": "rad/s", "gyro_y": "rad/s", "gyro_z": "rad/s",
            "av_x": "rad/s", "av_y": "rad/s", "av_z": "rad/s",
            "q[0]": "", "q[1]": "", "q[2]": "", "q[3]": "",
            "control[0]": "", "control[1]": "", "control[2]": "", "control[3]": "",
            "vx_sp": "m/s", "vy_sp": "m/s", "vz_sp": "m/s",
            "x_sp": "m", "y_sp": "m", "z_sp": "m",
            "roll_deg_sp": "deg", "pitch_deg_sp": "deg", "yaw_deg_sp": "deg",
            "roll_ctrl": "", "pitch_ctrl": "", "yaw_ctrl": "", "thrust_ctrl": "",
        }
        if field_name in unit_map:
            return unit_map[field_name]
        if field_name.startswith("motor_") or field_name.startswith("servo_"):
            return "[0,1]" if field_name.startswith("motor_") else "[-1,1]"
        if field_name.startswith("pwm_"):
            return "us"
        if "rate" in field_name or "gyro" in field_name:
            return "rad/s"
        if "deg" in field_name:
            return "deg"
        if "vel" in field_name or "speed" in field_name:
            return "m/s"
        if "pos" in field_name or field_name in ("x", "y", "z"):
            return "m"
        return ""

    def _on_search_changed(self, text: str):
        """Filter channels based on search text."""
        text = text.lower().strip()
        for ch_key, item in self._channel_items.items():
            if not text:
                # Show all if search is empty
                item.setHidden(False)
            else:
                # Show if channel key or parent message contains search text
                msg, field = ch_key.split(".", 1)
                visible = (text in ch_key.lower() or
                          text in msg.lower() or
                          text in field.lower())
                item.setHidden(not visible)

                # Also show parent items if they have visible children
                parent = item.parent()
                if parent and visible:
                    parent.setHidden(False)
                    parent.setExpanded(True)

    def _expand_all(self):
        """Expand all tree items."""
        self.tree.expandAll()

    def _collapse_all(self):
        """Collapse all tree items."""
        self.tree.collapseAll()

    def _update_status(self):
        """Update the status label with selection count."""
        selected_count = sum(
            1 for item in self._channel_items.values()
            if item.checkState(0) == Qt.CheckState.Checked
        )
        total_count = len(self._channel_items)
        if selected_count == 0:
            self.status_label.setText(f"未选择通道 (共 {total_count} 个可用)")
        else:
            self.status_label.setText(f"已选择 {selected_count}/{total_count} 个通道")

    def get_selected_channels(self) -> list[tuple[str, str]]:
        """Get list of (message_name, field_name) for checked channels."""
        selected = []
        for ch_key, item in self._channel_items.items():
            if item.checkState(0) == Qt.CheckState.Checked:
                msg, field = ch_key.split(".", 1)
                selected.append((msg, field))
        return selected

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Emit signal when a channel is toggled."""
        if column != 0:
            return
        # Find which channel this is
        for ch_key, ch_item in self._channel_items.items():
            if ch_item is item:
                msg, field = ch_key.split(".", 1)
                enabled = item.checkState(0) == Qt.CheckState.Checked
                self.channel_toggled.emit(msg, field, enabled)
                break
        # Update status
        self._update_status()

    def _on_preset_changed(self, index: int):
        """Apply a channel preset."""
        preset = self.preset_combo.currentData()
        self._deselect_all()

        if preset == "basic":
            targets = BASIC_CHANNELS
        elif preset == "rate_control":
            targets = RATE_CONTROL_CHANNELS
        elif preset == "attitude":
            targets = ATTITUDE_CHANNELS
        elif preset == "position_control":
            # Position control preset
            from tailor.parser.data_pipeline import ChannelSpec
            targets = [
                ChannelSpec("vehicle_local_position_setpoint", "x", "position_x_sp", "state"),
                ChannelSpec("vehicle_local_position_setpoint", "y", "position_y_sp", "state"),
                ChannelSpec("vehicle_local_position_setpoint", "z", "position_z_sp", "state"),
                ChannelSpec("vehicle_local_position", "x", "position_x", "state"),
                ChannelSpec("vehicle_local_position", "y", "position_y", "state"),
                ChannelSpec("vehicle_local_position", "z", "position_z", "state"),
                ChannelSpec("vehicle_local_position_setpoint", "vx", "velocity_x_sp", "state"),
                ChannelSpec("vehicle_local_position_setpoint", "vy", "velocity_y_sp", "state"),
                ChannelSpec("vehicle_local_position_setpoint", "vz", "velocity_z_sp", "state"),
                ChannelSpec("vehicle_local_position", "vx", "velocity_x", "state"),
                ChannelSpec("vehicle_local_position", "vy", "velocity_y", "state"),
                ChannelSpec("vehicle_local_position", "vz", "velocity_z", "state"),
            ]
        elif preset == "sensor_raw":
            # Raw sensor data preset
            from tailor.parser.data_pipeline import ChannelSpec
            targets = [
                ChannelSpec("sensor_gyro", "x", "gyro_x", "state"),
                ChannelSpec("sensor_gyro", "y", "gyro_y", "state"),
                ChannelSpec("sensor_gyro", "z", "gyro_z", "state"),
                ChannelSpec("sensor_accel", "x", "accel_x", "state"),
                ChannelSpec("sensor_accel", "y", "accel_y", "state"),
                ChannelSpec("sensor_accel", "z", "accel_z", "state"),
            ]
        elif preset == "actuator":
            # Actuator control preset
            from tailor.parser.data_pipeline import ChannelSpec
            targets = [
                ChannelSpec("actuator_controls", "control[0]", "roll_ctrl", "control"),
                ChannelSpec("actuator_controls", "control[1]", "pitch_ctrl", "control"),
                ChannelSpec("actuator_controls", "control[2]", "thrust_ctrl", "control"),
                ChannelSpec("actuator_controls", "control[3]", "yaw_ctrl", "control"),
            ]
        elif preset == "actuator_output":
            # Actuator output preset (derived channels)
            targets = []
            # Check for motor output channels
            for ch_key, item in self._channel_items.items():
                msg, field = ch_key.split(".", 1)
                if msg in ("derived_motor_output", "derived_servo_output", "derived_actuator_outputs_pwm"):
                    targets.append(type("Spec", (), {"message": msg, "field": field})())
        else:
            return

        for spec in targets:
            ch_key = f"{spec.message}.{spec.field}"
            if ch_key in self._channel_items:
                self._channel_items[ch_key].setCheckState(0, Qt.CheckState.Checked)

    def _select_all(self):
        """Select all visible channels."""
        for item in self._channel_items.values():
            if not item.isHidden():
                item.setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
        """Deselect all channels."""
        for item in self._channel_items.values():
            item.setCheckState(0, Qt.CheckState.Unchecked)


class LogViewerWidget(QWidget):
    """Full log viewer with pyqtgraph plots, mode indicator, and channel selector."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw_data: dict = {}
        self._flight_segments: list[dict] = []
        self._pipeline_result: Optional[PipelineResult] = None
        self._plot_items: list[pg.PlotItem] = []
        self._cursor_linked: bool = True
        self._auto_plot_on_load: bool = True
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter: left panel | plot area | right panel
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Channel selector
        self.channel_selector = ChannelSelector()
        self.channel_selector.setMinimumWidth(200)
        self.channel_selector.setMaximumWidth(320)
        main_splitter.addWidget(self.channel_selector)

        # Center: Plot area
        plot_area = QWidget()
        plot_layout = QVBoxLayout(plot_area)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(2)

        # Top toolbar area - use vertical layout to avoid overlap
        toolbar_frame = QFrame()
        toolbar_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        toolbar_main_layout = QVBoxLayout(toolbar_frame)
        toolbar_main_layout.setContentsMargins(4, 4, 4, 4)
        toolbar_main_layout.setSpacing(4)

        # Row 1: View and Processing controls
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(8)

        # View controls
        view_group = QGroupBox("视图")
        view_group.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        view_layout = QHBoxLayout(view_group)
        view_layout.setContentsMargins(6, 4, 6, 4)

        self.link_cursor_cb = QCheckBox("光标联动")
        self.link_cursor_cb.setChecked(True)
        self.link_cursor_cb.toggled.connect(self._toggle_cursor_link)
        view_layout.addWidget(self.link_cursor_cb)

        self.auto_plot_cb = QCheckBox("自动绘制")
        self.auto_plot_cb.setChecked(True)
        self.auto_plot_cb.toggled.connect(self._toggle_auto_plot)
        view_layout.addWidget(self.auto_plot_cb)

        view_layout.addWidget(QLabel("模式:"))
        self.plot_mode_combo = QComboBox()
        self.plot_mode_combo.addItem("重叠", "overlay")
        self.plot_mode_combo.addItem("分开", "separate")
        self.plot_mode_combo.addItem("按类别", "by_category")
        self.plot_mode_combo.setToolTip(
            "重叠: 所有通道在同一图表\n"
            "分开: 每个通道单独图表\n"
            "按类别: 同类重叠，不同类分开"
        )
        self.plot_mode_combo.setFixedWidth(70)
        view_layout.addWidget(self.plot_mode_combo)

        row1_layout.addWidget(view_group)

        # Processing controls
        proc_group = QGroupBox("处理")
        proc_group.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        proc_layout = QHBoxLayout(proc_group)
        proc_layout.setContentsMargins(6, 4, 6, 4)

        proc_layout.addWidget(QLabel("重采样:"))
        self.resample_spin = QDoubleSpinBox()
        self.resample_spin.setRange(0, 10000)
        self.resample_spin.setValue(0)
        self.resample_spin.setSpecialValueText("原始")
        self.resample_spin.setDecimals(1)
        self.resample_spin.setSuffix(" Hz")
        self.resample_spin.setFixedWidth(80)
        proc_layout.addWidget(self.resample_spin)

        proc_layout.addWidget(QLabel("坐标系:"))
        self.frame_combo = QComboBox()
        self.frame_combo.addItem("FRD", "frd")
        self.frame_combo.addItem("NED", "ned")
        self.frame_combo.addItem("ENU", "enu")
        self.frame_combo.addItem("推力垂向", "thrust_vertical")
        self.frame_combo.setFixedWidth(70)
        proc_layout.addWidget(self.frame_combo)

        row1_layout.addWidget(proc_group)

        # Action buttons
        action_group = QGroupBox("操作")
        action_group.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(6, 4, 6, 4)

        self.plot_btn = QPushButton("绘制")
        self.plot_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 4px 12px; }")
        self.plot_btn.clicked.connect(self._on_plot_clicked)
        action_layout.addWidget(self.plot_btn)

        self.clear_btn = QPushButton("清除")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        action_layout.addWidget(self.clear_btn)

        self.export_btn = QPushButton("导出")
        self.export_btn.clicked.connect(self._on_export_clicked)
        action_layout.addWidget(self.export_btn)

        row1_layout.addWidget(action_group)

        toolbar_main_layout.addLayout(row1_layout)

        # Row 2: Response analysis
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(8)

        response_group = QGroupBox("响应分析")
        response_group.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        response_layout = QHBoxLayout(response_group)
        response_layout.setContentsMargins(6, 4, 6, 4)

        response_layout.addWidget(QLabel("指令通道:"))
        self.cmd_combo = QComboBox()
        self.cmd_combo.setMinimumWidth(150)
        self.cmd_combo.setToolTip("选择指令通道 (setpoint)")
        response_layout.addWidget(self.cmd_combo)

        response_layout.addWidget(QLabel("响应通道:"))
        self.resp_combo = QComboBox()
        self.resp_combo.setMinimumWidth(150)
        self.resp_combo.setToolTip("选择响应通道 (state)")
        response_layout.addWidget(self.resp_combo)

        self.analyze_btn = QPushButton("分析")
        self.analyze_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 4px 16px; background-color: #4CAF50; color: white; }")
        self.analyze_btn.clicked.connect(self._on_analyze_response)
        self.analyze_btn.setToolTip("分析指令与响应的跟踪性能")
        response_layout.addWidget(self.analyze_btn)

        # Add stretch to push combo boxes to the left
        row2_layout.addWidget(response_group, stretch=1)

        toolbar_main_layout.addLayout(row2_layout)

        plot_layout.addWidget(toolbar_frame)

        # Mode indicator bar (now taller with time axis)
        self.mode_bar = ModeIndicatorBar()
        self.mode_bar.time_clicked.connect(self._on_mode_bar_clicked)
        plot_layout.addWidget(self.mode_bar)

        # pyqtgraph GraphicsLayoutWidget
        pg.setConfigOptions(antialias=True, background='w', foreground='k')
        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground('w')
        plot_layout.addWidget(self.plot_widget, stretch=1)

        # Bottom info bar
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        info_layout = QHBoxLayout(info_frame)
        info_layout.setContentsMargins(4, 2, 4, 2)

        self.info_label = QLabel('加载日志文件后，选择通道并点击"绘制"')
        self.info_label.setStyleSheet("font-size: 10px;")
        info_layout.addWidget(self.info_label)

        self.cursor_info_label = QLabel("")
        self.cursor_info_label.setStyleSheet("font-size: 10px; color: #666;")
        self.cursor_info_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        info_layout.addWidget(self.cursor_info_label)

        plot_layout.addWidget(info_frame)

        main_splitter.addWidget(plot_area)

        # Right: Statistics panel
        self.stats_panel = StatisticsPanel()
        self.stats_panel.setMinimumWidth(180)
        self.stats_panel.setMaximumWidth(250)
        main_splitter.addWidget(self.stats_panel)

        # Set splitter proportions
        main_splitter.setStretchFactor(0, 0)  # Channel selector - fixed
        main_splitter.setStretchFactor(1, 1)  # Plot area - stretch
        main_splitter.setStretchFactor(2, 0)  # Stats panel - fixed

        main_layout.addWidget(main_splitter)

    def _derive_processed_channels(self, raw_data: dict) -> tuple[dict, dict[str, list[str]]]:
        """Compute derived channels from raw data.

        Returns:
            (processed_data, processed_fields) where processed_data adds new
            message entries to raw_data and processed_fields maps those names
            to their column lists.
        """
        import math
        processed_data = {}
        processed_fields: dict[str, list[str]] = {}

        # 1. Attitude angles from quaternion (vehicle_attitude.q[0..3])
        att_df = raw_data.get("vehicle_attitude")
        if att_df is not None and not att_df.empty:
            q0 = att_df["q[0]"].values if "q[0]" in att_df.columns else None
            q1 = att_df["q[1]"].values if "q[1]" in att_df.columns else None
            q2 = att_df["q[2]"].values if "q[2]" in att_df.columns else None
            q3 = att_df["q[3]"].values if "q[3]" in att_df.columns else None
            if all(v is not None for v in [q0, q1, q2, q3]):
                roll = np.zeros(len(q0))
                pitch = np.zeros(len(q0))
                yaw = np.zeros(len(q0))
                for i in range(len(q0)):
                    # Roll (x-axis rotation)
                    sinr_cosp = 2.0 * (q0[i] * q1[i] + q2[i] * q3[i])
                    cosr_cosp = 1.0 - 2.0 * (q1[i] * q1[i] + q2[i] * q2[i])
                    roll[i] = math.atan2(sinr_cosp, cosr_cosp)
                    # Pitch (y-axis rotation)
                    sinp = 2.0 * (q0[i] * q2[i] - q3[i] * q1[i])
                    pitch[i] = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
                    # Yaw (z-axis rotation)
                    siny_cosp = 2.0 * (q0[i] * q3[i] + q1[i] * q2[i])
                    cosy_cosp = 1.0 - 2.0 * (q2[i] * q2[i] + q3[i] * q3[i])
                    yaw[i] = math.atan2(siny_cosp, cosy_cosp)

                deg = 180.0 / math.pi
                att_deg_df = pd.DataFrame({
                    "timestamp_s": att_df["timestamp_s"].values,
                    "roll_deg": roll * deg,
                    "pitch_deg": pitch * deg,
                    "yaw_deg": yaw * deg,
                })
                name = "derived_attitude_deg"
                processed_data[name] = att_deg_df
                processed_fields[name] = ["roll_deg", "pitch_deg", "yaw_deg"]

        # 2. Angular velocity from vehicle_rates_setpoint or sensor_gyro
        rates_df = raw_data.get("vehicle_rates_setpoint")
        if rates_df is not None and not rates_df.empty:
            cols = [c for c in ["roll", "pitch", "yaw"] if c in rates_df.columns]
            if cols:
                name = "derived_angular_rate_setpoint"
                sub = rates_df[["timestamp_s"] + cols].copy()
                sub.columns = ["timestamp_s"] + [f"{c}_rate_sp" for c in cols]
                processed_data[name] = sub
                processed_fields[name] = [f"{c}_rate_sp" for c in cols]

        gyro_df = raw_data.get("sensor_gyro")
        if gyro_df is not None and not gyro_df.empty:
            gyro_cols = [c for c in ["x", "y", "z"] if c in gyro_df.columns]
            if gyro_cols:
                name = "derived_gyro_rad_s"
                sub = gyro_df[["timestamp_s"] + gyro_cols].copy()
                sub.columns = ["timestamp_s"] + [f"gyro_{c}" for c in gyro_cols]
                processed_data[name] = sub
                processed_fields[name] = [f"gyro_{c}" for c in gyro_cols]

        # 3. Velocity from vehicle_local_position
        lpos_df = raw_data.get("vehicle_local_position")
        if lpos_df is not None and not lpos_df.empty:
            vel_cols = [c for c in ["vx", "vy", "vz"] if c in lpos_df.columns]
            if vel_cols:
                name = "derived_velocity_m_s"
                sub = lpos_df[["timestamp_s"] + vel_cols].copy()
                processed_data[name] = sub
                processed_fields[name] = vel_cols

        # 4. Position from vehicle_local_position
        if lpos_df is not None and not lpos_df.empty:
            pos_cols = [c for c in ["x", "y", "z"] if c in lpos_df.columns]
            if pos_cols:
                name = "derived_position_m"
                sub = lpos_df[["timestamp_s"] + pos_cols].copy()
                processed_data[name] = sub
                processed_fields[name] = pos_cols

        # 5. Attitude setpoint angles from quaternion (vehicle_attitude_setpoint.q_d[0..3])
        att_sp_df = raw_data.get("vehicle_attitude_setpoint")
        if att_sp_df is not None and not att_sp_df.empty:
            qd_cols = ["q_d[0]", "q_d[1]", "q_d[2]", "q_d[3]"]
            if all(c in att_sp_df.columns for c in qd_cols):
                q0 = att_sp_df["q_d[0]"].values
                q1 = att_sp_df["q_d[1]"].values
                q2 = att_sp_df["q_d[2]"].values
                q3 = att_sp_df["q_d[3]"].values
                roll_sp = np.zeros(len(q0))
                pitch_sp = np.zeros(len(q0))
                yaw_sp = np.zeros(len(q0))
                for i in range(len(q0)):
                    sinr_cosp = 2.0 * (q0[i] * q1[i] + q2[i] * q3[i])
                    cosr_cosp = 1.0 - 2.0 * (q1[i] * q1[i] + q2[i] * q2[i])
                    roll_sp[i] = math.atan2(sinr_cosp, cosr_cosp)
                    sinp = 2.0 * (q0[i] * q2[i] - q3[i] * q1[i])
                    pitch_sp[i] = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
                    siny_cosp = 2.0 * (q0[i] * q3[i] + q1[i] * q2[i])
                    cosy_cosp = 1.0 - 2.0 * (q2[i] * q2[i] + q3[i] * q3[i])
                    yaw_sp[i] = math.atan2(siny_cosp, cosy_cosp)
                deg = 180.0 / math.pi
                sp_df = pd.DataFrame({
                    "timestamp_s": att_sp_df["timestamp_s"].values,
                    "roll_deg_sp": roll_sp * deg,
                    "pitch_deg_sp": pitch_sp * deg,
                    "yaw_deg_sp": yaw_sp * deg,
                })
                name = "derived_attitude_setpoint_deg"
                processed_data[name] = sp_df
                processed_fields[name] = ["roll_deg_sp", "pitch_deg_sp", "yaw_deg_sp"]

        # 6. Actuator controls (roll/pitch/yaw/thrust)
        ac_df = raw_data.get("actuator_controls")
        if ac_df is not None and not ac_df.empty:
            ctrl_cols = [c for c in ["control[0]", "control[1]", "control[2]", "control[3]"] if c in ac_df.columns]
            if ctrl_cols:
                labels = {"control[0]": "roll_ctrl", "control[1]": "pitch_ctrl",
                          "control[2]": "thrust_ctrl", "control[3]": "yaw_ctrl"}
                sub = ac_df[["timestamp_s"] + ctrl_cols].copy()
                sub.columns = ["timestamp_s"] + [labels[c] for c in ctrl_cols]
                name = "derived_actuator_controls"
                processed_data[name] = sub
                processed_fields[name] = [labels[c] for c in ctrl_cols]

        # 7. Velocity setpoint from vehicle_local_position_setpoint
        lpos_sp_df = raw_data.get("vehicle_local_position_setpoint")
        if lpos_sp_df is not None and not lpos_sp_df.empty:
            vel_sp_cols = [c for c in ["vx", "vy", "vz"] if c in lpos_sp_df.columns]
            if vel_sp_cols:
                name = "derived_velocity_setpoint"
                sub = lpos_sp_df[["timestamp_s"] + vel_sp_cols].copy()
                sub.columns = ["timestamp_s"] + [f"{c}_sp" for c in vel_sp_cols]
                processed_data[name] = sub
                processed_fields[name] = [f"{c}_sp" for c in vel_sp_cols]
            pos_sp_cols = [c for c in ["x", "y", "z"] if c in lpos_sp_df.columns]
            if pos_sp_cols:
                name = "derived_position_setpoint"
                sub = lpos_sp_df[["timestamp_s"] + pos_sp_cols].copy()
                sub.columns = ["timestamp_s"] + [f"{c}_sp" for c in pos_sp_cols]
                processed_data[name] = sub
                processed_fields[name] = [f"{c}_sp" for c in pos_sp_cols]

        # 8. Motor output from actuator_motors (normalized [0,1])
        motors_df = raw_data.get("actuator_motors")
        if motors_df is not None and not motors_df.empty:
            motor_cols = sorted([c for c in motors_df.columns if c.startswith("control[")])
            if motor_cols:
                labels = {c: f"motor_{c.split('[')[1].split(']')[0]}" for c in motor_cols}
                sub = motors_df[["timestamp_s"] + motor_cols].copy()
                sub.columns = ["timestamp_s"] + [labels[c] for c in motor_cols]
                name = "derived_motor_output"
                processed_data[name] = sub
                processed_fields[name] = [labels[c] for c in motor_cols]

        # 9. Servo output from actuator_servos (normalized [-1,1])
        servos_df = raw_data.get("actuator_servos")
        if servos_df is not None and not servos_df.empty:
            servo_cols = sorted([c for c in servos_df.columns if c.startswith("control[")])
            if servo_cols:
                labels = {c: f"servo_{c.split('[')[1].split(']')[0]}" for c in servo_cols}
                sub = servos_df[["timestamp_s"] + servo_cols].copy()
                sub.columns = ["timestamp_s"] + [labels[c] for c in servo_cols]
                name = "derived_servo_output"
                processed_data[name] = sub
                processed_fields[name] = [labels[c] for c in servo_cols]

        # 10. Raw PWM output from actuator_outputs (microseconds)
        ao_df = raw_data.get("actuator_outputs")
        if ao_df is not None and not ao_df.empty:
            pwm_cols = sorted([c for c in ao_df.columns if c.startswith("output[")])
            if pwm_cols:
                labels = {c: f"pwm_{c.split('[')[1].split(']')[0]}" for c in pwm_cols}
                sub = ao_df[["timestamp_s"] + pwm_cols].copy()
                sub.columns = ["timestamp_s"] + [labels[c] for c in pwm_cols]
                name = "derived_actuator_outputs_pwm"
                processed_data[name] = sub
                processed_fields[name] = [labels[c] for c in pwm_cols]

        # 11. Vehicle angular velocity (filtered, used by rate controller)
        vav_df = raw_data.get("vehicle_angular_velocity")
        if vav_df is not None and not vav_df.empty:
            av_cols = [c for c in ["xyz[0]", "xyz[1]", "xyz[2]"] if c in vav_df.columns]
            if av_cols:
                labels = {"xyz[0]": "av_x", "xyz[1]": "av_y", "xyz[2]": "av_z"}
                sub = vav_df[["timestamp_s"] + av_cols].copy()
                sub.columns = ["timestamp_s"] + [labels[c] for c in av_cols]
                name = "derived_vehicle_angular_velocity"
                processed_data[name] = sub
                processed_fields[name] = [labels[c] for c in av_cols]

        return processed_data, processed_fields

    def load_data(
        self,
        raw_data: dict,
        available_messages: list[str],
        message_fields: dict[str, list[str]],
        flight_segments: Optional[list[dict]] = None,
    ):
        """Load parsed log data into the viewer.

        Args:
            raw_data: Dict of message_name -> DataFrame from UlogParser.
            available_messages: List of available message types.
            message_fields: Dict of message_name -> field names.
            flight_segments: Flight mode segments from parser.
        """
        self._raw_data = raw_data
        self._flight_segments = flight_segments or []

        # Derive processed channels
        processed_data, processed_fields = self._derive_processed_channels(raw_data)
        self._raw_data.update(processed_data)

        # Merge processed fields into message_fields for channel selector
        all_fields = dict(message_fields)
        all_fields.update(processed_fields)

        # Build available list including processed entries
        all_available = list(available_messages) + list(processed_fields.keys())

        # Populate channel selector
        self.channel_selector.populate_from_log(all_available, all_fields)

        # Auto-select derived channels in the channel selector
        for ch_key, item in self.channel_selector._channel_items.items():
            if ch_key.startswith("derived_"):
                item.setCheckState(0, Qt.CheckState.Checked)

        # Populate command and response combos for response analysis
        self._populate_response_combos()

        # Update mode bar
        if self._flight_segments:
            t_start = min(s["t_start"] for s in self._flight_segments)
            t_end = max(s["t_end"] for s in self._flight_segments)
            self.mode_bar.set_segments(self._flight_segments, t_start, t_end)

        # Info
        n_msgs = len(available_messages)
        n_processed = len(processed_fields)
        total_samples = sum(len(df) for df in self._raw_data.values())

        if not message_fields and not processed_fields:
            self.info_label.setText(
                f"已加载 {n_msgs} 种消息类型，但未能提取到可用的数据字段。"
                f"日志中可能不包含标准 PX4 uORB 消息。"
            )
        else:
            self.info_label.setText(
                f"已加载: {n_msgs} 种原始消息 + {n_processed} 种处理通道, "
                f"{total_samples:,} 条记录, "
                f"{len(self._flight_segments)} 个飞行模式段"
            )

        # Auto-plot derived channels if enabled
        if processed_fields and self._auto_plot_on_load:
            self._auto_plot_derived()

    def _populate_response_combos(self):
        """Populate command and response channel combos for response analysis."""
        self.cmd_combo.clear()
        self.resp_combo.clear()

        # Define channel categories for command and response
        cmd_channels = []  # Setpoint channels
        resp_channels = []  # State channels

        for name, df in self._raw_data.items():
            if hasattr(df, 'empty') and df.empty:
                continue
            if not hasattr(df, 'columns'):
                continue

            # Get numeric columns (excluding timestamp)
            numeric_cols = [c for c in df.columns if c not in ("timestamp_s", "timestamp", "instance")]
            if not numeric_cols:
                continue

            # Categorize based on message name
            if "setpoint" in name or "control" in name:
                # Command/setpoint channel
                for col in numeric_cols:
                    ch_key = f"{name}.{col}"
                    cmd_channels.append(ch_key)
            else:
                # State/measurement channel
                for col in numeric_cols:
                    ch_key = f"{name}.{col}"
                    resp_channels.append(ch_key)

        # Sort and add to combos
        cmd_channels.sort()
        resp_channels.sort()

        self.cmd_combo.addItems(cmd_channels)
        self.resp_combo.addItems(resp_channels)

        # Try to auto-select matching pairs
        self._auto_select_response_pair()

    def _auto_select_response_pair(self):
        """Auto-select matching command-response pair."""
        # Standard pairs to try
        AUTO_PAIRS = [
            ("derived_angular_rate_setpoint.roll_rate_sp", "derived_gyro_rad_s.gyro_x"),
            ("derived_angular_rate_setpoint.roll_rate_sp", "derived_vehicle_angular_velocity.av_x"),
            ("derived_angular_rate_setpoint.pitch_rate_sp", "derived_gyro_rad_s.gyro_y"),
            ("derived_angular_rate_setpoint.pitch_rate_sp", "derived_vehicle_angular_velocity.av_y"),
            ("derived_angular_rate_setpoint.yaw_rate_sp", "derived_gyro_rad_s.gyro_z"),
            ("derived_angular_rate_setpoint.yaw_rate_sp", "derived_vehicle_angular_velocity.av_z"),
            ("derived_attitude_setpoint_deg.roll_deg_sp", "derived_attitude_deg.roll_deg"),
            ("derived_attitude_setpoint_deg.pitch_deg_sp", "derived_attitude_deg.pitch_deg"),
            ("derived_velocity_setpoint.vx_sp", "derived_velocity_m_s.vx"),
            ("derived_position_setpoint.x_sp", "derived_position_m.x"),
        ]

        for cmd_ch, resp_ch in AUTO_PAIRS:
            cmd_idx = self.cmd_combo.findText(cmd_ch)
            resp_idx = self.resp_combo.findText(resp_ch)
            if cmd_idx >= 0 and resp_idx >= 0:
                self.cmd_combo.setCurrentIndex(cmd_idx)
                self.resp_combo.setCurrentIndex(resp_idx)
                break

    def _auto_plot_derived(self):
        """Auto-plot derived channels with setpoint vs estimated overlaid."""
        self.plot_widget.clear()
        self._plot_items.clear()

        # Axis colors: Roll=Red, Pitch=Green, Yaw=Blue
        AXIS_COLORS = {
            "roll": (228, 26, 28),
            "pitch": (77, 175, 74),
            "yaw": (55, 126, 184),
            "x": (228, 26, 28),
            "y": (77, 175, 74),
            "z": (55, 126, 184),
            "vx": (228, 26, 28),
            "vy": (77, 175, 74),
            "vz": (55, 126, 184),
            "thrust": (152, 78, 163),
        }

        def _downsample(time, values, max_pts=10000):
            if len(time) > max_pts:
                step = len(time) // max_pts
                return time[::step], values[::step]
            return time, values

        def _add_mode_overlay(plot_item):
            if not self._flight_segments:
                return
            for seg in self._flight_segments:
                classification = seg.get("classification", "unknown")
                color = MODE_COLORS.get(classification, MODE_COLORS["unknown"])
                region = pg.LinearRegionItem(
                    values=[seg["t_start"], seg["t_end"]],
                    brush=pg.mkBrush(color),
                    movable=False,
                )
                region.setZValue(-10)
                plot_item.addItem(region)

        group_idx = 0

        # --- Plot 1: Angular Rate (gyro solid + rate setpoint dashed) ---
        gyro_df = self._raw_data.get("derived_gyro_rad_s")
        rate_sp_df = self._raw_data.get("derived_angular_rate_setpoint")
        if gyro_df is not None and not gyro_df.empty:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="角速度 Angular Rate (rad/s)")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            # Measured gyro (solid lines)
            gyro_map = {"gyro_x": "Roll", "gyro_y": "Pitch", "gyro_z": "Yaw"}
            for field, label in gyro_map.items():
                if field in gyro_df.columns:
                    t, v = _downsample(gyro_df["timestamp_s"].values, gyro_df[field].values)
                    axis_key = label.lower()
                    color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                    pen = pg.mkPen(color=color, width=1.5)
                    plot_item.plot(t, v, pen=pen, name=f"{label} (实测)")

            # Rate setpoint (dashed lines, same colors)
            if rate_sp_df is not None and not rate_sp_df.empty:
                sp_map = {"roll_rate_sp": "Roll", "pitch_rate_sp": "Pitch", "yaw_rate_sp": "Yaw"}
                for field, label in sp_map.items():
                    if field in rate_sp_df.columns:
                        t, v = _downsample(rate_sp_df["timestamp_s"].values, rate_sp_df[field].values)
                        axis_key = label.lower()
                        color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                        pen = pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine)
                        plot_item.plot(t, v, pen=pen, name=f"{label} (指令)")

            _add_mode_overlay(plot_item)
            group_idx += 1

        # --- Plot 2: Attitude (estimated solid + setpoint dashed) ---
        att_df = self._raw_data.get("derived_attitude_deg")
        att_sp_df = self._raw_data.get("derived_attitude_setpoint_deg")
        if att_df is not None and not att_df.empty:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="姿态角 Attitude (deg)")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            att_map = {"roll_deg": "Roll", "pitch_deg": "Pitch", "yaw_deg": "Yaw"}
            for field, label in att_map.items():
                if field in att_df.columns:
                    t, v = _downsample(att_df["timestamp_s"].values, att_df[field].values)
                    axis_key = label.lower()
                    color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                    pen = pg.mkPen(color=color, width=1.5)
                    plot_item.plot(t, v, pen=pen, name=f"{label} (实测)")

            if att_sp_df is not None and not att_sp_df.empty:
                sp_map = {"roll_deg_sp": "Roll", "pitch_deg_sp": "Pitch", "yaw_deg_sp": "Yaw"}
                for field, label in sp_map.items():
                    if field in att_sp_df.columns:
                        t, v = _downsample(att_sp_df["timestamp_s"].values, att_sp_df[field].values)
                        axis_key = label.lower()
                        color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                        pen = pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine)
                        plot_item.plot(t, v, pen=pen, name=f"{label} (指令)")

            _add_mode_overlay(plot_item)
            if self._plot_items:
                plot_item.setXLink(self._plot_items[0])
            group_idx += 1

        # --- Plot 3: Velocity (estimated solid + setpoint dashed) ---
        vel_df = self._raw_data.get("derived_velocity_m_s")
        vel_sp_df = self._raw_data.get("derived_velocity_setpoint")
        if vel_df is not None and not vel_df.empty:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="速度 Velocity (m/s)")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            vel_map = {"vx": "Vx", "vy": "Vy", "vz": "Vz"}
            for field, label in vel_map.items():
                if field in vel_df.columns:
                    t, v = _downsample(vel_df["timestamp_s"].values, vel_df[field].values)
                    axis_key = field  # vx, vy, vz
                    color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                    pen = pg.mkPen(color=color, width=1.5)
                    plot_item.plot(t, v, pen=pen, name=f"{label} (实测)")

            if vel_sp_df is not None and not vel_sp_df.empty:
                sp_map = {"vx_sp": "Vx", "vy_sp": "Vy", "vz_sp": "Vz"}
                for field, label in sp_map.items():
                    if field in vel_sp_df.columns:
                        t, v = _downsample(vel_sp_df["timestamp_s"].values, vel_sp_df[field].values)
                        axis_key = field.replace("_sp", "")
                        color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                        pen = pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine)
                        plot_item.plot(t, v, pen=pen, name=f"{label} (指令)")

            _add_mode_overlay(plot_item)
            if self._plot_items:
                plot_item.setXLink(self._plot_items[0])
            group_idx += 1

        # --- Plot 4: Position (estimated solid + setpoint dashed) ---
        pos_df = self._raw_data.get("derived_position_m")
        pos_sp_df = self._raw_data.get("derived_position_setpoint")
        if pos_df is not None and not pos_df.empty:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="位置 Position (m)")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            pos_map = {"x": "X", "y": "Y", "z": "Z"}
            for field, label in pos_map.items():
                if field in pos_df.columns:
                    t, v = _downsample(pos_df["timestamp_s"].values, pos_df[field].values)
                    axis_key = field
                    color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                    pen = pg.mkPen(color=color, width=1.5)
                    plot_item.plot(t, v, pen=pen, name=f"{label} (实测)")

            if pos_sp_df is not None and not pos_sp_df.empty:
                sp_map = {"x_sp": "X", "y_sp": "Y", "z_sp": "Z"}
                for field, label in sp_map.items():
                    if field in pos_sp_df.columns:
                        t, v = _downsample(pos_sp_df["timestamp_s"].values, pos_sp_df[field].values)
                        axis_key = field.replace("_sp", "")
                        color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                        pen = pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine)
                        plot_item.plot(t, v, pen=pen, name=f"{label} (指令)")

            _add_mode_overlay(plot_item)
            if self._plot_items:
                plot_item.setXLink(self._plot_items[0])
            group_idx += 1

        # --- Plot 5: Actuator Controls ---
        ac_df = self._raw_data.get("derived_actuator_controls")
        if ac_df is not None and not ac_df.empty:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="执行器控制 Actuator Controls")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            ctrl_map = {"roll_ctrl": "Roll", "pitch_ctrl": "Pitch", "yaw_ctrl": "Yaw", "thrust_ctrl": "Thrust"}
            for field, label in ctrl_map.items():
                if field in ac_df.columns:
                    t, v = _downsample(ac_df["timestamp_s"].values, ac_df[field].values)
                    axis_key = label.lower()
                    color = AXIS_COLORS.get(axis_key, (100, 100, 100))
                    pen = pg.mkPen(color=color, width=1.5)
                    plot_item.plot(t, v, pen=pen, name=label)

            _add_mode_overlay(plot_item)
            if self._plot_items:
                plot_item.setXLink(self._plot_items[0])
            group_idx += 1

        # --- Plot 6: Actuator Outputs (Motor + Servo + PWM) ---
        motor_df = self._raw_data.get("derived_motor_output")
        servo_df = self._raw_data.get("derived_servo_output")
        pwm_df = self._raw_data.get("derived_actuator_outputs_pwm")
        has_actuator_output = (motor_df is not None and not motor_df.empty) or \
                              (servo_df is not None and not servo_df.empty) or \
                              (pwm_df is not None and not pwm_df.empty)
        if has_actuator_output:
            plot_item = self.plot_widget.addPlot(row=group_idx, col=0, title="执行器输出 Actuator Outputs")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            motor_colors = [(228, 26, 28), (55, 126, 184), (77, 175, 74), (152, 78, 163),
                            (255, 127, 0), (0, 126, 126), (166, 86, 40), (247, 129, 191)]

            # Motor outputs (solid lines)
            if motor_df is not None and not motor_df.empty:
                motor_fields = [c for c in motor_df.columns if c.startswith("motor_")]
                for i, field in enumerate(motor_fields):
                    ch_idx = i % len(motor_colors)
                    color = motor_colors[ch_idx]
                    pen = pg.mkPen(color=color, width=1.5)
                    t, v = _downsample(motor_df["timestamp_s"].values, motor_df[field].values)
                    plot_item.plot(t, v, pen=pen, name=f"Motor {field.split('_')[1]}")

            # Servo outputs (dashed lines)
            if servo_df is not None and not servo_df.empty:
                servo_fields = [c for c in servo_df.columns if c.startswith("servo_")]
                for i, field in enumerate(servo_fields):
                    ch_idx = i % len(motor_colors)
                    color = motor_colors[ch_idx]
                    pen = pg.mkPen(color=color, width=1.5, style=Qt.PenStyle.DashLine)
                    t, v = _downsample(servo_df["timestamp_s"].values, servo_df[field].values)
                    plot_item.plot(t, v, pen=pen, name=f"Servo {field.split('_')[1]}")

            # Raw PWM outputs (if no motor/servo data)
            if pwm_df is not None and not pwm_df.empty and motor_df is None and servo_df is None:
                pwm_fields = [c for c in pwm_df.columns if c.startswith("pwm_")]
                for i, field in enumerate(pwm_fields):
                    ch_idx = i % len(motor_colors)
                    color = motor_colors[ch_idx]
                    pen = pg.mkPen(color=color, width=1.5)
                    t, v = _downsample(pwm_df["timestamp_s"].values, pwm_df[field].values)
                    plot_item.plot(t, v, pen=pen, name=f"PWM {field.split('_')[1]} (us)")

            _add_mode_overlay(plot_item)
            if self._plot_items:
                plot_item.setXLink(self._plot_items[0])
            group_idx += 1

        # Add crosshair to all plots for synchronized cursor tracking
        if self._cursor_linked and self._plot_items:
            self._add_crosshair(self._plot_items[0])

        self.info_label.setText(
            f"已绘制 {group_idx} 组通道 (实线=实测, 虚线=指令) | "
            f"飞行模式: 蓝=多旋翼, 绿=固定翼, 橙=过渡"
        )

    def _on_plot_clicked(self):
        """Run pipeline and plot selected channels."""
        selected = self.channel_selector.get_selected_channels()
        if not selected:
            self.info_label.setText("请先选择至少一个数据通道")
            return

        # Build pipeline config
        channels = []
        for msg, field in selected:
            # Determine category from message name
            if "setpoint" in msg or "control" in msg:
                category = "control"
            elif "motor" in msg or "servo" in msg or "pwm" in msg or "actuator" in msg:
                category = "actuator"
            else:
                category = "state"
            # Shorter display name for derived channels
            if msg.startswith("derived_"):
                display_name = field  # e.g. "roll_deg", "vx"
            else:
                display_name = f"{msg}.{field}"
            channels.append(ChannelSpec(
                message=msg,
                field=field,
                display_name=display_name,
                category=category,
            ))

        target_frame_str = self.frame_combo.currentData()
        target_frame_map = {
            "frd": CoordFrame.FRD,
            "ned": CoordFrame.NED,
            "enu": CoordFrame.ENU,
            "thrust_vertical": CoordFrame.THRUST_VERT,
        }

        resample_rate = self.resample_spin.value()
        if resample_rate <= 0:
            resample_rate = None

        config = PipelineConfig(
            channels=channels,
            target_frame=target_frame_map.get(target_frame_str, CoordFrame.FRD),
            resample_rate=resample_rate,
        )

        # Get attitude data for coord transforms
        attitude_df = self._raw_data.get("vehicle_attitude")

        # Run pipeline
        pipeline = DataPipeline()
        self._pipeline_result = pipeline.run(
            self._raw_data, config,
            attitude_quat=attitude_df,
            flight_mode_segments=self._flight_segments,
        )

        # Plot
        self._plot_result(self._pipeline_result)

    def _plot_result(self, result: PipelineResult):
        """Plot pipeline result using pyqtgraph.

        Supports three plotting modes:
        - overlay: All channels on the same plot
        - separate: Each channel on its own plot
        - by_category: Group by category (state/control), channels in same group overlaid
        """
        self.plot_widget.clear()
        self._plot_items.clear()

        if result.data.empty:
            self.info_label.setText("无数据可绘制")
            return

        df = result.data
        n_channels = len(df.columns)

        if n_channels == 0:
            return

        time = df.index.values
        plot_mode = self.plot_mode_combo.currentData()

        # Helper function for downsampling
        def downsample(t, v, max_pts=10000):
            if len(t) > max_pts:
                step = len(t) // max_pts
                return t[::step], v[::step]
            return t, v

        if plot_mode == "overlay":
            # All channels on one plot
            plot_item = self.plot_widget.addPlot(row=0, col=0, title="所有通道")
            plot_item.setLabel("bottom", "时间", units="s")
            plot_item.showGrid(x=True, y=True, alpha=0.3)
            plot_item.addLegend(offset=(10, 10))
            self._plot_items.append(plot_item)

            for ch_idx, col in enumerate(df.columns):
                color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]
                pen = pg.mkPen(color=color, width=1.5)
                t_ds, v_ds = downsample(time, df[col].values)
                plot_item.plot(t_ds, v_ds, pen=pen, name=col)

            if self._cursor_linked:
                self._add_crosshair(plot_item)

        elif plot_mode == "separate":
            # Each channel on its own plot
            for ch_idx, col in enumerate(df.columns):
                color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]
                pen = pg.mkPen(color=color, width=1.5)

                plot_item = self.plot_widget.addPlot(row=ch_idx, col=0, title=col)
                plot_item.setLabel("bottom", "时间", units="s")
                plot_item.showGrid(x=True, y=True, alpha=0.3)
                self._plot_items.append(plot_item)

                t_ds, v_ds = downsample(time, df[col].values)
                plot_item.plot(t_ds, v_ds, pen=pen)

                # Link x-axis to first plot
                if ch_idx > 0 and self._plot_items:
                    plot_item.setXLink(self._plot_items[0])

                if self._cursor_linked:
                    self._add_crosshair(plot_item)

        else:  # by_category
            # Group channels by category for shared axes
            state_cols = [s.display_name for s in result.channel_specs if s.category == "state" and s.display_name in df.columns]
            control_cols = [s.display_name for s in result.channel_specs if s.category == "control" and s.display_name in df.columns]
            other_cols = [c for c in df.columns if c not in state_cols and c not in control_cols]

            plot_groups = []
            if state_cols:
                plot_groups.append(("状态量", state_cols))
            if control_cols:
                plot_groups.append(("控制量", control_cols))
            if other_cols:
                plot_groups.append(("其他", other_cols))

            for group_idx, (group_name, cols) in enumerate(plot_groups):
                plot_item = self.plot_widget.addPlot(
                    row=group_idx, col=0,
                    title=f"{group_name}",
                )
                plot_item.setLabel("bottom", "时间", units="s")
                plot_item.showGrid(x=True, y=True, alpha=0.3)
                plot_item.addLegend(offset=(10, 10))
                self._plot_items.append(plot_item)

                for ch_idx, col in enumerate(cols):
                    color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]
                    pen = pg.mkPen(color=color, width=1.5)
                    t_ds, v_ds = downsample(time, df[col].values)
                    plot_item.plot(t_ds, v_ds, pen=pen, name=col)

                # Link x-axis to first plot
                if group_idx > 0 and self._plot_items:
                    plot_item.setXLink(self._plot_items[0])

                if self._cursor_linked:
                    self._add_crosshair(plot_item)

        # Add mode indicator overlay on all plots
        if self._plot_items and self._flight_segments:
            for plot_item in self._plot_items:
                for seg in self._flight_segments:
                    classification = seg.get("classification", "unknown")
                    color = MODE_COLORS.get(classification, MODE_COLORS["unknown"])
                    region = pg.LinearRegionItem(
                        values=[seg["t_start"], seg["t_end"]],
                        brush=pg.mkBrush(color),
                        movable=False,
                    )
                    region.setZValue(-10)
                    plot_item.addItem(region)

        mode_names = {
            "overlay": "重叠绘图",
            "separate": "分开绘图",
            "by_category": "按类别分组"
        }
        mode_name = mode_names.get(plot_mode, plot_mode)
        self.info_label.setText(
            f"已绘制 {n_channels} 个通道 ({mode_name}), {len(time):,} 个数据点 | "
            f"坐标系: {result.metadata.get('target_frame', 'frd')}"
        )

    def _add_crosshair(self, plot_item: pg.PlotItem):
        """Add a crosshair line to a plot for cursor tracking."""
        # Vertical line
        v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('r', width=1, style=Qt.PenStyle.DashLine))
        plot_item.addItem(v_line, ignoreBounds=True)

        # Add crosshair lines to all other plots
        if self._cursor_linked:
            for pi in self._plot_items:
                if pi is not plot_item:
                    linked_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('r', width=1, style=Qt.PenStyle.DashLine))
                    pi.addItem(linked_line, ignoreBounds=True)

        # Connect mouse move
        def mouse_moved(pos):
            if plot_item.sceneBoundingRect().contains(pos):
                mouse_point = plot_item.getViewBox().mapSceneToView(pos)
                t_pos = mouse_point.x()
                v_line.setPos(t_pos)

                # Update all linked crosshair lines
                if self._cursor_linked:
                    for pi in self._plot_items:
                        if pi is not plot_item:
                            for item in pi.items:
                                if isinstance(item, pg.InfiniteLine):
                                    item.setPos(t_pos)

                # Update mode bar cursor
                self.mode_bar.set_cursor_position(t_pos)

                # Update cursor info label
                self.cursor_info_label.setText(f"时间: {t_pos:.3f}s")

                # Update statistics panel
                self.stats_panel.update_statistics(t_pos, self._raw_data)

        plot_item.scene().sigMouseMoved.connect(mouse_moved)

    def _toggle_cursor_link(self, checked: bool):
        self._cursor_linked = checked
        # Re-setup crosshairs when toggling
        if self._plot_items:
            self._add_crosshair(self._plot_items[0])

    def _toggle_auto_plot(self, checked: bool):
        self._auto_plot_on_load = checked

    def _on_mode_bar_clicked(self, t: float):
        """Handle click on mode indicator bar to scroll plots to that time."""
        if self._plot_items:
            # Set the X range of all plots to center on the clicked time
            for pi in self._plot_items:
                view_range = pi.viewRange()[0]
                current_duration = view_range[1] - view_range[0]
                new_start = t - current_duration / 2
                new_end = t + current_duration / 2
                pi.setXRange(new_start, new_end, padding=0)

    def _on_clear_clicked(self):
        """Clear all plots and reset the viewer."""
        self.plot_widget.clear()
        self._plot_items.clear()
        self.info_label.setText('已清除图表，选择通道后点击"绘制"')
        self.cursor_info_label.setText("")
        self.stats_panel.stats_label.setText("悬停在图表上查看统计")

    def _on_export_clicked(self):
        """Export current pipeline result."""
        if self._pipeline_result is None or self._pipeline_result.data.empty:
            self.info_label.setText("没有可导出的数据，请先绘制通道")
            return

        from PySide6.QtWidgets import QFileDialog
        from tailor.parser.export import DataExporter

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出数据", "",
            "CSV 文件 (*.csv);;MAT 文件 (*.mat);;Parquet 文件 (*.parquet)"
        )
        if not file_path:
            return

        exporter = DataExporter()
        try:
            out = exporter.export(self._pipeline_result, Path(file_path))
            self.info_label.setText(f"已导出: {out}")
        except Exception as e:
            self.info_label.setText(f"导出失败: {e}")

    def _find_setpoint_state_pairs(self) -> list[tuple[str, str, str]]:
        """Find matching setpoint and state channel pairs.

        Returns:
            List of (setpoint_channel, state_channel, axis_label) tuples.
        """
        pairs = []

        # Define standard setpoint-state pairs
        STANDARD_PAIRS = [
            # Angular rate
            ("derived_angular_rate_setpoint.roll_rate_sp", "derived_gyro_rad_s.gyro_x", "Roll 角速度"),
            ("derived_angular_rate_setpoint.pitch_rate_sp", "derived_gyro_rad_s.gyro_y", "Pitch 角速度"),
            ("derived_angular_rate_setpoint.yaw_rate_sp", "derived_gyro_rad_s.gyro_z", "Yaw 角速度"),
            # Angular rate (filtered)
            ("derived_angular_rate_setpoint.roll_rate_sp", "derived_vehicle_angular_velocity.av_x", "Roll 滤波角速度"),
            ("derived_angular_rate_setpoint.pitch_rate_sp", "derived_vehicle_angular_velocity.av_y", "Pitch 滤波角速度"),
            ("derived_angular_rate_setpoint.yaw_rate_sp", "derived_vehicle_angular_velocity.av_z", "Yaw 滤波角速度"),
            # Attitude
            ("derived_attitude_setpoint_deg.roll_deg_sp", "derived_attitude_deg.roll_deg", "Roll 姿态角"),
            ("derived_attitude_setpoint_deg.pitch_deg_sp", "derived_attitude_deg.pitch_deg", "Pitch 姿态角"),
            ("derived_attitude_setpoint_deg.yaw_deg_sp", "derived_attitude_deg.yaw_deg", "Yaw 姿态角"),
            # Velocity
            ("derived_velocity_setpoint.vx_sp", "derived_velocity_m_s.vx", "X 速度"),
            ("derived_velocity_setpoint.vy_sp", "derived_velocity_m_s.vy", "Y 速度"),
            ("derived_velocity_setpoint.vz_sp", "derived_velocity_m_s.vz", "Z 速度"),
            # Position
            ("derived_position_setpoint.x_sp", "derived_position_m.x", "X 位置"),
            ("derived_position_setpoint.y_sp", "derived_position_m.y", "Y 位置"),
            ("derived_position_setpoint.z_sp", "derived_position_m.z", "Z 位置"),
        ]

        # Check which pairs are available in the data
        for sp_ch, state_ch, label in STANDARD_PAIRS:
            if sp_ch in self._raw_data and state_ch in self._raw_data:
                sp_df = self._raw_data[sp_ch]
                state_df = self._raw_data[state_ch]
                if hasattr(sp_df, 'empty') and not sp_df.empty and hasattr(state_df, 'empty') and not state_df.empty:
                    pairs.append((sp_ch, state_ch, label))

        return pairs

    def _on_analyze_response(self):
        """Analyze response performance for selected command-response pair."""
        # Get selected channels from combos
        cmd_ch = self.cmd_combo.currentText()
        resp_ch = self.resp_combo.currentText()

        if not cmd_ch or not resp_ch:
            self.info_label.setText("请选择指令通道和响应通道")
            return

        # Check if channels exist in data
        # Channels are stored as "message.field" keys in _raw_data
        # But the combo stores them as "message.field" too
        # We need to find the actual DataFrame

        cmd_data = None
        resp_data = None

        # Search for the channel in raw_data
        for name, df in self._raw_data.items():
            if not hasattr(df, 'columns'):
                continue
            # Check if this is the message containing our field
            if cmd_ch.startswith(name + "."):
                field = cmd_ch.split(".", 1)[1]
                if field in df.columns:
                    cmd_data = df
                    cmd_field = field
                    break
            elif cmd_ch == name:
                # Single column message
                cmd_data = df
                cmd_field = None
                break

        for name, df in self._raw_data.items():
            if not hasattr(df, 'columns'):
                continue
            if resp_ch.startswith(name + "."):
                field = resp_ch.split(".", 1)[1]
                if field in df.columns:
                    resp_data = df
                    resp_field = field
                    break
            elif resp_ch == name:
                resp_data = df
                resp_field = None
                break

        if cmd_data is None or resp_data is None:
            self.info_label.setText(f"未找到通道数据: {cmd_ch} 或 {resp_ch}")
            return

        # Get time and values
        if "timestamp_s" in cmd_data.columns:
            t_cmd = cmd_data["timestamp_s"].values
            if cmd_field:
                cmd_values = cmd_data[cmd_field].values
            else:
                cmd_values = cmd_data.select_dtypes(include=[np.number]).values.flatten()
        else:
            self.info_label.setText("指令通道缺少时间戳")
            return

        if "timestamp_s" in resp_data.columns:
            t_resp = resp_data["timestamp_s"].values
            if resp_field:
                resp_values = resp_data[resp_field].values
            else:
                resp_values = resp_data.select_dtypes(include=[np.number]).values.flatten()
        else:
            self.info_label.setText("响应通道缺少时间戳")
            return

        # Align lengths
        n = min(len(cmd_values), len(resp_values))
        cmd_values = cmd_values[:n]
        resp_values = resp_values[:n]

        if n < 10:
            self.info_label.setText("数据点不足 (需要至少10个点)")
            return

        # Use response time as reference
        t = t_resp[:n]
        dt = np.mean(np.diff(t))

        # Clear plots and prepare for analysis
        self.plot_widget.clear()
        self._plot_items.clear()

        # Compute step response metrics
        metrics = self._compute_step_metrics(cmd_values, resp_values, t)

        # Compute frequency response metrics
        freq_metrics = self._compute_freq_metrics(cmd_values, resp_values, dt)

        # Create label from channel names
        label = f"{cmd_ch} → {resp_ch}"

        # Store result
        result = {
            "label": label,
            "cmd_ch": cmd_ch,
            "resp_ch": resp_ch,
            "metrics": metrics,
            "freq_metrics": freq_metrics,
        }

        # Plot step response
        plot_item = self.plot_widget.addPlot(row=0, col=0, title="响应分析")
        plot_item.setLabel("bottom", "时间", units="s")
        plot_item.setLabel("left", "幅值")
        plot_item.showGrid(x=True, y=True, alpha=0.3)
        plot_item.addLegend(offset=(10, 10))
        self._plot_items.append(plot_item)

        # Downsample for display
        max_pts = 5000
        if n > max_pts:
            step = n // max_pts
            t_ds = t[::step]
            cmd_ds = cmd_values[::step]
            resp_ds = resp_values[::step]
        else:
            t_ds = t
            cmd_ds = cmd_values
            resp_ds = resp_values

        # Plot command (setpoint)
        pen_cmd = pg.mkPen(color=(55, 126, 184), width=1.5)
        plot_item.plot(t_ds, cmd_ds, pen=pen_cmd, name="指令")

        # Plot response
        pen_resp = pg.mkPen(color=(228, 26, 28), width=1.5)
        plot_item.plot(t_ds, resp_ds, pen=pen_resp, name="响应")

        # Add reference lines for metrics
        if metrics.get("rise_time_s") is not None:
            # Add 10% and 90% threshold lines
            cmd_range = np.max(cmd_values) - np.min(cmd_values)
            cmd_mean = np.mean(cmd_values)
            pen_thresh = pg.mkPen(color=(150, 150, 150), width=1, style=Qt.PenStyle.DotLine)
            plot_item.addLine(y=cmd_mean + 0.1 * cmd_range, pen=pen_thresh)
            plot_item.addLine(y=cmd_mean + 0.9 * cmd_range, pen=pen_thresh)

        # Add error plot
        error_plot = self.plot_widget.addPlot(row=1, col=0, title="跟踪误差")
        error_plot.setLabel("bottom", "时间", units="s")
        error_plot.setLabel("left", "误差")
        error_plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot_items.append(error_plot)

        # Compute and plot error
        error = cmd_values - resp_values
        if n > max_pts:
            error_ds = error[::step]
        else:
            error_ds = error

        pen_err = pg.mkPen(color=(255, 127, 0), width=1)
        error_plot.plot(t_ds, error_ds, pen=pen_err, name="误差")

        # Add zero reference line
        pen_zero = pg.mkPen(color=(150, 150, 150), width=1, style=Qt.PenStyle.DotLine)
        error_plot.addLine(y=0, pen=pen_zero)

        # Link x-axis
        error_plot.setXLink(plot_item)

        # Update statistics panel with analysis results
        self._update_analysis_stats([result])

        self.info_label.setText(
            f"响应分析完成: {cmd_ch} → {resp_ch} | "
            f"查看右侧统计面板获取详细指标"
        )

    def _compute_step_metrics(self, sp: np.ndarray, state: np.ndarray, t: np.ndarray) -> dict:
        """Compute step response metrics treating setpoint vs state as equivalent step response.

        Analyzes: steady-state error, overshoot, settling time, oscillation characteristics.

        Args:
            sp: Setpoint values
            state: State values
            t: Time array

        Returns:
            Dictionary with step response metrics
        """
        metrics = {}
        n = len(state)
        if n < 10:
            return metrics

        # --- Identify step transition ---
        # Find the dominant step change in setpoint
        sp_diff = np.diff(sp)
        sp_range = np.max(sp) - np.min(sp)

        if sp_range < 1e-10:
            # No significant step change; use mean as reference
            sp_final = np.mean(sp)
            sp_initial = sp_final
            step_idx = 0
        else:
            # Find the largest step change
            step_idx = np.argmax(np.abs(sp_diff))
            # Use median before and after step as initial/final
            half = n // 2
            if step_idx < half:
                sp_initial = np.median(sp[:step_idx + 1]) if step_idx > 0 else sp[0]
                sp_final = np.median(sp[step_idx + 1:])
            else:
                sp_initial = np.median(sp[:half])
                sp_final = np.median(sp[half:])

        step_size = abs(sp_final - sp_initial)

        # --- Error signal ---
        error = state - sp
        ss_start = int(n * 0.8)
        ss_error_value = np.mean(error[ss_start:])
        metrics["ss_error"] = abs(ss_error_value)
        metrics["ss_error_signed"] = ss_error_value

        # --- RMSE ---
        metrics["rmse"] = float(np.sqrt(np.mean(error ** 2)))

        # If step size is negligible, return basic metrics
        if step_size < 1e-10:
            metrics["overshoot_pct"] = 0.0
            metrics["rise_time_s"] = None
            metrics["settling_time_s"] = None
            metrics["osc_count"] = 0
            metrics["damping_ratio"] = None
            metrics["osc_freq_hz"] = None
            return metrics

        # --- Overshoot ---
        # Overshoot = (peak - final) / step_size * 100 for positive step
        #             (final - trough) / step_size * 100 for negative step
        step_sign = 1.0 if sp_final >= sp_initial else -1.0
        deviation = (state - sp_final) * step_sign

        # Only consider deviations after the step transition
        post_step = deviation[step_idx:] if step_idx < n - 1 else deviation
        max_positive_dev = np.max(post_step)
        max_negative_dev = np.min(post_step)

        if max_positive_dev > 0:
            overshoot_pct = (max_positive_dev / step_size) * 100
        elif max_negative_dev < 0:
            # Undershoot case
            overshoot_pct = 0.0
            metrics["undershoot_pct"] = (abs(max_negative_dev) / step_size) * 100
        else:
            overshoot_pct = 0.0

        metrics["overshoot_pct"] = float(overshoot_pct)

        # --- Rise time (10% to 90% of step) ---
        thresh_10 = sp_initial + 0.1 * (sp_final - sp_initial)
        thresh_90 = sp_initial + 0.9 * (sp_final - sp_initial)

        if sp_final > sp_initial:
            idx_10 = np.where(state >= thresh_10)[0]
            idx_90 = np.where(state >= thresh_90)[0]
        else:
            idx_10 = np.where(state <= thresh_10)[0]
            idx_90 = np.where(state <= thresh_90)[0]

        if len(idx_10) > 0 and len(idx_90) > 0:
            i10 = idx_10[0]
            i90 = idx_90[0]
            if i90 > i10:
                metrics["rise_time_s"] = float(t[i90] - t[i10])
            else:
                metrics["rise_time_s"] = None
        else:
            metrics["rise_time_s"] = None

        # --- Settling time (last time error exceeds ±2% of step size) ---
        band = 0.02 * step_size
        # Search backwards from the end
        settling_idx = None
        for i in range(n - 1, step_idx, -1):
            if abs(state[i] - sp_final) > band:
                settling_idx = i
                break

        if settling_idx is not None and settling_idx < n - 1:
            metrics["settling_time_s"] = float(t[settling_idx] - t[step_idx])
        else:
            # Settled from the start or no step detected
            metrics["settling_time_s"] = 0.0

        # --- Oscillation characteristics ---
        # Use error signal after step transition for oscillation analysis
        if step_idx < n - 20:
            err_post = error[step_idx:]
            t_post = t[step_idx:] - t[step_idx]

            # Count zero crossings of error (oscillation count)
            err_sign = np.sign(err_post - np.mean(err_post[ss_start - step_idx:]))
            crossings = np.where(np.diff(err_sign) != 0)[0]
            osc_count = len(crossings) // 2  # Each oscillation = 2 crossings
            metrics["osc_count"] = int(osc_count)

            # Oscillation frequency from zero crossings
            if len(crossings) >= 2:
                avg_period = 2 * (t_post[crossings[-1]] - t_post[crossings[0]]) / len(crossings)
                if avg_period > 0:
                    metrics["osc_freq_hz"] = float(1.0 / avg_period)
                else:
                    metrics["osc_freq_hz"] = None
            else:
                metrics["osc_freq_hz"] = None

            # Damping ratio estimation from peak envelope decay
            # Find peaks in the error signal after step
            from scipy.signal import find_peaks
            peaks_pos, _ = find_peaks(err_post, height=band * 0.5)
            peaks_neg, _ = find_peaks(-err_post, height=band * 0.5)

            if len(peaks_pos) >= 2:
                # Logarithmic decrement from positive peaks
                peak_vals = err_post[peaks_pos]
                peak_vals = np.abs(peak_vals)
                peak_vals = peak_vals[peak_vals > band * 0.1]  # Filter noise
                if len(peak_vals) >= 2:
                    # delta = ln(A1/A2) for successive peaks
                    deltas = np.log(peak_vals[:-1] / (peak_vals[1:] + 1e-10))
                    delta = np.mean(deltas[deltas > 0])
                    if delta > 0 and np.isfinite(delta):
                        # zeta = delta / sqrt(4*pi^2 + delta^2)
                        damping = delta / np.sqrt(4 * np.pi ** 2 + delta ** 2)
                        metrics["damping_ratio"] = float(np.clip(damping, 0, 1))
                    else:
                        metrics["damping_ratio"] = None
                else:
                    metrics["damping_ratio"] = None
            elif len(peaks_neg) >= 2:
                peak_vals = np.abs(err_post[peaks_neg])
                peak_vals = peak_vals[peak_vals > band * 0.1]
                if len(peak_vals) >= 2:
                    deltas = np.log(peak_vals[:-1] / (peak_vals[1:] + 1e-10))
                    delta = np.mean(deltas[deltas > 0])
                    if delta > 0 and np.isfinite(delta):
                        damping = delta / np.sqrt(4 * np.pi ** 2 + delta ** 2)
                        metrics["damping_ratio"] = float(np.clip(damping, 0, 1))
                    else:
                        metrics["damping_ratio"] = None
                else:
                    metrics["damping_ratio"] = None
            else:
                metrics["damping_ratio"] = None
        else:
            metrics["osc_count"] = 0
            metrics["osc_freq_hz"] = None
            metrics["damping_ratio"] = None

        return metrics

    def _compute_freq_metrics(self, sp: np.ndarray, state: np.ndarray, dt: float) -> dict:
        """Compute frequency response metrics.

        Args:
            sp: Setpoint values
            state: State values
            dt: Sample time

        Returns:
            Dictionary with frequency response metrics
        """
        from scipy import signal

        metrics = {}

        try:
            # Compute transfer function using cross-spectral density
            fs = 1.0 / dt

            # Compute cross-spectral density
            f, Pxy = signal.csd(sp, state, fs=fs, nperseg=min(256, len(sp) // 4))
            f, Pxx = signal.welch(sp, fs=fs, nperseg=min(256, len(sp) // 4))

            # Compute frequency response (H = Pxy / Pxx)
            H = Pxy / (Pxx + 1e-10)  # Add small value to avoid division by zero

            # Compute magnitude and phase
            mag = np.abs(H)
            phase = np.angle(H, deg=True)

            # Find bandwidth (-3dB point)
            mag_db = 20 * np.log10(mag + 1e-10)
            dc_gain_db = mag_db[0]

            # Find -3dB point
            bandwidth_hz = None
            for i in range(len(mag_db)):
                if mag_db[i] < dc_gain_db - 3:
                    if i > 0:
                        # Interpolate
                        f1, f2 = f[i-1], f[i]
                        m1, m2 = mag_db[i-1], mag_db[i]
                        bandwidth_hz = f1 + (f2 - f1) * (dc_gain_db - 3 - m1) / (m2 - m1)
                    else:
                        bandwidth_hz = f[i]
                    break

            metrics["bandwidth_hz"] = bandwidth_hz

            # Compute phase margin (at bandwidth frequency)
            if bandwidth_hz is not None:
                # Find phase at bandwidth
                idx_bw = np.argmin(np.abs(f - bandwidth_hz))
                phase_at_bw = phase[idx_bw]
                metrics["phase_margin_deg"] = 180 + phase_at_bw
            else:
                metrics["phase_margin_deg"] = None

            # Compute DC gain
            metrics["dc_gain"] = mag[0]

            # Compute resonance peak
            peak_idx = np.argmax(mag)
            metrics["resonance_peak_db"] = 20 * np.log10(mag[peak_idx] + 1e-10)
            metrics["resonance_freq_hz"] = f[peak_idx]

        except Exception as e:
            metrics["error"] = str(e)

        return metrics

    def _update_analysis_stats(self, results: list[dict]):
        """Update statistics panel with analysis results."""
        if not results:
            return

        stats_text = ["<b>=== 响应分析结果 ===</b>"]

        for result in results:
            label = result["label"]
            metrics = result["metrics"]
            freq_metrics = result["freq_metrics"]

            stats_text.append(f"<br><b>{label}</b>")

            # Step response metrics
            stats_text.append("<b>时域指标:</b>")

            if metrics.get("rise_time_s") is not None:
                stats_text.append(f"  上升时间: {metrics['rise_time_s']:.3f}s")
            else:
                stats_text.append(f"  上升时间: N/A")

            if metrics.get("overshoot_pct") is not None:
                val = metrics["overshoot_pct"]
                status = " [!]" if val > 10 else ""
                stats_text.append(f"  超调量: {val:.1f}%{status}")

            if metrics.get("undershoot_pct") is not None:
                stats_text.append(f"  下冲量: {metrics['undershoot_pct']:.1f}%")

            if metrics.get("settling_time_s") is not None:
                stats_text.append(f"  调节时间: {metrics['settling_time_s']:.3f}s")

            if metrics.get("ss_error") is not None:
                val = metrics["ss_error"]
                status = " [!]" if val > 0.05 else ""
                stats_text.append(f"  稳态误差: {val:.4f}{status}")

            stats_text.append(f"  RMSE: {metrics.get('rmse', 0):.4f}")

            # Oscillation characteristics
            stats_text.append("<b>振荡特性:</b>")
            osc_count = metrics.get("osc_count", 0)
            stats_text.append(f"  振荡次数: {osc_count}")

            if metrics.get("damping_ratio") is not None:
                zeta = metrics["damping_ratio"]
                if zeta < 0.4:
                    desc = "欠阻尼(振荡)"
                elif zeta < 0.8:
                    desc = "欠阻尼(良好)"
                elif zeta < 1.0:
                    desc = "欠阻尼(临界)"
                else:
                    desc = "过阻尼"
                stats_text.append(f"  阻尼比: {zeta:.3f} ({desc})")
            else:
                stats_text.append(f"  阻尼比: N/A")

            if metrics.get("osc_freq_hz") is not None:
                stats_text.append(f"  振荡频率: {metrics['osc_freq_hz']:.2f}Hz")

            # Frequency response metrics
            stats_text.append("<b>频域指标:</b>")
            if freq_metrics.get("bandwidth_hz") is not None:
                stats_text.append(f"  带宽: {freq_metrics['bandwidth_hz']:.2f}Hz")
            else:
                stats_text.append(f"  带宽: N/A")

            if freq_metrics.get("phase_margin_deg") is not None:
                pm = freq_metrics["phase_margin_deg"]
                status = " [!]" if pm < 30 else ""
                stats_text.append(f"  相位裕度: {pm:.1f}deg{status}")

            if freq_metrics.get("resonance_peak_db") is not None:
                stats_text.append(f"  谐振峰值: {freq_metrics['resonance_peak_db']:.1f}dB")

            if freq_metrics.get("dc_gain") is not None:
                stats_text.append(f"  直流增益: {freq_metrics['dc_gain']:.3f}")

        self.stats_panel.stats_label.setText("<br>".join(stats_text))

    def clear(self):
        """Clear all plots and data."""
        self.plot_widget.clear()
        self._plot_items.clear()
        self._raw_data.clear()
        self._flight_segments.clear()
        self._pipeline_result = None
        self.channel_selector.tree.clear()
        self.info_label.setText("就绪")


# Need to import Path at module level for export
from pathlib import Path
from tailor.parser.coordinate import CoordFrame
