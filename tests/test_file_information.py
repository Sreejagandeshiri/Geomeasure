"""
Tests for GET /api/files/{id}/ endpoint.

Covers:
- Retrieving metadata of an uploaded file
- Proper 404 response when ID does not exist
- Status and summary statistics fields
- Optional list endpoint GET /api/files/
- Optional delete endpoint DELETE /api/files/{id}/
"""

import io
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_kml_polygon, make_kml_multi_feature


def test_get_file_info_success(client: TestClient):
    """Retrieving file info for a valid uploaded file should return 200 with all metadata."""
    kml_bytes = make_kml_polygon(name="field_a")
    files = {"file": ("field_a.kml", io.BytesIO(kml_bytes), "application/xml")}
    up_res = client.post("/api/files/", files=files)
    file_id = up_res.json()["file_id"]

    res = client.get(f"/api/files/{file_id}/")
    assert res.status_code == 200
    data = res.json()
    assert data["file_id"] == file_id
    assert data["filename"] == "field_a.kml"
    assert data["feature_count"] == 1
    assert data["source_crs"] == "EPSG:4326"
    assert data["status"] in ("COMPLETED", "COMPLETED_WITH_WARNINGS")
    assert data["success_count"] >= 1
    assert data["failure_count"] == 0
    assert "upload_timestamp" in data
    assert data["summary_statistics"] is not None
    assert data["summary_statistics"]["total_features"] == 1


def test_get_file_info_not_found(client: TestClient):
    """Retrieving file info for an unknown ID should return 404."""
    res = client.get("/api/files/999999/")
    assert res.status_code == 404


def test_list_files(client: TestClient):
    """GET /api/files/ should list previously uploaded files with pagination."""
    # Ensure at least one file is uploaded
    kml_bytes = make_kml_polygon(name="test_list")
    client.post("/api/files/", files={"file": ("list_sample.kml", io.BytesIO(kml_bytes), "application/xml")})

    res = client.get("/api/files/?page=1&page_size=10")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "page" in data
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) >= 1


def test_delete_file(client: TestClient):
    """DELETE /api/files/{id}/ should delete file record and return 204."""
    kml_bytes = make_kml_polygon(name="to_delete")
    up_res = client.post("/api/files/", files={"file": ("to_delete.kml", io.BytesIO(kml_bytes), "application/xml")})
    file_id = up_res.json()["file_id"]

    # Delete
    del_res = client.delete(f"/api/files/{file_id}/")
    assert del_res.status_code == 204

    # Subsequent GET should return 404
    get_res = client.get(f"/api/files/{file_id}/")
    assert get_res.status_code == 404


def test_delete_file_not_found(client: TestClient):
    """Deleting a non-existent file should return 404."""
    del_res = client.delete("/api/files/999999/")
    assert del_res.status_code == 404
