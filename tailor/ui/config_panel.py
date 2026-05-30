"""Vehicle configuration editor panel."""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QDoubleSpinBox,
    QSpinBox,
    QTextEdit,
    QPushButton,
    QComboBox,
    QLabel,
    QGroupBox,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QTabWidget,
)

from tailor.core.config import DEFAULT_VEHICLE_PARAMS
from tailor.data.database import Database
from tailor.data.manager import VehicleManager, ConfigurationManager


class ConfigurationPanel(QWidget):
    """Bottom panel for editing vehicle configuration parameters."""

    def __init__(self, db: Database):
        super().__init__()
        self._db = db
        self._vehicle_id: Optional[int] = None
        self._param_widgets: dict[str, QWidget] = {}
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()
        self.vehicle_label = QLabel("未选择飞行器")
        self.vehicle_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.vehicle_label)
        header_layout.addStretch()

        self.config_selector = QComboBox()
        self.config_selector.setMinimumWidth(200)
        self.config_selector.currentIndexChanged.connect(self._on_config_changed)
        header_layout.addWidget(QLabel("配置:"))
        header_layout.addWidget(self.config_selector)

        main_layout.addLayout(header_layout)

        # Tab widget for parameter groups
        self.tabs = QTabWidget()

        # Physical parameters tab
        self.physical_tab = self._create_physical_params_tab()
        self.tabs.addTab(self.physical_tab, "物理参数")

        # Motor/servo parameters tab
        self.propulsion_tab = self._create_propulsion_params_tab()
        self.tabs.addTab(self.propulsion_tab, "动力系统")

        # Sensor offsets tab
        self.sensor_tab = self._create_sensor_params_tab()
        self.tabs.addTab(self.sensor_tab, "传感器偏移")

        # Notes tab
        self.notes_tab = self._create_notes_tab()
        self.tabs.addTab(self.notes_tab, "备注")

        main_layout.addWidget(self.tabs)

        # Bottom buttons
        btn_layout = QHBoxLayout()

        self.save_btn = QPushButton("保存配置")
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.save_btn)

        self.save_as_btn = QPushButton("另存为模板")
        self.save_as_btn.clicked.connect(self._on_save_as_template)
        btn_layout.addWidget(self.save_as_btn)

        self.import_btn = QPushButton("从 JSON 导入")
        self.import_btn.clicked.connect(self._on_import_json)
        btn_layout.addWidget(self.import_btn)

        self.export_btn = QPushButton("导出 JSON")
        self.export_btn.clicked.connect(self._on_export_json)
        btn_layout.addWidget(self.export_btn)

        btn_layout.addStretch()

        main_layout.addLayout(btn_layout)

    def _create_physical_params_tab(self) -> QWidget:
        """Create the physical parameters form."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        form = QFormLayout(widget)

        # Mass
        self._add_double_param(form, "mass", "质量 (kg)", 0.0, 1000.0, 3)

        # Moments of inertia
        self._add_double_param(form, "inertia_ixx", "转动惯量 Ixx (kg·m²)", 0.0, 1000.0, 6)
        self._add_double_param(form, "inertia_iyy", "转动惯量 Iyy (kg·m²)", 0.0, 1000.0, 6)
        self._add_double_param(form, "inertia_izz", "转动惯量 Izz (kg·m²)", 0.0, 1000.0, 6)
        self._add_double_param(form, "inertia_ixz", "转动惯量 Ixz (kg·m²)", -1000.0, 1000.0, 6)

        # CG position
        self._add_double_param(form, "cg_x", "重心 X (m)", -10.0, 10.0, 4)
        self._add_double_param(form, "cg_y", "重心 Y (m)", -10.0, 10.0, 4)
        self._add_double_param(form, "cg_z", "重心 Z (m)", -10.0, 10.0, 4)

        # Wing parameters
        self._add_double_param(form, "wingspan", "翼展 (m)", 0.0, 50.0, 3)
        self._add_double_param(form, "wing_area", "翼面积 (m²)", 0.0, 100.0, 3)

        scroll.setWidget(widget)
        return scroll

    def _create_propulsion_params_tab(self) -> QWidget:
        """Create the motor/servo parameters form."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        form = QFormLayout(widget)

        self._add_int_param(form, "num_motors", "电机数量", 0, 32)
        self._add_int_param(form, "num_servos", "舵机数量", 0, 32)
        self._add_double_param(form, "motor_thrust_coeff", "电机推力系数 (N/cmd)", 0.0, 1000.0, 6)
        self._add_double_param(form, "motor_torque_coeff", "电机扭矩系数 (Nm/cmd)", 0.0, 100.0, 6)
        self._add_double_param(form, "servo_efficiency", "舵面效率", 0.0, 2.0, 3)

        scroll.setWidget(widget)
        return scroll

    def _create_sensor_params_tab(self) -> QWidget:
        """Create the sensor offset parameters form."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        form = QFormLayout(widget)

        for axis in ["x", "y", "z"]:
            self._add_double_param(
                form, f"accel_offset_{axis}",
                f"加速度计偏移 {axis.upper()} (m/s²)", -10.0, 10.0, 6
            )
            self._add_double_param(
                form, f"gyro_offset_{axis}",
                f"陀螺仪偏移 {axis.upper()} (rad/s)", -1.0, 1.0, 6
            )
            self._add_double_param(
                form, f"mag_offset_{axis}",
                f"磁力计偏移 {axis.upper()}", -1000.0, 1000.0, 2
            )

        # Mounting angle offsets
        self._add_double_param(form, "sensor_roll_offset", "传感器安装滚转偏移 (°)", -180.0, 180.0, 2)
        self._add_double_param(form, "sensor_pitch_offset", "传感器安装俯仰偏移 (°)", -180.0, 180.0, 2)
        self._add_double_param(form, "sensor_yaw_offset", "传感器安装偏航偏移 (°)", -180.0, 180.0, 2)

        scroll.setWidget(widget)
        return scroll

    def _create_notes_tab(self) -> QWidget:
        """Create the notes tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("飞行器备注、特殊配置说明...")
        layout.addWidget(self.notes_edit)
        return widget

    def _add_double_param(self, form: QFormLayout, key: str, label: str,
                          min_val: float, max_val: float, decimals: int):
        """Add a double spin box parameter to the form."""
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setDecimals(decimals)
        spin.setSingleStep(0.1 ** min(decimals, 3))
        self._param_widgets[key] = spin
        form.addRow(label, spin)

    def _add_int_param(self, form: QFormLayout, key: str, label: str,
                       min_val: int, max_val: int):
        """Add an integer spin box parameter to the form."""
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        self._param_widgets[key] = spin
        form.addRow(label, spin)

    def load_vehicle(self, vehicle_id: int):
        """Load a vehicle's configuration into the form."""
        self._vehicle_id = vehicle_id

        with self._db.session_scope() as session:
            vm = VehicleManager(session)
            vehicle = vm.get(vehicle_id)
            if not vehicle:
                self.vehicle_label.setText("飞行器未找到")
                return

            self.vehicle_label.setText(f"{vehicle.name} ({vehicle.frame_type or '未知机架'})")

            # Load configurations for this vehicle
            cm = ConfigurationManager(session)
            configs = cm.list_for_vehicle(vehicle_id)

            self.config_selector.blockSignals(True)
            self.config_selector.clear()
            self.config_selector.addItem("当前参数", None)
            for cfg in configs:
                self.config_selector.addItem(cfg.name, cfg.id)
            self.config_selector.blockSignals(False)

            # Load current params into form
            self._load_params(vehicle.params or {})

    def _load_params(self, params: dict):
        """Load parameter values into form widgets."""
        for key, widget in self._param_widgets.items():
            value = params.get(key, DEFAULT_VEHICLE_PARAMS.get(key, 0))
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value) if value else 0.0)
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value) if value else 0)
        self.notes_edit.setPlainText(params.get("notes", ""))

    def _collect_params(self) -> dict:
        """Collect current parameter values from form widgets."""
        params = {}
        for key, widget in self._param_widgets.items():
            if isinstance(widget, QDoubleSpinBox):
                params[key] = widget.value()
            elif isinstance(widget, QSpinBox):
                params[key] = widget.value()
        params["notes"] = self.notes_edit.toPlainText()
        return params

    def _on_config_changed(self, index: int):
        """Handle configuration selection change."""
        config_id = self.config_selector.currentData()
        if config_id is None:
            # Load vehicle's current params
            if self._vehicle_id:
                with self._db.session_scope() as session:
                    vehicle = VehicleManager(session).get(self._vehicle_id)
                    if vehicle:
                        self._load_params(vehicle.params or {})
            return

        with self._db.session_scope() as session:
            cm = ConfigurationManager(session)
            config = cm.get(config_id)
            if config and config.params:
                self._load_params(config.params)

    def _on_save(self):
        """Save current parameters to the vehicle."""
        if not self._vehicle_id:
            QMessageBox.warning(self, "警告", "请先选择一个飞行器。")
            return

        params = self._collect_params()

        config_id = self.config_selector.currentData()
        if config_id is not None:
            # Update existing configuration
            with self._db.session_scope() as session:
                cm = ConfigurationManager(session)
                config = cm.get(config_id)
                if config:
                    cm.update(config, params=params)
                    QMessageBox.information(self, "保存成功", f"配置 '{config.name}' 已更新。")
        else:
            # Update vehicle's current params
            with self._db.session_scope() as session:
                vm = VehicleManager(session)
                vehicle = vm.get(self._vehicle_id)
                if vehicle:
                    vm.update(vehicle, params=params)
                    QMessageBox.information(self, "保存成功", f"飞行器 '{vehicle.name}' 参数已更新。")

    def _on_save_as_template(self):
        """Save current params as a new named configuration."""
        if not self._vehicle_id:
            QMessageBox.warning(self, "警告", "请先选择一个飞行器。")
            return

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "保存配置", "配置名称:")
        if not ok or not name.strip():
            return

        params = self._collect_params()
        with self._db.session_scope() as session:
            cm = ConfigurationManager(session)
            cm.create(
                vehicle_id=self._vehicle_id,
                name=name.strip(),
                params=params,
                description=self.notes_edit.toPlainText(),
            )

        # Refresh config selector
        self.load_vehicle(self._vehicle_id)
        QMessageBox.information(self, "保存成功", f"配置 '{name}' 已创建。")

    def _on_import_json(self):
        """Import parameters from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "",
            "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                params = json.load(f)
            self._load_params(params)
            QMessageBox.information(self, "导入成功", "参数已从文件加载。请检查并保存。")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"无法读取文件:\n{e}")

    def _on_export_json(self):
        """Export current parameters to a JSON file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "",
            "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not file_path:
            return

        params = self._collect_params()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(params, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "导出成功", f"参数已保存到:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法写入文件:\n{e}")
