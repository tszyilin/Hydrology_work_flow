"""Write RFFE results to disk and build QGIS layers from them."""

from __future__ import annotations

import csv
import json
import os
import time

from .rffe_client import AEPS, station_table


#: Bundled reference geojson of FFA catchment polygons keyed by gauge ID.
FFA_CATCHMENTS_GEOJSON = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "ffa_catchments.geojson"))

#: NT 1:250K geology outcrop shapefile. Has a 'type' field taking values
#: 'rock' or 'unconsolid' — the split used for rock/alluvial proportion.
NT_GEOLOGY_SHP = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "NT_geology_outcrop_250K.shp"))

#: Layer-name suffix used to tag the FFA catchments layer built by build_layers,
#: so the dialog can find it in the returned list without matching on the site name.
FFA_LAYER_SUFFIX = "ffa_catchments"


def _station_ids(region: dict) -> list[str]:
    """Return the gauge IDs used to fit the regional models, deduped, order-preserving."""
    header, rows = station_table(region)
    if not rows:
        return []
    idx = {h: i for i, h in enumerate(header)}
    if "Station_ID" not in idx:
        return []
    seen, out = set(), []
    for row in rows:
        sid = str(row[idx["Station_ID"]]).strip()
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


# ----------------------------------------------------------------------
# Tabular output
# ----------------------------------------------------------------------

def result_rows(site: dict, models: dict) -> list[list]:
    """One row per model, with flows and 90% limits for each AEP."""
    header = (["Outlet_Lon", "Outlet_Lat", "Area_km2", "Basin", "Region",
               "Recommended_Model", "Model"]
              + [f"Q{a}_m3s" for a in AEPS]
              + [f"Q{a}_lower90" for a in AEPS]
              + [f"Q{a}_upper90" for a in AEPS])
    rows = [header]
    rec = models.get("Recommended Model")
    for name, d in models.items():
        if not isinstance(d, dict):
            continue                                   # the "Recommended Model" string
        rows.append([site["Outlet Lon"], site["Outlet Lat"],
                     round(site["Area km2"], 4), site.get("Basin", ""),
                     site.get("Region Name", ""), rec, name]
                    + [d["Flow"][i] for i in range(len(AEPS))]
                    + [d["05pct"][i] for i in range(len(AEPS))]
                    + [d["95pct"][i] for i in range(len(AEPS))])
    return rows


def _write_csv(path: str, rows: list[list]) -> str:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


def write_outputs(out_dir: str, name: str, site: dict, models: dict,
                  region: dict, polygon: list) -> dict:
    """Write results, stations and raw JSON into *out_dir*.

    :returns: mapping of output kind -> path written.
    """
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = f"{_safe(name)}_{stamp}"
    written = {}

    written["results"] = _write_csv(os.path.join(out_dir, base + "_results.csv"),
                                    result_rows(site, models))

    header, rows = station_table(region)
    if rows:
        written["stations"] = _write_csv(
            os.path.join(out_dir, base + "_stations.csv"), [header] + rows)

    jpath = os.path.join(out_dir, base + ".json")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump({"site": site, "models": models, "region": region,
                   "catchment_polygon": polygon}, fh, indent=1)
    written["json"] = jpath
    return written


def _safe(name: str) -> str:
    """Reduce a user-supplied name to something safe for a filename."""
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (name or "site"))
    return keep.strip("_") or "site"


# ----------------------------------------------------------------------
# QGIS layers
# ----------------------------------------------------------------------

