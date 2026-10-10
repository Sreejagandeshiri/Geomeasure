"""
Tests for POST /api/files/ endpoint.

Covers:
- Uploading a valid KML file
- Uploading a valid zipped Shapefile
- Rejecting unsupported file extensions (415)
- Rejecting corrupt ZIP files (400)
- Rejecting ZIP missing required Shapefile components (422)
- Rejecting empty ZIP files (400)
- Enforcing upload size limit (413)
- Path traversal in ZIP files (400)
"""

import io
import zipfile
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    make_kml_polygon,
    make_shapefile_zip,
    make_corrupt_zip,
    make_corrupt_kml,
)
from app.core.config import settings


def test_upload_valid_kml(client: TestClient):
    """Uploading a valid KML file should return 201 with status COMPLETED."""
    kml_bytes = make_kml_polygon(name="park")
    files = {"file": ("test_park.kml", io.BytesIO(kml_bytes), "application/vnd.google-earth.kml+xml")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 201
    data = response.json()
    assert "file_id" in data
    assert data["filename"] == "test_park.kml"
    assert data["status"] in ("COMPLETED", "COMPLETED_WITH_WARNINGS")
    assert "message" in data


def test_upload_valid_shapefile_zip(client: TestClient):
    """Uploading a valid zipped Shapefile should return 201 with status COMPLETED."""
    zip_bytes = make_shapefile_zip(crs_epsg=4326)
    files = {"file": ("boundary.zip", io.BytesIO(zip_bytes), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 201
    data = response.json()
    assert "file_id" in data
    assert data["filename"] == "boundary.zip"
    assert data["status"] in ("COMPLETED", "COMPLETED_WITH_WARNINGS")


def test_upload_unsupported_file_extension(client: TestClient):
    """Uploading an unsupported extension (e.g. .geojson) should return 415."""
    files = {"file": ("data.geojson", io.BytesIO(b'{"type": "FeatureCollection"}'), "application/json")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 415
    data = response.json()
    assert "detail" in data or "error" in data


def test_upload_corrupt_zip(client: TestClient):
    """Uploading a corrupt ZIP file should return 400 Bad Request."""
    corrupt_bytes = make_corrupt_zip()
    files = {"file": ("corrupt.zip", io.BytesIO(corrupt_bytes), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 400


def test_upload_empty_zip(client: TestClient):
    """Uploading an empty ZIP file should return 400 Bad Request."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        pass  # empty
    files = {"file": ("empty.zip", io.BytesIO(buf.getvalue()), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 400


def test_upload_shapefile_missing_shx(client: TestClient):
    """Uploading a Shapefile missing .shx component should return 422 Unprocessable Entity."""
    zip_bytes = make_shapefile_zip(include_shx=False)
    files = {"file": ("missing_shx.zip", io.BytesIO(zip_bytes), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 422


def test_upload_shapefile_missing_dbf(client: TestClient):
    """Uploading a Shapefile missing .dbf component should return 422 Unprocessable Entity."""
    zip_bytes = make_shapefile_zip(include_dbf=False)
    files = {"file": ("missing_dbf.zip", io.BytesIO(zip_bytes), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 422


def test_upload_zip_with_path_traversal(client: TestClient):
    """Uploading a ZIP containing path traversal (..) should return 400 Bad Request."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "evil content")
    files = {"file": ("traversal.zip", io.BytesIO(buf.getvalue()), "application/zip")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 400


def test_upload_file_size_exceeded(client: TestClient, monkeypatch):
    """Uploading a file exceeding MAX_UPLOAD_SIZE_BYTES should return 413."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 50)  # 50 bytes limit
    kml_bytes = make_kml_polygon()  # > 50 bytes
    files = {"file": ("too_large.kml", io.BytesIO(kml_bytes), "application/xml")}

    response = client.post("/api/files/", files=files)
    assert response.status_code == 413
