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

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Settings
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)

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
        self.segment_list.setMaximumHeight(120)
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

        splitter.addWidget(settings_widget)

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
