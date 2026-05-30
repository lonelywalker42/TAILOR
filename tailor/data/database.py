"""Database session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tailor.core.config import DATABASE_URL
from tailor.data.models import Base


class Database:
    """Manages SQLAlchemy engine and session lifecycle."""

    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url
        self.engine = create_engine(database_url, echo=False, future=True)

        # SQLite pragmas
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_tables(self):
        """Create all tables if they don't exist."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """Drop all tables. Use with caution."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a transactional session scope."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self) -> Session:
        """Get a new session (caller is responsible for closing)."""
        return self.SessionLocal()


# Module-level default database instance
_default_db: Database | None = None


def get_database() -> Database:
    """Get or create the default database instance."""
    global _default_db
    if _default_db is None:
        _default_db = Database()
        _default_db.create_tables()
    return _default_db


def init_database(database_url: str = DATABASE_URL) -> Database:
    """Initialize database with a specific URL (for testing or custom paths)."""
    global _default_db
    _default_db = Database(database_url)
    _default_db.create_tables()
    return _default_db
