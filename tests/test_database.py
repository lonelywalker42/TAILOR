"""Tests for database setup and session management."""

from __future__ import annotations

import pytest
from pathlib import Path

from sqlalchemy import inspect

from tailor.data.database import Database
from tailor.data.models import Base, Vehicle, FlightLog


class TestDatabase:
    def test_create_tables(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'test.db'}")
        db.create_tables()
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        assert "vehicles" in tables
        assert "flight_logs" in tables
        assert "tags" in tables
        assert "configurations" in tables
        assert "analysis_results" in tables
        assert "pid_tunings" in tables

    def test_session_scope_commit(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'test.db'}")
        db.create_tables()
        with db.session_scope() as session:
            v = Vehicle(name="Test", frame_type="quad")
            session.add(v)

        # Verify commit happened
        with db.session_scope() as session:
            vehicles = session.query(Vehicle).all()
            assert len(vehicles) == 1
            assert vehicles[0].name == "Test"

    def test_session_scope_rollback(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'test.db'}")
        db.create_tables()
        with pytest.raises(ValueError):
            with db.session_scope() as session:
                v = Vehicle(name="Test", frame_type="quad")
                session.add(v)
                raise ValueError("forced error")

        # Verify rollback happened
        with db.session_scope() as session:
            vehicles = session.query(Vehicle).all()
            assert len(vehicles) == 0

    def test_wal_mode(self, tmp_path):
        db = Database(f"sqlite:///{tmp_path / 'test.db'}")
        db.create_tables()
        with db.engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode").fetchone()
            assert result[0] == "wal"
