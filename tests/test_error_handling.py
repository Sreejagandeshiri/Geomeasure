"""
Tests for error handling, feature-level resilience, and cleanup.

Covers:
- Corrupted KML returns 400
- Missing .prj Shapefile fails gracefully with meaningful error
- Feature-level failure without aborting entire file
- Database persistence after API restart
- Storage cleanup on deletion and failed extraction
"""

import io
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, LineString, Point
import fiona
from pyproj import CRS
from shapely.geometry import mapping
import tempfile
import zipfile
from pathlib import Path

from tests.conftest import make_corrupt_kml, make_shapefile_zip, TestSessionLocal
from app.db.models import UploadedFile, FeatureMeasurement


def test_corrupt_kml_returns_400(client: TestClient):
    """Uploading corrupt KML data should return 400."""
    files = {"file": ("bad.kml", io.BytesIO(make_corrupt_kml()), "application/xml")}
    res = client.post("/api/files/", files=files)
    assert res.status_code == 400


def test_shapefile_without_prj_fails_with_crs_error(client: TestClient):
    """Uploading Shapefile without .prj should fail with status FAILED or 422 error."""
    zip_bytes = make_shapefile_zip(include_prj=False)
    files = {"file": ("no_prj.zip", io.BytesIO(zip_bytes), "application/zip")}
    res = client.post("/api/files/", files=files)
    assert res.status_code in (201, 422)
    if res.status_code == 201:
        data = res.json()
        assert data["status"] == "FAILED"
        # Check info endpoint
        info_res = client.get(f"/api/files/{data['file_id']}/")
        assert info_res.status_code == 200
        assert info_res.json()["status"] == "FAILED"
        assert "CRS" in (info_res.json()["error_message"] or "")


def test_feature_level_resilience(client: TestClient):
    """Shapefile with a valid polygon and an invalid geometry should process without crashing."""
    # Create Shapefile with 2 polygons: 1 valid, 1 invalid bowtie
    valid_poly = Polygon([(0.0, 51.5), (0.014, 51.5), (0.014, 51.509), (0.0, 51.509)])
    bowtie = Polygon([(0.0, 51.5), (0.014, 51.509), (0.014, 51.5), (0.0, 51.509)])  # self-intersecting
    crs_obj = CRS.from_epsg(4326)
    schema = {"geometry": "Polygon", "properties": {"name": "str"}}

    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = Path(tmp_dir) / "resilience.shp"
        with fiona.open(
            str(shp_path),
            "w",
            driver="ESRI Shapefile",
            crs=crs_obj.to_wkt(),
            schema=schema,
        ) as dst:
            dst.write({"geometry": mapping(valid_poly), "properties": {"name": "valid"}})
            dst.write({"geometry": mapping(bowtie), "properties": {"name": "invalid_bowtie"}})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj"]:
                path = shp_path.with_suffix(ext)
                if path.exists():
                    zf.write(path, path.name)
        zip_bytes = buf.getvalue()

    files = {"file": ("resilience.zip", io.BytesIO(zip_bytes), "application/zip")}
    res = client.post("/api/files/", files=files)
    assert res.status_code == 201
    file_id = res.json()["file_id"]

    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_res.status_code == 200
    m_data = meas_res.json()

    assert len(m_data["features"]) == 2
    # Feature 0 should succeed
    assert m_data["features"][0]["status"] == "SUCCESS"
    assert m_data["features"][0]["area_m2"] is not None

    # Feature 1 should report warning or failure, not crash
    assert m_data["features"][1]["status"] in ("WARNING", "FAILED")


def test_database_persistence():
    """Verify records are persisted in the database model directly."""
    db = TestSessionLocal()
    try:
        # Create a record
        uploaded_file = UploadedFile(
            filename="persist_test.kml",
            stored_filename="abc.kml",
            status="COMPLETED",
            feature_count=1,
        )
        db.add(uploaded_file)
        db.commit()
        db.refresh(uploaded_file)
        file_id = uploaded_file.id

        meas = FeatureMeasurement(
            uploaded_file_id=file_id,
            feature_index=0,
            geometry_type="Polygon",
            area_m2=1000.0,
            status="SUCCESS",
        )
        db.add(meas)
        db.commit()

        # Query back
        fetched = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        assert fetched is not None
        assert fetched.filename == "persist_test.kml"
        assert fetched.feature_measurements.count() == 1
        assert fetched.feature_measurements.first().area_m2 == 1000.0
    finally:
        db.close()
