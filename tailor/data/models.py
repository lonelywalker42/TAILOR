"""SQLAlchemy ORM models for TAILOR data management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    create_engine,
    event,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, Session


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# Association table for log <-> tag many-to-many
from sqlalchemy import Table

log_tags = Table(
    "log_tags",
    Base.metadata,
    Column("log_id", Integer, ForeignKey("flight_logs.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Vehicle(Base):
    """A physical aircraft with its configuration parameters."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    frame_type: Mapped[str] = mapped_column(String(64), default="")  # quad_x, tiltrotor, etc.
    firmware_version: Mapped[str] = mapped_column(String(32), default="")
    num_motors: Mapped[int] = mapped_column(Integer, default=4)
    num_servos: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Physical parameters (stored as JSON for flexibility)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)

    # Relationships
    logs: Mapped[list["FlightLog"]] = relationship("FlightLog", back_populates="vehicle", cascade="all, delete-orphan")
    configurations: Mapped[list["Configuration"]] = relationship("Configuration", back_populates="vehicle", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} name='{self.name}' frame='{self.frame_type}'>"


class Configuration(Base):
    """A named set of vehicle parameters (template or snapshot)."""

    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Full parameter snapshot as JSON
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="configurations")

    def __repr__(self) -> str:
        return f"<Configuration id={self.id} name='{self.name}' vehicle_id={self.vehicle_id}>"


class FlightLog(Base):
    """A single PX4 .ulg flight log file."""

    __tablename__ = "flight_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_hash: Mapped[str] = mapped_column(String(64), default="")  # SHA-256

    # Metadata extracted from .ulg
    firmware_version: Mapped[str] = mapped_column(String(32), default="")
    airframe_type: Mapped[str] = mapped_column(String(64), default="")
    airframe_name: Mapped[str] = mapped_column(String(128), default="")
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    drop_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # User annotations
    title: Mapped[str] = mapped_column(String(256), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    flight_mode_label: Mapped[str] = mapped_column(String(64), default="")  # hover, cruise, transition
    fault_label: Mapped[str] = mapped_column(String(128), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    vehicle: Mapped[Optional["Vehicle"]] = relationship("Vehicle", back_populates="logs")
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=log_tags, back_populates="logs")
    analysis_results: Mapped[list["AnalysisResult"]] = relationship("AnalysisResult", back_populates="log", cascade="all, delete-orphan")
    pid_tunings: Mapped[list["PIDTuning"]] = relationship("PIDTuning", back_populates="log", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<FlightLog id={self.id} file='{self.file_name}' duration={self.duration_s:.1f}s>"


class Tag(Base):
    """User-defined tag for labeling logs."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(7), default="#4A90D9")  # hex color

    logs: Mapped[list["FlightLog"]] = relationship("FlightLog", secondary=log_tags, back_populates="tags")

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name='{self.name}'>"


class AnalysisResult(Base):
    """System identification / analysis result stored in DB."""

    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(Integer, ForeignKey("flight_logs.id", ondelete="CASCADE"), nullable=False)
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)  # 'transfer_function', 'step_response', etc.
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    flight_phase: Mapped[str] = mapped_column(String(32), default="")  # multirotor, fixedwing, transition

    # Input/output channel info
    input_channel: Mapped[str] = mapped_column(String(128), default="")
    output_channel: Mapped[str] = mapped_column(String(128), default="")
    input_coord_frame: Mapped[str] = mapped_column(String(32), default="frd")
    output_coord_frame: Mapped[str] = mapped_column(String(32), default="frd")

    # Model data (JSON-serialized transfer function coefficients, etc.)
    model_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)

    # Performance metrics
    fit_percent: Mapped[float] = mapped_column(Float, default=0.0)  # VAF
    bandwidth_hz: Mapped[float] = mapped_column(Float, default=0.0)
    phase_margin_deg: Mapped[float] = mapped_column(Float, default=0.0)
    gain_margin_db: Mapped[float] = mapped_column(Float, default=0.0)
    overshoot_pct: Mapped[float] = mapped_column(Float, default=0.0)
    rise_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    settling_time_s: Mapped[float] = mapped_column(Float, default=0.0)

    # Time segment used
    t_start: Mapped[float] = mapped_column(Float, default=0.0)
    t_end: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    log: Mapped["FlightLog"] = relationship("FlightLog", back_populates="analysis_results")

    def __repr__(self) -> str:
        return f"<AnalysisResult id={self.id} type='{self.result_type}' log_id={self.log_id}>"


class PIDTuning(Base):
    """PID tuning iteration record."""

    __tablename__ = "pid_tunings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("flight_logs.id", ondelete="SET NULL"), nullable=True)
    analysis_result_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("analysis_results.id", ondelete="SET NULL"), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    flight_phase: Mapped[str] = mapped_column(String(32), default="")  # multirotor, fixedwing

    # PID parameters as JSON: {"roll_rate": {"kp": 0.1, "ki": 0.05, "kd": 0.01, "ff": 0.0}, ...}
    pid_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)

    # Performance before/after
    before_bandwidth_hz: Mapped[float] = mapped_column(Float, default=0.0)
    before_phase_margin_deg: Mapped[float] = mapped_column(Float, default=0.0)
    before_overshoot_pct: Mapped[float] = mapped_column(Float, default=0.0)
    after_bandwidth_hz: Mapped[float] = mapped_column(Float, default=0.0)
    after_phase_margin_deg: Mapped[float] = mapped_column(Float, default=0.0)
    after_overshoot_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # Optimization method
    method: Mapped[str] = mapped_column(String(64), default="manual")  # manual, ziegler_nichols, simc, optimizer

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    log: Mapped[Optional["FlightLog"]] = relationship("FlightLog", back_populates="pid_tunings")
    analysis_result: Mapped[Optional["AnalysisResult"]] = relationship("AnalysisResult")

    def __repr__(self) -> str:
        return f"<PIDTuning id={self.id} iteration={self.iteration} method='{self.method}'>"


def create_engine_and_tables(database_url: str):
    """Create engine and initialize all tables."""
    engine = create_engine(database_url, echo=False)
    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine
