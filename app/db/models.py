"""
SQLAlchemy ORM models for GeoMeasure.

Schema design decisions
───────────────────────
* Full geometry WKT is NOT stored in FeatureMeasurement.  The assignment API
  contract only requires returning measurement values, geometry type, and
  properties.  Storing full geometry would substantially increase database size
  for large datasets without enabling any additional required query.  If future
  requirements demand spatial querying a PostGIS backend should be adopted.

* Properties are stored as a JSON column (TEXT in SQLite) because feature
  properties are schema-free across different files.

* summary_* columns on UploadedFile are denormalised aggregates computed once
  at the end of processing.  This makes the GET /api/files/{id}/ endpoint a
  single cheap query instead of requiring an aggregating join.

* Timestamps use UTC and are stored as ISO-8601 strings in SQLite (which has
  no native datetime type).  SQLAlchemy's DateTime type handles serialisation.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadedFile(Base):
    """Represents a single uploaded geospatial file and its processing result."""

    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)  # server-side safe name
    source_crs = Column(String(128), nullable=True)         # e.g. "EPSG:4326"
    feature_count = Column(Integer, nullable=True)

    # Lifecycle status: PROCESSING | COMPLETED | COMPLETED_WITH_WARNINGS | FAILED
    status = Column(String(32), nullable=False, default="PROCESSING")

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Human-readable error if status == FAILED
    error_message = Column(Text, nullable=True)

    # Denormalised summary statistics (populated when processing completes)
    success_count = Column(Integer, nullable=True)
    failure_count = Column(Integer, nullable=True)
    warning_count = Column(Integer, nullable=True)

    # Aggregate measurements (null when no supported geometries exist)
    total_area_m2 = Column(Float, nullable=True)
    total_length_m = Column(Float, nullable=True)

    # One-to-many relationship to feature measurements
    feature_measurements = relationship(
        "FeatureMeasurement",
        back_populates="uploaded_file",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<UploadedFile id={self.id} filename={self.filename!r} status={self.status}>"


class FeatureMeasurement(Base):
    """Stores per-feature measurement results for an uploaded file."""

    __tablename__ = "feature_measurements"

    id = Column(Integer, primary_key=True, index=True)
    uploaded_file_id = Column(
        Integer,
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_index = Column(Integer, nullable=False)
    geometry_type = Column(String(64), nullable=True)

    # Feature properties serialised as JSON text (schema-free across files)
    _properties_json = Column("properties", Text, nullable=True)

    # Polygon measurements (null for non-polygon geometries)
    area_m2 = Column(Float, nullable=True)
    area_ha = Column(Float, nullable=True)

    # LineString measurements (null for non-line geometries)
    length_m = Column(Float, nullable=True)
    length_km = Column(Float, nullable=True)

    # The projected CRS actually used for measurement (e.g. "EPSG:32643")
    measurement_crs = Column(String(128), nullable=True)

    # Feature-level status: SUCCESS | WARNING | UNSUPPORTED | FAILED
    status = Column(String(32), nullable=False, default="SUCCESS")

    # Human-readable warning or error for this feature
    warning_message = Column(Text, nullable=True)

    uploaded_file = relationship("UploadedFile", back_populates="feature_measurements")

    # Fast lookup for all measurements belonging to a file, ordered by index.
    __table_args__ = (
        Index("ix_fm_file_index", "uploaded_file_id", "feature_index"),
    )

    @property
    def properties(self) -> dict:
        if self._properties_json:
            return json.loads(self._properties_json)
        return {}

    @properties.setter
    def properties(self, value: dict) -> None:
        self._properties_json = json.dumps(value) if value else None

    def __repr__(self) -> str:
        return (
            f"<FeatureMeasurement id={self.id} "
            f"file_id={self.uploaded_file_id} "
            f"index={self.feature_index} "
            f"type={self.geometry_type}>"
        )
