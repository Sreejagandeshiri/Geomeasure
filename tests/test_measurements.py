"""
Tests for GET /api/files/{id}/measurements/ endpoint.

Covers:
- Retrieving per-feature measurements
- Polygon area calculation (m² and ha)
- LineString length calculation (m and km)
- Point features having null measurements
- Graceful handling of multi-feature geometries
- Quality report verification
- Proper 404 response for unknown ID
"""

import io
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    make_kml_polygon,
    make_kml_linestring,
    make_kml_point,
    make_kml_multi_feature,
    make_shapefile_zip,
)


def test_get_measurements_polygon(client: TestClient):
    """Polygon feature should return valid area_m2 and area_ha, and null lengths."""
    kml_bytes = make_kml_polygon(name="poly_test")
    up_res = client.post("/api/files/", files={"file": ("poly.kml", io.BytesIO(kml_bytes), "application/xml")})
    file_id = up_res.json()["file_id"]

    res = client.get(f"/api/files/{file_id}/measurements/")
    assert res.status_code == 200
    data = res.json()
    assert data["file_id"] == file_id
    assert data["source_crs"] == "EPSG:4326"
    assert data["measurement_crs"] is not None
    assert len(data["features"]) == 1

    feature = data["features"][0]
    assert feature["geometry_type"] in ("Polygon", "MultiPolygon")
    assert feature["area_m2"] is not None
    assert feature["area_m2"] > 0
    assert feature["area_ha"] is not None
    assert feature["area_ha"] == pytest.approx(feature["area_m2"] / 10000.0, rel=1e-3)
    assert feature["length_m"] is None
    assert feature["length_km"] is None
    assert feature["status"] == "SUCCESS"


def test_get_measurements_linestring(client: TestClient):
    """LineString feature should return valid length_m and length_km, and null areas."""
    kml_bytes = make_kml_linestring(name="line_test")
    up_res = client.post("/api/files/", files={"file": ("line.kml", io.BytesIO(kml_bytes), "application/xml")})
    file_id = up_res.json()["file_id"]

    res = client.get(f"/api/files/{file_id}/measurements/")
    assert res.status_code == 200
    data = res.json()
    feature = data["features"][0]
    assert feature["geometry_type"] in ("LineString", "MultiLineString")
    assert feature["length_m"] is not None
    assert feature["length_m"] > 0
    assert feature["length_km"] is not None
    assert feature["length_km"] == pytest.approx(feature["length_m"] / 1000.0, rel=1e-3)
    assert feature["area_m2"] is None
    assert feature["area_ha"] is None
    assert feature["status"] == "SUCCESS"


def test_get_measurements_point(client: TestClient):
    """Point feature should return null for both area and length, without failing."""
    kml_bytes = make_kml_point(name="pt_test")
    up_res = client.post("/api/files/", files={"file": ("pt.kml", io.BytesIO(kml_bytes), "application/xml")})
    file_id = up_res.json()["file_id"]

    res = client.get(f"/api/files/{file_id}/measurements/")
    assert res.status_code == 200
    data = res.json()
    feature = data["features"][0]
    assert feature["geometry_type"] == "Point"
    assert feature["area_m2"] is None
    assert feature["length_m"] is None
    assert feature["status"] == "SUCCESS"
    assert "Point" in (feature["warning_message"] or "")


def test_get_measurements_multi_feature(client: TestClient):
    """Multi-feature file should measure each feature appropriately and populate quality report."""
    kml_bytes = make_kml_multi_feature()
    up_res = client.post("/api/files/", files={"file": ("multi.kml", io.BytesIO(kml_bytes), "application/xml")})
    file_id = up_res.json()["file_id"]

    res = client.get(f"/api/files/{file_id}/measurements/")
    assert res.status_code == 200
    data = res.json()
    assert len(data["features"]) == 3

    # Quality report checks
    qr = data["quality_report"]
    assert qr["total_features"] == 3
    assert qr["successfully_measured"] == 2  # polygon and linestring
    assert qr["total_area_m2"] is not None
    assert qr["total_length_m"] is not None


def test_get_measurements_not_found(client: TestClient):
    """Retrieving measurements for non-existent file ID returns 404."""
    res = client.get("/api/files/999999/measurements/")
    assert res.status_code == 404
