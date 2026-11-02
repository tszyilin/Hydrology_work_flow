"""Point-in-polygon recommendation of the applicable ARR region.

If `data/arr_regions/*.shp` (or *.gpkg) exists, we look up the region for
the outlet point; otherwise we fall back to a coarse Australia-wide
state boundaries check based on lon/lat.
"""

import os

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "arr_regions")
)


def _find_region_shp():
    if not os.path.isdir(_DATA_DIR):
        return None
    for name in os.listdir(_DATA_DIR):
        if name.lower().endswith((".shp", ".gpkg")):
            return os.path.join(_DATA_DIR, name)
    return None


def _fallback_state(lon, lat):
    """Coarse state-only classification when no region shapefile is bundled.
    Purely for the UI recommendation label; not a hydrological zone."""
    if lat is None or lon is None:
        return None
    if -29.0 <= lat <= -10.0 and 138.0 <= lon <= 154.0:
        return "QLD"
    if -39.0 <= lat <= -28.0 and 140.9 <= lon <= 154.0:
        return "NSW"
    if -39.5 <= lat <= -33.9 and 140.9 <= lon <= 150.0:
        return "VIC"
    if -35.7 <= lat <= -13.5 and 112.0 <= lon <= 129.0:
        return "WA"
    if -26.0 <= lat <= -10.0 and 129.0 <= lon <= 138.0:
        return "NT"
    if -38.5 <= lat <= -26.0 and 129.0 <= lon <= 141.0:
        return "SA"
    if -43.7 <= lat <= -40.5 and 143.0 <= lon <= 148.5:
        return "TAS"
    return None


def recommend_region(lon, lat):
    """Return a region code (e.g. 'QLD', 'NSW') for the outlet, or None."""
    shp = _find_region_shp()
    if shp is not None:
        try:
            return _lookup_via_qgis(shp, lon, lat)
        except Exception:
            pass
    return _fallback_state(lon, lat)


def _lookup_via_qgis(shp_path, lon, lat):
    """Point-in-polygon lookup using QGIS's core API. Reads the first
    string-valued attribute of the containing feature as the region code."""
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeatureRequest,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRectangle,
        QgsVectorLayer,
    )

    layer = QgsVectorLayer(shp_path, "arr_regions", "ogr")
    if not layer.isValid():
        return None

    src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    xform = QgsCoordinateTransform(src_crs, layer.crs(), QgsProject.instance())
    pt = xform.transform(QgsPointXY(lon, lat))
    pt_geom = QgsGeometry.fromPointXY(pt)

    request = QgsFeatureRequest().setFilterRect(
        QgsRectangle(pt.x() - 1e-6, pt.y() - 1e-6, pt.x() + 1e-6, pt.y() + 1e-6)
    )
    for feat in layer.getFeatures(request):
        if feat.geometry() and feat.geometry().contains(pt_geom):
            for field in layer.fields():
                v = feat[field.name()]
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None
