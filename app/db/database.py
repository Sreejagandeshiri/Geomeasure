"""
SQLAlchemy database engine and session management.

We use SQLite for simplicity and portability.  The connection string can be
changed to any SQLAlchemy-supported database via the DATABASE_URL environment
variable without touching application code.

Design note: We store uploaded files in the filesystem and persist only
metadata and measurement results in the database.  This keeps the database
lean while still allowing the API to answer all required queries without
re-reading uploaded files.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

# check_same_thread=False is required for SQLite when used with FastAPI
# because multiple threads share a single connection pool.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a database session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all tables defined in the ORM models (idempotent)."""
    # Import models so that SQLAlchemy registers them on the metadata.
    import app.db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
