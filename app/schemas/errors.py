"""
Pydantic schema for consistent error responses.

Every non-2xx response from the API follows this structure so that API
consumers can always parse the body in the same way.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """A single validation or processing error detail."""

    field: Optional[str] = None
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned for all API errors."""

    error: str = "An error occurred"
    detail: Optional[str] = None
    errors: Optional[list[ErrorDetail]] = None
    status_code: int
