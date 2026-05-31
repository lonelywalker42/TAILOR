"""Main application window for TAILOR."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStatusBar,
    QMenuBar,
    QMenu,
    QToolBar,
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QMessageBox,
    QFileDialog,
    QLabel,
    QDockWidget,
    QPushButton,
)

from tailor import __app_name__, __version__
from tailor.data.database import get_database
from tailor.data.models import FlightLog
from tailor.data.manager import VehicleManager, FlightLogManager
from tailor.ui.vehicle_panel import VehiclePanel
from tailor.ui.log_panel import LogPanel
from tailor.ui.config_panel import ConfigurationPanel
from tailor.ui.log_viewer import LogViewerWidget
from tailor.ui.ident_panel import IdentPanel
from tailor.ui.pid_panel import PIDPanel


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} — PX4 Flight Log Analysis Platform")
        self.setMinimumSize(QSize(1200, 800))
        self.resize(1600, 1000)

        self._db = get_database()

        self._setup_menus()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_docks()
        self._setup_statusbar()

    def _setup_menus(self):
        """Create the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("文件(&F)")

        import_action = QAction("导入日志(&I)...", self)
        import_action.setShortcut(QKeySequence("Ctrl+I"))
        import_action.setStatusTip("导入 PX4 .ulg 飞行日志文件")
        import_action.triggered.connect(self._on_import_logs)
        file_menu.addAction(import_action)

        import_batch_action = QAction("批量导入(&B)...", self)
        import_batch_action.setStatusTip("批量导入多个 .ulg 文件")
        import_batch_action.triggered.connect(self._on_import_batch)
        file_menu.addAction(import_batch_action)

        file_menu.addSeparator()

        export_action = QAction("导出数据(&E)...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.setStatusTip("导出当前数据为 CSV/MAT/Parquet")
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("退出(&Q)", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # View menu
        view_menu = menubar.addMenu("视图(&V)")

        # Tools menu
        tools_menu = menubar.addMenu("工具(&T)")

        # Help menu
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        """Create the main toolbar."""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        toolbar.addAction("导入日志", self._on_import_logs)
        toolbar.addAction("新建飞行器", self._on_new_vehicle)
        toolbar.addSeparator()

    def _setup_central_widget(self):
        """Create the central tab widget."""
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.setCentralWidget(self.tab_widget)

        # Log table tab
        self.log_panel = LogPanel(self._db)
        self.log_panel.log_open_requested.connect(self._on_open_log)
        self.tab_widget.addTab(self.log_panel, "飞行日志")

        # Log viewer / analysis tab
        self.log_viewer = LogViewerWidget()
        self.tab_widget.addTab(self.log_viewer, "日志分析")

        # System identification tab
        self.ident_panel = IdentPanel()
        self.tab_widget.addTab(self.ident_panel, "系统辨识")

        # PID tuning tab
        self.pid_panel = PIDPanel()
        self.tab_widget.addTab(self.pid_panel, "PID 调参")

        # Report tab
        report_widget = QWidget()
        report_layout = QVBoxLayout(report_widget)
        report_layout.addWidget(QLabel("一键生成分析报告（飞行信息 + 图表 + 辨识结果 + 调参对比）"))
        self.gen_report_btn = QPushButton("生成 HTML 报告")
        self.gen_report_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 10px; font-size: 14px; }")
        self.gen_report_btn.clicked.connect(self._on_generate_report)
        report_layout.addWidget(self.gen_report_btn)
        report_layout.addStretch()
        self.tab_widget.addTab(report_widget, "报告")

    def _setup_docks(self):
        """Create dockable panels."""
        # Vehicle panel (left dock)
        vehicle_dock = QDockWidget("飞行器列表", self)
        vehicle_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.vehicle_panel = VehiclePanel(self._db)
        vehicle_dock.setWidget(self.vehicle_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, vehicle_dock)

        # Configuration panel (bottom dock)
        config_dock = QDockWidget("配置与参数", self)
        config_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.config_panel = ConfigurationPanel(self._db)
        config_dock.setWidget(self.config_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, config_dock)

        # Connect vehicle selection to config panel
        self.vehicle_panel.vehicle_selected.connect(self._on_vehicle_selected)

    def _setup_statusbar(self):
        """Create the status bar."""
        status = QStatusBar()
        self.setStatusBar(status)
        status.showMessage("就绪")

    def _on_import_logs(self):
        """Open file dialog to import a single .ulg file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 PX4 日志文件", "",
            "PX4 日志文件 (*.ulg);;所有文件 (*)"
        )
        if file_path:
            self._import_single_log(Path(file_path))

    def _on_import_batch(self):
        """Open file dialog to import multiple .ulg files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "批量选择 PX4 日志文件", "",
            "PX4 日志文件 (*.ulg);;所有文件 (*)"
        )
        if file_paths:
            paths = [Path(fp) for fp in file_paths]
            self.log_panel.import_logs(paths)

    def _import_single_log(self, path: Path):
        """Import a single log file."""
        self.log_panel.import_logs([path])

    def _on_new_vehicle(self):
        """Open dialog to create a new vehicle."""
        self.vehicle_panel.create_vehicle_dialog()

    def _on_vehicle_selected(self, vehicle_id: int):
        """Handle vehicle selection from the vehicle panel."""
        self.config_panel.load_vehicle(vehicle_id)
        self.log_panel.filter_by_vehicle(vehicle_id)
        self.statusBar().showMessage(f"已选择飞行器 ID: {vehicle_id}")

    def _on_open_log(self, log_id: int):
        """Open a log in the viewer for analysis."""
        from tailor.parser.ulog_parser import UlogParser

        with self._db.session_scope() as session:
            log = session.get(FlightLog, log_id)
            if not log:
                self.statusBar().showMessage(f"日志 ID {log_id} 未找到")
                return
            file_path = log.file_path
            file_name = log.file_name

        if not Path(file_path).exists():
            self.statusBar().showMessage(f"文件不存在: {file_path}")
            QMessageBox.warning(self, "文件缺失", f"日志文件不存在:\n{file_path}\n\n可能文件已被移动或删除。")
            return

        self.statusBar().showMessage(f"正在解析 {file_name}...")
        try:
            parser = UlogParser(Path(file_path))
            parser.open()

            raw_data = parser.get_core_data()
            available = parser.get_available_messages()
            message_fields = {}
            for msg_name in available:
                try:
                    df = parser.get_message_data(msg_name)
                    if not df.empty:
                        message_fields[msg_name] = list(df.columns)
                except Exception:
                    pass

            segments = parser.get_flight_mode_segments()

            # Load into viewer
            self.log_viewer.load_data(raw_data, available, message_fields, segments)

            # Load into identification panel (pass flattened 1D arrays)
            flat_data = {}
            for msg_name, df in raw_data.items():
                if "instance" in df.columns:
                    df = df[df["instance"] == 0]
                for col in df.columns:
                    if col in ("timestamp", "timestamp_s", "instance"):
                        continue
                    flat_data[f"{msg_name}.{col}"] = df[col].values
            self.ident_panel.load_data(flat_data)

            self.tab_widget.setCurrentWidget(self.log_viewer)
            self.statusBar().showMessage(
                f"已加载: {file_name} | {len(raw_data)} 种核心消息, "
                f"{len(message_fields)} 种可用消息, {len(segments)} 个飞行模式段"
            )

        except Exception as e:
            self.statusBar().showMessage(f"解析失败: {e}")
            QMessageBox.warning(self, "解析错误", f"无法解析日志文件:\n{e}")

    def _on_generate_report(self):
        """Generate an HTML analysis report."""
        from PySide6.QtWidgets import QFileDialog
        from tailor.control.report import ReportGenerator

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存报告", "",
            "HTML 文件 (*.html);;所有文件 (*)"
        )
        if not file_path:
            return

        self.statusBar().showMessage("正在生成报告...")
        try:
            gen = ReportGenerator(__version__)
            html = gen.generate_html(
                title="TAILOR 飞行分析报告",
                flight_info={"状态": "就绪", "版本": __version__},
                key_metrics=[{"label": "模块", "value": "5/5 完成"}],
                recommendations=["所有核心模块已实现，可进行端到端分析"],
                output_path=Path(file_path),
            )
            self.statusBar().showMessage(f"报告已生成: {file_path}")
            QMessageBox.information(self, "报告生成", f"报告已保存到:\n{file_path}")
        except Exception as e:
            self.statusBar().showMessage(f"报告生成失败: {e}")
            QMessageBox.warning(self, "错误", f"报告生成失败:\n{e}")

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            f"关于 {__app_name__}",
            f"<h2>{__app_name__}</h2>"
            f"<p>Tail-sitter Analysis, Identification, Log & Optimization Resource</p>"
            f"<p>版本: {__version__}</p>"
            f"<p>PX4 尾座式飞行器日志分析与 PID 调参平台</p>"
            f"<p>基于 pyulog · PySide6 · SciPy · python-control</p>",
        )
