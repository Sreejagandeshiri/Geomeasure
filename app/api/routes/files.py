"""
API route handlers for file upload, retrieval, list, and deletion.

Route overview
──────────────
  POST   /api/files/           Upload and process a geospatial file.
  GET    /api/files/           List uploaded files (paginated).
  GET    /api/files/{id}/      Retrieve file metadata and summary.
  DELETE /api/files/{id}/      Delete a file and all its measurements.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    CorruptFileError,
    FileTooLargeError,
    InvalidArchiveError,
    MissingCRSError,
    MissingShapefileComponentError,
    UnsupportedFileTypeError,
)
from app.db.database import get_db
from app.db.models import UploadedFile
from app.schemas.files import (
    FileInfoResponse,
    FileListItem,
    FileListResponse,
    FileUploadResponse,
    SummaryStatistics,
)
from app.services.file_service import process_upload
from app.services.storage_service import delete_upload
from app.utils.file_validation import (
    validate_extension,
    validate_shapefile_components,
    validate_size,
    validate_zip_safety,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["Files"])


# ── POST /api/files/ ──────────────────────────────────────────────────────────

@router.post("/", status_code=201, response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(..., description="A .kml file or a .zip containing a Shapefile."),
    content_length: Optional[int] = Header(None),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload and process a geospatial file.

    Accepts:
    - `.kml` files
    - `.zip` archives containing a Shapefile (`.shp`, `.shx`, `.dbf` required)

    Returns the assigned file ID and processing status.
    """
    filename = file.filename or "unknown"
    logger.info("Upload request: filename=%r content_length=%s", filename, content_length)

    # ── Validate extension early before reading bytes ─────────────────────────
    try:
        ext = validate_extension(filename)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc))

    # ── Read the file bytes ───────────────────────────────────────────────────
    try:
        data = await file.read()
    except Exception as exc:
        logger.error("Failed to read uploaded file: %s", exc)
        raise HTTPException(status_code=400, detail="Failed to read the uploaded file.")

    # ── Size check ────────────────────────────────────────────────────────────
    try:
        validate_size(content_length, data)
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    # ── ZIP-specific pre-flight checks ────────────────────────────────────────
    if ext == ".zip":
        try:
            zf = validate_zip_safety(data)
            validate_shapefile_components(zf)
            zf.close()
        except InvalidArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except MissingShapefileComponentError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # ── Process (parse, measure, persist) ─────────────────────────────────────
    try:
        db_file = process_upload(
            filename=filename,
            file_data=data,
            db=db,
            content_length=content_length,
        )
    except (FileTooLargeError, UnsupportedFileTypeError, InvalidArchiveError,
            MissingShapefileComponentError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during file processing: %s", exc)
        raise HTTPException(status_code=500, detail="An internal error occurred during processing.")

    if db_file.status == "FAILED":
        if isinstance(db_file.error_message, str) and ("corrupt" in db_file.error_message.lower() or "failed to parse" in db_file.error_message.lower() or "no features" in db_file.error_message.lower()):
            raise HTTPException(status_code=400, detail=f"Invalid or corrupt geospatial file: {db_file.error_message}")

    message = f"File processed successfully with status: {db_file.status}"
    if db_file.status == "FAILED" and db_file.error_message:
        message = f"Processing failed: {db_file.error_message}"

    logger.info("Upload complete: file_id=%d status=%s", db_file.id, db_file.status)

    return FileUploadResponse(
        file_id=db_file.id,
        filename=db_file.filename,
        status=db_file.status,
        message=message,
    )


# ── GET /api/files/ ───────────────────────────────────────────────────────────

@router.get("/", response_model=FileListResponse)
def list_files(
    page: int = Query(1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(
        settings.DEFAULT_PAGE_SIZE,
        ge=1,
        le=settings.MAX_PAGE_SIZE,
        description="Results per page.",
    ),
    db: Session = Depends(get_db),
) -> FileListResponse:
    """List previously uploaded files, ordered by most recent first."""
    offset = (page - 1) * page_size
    total = db.query(UploadedFile).count()
    files = (
        db.query(UploadedFile)
        .order_by(UploadedFile.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        FileListItem(
            file_id=f.id,
            filename=f.filename,
            status=f.status,
            feature_count=f.feature_count,
            upload_timestamp=f.created_at,
        )
        for f in files
    ]

    return FileListResponse(total=total, page=page, page_size=page_size, items=items)


# ── GET /api/files/{id}/ ──────────────────────────────────────────────────────

@router.get("/{file_id}/", response_model=FileInfoResponse)
def get_file_info(
    file_id: int,
    db: Session = Depends(get_db),
) -> FileInfoResponse:
    """Retrieve metadata and summary statistics for a specific uploaded file."""
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if db_file is None:
        raise HTTPException(status_code=404, detail=f"File with id={file_id} not found.")

    summary = None
    if db_file.status in ("COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"):
        summary = SummaryStatistics(
            total_features=db_file.feature_count or 0,
            success_count=db_file.success_count or 0,
            failure_count=db_file.failure_count or 0,
            warning_count=db_file.warning_count or 0,
            total_area_m2=db_file.total_area_m2,
            total_length_m=db_file.total_length_m,
        )

    return FileInfoResponse(
        file_id=db_file.id,
        filename=db_file.filename,
        upload_timestamp=db_file.created_at,
        feature_count=db_file.feature_count,
        source_crs=db_file.source_crs,
        status=db_file.status,
        success_count=db_file.success_count,
        failure_count=db_file.failure_count,
        warning_count=db_file.warning_count,
        summary_statistics=summary,
        error_message=db_file.error_message,
    )


# ── DELETE /api/files/{id}/ ───────────────────────────────────────────────────

@router.delete("/{file_id}/", status_code=204)
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete a file record, its feature measurements, and the stored file.

    Returns 204 No Content on success, 404 if the file does not exist.
    Deletion is atomic: both the DB records and the stored file are removed
    or an error is returned without partial deletion.
    """
    db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if db_file is None:
        raise HTTPException(status_code=404, detail=f"File with id={file_id} not found.")

    stored_filename = db_file.stored_filename

    # Delete DB records first (CASCADE handles FeatureMeasurements).
    db.delete(db_file)
    db.commit()

    # Delete the stored file (best-effort; log but don't fail on missing file).
    delete_upload(stored_filename)

    logger.info("Deleted file id=%d stored_filename=%r", file_id, stored_filename)
