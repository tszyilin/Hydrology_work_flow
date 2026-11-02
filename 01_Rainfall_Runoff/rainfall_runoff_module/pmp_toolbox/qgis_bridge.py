"""The only module that talks to the QGIS API.

Keeping the QGIS calls here lets ``dda``, ``gsdm``, ``ellipses`` and
``optimiser`` be imported and tested with plain Python.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingUtils,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType

from .core import ellipses, gsdm
from .core.optimiser import CatchmentRaster, Placement

#: Fields written to the output ellipse layer, mirroring Bulletin Table A2.2.
#: Names are kept to 10 characters -- the DBF limit -- so writing to a shapefile
#: does not silently truncate them.
#: ``(name, type, length)``. Text lengths are declared so the shapefile writer
#: does not fall back to 255 and then warn about clamping it to the DBF's 254.
OUTPUT_FIELDS = [
    ("Ellipse", QMetaType.Type.QString, 2),
    ("EllipseKm2", QMetaType.Type.Double, 0),
    ("CBtn", QMetaType.Type.Double, 0),
    ("CEnc", QMetaType.Type.Double, 0),
    ("IMRD", QMetaType.Type.Double, 0),
    ("AMRD", QMetaType.Type.Double, 0),
    ("VEnc", QMetaType.Type.Double, 0),
    ("VBtn", QMetaType.Type.Double, 0),
    ("MRD", QMetaType.Type.Double, 0),
    ("Source", QMetaType.Type.QString, 8),
]


#: Upper bound on the sample points a single search may use.  The scoring loop
#: is O(points) per candidate and runs thousands of candidates, so this is a
#: guard on run time as much as on memory.
MAX_SEARCH_POINTS = 500_000


class ProjectionError(RuntimeError):
    pass


def catchment_geometry(
    layer: QgsVectorLayer, selected_only: bool = False
) -> tuple[QgsGeometry, QgsCoordinateReferenceSystem]:
    """Dissolve a catchment layer into one geometry in a projected CRS.

    GSDM works in kilometres of ground distance, so a geographic CRS would make
    every area and axis length wrong.  We refuse rather than guess a projection.
    """
    crs = layer.crs()
    if crs.isGeographic():
        raise ProjectionError(
            f"Layer '{layer.name()}' is in a geographic CRS ({crs.authid()}). "
            "Reproject it to a projected CRS in metres (e.g. the appropriate "
            "MGA / UTM zone) before running the optimiser."
        )
    if crs.mapUnits() != Qgis.DistanceUnit.Meters:
        raise ProjectionError(
            f"Layer '{layer.name()}' uses {crs.mapUnits()}, not metres; "
            "GSDM ellipse axes and areas are defined in metres and kilometres."
        )

    features = layer.selectedFeatures() if selected_only else list(layer.getFeatures())
    geometries = [f.geometry() for f in features if f.hasGeometry()]
    if not geometries:
        raise ValueError(f"Layer '{layer.name()}' has no features with geometry.")

    combined = QgsGeometry.unaryUnion(geometries)
    if combined.isEmpty():
        raise ValueError(f"Layer '{layer.name()}' dissolved to an empty geometry.")
    if not combined.isGeosValid():
        combined = combined.makeValid()
    return combined, crs


def centroid_lonlat(
    layer: QgsVectorLayer, selected_only: bool = False
) -> tuple[float, float]:
    """The catchment centroid as ``(lon, lat)`` in EPSG:4326.

    Deliberately independent of :func:`catchment_geometry`: that refuses a
    geographic CRS because GSDM areas are ground distances, but a Figure 3
    lookup only wants degrees and works perfectly well from a lat/long layer.
    """
    features = layer.selectedFeatures() if selected_only else list(layer.getFeatures())
    geometries = [f.geometry() for f in features if f.hasGeometry()]
    if not geometries:
        raise ValueError(f"Layer '{layer.name()}' has no features with geometry.")

    centre = QgsGeometry.unaryUnion(geometries).centroid()
    if centre.isEmpty():
        raise ValueError(f"Layer '{layer.name()}' has no usable centroid.")
    point = centre.asPoint()

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if layer.crs() != wgs84:
        transform = QgsCoordinateTransform(
            layer.crs(), wgs84, QgsProject.instance().transformContext()
        )
        point = transform.transform(point)
    return point.x(), point.y()


@dataclass
class CatchmentSummary:
    """What every tab needs from a catchment layer, from one dissolve.

    The three tabs each want the same two things -- how big the catchment is
    and where it is -- and computing them separately means dissolving the layer
    twice on every layer change.  Here it happens once.

    ``geometry`` and ``crs`` are carried too so the Areal GSDM tab can go
    straight on to rasterising without a third dissolve.
    """

    area_km2: float
    lat: float
    lon: float
    geometry: QgsGeometry
    crs: QgsCoordinateReferenceSystem
    feature_count: int


def catchment_summary(
    layer: QgsVectorLayer, selected_only: bool = False
) -> CatchmentSummary:
    """Dissolve once, and report the area and centroid together.

    The area is measured on the projected geometry, which
    :func:`catchment_geometry` has already established is in metres; the
    centroid is transformed to EPSG:4326 because the Figure 2, Figure 3, zone
    and grid lookups all want degrees.
    """
    geometry, crs = catchment_geometry(layer, selected_only)

    centre = geometry.centroid()
    if centre.isEmpty():
        raise ValueError(f"Layer '{layer.name()}' has no usable centroid.")
    point = centre.asPoint()

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if crs != wgs84:
        transform = QgsCoordinateTransform(
            crs, wgs84, QgsProject.instance().transformContext()
        )
        point = transform.transform(point)

    count = (
        layer.selectedFeatureCount() if selected_only else layer.featureCount()
    )
    return CatchmentSummary(
        area_km2=geometry.area() / 1.0e6,
        lat=point.y(),
        lon=point.x(),
        geometry=geometry,
        crs=crs,
        feature_count=count,
    )


@dataclass
class FeatureCatchment:
    """One CatchmentSummary per polygon feature, plus its FID and name.

    Used to auto-populate the Cases sidebar from a multi-polygon layer, so
    each catchment feature drives its own case (rather than dissolving
    everything into a single composite).
    """

    fid: int
    name: str
    summary: "CatchmentSummary"


def feature_catchments(
    layer: QgsVectorLayer,
    name_field: str | None = None,
    selected_only: bool = False,
) -> list[FeatureCatchment]:
    """One CatchmentSummary per feature (or per selected feature).

    ``name_field`` picks the attribute used as the case name; falls back to
    the FID as ``"Feature <fid>"`` when the field is missing, empty, or None.
    """
    crs = layer.crs()
    if crs.isGeographic():
        raise ProjectionError(
            f"Layer '{layer.name()}' is in a geographic CRS ({crs.authid()}). "
            "Reproject it to a projected CRS in metres (e.g. the appropriate "
            "MGA / UTM zone) before enumerating catchments."
        )
    if crs.mapUnits() != Qgis.DistanceUnit.Meters:
        raise ProjectionError(
            f"Layer '{layer.name()}' uses {crs.mapUnits()}, not metres."
        )

    features = layer.selectedFeatures() if selected_only else list(layer.getFeatures())
    if not features:
        raise ValueError(f"Layer '{layer.name()}' has no features to iterate.")

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    transform = None
    if crs != wgs84:
        transform = QgsCoordinateTransform(
            crs, wgs84, QgsProject.instance().transformContext()
        )

    field_index = layer.fields().indexOf(name_field) if name_field else -1

    out: list[FeatureCatchment] = []
    for feat in features:
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        if not geom.isGeosValid():
            geom = geom.makeValid()
        centre = geom.centroid()
        if centre.isEmpty():
            continue
        point = centre.asPoint()
        if transform is not None:
            point = transform.transform(point)

        if field_index >= 0:
            raw = feat.attribute(field_index)
            name = str(raw).strip() if raw not in (None, "") else ""
        else:
            name = ""
        if not name:
            name = f"Feature {feat.id()}"

        summary = CatchmentSummary(
            area_km2=geom.area() / 1.0e6,
            lat=point.y(),
            lon=point.x(),
            geometry=geom,
            crs=crs,
            feature_count=1,
        )
        out.append(FeatureCatchment(fid=feat.id(), name=name, summary=summary))

    if not out:
        raise ValueError(f"Layer '{layer.name()}' has no usable features.")
    return out


def catchment_grid_points(
    geometry: QgsGeometry,
    source_crs: QgsCoordinateReferenceSystem,
    cellsize_deg: float,
    top_lat: float,
    left_lon: float,
) -> list[tuple[float, float]]:
    """Every WGS84 grid cell centre whose point-in-polygon lands inside ``geometry``.

    ``top_lat`` / ``left_lon`` / ``cellsize_deg`` describe the packed grid the
    caller wants averaged (see ``core/grids.py``: ``TOP_LAT``, ``LEFT_LON``,
    ``CELLSIZE``). Returns ``(lat, lon)`` pairs for use as sample points.

    If no cell centre falls inside — the catchment is smaller than one cell —
    returns a single-element list with the polygon's centroid, so the caller
    can still produce a value (equivalent to the centroid-only path).
    """
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if source_crs != wgs84:
        transform = QgsCoordinateTransform(
            source_crs, wgs84, QgsProject.instance().transformContext()
        )
        polygon = QgsGeometry(geometry)
        polygon.transform(transform)
    else:
        polygon = geometry

    box = polygon.boundingBox()
    x_min, x_max = box.xMinimum(), box.xMaximum()
    y_min, y_max = box.yMinimum(), box.yMaximum()

    # Grid cell centres bracket the polygon: snap the bbox to grid indices.
    r_top = math.floor((top_lat - y_max) / cellsize_deg)
    r_bot = math.ceil((top_lat - y_min) / cellsize_deg)
    c_left = math.floor((x_min - left_lon) / cellsize_deg)
    c_right = math.ceil((x_max - left_lon) / cellsize_deg)

    engine = QgsGeometry.createGeometryEngine(polygon.constGet())
    engine.prepareGeometry()

    points: list[tuple[float, float]] = []
    for r in range(max(r_top, 0), r_bot + 1):
        lat = top_lat - r * cellsize_deg
        for c in range(max(c_left, 0), c_right + 1):
            lon = left_lon + c * cellsize_deg
            pt = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
            if engine.intersects(pt.constGet()):
                points.append((lat, lon))

    if not points:
        # Polygon smaller than one 0.05° cell — fall back to the centroid.
        centre = polygon.centroid()
        if centre.isEmpty():
            return []
        p = centre.asPoint()
        return [(p.y(), p.x())]
    return points


def estimate_points(width_m: float, height_m: float, cell_m: float) -> int:
    """Sample points a bounding box of this size yields at this spacing.

    An upper bound: the catchment keeps only the fraction falling inside it.
    Used both to refuse an unworkable spacing before any memory is committed
    and to show the user what they are asking for as they choose one.
    """
    if cell_m <= 0:
        raise ValueError("sampling distance must be greater than zero")
    return int((max(width_m, 0.0) / cell_m) * (max(height_m, 0.0) / cell_m))


def workable_spacing_m(width_m: float, height_m: float) -> int:
    """The finest whole-metre spacing that stays within MAX_SEARCH_POINTS."""
    return math.ceil(math.sqrt(width_m * height_m / MAX_SEARCH_POINTS))


def rasterise(geometry: QgsGeometry, cell_m: float = 50.0) -> CatchmentRaster:
    """Sample a catchment on a regular grid of points ``cell_m`` metres apart.

    A prepared GEOS engine makes the point-in-polygon test cheap enough to run
    over tens of thousands of points; the resulting point cloud is then scored
    purely in numpy, with no geometry calls inside the search loop.  Nothing
    here is written anywhere -- the points exist only for the duration of the
    search, and the areas that reach the report come from polygon intersection
    in :func:`exact_ring_areas`.
    """
    box = geometry.boundingBox()
    width, height = box.width(), box.height()
    if width <= 0 or height <= 0:
        raise ValueError("catchment has no extent")

    # Check the cost before building the grid: at a few metres over a large
    # catchment the meshgrid alone would exhaust memory long before any
    # count-based check downstream could fire.
    wanted = estimate_points(width, height, cell_m)
    if wanted > MAX_SEARCH_POINTS:
        raise ValueError(
            f"A sampling distance of {cell_m:g} m over this catchment needs up "
            f"to {wanted:,} sample points, more than the {MAX_SEARCH_POINTS:,} "
            f"limit. Use {workable_spacing_m(width, height)} m or more."
        )

    cell = float(cell_m)
    xs = np.arange(box.xMinimum() + cell / 2.0, box.xMaximum(), cell)
    ys = np.arange(box.yMinimum() + cell / 2.0, box.yMaximum(), cell)
    gx, gy = (a.ravel() for a in np.meshgrid(xs, ys))

    engine = QgsGeometry.createGeometryEngine(geometry.constGet())
    engine.prepareGeometry()
    inside = np.fromiter(
        (engine.intersects(QgsGeometry.fromPointXY(QgsPointXY(x, y)).constGet())
         for x, y in zip(gx, gy)),
        dtype=bool,
        count=len(gx),
    )
    points = np.column_stack((gx[inside], gy[inside]))
    if len(points) == 0:
        raise ValueError(
            f"Sampling at {cell_m:g} m produced no points inside the catchment, "
            "which may be narrower than that. Reduce the sampling distance."
        )
    return CatchmentRaster(points, cell * cell / 1.0e6)


def geometry_polygons(geometry: QgsGeometry) -> list[list[np.ndarray]]:
    """A geometry as plain coordinate arrays: ``[[exterior, hole, ...], ...]``.

    This is the whole QGIS-to-preview boundary.  Keeping the ring grouping (as
    opposed to one flat list) lets the preview fill each part odd-even, so the
    holes in a clipped annulus stay holes.
    """
    if geometry is None or geometry.isEmpty():
        return []
    if geometry.isMultipart():
        parts = geometry.asMultiPolygon()
    else:
        single = geometry.asPolygon()
        parts = [single] if single else []

    out: list[list[np.ndarray]] = []
    for part in parts:
        rings = [
            np.array([(p.x(), p.y()) for p in ring], dtype=float)
            for ring in part
            if len(ring) >= 3
        ]
        if rings:
            out.append(rings)
    return out


def ellipse_geometry(
    cx: float, cy: float, theta: float, area_km2: float, segments: int = 180
) -> QgsGeometry:
    ring = ellipses.polygon(cx, cy, theta, area_km2, segments)
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in ring]])


def exact_ring_areas(
    catchment: QgsGeometry, placement: Placement, segments: int = 180
) -> tuple[dict[str, float], dict[str, QgsGeometry]]:
    """Step 2, done exactly: catchment area in each annulus, by intersection.

    The optimiser's cell counts are only as good as the raster; the numbers that
    reach the report are recomputed here with real geometry.
    """
    areas: dict[str, float] = {}
    clipped: dict[str, QgsGeometry] = {}
    previous: QgsGeometry | None = None
    for label, area_km2, _ring in ellipses.template(
        placement.cx, placement.cy, placement.theta, segments
    ):
        disc = ellipse_geometry(placement.cx, placement.cy, placement.theta, area_km2, segments)
        annulus = disc if previous is None else disc.difference(previous)
        part = catchment.intersection(annulus)
        areas[label] = 0.0 if part.isEmpty() else part.area() / 1.0e6
        clipped[label] = part
        previous = disc
    return areas, clipped


def build_output_layers(
    result: gsdm.Result,
    placement: Placement,
    clipped: dict[str, QgsGeometry],
    crs: QgsCoordinateReferenceSystem,
    name_prefix: str = "GSDM",
    segments: int = 180,
) -> tuple[QgsVectorLayer, QgsVectorLayer]:
    """Return ``(ellipse outlines, rainfall rings clipped to the catchment)``."""
    fields = QgsFields()
    for name, qtype, length in OUTPUT_FIELDS:
        field = QgsField(name, qtype)
        if length:
            field.setLength(length)
        fields.append(field)

    outlines = _memory_layer(f"{name_prefix} ellipses", crs, fields)
    rings = _memory_layer(f"{name_prefix} rainfall", crs, fields)

    outline_feats, ring_feats = [], []
    for ring in result.rings:
        attributes = [
            ring.label,
            ring.ellipse_area_km2,
            ring.cbtn,
            ring.cenc,
            ring.imrd,
            ring.amrd,
            ring.venc,
            ring.vbtn,
            ring.mrd,
            ring.source,
        ]
        outline = QgsFeature(fields)
        outline.setAttributes(attributes)
        outline.setGeometry(
            ellipse_geometry(
                placement.cx, placement.cy, placement.theta, ring.ellipse_area_km2, segments
            )
        )
        outline_feats.append(outline)

        clip = clipped.get(ring.label)
        if clip is not None and not clip.isEmpty():
            painted = QgsFeature(fields)
            painted.setAttributes(attributes)
            painted.setGeometry(clip)
            ring_feats.append(painted)

    outlines.dataProvider().addFeatures(outline_feats)
    rings.dataProvider().addFeatures(ring_feats)
    for layer in (outlines, rings):
        layer.updateExtents()
    return outlines, rings


def _memory_layer(name: str, crs, fields: QgsFields) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"MultiPolygon?crs={crs.authid()}", name, "memory")
    layer.dataProvider().addAttributes(fields.toList())
    layer.updateFields()
    return layer


def temp_directory() -> Path:
    """A per-run folder inside QGIS's own temporary area.

    Using QGIS's temp folder rather than the system one means the files are
    swept up by the same housekeeping as any other temporary QGIS output.
    """
    base = Path(QgsProcessingUtils.tempFolder()) / "pmp_toolbox"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="run_", dir=str(base)))


def write_shapefile(layer: QgsVectorLayer, path: Path) -> QgsVectorLayer:
    """Write a layer to an ESRI Shapefile and return the layer reading it back.

    The returned layer is file-backed, so it survives a QGIS restart and can be
    copied or handed on -- unlike the in-memory scratch layer it came from.
    """
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "ESRI Shapefile"
    options.fileEncoding = "UTF-8"

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), QgsProject.instance().transformContext(), options
    )
    error, message = result[0], result[1]
    if error != QgsVectorFileWriter.WriterError.NoError:
        raise OSError(f"Could not write {path.name}: {message or error}")

    written = QgsVectorLayer(str(path), layer.name(), "ogr")
    if not written.isValid():
        raise OSError(f"Wrote {path} but it did not load back.")

    missing = {f.name() for f in layer.fields()} - {f.name() for f in written.fields()}
    if missing:
        raise OSError(
            f"{path.name} lost field(s) {sorted(missing)} on write -- shapefile "
            "attribute names are limited to 10 characters."
        )
    return written


def save_as_temp_shapefiles(
    outlines: QgsVectorLayer, rings: QgsVectorLayer, directory: Path | None = None
) -> tuple[QgsVectorLayer, QgsVectorLayer, Path]:
    """Persist both output layers as shapefiles in a temporary folder."""
    directory = directory or temp_directory()
    written = [
        write_shapefile(layer, directory / f"{_slug(layer.name())}.shp")
        for layer in (outlines, rings)
    ]
    return written[0], written[1], directory


def _slug(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in name]
    return "".join(keep).strip("_") or "gsdm"


def run(
    layer: QgsVectorLayer,
    inputs: gsdm.Inputs,
    selected_only: bool = False,
    cell_m: float = 50.0,
    thetas: int = 12,
    weights: dict[str, float] | None = None,
    progress=None,
    observer=None,
):
    """Whole pipeline: dissolve, rasterise, optimise, then GSDM Steps 2-9.

    ``observer`` is passed to :func:`optimiser.optimise`; if it also has an
    ``on_catchment`` attribute it is handed the dissolved outline first, so a
    live view can frame itself without dissolving the layer a second time.
    """
    from .core.optimiser import optimise

    catchment, crs = catchment_geometry(layer, selected_only)
    on_catchment = getattr(observer, "on_catchment", None)
    if on_catchment is not None:
        on_catchment(geometry_polygons(catchment))

    raster = rasterise(catchment, cell_m)

    weights = weights or gsdm.weight_profile(inputs)
    coarse, placement = optimise(
        raster, weights, thetas_deg=thetas, progress=progress, observer=observer
    )
    if not placement.feasible:
        raise ValueError(
            f"The catchment ({raster.area_km2:.0f} km2) does not fit inside "
            f"ellipse J ({ellipses.AREAS_KM2[-1]:.0f} km2), the largest in the "
            "GSDM template. The method does not apply at this scale."
        )

    areas, clipped = exact_ring_areas(catchment, placement)
    result = gsdm.distribute(areas, inputs)

    exact_area_km2 = catchment.area() / 1.0e6
    if abs(result.catchment_area_km2 - exact_area_km2) > 0.01 * exact_area_km2:
        result.warnings.append(
            f"Ring areas total {result.catchment_area_km2:.2f} km2 but the "
            f"catchment is {exact_area_km2:.2f} km2."
        )
    return result, placement, coarse, clipped, crs, raster
