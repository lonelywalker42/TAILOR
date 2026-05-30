"""Tests for database models and data managers."""

from __future__ import annotations

import pytest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tailor.data.models import Base, Vehicle, FlightLog, Tag, Configuration, AnalysisResult, PIDTuning
from tailor.data.database import Database
from tailor.data.manager import VehicleManager, FlightLogManager, ConfigurationManager


@pytest.fixture
def db(tmp_path):
    """Create an in-memory test database."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    database = Database(db_url)
    database.create_tables()
    yield database


@pytest.fixture
def session(db):
    """Provide a transactional session for tests."""
    with db.session_scope() as session:
        yield session


class TestVehicleManager:
    def test_create_vehicle(self, session):
        mgr = VehicleManager(session)
        v = mgr.create(name="TestDrone", frame_type="quad_x")
        assert v.id is not None
        assert v.name == "TestDrone"
        assert v.frame_type == "quad_x"

    def test_get_by_name(self, session):
        mgr = VehicleManager(session)
        mgr.create(name="MyDrone", frame_type="hexa_x")
        v = mgr.get_by_name("MyDrone")
        assert v is not None
        assert v.frame_type == "hexa_x"

    def test_list_all(self, session):
        mgr = VehicleManager(session)
        mgr.create(name="A", frame_type="quad")
        mgr.create(name="B", frame_type="hexa")
        mgr.create(name="C", frame_type="octo")
        vehicles = mgr.list_all()
        assert len(vehicles) == 3

    def test_update_vehicle(self, session):
        mgr = VehicleManager(session)
        v = mgr.create(name="Drone1", frame_type="quad")
        mgr.update(v, name="Drone1v2", frame_type="tiltrotor")
        assert v.name == "Drone1v2"
        assert v.frame_type == "tiltrotor"

    def test_delete_vehicle(self, session):
        mgr = VehicleManager(session)
        v = mgr.create(name="ToDelete", frame_type="quad")
        vid = v.id
        assert mgr.delete(vid) is True
        assert mgr.get(vid) is None

    def test_delete_nonexistent(self, session):
        mgr = VehicleManager(session)
        assert mgr.delete(9999) is False


class TestFlightLogManager:
    def _create_dummy_ulg(self, tmp_path: Path, name: str = "test.ulg") -> Path:
        """Create a dummy .ulg file for testing."""
        p = tmp_path / name
        p.write_bytes(b"\x00" * 100)  # minimal content
        return p

    def test_import_ulg(self, session, tmp_path):
        p = self._create_dummy_ulg(tmp_path)
        mgr = FlightLogManager(session)
        log = mgr.import_ulg(p)
        assert log.id is not None
        assert log.file_name == "test.ulg"
        assert log.file_size == 100

    def test_import_duplicate(self, session, tmp_path):
        p = self._create_dummy_ulg(tmp_path)
        mgr = FlightLogManager(session)
        log1 = mgr.import_ulg(p)
        log2 = mgr.import_ulg(p)
        assert log1.id == log2.id  # Same record returned

    def test_import_batch(self, session, tmp_path):
        paths = [
            self._create_dummy_ulg(tmp_path, f"log{i}.ulg")
            for i in range(3)
        ]
        mgr = FlightLogManager(session)
        imported, errors = mgr.import_batch(paths)
        assert len(imported) == 3
        assert len(errors) == 0

    def test_import_invalid_extension(self, session, tmp_path):
        p = tmp_path / "bad.txt"
        p.write_bytes(b"data")
        mgr = FlightLogManager(session)
        with pytest.raises(ValueError, match="Unsupported file type"):
            mgr.import_ulg(p)

    def test_search_logs(self, session, tmp_path):
        p = self._create_dummy_ulg(tmp_path, "hover_test.ulg")
        mgr = FlightLogManager(session)
        log = mgr.import_ulg(p)
        mgr.update(log, title="Hover step test")
        results = mgr.search("hover")
        assert len(results) >= 1

    def test_tag_operations(self, session, tmp_path):
        p = self._create_dummy_ulg(tmp_path)
        mgr = FlightLogManager(session)
        log = mgr.import_ulg(p)
        tag = mgr.add_tag(log.id, "悬停测试", color="#FF0000")
        assert tag.name == "悬停测试"
        assert tag in log.tags

        # Adding same tag again should be idempotent
        mgr.add_tag(log.id, "悬停测试")
        assert len(log.tags) == 1

        assert mgr.remove_tag(log.id, "悬停测试") is True
        assert len(log.tags) == 0

    def test_list_with_filters(self, session, tmp_path):
        mgr = FlightLogManager(session)
        for i in range(5):
            p = self._create_dummy_ulg(tmp_path, f"log{i}.ulg")
            log = mgr.import_ulg(p)
            if i < 3:
                mgr.update(log, flight_mode_label="multirotor")
            else:
                mgr.update(log, flight_mode_label="fixedwing")

        multi_logs = mgr.list_all(flight_mode="multirotor")
        fw_logs = mgr.list_all(flight_mode="fixedwing")
        assert len(multi_logs) == 3
        assert len(fw_logs) == 2


class TestConfigurationManager:
    def test_create_config(self, session):
        vm = VehicleManager(session)
        v = vm.create(name="Drone", frame_type="quad")
        cm = ConfigurationManager(session)
        cfg = cm.create(
            vehicle_id=v.id,
            name="Baseline",
            params={"mass": 1.5, "inertia_ixx": 0.01},
        )
        assert cfg.id is not None
        assert cfg.params["mass"] == 1.5

    def test_list_for_vehicle(self, session):
        vm = VehicleManager(session)
        v = vm.create(name="Drone", frame_type="quad")
        cm = ConfigurationManager(session)
        cm.create(vehicle_id=v.id, name="Config1", params={})
        cm.create(vehicle_id=v.id, name="Config2", params={})
        configs = cm.list_for_vehicle(v.id)
        assert len(configs) == 2

    def test_duplicate_as_template(self, session):
        vm = VehicleManager(session)
        v = vm.create(name="Drone", frame_type="quad")
        cm = ConfigurationManager(session)
        cfg = cm.create(vehicle_id=v.id, name="Original", params={"mass": 2.0})
        template = cm.duplicate_as_template(cfg.id, "MyTemplate")
        assert template.is_template is True
        assert template.params["mass"] == 2.0
        assert template.name == "MyTemplate"


class TestTag:
    def test_tag_unique(self, session):
        t1 = Tag(name="test_tag", color="#00FF00")
        t2 = Tag(name="test_tag", color="#FF0000")
        session.add(t1)
        session.flush()
        session.add(t2)
        with pytest.raises(Exception):  # IntegrityError
            session.flush()