def build_layers(site: dict, models: dict, region: dict, polygon: list,
                 name: str, out_dir: str | None = None):
    """Build the catchment polygon, outlet/centroid points and station layers.

    Written as GeoPackage when *out_dir* is given, otherwise as memory layers.
    Imports PyQGIS lazily so the module stays importable outside QGIS.

    :returns: list of QgsVectorLayer, already populated.
    """
    from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsField,
                           QgsGeometry, QgsPointXY, QgsVectorFileWriter,
                           QgsVectorLayer, QgsProject)
    from qgis.PyQt.QtCore import QVariant

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    layers = []

    def new_layer(kind: str, suffix: str, fields: list[tuple[str, object]]):
        lyr = QgsVectorLayer(f"{kind}?crs=EPSG:4326", f"{name} {suffix}", "memory")
        dp = lyr.dataProvider()
        dp.addAttributes([QgsField(n, t) for n, t in fields])
        lyr.updateFields()
        return lyr

    # --- catchment polygon (positions arrive as [lat, lon]) ---
    catch = new_layer("Polygon", "catchment",
                      [("Name", QVariant.String), ("Area_km2", QVariant.Double),
                       ("Basin", QVariant.String), ("Region", QVariant.String)])
    ring = [QgsPointXY(float(lon), float(lat)) for lat, lon in polygon]
    f = QgsFeature(catch.fields())
    f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
    f.setAttributes([name, round(site.get("Area km2", 0.0), 4),
                     site.get("Basin", ""), site.get("Region Name", "")])
    catch.dataProvider().addFeature(f)
    catch.updateExtents()
    layers.append(catch)

    # --- outlet + centroid, with the headline results on the outlet ---
    rec = models.get("Recommended Model")
    pts = new_layer("Point", "points",
                    [("Name", QVariant.String), ("Type", QVariant.String),
                     ("Model", QVariant.String)]
                    + [(f"Q{a}", QVariant.Double) for a in AEPS])
    rec_model = models.get(rec, {})
    outlet = QgsFeature(pts.fields())
    outlet.setGeometry(QgsGeometry.fromPointXY(
        QgsPointXY(float(site["Outlet Lon"]), float(site["Outlet Lat"]))))
    outlet.setAttributes([name, "Outlet", rec or ""]
                         + [rec_model.get("Flow", [None] * 6)[i] for i in range(len(AEPS))])
    cent = QgsFeature(pts.fields())
    cent.setGeometry(QgsGeometry.fromPointXY(
        QgsPointXY(float(site["Centroid Lon"]), float(site["Centroid Lat"]))))
    cent.setAttributes([name, "Centroid", ""] + [None] * len(AEPS))
    pts.dataProvider().addFeatures([outlet, cent])
    pts.updateExtents()
    layers.append(pts)

    # --- gauged stations behind the regional models ---
    header, rows = station_table(region)
    if rows:
        idx = {h: i for i, h in enumerate(header)}
        keep = [("Region_ID", QVariant.String), ("Station_ID", QVariant.String),
                ("Station Name", QVariant.String), ("River Name", QVariant.String),
                ("State", QVariant.String), ("Area km2", QVariant.Double),
                ("Record Length", QVariant.Double), ("Initial Year", QVariant.Double),
                ("Final Year", QVariant.Double), ("Dist km", QVariant.Double),
                ("Q_10.00%", QVariant.Double), ("Q_1.00%", QVariant.Double)]
        # Gauge area relative to the site: 1.0 is identical, 2.0 twice as large.
        # Carried as a field so it is filterable, not just implied by the symbol.
        derived = [("Area_Ratio", QVariant.Double), ("Size_Class", QVariant.String)]
        stn = new_layer("Point", "gauges", keep + derived)
        site_area = float(site.get("Area km2") or 0.0)

        # A station can serve more than one region; keep one feature per station
        # and record every region it belongs to.
        seen: dict[str, QgsFeature] = {}
        order: list[str] = []
        for row in rows:
            try:
                lon = float(row[idx["Gauge Lon"]])
                lat = float(row[idx["Gauge Lat"]])
            except (KeyError, TypeError, ValueError):
                continue                                # station without coordinates
            sid = str(row[idx["Station_ID"]])
            if sid in seen:
                f_prev = seen[sid]
                regions = f_prev["Region_ID"]
                extra = str(row[idx["Region_ID"]])
                if extra not in str(regions).split(", "):
                    f_prev["Region_ID"] = f"{regions}, {extra}"
                continue
            sf = QgsFeature(stn.fields())
            sf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            attrs = [row[idx[k]] if k in idx else None for k, _ in keep]
            ratio, cls = _size_class(row[idx["Area km2"]] if "Area km2" in idx else None,
                                     site_area)
            sf.setAttributes(attrs + [ratio, cls])
            seen[sid] = sf
            order.append(sid)

        stn.dataProvider().addFeatures([seen[s] for s in order])
        stn.updateExtents()
        _style_gauges(stn)
        layers.append(stn)

    # --- FFA catchment polygons for the gauges the regional models used ---
    ffa = _ffa_catchments_layer(_station_ids(region), name)

    if out_dir:
        layers = [_to_gpkg(l, out_dir, wgs84) or l for l in layers]
        if ffa is not None:
            ffa = _to_shp(ffa, out_dir, wgs84) or ffa
    if ffa is not None:
        layers.append(ffa)
    return layers


