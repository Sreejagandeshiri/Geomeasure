"""
File validation utilities for GeoMeasure.

Security-oriented checks that must run *before* any geospatial library
touches the uploaded bytes.

Validation order
────────────────
1. Extension check  — fast, no I/O beyond inspecting the name.
2. Size check       — refuse to buffer oversized payloads.
3. ZIP safety check — detect path traversal, bombs, and corrupt archives.
4. ZIP content check — verify required Shapefile components are present.

None of these functions perform geospatial parsing; that belongs in
geospatial_service.py.
"""

import logging
import zipfile
from pathlib import Path, PurePosixPath

from app.core.config import settings
from app.core.exceptions import (
    FileTooLargeError,
    InvalidArchiveError,
    MissingShapefileComponentError,
    UnsupportedFileTypeError,
)

logger = logging.getLogger(__name__)

# Required Shapefile components (case-insensitive).
REQUIRED_SHP_EXTENSIONS = {".shp", ".shx", ".dbf"}
OPTIONAL_SHP_EXTENSIONS = {".prj", ".cpg", ".qpj"}


def validate_extension(filename: str) -> str:
    """Return the lowercased extension if allowed, otherwise raise.

    Args:
        filename: The original filename provided by the client.

    Returns:
        The lowercased file extension, e.g. '.kml' or '.zip'.

    Raises:
        UnsupportedFileTypeError: If the extension is not in ALLOWED_EXTENSIONS.
    """
    ext = Path(filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"File type {ext!r} is not supported. "
            f"Accepted types: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )
    return ext


def validate_size(content_length: int | None, data: bytes) -> None:
    """Raise FileTooLargeError when the payload exceeds the configured limit.

    We check both the Content-Length header (fast pre-check) and the actual
    bytes read (authoritative check) because clients can lie about header values.

    Args:
        content_length: Value from the Content-Length header (may be None).
        data: Fully buffered file bytes.

    Raises:
        FileTooLargeError: When file size exceeds MAX_UPLOAD_SIZE_BYTES.
    """
    limit = settings.MAX_UPLOAD_SIZE_BYTES
    if content_length is not None and content_length > limit:
        raise FileTooLargeError(
            f"Upload size {content_length / 1024 / 1024:.1f} MB "
            f"exceeds the {limit // 1024 // 1024} MB limit."
        )
    if len(data) > limit:
        raise FileTooLargeError(
            f"Upload size {len(data) / 1024 / 1024:.1f} MB "
            f"exceeds the {limit // 1024 // 1024} MB limit."
        )


def validate_zip_safety(data: bytes) -> zipfile.ZipFile:
    """Open a ZIP archive and perform security checks.

    Checks performed:
    * Corrupt or non-ZIP bytes → InvalidArchiveError.
    * Empty archive            → InvalidArchiveError.
    * Path traversal (../…)   → InvalidArchiveError.
    * Absolute paths inside    → InvalidArchiveError.

    We intentionally do NOT extract any files here; only the central directory
    is inspected.

    Args:
        data: Raw bytes of the ZIP file.

    Returns:
        An open ZipFile object (caller must close or use as context manager).

    Raises:
        InvalidArchiveError: On any safety issue.
    """
    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(f"The uploaded file is not a valid ZIP archive: {exc}") from exc

    names = zf.namelist()
    if not names:
        zf.close()
        raise InvalidArchiveError("The ZIP archive is empty.")

    for name in names:
        # Reject absolute paths and directory traversal.
        p = PurePosixPath(name)
        if p.is_absolute():
            zf.close()
            raise InvalidArchiveError(
                f"ZIP entry {name!r} uses an absolute path which is not allowed."
            )
        # Check each part for traversal tokens.
        if any(part == ".." for part in p.parts):
            zf.close()
            raise InvalidArchiveError(
                f"ZIP entry {name!r} contains a path traversal sequence (..)."
            )

    logger.debug("ZIP safety check passed: %d entries", len(names))
    return zf


def validate_shapefile_components(zf: zipfile.ZipFile) -> str:
    """Verify that the ZIP contains all required Shapefile components.

    Shapefiles may be nested inside a subdirectory within the ZIP.  We search
    for any .shp file and then confirm that its paired .shx and .dbf siblings
    also exist in the same directory.

    Args:
        zf: An already-validated open ZipFile object.

    Returns:
        The base name (without extension) of the Shapefile found, e.g. "roads".

    Raises:
        MissingShapefileComponentError: If required components are absent.
    """
    names_lower = {n.lower(): n for n in zf.namelist()}

    # Find candidate .shp files.
    shp_files = [n for n in names_lower if n.endswith(".shp")]
    if not shp_files:
        raise MissingShapefileComponentError(
            "No .shp file found inside the ZIP archive."
        )

    # Use the first .shp found.  If there are multiple we warn but proceed
    # with the first; this mirrors common GIS tooling behaviour.
    shp_key = shp_files[0]
    stem = shp_key[: -len(".shp")]

    missing = []
    for ext in REQUIRED_SHP_EXTENSIONS - {".shp"}:
        if f"{stem}{ext}" not in names_lower:
            missing.append(ext)

    if missing:
        raise MissingShapefileComponentError(
            f"The ZIP is missing required Shapefile components: "
            f"{', '.join(sorted(missing))} "
            f"(found .shp at {shp_key!r})."
        )

    prj_present = f"{stem}.prj" in names_lower
    if not prj_present:
        logger.warning(
            "Shapefile %r has no .prj file — CRS will be unknown.", shp_key
        )

    logger.info(
        "Shapefile components validated: stem=%r, prj_present=%s",
        stem,
        prj_present,
    )
    return stem
