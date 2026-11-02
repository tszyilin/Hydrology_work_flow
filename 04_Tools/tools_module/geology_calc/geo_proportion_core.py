import os
import csv
from collections import defaultdict

from qgis.core import (
    QgsProject,
    QgsDistanceArea,
    QgsUnitTypes,
)

import processing

# Prefix applied to overlay (sub-catchment) field names in the intersection
# result to avoid collisions with geology field names.
OVERLAY_PREFIX = 'sc_'


def resolve_field(name, available, label, fallback=None):
    """Return *name* if it exists in *available*, else try *fallback*.
    Raises ValueError with a helpful message if neither is found."""
    if name in available:
        return name
    if fallback and fallback in available:
        return fallback
    lower = name.lower()
    for f in available:
        if f.lower() == lower:
            return f
    raise ValueError(
        f"Could not find {label} field '{name}' in the intersection result.\n"
        f"Available fields: {available}\n\n"
        f"Tip: field names may change if both layers share the same field name. "
        f"Try renaming one field before running."
    )


def run_geo_proportion(geo_layer, catch_layer, geo_field, catch_field, output_csv,
                        context=None, feedback=None):
    """Intersect *geo_layer* with *catch_layer*, calculate ellipsoidal area per
    (sub-catchment, geology type), and write a CSV summary to *output_csv*.

    Returns a dict with the computed rows and summary counts. Can be called
    both from the interactive dialog and from the batch-capable Processing
    algorithm.
    """
    if feedback is not None:
        feedback.pushInfo('Running intersection...')

    int_result = processing.run(
        'native:intersection',
        {
            'INPUT': geo_layer,
            'OVERLAY': catch_layer,
            'INPUT_FIELDS': [],
            'OVERLAY_FIELDS': [],
            'OVERLAY_FIELDS_PREFIX': OVERLAY_PREFIX,
            'OUTPUT': 'memory:',
        },
        context=context,
        feedback=feedback,
    )
    int_layer = int_result['OUTPUT']

    if int_layer.featureCount() == 0:
        raise ValueError(
            'The intersection produced no features.\n'
            'Check that the two layers overlap and are in compatible CRS.'
        )

    int_field_names = [f.name() for f in int_layer.fields()]

    geo_field_int = resolve_field(geo_field, int_field_names, 'geology')
    catch_field_int = resolve_field(
        OVERLAY_PREFIX + catch_field, int_field_names, 'sub-catchment',
        fallback=catch_field,
    )

    if feedback is not None:
        feedback.pushInfo('Calculating areas...')

    da = QgsDistanceArea()
    da.setSourceCrs(int_layer.crs(), QgsProject.instance().transformContext())
    da.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')

    geo_areas: dict = defaultdict(float)
    catch_totals: dict = defaultdict(float)
    feature_areas: dict = {}

    for feat in int_layer.getFeatures():
        catch_id = str(feat[catch_field_int]) if feat[catch_field_int] is not None else ''
        geo_type = str(feat[geo_field_int]) if feat[geo_field_int] is not None else ''
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        area_raw = da.measureArea(geom)
        area_m2 = da.convertAreaMeasurement(area_raw, QgsUnitTypes.AreaSquareMeters)
        area_km2 = area_m2 / 1_000_000.0

        geo_areas[(catch_id, geo_type)] += area_km2
        catch_totals[catch_id] += area_km2
        feature_areas[feat.id()] = area_km2

    # --- Area check: compare intersection totals against actual catch_layer areas ---
    da_catch = QgsDistanceArea()
    da_catch.setSourceCrs(catch_layer.crs(), QgsProject.instance().transformContext())
    da_catch.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')

    actual_areas: dict = defaultdict(float)
    for feat in catch_layer.getFeatures():
        cid = str(feat[catch_field]) if feat[catch_field] is not None else ''
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        area_raw = da_catch.measureArea(geom)
        area_m2  = da_catch.convertAreaMeasurement(area_raw, QgsUnitTypes.AreaSquareMeters)
        actual_areas[cid] += area_m2 / 1_000_000.0

    area_warnings = []
    TOLERANCE = 0.01   # flag if intersection covers < 99 % of actual area
    for cid, actual in sorted(actual_areas.items()):
        intersected = catch_totals.get(cid, 0.0)
        if actual > 0:
            coverage = intersected / actual
            if coverage < (1.0 - TOLERANCE):
                area_warnings.append(
                    f'  {cid}: intersected {intersected:.4f} km²,'
                    f' actual {actual:.4f} km²'
                    f' (coverage {coverage * 100:.1f} %)'
                )

    if feedback is not None and area_warnings:
        feedback.pushWarning(
            'Area mismatch detected for the following sub-catchments '
            '(geology layer may not fully cover these catchments):\n'
            + '\n'.join(area_warnings)
        )

    # Pivot: one row per sub-catchment, one area column per geology type
    geo_types = sorted({geo_type for _, geo_type in geo_areas})
    catch_ids = sorted(catch_totals.keys())

    rows = []
    for catch_id in catch_ids:
        total = catch_totals[catch_id]
        type_areas = {gt: geo_areas.get((catch_id, gt), 0.0) for gt in geo_types}
        row = [catch_id]
        row += [round(type_areas[gt], 6) for gt in geo_types]
        row.append(round(total, 6))
        portions = [round(type_areas[gt] / total, 4) if total > 0 else 0.0
                    for gt in geo_types]
        row += portions
        row.append(round(sum(portions), 4))
        rows.append(row)

    header = (['id']
              + [f'{gt} area' for gt in geo_types]
              + ['total area']
              + [f'portion of {gt}' for gt in geo_types]
              + ['total'])

    if feedback is not None:
        feedback.pushInfo(f'Writing CSV to {output_csv}...')

    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    with open(output_csv, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)

    return {
        'rows': rows,
        'int_layer': int_layer,
        'feature_areas': feature_areas,
        'n_catchments': len(catch_totals),
        'n_geology_types': len(geo_types),
        'area_warnings': area_warnings,
        'actual_areas': actual_areas,
    }