def _ffa_catchments_layer(station_ids: list[str], name: str):
    """Build a memory polygon layer with the FFA catchments matching *station_ids*.

    IDs in the bundled geojson are integers; station IDs from the RFFE tables may
    arrive as ints or strings, so both sides are coerced to str for the compare.
    Returns None when the geojson is missing or no gauge matches.
    """
    if not station_ids:
        return None
    from qgis.core import QgsVectorLayer

    src = QgsVectorLayer(FFA_CATCHMENTS_GEOJSON, "ffa_src", "ogr")
    if not src.isValid():
        return None
    wanted = {str(s) for s in station_ids}
    matches = [f for f in src.getFeatures() if str(f["ID"]) in wanted]
    if not matches:
        return None

    lyr = QgsVectorLayer("Polygon?crs=EPSG:4326", f"{name} ffa_catchments", "memory")
    dp = lyr.dataProvider()
    dp.addAttributes(src.fields())
    lyr.updateFields()
    dp.addFeatures(matches)
    lyr.updateExtents()
    return lyr


def geology_bbox() -> tuple | None:
    """Return (xmin, ymin, xmax, ymax) from the geology .shp header, or None.

    Reading the fixed-offset header avoids pulling the whole 158k-feature layer
    just to answer a "should we bother?" check.
    """
    import struct
    try:
        with open(NT_GEOLOGY_SHP, "rb") as fh:
            hdr = fh.read(100)
    except OSError:
        return None
    if len(hdr) < 68:
        return None
    return struct.unpack("<dddd", hdr[36:68])


def catchments_in_geology(catchments_layer) -> bool:
    """True when any catchment's bbox intersects the geology shapefile's extent."""
    bbox = geology_bbox()
    if bbox is None or catchments_layer is None:
        return False
    from qgis.core import QgsRectangle
    ext = QgsRectangle(bbox[0], bbox[1], bbox[2], bbox[3])
    for f in catchments_layer.getFeatures():
        if f.geometry() and f.geometry().boundingBox().intersects(ext):
            return True
    return False


def compute_rock_alluvial(catchments_layer) -> int:
    """Add rock/alluvial area and percentage fields to *catchments_layer*.

    Uses the NT geology shapefile's ``type`` field ('rock' vs 'unconsolid').
    Areas are ellipsoidal (GRS80) so the km² values are meaningful for
    catchments stored in EPSG:4326. Only catchments that actually overlap the
    geology extent get populated; the rest keep NULLs.

    :returns: number of catchments updated (0 if the geology layer is missing).
    """
    from qgis.core import (QgsCoordinateReferenceSystem, QgsDistanceArea,
                           QgsField, QgsProject, QgsSpatialIndex, QgsVectorLayer)
    from qgis.PyQt.QtCore import QVariant

    geo = QgsVectorLayer(NT_GEOLOGY_SHP, "geology_src", "ogr")
    if not geo.isValid():
        return 0
    type_ix = geo.fields().indexOf("type")
    if type_ix < 0:
        return 0
    sindex = QgsSpatialIndex(geo.getFeatures())

    da = QgsDistanceArea()
    da.setEllipsoid("GRS80")
    da.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance().transformContext())

    dp = catchments_layer.dataProvider()
    new = [("rock_km2", QVariant.Double), ("alluv_km2", QVariant.Double),
           ("rock_pct", QVariant.Double), ("alluv_pct", QVariant.Double)]
    existing = {catchments_layer.fields().at(i).name()
                for i in range(catchments_layer.fields().count())}
    to_add = [QgsField(n, t) for n, t in new if n not in existing]
    if to_add:
        dp.addAttributes(to_add)
        catchments_layer.updateFields()

    ix = {n: catchments_layer.fields().indexOf(n) for n, _ in new}
    updated = 0
    for cat in catchments_layer.getFeatures():
        cg = cat.geometry()
        if cg is None or cg.isEmpty():
            continue
        total = da.measureArea(cg) / 1e6
        if total <= 0:
            continue
        rock_a = alluv_a = 0.0
        for fid in sindex.intersects(cg.boundingBox()):
            gf = geo.getFeature(fid)
            gg = gf.geometry()
            if gg is None or gg.isEmpty() or not cg.intersects(gg):
                continue
            inter = cg.intersection(gg)
            if inter.isEmpty():
                continue
            a = da.measureArea(inter) / 1e6
            t = (gf["type"] or "").strip()
            if t == "rock":
                rock_a += a
            elif t == "unconsolid":
                alluv_a += a
        dp.changeAttributeValues({cat.id(): {
            ix["rock_km2"]: round(rock_a, 4),
            ix["alluv_km2"]: round(alluv_a, 4),
            ix["rock_pct"]: round(100 * rock_a / total, 2),
            ix["alluv_pct"]: round(100 * alluv_a / total, 2)}})
        updated += 1
    catchments_layer.updateExtents()
    catchments_layer.triggerRepaint()
    return updated


