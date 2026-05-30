"""Log viewer widget with pyqtgraph time series plots and mode indicator."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPen, QBrush
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


class ModeIndicatorBar(QWidget):
    """Horizontal bar showing flight mode segments with color coding."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: list[dict] = []
        self._t_start: float = 0.0
        self._t_end: float = 0.0
        self.setMinimumHeight(18)
        self.setMaximumHeight(18)

    def set_segments(self, segments: list[dict], t_start: float, t_end: float):
        """Set flight mode segments for display."""
        self._segments = segments
        self._t_start = t_start
        self._t_end = t_end
        self.update()

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
                painter.drawText(x_mid - tw // 2, h - 4, label)

        painter.end()


class ChannelSelector(QWidget):
    """Tree widget for selecting data channels grouped by category."""

    channel_toggled = Signal(str, str, bool)  # message, field, enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._channel_items: dict[str, QTreeWidgetItem] = {}

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Preset selector
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("预设:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("基础状态量", "basic")
        self.preset_combo.addItem("角速率控制", "rate_control")
        self.preset_combo.addItem("姿态跟踪", "attitude")
        self.preset_combo.addItem("自定义", "custom")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        preset_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("全不选")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        preset_layout.addWidget(self.deselect_all_btn)

        layout.addLayout(preset_layout)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["通道", "消息", "字段", "单位"])
        self.tree.setColumnCount(4)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

    def populate_from_log(self, available_messages: list[str], message_fields: dict[str, list[str]]):
        """Populate the tree with available channels from a log file.

        Args:
            available_messages: List of message names present in the log.
            message_fields: Dict of message_name -> list of field names.
        """
        self.tree.clear()
        self._channel_items.clear()

        # Group by category
        categories = {
            "传感器 (Sensor)": ["sensor_accel", "sensor_gyro", "sensor_mag", "airspeed"],
            "姿态 (Attitude)": ["vehicle_attitude", "vehicle_attitude_setpoint", "vehicle_rates_setpoint"],
            "位置 (Position)": ["vehicle_local_position", "vehicle_local_position_setpoint", "vehicle_global_position"],
            "执行器 (Actuator)": ["actuator_outputs", "actuator_controls", "actuator_motors", "actuator_servos"],
            "状态 (Status)": ["vehicle_status", "manual_control_setpoint", "battery_status"],
            "其他 (Other)": [],
        }

        # Assign messages to categories
        assigned = set()
        for cat_name, msg_list in categories.items():
            cat_item = QTreeWidgetItem(self.tree, [cat_name])
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            cat_item.setCheckState(0, Qt.CheckState.Unchecked)

            for msg_name in msg_list:
                if msg_name not in available_messages:
                    continue
                assigned.add(msg_name)
                fields = message_fields.get(msg_name, [])
                msg_item = QTreeWidgetItem(cat_item, [msg_name, msg_name, "", ""])
                msg_item.setFlags(msg_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                msg_item.setCheckState(0, Qt.CheckState.Unchecked)

                for field_name in fields:
                    if field_name in ("timestamp", "timestamp_s", "instance"):
                        continue
                    ch_key = f"{msg_name}.{field_name}"
                    field_item = QTreeWidgetItem(msg_item, [field_name, msg_name, field_name, ""])
                    field_item.setCheckState(0, Qt.CheckState.Unchecked)
                    field_item.setFlags(field_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    self._channel_items[ch_key] = field_item

            cat_item.setExpanded(True)

        # Add unassigned messages to "Other"
        other_item = None
        for msg_name in available_messages:
            if msg_name not in assigned:
                if other_item is None:
                    other_item = QTreeWidgetItem(self.tree, ["其他 (Other)"])
                    other_item.setFlags(other_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                    other_item.setCheckState(0, Qt.CheckState.Unchecked)
                    other_item.setExpanded(True)
                fields = message_fields.get(msg_name, [])
                msg_item = QTreeWidgetItem(other_item, [msg_name, msg_name, "", ""])
                msg_item.setFlags(msg_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
                msg_item.setCheckState(0, Qt.CheckState.Unchecked)
                for field_name in fields:
                    if field_name in ("timestamp", "timestamp_s", "instance"):
                        continue
                    ch_key = f"{msg_name}.{field_name}"
                    field_item = QTreeWidgetItem(msg_item, [field_name, msg_name, field_name, ""])
                    field_item.setCheckState(0, Qt.CheckState.Unchecked)
                    field_item.setFlags(field_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    self._channel_items[ch_key] = field_item

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
        else:
            return

        for spec in targets:
            ch_key = f"{spec.message}.{spec.field}"
            if ch_key in self._channel_items:
                self._channel_items[ch_key].setCheckState(0, Qt.CheckState.Checked)

    def _select_all(self):
        for item in self._channel_items.values():
            item.setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
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
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter: channel selector | plot area
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Channel selector
        self.channel_selector = ChannelSelector()
        self.channel_selector.setMinimumWidth(220)
        self.channel_selector.setMaximumWidth(350)
        splitter.addWidget(self.channel_selector)

        # Right: Plot area
        plot_area = QWidget()
        plot_layout = QVBoxLayout(plot_area)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)

        self.link_cursor_cb = QCheckBox("光标联动")
        self.link_cursor_cb.setChecked(True)
        self.link_cursor_cb.toggled.connect(self._toggle_cursor_link)
        toolbar.addWidget(self.link_cursor_cb)

        toolbar.addSeparator()

        # Resample rate
        toolbar.addWidget(QLabel("重采样(Hz):"))
        self.resample_spin = QDoubleSpinBox()
        self.resample_spin.setRange(0, 10000)
        self.resample_spin.setValue(0)
        self.resample_spin.setSpecialValueText("原始")
        self.resample_spin.setDecimals(1)
        toolbar.addWidget(self.resample_spin)

        toolbar.addSeparator()

        # Coordinate frame
        toolbar.addWidget(QLabel("坐标系:"))
        self.frame_combo = QComboBox()
        self.frame_combo.addItem("机体 FRD", "frd")
        self.frame_combo.addItem("世界 NED", "ned")
        self.frame_combo.addItem("世界 ENU", "enu")
        self.frame_combo.addItem("推力垂向", "thrust_vertical")
        toolbar.addWidget(self.frame_combo)

        toolbar.addSeparator()

        self.plot_btn = QPushButton("绘制")
        self.plot_btn.clicked.connect(self._on_plot_clicked)
        toolbar.addWidget(self.plot_btn)

        self.export_btn = QPushButton("导出")
        self.export_btn.clicked.connect(self._on_export_clicked)
        toolbar.addWidget(self.export_btn)

        plot_layout.addWidget(toolbar)

        # Mode indicator bar
        self.mode_bar = ModeIndicatorBar()
        plot_layout.addWidget(self.mode_bar)

        # pyqtgraph GraphicsLayoutWidget
        pg.setConfigOptions(antialias=True, background='w', foreground='k')
        self.plot_widget = pg.GraphicsLayoutWidget()
        self.plot_widget.setBackground('w')
        plot_layout.addWidget(self.plot_widget, stretch=1)

        # Info label
        self.info_label = QLabel('加载日志文件后，选择通道并点击"绘制"')
        plot_layout.addWidget(self.info_label)

        splitter.addWidget(plot_area)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

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

        # Populate channel selector
        self.channel_selector.populate_from_log(available_messages, message_fields)

        # Update mode bar
        if self._flight_segments:
            t_start = min(s["t_start"] for s in self._flight_segments)
            t_end = max(s["t_end"] for s in self._flight_segments)
            self.mode_bar.set_segments(self._flight_segments, t_start, t_end)

        # Info
        n_msgs = len(available_messages)
        total_samples = sum(len(df) for df in raw_data.values())
        self.info_label.setText(
            f"已加载: {n_msgs} 种消息, {total_samples:,} 条记录, "
            f"{len(self._flight_segments)} 个飞行模式段"
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
            if "sensor" in msg:
                category = "state"
            elif "setpoint" in msg or "control" in msg:
                category = "control"
            else:
                category = "state"
            channels.append(ChannelSpec(
                message=msg,
                field=field,
                display_name=f"{msg}.{field}",
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
        """Plot pipeline result using pyqtgraph."""
        self.plot_widget.clear()
        self._plot_items.clear()

        if result.data.empty:
            self.info_label.setText("无数据可绘制")
            return

        df = result.data
        n_channels = len(df.columns)

        if n_channels == 0:
            return

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

        time = df.index.values

        for group_idx, (group_name, cols) in enumerate(plot_groups):
            # Create a plot row
            vb = None  # Link all views in group
            for ch_idx, col in enumerate(cols):
                color = PLOT_COLORS[ch_idx % len(PLOT_COLORS)]
                pen = pg.mkPen(color=color, width=1.5)

                if ch_idx == 0:
                    plot_item = self.plot_widget.addPlot(
                        row=group_idx, col=0,
                        title=f"{group_name}",
                    )
                    plot_item.setLabel("bottom", "时间", units="s")
                    plot_item.showGrid(x=True, y=True, alpha=0.3)
                    plot_item.addLegend(offset=(10, 10))
                    vb = plot_item.getViewBox()
                    self._plot_items.append(plot_item)
                else:
                    # Share the same plot for channels in same group
                    pass

                # Downsample if too many points for display
                values = df[col].values
                if len(time) > 10000:
                    step = len(time) // 10000
                    t_ds = time[::step]
                    v_ds = values[::step]
                else:
                    t_ds = time
                    v_ds = values

                plot_item.plot(t_ds, v_ds, pen=pen, name=col, autoDownsample=True)

            # Add crosshair for cursor linkage
            if self._cursor_linked and plot_item:
                self._add_crosshair(plot_item)

        # Add mode indicator overlay on the first plot
        if self._plot_items and self._flight_segments:
            first_plot = self._plot_items[0]
            for seg in self._flight_segments:
                classification = seg.get("classification", "unknown")
                color = MODE_COLORS.get(classification, MODE_COLORS["unknown"])
                region = pg.LinearRegionItem(
                    values=[seg["t_start"], seg["t_end"]],
                    brush=pg.mkBrush(color),
                    movable=False,
                )
                region.setZValue(-10)
                first_plot.addItem(region)

        self.info_label.setText(
            f"已绘制 {n_channels} 个通道, {len(time):,} 个数据点 | "
            f"坐标系: {result.metadata.get('target_frame', 'frd')}"
        )

    def _add_crosshair(self, plot_item: pg.PlotItem):
        """Add a crosshair line to a plot for cursor tracking."""
        # Vertical line
        v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('r', width=1, style=Qt.PenStyle.DashLine))
        plot_item.addItem(v_line, ignoreBounds=True)

        # Connect mouse move
        def mouse_moved(evt):
            pos = evt[0]
            if plot_item.sceneBoundingRect().contains(pos):
                mouse_point = plot_item.getViewBox().mapSceneToView(pos)
                v_line.setPos(mouse_point.x())
                # Move linked lines
                if self._cursor_linked:
                    for pi in self._plot_items:
                        if pi is not plot_item:
                            for item in pi.items:
                                if isinstance(item, pg.InfiniteLine):
                                    item.setPos(mouse_point.x())

        plot_item.scene().sigMouseMoved.connect(mouse_moved)

    def _toggle_cursor_link(self, checked: bool):
        self._cursor_linked = checked

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
