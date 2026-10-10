"""
GeoMeasure FastAPI application entry point.

Startup sequence
────────────────
1. Configure structured logging.
2. Create all database tables (idempotent).
3. Register API routers.
4. Register global exception handlers for clean error responses.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import (
    CorruptFileError,
    FileTooLargeError,
    GeoMeasureError,
    InvalidArchiveError,
    MissingCRSError,
    MissingShapefileComponentError,
    UnsupportedFileTypeError,
)
from app.core.logging_config import configure_logging
from app.db.database import create_all_tables

configure_logging()

logger = logging.getLogger(__name__)


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and log configuration
    create_all_tables()
    logger.info(
        "%s v%s started — DB: %s, Upload dir: %s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.DATABASE_URL,
        settings.UPLOAD_DIR,
    )
    yield


def create_app() -> FastAPI:
    """Application factory.  Returns a configured FastAPI instance."""

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "A REST API that accepts geospatial files (.kml or .zip Shapefile), "
            "extracts features, calculates accurate projected measurements, and "
            "exposes results through typed JSON endpoints."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Register routers ──────────────────────────────────────────────────────
    from app.api.routes.files import router as files_router
    from app.api.routes.measurements import router as measurements_router

    app.include_router(files_router)
    app.include_router(measurements_router)

    # ── Global exception handlers ─────────────────────────────────────────────
    # These catch exceptions that bubble past route handlers and return clean
    # JSON instead of exposing stack traces.

    @app.exception_handler(FileTooLargeError)
    async def file_too_large_handler(request: Request, exc: FileTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"error": str(exc), "status_code": 413})

    @app.exception_handler(UnsupportedFileTypeError)
    async def unsupported_type_handler(request: Request, exc: UnsupportedFileTypeError) -> JSONResponse:
        return JSONResponse(status_code=415, content={"error": str(exc), "status_code": 415})

    @app.exception_handler(InvalidArchiveError)
    async def invalid_archive_handler(request: Request, exc: InvalidArchiveError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc), "status_code": 400})

    @app.exception_handler(MissingShapefileComponentError)
    async def missing_component_handler(request: Request, exc: MissingShapefileComponentError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc), "status_code": 422})

    @app.exception_handler(MissingCRSError)
    async def missing_crs_handler(request: Request, exc: MissingCRSError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc), "status_code": 422})

    @app.exception_handler(CorruptFileError)
    async def corrupt_file_handler(request: Request, exc: CorruptFileError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc), "status_code": 400})

    @app.exception_handler(GeoMeasureError)
    async def geomeasure_error_handler(request: Request, exc: GeoMeasureError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc), "status_code": 400})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s: %s", request.method, request.url, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "An internal server error occurred.", "status_code": 500},
        )

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["Health"])
    def health_check() -> dict:
        return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

    return app


app = create_app()