def _to_shp(layer, out_dir: str, crs):
    """Save a memory layer to an ESRI Shapefile; return the file-backed layer or None."""
    from qgis.core import (QgsCoordinateTransformContext, QgsVectorFileWriter,
                           QgsVectorLayer)

    path = os.path.join(out_dir, _safe(layer.name()) + ".shp")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "ESRI Shapefile"
    opts.fileEncoding = "UTF-8"
    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsCoordinateTransformContext(), opts)
    code = err[0] if isinstance(err, tuple) else err
    if code != QgsVectorFileWriter.NoError:
        return None
    saved = QgsVectorLayer(path, layer.name(), "ogr")
    return saved if saved.isValid() else None


#: A gauge within this factor of the site's area is treated as comparable.
SIZE_TOLERANCE = 2.0


def _size_class(gauge_area, site_area: float):
    """Classify a gauge's catchment area against the site's.

    :returns: ``(ratio, label)`` where ratio is gauge area / site area.
    """
    try:
        gauge_area = float(gauge_area)
    except (TypeError, ValueError):
        return None, "unknown"
    if not site_area or gauge_area <= 0:
        return None, "unknown"
    ratio = gauge_area / site_area
    if ratio < 1.0 / SIZE_TOLERANCE:
        return round(ratio, 4), "smaller"
    if ratio > SIZE_TOLERANCE:
        return round(ratio, 4), "larger"
    return round(ratio, 4), "comparable"


def _style_gauges(layer) -> None:
    """Style the gauges by catchment area.

    Graduated colour on ``Area km2`` (small = green through large = red) with
    log-ish break points that span the range typical of RFFE gauge networks.
    All markers are simple circles; the shape channel is intentionally left
    free for the reader to compare against the site's own area.
    """
    from qgis.core import (QgsGraduatedSymbolRenderer, QgsMarkerSymbol,
                           QgsPalLayerSettings, QgsRendererRange,
                           QgsTextFormat, QgsVectorLayerSimpleLabeling)
    from qgis.PyQt.QtGui import QColor, QFont

    # Bands span three orders of magnitude, which is the typical range of gauge
    # catchments feeding an RFFE run (tens to tens of thousands of km²).
    bands = [(0, 100, "#1a9850", "< 100 km2"),
             (100, 500, "#91cf60", "100 - 500 km2"),
             (500, 2000, "#fee08b", "500 - 2000 km2"),
             (2000, 10000, "#fc8d59", "2000 - 10000 km2"),
             (10000, float("inf"), "#d73027", "> 10000 km2")]
    ranges = []
    for lo, hi, colour, label in bands:
        sym = QgsMarkerSymbol.createSimple(
            {"name": "circle", "color": colour, "outline_color": "#333333",
             "outline_width": "0.2", "size": "3.0"})
        ranges.append(QgsRendererRange(lo, hi, sym, label))
    renderer = QgsGraduatedSymbolRenderer("Area km2", ranges)
    renderer.setClassAttribute("Area km2")
    layer.setRenderer(renderer)

    settings = QgsPalLayerSettings()
    settings.fieldName = '"Station Name"'
    settings.isExpression = True
    settings.placement = QgsPalLayerSettings.AroundPoint
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", 8))
    fmt.setColor(QColor("#333333"))
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)

    layer.setAbstract(
        "Colour = gauge catchment area (Area km2): green for small (<100), "
        "through yellow/orange, to red for very large (>10000).")


def _to_gpkg(layer, out_dir: str, crs):
    """Save a memory layer to GeoPackage; return the file-backed layer or None."""
    from qgis.core import (QgsCoordinateTransformContext, QgsVectorFileWriter,
                           QgsVectorLayer)

    path = os.path.join(out_dir, _safe(layer.name()) + ".gpkg")
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.fileEncoding = "UTF-8"
    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsCoordinateTransformContext(), opts)
    # V3 returns (error, message) or (error, message, newFile, newLayer)
    code = err[0] if isinstance(err, tuple) else err
    if code != QgsVectorFileWriter.NoError:
        return None
    saved = QgsVectorLayer(path, layer.name(), "ogr")
    return saved if saved.isValid() else None
