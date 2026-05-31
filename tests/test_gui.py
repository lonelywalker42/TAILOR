"""GUI smoke tests — verify widget instantiation and basic state.

These tests ensure all UI panels can be created without errors.
They do not test complex interactions (those require a running event loop).
"""

from __future__ import annotations

import pytest

# Skip all tests if PySide6 is not available or no display
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def db_session(qapp, tmp_path):
    """Create a temporary database for UI tests."""
    from tailor.data.database import Database
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


class TestMainWindow:
    """Smoke test for MainWindow."""

    def test_import(self):
        """MainWindow can be imported."""
        from tailor.ui.main_window import MainWindow
        assert MainWindow is not None

    def test_instantiate(self, qapp, db_session, monkeypatch):
        """MainWindow can be instantiated."""
        from tailor.ui.main_window import MainWindow
        # Patch get_database to use test db
        monkeypatch.setattr("tailor.ui.main_window.get_database", lambda: db_session)
        window = MainWindow()
        assert window is not None
        assert window.windowTitle() != ""
        window.close()


class TestVehiclePanel:
    """Smoke test for VehiclePanel."""

    def test_import(self):
        from tailor.ui.vehicle_panel import VehiclePanel
        assert VehiclePanel is not None

    def test_instantiate(self, qapp, db_session):
        from tailor.ui.vehicle_panel import VehiclePanel
        panel = VehiclePanel(db_session)
        assert panel is not None
        panel.close()


class TestLogPanel:
    """Smoke test for LogPanel."""

    def test_import(self):
        from tailor.ui.log_panel import LogPanel
        assert LogPanel is not None

    def test_instantiate(self, qapp, db_session):
        from tailor.ui.log_panel import LogPanel
        panel = LogPanel(db_session)
        assert panel is not None
        panel.close()


class TestConfigurationPanel:
    """Smoke test for ConfigurationPanel."""

    def test_import(self):
        from tailor.ui.config_panel import ConfigurationPanel
        assert ConfigurationPanel is not None

    def test_instantiate(self, qapp, db_session):
        from tailor.ui.config_panel import ConfigurationPanel
        panel = ConfigurationPanel(db_session)
        assert panel is not None
        panel.close()


class TestLogViewer:
    """Smoke test for LogViewerWidget."""

    def test_import(self):
        from tailor.ui.log_viewer import LogViewerWidget
        assert LogViewerWidget is not None

    def test_instantiate(self, qapp):
        from tailor.ui.log_viewer import LogViewerWidget
        widget = LogViewerWidget()
        assert widget is not None
        widget.close()


class TestIdentPanel:
    """Smoke test for IdentPanel."""

    def test_import(self):
        from tailor.ui.ident_panel import IdentPanel
        assert IdentPanel is not None

    def test_instantiate(self, qapp):
        from tailor.ui.ident_panel import IdentPanel
        panel = IdentPanel()
        assert panel is not None
        panel.close()


class TestPIDPanel:
    """Smoke test for PIDPanel."""

    def test_import(self):
        from tailor.ui.pid_panel import PIDPanel
        assert PIDPanel is not None

    def test_instantiate(self, qapp):
        from tailor.ui.pid_panel import PIDPanel
        panel = PIDPanel()
        assert panel is not None
        panel.close()

    def test_default_gains(self, qapp):
        """PIDPanel loads default gains correctly."""
        from tailor.ui.pid_panel import PIDPanel
        panel = PIDPanel()
        panel._load_defaults()
        assert panel.kp_spin.value() >= 0
        assert panel.ki_spin.value() >= 0
        panel.close()


class TestUIImports:
    """Verify all UI modules import cleanly."""

    def test_import_main_window(self):
        from tailor.ui import main_window
        assert main_window is not None

    def test_import_vehicle_panel(self):
        from tailor.ui import vehicle_panel
        assert vehicle_panel is not None

    def test_import_log_panel(self):
        from tailor.ui import log_panel
        assert log_panel is not None

    def test_import_config_panel(self):
        from tailor.ui import config_panel
        assert config_panel is not None

    def test_import_log_viewer(self):
        from tailor.ui import log_viewer
        assert log_viewer is not None

    def test_import_ident_panel(self):
        from tailor.ui import ident_panel
        assert ident_panel is not None

    def test_import_pid_panel(self):
        from tailor.ui import pid_panel
        assert pid_panel is not None
