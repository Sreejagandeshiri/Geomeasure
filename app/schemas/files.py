"""
Pydantic schemas for the Files API.

All API inputs and outputs are typed here so that FastAPI can generate
accurate OpenAPI documentation and perform automatic validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class SummaryStatistics(BaseModel):
    """Aggregate statistics across all features in a file."""

    total_features: int
    success_count: int
    failure_count: int
    warning_count: int
    total_area_m2: Optional[float] = Field(
        None,
        description="Sum of all polygon areas in m². Null when no polygons exist.",
    )
    total_length_m: Optional[float] = Field(
        None,
        description="Sum of all line lengths in metres. Null when no lines exist.",
    )


# ── Upload response ───────────────────────────────────────────────────────────

class FileUploadResponse(BaseModel):
    """Returned by POST /api/files/."""

    file_id: int
    filename: str
    status: str
    message: str

    model_config = {"from_attributes": True}


# ── File information ──────────────────────────────────────────────────────────

class FileInfoResponse(BaseModel):
    """Returned by GET /api/files/{id}/."""

    file_id: int
    filename: str
    upload_timestamp: datetime
    feature_count: Optional[int]
    source_crs: Optional[str]
    status: str
    success_count: Optional[int]
    failure_count: Optional[int]
    warning_count: Optional[int]
    summary_statistics: Optional[SummaryStatistics]
    error_message: Optional[str]

    model_config = {"from_attributes": True}


# ── File list (optional endpoint) ────────────────────────────────────────────

class FileListItem(BaseModel):
    """A single item in the file list response."""

    file_id: int
    filename: str
    status: str
    feature_count: Optional[int]
    upload_timestamp: datetime

    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    """Returned by GET /api/files/."""

    total: int
    page: int
    page_size: int
    items: list[FileListItem]
