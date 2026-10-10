"""
API route handlers for per-feature measurements.
"""

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import FeatureMeasurement, UploadedFile
from app.schemas.measurements import (
    FeatureMeasurementSchema,
    MeasurementQualityReport,
    MeasurementsResponse,
)
from app.services.measurement_service import round_measurement

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["Measurements"])


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(
    file_id: int,
    db: Session = Depends(get_db),
) -> MeasurementsResponse:
    """Retrieve per-feature measurement results for an uploaded file.

    Returns area (m² and hectares) for polygons and length (m and km)
    for LineStrings.  Points and unsupported types return null values with
    an explanatory status field.
    """
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if db_file is None:
        raise HTTPException(status_code=404, detail=f"File with id={file_id} not found.")

    # Retrieve all feature measurements, ordered by index.
    raw_measurements = (
        db.query(FeatureMeasurement)
        .filter(FeatureMeasurement.uploaded_file_id == file_id)
        .order_by(FeatureMeasurement.feature_index)
        .all()
    )

    # Build per-feature response objects with rounded values for presentation.
    features = [
        FeatureMeasurementSchema(
            feature_index=fm.feature_index,
            geometry_type=fm.geometry_type,
            properties=fm.properties,
            area_m2=round_measurement(fm.area_m2, 4),
            area_ha=round_measurement(fm.area_ha, 6),
            length_m=round_measurement(fm.length_m, 4),
            length_km=round_measurement(fm.length_km, 6),
            measurement_crs=fm.measurement_crs,
            status=fm.status,
            warning_message=fm.warning_message,
        )
        for fm in raw_measurements
    ]

    # ── Quality report ────────────────────────────────────────────────────────
    type_counter: Counter = Counter(
        fm.geometry_type or "Unknown" for fm in raw_measurements
    )
    successfully_measured = sum(
        1 for fm in raw_measurements
        if fm.status == "SUCCESS"
        and (fm.area_m2 is not None or fm.length_m is not None)
    )
    unsupported = sum(1 for fm in raw_measurements if fm.status == "UNSUPPORTED")
    invalid_empty = sum(
        1 for fm in raw_measurements
        if fm.status == "FAILED"
        and fm.warning_message
        and ("empty" in fm.warning_message.lower() or "invalid" in fm.warning_message.lower())
    )
    with_warnings = sum(1 for fm in raw_measurements if fm.status == "WARNING")

    total_area = db_file.total_area_m2
    total_length = db_file.total_length_m

    quality_report = MeasurementQualityReport(
        total_features=db_file.feature_count or len(raw_measurements),
        by_geometry_type=dict(type_counter),
        successfully_measured=successfully_measured,
        unsupported_features=unsupported,
        invalid_or_empty_geometries=invalid_empty,
        features_with_warnings=with_warnings,
        total_area_m2=round_measurement(total_area, 4),
        total_length_m=round_measurement(total_length, 4),
    )

    # Determine the primary measurement CRS (most common across features).
    crs_values = [fm.measurement_crs for fm in raw_measurements if fm.measurement_crs]
    primary_measurement_crs = Counter(crs_values).most_common(1)[0][0] if crs_values else None

    return MeasurementsResponse(
        file_id=file_id,
        status=db_file.status,
        source_crs=db_file.source_crs,
        measurement_crs=primary_measurement_crs,
        features=features,
        quality_report=quality_report,
    )
