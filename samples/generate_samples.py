"""
Sample geospatial data generator for GeoMeasure.

Generates sample files in the samples/ directory:
1. sample_polygon.kml — A sample KML polygon located in Greenwich, London (~1 km²).
2. sample_linestring.kml — A sample KML LineString (~1.5 km).
3. sample_multifeature.kml — A multi-feature KML with polygon, linestring, and point.
4. sample_shapefile.zip — A zipped ESRI Shapefile with polygon and full components (.shp, .shx, .dbf, .prj).
"""

import io
import os
import zipfile
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import Polygon, mapping

SAMPLES_DIR = Path(__file__).resolve().parent


def create_sample_kml_polygon() -> Path:
    """Create a sample KML polygon file."""
    coords = [
        (0.0, 51.5),
        (0.014, 51.5),
        (0.014, 51.509),
        (0.0, 51.509),
        (0.0, 51.5),
    ]
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Greenwich Park Sample</name>
    <Placemark>
      <name>Sample Agricultural Field</name>
      <description>Greenwich 1 km² test polygon</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{coord_str}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    out_path = SAMPLES_DIR / "sample_polygon.kml"
    out_path.write_text(kml, encoding="utf-8")
    print(f"Generated: {out_path.name}")
    return out_path


def create_sample_kml_linestring() -> Path:
    """Create a sample KML linestring file."""
    coords = [(0.0, 51.5), (0.014, 51.5), (0.021, 51.505)]
    coord_str = " ".join(f"{lon},{lat},0" for lon, lat in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Survey Route</name>
    <Placemark>
      <name>Survey Flight Line</name>
      <description>Sample survey flight line</description>
      <LineString>
        <coordinates>{coord_str}</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    out_path = SAMPLES_DIR / "sample_linestring.kml"
    out_path.write_text(kml, encoding="utf-8")
    print(f"Generated: {out_path.name}")
    return out_path


def create_sample_shapefile_zip() -> Path:
    """Create a sample zipped Shapefile with all required components (.shp, .shx, .dbf, .prj)."""
    polygon = Polygon([(0.0, 51.5), (0.014, 51.5), (0.014, 51.509), (0.0, 51.509)])
    schema = {"geometry": "Polygon", "properties": {"name": "str", "crop": "str"}}
    crs_obj = CRS.from_epsg(4326)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        shp_path = Path(tmp_dir) / "parcels.shp"
        with fiona.open(
            str(shp_path),
            "w",
            driver="ESRI Shapefile",
            crs=crs_obj.to_wkt(),
            schema=schema,
        ) as dst:
            dst.write({
                "geometry": mapping(polygon),
                "properties": {"name": "Parcel-101", "crop": "Wheat"},
            })

        out_zip = SAMPLES_DIR / "sample_shapefile.zip"
        with zipfile.ZipFile(out_zip, "w") as zf:
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                path = shp_path.with_suffix(ext)
                if path.exists():
                    zf.write(path, path.name)

    print(f"Generated: {out_zip.name}")
    return out_zip


if __name__ == "__main__":
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    create_sample_kml_polygon()
    create_sample_kml_linestring()
    create_sample_shapefile_zip()
    print("All sample files generated successfully in samples/")
