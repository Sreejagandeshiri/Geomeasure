"""
Measurement service: calculates area and length for individual geometries.

All measurements are performed on *projected* geometries (never on raw
longitude/latitude coordinates).  The caller is responsible for supplying
already-transformed geometries; this module focuses only on the arithmetic
and unit conversion.

Geometry support matrix
───────────────────────
  Geometry type       Area    Length  Notes
  ─────────────────── ─────── ─────── ─────────────────────────────────────────
  Polygon             ✓       —       Holes handled automatically by Shapely.
  MultiPolygon        ✓       —       Sum of all sub-polygon areas.
  LineString          —       ✓
  MultiLineString     —       ✓       Sum of all sub-line lengths.
  Point / MultiPoint  —       —       No measurement applicable.
  Other               —       —       Reported as UNSUPPORTED.
"""

import logging
from typing import Optional

from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)

# Geometry type names that produce area measurements.
AREA_TYPES = {"Polygon", "MultiPolygon"}

# Geometry type names that produce length measurements.
LENGTH_TYPES = {"LineString", "MultiLineString"}

# Geometry types we recognise but cannot measure.
POINT_TYPES = {"Point", "MultiPoint"}

_M2_PER_HA = 10_000.0
_M_PER_KM = 1_000.0


def calculate_area(geometry: BaseGeometry) -> tuple[Optional[float], Optional[float]]:
    """Calculate polygon area from a *projected* geometry.

    Args:
        geometry: A Shapely Polygon or MultiPolygon in a projected CRS
                  (units must be metres).

    Returns:
        Tuple of (area_m2, area_ha).  Both values are unrounded floats.
        Returns (None, None) for non-polygon geometries.
    """
    if geometry is None or geometry.is_empty:
        return None, None

    geom_type = geometry.geom_type
    if geom_type not in AREA_TYPES:
        return None, None

    area_m2 = float(geometry.area)
    area_ha = area_m2 / _M2_PER_HA
    return area_m2, area_ha


def calculate_length(geometry: BaseGeometry) -> tuple[Optional[float], Optional[float]]:
    """Calculate line length from a *projected* geometry.

    Args:
        geometry: A Shapely LineString or MultiLineString in a projected CRS
                  (units must be metres).

    Returns:
        Tuple of (length_m, length_km).  Both values are unrounded floats.
        Returns (None, None) for non-line geometries.
    """
    if geometry is None or geometry.is_empty:
        return None, None

    geom_type = geometry.geom_type
    if geom_type not in LENGTH_TYPES:
        return None, None

    length_m = float(geometry.length)
    length_km = length_m / _M_PER_KM
    return length_m, length_km


def classify_geometry(geometry: Optional[BaseGeometry]) -> str:
    """Return a feature-level status based on geometry validity.

    Statuses:
      MEASURABLE   — geometry is valid and has a supported type.
      POINT        — geometry is a Point/MultiPoint (no measurement needed).
      UNSUPPORTED  — geometry type is not in our support matrix.
      INVALID      — geometry is not None/empty but fails Shapely's is_valid.
      EMPTY        — geometry is None or empty.

    Args:
        geometry: A Shapely geometry or None.

    Returns:
        One of the status strings above.
    """
    if geometry is None or geometry.is_empty:
        return "EMPTY"

    geom_type = geometry.geom_type
    if geom_type in AREA_TYPES or geom_type in LENGTH_TYPES:
        if not geometry.is_valid:
            return "INVALID"
        return "MEASURABLE"

    if geom_type in POINT_TYPES:
        return "POINT"

    return "UNSUPPORTED"


def round_measurement(value: Optional[float], decimals: int = 4) -> Optional[float]:
    """Round a measurement value for presentation only.

    We store full-precision floats in the database and round only when
    building the API response to avoid compounding rounding errors.

    Args:
        value: The raw measurement value.
        decimals: Number of decimal places.

    Returns:
        Rounded float, or None if value is None.
    """
    if value is None:
        return None
    return round(value, decimals)
