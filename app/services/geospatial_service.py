"""
Geospatial parsing service.

Responsible for reading geospatial files (KML and Shapefile-in-ZIP) into
GeoDataFrames.  No measurement logic lives here; see measurement_service.py
and crs_service.py.

File reading strategy
─────────────────────
KML:    Read via geopandas with the 'fiona' or 'pyogrio' engine.  KML always
        uses EPSG:4326 (WGS 84) as its CRS.
ZIP:    Extract only required Shapefile components to a temporary directory.
        The directory is cleaned up by the caller via a context manager.
        We never extract to a caller-supplied path.

Empty and corrupt file handling
────────────────────────────────
geopandas / fiona raise exceptions for unreadable files.  We catch those and
re-raise as CorruptFileError so the API layer can return a clean 400 response
without leaking library internals.
"""

import io
import logging
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import geopandas as gpd

from app.core.exceptions import CorruptFileError, MissingCRSError

logger = logging.getLogger(__name__)

# KML files are always in geographic coordinates (EPSG:4326) per the spec.
KML_DEFAULT_CRS = "EPSG:4326"


def read_kml(data: bytes) -> gpd.GeoDataFrame:
    """Parse KML bytes into a GeoDataFrame.

    GeoPandas reads KML via fiona (which delegates to the GDAL KML driver).
    KML is always in EPSG:4326 per the OGC specification.

    Args:
        data: Raw KML file bytes.

    Returns:
        A GeoDataFrame with at least a 'geometry' column and CRS set to
        EPSG:4326.

    Raises:
        CorruptFileError: If the data cannot be parsed as KML.
    """
    try:
        # Write to an in-memory buffer using a tmp file because fiona/GDAL
        # needs a seekable stream, and geopandas does not accept raw bytes directly.
        with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        try:
            try:
                gdf = gpd.read_file(tmp_path, engine="pyogrio")
            except Exception:
                gdf = gpd.read_file(tmp_path, engine="fiona")
        finally:
            tmp_path.unlink(missing_ok=True)

        if gdf is None or gdf.empty:
            raise CorruptFileError("The KML file contains no features.")

        # KML is always WGS84; fiona should set this but we enforce it.
        if gdf.crs is None:
            logger.warning("KML parsed with no CRS — setting to EPSG:4326 per KML spec.")
            gdf = gdf.set_crs(KML_DEFAULT_CRS)

        logger.info("KML parsed: %d features, CRS=%s", len(gdf), gdf.crs)
        return gdf

    except CorruptFileError:
        raise
    except Exception as exc:
        raise CorruptFileError(f"Failed to parse KML file: {exc}") from exc


@contextmanager
def extract_shapefile(zip_data: bytes) -> Generator[Path, None, None]:
    """Context manager that extracts a Shapefile from a ZIP to a temp directory.

    Yields the path to the directory containing the extracted Shapefile
    components.  The directory and all its contents are deleted on exit.

    Args:
        zip_data: Raw bytes of the ZIP archive (already validated).

    Yields:
        Path to the temporary extraction directory.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="geomeasure_shp_"))
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), "r") as zf:
            # Extract to a sandboxed temp directory; zip_safety has already
            # verified there are no path-traversal entries.
            zf.extractall(tmp_dir)
        logger.debug("Shapefile extracted to %s", tmp_dir)
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.debug("Temp extraction dir cleaned up: %s", tmp_dir)


def read_shapefile(tmp_dir: Path) -> gpd.GeoDataFrame:
    """Read a Shapefile from a temporary extraction directory.

    Searches for the first .shp file in the directory tree and reads it.

    Args:
        tmp_dir: Path to a directory containing extracted Shapefile components.

    Returns:
        A GeoDataFrame with geometry and attribute columns.

    Raises:
        CorruptFileError: If no .shp is found or it cannot be parsed.
        MissingCRSError: If the Shapefile has no .prj and no CRS can be inferred.
    """
    shp_files = list(tmp_dir.rglob("*.shp"))
    if not shp_files:
        raise CorruptFileError("No .shp file found after extracting ZIP.")

    shp_path = shp_files[0]
    logger.info("Reading Shapefile: %s", shp_path)

    try:
        try:
            gdf = gpd.read_file(shp_path, engine="pyogrio")
        except Exception:
            gdf = gpd.read_file(shp_path, engine="fiona")
    except Exception as exc:
        raise CorruptFileError(f"Failed to read Shapefile {shp_path.name}: {exc}") from exc

    if gdf is None or gdf.empty:
        raise CorruptFileError("The Shapefile contains no features.")

    if gdf.crs is None:
        # A missing .prj means we have no authoritative CRS.  We explicitly
        # raise rather than silently assuming EPSG:4326.
        raise MissingCRSError(
            "The Shapefile has no .prj file and no CRS could be determined. "
            "Measurements cannot be performed safely without a known CRS."
        )

    logger.info("Shapefile parsed: %d features, CRS=%s", len(gdf), gdf.crs)
    return gdf
