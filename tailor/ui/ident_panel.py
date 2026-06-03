"""System identification wizard panel.

Guides the user through: data selection → preprocessing → identification → results.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QComboBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QGroupBox,
    QFormLayout,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QProgressBar,
    QTabWidget,
    QHeaderView,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
)

from tailor.dynamics.identifier import (
    SystemIdentifier,
    TransferFunctionModel,
    IdentificationMethod,
)
from tailor.dynamics.excitation import ExcitationDetector, ExcitationSegment
from tailor.dynamics.validation import (
    ModelValidator,
    StepResponseMetrics,
    FrequencyMetrics,
    compute_step_response_data,
    compute_frequency_response_data,
)


class IdentificationWorker(QThread):
    """Background thread for running identification."""

    finished = Signal(object)   # TransferFunctionModel or Exception
    progress = Signal(str)

    def __init__(
        self,
        u: np.ndarray,
        y: np.ndarray,
        method: IdentificationMethod,
        na: int,
        nb: int,
        nk: int,
        dt: float,
        input_channel: str,
        output_channel: str,
    ):
        super().__init__()
        self.u = u
        self.y = y
        self.method = method
        self.na = na
        self.nb = nb
        self.nk = nk
        self.dt = dt
        self.input_channel = input_channel
        self.output_channel = output_channel

    def run(self):
        try:
            identifier = SystemIdentifier()
            self.progress.emit("正在辨识...")

            if self.method == IdentificationMethod.ARX:
                model = identifier.identify_arx(
                    self.u, self.y,
                    na=self.na, nb=self.nb, nk=self.nk, dt=self.dt,
                    input_channel=self.input_channel,
                    output_channel=self.output_channel,
                )
            elif self.method == IdentificationMethod.OE:
                model = identifier.identify_oe(
                    self.u, self.y,
                    nf=self.na, nb=self.nb, nk=self.nk, dt=self.dt,
                    input_channel=self.input_channel,
                    output_channel=self.output_channel,
                )
            elif self.method == IdentificationMethod.FREQUENCY:
                model = identifier.identify_frequency(
                    self.u, self.y,
                    order=self.na, dt=self.dt,
                    input_channel=self.input_channel,
                    output_channel=self.output_channel,
                )
            else:
                model = identifier.identify_arx(
                    self.u, self.y,
                    na=self.na, nb=self.nb, nk=self.nk, dt=self.dt,
                    input_channel=self.input_channel,
                    output_channel=self.output_channel,
                )

            self.finished.emit(model)
        except Exception as e:
            self.finished.emit(e)


class IdentPanel(QWidget):
    """System identification wizard panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw_data: dict = {}
        self._time: Optional[np.ndarray] = None
        self._models: list[TransferFunctionModel] = []
        self._worker: Optional[IdentificationWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Settings (wrapped in scroll area for small windows)
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(0, 0, 0, 0)

        # Step 1: Data Selection
        data_group = QGroupBox("1. 数据选择")
        data_form = QFormLayout(data_group)

        self.input_combo = QComboBox()
        self.input_combo.setMinimumWidth(200)
        data_form.addRow("输入通道 (u):", self.input_combo)

        self.output_combo = QComboBox()
        self.output_combo.setMinimumWidth(200)
        data_form.addRow("输出通道 (y):", self.output_combo)

        self.detect_btn = QPushButton("检测激励段")
        self.detect_btn.clicked.connect(self._on_detect_excitation)
        data_form.addRow(self.detect_btn)

        self.segment_list = QListWidget()
        self.segment_list.setMinimumHeight(80)
        self.segment_list.setMaximumHeight(160)
        self.segment_list.itemClicked.connect(self._on_segment_selected)
        data_form.addRow("检测到的段:", self.segment_list)

        settings_layout.addWidget(data_group)

        # Step 2: Preprocessing
        preprocess_group = QGroupBox("2. 预处理")
        preprocess_form = QFormLayout(preprocess_group)

        self.detrend_cb = QCheckBox("去趋势")
        self.detrend_cb.setChecked(True)
        preprocess_form.addRow(self.detrend_cb)

        self.filter_cb = QCheckBox("低通滤波")
        preprocess_form.addRow(self.filter_cb)

        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(0.1, 1000)
        self.cutoff_spin.setValue(20)
        self.cutoff_spin.setSuffix(" Hz")
        preprocess_form.addRow("截止频率:", self.cutoff_spin)

        settings_layout.addWidget(preprocess_group)

        # Step 3: Model Configuration
        model_group = QGroupBox("3. 模型配置")
        model_form = QFormLayout(model_group)

        self.method_combo = QComboBox()
        self.method_combo.addItem("ARX", IdentificationMethod.ARX)
        self.method_combo.addItem("OE (Output-Error)", IdentificationMethod.OE)
        self.method_combo.addItem("频域辨识", IdentificationMethod.FREQUENCY)
        model_form.addRow("辨识方法:", self.method_combo)

        self.na_spin = QSpinBox()
        self.na_spin.setRange(1, 20)
        self.na_spin.setValue(3)
        model_form.addRow("分母阶次 (na):", self.na_spin)

        self.nb_spin = QSpinBox()
        self.nb_spin.setRange(1, 20)
        self.nb_spin.setValue(3)
        model_form.addRow("分子阶次 (nb):", self.nb_spin)

        self.nk_spin = QSpinBox()
        self.nk_spin.setRange(0, 50)
        self.nk_spin.setValue(0)
        model_form.addRow("延迟 (nk):", self.nk_spin)

        self.dt_spin = QDoubleSpinBox()
        self.dt_spin.setRange(0.001, 1.0)
        self.dt_spin.setValue(0.01)
        self.dt_spin.setDecimals(4)
        self.dt_spin.setSuffix(" s")
        model_form.addRow("采样时间:", self.dt_spin)

        self.auto_order_cb = QCheckBox("自动选择阶次")
        model_form.addRow(self.auto_order_cb)

        self.max_order_spin = QSpinBox()
        self.max_order_spin.setRange(2, 20)
        self.max_order_spin.setValue(8)
        model_form.addRow("最大阶次:", self.max_order_spin)

        settings_layout.addWidget(model_group)

        # Run button
        self.run_btn = QPushButton("开始辨识")
        self.run_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 8px; }")
        self.run_btn.clicked.connect(self._on_run_identification)
        settings_layout.addWidget(self.run_btn)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        settings_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        settings_layout.addWidget(self.status_label)

        settings_layout.addStretch()

        # Wrap settings in scroll area
        from PySide6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidget(settings_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(280)
        scroll_area.setMaximumWidth(400)

        splitter.addWidget(scroll_area)

        # Right: Results
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)

        # Results tabs
        self.results_tabs = QTabWidget()

        # Time domain tab
        self.time_plot = pg.PlotWidget()
        self.time_plot.setLabel("bottom", "时间", units="s")
        self.time_plot.setLabel("left", "幅值")
        self.time_plot.showGrid(x=True, y=True, alpha=0.3)
        self.time_plot.addLegend(offset=(10, 10))
        self.results_tabs.addTab(self.time_plot, "时域对比")

        # Frequency domain tab
        self.freq_plot = pg.PlotWidget()
        self.freq_plot.setLabel("bottom", "频率", units="Hz")
        self.freq_plot.setLabel("left", "幅值", units="dB")
        self.freq_plot.showGrid(x=True, y=True, alpha=0.3)
        self.freq_plot.addLegend(offset=(10, 10))
        self.freq_plot.setLogMode(x=True, y=False)
        self.results_tabs.addTab(self.freq_plot, "频率响应")

        # Step response tab
        self.step_plot = pg.PlotWidget()
        self.step_plot.setLabel("bottom", "时间", units="s")
        self.step_plot.setLabel("left", "幅值")
        self.step_plot.showGrid(x=True, y=True, alpha=0.3)
        self.step_plot.addLegend(offset=(10, 10))
        self.results_tabs.addTab(self.step_plot, "阶跃响应")

        # Residual tab
        self.resid_plot = pg.PlotWidget()
        self.resid_plot.setLabel("bottom", "时间", units="s")
        self.resid_plot.setLabel("left", "残差")
        self.resid_plot.showGrid(x=True, y=True, alpha=0.3)
        self.results_tabs.addTab(self.resid_plot, "残差分析")

        # PID tracking analysis tab
        self.pid_plot = pg.PlotWidget()
        self.pid_plot.setLabel("bottom", "时间", units="s")
        self.pid_plot.setLabel("left", "角速度", units="rad/s")
        self.pid_plot.showGrid(x=True, y=True, alpha=0.3)
        self.pid_plot.addLegend(offset=(10, 10))
        self.results_tabs.addTab(self.pid_plot, "PID 跟踪分析")

        results_layout.addWidget(self.results_tabs)

        # Model results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels([
            "方法", "阶次(na,nb)", "延迟", "拟合%", "BIC",
            "带宽(Hz)", "相位裕度", "超调%"
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.itemSelectionChanged.connect(self._on_model_selected)
        results_layout.addWidget(self.results_table)

        # Info text
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(100)
        self.info_text.setReadOnly(True)
        results_layout.addWidget(self.info_text)

        splitter.addWidget(results_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    def load_data(self, raw_data: dict, time: Optional[np.ndarray] = None):
        """Load data for identification.

        Args:
            raw_data: Dict of channel_name -> numpy array.
            time: Optional time array (if not provided, derive from data).
        """
        self._raw_data = raw_data
        self._time = time

        # Populate channel combos
        self.input_combo.clear()
        self.output_combo.clear()
        for name in sorted(raw_data.keys()):
            self.input_combo.addItem(name)
            self.output_combo.addItem(name)

        # Try to select sensible defaults
        for i in range(self.input_combo.count()):
            text = self.input_combo.itemText(i)
            if "control" in text or "actuator" in text or "throttle" in text:
                self.input_combo.setCurrentIndex(i)
                break

        for i in range(self.output_combo.count()):
            text = self.output_combo.itemText(i)
            if "gyro" in text or "rate" in text:
                self.output_combo.setCurrentIndex(i)
                break

        self.status_label.setText(f"已加载 {len(raw_data)} 个通道")

    def auto_setup_pairs(self, flat_data: dict, time: Optional[np.ndarray] = None):
        """Auto-detect excitation and pre-fill channel pairs for system identification.

        Called after log load to prepare the ident panel for user confirmation.

        Args:
            flat_data: Dict of channel_name -> numpy array (same as load_data).
            time: Time array for excitation detection.
        """
        # Update internal data with time
        self._raw_data = flat_data
        self._time = time

        # Standard input/output pairs for rate and attitude identification
        STANDARD_PAIRS = [
            ("actuator_controls.control[0]", "sensor_gyro.x", "Roll 速率"),
            ("actuator_controls.control[1]", "sensor_gyro.y", "Pitch 速率"),
            ("actuator_controls.control[3]", "sensor_gyro.z", "Yaw 速率"),
            ("actuator_controls.control[0]", "derived_attitude_deg.roll_deg", "Roll 角度"),
            ("actuator_controls.control[1]", "derived_attitude_deg.pitch_deg", "Pitch 角度"),
        ]

        # Find best available pair
        best_pair = None
        best_score = -1
        for input_ch, output_ch, label in STANDARD_PAIRS:
            if input_ch in flat_data and output_ch in flat_data:
                # Prefer rate control pairs (they have better excitation)
                score = 2 if "gyro" in output_ch else 1
                if score > best_score:
                    best_score = score
                    best_pair = (input_ch, output_ch, label)

        if best_pair is None:
            self.status_label.setText("未找到标准通道对，请手动选择")
            return

        input_ch, output_ch, label = best_pair

        # Set combo selections
        input_idx = self.input_combo.findText(input_ch)
        if input_idx >= 0:
            self.input_combo.setCurrentIndex(input_idx)

        output_idx = self.output_combo.findText(output_ch)
        if output_idx >= 0:
            self.output_combo.setCurrentIndex(output_idx)

        # Auto-detect excitation on output channel
        output_data = flat_data.get(output_ch)
        if output_data is not None and time is not None:
            detector = ExcitationDetector()
            try:
                segments = detector.detect(time, np.asarray(output_data).flatten(), channel_name=output_ch)
                self.segment_list.clear()
                for seg in segments:
                    item = QListWidgetItem(
                        f"[{seg.t_start:.2f}-{seg.t_end:.2f}s] "
                        f"{seg.excitation_type.value} q={seg.quality_score:.2f}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, seg)
                    self.segment_list.addItem(item)
                # Auto-select best segment
                if self.segment_list.count() > 0:
                    self.segment_list.setCurrentRow(0)
            except Exception:
                pass

        self.status_label.setText(f"已自动配置: {label} ({input_ch} → {output_ch})")

    def _on_detect_excitation(self):
        """Detect excitation segments in the selected output channel."""
        from tailor.dynamics.excitation import ExcitationDetector

        output_name = self.output_combo.currentText()
        if output_name not in self._raw_data:
            return

        data = self._raw_data[output_name]
        if self._time is not None:
            t = self._time
        else:
            t = np.arange(len(data)) * self.dt_spin.value()

        detector = ExcitationDetector()
        segments = detector.detect(t, data, channel_name=output_name)

        self.segment_list.clear()
        for i, seg in enumerate(segments):
            item = QListWidgetItem(
                f"[{seg.t_start:.2f}-{seg.t_end:.2f}s] "
                f"{seg.excitation_type.value} q={seg.quality_score:.2f}"
            )
            item.setData(Qt.ItemDataRole.UserRole, seg)
            self.segment_list.addItem(item)

        self.status_label.setText(f"检测到 {len(segments)} 个激励段")

    def _on_segment_selected(self, item: QListWidgetItem):
        """Handle segment selection."""
        seg = item.data(Qt.ItemDataRole.UserRole)
        if seg:
            self.status_label.setText(
                f"已选: {seg.t_start:.2f}-{seg.t_end:.2f}s "
                f"({seg.duration:.1f}s, {seg.excitation_type.value})"
            )

    def _get_selected_data(self) -> tuple[np.ndarray, np.ndarray, float]:
        """Get the selected input/output data, optionally windowed.

        Returns:
            (u, y, dt)
        """
        input_name = self.input_combo.currentText()
        output_name = self.output_combo.currentText()

        u = self._raw_data.get(input_name)
        y = self._raw_data.get(output_name)

        if u is None or y is None:
            raise ValueError(f"通道未找到: {input_name} 或 {output_name}")

        u = np.asarray(u).flatten()
        y = np.asarray(y).flatten()

        # Align lengths
        n = min(len(u), len(y))
        u = u[:n]
        y = y[:n]

        # Apply time window if segment selected
        current_item = self.segment_list.currentItem()
        if current_item:
            seg = current_item.data(Qt.ItemDataRole.UserRole)
            if seg and self._time is not None:
                mask = (self._time >= seg.t_start) & (self._time <= seg.t_end)
                u = u[mask]
                y = y[mask]

        # Preprocessing
        if self.detrend_cb.isChecked():
            from scipy.signal import detrend
            u = detrend(u)
            y = detrend(y)

        if self.filter_cb.isChecked():
            from scipy.signal import butter, filtfilt
            dt = self.dt_spin.value()
            fs = 1.0 / dt
            cutoff = self.cutoff_spin.value()
            if cutoff < fs / 2:
                b, a = butter(4, cutoff / (fs / 2), btype='low')
                u = filtfilt(b, a, u)
                y = filtfilt(b, a, y)

        dt = self.dt_spin.value()
        return u, y, dt

    def _on_run_identification(self):
        """Run system identification in background thread."""
        try:
            u, y, dt = self._get_selected_data()
        except Exception as e:
            QMessageBox.warning(self, "数据错误", str(e))
            return

        if len(u) < 20:
            QMessageBox.warning(self, "数据不足", "需要至少 20 个数据点")
            return

        method = self.method_combo.currentData()
        na = self.na_spin.value()
        nb = self.nb_spin.value()
        nk = self.nk_spin.value()

        input_ch = self.input_combo.currentText()
        output_ch = self.output_combo.currentText()

        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText("正在辨识...")

        self._worker = IdentificationWorker(
            u, y, method, na, nb, nk, dt, input_ch, output_ch
        )
        self._worker.finished.connect(self._on_identification_done)
        self._worker.start()

    def _on_identification_done(self, result):
        """Handle identification completion."""
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if isinstance(result, Exception):
            self.status_label.setText(f"辨识失败: {result}")
            QMessageBox.warning(self, "辨识失败", str(result))
            return

        model = result
        self._models.append(model)

        # Validate
        sm = ModelValidator.step_response_metrics(model)
        fm = ModelValidator.frequency_metrics(model)

        # Update results table
        row = self.results_table.rowCount()
        self.results_table.setRowCount(row + 1)
        self.results_table.setItem(row, 0, QTableWidgetItem(model.method.value))
        self.results_table.setItem(row, 1, QTableWidgetItem(f"{model.order_den},{model.order_num}"))
        self.results_table.setItem(row, 2, QTableWidgetItem(str(model.delay)))
        self.results_table.setItem(row, 3, QTableWidgetItem(f"{model.fit_percent:.1f}"))
        self.results_table.setItem(row, 4, QTableWidgetItem(f"{model.bic:.1f}"))
        self.results_table.setItem(row, 5, QTableWidgetItem(f"{fm.bandwidth_hz:.2f}"))
        self.results_table.setItem(row, 6, QTableWidgetItem(f"{fm.phase_margin_deg:.1f}"))
        self.results_table.setItem(row, 7, QTableWidgetItem(f"{sm.overshoot_pct:.1f}"))

        # Plot results
        self._plot_model_results(model)

        self.status_label.setText(
            f"辨识完成: {model.method.value} "
            f"拟合={model.fit_percent:.1f}% "
            f"带宽={fm.bandwidth_hz:.2f}Hz "
            f"PM={fm.phase_margin_deg:.1f}°"
        )

        # Info text
        self.info_text.setText(
            f"模型: {model}\n"
            f"极点: {model.get_poles()}\n"
            f"零点: {model.get_zeros()}\n"
            f"稳定: {'是' if model.is_stable() else '否'}\n"
            f"上升时间: {sm.rise_time_s:.3f}s | 超调: {sm.overshoot_pct:.1f}% | "
            f"调节时间: {sm.settling_time_s:.3f}s"
        )

        # Run PID tracking analysis
        self._analyze_pid_tracking(model)

    def _plot_model_results(self, model: TransferFunctionModel):
        """Plot identification results."""
        input_name = self.input_combo.currentText()
        output_name = self.output_combo.currentText()
        u = self._raw_data.get(input_name)
        y = self._raw_data.get(output_name)

        if u is None or y is None:
            return

        u = np.asarray(u).flatten()
        y = np.asarray(y).flatten()
        n = min(len(u), len(y))
        u = u[:n]
        y = y[:n]

        dt = model.dt if model.dt > 0 else self.dt_spin.value()
        t = np.arange(n) * dt

        # Time domain: measured vs simulated
        self.time_plot.clear()
        y_sim = model.simulate(u)

        pen_meas = pg.mkPen(color=(55, 126, 184), width=1.5)
        pen_sim = pg.mkPen(color=(228, 26, 28), width=1.5, style=Qt.PenStyle.DashLine)
        self.time_plot.plot(t, y, pen=pen_meas, name="实测")
        self.time_plot.plot(t[:len(y_sim)], y_sim, pen=pen_sim, name="模型仿真")

        # Step response
        self.step_plot.clear()
        t_step, y_step = compute_step_response_data(model, t_duration=min(5.0, t[-1]))
        pen_step = pg.mkPen(color=(77, 175, 74), width=2)
        self.step_plot.plot(t_step, y_step, pen=pen_step, name="阶跃响应")

        # Add reference line
        ref_pen = pg.mkPen(color=(150, 150, 150), width=1, style=Qt.PenStyle.DotLine)
        self.step_plot.plot(t_step, np.ones_like(t_step), pen=ref_pen, name="参考")

        # Frequency response
        self.freq_plot.clear()
        freq_hz, mag_db, _ = compute_frequency_response_data(model)
        pen_mag = pg.mkPen(color=(152, 78, 163), width=2)
        self.freq_plot.plot(freq_hz, mag_db, pen=pen_mag, name="幅频响应")

        # Residual
        self.resid_plot.clear()
        residuals = y[:len(y_sim)] - y_sim
        pen_resid = pg.mkPen(color=(255, 127, 0), width=1)
        self.resid_plot.plot(t[:len(residuals)], residuals, pen=pen_resid, name="残差")

    def _on_model_selected(self):
        """Handle model selection in the results table."""
        row = self.results_table.currentRow()
        if 0 <= row < len(self._models):
            model = self._models[row]
            self._plot_model_results(model)

    def _analyze_pid_tracking(self, model: TransferFunctionModel):
        """Analyze PID tracking performance using setpoint vs actual response.

        Computes tracking metrics between rate setpoints and gyro measurements,
        and displays results on the PID tracking tab.
        """
        # Map output channel to corresponding setpoint channel
        output_ch = self.output_combo.currentText()
        sp_map = {
            "sensor_gyro.x": ("derived_angular_rate_setpoint.roll_rate_sp", "Roll"),
            "sensor_gyro.y": ("derived_angular_rate_setpoint.pitch_rate_sp", "Pitch"),
            "sensor_gyro.z": ("derived_angular_rate_setpoint.yaw_rate_sp", "Yaw"),
            "derived_attitude_deg.roll_deg": ("derived_attitude_setpoint_deg.roll_deg_sp", "Roll"),
            "derived_attitude_deg.pitch_deg": ("derived_attitude_setpoint_deg.pitch_deg_sp", "Pitch"),
        }

        sp_ch = sp_map.get(output_ch)
        if sp_ch is None:
            return

        sp_name, axis_label = sp_ch
        sp_data = self._raw_data.get(sp_name)
        resp_data = self._raw_data.get(output_ch)

        if sp_data is None or resp_data is None:
            return

        sp = np.asarray(sp_data).flatten()
        resp = np.asarray(resp_data).flatten()
        n = min(len(sp), len(resp))
        sp = sp[:n]
        resp = resp[:n]

        if n < 10:
            return

        dt = self.dt_spin.value()
        t = np.arange(n) * dt

        # --- Compute tracking metrics ---
        error = sp - resp
        rmse = np.sqrt(np.nanmean(error ** 2))
        max_error = np.nanmax(np.abs(error))

        # Cross-correlation for delay estimation
        from scipy.signal import correlate
        sp_norm = sp - np.nanmean(sp)
        resp_norm = resp - np.nanmean(resp)
        sp_std = np.nanstd(sp_norm)
        resp_std = np.nanstd(resp_norm)
        if sp_std > 1e-10 and resp_std > 1e-10:
            xcorr = correlate(sp_norm, resp_norm, mode='full')
            xcorr /= (sp_std * resp_std * n)
            lags = np.arange(-n + 1, n)
            peak_idx = np.argmax(np.abs(xcorr))
            delay_samples = lags[peak_idx]
            delay_s = delay_samples * dt
            peak_corr = xcorr[peak_idx]
        else:
            delay_s = 0.0
            peak_corr = 0.0

        # Normalized RMS tracking error
        sp_range = np.nanmax(sp) - np.nanmin(sp)
        nrmse = (rmse / sp_range * 100) if sp_range > 1e-10 else 0.0

        # --- Plot setpoint vs response ---
        self.pid_plot.clear()
        pen_sp = pg.mkPen(color=(55, 126, 184), width=1.5)
        pen_resp = pg.mkPen(color=(228, 26, 28), width=1.5)
        pen_err = pg.mkPen(color=(255, 127, 0), width=1, style=Qt.PenStyle.DashLine)

        # Downsample for display
        max_pts = 10000
        if n > max_pts:
            step = n // max_pts
            t_ds = t[::step]
            sp_ds = sp[::step]
            resp_ds = resp[::step]
            err_ds = error[::step]
        else:
            t_ds = t
            sp_ds = sp
            resp_ds = resp
            err_ds = error

        self.pid_plot.plot(t_ds, sp_ds, pen=pen_sp, name=f"{axis_label} 指令")
        self.pid_plot.plot(t_ds, resp_ds, pen=pen_resp, name=f"{axis_label} 响应")
        self.pid_plot.plot(t_ds, err_ds, pen=pen_err, name="跟踪误差")

        # Add zero reference line
        ref_pen = pg.mkPen(color=(150, 150, 150), width=1, style=Qt.PenStyle.DotLine)
        self.pid_plot.plot(t_ds, np.zeros_like(t_ds), pen=ref_pen)

        # --- Update info text with tracking metrics ---
        info = (
            f"=== PID 跟踪性能 ({axis_label}) ===\n"
            f"RMSE: {rmse:.4f} rad/s | 归一化RMSE: {nrmse:.1f}%\n"
            f"最大误差: {max_error:.4f} rad/s\n"
            f"响应延迟: {delay_s:.3f}s | 相关峰值: {peak_corr:.3f}\n"
            f"模型拟合: {model.fit_percent:.1f}% | 带宽: "
        )
        from tailor.dynamics.validation import ModelValidator
        fm = ModelValidator.frequency_metrics(model)
        info += f"{fm.bandwidth_hz:.2f}Hz | 相位裕度: {fm.phase_margin_deg:.1f}°"
        self.info_text.setText(info)

        # Store tracking metrics for PID panel
        self._tracking_metrics = {
            "axis": axis_label,
            "rmse": rmse,
            "nrmse_pct": nrmse,
            "max_error": max_error,
            "delay_s": delay_s,
            "correlation": peak_corr,
        }

    def get_tracking_metrics(self) -> Optional[dict]:
        """Get the latest tracking metrics for the PID panel."""
        return getattr(self, '_tracking_metrics', None)

    def get_latest_model(self) -> Optional[TransferFunctionModel]:
        """Get the most recently identified model."""
        return self._models[-1] if self._models else None

    def clear(self):
        """Clear all data and results."""
        self._raw_data.clear()
        self._models.clear()
        self.time_plot.clear()
        self.freq_plot.clear()
        self.step_plot.clear()
        self.resid_plot.clear()
        self.results_table.setRowCount(0)
        self.segment_list.clear()
        self.info_text.clear()
        self.input_combo.clear()
        self.output_combo.clear()
        self.status_label.setText("就绪")
