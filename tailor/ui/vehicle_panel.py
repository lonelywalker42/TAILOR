"""Vehicle list panel for the left sidebar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QInputDialog,
    QMessageBox,
    QLabel,
    QComboBox,
    QLineEdit,
)

from tailor.data.database import Database
from tailor.data.manager import VehicleManager


class VehiclePanel(QWidget):
    """Left-side panel showing the list of registered vehicles."""

    vehicle_selected = Signal(int)  # Emits vehicle_id when selected

    def __init__(self, db: Database):
        super().__init__()
        self._db = db
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Search/filter
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索飞行器...")
        self.search_edit.textChanged.connect(self._on_search)
        layout.addWidget(self.search_edit)

        # Vehicle list
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_widget)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.add_btn.clicked.connect(self.create_vehicle_dialog)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("编辑")
        self.edit_btn.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.edit_btn)

        self.del_btn = QPushButton("删除")
        self.del_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.del_btn)

        layout.addLayout(btn_layout)

    def refresh(self):
        """Reload vehicle list from database."""
        self.list_widget.clear()
        with self._db.session_scope() as session:
            mgr = VehicleManager(session)
            vehicles = mgr.list_all()
            for v in vehicles:
                item = QListWidgetItem(f"{v.name} ({v.frame_type or '未知'})")
                item.setData(Qt.ItemDataRole.UserRole, v.id)
                self.list_widget.addItem(item)

    def _on_search(self, text: str):
        """Filter the vehicle list."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _on_item_changed(self, current: QListWidgetItem, _previous):
        """Emit signal when a vehicle is selected."""
        if current:
            vehicle_id = current.data(Qt.ItemDataRole.UserRole)
            self.vehicle_selected.emit(vehicle_id)

    def _get_selected_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def create_vehicle_dialog(self):
        """Show dialog to create a new vehicle."""
        name, ok = QInputDialog.getText(self, "新建飞行器", "飞行器名称:")
        if not ok or not name.strip():
            return

        frame_type, ok = QInputDialog.getItem(
            self, "机架类型", "选择机架类型:",
            ["quad_x", "hexa_x", "octo_x", "tiltrotor", "tailsitter", "vtol", "custom"],
            editable=True,
        )
        if not ok:
            return

        with self._db.session_scope() as session:
            mgr = VehicleManager(session)
            existing = mgr.get_by_name(name.strip())
            if existing:
                QMessageBox.warning(self, "重复", f"飞行器 '{name}' 已存在。")
                return
            mgr.create(name=name.strip(), frame_type=frame_type)

        self.refresh()

    def _on_edit(self):
        """Edit the selected vehicle."""
        vid = self._get_selected_id()
        if vid is None:
            QMessageBox.information(self, "提示", "请先选择一个飞行器。")
            return

        with self._db.session_scope() as session:
            mgr = VehicleManager(session)
            vehicle = mgr.get(vid)
            if not vehicle:
                return
            name, ok = QInputDialog.getText(self, "编辑飞行器", "飞行器名称:", text=vehicle.name)
            if ok and name.strip():
                mgr.update(vehicle, name=name.strip())

        self.refresh()

    def _on_delete(self):
        """Delete the selected vehicle after confirmation."""
        vid = self._get_selected_id()
        if vid is None:
            QMessageBox.information(self, "提示", "请先选择一个飞行器。")
            return

        with self._db.session_scope() as session:
            mgr = VehicleManager(session)
            vehicle = mgr.get(vid)
            if not vehicle:
                return
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除飞行器 '{vehicle.name}' 及其所有关联数据吗？\n此操作不可撤销。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                mgr.delete(vid)

        self.refresh()
