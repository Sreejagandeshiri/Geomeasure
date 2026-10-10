"""
Pytest configuration and shared fixtures for GeoMeasure tests.

Test isolation strategy
───────────────────────
* Each test run uses a separate in-memory SQLite database so tests never
  touch the production database.
* Uploaded files go to a per-test temporary directory that is cleaned up
  after each test.
* The FastAPI TestClient is configured with a database session override so
  that the same session used by the service is used by the assertions.
"""

import io
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Override config before the app is imported so that the test db and upload
# directory are used instead of the production ones.
_test_upload_dir = tempfile.mkdtemp(prefix="geomeasure_test_uploads_")
os.environ["DATABASE_URL"] = "sqlite://"   # in-memory SQLite
os.environ["UPLOAD_DIR"] = _test_upload_dir


from app.db.database import Base, get_db
import app.main as app_main

fastapi_app = app_main.app

# ── Test database setup ───────────────────────────────────────────────────────

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # share the same in-memory connection across the session
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


def _override_get_db() -> Generator[Session, None, None]:
    """Dependency override that uses the test database."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Create tables once for the entire test module.
import app.db.models  # noqa: F401 — ensures models are registered before create_all
Base.metadata.create_all(bind=TEST_ENGINE)

fastapi_app.dependency_overrides[get_db] = _override_get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Yield a clean database session; roll back all changes after each test."""
    connection = TEST_ENGINE.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """FastAPI test client with test database dependency override."""
    with TestClient(fastapi_app) as c:
        yield c


# ── Sample file factories ─────────────────────────────────────────────────────

def make_kml_polygon(
    name: str = "test_polygon",
    coords: list[tuple[float, float]] | None = None,
) -> bytes:
    """Generate a minimal KML file with a single polygon feature.

    Args:
        name: Feature name.
        coords: List of (lon, lat) tuples.  Defaults to a ~1 km² square
                near London so tests have a known geometry.

    Returns:
        KML file bytes.
    """
    if coords is None:
        # A ~1 km² square around (0°, 51.5°) — Greenwich, London.
        # At this latitude 0.009° lat ≈ 1 km and 0.014° lon ≈ 1 km.
        coords = [
            (0.0, 51.5),
            (0.014, 51.5),
            (0.014, 51.509),
            (0.0, 51.509),
            (0.0, 51.5),  # close the ring
        ]
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>{name}</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>{coord_str}</coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
</kml>"""
    return kml.encode("utf-8")


def make_kml_linestring(
    name: str = "test_line",
    coords: list[tuple[float, float]] | None = None,
) -> bytes:
    """Generate a minimal KML file with a single LineString feature."""
    if coords is None:
        # A ~1 km east-west line at Greenwich.
        coords = [(0.0, 51.5), (0.014, 51.5)]
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>{name}</name>
    <LineString>
      <coordinates>{coord_str}</coordinates>
    </LineString>
  </Placemark>
</kml>"""
    return kml.encode("utf-8")


def make_kml_point(name: str = "test_point") -> bytes:
    """Generate a minimal KML file with a single Point feature."""
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>{name}</name>
    <Point>
      <coordinates>0.0,51.5,0</coordinates>
    </Point>
  </Placemark>
</kml>"""
    return kml.encode("utf-8")


def make_kml_multi_feature() -> bytes:
    """Generate a KML with polygon, line, and point features."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>poly</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>0.0,51.5,0 0.014,51.5,0 0.014,51.509,0 0.0,51.509,0 0.0,51.5,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>line</name>
      <LineString>
        <coordinates>0.0,51.5,0 0.014,51.5,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>point</name>
      <Point>
        <coordinates>0.0,51.5,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    return kml.encode("utf-8")


def make_shapefile_zip(
    crs_epsg: int = 4326,
    include_prj: bool = True,
    include_shx: bool = True,
    include_dbf: bool = True,
) -> bytes:
    """Generate a valid zipped Shapefile with a single polygon feature.

    Uses fiona to write a real Shapefile into a BytesIO buffer, then zips it.

    Args:
        crs_epsg: EPSG code for the CRS.
        include_prj: Whether to include the .prj file.
        include_shx: Whether to include the .shx file.
        include_dbf: Whether to include the .dbf file.

    Returns:
        ZIP file bytes.
    """
    import fiona
    import tempfile
    from pyproj import CRS
    from shapely.geometry import mapping, Polygon

    polygon = Polygon([(0.0, 51.5), (0.014, 51.5), (0.014, 51.509), (0.0, 51.509)])
    schema = {"geometry": "Polygon", "properties": {"name": "str"}}
    crs_obj = CRS.from_epsg(crs_epsg)

    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = Path(tmp_dir) / "test.shp"
        with fiona.open(
            str(shp_path),
            "w",
            driver="ESRI Shapefile",
            crs=crs_obj.to_wkt(),
            schema=schema,
        ) as dst:
            dst.write({"geometry": mapping(polygon), "properties": {"name": "test"}})

        # Collect the generated component files.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                path = shp_path.with_suffix(ext)
                skip = (
                    (ext == ".prj" and not include_prj)
                    or (ext == ".shx" and not include_shx)
                    or (ext == ".dbf" and not include_dbf)
                )
                if path.exists() and not skip:
                    zf.write(path, path.name)
        return buf.getvalue()


def make_corrupt_zip() -> bytes:
    """Return bytes that look like a ZIP header but are corrupt."""
    return b"PK\x03\x04" + b"\x00" * 100


def make_corrupt_kml() -> bytes:
    """Return bytes that are not valid KML/XML."""
    return b"NOT_VALID_KML_CONTENT_AT_ALL @@@@"
