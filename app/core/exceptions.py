"""
Custom exception hierarchy for GeoMeasure.

Using named exception classes rather than generic exceptions makes error
handling explicit and allows FastAPI exception handlers to return consistent
JSON responses without leaking internal details.
"""


class GeoMeasureError(Exception):
    """Base class for all GeoMeasure application errors."""


# ── File validation ───────────────────────────────────────────────────────────

class FileTooLargeError(GeoMeasureError):
    """Raised when an uploaded file exceeds the configured size limit."""


class UnsupportedFileTypeError(GeoMeasureError):
    """Raised when the uploaded file has an extension we cannot process."""


class InvalidArchiveError(GeoMeasureError):
    """Raised when a ZIP file is corrupt, empty, or contains path traversal."""


class MissingShapefileComponentError(GeoMeasureError):
    """Raised when a ZIP does not contain the required Shapefile components."""


class CorruptFileError(GeoMeasureError):
    """Raised when a file cannot be parsed as valid geospatial data."""


# ── CRS and measurement ───────────────────────────────────────────────────────

class MissingCRSError(GeoMeasureError):
    """Raised when no CRS can be determined for a dataset."""


class CRSTransformError(GeoMeasureError):
    """Raised when a geometry cannot be transformed to the measurement CRS."""


class MeasurementError(GeoMeasureError):
    """Raised when a measurement calculation fails for unexpected reasons."""


# ── Database ──────────────────────────────────────────────────────────────────

class RecordNotFoundError(GeoMeasureError):
    """Raised when a database record cannot be found by the given identifier."""
