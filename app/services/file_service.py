"""
File processing service: orchestrates the full upload-to-measurement pipeline.

This is the high-level coordinator:
  1. Validate → 2. Save → 3. Parse → 4. Measure → 5. Persist

It intentionally contains no geospatial math; that lives in the dedicated
measurement_service and crs_service modules.  Database interaction is handled
here because the service owns the processing lifecycle.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from app.core.exceptions import (
    CorruptFileError,
    CRSTransformError,
    MissingCRSError,
)
from app.db.models import FeatureMeasurement, UploadedFile
from app.services.crs_service import (
    crs_to_string,
    determine_measurement_crs,
    get_source_crs,
    transform_geometry,
)
from app.services.geospatial_service import (
    extract_shapefile,
    read_kml,
    read_shapefile,
)
from app.services.measurement_service import (
    AREA_TYPES,
    LENGTH_TYPES,
    POINT_TYPES,
    calculate_area,
    calculate_length,
    classify_geometry,
)
from app.services.storage_service import get_upload_path, save_upload

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _properties_to_dict(row_props: Any) -> dict:
    """Convert a GeoDataFrame row's properties to a plain dict.

    GeoPandas exposes properties as a dict-like Series row without the
    geometry column.  We serialise values to JSON-safe types.

    Args:
        row_props: A dict or dict-like of feature attributes.

    Returns:
        A plain dict with JSON-serialisable values.
    """
    result = {}
    for k, v in row_props.items():
        if k == "geometry":
            continue
        try:
            # Attempt standard serialisation; fall back to str().
            import json
            json.dumps(v)
            result[str(k)] = v
        except (TypeError, ValueError):
            result[str(k)] = str(v)
    return result


def _process_feature(
    idx: int,
    geom: Any,  # shapely geometry or None
    properties: dict,
    source_crs: CRS,
    area_crs: CRS,
    length_crs: CRS,
    area_crs_str: str,
    length_crs_str: str,
) -> dict:
    """Process a single feature: classify, transform, and measure.

    Returns a dict of keyword arguments suitable for constructing a
    FeatureMeasurement ORM model.

    Feature-level failures are caught here and recorded as status=FAILED or
    status=UNSUPPORTED so that processing can continue for other features.
    """
    result: dict = {
        "feature_index": idx,
        "geometry_type": None,
        "properties": properties,
        "area_m2": None,
        "area_ha": None,
        "length_m": None,
        "length_km": None,
        "measurement_crs": None,
        "status": "SUCCESS",
        "warning_message": None,
    }

    if geom is None or (hasattr(geom, "is_empty") and geom.is_empty):
        result["status"] = "FAILED"
        result["warning_message"] = "Feature has a null or empty geometry."
        return result

    result["geometry_type"] = geom.geom_type

    classification = classify_geometry(geom)

    if classification == "EMPTY":
        result["status"] = "FAILED"
        result["warning_message"] = "Geometry is empty."
        return result

    if classification == "INVALID":
        # We report invalid geometry without silently repairing it.
        result["status"] = "WARNING"
        result["warning_message"] = (
            "Geometry is invalid per Shapely's is_valid check. "
            "Measurements may be unreliable. "
            "Repair was not attempted automatically."
        )
        # Fall through to attempt measurement anyway (Shapely may still compute).

    if classification == "UNSUPPORTED":
        result["status"] = "UNSUPPORTED"
        result["warning_message"] = (
            f"Geometry type '{geom.geom_type}' is not supported for measurement."
        )
        return result

    if classification == "POINT":
        # Points are valid but produce no measurements.
        result["status"] = "SUCCESS"
        result["warning_message"] = "Point geometry — no measurement applicable."
        return result

    # ── Perform measurements ──────────────────────────────────────────────────

    if geom.geom_type in AREA_TYPES:
        try:
            projected = transform_geometry(geom, source_crs, area_crs)
            area_m2, area_ha = calculate_area(projected)
            result["area_m2"] = area_m2
            result["area_ha"] = area_ha
            result["measurement_crs"] = area_crs_str
        except CRSTransformError as exc:
            result["status"] = "FAILED"
            result["warning_message"] = f"CRS transformation failed: {exc}"
        except Exception as exc:
            result["status"] = "FAILED"
            result["warning_message"] = f"Area calculation failed: {exc}"
            logger.warning("Area calculation error at feature %d: %s", idx, exc)

    elif geom.geom_type in LENGTH_TYPES:
        try:
            projected = transform_geometry(geom, source_crs, length_crs)
            length_m, length_km = calculate_length(projected)
            result["length_m"] = length_m
            result["length_km"] = length_km
            result["measurement_crs"] = length_crs_str
        except CRSTransformError as exc:
            result["status"] = "FAILED"
            result["warning_message"] = f"CRS transformation failed: {exc}"
        except Exception as exc:
            result["status"] = "FAILED"
            result["warning_message"] = f"Length calculation failed: {exc}"
            logger.warning("Length calculation error at feature %d: %s", idx, exc)

    if result["status"] == "WARNING" and result.get("area_m2") is not None:
        # Measurement succeeded despite invalid geometry — keep WARNING status.
        pass

    return result


def _build_summary(feature_results: list[dict]) -> dict:
    """Aggregate feature-level results into file-level summary stats."""
    total = len(feature_results)
    success = sum(1 for r in feature_results if r["status"] == "SUCCESS")
    failed = sum(1 for r in feature_results if r["status"] == "FAILED")
    warning = sum(1 for r in feature_results if r["status"] == "WARNING")
    unsupported = sum(1 for r in feature_results if r["status"] == "UNSUPPORTED")

    total_area = sum(
        r["area_m2"] for r in feature_results
        if r.get("area_m2") is not None
    ) or None
    total_length = sum(
        r["length_m"] for r in feature_results
        if r.get("length_m") is not None
    ) or None

    # Determine overall file status.
    if failed == total:
        status = "FAILED"
    elif failed > 0 or warning > 0 or unsupported > 0:
        status = "COMPLETED_WITH_WARNINGS"
    else:
        status = "COMPLETED"

    return {
        "status": status,
        "success_count": success,
        "failure_count": failed,
        "warning_count": warning + unsupported,
        "total_area_m2": total_area,
        "total_length_m": total_length,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def process_upload(
    filename: str,
    file_data: bytes,
    db: Session,
    content_length: int | None = None,
) -> UploadedFile:
    """Full processing pipeline for an uploaded geospatial file.

    This function is called from the API route and handles the complete
    lifecycle:
      1. Save the raw file.
      2. Create an UploadedFile record in PROCESSING state.
      3. Parse the geospatial data.
      4. Determine CRS and run measurements.
      5. Persist FeatureMeasurement records.
      6. Update the UploadedFile record with final status.

    If a fatal error occurs (e.g. corrupt file), the UploadedFile is marked
    FAILED and the error is saved, but the HTTP response is still 201 with
    status=FAILED rather than a 500.  This allows clients to poll for status.

    Args:
        filename: Original client-provided filename (used for display only).
        file_data: Raw bytes of the uploaded file.
        db: SQLAlchemy database session.
        content_length: Optional Content-Length header value.

    Returns:
        The persisted UploadedFile ORM object.
    """
    from app.utils.file_validation import (
        validate_extension,
        validate_shapefile_components,
        validate_size,
        validate_zip_safety,
    )

    # ── Step 1: Validate ──────────────────────────────────────────────────────
    validate_size(content_length, file_data)
    ext = validate_extension(filename)

    # ── Step 2: Save raw file ─────────────────────────────────────────────────
    stored_filename = save_upload(file_data, filename)

    # ── Step 3: Create DB record in PROCESSING state ──────────────────────────
    db_file = UploadedFile(
        filename=filename,
        stored_filename=stored_filename,
        status="PROCESSING",
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    logger.info(
        "Processing file id=%d filename=%r ext=%s size=%d bytes",
        db_file.id, filename, ext, len(file_data),
    )

    try:
        # ── Step 4: Parse geospatial data ─────────────────────────────────────
        gdf = _load_geodataframe(ext, file_data)

        source_crs = get_source_crs(gdf)
        source_crs_str = crs_to_string(source_crs)

        if source_crs is None:
            # Without a CRS we cannot safely project.  Mark FAILED.
            raise MissingCRSError(
                "The uploaded file has no CRS. "
                "Cannot perform accurate measurements without a known coordinate reference system."
            )

        # ── Step 5: Determine measurement CRSes ──────────────────────────────
        area_crs, area_crs_explanation = determine_measurement_crs(gdf, purpose="area")
        length_crs, length_crs_explanation = determine_measurement_crs(gdf, purpose="length")
        area_crs_str = crs_to_string(area_crs)
        length_crs_str = crs_to_string(length_crs)

        logger.info(
            "CRS selected — source: %s, area: %s, length: %s",
            source_crs_str, area_crs_str, length_crs_str,
        )

        # ── Step 6: Process features ──────────────────────────────────────────
        feature_results = []
        for idx, row in enumerate(gdf.itertuples(index=False)):
            geom = getattr(row, "geometry", None)
            props = _properties_to_dict(
                {c: getattr(row, c) for c in gdf.columns if c != "geometry"}
            )
            result = _process_feature(
                idx=idx,
                geom=geom,
                properties=props,
                source_crs=source_crs,
                area_crs=area_crs,
                length_crs=length_crs,
                area_crs_str=area_crs_str,
                length_crs_str=length_crs_str,
            )
            feature_results.append(result)

        # ── Step 7: Persist feature measurements ──────────────────────────────
        for r in feature_results:
            fm = FeatureMeasurement(uploaded_file_id=db_file.id)
            fm.feature_index = r["feature_index"]
            fm.geometry_type = r["geometry_type"]
            fm.properties = r["properties"]
            fm.area_m2 = r["area_m2"]
            fm.area_ha = r["area_ha"]
            fm.length_m = r["length_m"]
            fm.length_km = r["length_km"]
            fm.measurement_crs = r["measurement_crs"]
            fm.status = r["status"]
            fm.warning_message = r["warning_message"]
            db.add(fm)

        # ── Step 8: Update file record with summary ───────────────────────────
        summary = _build_summary(feature_results)
        db_file.source_crs = source_crs_str
        db_file.feature_count = len(gdf)
        db_file.status = summary["status"]
        db_file.success_count = summary["success_count"]
        db_file.failure_count = summary["failure_count"]
        db_file.warning_count = summary["warning_count"]
        db_file.total_area_m2 = summary["total_area_m2"]
        db_file.total_length_m = summary["total_length_m"]
        db_file.completed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(db_file)
        logger.info(
            "Processing complete: id=%d status=%s features=%d",
            db_file.id, db_file.status, db_file.feature_count,
        )
        return db_file

    except (MissingCRSError, CorruptFileError) as exc:
        logger.warning("File processing failed (id=%d): %s", db_file.id, exc)
        db_file.status = "FAILED"
        db_file.error_message = str(exc)
        db_file.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_file)
        return db_file

    except Exception as exc:
        logger.exception("Unexpected error processing file id=%d: %s", db_file.id, exc)
        db_file.status = "FAILED"
        db_file.error_message = "An unexpected error occurred during processing."
        db_file.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_file)
        return db_file


def _load_geodataframe(ext: str, file_data: bytes) -> gpd.GeoDataFrame:
    """Load file bytes into a GeoDataFrame based on the extension.

    Args:
        ext: Lowercased file extension ('.kml' or '.zip').
        file_data: Raw file bytes.

    Returns:
        A GeoDataFrame.

    Raises:
        CorruptFileError: If the file cannot be parsed.
        MissingCRSError: If the Shapefile has no CRS.
    """
    if ext == ".kml":
        return read_kml(file_data)

    if ext == ".zip":
        # validate_zip_safety and validate_shapefile_components have already run
        # by the time we reach here (called from the route handler before this
        # function is invoked), so we can proceed directly to extraction.
        with extract_shapefile(file_data) as tmp_dir:
            return read_shapefile(tmp_dir)

    raise CorruptFileError(f"Unsupported extension: {ext!r}")
