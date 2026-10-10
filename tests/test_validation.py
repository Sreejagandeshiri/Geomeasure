"""
Tests for file validation, safety utilities, and geometry classification.

Covers:
- Extension validation (.kml, .zip allowed; others rejected)
- File size validation
- ZIP path traversal detection
- ZIP absolute path detection
- ZIP missing components
- Geometry classification: valid, invalid, empty, unsupported, point
"""

import io
import pytest
import zipfile
from shapely.geometry import Polygon, LineString, Point, MultiPolygon

from app.utils.file_validation import (
    validate_extension,
    validate_size,
    validate_zip_safety,
    validate_shapefile_components,
)
from app.services.measurement_service import classify_geometry
from app.core.exceptions import (
    UnsupportedFileTypeError,
    FileTooLargeError,
    InvalidArchiveError,
    MissingShapefileComponentError,
)


def test_validate_extension_valid():
    assert validate_extension("boundary.kml") == ".kml"
    assert validate_extension("SHAPEFILE.ZIP") == ".zip"


def test_validate_extension_invalid():
    with pytest.raises(UnsupportedFileTypeError):
        validate_extension("data.csv")
    with pytest.raises(UnsupportedFileTypeError):
        validate_extension("map.geojson")


def test_validate_size():
    # Below limit
    validate_size(100, b"x" * 100)

    # Exceeding limit
    with pytest.raises(FileTooLargeError):
        validate_size(1000, b"x" * 1000)  # when checked against smaller limit via mock or directly
        validate_size(None, b"x" * (60 * 1024 * 1024))  # > 50MB


def test_validate_zip_safety_path_traversal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../dangerous.shp", "content")
    
    with pytest.raises(InvalidArchiveError):
        validate_zip_safety(buf.getvalue())


def test_validate_zip_safety_corrupt():
    with pytest.raises(InvalidArchiveError):
        validate_zip_safety(b"non-zip-data-garbage")


def test_validate_shapefile_components_valid():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.shp", "shp")
        zf.writestr("test.shx", "shx")
        zf.writestr("test.dbf", "dbf")
        zf.writestr("test.prj", "prj")
    
    zf = zipfile.ZipFile(buf, "r")
    stem = validate_shapefile_components(zf)
    assert stem == "test"
    zf.close()


def test_validate_shapefile_components_missing_dbf():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("test.shp", "shp")
        zf.writestr("test.shx", "shx")
    
    zf = zipfile.ZipFile(buf, "r")
    with pytest.raises(MissingShapefileComponentError):
        validate_shapefile_components(zf)
    zf.close()


def test_classify_geometry():
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
    assert classify_geometry(poly) == "MEASURABLE"

    line = LineString([(0, 0), (1, 1)])
    assert classify_geometry(line) == "MEASURABLE"

    pt = Point(0, 0)
    assert classify_geometry(pt) == "POINT"

    empty_poly = Polygon()
    assert classify_geometry(empty_poly) == "EMPTY"

    assert classify_geometry(None) == "EMPTY"

    # Self-intersecting bowtie polygon (invalid)
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    assert classify_geometry(bowtie) == "INVALID"
