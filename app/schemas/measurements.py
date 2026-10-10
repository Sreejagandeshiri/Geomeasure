"""
Pydantic schemas for the Measurements API.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FeatureMeasurementSchema(BaseModel):
    """Measurement result for a single geospatial feature."""

    feature_index: int
    geometry_type: Optional[str]
    properties: Optional[dict[str, Any]]

    # Polygon measurements — null for non-polygon geometries
    area_m2: Optional[float] = Field(
        None,
        description="Polygon area in square metres. Null for non-polygon geometries.",
    )
    area_ha: Optional[float] = Field(
        None,
        description="Polygon area in hectares. Null for non-polygon geometries.",
    )

    # Line measurements — null for non-line geometries
    length_m: Optional[float] = Field(
        None,
        description="LineString length in metres. Null for non-line geometries.",
    )
    length_km: Optional[float] = Field(
        None,
        description="LineString length in kilometres. Null for non-line geometries.",
    )

    measurement_crs: Optional[str] = Field(
        None,
        description="The projected CRS used for this feature's measurement.",
    )
    status: str = Field(description="Feature processing status: SUCCESS | WARNING | UNSUPPORTED | FAILED")
    warning_message: Optional[str]

    model_config = {"from_attributes": True}


class MeasurementQualityReport(BaseModel):
    """Quality breakdown of all features in the file."""

    total_features: int
    by_geometry_type: dict[str, int] = Field(
        description="Count of features grouped by geometry type string.",
    )
    successfully_measured: int
    unsupported_features: int
    invalid_or_empty_geometries: int
    features_with_warnings: int
    total_area_m2: Optional[float] = Field(
        None,
        description="Sum of all polygon areas. Null when no polygons present.",
    )
    total_length_m: Optional[float] = Field(
        None,
        description="Sum of all line lengths. Null when no lines present.",
    )


class MeasurementsResponse(BaseModel):
    """Returned by GET /api/files/{id}/measurements/."""

    file_id: int
    status: str
    source_crs: Optional[str]
    measurement_crs: Optional[str] = Field(
        None,
        description="Primary measurement CRS used. Individual features may differ.",
    )
    features: list[FeatureMeasurementSchema]
    quality_report: MeasurementQualityReport
