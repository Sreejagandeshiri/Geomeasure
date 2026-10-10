"""
Dedicated CRS transformation and measurement accuracy tests.

Requirements:
- Never calculate planar polygon area or line length directly from lon/lat (EPSG:4326).
- Correct polygon area for a known geometry in projected CRS.
- Correct LineString length for a known geometry in projected CRS.
- CRS transformation from EPSG:4326 to projected CRS.
- Missing or invalid CRS handling.
"""

import math
import pytest
import geopandas as gpd
from pyproj import CRS
from shapely.geometry import Polygon, LineString, Point

from app.services.crs_service import (
    determine_measurement_crs,
    transform_geometry,
    get_utm_crs_for_point,
    EQUAL_AREA_CRS,
    crs_to_string,
)
from app.services.measurement_service import calculate_area, calculate_length
from app.core.exceptions import MissingCRSError


def test_utm_zone_determination():
    """Verify UTM zone calculation for various global coordinates."""
    # London (~0° lon, 51.5° lat): Zone 30 North or 31 North
    # (0 + 180) / 6 + 1 = 30 + 1 = 31
    utm_london = get_utm_crs_for_point(0.0, 51.5)
    assert utm_london.to_epsg() == 32631

    # New York (~ -74° lon, 40.7° lat): (-74 + 180)/6 + 1 = 18.66 -> 18 North -> 32618
    utm_ny = get_utm_crs_for_point(-74.0, 40.7)
    assert utm_ny.to_epsg() == 32618

    # Sydney (~ 151° lon, -33.8° lat): (151 + 180)/6 + 1 = 56 South -> 32756
    utm_sydney = get_utm_crs_for_point(151.0, -33.8)
    assert utm_sydney.to_epsg() == 32756


def test_missing_crs_raises_error():
    """determine_measurement_crs must raise MissingCRSError when gdf has no CRS."""
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    gdf_no_crs = gpd.GeoDataFrame({"geometry": [poly]}, crs=None)

    with pytest.raises(MissingCRSError):
        determine_measurement_crs(gdf_no_crs, purpose="area")


def test_projected_polygon_known_area():
    """Test known 100m x 200m rectangle in UTM CRS directly (20,000 m² = 2 ha)."""
    # 100m wide, 200m high rectangle
    rect = Polygon([(500000, 4000000), (500100, 4000000), (500100, 4000200), (500000, 4000200)])
    area_m2, area_ha = calculate_area(rect)

    assert area_m2 == pytest.approx(20000.0, rel=1e-5)
    assert area_ha == pytest.approx(2.0, rel=1e-5)


def test_projected_linestring_known_length():
    """Test known 1,500m LineString in UTM CRS directly (1,500m = 1.5 km)."""
    line = LineString([(500000, 4000000), (501500, 4000000)])
    len_m, len_km = calculate_length(line)

    assert len_m == pytest.approx(1500.0, rel=1e-5)
    assert len_km == pytest.approx(1.5, rel=1e-5)


def test_polygon_with_hole():
    """Test polygon with interior ring (hole): 100x100 square with 20x20 hole = 9,600 m²."""
    exterior = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(40, 40), (60, 40), (60, 60), (40, 60)]
    poly_hole = Polygon(exterior, [hole])

    area_m2, area_ha = calculate_area(poly_hole)
    assert area_m2 == pytest.approx(9600.0, rel=1e-5)
    assert area_ha == pytest.approx(0.96, rel=1e-5)


def test_geographic_to_projected_transformation():
    """Test transformation from EPSG:4326 to equal-area projection and check area reasonable."""
    # ~1 deg at equator is ~111.32 km. A 0.01 deg square at equator is ~1.1132 km x 1.1132 km ≈ 1.24 km² = 1.24e6 m²
    poly_wgs84 = Polygon([(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)])
    source_crs = CRS.from_epsg(4326)

    projected_geom = transform_geometry(poly_wgs84, source_crs, EQUAL_AREA_CRS)
    area_m2, area_ha = calculate_area(projected_geom)

    # 1.2e6 m² <= area <= 1.3e6 m²
    assert 1_200_000 <= area_m2 <= 1_300_000
    assert 120 <= area_ha <= 130


def test_crs_to_string_formatting():
    """Test crs_to_string correctly formats well-known and custom CRSes."""
    crs_4326 = CRS.from_epsg(4326)
    assert crs_to_string(crs_4326) == "EPSG:4326"

    crs_utm = CRS.from_epsg(32630)
    assert crs_to_string(crs_utm) == "EPSG:32630"
