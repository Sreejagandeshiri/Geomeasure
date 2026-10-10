"""
CRS selection and transformation service.

Design goals
────────────
1. Never calculate planar measurements on raw EPSG:4326 (lon/lat) data.
2. Choose a projection that minimises distortion for the dataset's actual
   geographic extent rather than blindly applying one projection globally.
3. Be explicit about what CRS was used so callers can report it.
4. Fail loudly when no safe projection can be determined.

Projection strategy (documented as required by the assignment)
──────────────────────────────────────────────────────────────
For POLYGON AREAS we always use an *equal-area* projection:
  • ESRI:54034  World Cylindrical Equal Area — used as the global fallback.
    This projection distorts shape but preserves area and is appropriate for
    datasets that cross UTM zones or span very large areas.
  • For datasets confined to a single UTM zone we could use the zone's UTM
    CRS, but we still prefer equal-area for correctness.  UTM is conformal
    (preserves shape), not equal-area, so polygon areas in UTM are approximate.

For LINE LENGTHS we use a *local projected* CRS that minimises distortion near
the centroid:
  • UTM zone derived from the dataset centroid.
  • World Mercator (EPSG:3395) as a fallback for datasets with no clear centroid
    (e.g. crossing the antimeridian).

Limitations
───────────
* Very large datasets (global or continental extent) will have measurable
  distortion even in equal-area projections; ESRI:54034 is the best readily
  available global equal-area projection without requiring PROJ datum grids.
* The UTM zone chosen for line measurement is derived from the centroid; features
  near UTM zone boundaries may experience slightly higher distortion.
* Datasets crossing the antimeridian are not currently handled; they will be
  transformed to World Mercator which may produce incorrect centroids.
"""

import logging
from typing import Optional

import geopandas as gpd
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

from app.core.exceptions import CRSTransformError, MissingCRSError

logger = logging.getLogger(__name__)

# Global equal-area CRS for polygon area calculations.
EQUAL_AREA_CRS = CRS.from_user_input("ESRI:54034")

# World Mercator — fallback for line length when UTM cannot be determined.
WORLD_MERCATOR_CRS = CRS.from_user_input("EPSG:3395")


def get_utm_crs_for_point(lon: float, lat: float) -> CRS:
    """Return the UTM CRS appropriate for a given (lon, lat) coordinate.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        A pyproj CRS object for the appropriate UTM zone.
    """
    zone_number = int((lon + 180) / 6) + 1
    hemisphere = "north" if lat >= 0 else "south"
    # UTM EPSG codes: 32600+zone (north), 32700+zone (south)
    epsg = 32600 + zone_number if hemisphere == "north" else 32700 + zone_number
    return CRS.from_epsg(epsg)


def determine_measurement_crs(
    gdf: gpd.GeoDataFrame,
    purpose: str = "area",  # "area" | "length"
) -> tuple[CRS, str]:
    """Choose the most appropriate projected CRS for measurement.

    Args:
        gdf: GeoDataFrame in its source CRS (must already have crs set).
        purpose: "area" to prefer equal-area, "length" to prefer UTM.

    Returns:
        Tuple of (CRS object, human-readable explanation string).

    Raises:
        MissingCRSError: If gdf has no CRS.
    """
    if gdf.crs is None:
        raise MissingCRSError("GeoDataFrame has no CRS — cannot determine measurement projection.")

    if purpose == "area":
        return EQUAL_AREA_CRS, f"World Cylindrical Equal Area (ESRI:54034) selected for polygon area calculation"

    # For line lengths: project to geographic (EPSG:4326) to get centroid lon/lat,
    # then select the appropriate UTM zone.
    try:
        # Work with a copy in WGS84 to compute centroid safely.
        gdf_4326 = gdf.to_crs("EPSG:4326")
        all_geoms = gdf_4326.geometry.dropna()
        if all_geoms.empty:
            return WORLD_MERCATOR_CRS, "World Mercator (EPSG:3395) — no valid geometries to determine centroid"

        # Dissolve into a single bounding box to find overall centroid.
        total_bounds = gdf_4326.total_bounds  # (minx, miny, maxx, maxy)
        minx, miny, maxx, maxy = total_bounds
        centroid_lon = (minx + maxx) / 2
        centroid_lat = (miny + maxy) / 2

        # Sanity check: bounds should be within WGS84 range.
        if not (-180 <= centroid_lon <= 180 and -90 <= centroid_lat <= 90):
            logger.warning(
                "Centroid (%f, %f) is outside WGS84 bounds; falling back to World Mercator.",
                centroid_lon,
                centroid_lat,
            )
            return WORLD_MERCATOR_CRS, "World Mercator (EPSG:3395) — centroid outside valid range"

        utm_crs = get_utm_crs_for_point(centroid_lon, centroid_lat)
        explanation = (
            f"UTM zone derived from dataset centroid "
            f"({centroid_lon:.2f}°, {centroid_lat:.2f}°): {utm_crs.to_string()}"
        )
        return utm_crs, explanation

    except Exception as exc:
        logger.warning("Could not determine UTM CRS (%s); falling back to World Mercator.", exc)
        return WORLD_MERCATOR_CRS, f"World Mercator (EPSG:3395) — UTM detection failed: {exc}"


def transform_geometry(
    geometry: BaseGeometry,
    source_crs: CRS,
    target_crs: CRS,
) -> BaseGeometry:
    """Transform a single Shapely geometry from source_crs to target_crs.

    Args:
        geometry: A Shapely geometry object.
        source_crs: The CRS the geometry is currently in.
        target_crs: The CRS to transform into.

    Returns:
        A new Shapely geometry in target_crs.

    Raises:
        CRSTransformError: If the transformation fails.
    """
    if source_crs.equals(target_crs):
        return geometry

    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        import shapely
        import numpy as np

        def _transform_coords(coords: np.ndarray) -> np.ndarray:
            x, y = transformer.transform(coords[:, 0], coords[:, 1])
            return np.column_stack((x, y))

        return shapely.transform(geometry, _transform_coords)
    except Exception as exc:
        raise CRSTransformError(
            f"Failed to transform geometry from {source_crs.to_string()} "
            f"to {target_crs.to_string()}: {exc}"
        ) from exc


def get_source_crs(gdf: gpd.GeoDataFrame) -> Optional[CRS]:
    """Extract and return the source CRS from a GeoDataFrame, or None.

    We deliberately return None rather than assuming EPSG:4326 when the CRS
    is absent, because silently assuming geographic coordinates can produce
    grossly incorrect measurements.

    Args:
        gdf: A GeoDataFrame loaded from a geospatial file.

    Returns:
        The source CRS, or None if it is not set.
    """
    return gdf.crs if gdf.crs is not None else None


def crs_to_string(crs: Optional[CRS]) -> Optional[str]:
    """Convert a pyproj CRS to a short human-readable string.

    Prefers the EPSG authority code (e.g. "EPSG:4326") for well-known CRSes,
    falling back to PROJ string for custom CRSes.

    Args:
        crs: A CRS object, or None.

    Returns:
        A string like "EPSG:4326", or None if crs is None.
    """
    if crs is None:
        return None
    try:
        authority = crs.to_authority()
        if authority:
            return f"{authority[0]}:{authority[1]}"
        return crs.to_string()
    except Exception:
        return str(crs)
