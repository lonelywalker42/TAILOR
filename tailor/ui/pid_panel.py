"""PID tuning panel — interactive gain optimization with visualization."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QComboBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QProgressBar,
    QCheckBox,
    QTabWidget,
    QHeaderView,
    QMessageBox,
)

from tailor.control.pid_controller import (
    PIDController,
    PIDGains,
    PIDStructure,
    ControlAxis,
    AxisConfig,
    ControllerParams,
    default_rate_gains,
)
from tailor.control.optimizer import (
    PIDOptimizer,
    TuningMethod,
    TuningObjective,
    TuningResult,
)
from tailor.dynamics.identifier import TransferFunctionModel


class TuningWorker(QThread):
    """Background thread for PID optimization."""

    finished = Signal(object)  # TuningResult or Exception
    progress = Signal(str)

    def __init__(
        self,
        plant_tf: tuple,
        initial_gains: PIDGains,
        objective: TuningObjective,
        axis: str,
        structure: PIDStructure,
        dt: float,
        method: TuningMethod,
    ):
        super().__init__()
        self.plant_tf = plant_tf
        self.initial_gains = initial_gains
        self.objective = objective
        self.axis = axis
        self.structure = structure
        self.dt = dt
        self.method = method

    def run(self):
        try:
            self.progress.emit("正在优化...")
            optimizer = PIDOptimizer()
            result = optimizer.optimize(
                plant_tf=self.plant_tf,
                initial_gains=self.initial_gains,
                objective=self.objective,
                axis=self.axis,
                structure=self.structure,
                dt=self.dt,
                method=self.method,
            )
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(e)


class PIDPanel(QWidget):
    """PID tuning panel with gain editors, optimizer, and visualization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plant_tf: Optional[tuple] = None
        self._dt: float = 0.01
        self._results: list[TuningResult] = []
        self._worker: Optional[TuningWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Settings
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)

        # Plant model
        plant_group = QGroupBox("被控对象模型")
        plant_form = QFormLayout(plant_group)
        self.plant_label = QLabel("未加载")
        plant_form.addRow("传递函数:", self.plant_label)
        self.dt_spin = QDoubleSpinBox()
        self.dt_spin.setRange(0.001, 1.0)
        self.dt_spin.setValue(0.01)
        self.dt_spin.setDecimals(4)
        self.dt_spin.setSuffix(" s")
        plant_form.addRow("采样时间:", self.dt_spin)
        settings_layout.addWidget(plant_group)

        # Axis / Structure
        axis_group = QGroupBox("控制通道")
        axis_form = QFormLayout(axis_group)
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("Roll", ControlAxis.ROLL)
        self.axis_combo.addItem("Pitch", ControlAxis.PITCH)
        self.axis_combo.addItem("Yaw", ControlAxis.YAW)
        axis_form.addRow("轴:", self.axis_combo)

        self.structure_combo = QComboBox()
        self.structure_combo.addItem("PI + 前馈", PIDStructure.PI_FF)
        self.structure_combo.addItem("PID + 前馈", PIDStructure.PID_FF)
        self.structure_combo.addItem("P", PIDStructure.P)
        self.structure_combo.addItem("P + 前馈", PIDStructure.P_FF)
        axis_form.addRow("结构:", self.structure_combo)
        settings_layout.addWidget(axis_group)

        # Current gains
        gains_group = QGroupBox("当前增益")
        gains_form = QFormLayout(gains_group)

        self.kp_spin = QDoubleSpinBox()
        self.kp_spin.setRange(0, 100)
        self.kp_spin.setDecimals(5)
        self.kp_spin.setSingleStep(0.01)
        gains_form.addRow("Kp:", self.kp_spin)

        self.ki_spin = QDoubleSpinBox()
        self.ki_spin.setRange(0, 100)
        self.ki_spin.setDecimals(5)
        self.ki_spin.setSingleStep(0.01)
        gains_form.addRow("Ki:", self.ki_spin)

        self.kd_spin = QDoubleSpinBox()
        self.kd_spin.setRange(0, 100)
        self.kd_spin.setDecimals(5)
        self.kd_spin.setSingleStep(0.001)
        gains_form.addRow("Kd:", self.kd_spin)

        self.kff_spin = QDoubleSpinBox()
        self.kff_spin.setRange(0, 100)
        self.kff_spin.setDecimals(5)
        self.kff_spin.setSingleStep(0.01)
        gains_form.addRow("Kff:", self.kff_spin)

        self.load_default_btn = QPushButton("加载默认值")
        self.load_default_btn.clicked.connect(self._load_defaults)
        gains_form.addRow(self.load_default_btn)

        settings_layout.addWidget(gains_group)

        # Tuning objectives
        obj_group = QGroupBox("优化目标")
        obj_form = QFormLayout(obj_group)

        self.bw_spin = QDoubleSpinBox()
        self.bw_spin.setRange(0.1, 100)
        self.bw_spin.setValue(5.0)
        self.bw_spin.setSuffix(" Hz")
        obj_form.addRow("目标带宽:", self.bw_spin)

        self.pm_spin = QDoubleSpinBox()
        self.pm_spin.setRange(10, 90)
        self.pm_spin.setValue(45)
        self.pm_spin.setSuffix("°")
        obj_form.addRow("最小相位裕度:", self.pm_spin)

        self.os_spin = QDoubleSpinBox()
        self.os_spin.setRange(0, 100)
        self.os_spin.setValue(15)
        self.os_spin.setSuffix("%")
        obj_form.addRow("最大超调:", self.os_spin)

        settings_layout.addWidget(obj_group)

        # Method
        method_group = QGroupBox("调参方法")
        method_form = QFormLayout(method_group)
        self.method_combo = QComboBox()
        self.method_combo.addItem("数值优化", TuningMethod.OPTIMIZER)
        self.method_combo.addItem("Ziegler-Nichols", TuningMethod.ZIEGLER_NICHOLS)
        self.method_combo.addItem("SIMC", TuningMethod.SIMC)
        method_form.addRow("方法:", self.method_combo)

        self.run_btn = QPushButton("开始调参")
        self.run_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 8px; }")
        self.run_btn.clicked.connect(self._on_run_tuning)
        method_form.addRow(self.run_btn)

        self.export_btn = QPushButton("导出 PX4 参数")
        self.export_btn.clicked.connect(self._on_export_params)
        method_form.addRow(self.export_btn)

        settings_layout.addWidget(method_group)

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

        self.plot_tabs = QTabWidget()

        # Step response comparison
        self.step_plot = pg.PlotWidget()
        self.step_plot.setLabel("bottom", "时间", units="s")
        self.step_plot.setLabel("left", "输出")
        self.step_plot.showGrid(x=True, y=True, alpha=0.3)
        self.step_plot.addLegend(offset=(10, 10))
        self.plot_tabs.addTab(self.step_plot, "阶跃响应对比")

        # Bode comparison
        self.bode_plot = pg.PlotWidget()
        self.bode_plot.setLabel("bottom", "频率", units="Hz")
        self.bode_plot.setLabel("left", "幅值", units="dB")
        self.bode_plot.showGrid(x=True, y=True, alpha=0.3)
        self.bode_plot.addLegend(offset=(10, 10))
        self.bode_plot.setLogMode(x=True, y=False)
        self.plot_tabs.addTab(self.bode_plot, "伯德图对比")

        # Control effort
        self.effort_plot = pg.PlotWidget()
        self.effort_plot.setLabel("bottom", "时间", units="s")
        self.effort_plot.setLabel("left", "控制量")
        self.effort_plot.showGrid(x=True, y=True, alpha=0.3)
        self.effort_plot.addLegend(offset=(10, 10))
        self.plot_tabs.addTab(self.effort_plot, "控制量")

        results_layout.addWidget(self.plot_tabs)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels([
            "方法", "Kp", "Ki", "Kd", "带宽", "PM", "超调"
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.itemSelectionChanged.connect(self._on_result_selected)
        results_layout.addWidget(self.results_table)

        # Info
        self.info_text = QTextEdit()
        self.info_text.setMaximumHeight(80)
        self.info_text.setReadOnly(True)
        results_layout.addWidget(self.info_text)

        splitter.addWidget(results_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    def load_plant_model(self, model: TransferFunctionModel):
        """Load plant transfer function from an identified model."""
        self._plant_tf = (model.num, model.den)
        self._dt = model.dt if model.dt > 0 else 0.01
        self.dt_spin.setValue(self._dt)

        # Display TF
        num_str = ", ".join(f"{c:.4f}" for c in model.num)
        den_str = ", ".join(f"{c:.4f}" for c in model.den)
        self.plant_label.setText(f"Num: [{num_str}]\nDen: [{den_str}]")

        self.status_label.setText(f"已加载模型: {model.method.value} fit={model.fit_percent:.1f}%")

    def _load_defaults(self):
        axis = self.axis_combo.currentData()
        cfg = default_rate_gains(axis)
        self.kp_spin.setValue(cfg.gains.kp)
        self.ki_spin.setValue(cfg.gains.ki)
        self.kd_spin.setValue(cfg.gains.kd)
        self.kff_spin.setValue(cfg.gains.kff)

    def _get_current_gains(self) -> PIDGains:
        return PIDGains(
            kp=self.kp_spin.value(),
            ki=self.ki_spin.value(),
            kd=self.kd_spin.value(),
            kff=self.kff_spin.value(),
        )

    def _on_run_tuning(self):
        if self._plant_tf is None:
            QMessageBox.warning(self, "警告", "请先加载被控对象模型（从系统辨识结果中）")
            return

        gains = self._get_current_gains()
        method = self.method_combo.currentData()
        axis = self.axis_combo.currentData().value
        structure = self.structure_combo.currentData()
        dt = self.dt_spin.value()

        objective = TuningObjective(
            target_bandwidth_hz=self.bw_spin.value(),
            min_phase_margin_deg=self.pm_spin.value(),
            max_overshoot_pct=self.os_spin.value(),
        )

        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self._worker = TuningWorker(
            self._plant_tf, gains, objective, axis, structure, dt, method
        )
        self._worker.finished.connect(self._on_tuning_done)
        self._worker.start()

    def _on_tuning_done(self, result):
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        if isinstance(result, Exception):
            self.status_label.setText(f"优化失败: {result}")
            return

        self._results.append(result)
        self._plot_comparison(result)
        self._update_results_table()

        # Apply optimized gains to spin boxes
        self.kp_spin.setValue(result.optimized_gains.kp)
        self.ki_spin.setValue(result.optimized_gains.ki)
        self.kd_spin.setValue(result.optimized_gains.kd)
        self.kff_spin.setValue(result.optimized_gains.kff)

        self.info_text.setText(result.improvement_summary())
        self.status_label.setText(
            f"优化完成: {result.method.value} "
            f"带宽={result.after_bandwidth_hz:.2f}Hz "
            f"PM={result.after_phase_margin_deg:.1f}°"
        )

    def _plot_comparison(self, result: TuningResult):
        """Plot before/after step response and Bode."""
        from tailor.dynamics.validation import compute_step_response_data, compute_frequency_response_data
        from tailor.dynamics.identifier import TransferFunctionModel, IdentificationMethod

        # Create closed-loop models
        controller = PIDController(self.structure_combo.currentData())

        # Before
        cl_before = controller.get_closed_loop_tf(result.original_gains, result.plant_tf)
        if isinstance(cl_before, tuple):
            model_before = TransferFunctionModel(
                num=cl_before[0], den=cl_before[1], dt=self._dt,
                method=IdentificationMethod.ARX,
            )
        else:
            model_before = TransferFunctionModel(
                num=np.array(cl_before.num[0][0]),
                den=np.array(cl_before.den[0][0]),
                dt=self._dt,
                method=IdentificationMethod.ARX,
            )

        # After
        cl_after = controller.get_closed_loop_tf(result.optimized_gains, result.plant_tf)
        if isinstance(cl_after, tuple):
            model_after = TransferFunctionModel(
                num=cl_after[0], den=cl_after[1], dt=self._dt,
                method=IdentificationMethod.ARX,
            )
        else:
            model_after = TransferFunctionModel(
                num=np.array(cl_after.num[0][0]),
                den=np.array(cl_after.den[0][0]),
                dt=self._dt,
                method=IdentificationMethod.ARX,
            )

        # Step response
        self.step_plot.clear()
        t_b, y_b = compute_step_response_data(model_before, 2.0)
        t_a, y_a = compute_step_response_data(model_after, 2.0)
        pen_b = pg.mkPen(color=(200, 100, 100), width=1.5)
        pen_a = pg.mkPen(color=(50, 150, 50), width=2)
        self.step_plot.plot(t_b, y_b, pen=pen_b, name="优化前")
        self.step_plot.plot(t_a, y_a, pen=pen_a, name="优化后")
        ref_pen = pg.mkPen(color=(150, 150, 150), width=1, style=Qt.PenStyle.DotLine)
        self.step_plot.plot(t_b, np.ones_like(t_b), pen=ref_pen)

        # Bode
        self.bode_plot.clear()
        f_b, m_b, _ = compute_frequency_response_data(model_before)
        f_a, m_a, _ = compute_frequency_response_data(model_after)
        self.bode_plot.plot(f_b, m_b, pen=pen_b, name="优化前")
        self.bode_plot.plot(f_a, m_a, pen=pen_a, name="优化后")

    def _update_results_table(self):
        self.results_table.setRowCount(len(self._results))
        for i, r in enumerate(self._results):
            self.results_table.setItem(i, 0, QTableWidgetItem(r.method.value))
            self.results_table.setItem(i, 1, QTableWidgetItem(f"{r.optimized_gains.kp:.4f}"))
            self.results_table.setItem(i, 2, QTableWidgetItem(f"{r.optimized_gains.ki:.4f}"))
            self.results_table.setItem(i, 3, QTableWidgetItem(f"{r.optimized_gains.kd:.4f}"))
            self.results_table.setItem(i, 4, QTableWidgetItem(f"{r.after_bandwidth_hz:.2f}"))
            self.results_table.setItem(i, 5, QTableWidgetItem(f"{r.after_phase_margin_deg:.1f}"))
            self.results_table.setItem(i, 6, QTableWidgetItem(f"{r.after_overshoot_pct:.1f}"))

    def _on_result_selected(self):
        row = self.results_table.currentRow()
        if 0 <= row < len(self._results):
            r = self._results[row]
            self.kp_spin.setValue(r.optimized_gains.kp)
            self.ki_spin.setValue(r.optimized_gains.ki)
            self.kd_spin.setValue(r.optimized_gains.kd)
            self.kff_spin.setValue(r.optimized_gains.kff)
            self.info_text.setText(r.improvement_summary())

    def _on_export_params(self):
        gains = self._get_current_gains()
        axis = self.axis_combo.currentData()
        axis_map = {
            ControlAxis.ROLL: "MC_ROLLRATE",
            ControlAxis.PITCH: "MC_PITCHRATE",
            ControlAxis.YAW: "MC_YAWRATE",
        }
        prefix = axis_map.get(axis, "MC_ROLLRATE")

        params = f"""# TAILOR PID Export — {axis.value}
# Generated by TAILOR v0.1.0

{prefix}_P {gains.kp:.6f}
{prefix}_I {gains.ki:.6f}
{prefix}_D {gains.kd:.6f}
{prefix}_FF {gains.kff:.6f}
"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PX4 参数", "",
            "参数文件 (*.params);;文本文件 (*.txt);;所有文件 (*)"
        )
        if path:
            from pathlib import Path
            Path(path).write_text(params, encoding="utf-8")
            self.status_label.setText(f"已导出: {path}")

    def clear(self):
        self._results.clear()
        self.step_plot.clear()
        self.bode_plot.clear()
        self.effort_plot.clear()
        self.results_table.setRowCount(0)
        self.info_text.clear()
        self.plant_label.setText("未加载")
        self._plant_tf = None
        self.status_label.setText("就绪")
