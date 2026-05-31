"""Flight log list and management panel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLineEdit,
    QComboBox,
    QLabel,
    QProgressBar,
    QMessageBox,
    QHeaderView,
    QMenu,
    QInputDialog,
)

from tailor.data.database import Database
from tailor.data.manager import FlightLogManager
from tailor.parser.ulog_parser import extract_metadata_quick


class LogImportWorker(QThread):
    """Background thread for importing .ulg files."""

    progress = Signal(int, int, str)  # current, total, filename
    finished = Signal(list, list)     # imported, errors

    def __init__(self, db: Database, file_paths: list[Path], vehicle_id: Optional[int] = None):
        super().__init__()
        self._db = db
        self._file_paths = file_paths
        self._vehicle_id = vehicle_id

    def run(self):
        imported = []
        errors = []
        total = len(self._file_paths)

        with self._db.session_scope() as session:
            mgr = FlightLogManager(session)
            for i, fp in enumerate(self._file_paths):
                self.progress.emit(i + 1, total, fp.name)
                try:
                    # Extract metadata first
                    metadata = extract_metadata_quick(fp)
                    if "error" in metadata:
                        errors.append((fp, metadata["error"]))
                        continue
                    log = mgr.import_ulg(fp, vehicle_id=self._vehicle_id, metadata=metadata)
                    imported.append(log)
                except Exception as e:
                    errors.append((fp, str(e)))

        self.finished.emit(imported, errors)


class LogPanel(QWidget):
    """Panel displaying the flight log table with filtering and import."""

    log_open_requested = Signal(int)  # Emits log_id when user wants to view a log

    def __init__(self, db: Database):
        super().__init__()
        self._db = db
        self._current_vehicle_id: Optional[int] = None
        self._import_worker: Optional[LogImportWorker] = None
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Filter bar
        filter_layout = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索日志（标题、文件名、备注）...")
        self.search_edit.returnPressed.connect(self.refresh)
        filter_layout.addWidget(self.search_edit)

        self.mode_filter = QComboBox()
        self.mode_filter.addItem("所有模式", "")
        self.mode_filter.addItem("悬停/多旋翼", "multirotor")
        self.mode_filter.addItem("巡航/固定翼", "fixedwing")
        self.mode_filter.addItem("过渡段", "transition")
        self.mode_filter.currentIndexChanged.connect(self.refresh)
        filter_layout.addWidget(QLabel("飞行模式:"))
        filter_layout.addWidget(self.mode_filter)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self.refresh_btn)

        layout.addLayout(filter_layout)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Log table
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "ID", "文件名", "飞行器", "时长(s)", "固件版本",
            "机架", "模式", "标签", "导入时间", "备注"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._on_log_double_clicked)
        layout.addWidget(self.table)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        self.import_btn = QPushButton("导入日志")
        self.import_btn.clicked.connect(self._on_import_clicked)
        btn_layout.addWidget(self.import_btn)

        self.analyze_btn = QPushButton("分析选中日志")
        self.analyze_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 6px 12px; }")
        self.analyze_btn.clicked.connect(self._on_analyze_selected)
        btn_layout.addWidget(self.analyze_btn)

        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        btn_layout.addWidget(self.delete_btn)

        btn_layout.addStretch()
        self.count_label = QLabel("共 0 条日志")
        btn_layout.addWidget(self.count_label)

        layout.addLayout(btn_layout)

    def refresh(self):
        """Reload the log table."""
        search_text = self.search_edit.text().strip()
        mode = self.mode_filter.currentData()

        with self._db.session_scope() as session:
            mgr = FlightLogManager(session)
            if search_text:
                logs = mgr.search(search_text)
            else:
                logs = mgr.list_all(
                    vehicle_id=self._current_vehicle_id,
                    flight_mode=mode if mode else None,
                )

            from tailor.data.manager import VehicleManager
            v_mgr = VehicleManager(session)

            # Build table rows while session is active (lazy loads need session)
            rows = []
            for log in logs:
                vehicle_name = ""
                if log.vehicle_id:
                    v = v_mgr.get(log.vehicle_id)
                    if v:
                        vehicle_name = v.name
                tags_str = ", ".join(t.name for t in log.tags) if log.tags else ""
                rows.append((
                    log.id,
                    log.file_name,
                    vehicle_name,
                    f"{log.duration_s:.1f}",
                    log.firmware_version,
                    log.airframe_type,
                    log.flight_mode_label,
                    tags_str,
                    log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
                    log.notes or "",
                ))

        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))

        self.count_label.setText(f"共 {len(rows)} 条日志")

    def filter_by_vehicle(self, vehicle_id: int):
        """Filter logs by vehicle."""
        self._current_vehicle_id = vehicle_id
        self.refresh()

    def clear_filter(self):
        """Clear vehicle filter."""
        self._current_vehicle_id = None
        self.refresh()

    def import_logs(self, file_paths: list[Path]):
        """Import log files in background thread."""
        if not file_paths:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(file_paths))
        self.progress_bar.setValue(0)
        self.import_btn.setEnabled(False)

        self._import_worker = LogImportWorker(
            self._db, file_paths, self._current_vehicle_id
        )
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.start()

    def _on_import_progress(self, current: int, total: int, filename: str):
        self.progress_bar.setValue(current)
        self.statusBar().showMessage(f"正在导入: {filename} ({current}/{total})")

    def _on_import_finished(self, imported: list, errors: list):
        self.progress_bar.setVisible(False)
        self.import_btn.setEnabled(True)
        self.refresh()

        msg = f"成功导入 {len(imported)} 个日志文件。"
        if errors:
            msg += f"\n{len(errors)} 个文件导入失败："
            for fp, err in errors[:5]:
                msg += f"\n  {fp.name}: {err}"
            if len(errors) > 5:
                msg += f"\n  ...及其他 {len(errors) - 5} 个"

        QMessageBox.information(self, "导入完成", msg)

    def _on_import_clicked(self):
        """Handle import button click."""
        from PySide6.QtWidgets import QFileDialog
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 PX4 日志文件", "",
            "PX4 日志文件 (*.ulg);;所有文件 (*)"
        )
        if file_paths:
            self.import_logs([Path(fp) for fp in file_paths])

    def _on_delete_selected(self):
        """Delete selected log entries."""
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        if not rows:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除选中的 {len(rows)} 条日志吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with self._db.session_scope() as session:
            mgr = FlightLogManager(session)
            for row in rows:
                log_id = int(self.table.item(row, 0).text())
                mgr.delete(log_id)

        self.refresh()

    def _show_context_menu(self, pos):
        """Show context menu for log table."""
        menu = QMenu(self)
        menu.addAction("分析日志", self._on_analyze_selected)
        menu.addAction("查看详情", self._on_view_details)
        menu.addSeparator()
        menu.addAction("添加标签", self._on_add_tag)
        menu.addAction("关联飞行器", self._on_associate_vehicle)
        menu.addSeparator()
        menu.addAction("删除", self._on_delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _get_selected_log_id(self) -> Optional[int]:
        """Get the log_id of the first selected row, or None."""
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        if not rows:
            return None
        row = min(rows)
        id_item = self.table.item(row, 0)
        return int(id_item.text()) if id_item else None

    def _on_view_details(self):
        """Show detailed view of selected log."""
        log_id = self._get_selected_log_id()
        if log_id is None:
            return

        with self._db.session_scope() as session:
            mgr = FlightLogManager(session)
            log = mgr.get(log_id)
            if not log:
                return
            from tailor.data.manager import VehicleManager
            vehicle_name = ""
            if log.vehicle_id:
                v = VehicleManager(session).get(log.vehicle_id)
                if v:
                    vehicle_name = v.name
            tags_str = ", ".join(t.name for t in log.tags) if log.tags else "无"
            file_name = log.file_name
            info = (
                f"文件名: {log.file_name}\n"
                f"飞行器: {vehicle_name or '未关联'}\n"
                f"时长: {log.duration_s:.1f} 秒\n"
                f"固件版本: {log.firmware_version}\n"
                f"机架类型: {log.airframe_type}\n"
                f"飞行模式: {log.flight_mode_label}\n"
                f"消息数: {log.message_count}\n"
                f"丢包率: {log.drop_rate:.4f}\n"
                f"标签: {tags_str}\n"
                f"导入时间: {log.created_at}\n"
                f"文件路径: {log.file_path}\n"
                f"备注: {log.notes or '无'}"
            )

        QMessageBox.information(self, f"日志详情 — {file_name}", info)

    def _on_add_tag(self):
        """Add tag to selected log."""
        log_id = self._get_selected_log_id()
        if log_id is None:
            return

        tag_name, ok = QInputDialog.getText(self, "添加标签", "标签名称:")
        if not ok or not tag_name.strip():
            return

        with self._db.session_scope() as session:
            FlightLogManager(session).add_tag(log_id, tag_name.strip())

        self.refresh()

    def _on_associate_vehicle(self):
        """Associate selected log with a vehicle."""
        log_id = self._get_selected_log_id()
        if log_id is None:
            return

        with self._db.session_scope() as session:
            from tailor.data.manager import VehicleManager
            vehicles = VehicleManager(session).list_all()
            if not vehicles:
                QMessageBox.information(self, "无飞行器", "请先创建一个飞行器。")
                return
            vehicle_names = [v.name for v in vehicles]
            vehicle_ids = [v.id for v in vehicles]

        name, ok = QInputDialog.getItem(self, "关联飞行器", "选择飞行器:", vehicle_names, 0, False)
        if not ok:
            return

        vid = vehicle_ids[vehicle_names.index(name)]
        with self._db.session_scope() as session:
            log = FlightLogManager(session).get(log_id)
            if log:
                log.vehicle_id = vid

        self.refresh()

    def _on_log_double_clicked(self, index):
        """Handle double-click on a log entry — open in viewer."""
        row = index.row()
        id_item = self.table.item(row, 0)
        if id_item:
            log_id = int(id_item.text())
            self.log_open_requested.emit(log_id)

    def _on_analyze_selected(self):
        """Analyze the selected log entry."""
        log_id = self._get_selected_log_id()
        if log_id is None:
            QMessageBox.information(self, "提示", "请先选择一条日志。")
            return
        self.log_open_requested.emit(log_id)

    def statusBar(self):
        """Get the main window status bar."""
        parent = self.window()
        if hasattr(parent, 'statusBar'):
            return parent.statusBar()
        return None
