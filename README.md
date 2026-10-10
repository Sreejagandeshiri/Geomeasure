# GeoMeasure — Geospatial File Measurement & Validation API

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.13-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![GeoPandas](https://img.shields.io/badge/GeoPandas-1.2+-green.svg)](https://geopandas.org/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Pytest-38%20Passed-brightgreen.svg)]()

> A production-minded geospatial intelligence REST API developed for the software development internship assignment at **AEREO**.

GeoMeasure ingests geospatial files (`.kml` and zipped Shapefiles `.zip`), securely validates archives against path traversal and file corruption, dynamically determines the optimal projected Coordinate Reference System (CRS) for measurement accuracy, extracts features and attributes, computes rigorous planar measurements (area in $\text{m}^2$/hectares, length in $\text{m}$/$\text{km}$), and persists structured results for retrieval via REST endpoints.

---

## Table of Contents

1. [Key Features](#1-key-features)
2. [Technology Stack](#2-technology-stack)
3. [Architecture & Workflow](#3-architecture--workflow)
4. [Folder Structure](#4-folder-structure)
5. [CRS Handling & Measurement Strategy](#5-crs-handling--measurement-strategy)
6. [Database Design & Persistence Decisions](#6-database-design--persistence-decisions)
7. [Installation & Setup](#7-installation--setup)
8. [Running the Application](#8-running-the-application)
9. [API Documentation & Endpoints](#9-api-documentation--endpoints)
10. [Automated Testing](#10-automated-testing)
11. [Sample Files & Demonstration](#11-sample-files--demonstration)
12. [Design Decisions & Alternatives](#12-design-decisions--alternatives)
13. [Security Considerations](#13-security-considerations)
14. [Known Limitations](#14-known-limitations)
15. [What I Learned](#15-what-i-learned)
16. [Future Scope](#16-future-scope)
17. [Docker Deployment](#17-docker-deployment)

---

## 1. Key Features

- **Multi-Format Geospatial Ingestion**: Supports `.kml` and `.zip` archives containing ESRI Shapefiles (`.shp`, `.shx`, `.dbf`, `.prj`).
- **Defensive Archive Validation**: Pre-flight inspection of ZIP directory tables detecting directory traversal attacks (`../`), absolute paths, and missing required Shapefile components before unpacking.
- **Strict CRS Handling**: Preserves source CRSes; refuses to silently calculate planar calculations directly on geographic angular degrees ($\text{EPSG:4326}$).
- **Automatic Projection Selection**:
  - *Polygons*: Projected to equal-area projections ($\text{ESRI:54034}$ World Cylindrical Equal Area) for distortion-free area calculations in square metres ($\text{m}^2$) and hectares ($\text{ha}$).
  - *LineStrings*: Dynamically projected to the optimal local Universal Transverse Mercator (UTM) zone calculated from the dataset centroid for minimal length distortion.
- **Robust Feature Resilience**: Feature-level errors (e.g. self-intersecting geometries, corrupt coordinates, points) are isolated and flagged with warnings without aborting valid features in the dataset.
- **Denormalized Fast Retrieval**: Summary statistics and quality metrics are pre-computed during ingestion for rapid $O(1)$ query retrieval.
- **Interactive Documentation**: Full OpenAPI specification and Swagger UI rendered out of the box at `/docs`.

---

## 2. Technology Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (high performance, typed async web framework)
- **ASGI Server**: [Uvicorn](https://www.uvicorn.org/) (lightning-fast ASGI web server)
- **Geospatial Processing**:
  - [GeoPandas](https://geopandas.org/): Vector data manipulation
  - [Shapely](https://shapely.readthedocs.io/): Planar geometric operations and validation
  - [PyProj](https://pyproj4.github.io/pyproj/): Coordinate Reference System transformations and PROJ interfaces
  - [Pyogrio](https://pyogrio.readthedocs.io/) & [Fiona](https://fiona.readthedocs.io/): GDAL vector driver interfaces
- **Database & ORM**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with SQLite (configurable to PostgreSQL/PostGIS)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/) for strict schema validation
- **Testing**: [Pytest](https://docs.pytest.org/) and FastAPI TestClient (HTTPX)

---

## 3. Architecture & Workflow

```
[ Geospatial Upload (.kml / .zip) ]
                 │
                 ▼
     [ 1. Extension & Size Check ]
                 │
                 ▼
     [ 2. Safe Archive Inspection ] ──(Corrupt / Malicious)──► HTTP 400/413/415/422
                 │
                 ▼
     [ 3. Atomic File Storage (UUID) ]
                 │
                 ▼
     [ 4. Driver Ingestion (Pyogrio/Fiona) ]
                 │
                 ▼
     [ 5. CRS Detection & Transformation ]
          ├─ Polygon: Equal-Area (ESRI:54034)
          └─ LineString: Local UTM Zone
                 │
                 ▼
     [ 6. Per-Feature Measurement & Validation ]
          ├─ Polygon: m² and hectares (handles holes & multipart)
          ├─ Line: metres and kilometres
          └─ Point: marked SUCCESS with null measurements
                 │
                 ▼
     [ 7. SQLite Database Persistence (UploadedFile + FeatureMeasurements) ]
                 │
                 ▼
     [ 8. Response (JSON with File ID & Status) ]
```

---

## 4. Folder Structure

```
geomeasure/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory, lifespan, error handlers
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── files.py            # POST /api/files/, GET /api/files/, DELETE
│   │       └── measurements.py     # GET /api/files/{id}/measurements/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # Environment configuration via Pydantic/Settings
│   │   ├── exceptions.py           # Custom exception hierarchy
│   │   └── logging_config.py       # Structured logging configuration
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py             # SQLAlchemy session and engine management
│   │   └── models.py               # UploadedFile & FeatureMeasurement models
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── errors.py               # Standardized error response models
│   │   ├── files.py                # Upload, info, and list response schemas
│   │   └── measurements.py         # Measurement and Quality Report schemas
│   ├── services/
│   │   ├── __init__.py
│   │   ├── crs_service.py          # Optimal CRS selection and transformation
│   │   ├── file_service.py         # High-level pipeline coordinator
│   │   ├── geospatial_service.py   # Driver parser (KML & Shapefile)
│   │   ├── measurement_service.py  # Area/length calculations & geometry classifier
│   │   └── storage_service.py      # Secure atomic file storage on disk
│   └── utils/
│       ├── __init__.py
│       └── file_validation.py      # Archive safety, extension, and component checks
├── samples/
│   ├── generate_samples.py         # Deterministic sample dataset generator
│   ├── sample_polygon.kml
│   ├── sample_linestring.kml
│   └── sample_shapefile.zip
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures, in-memory DB, sample factories
│   ├── test_crs.py                 # CRS transform & math precision tests
│   ├── test_error_handling.py      # Error responses & DB persistence tests
│   ├── test_file_information.py   # Info, pagination, and deletion tests
│   ├── test_measurements.py        # Measurement calculations & quality report tests
│   ├── test_upload.py              # File upload validation tests
│   └── test_validation.py          # Archive safety & geometry classifier tests
├── .env.example
├── .gitignore
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 5. CRS Handling & Measurement Strategy

### The Problem with EPSG:4326 Planar Calculations
Geographic coordinate systems such as $\text{EPSG:4326}$ (WGS 84) measure positions in angular degrees ($\text{longitude}, \text{latitude}$). Computing Euclidean area ($\Delta x \times \Delta y$) directly on degree coordinates results in meaningless square degrees ($\text{deg}^2$). Because meridians converge towards the poles, 1 degree of longitude is ~111.32 km at the equator but shrinks to 0 km at the poles. Planar calculations on unprojected coordinates introduce severe errors.

### The GeoMeasure Strategy
1. **Source CRS Preservation**: KML datasets default strictly to $\text{EPSG:4326}$ per OGC specifications. Shapefiles must declare their projection via `.prj`. If a Shapefile lacks a `.prj`, GeoMeasure halts processing and raises an explicit error rather than making silent assumptions.
2. **Polygon Area Measurements**:
   - Equal-area projection: GeoMeasure projects polygons into **$\text{ESRI:54034}$ (World Cylindrical Equal Area)** or equivalent equal-area projection.
   - Preserves true surface area across all latitudes regardless of UTM zone boundaries or continental extents.
   - Handles inner holes (`LinearRing`) and multipart polygons (`MultiPolygon`) automatically.
3. **LineString Length Measurements**:
   - Conformal / local projection: GeoMeasure computes the geographic centroid of the dataset and calculates the exact Universal Transverse Mercator (UTM) zone ($\text{EPSG:32601}$–$\text{32660}$ for North, $\text{32701}$–$\text{32760}$ for South).
   - Minimizes local distance distortion to $< 0.1\%$ along the central meridian.
4. **Precision**: Unrounded floating point values are stored internally and in the database. Rounding is applied only at API serialization.

---

## 6. Database Design & Persistence Decisions

### Relational Schema

#### `uploaded_files` Table
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Auto-increment primary key |
| `filename` | VARCHAR(255) | Original uploaded file name |
| `stored_filename` | VARCHAR(255) | Server-side UUID storage reference |
| `source_crs` | VARCHAR(128) | Detected source CRS (e.g. `EPSG:4326`) |
| `feature_count` | INTEGER | Number of features found |
| `status` | VARCHAR(32) | `PROCESSING`, `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED` |
| `created_at` | DATETIME | Timestamp when upload started |
| `completed_at` | DATETIME | Timestamp when processing finished |
| `error_message` | TEXT | Diagnostics if status is `FAILED` |
| `success_count` | INTEGER | Denormalized count of successfully measured features |
| `failure_count` | INTEGER | Denormalized count of failed features |
| `warning_count` | INTEGER | Denormalized count of warnings/unsupported |
| `total_area_m2` | FLOAT | Pre-computed sum of all polygon areas |
| `total_length_m` | FLOAT | Pre-computed sum of all line lengths |

#### `feature_measurements` Table
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER (PK) | Auto-increment primary key |
| `uploaded_file_id` | INTEGER (FK) | Foreign key pointing to `uploaded_files.id` (`ON DELETE CASCADE`) |
| `feature_index` | INTEGER | Zero-based index of feature in dataset |
| `geometry_type` | VARCHAR(64) | `Polygon`, `LineString`, `Point`, etc. |
| `properties` | TEXT (JSON) | Serialized feature attribute table |
| `area_m2` | FLOAT | Area in $\text{m}^2$ (null for non-polygons) |
| `area_ha` | FLOAT | Area in hectares (null for non-polygons) |
| `length_m` | FLOAT | Length in metres (null for non-lines) |
| `length_km` | FLOAT | Length in kilometres (null for non-lines) |
| `measurement_crs` | VARCHAR(128) | Projected CRS used for calculation |
| `status` | VARCHAR(32) | `SUCCESS`, `WARNING`, `UNSUPPORTED`, `FAILED` |
| `warning_message` | TEXT | Feature-level diagnostic or warning |

### Storage Decision
- **Why full geometry WKT is omitted from the DB**: Full coordinates can be gigabytes in size for detailed GIS datasets. Storing redundant copies in SQLite bloats the database and increases memory overhead without adding value to the API's measurement reporting contract. The original file is safely stored on disk referenced by a unique UUID.

---

## 7. Installation & Setup

### Prerequisites
- Python 3.11+ (tested on Python 3.11 and 3.13)
- Windows PowerShell or Unix/macOS Terminal

### Step 1: Clone the Repository
```bash
git clone <repository_url> geomeasure
cd geomeasure
```

### Step 2: Create and Activate Virtual Environment
**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

---

## 8. Running the Application

Start the development server with Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be accessible at:
- **API Base URL**: `http://localhost:8000`
- **Interactive Swagger UI**: `http://localhost:8000/docs`
- **ReDoc Documentation**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/health`

---

## 9. API Documentation & Endpoints

### 1. Upload & Process a File
- **Endpoint**: `POST /api/files/`
- **Content-Type**: `multipart/form-data`
- **Field**: `file` (`.kml` or `.zip`)

#### Example Request (cURL):
```bash
curl -X POST "http://localhost:8000/api/files/" \
     -H "accept: application/json" \
     -F "file=@samples/sample_polygon.kml"
```

#### Example Response (`201 Created`):
```json
{
  "file_id": 1,
  "filename": "sample_polygon.kml",
  "status": "COMPLETED",
  "message": "File processed successfully with status: COMPLETED"
}
```

---

### 2. Retrieve File Information
- **Endpoint**: `GET /api/files/{id}/`

#### Example Request:
```bash
curl -X GET "http://localhost:8000/api/files/1/"
```

#### Example Response (`200 OK`):
```json
{
  "file_id": 1,
  "filename": "sample_polygon.kml",
  "upload_timestamp": "2026-10-10T22:15:30.123456Z",
  "feature_count": 1,
  "source_crs": "EPSG:4326",
  "status": "COMPLETED",
  "success_count": 1,
  "failure_count": 0,
  "warning_count": 0,
  "summary_statistics": {
    "total_features": 1,
    "success_count": 1,
    "failure_count": 0,
    "warning_count": 0,
    "total_area_m2": 971384.2185,
    "total_length_m": null
  },
  "error_message": null
}
```

---

### 3. Retrieve Measurements & Quality Report
- **Endpoint**: `GET /api/files/{id}/measurements/`

#### Example Request:
```bash
curl -X GET "http://localhost:8000/api/files/1/measurements/"
```

#### Example Response (`200 OK`):
```json
{
  "file_id": 1,
  "status": "COMPLETED",
  "source_crs": "EPSG:4326",
  "measurement_crs": "ESRI:54034",
  "features": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "properties": {
        "Name": "Sample Agricultural Field",
        "description": "Greenwich 1 km² test polygon"
      },
      "area_m2": 971384.2185,
      "area_ha": 97.138422,
      "length_m": null,
      "length_km": null,
      "measurement_crs": "ESRI:54034",
      "status": "SUCCESS",
      "warning_message": null
    }
  ],
  "quality_report": {
    "total_features": 1,
    "by_geometry_type": {
      "Polygon": 1
    },
    "successfully_measured": 1,
    "unsupported_features": 0,
    "invalid_or_empty_geometries": 0,
    "features_with_warnings": 0,
    "total_area_m2": 971384.2185,
    "total_length_m": null
  }
}
```

---

### 4. List Files (Optional Endpoint)
- **Endpoint**: `GET /api/files/?page=1&page_size=20`

#### Example Response (`200 OK`):
```json
{
  "total": 1,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "file_id": 1,
      "filename": "sample_polygon.kml",
      "status": "COMPLETED",
      "feature_count": 1,
      "upload_timestamp": "2026-10-10T22:15:30.123456Z"
    }
  ]
}
```

---

### 5. Delete File (Optional Endpoint)
- **Endpoint**: `DELETE /api/files/{id}/`
- **Status Code**: `204 No Content` (deletes DB record, cascaded measurements, and disk storage).

---

## 10. Automated Testing

The project includes 38 comprehensive automated tests covering all 18 functional requirements from the assignment.

### Running Tests
Execute pytest using the project virtual environment:

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -v
```
```bash
# Linux / macOS
python -m pytest -v
```

### Verified Test Suite Breakdown
```
tests/test_crs.py::test_utm_zone_determination PASSED
tests/test_crs.py::test_missing_crs_raises_error PASSED
tests/test_crs.py::test_projected_polygon_known_area PASSED
tests/test_crs.py::test_projected_linestring_known_length PASSED
tests/test_crs.py::test_polygon_with_hole PASSED
tests/test_crs.py::test_geographic_to_projected_transformation PASSED
tests/test_crs.py::test_crs_to_string_formatting PASSED
tests/test_error_handling.py::test_corrupt_kml_returns_400 PASSED
tests/test_error_handling.py::test_shapefile_without_prj_fails_with_crs_error PASSED
tests/test_error_handling.py::test_feature_level_resilience PASSED
tests/test_error_handling.py::test_database_persistence PASSED
tests/test_file_information.py::test_get_file_info_success PASSED
tests/test_file_information.py::test_get_file_info_not_found PASSED
tests/test_file_information.py::test_list_files PASSED
tests/test_file_information.py::test_delete_file PASSED
tests/test_file_information.py::test_delete_file_not_found PASSED
tests/test_measurements.py::test_get_measurements_polygon PASSED
tests/test_measurements.py::test_get_measurements_linestring PASSED
tests/test_measurements.py::test_get_measurements_point PASSED
tests/test_measurements.py::test_get_measurements_multi_feature PASSED
tests/test_measurements.py::test_get_measurements_not_found PASSED
tests/test_upload.py::test_upload_valid_kml PASSED
tests/test_upload.py::test_upload_valid_shapefile_zip PASSED
tests/test_upload.py::test_upload_unsupported_file_extension PASSED
tests/test_upload.py::test_upload_corrupt_zip PASSED
tests/test_upload.py::test_upload_empty_zip PASSED
tests/test_upload.py::test_upload_shapefile_missing_shx PASSED
tests/test_upload.py::test_upload_shapefile_missing_dbf PASSED
tests/test_upload.py::test_upload_zip_with_path_traversal PASSED
tests/test_upload.py::test_upload_file_size_exceeded PASSED
tests/test_validation.py::test_validate_extension_valid PASSED
tests/test_validation.py::test_validate_extension_invalid PASSED
tests/test_validation.py::test_validate_size PASSED
tests/test_validation.py::test_validate_zip_safety_path_traversal PASSED
tests/test_validation.py::test_validate_zip_safety_corrupt PASSED
tests/test_validation.py::test_validate_shapefile_components_valid PASSED
tests/test_validation.py::test_validate_shapefile_components_missing_dbf PASSED
tests/test_validation.py::test_classify_geometry PASSED

======================== 38 passed in 1.14s ========================
```

---

## 11. Sample Files & Demonstration

Deterministic sample files are included in `samples/` and can be regenerated anytime with:

```bash
python samples/generate_samples.py
```

Generated fixtures:
1. `samples/sample_polygon.kml`: 1 km² polygon near Greenwich, London ($\text{WGS 84}$).
2. `samples/sample_linestring.kml`: ~1.5 km flight survey line ($\text{WGS 84}$).
3. `samples/sample_shapefile.zip`: Zipped Shapefile containing agricultural parcels with attributes and complete `.shp`, `.shx`, `.dbf`, `.prj` files.

---

## 12. Design Decisions & Alternatives

1. **Dual Driver Strategy (Pyogrio & Fiona)**:
   - *Choice*: GeoMeasure attempts parsing with `pyogrio` first (direct C-level GDAL bindings) with graceful fallback to `fiona`.
   - *Rationale*: Eliminates driver mismatches across different operating system GDAL installations (e.g. `LIBKML` driver issues on Windows).
2. **Denormalized Summary Statistics**:
   - *Choice*: Total area, length, and success counts are persisted in the `uploaded_files` row.
   - *Rationale*: Eliminates expensive table scans and aggregations across hundreds of thousands of feature rows when polling `GET /api/files/{id}/`.
3. **Atomic File Ingestion**:
   - *Choice*: Files are written with temporary extensions (`.tmp`) and atomically renamed upon upload completion.
   - *Rationale*: Prevents partially written files from being read by concurrent requests during slow network uploads.

---

## 13. Security Considerations

- **Path Traversal Protection**: Uploaded ZIP archives are pre-inspected for entries with `..` or absolute path prefixes.
- **Randomized File Names**: Stored files use UUID4 filenames (`<uuid4>.kml`). User-supplied filenames are never used as filesystem paths.
- **Upload Size Enforcement**: A configurable 50 MB limit is enforced both against the HTTP header and against raw byte streams.
- **Leakage Prevention**: Internal server exceptions and tracebacks are intercepted; clean JSON messages are returned to the client while complete diagnostics are recorded in server logs.

---

## 14. Known Limitations

- **Antimeridian Crossing**: Geometries crossing the 180° meridian may produce warped centroids when computing UTM zones.
- **3D / Z Coordinates**: Z coordinates are preserved during ingestion but planar calculations measure 2D surface projections.

---

## 15. What I Learned

- **CRS Transformations**: Gained deep insights into why calculating planar measurements in $\text{EPSG:4326}$ yields incorrect results and how selecting the appropriate equal-area projection vs. local conformal UTM projection guarantees precision.
- **Resilient Geospatial Parsing**: Handling real-world edge cases in GIS (missing `.prj` files, multipart geometries, self-intersecting loops) without causing entire HTTP processing pipelines to fail.
- **Defensive API Architecture**: Designing layered validation checks ensuring that untrusted user uploads are checked before geospatial engines touch memory.

---

## 16. Future Scope

1. **PostGIS Integration**: Add native PostgreSQL / PostGIS backend support for spatial indexing (`ST_Area`, `ST_Length`, `ST_Transform`).
2. **Asynchronous Background Workers**: Support large vector files (>500MB) using Celery or ARQ with Redis queues and WebSocket progress updates.
3. **GeoJSON & GeoPackage Support**: Extend ingestion support to `.geojson` and `.gpkg` formats.

---

## 17. Docker Deployment

Build and run the containerized application with Docker:

```bash
# Build the Docker image
docker build -t geomeasure:latest .

# Run the container
docker run -d -p 8000:8000 --name geomeasure-api geomeasure:latest
```

The service will be live at `http://localhost:8000/docs`.
