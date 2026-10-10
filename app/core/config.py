"""
Application configuration loaded from environment variables or a .env file.
All tuneable parameters are centralised here to avoid magic constants scattered
across the codebase.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (two levels above this file)
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(_project_root / ".env")


class Settings:
    """Centralised application settings."""

    # ── General ──────────────────────────────────────────────────────────────
    APP_NAME: str = os.getenv("APP_NAME", "GeoMeasure")
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ── Storage ───────────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(_project_root / "uploads")))

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_project_root / 'geomeasure.db'}",
    )

    # ── File upload constraints ────────────────────────────────────────────────
    # Default: 50 MB.  Override via MAX_UPLOAD_SIZE_MB in .env.
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024

    ALLOWED_EXTENSIONS: tuple[str, ...] = (".kml", ".zip")

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Measurement ───────────────────────────────────────────────────────────
    # Equal-area projection used for all polygon area calculations.
    # ESRI:54034 (World Cylindrical Equal Area) is appropriate for global data.
    EQUAL_AREA_CRS: str = os.getenv("EQUAL_AREA_CRS", "ESRI:54034")

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
    MAX_PAGE_SIZE: int = int(os.getenv("MAX_PAGE_SIZE", "100"))


settings = Settings()

# Ensure the upload directory exists at startup.
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
