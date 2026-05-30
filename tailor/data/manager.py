"""Data managers for vehicles, logs, and configurations."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from tailor.data.database import get_database
from tailor.data.models import Vehicle, FlightLog, Configuration, Tag, AnalysisResult, PIDTuning


class VehicleManager:
    """CRUD operations for Vehicle entities."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, name: str, frame_type: str = "", description: str = "", **kwargs) -> Vehicle:
        vehicle = Vehicle(
            name=name,
            frame_type=frame_type,
            description=description,
            firmware_version=kwargs.get("firmware_version", ""),
            num_motors=kwargs.get("num_motors", 4),
            num_servos=kwargs.get("num_servos", 0),
            params=kwargs.get("params", {}),
        )
        self.session.add(vehicle)
        self.session.flush()
        return vehicle

    def get(self, vehicle_id: int) -> Optional[Vehicle]:
        return self.session.get(Vehicle, vehicle_id)

    def get_by_name(self, name: str) -> Optional[Vehicle]:
        return self.session.query(Vehicle).filter(Vehicle.name == name).first()

    def list_all(self) -> list[Vehicle]:
        return self.session.query(Vehicle).order_by(Vehicle.name).all()

    def update(self, vehicle: Vehicle, **kwargs) -> Vehicle:
        for key, value in kwargs.items():
            if hasattr(vehicle, key):
                setattr(vehicle, key, value)
        vehicle.updated_at = datetime.utcnow()
        self.session.flush()
        return vehicle

    def delete(self, vehicle_id: int) -> bool:
        vehicle = self.get(vehicle_id)
        if vehicle:
            self.session.delete(vehicle)
            self.session.flush()
            return True
        return False


class FlightLogManager:
    """CRUD and import operations for FlightLog entities."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def import_ulg(
        self,
        file_path: Path,
        vehicle_id: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> FlightLog:
        """Import a .ulg file, creating a FlightLog record.

        Args:
            file_path: Path to the .ulg file.
            vehicle_id: Optional vehicle to associate with.
            metadata: Pre-extracted metadata dict (from UlogParser).

        Returns:
            The created FlightLog instance.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if file_path.suffix.lower() not in (".ulg",):
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        file_hash = self.compute_file_hash(file_path)

        # Check for duplicate
        existing = self.session.query(FlightLog).filter(FlightLog.file_hash == file_hash).first()
        if existing:
            return existing  # Already imported

        meta = metadata or {}
        log = FlightLog(
            vehicle_id=vehicle_id,
            file_path=str(file_path.resolve()),
            file_name=file_path.name,
            file_size=file_path.stat().st_size,
            file_hash=file_hash,
            firmware_version=meta.get("firmware_version", ""),
            airframe_type=str(meta.get("airframe_type", "")),
            airframe_name=meta.get("airframe_name", ""),
            duration_s=meta.get("duration_s", 0.0),
            start_time=meta.get("start_time"),
            end_time=meta.get("end_time"),
            message_count=meta.get("message_count", 0),
            drop_rate=meta.get("drop_rate", 0.0),
        )
        self.session.add(log)
        self.session.flush()
        return log

    def import_batch(
        self,
        file_paths: list[Path],
        vehicle_id: Optional[int] = None,
    ) -> tuple[list[FlightLog], list[tuple[Path, str]]]:
        """Import multiple .ulg files.

        Returns:
            (imported_logs, errors) where errors is list of (path, error_message).
        """
        imported = []
        errors = []
        for fp in file_paths:
            try:
                log = self.import_ulg(fp, vehicle_id=vehicle_id)
                imported.append(log)
            except Exception as e:
                errors.append((fp, str(e)))
        return imported, errors

    def get(self, log_id: int) -> Optional[FlightLog]:
        return self.session.get(FlightLog, log_id)

    def list_all(
        self,
        vehicle_id: Optional[int] = None,
        tag_name: Optional[str] = None,
        flight_mode: Optional[str] = None,
        limit: int = 500,
    ) -> list[FlightLog]:
        """List logs with optional filters."""
        q = self.session.query(FlightLog)
        if vehicle_id is not None:
            q = q.filter(FlightLog.vehicle_id == vehicle_id)
        if flight_mode:
            q = q.filter(FlightLog.flight_mode_label == flight_mode)
        if tag_name:
            q = q.join(FlightLog.tags).filter(Tag.name == tag_name)
        return q.order_by(FlightLog.created_at.desc()).limit(limit).all()

    def search(self, query: str) -> list[FlightLog]:
        """Free-text search across log title, notes, file name."""
        pattern = f"%{query}%"
        return (
            self.session.query(FlightLog)
            .filter(
                or_(
                    FlightLog.title.ilike(pattern),
                    FlightLog.notes.ilike(pattern),
                    FlightLog.file_name.ilike(pattern),
                )
            )
            .order_by(FlightLog.created_at.desc())
            .all()
        )

    def update(self, log: FlightLog, **kwargs) -> FlightLog:
        for key, value in kwargs.items():
            if hasattr(log, key):
                setattr(log, key, value)
        self.session.flush()
        return log

    def delete(self, log_id: int) -> bool:
        log = self.get(log_id)
        if log:
            self.session.delete(log)
            self.session.flush()
            return True
        return False

    def add_tag(self, log_id: int, tag_name: str, color: str = "#4A90D9") -> Tag:
        """Add a tag to a log, creating the tag if needed."""
        log = self.get(log_id)
        if not log:
            raise ValueError(f"Log {log_id} not found")
        tag = self.session.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name, color=color)
            self.session.add(tag)
            self.session.flush()
        if tag not in log.tags:
            log.tags.append(tag)
            self.session.flush()
        return tag

    def remove_tag(self, log_id: int, tag_name: str) -> bool:
        log = self.get(log_id)
        if not log:
            return False
        tag = self.session.query(Tag).filter(Tag.name == tag_name).first()
        if tag and tag in log.tags:
            log.tags.remove(tag)
            self.session.flush()
            return True
        return False


class ConfigurationManager:
    """CRUD for vehicle configuration records."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        vehicle_id: int,
        name: str,
        params: dict,
        description: str = "",
        is_template: bool = False,
    ) -> Configuration:
        config = Configuration(
            vehicle_id=vehicle_id,
            name=name,
            params=params,
            description=description,
            is_template=is_template,
        )
        self.session.add(config)
        self.session.flush()
        return config

    def get(self, config_id: int) -> Optional[Configuration]:
        return self.session.get(Configuration, config_id)

    def list_for_vehicle(self, vehicle_id: int) -> list[Configuration]:
        return (
            self.session.query(Configuration)
            .filter(Configuration.vehicle_id == vehicle_id)
            .order_by(Configuration.created_at.desc())
            .all()
        )

    def list_templates(self) -> list[Configuration]:
        return (
            self.session.query(Configuration)
            .filter(Configuration.is_template == True)
            .order_by(Configuration.name)
            .all()
        )

    def update(self, config: Configuration, **kwargs) -> Configuration:
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        self.session.flush()
        return config

    def delete(self, config_id: int) -> bool:
        config = self.get(config_id)
        if config:
            self.session.delete(config)
            self.session.flush()
            return True
        return False

    def duplicate_as_template(self, config_id: int, template_name: str) -> Configuration:
        """Create a template from an existing configuration."""
        original = self.get(config_id)
        if not original:
            raise ValueError(f"Configuration {config_id} not found")
        return self.create(
            vehicle_id=original.vehicle_id,
            name=template_name,
            params=dict(original.params) if original.params else {},
            description=f"Template from: {original.name}",
            is_template=True,
        )
