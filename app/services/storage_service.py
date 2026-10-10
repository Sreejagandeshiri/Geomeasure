"""
Storage service: manages the safe storage of uploaded files.

Design decisions
────────────────
* Uploaded files are stored with a UUID-prefixed server-generated filename so
  that the original client filename never becomes a filesystem path.
* The upload directory is configurable and created at startup.
* Files are written atomically using a temp-file-then-rename approach to avoid
  partial uploads being visible to concurrent readers.
* The API does not expose the stored filename or internal path to clients.
"""

import logging
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def _safe_extension(filename: str) -> str:
    """Return the lowercased extension (e.g. '.kml') from a filename."""
    return Path(filename).suffix.lower()


def save_upload(data: bytes, original_filename: str) -> str:
    """Persist raw upload bytes to the upload directory.

    Args:
        data: The raw file bytes.
        original_filename: The original filename provided by the client.
                           Used only to determine the extension.

    Returns:
        The server-side stored filename (not a full path) that can be used
        to retrieve the file later.
    """
    ext = _safe_extension(original_filename)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    target = settings.UPLOAD_DIR / stored_name

    # Write to a .tmp file first, then rename to make the write atomic.
    tmp_target = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp_target.write_bytes(data)
        tmp_target.rename(target)
    except Exception:
        tmp_target.unlink(missing_ok=True)
        raise

    logger.info("Saved upload: %s (%d bytes) → %s", original_filename, len(data), stored_name)
    return stored_name


def get_upload_path(stored_filename: str) -> Path:
    """Return the full Path for a stored upload.

    Args:
        stored_filename: The server-side stored filename returned by save_upload.

    Returns:
        Full Path object pointing to the stored file.
    """
    return settings.UPLOAD_DIR / stored_filename


def delete_upload(stored_filename: str) -> None:
    """Delete a stored upload file.

    Silently succeeds if the file does not exist (idempotent).

    Args:
        stored_filename: The server-side stored filename.
    """
    path = settings.UPLOAD_DIR / stored_filename
    if path.exists():
        path.unlink()
        logger.info("Deleted stored upload: %s", stored_filename)
    else:
        logger.warning("Attempted to delete non-existent upload: %s", stored_filename)
