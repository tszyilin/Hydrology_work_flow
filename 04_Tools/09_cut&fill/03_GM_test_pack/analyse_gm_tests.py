"""
Compare Global Mapper's reports for the synthetic tests with each hypothesis
about how it calculates. Put each report in its test folder as
<ID>_GM.txt (e.g. T01\\T01_GM.txt) and the spacing Global Mapper showed in
results.csv, then:

    python -I analyse_gm_tests.py            # all tests that have a report
    python -I analyse_gm_tests.py --predict  # predictions only, no reports

Hypotheses:
  area   planar map grid | ellipsoid (GRS80) | sphere 6,367,449 m (rectifying,
         the tool's model) | sphere 6,371,009 m (mean)
  surface (z between cell centres)  bilinear (the tool) | nearest cell |
         triangles (two per quad of cell centres, either diagonal)
  3D     Horn per cell (the tool) | bilinear gradient | triangle facets
  spacing  min(cell / 2, smaller bbox side / 200) (the tool's default)
"""

import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))      # cut_fill_volume.py

import numpy as np  # noqa: E402
from osgeo import gdal, ogr, osr  # noqa: E402

import cut_fill_volume as cfv  # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()
R_MEAN = 6371008.771


def sphere_area(geom, srs_wkt, radius):
    a = cfv._gm_sphere_area(geom, srs_wkt)
    return None if a is None else a * (radius / cfv.GM_SPHERE_RADIUS) ** 2


def load(test):
    folder = os.path.join(HERE, test['folder'])
    ds = gdal.Open(os.path.join(folder, 'dem.tif'))
    shp = ogr.Open(os.path.join(folder, 'area.shp'))
    feat = shp.GetLayer().GetNextFeature()
    geom = feat.GetGeometryRef().Clone()
    return folder, ds, geom


def area_models(geom, srs_wkt, geographic):
    planar = None if geographic else geom.GetArea()
    ell = cfv._geodesic_area(geom, srs_wkt)
    return {
        'planar map grid': planar,
        'ellipsoid GRS80': ell,
        'sphere 6,367,449 (tool)': sphere_area(geom, srs_wkt, cfv.GM_SPHERE_RADIUS),
        'sphere 6,371,009 (mean)': sphere_area(geom, srs_wkt, R_MEAN),
    }


# --- surface / 3D hypotheses on a fine lattice (exact-integral stand-in) ----

def fine_samples(ds, geom, step):
    gt = ds.GetGeoTransform()
    a = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    minx, maxx, miny, maxy = geom.GetEnvelope()
    nx = int(math.ceil((maxx - minx) / step))
    ny = int(math.ceil((maxy - miny) / step))
    mask = cfv._rasterize_mask(geom.ExportToWkt(), ds.GetProjection(),
                               (minx, step, 0, maxy, 0, -step), nx, ny)
    ii, jj = np.nonzero(mask)
    x = minx + (jj + 0.5) * step
    y = maxy - (ii + 0.5) * step
    cw = gt[1]
    c = (x - gt[0]) / cw - 0.5
    r = (gt[3] - y) / cw - 0.5
    j = np.floor(c).astype(np.int64)
    i = np.floor(r).astype(np.int64)
    fx, fy = c - j, r - i
    return a, cw, i, j, fx, fy, step * step


def surface(a, cw, i, j, fx, fy, method):
    z00, z01, z10, z11 = a[i, j], a[i, j + 1], a[i + 1, j], a[i + 1, j + 1]
    if method == 'bilinear (tool)':
        z = z00 * (1 - fx) * (1 - fy) + z01 * fx * (1 - fy) + z10 * (1 - fx) * fy + z11 * fx * fy
        gx = ((z01 - z00) * (1 - fy) + (z11 - z10) * fy) / cw
        gy = ((z10 - z00) * (1 - fx) + (z11 - z01) * fx) / cw
    elif method == 'nearest cell':
        ci = np.where(fy < 0.5, i, i + 1)
        cj = np.where(fx < 0.5, j, j + 1)
        z = a[ci, cj]
        gx = gy = np.zeros_like(z)
    else:                                   # triangles
        if method == 'triangles, NW-SE diagonal':
            up = fx >= fy                   # triangle z00, z01, z11
            z = np.where(up, z00 + (z01 - z00) * fx + (z11 - z01) * fy,
                         z00 + (z10 - z00) * fy + (z11 - z10) * fx)
            gx = np.where(up, z01 - z00, z11 - z10) / cw
            gy = np.where(up, z11 - z01, z10 - z00) / cw
        else:                               # NE-SW diagonal (z01-z10)
            lo = fx + fy <= 1
            z = np.where(lo, z00 + (z01 - z00) * fx + (z10 - z00) * fy,
                         z11 + (z10 - z11) * (1 - fx) + (z01 - z11) * (1 - fy))
            gx = np.where(lo, z01 - z00, z11 - z10) / cw
            gy = np.where(lo, z10 - z00, z11 - z01) / cw
    return z, np.sqrt(1 + gx * gx + gy * gy)


SURFACES = ('bilinear (tool)', 'nearest cell', 'triangles, NW-SE diagonal',
            'triangles, NE-SW diagonal')


def horn_factor(a, cw, i, j, fx, fy):
    h = cfv._horn_slope_factor(a, cw, cw)
    return (h[i, j] * (1 - fx) * (1 - fy) + h[i, j + 1] * fx * (1 - fy)
            + h[i + 1, j] * (1 - fx) * fy + h[i + 1, j + 1] * fx * fy)


# --- reading what came back -------------------------------------------------

def read_spacings():
    path = os.path.join(HERE, 'results.csv')
    out = {}
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                try:
                    out[row['test'].strip()] = float(row['gm_x_spacing_m'])
                except (KeyError, ValueError):
                    pass
    return out


def pct(a, b):
    return 100.0 * (a / b - 1) if b else float('nan')


def main():
    predict_only = '--predict' in sys.argv
    with open(os.path.join(HERE, 'tests.json')) as f:
        tests = json.load(f)
    seen_spacing = read_spacings()
    for t in tests:
        folder, ds, geom = load(t)
        report = os.path.join(folder, '%s_GM.txt' % t['id'])
        have = os.path.exists(report) and not predict_only
        if not have and not predict_only:
            continue
        srs_wkt = ds.GetProjection()
        geographic = osr.SpatialReference(wkt=srs_wkt).IsGeographic()
        minx, maxx, miny, maxy = geom.GetEnvelope()
        cell = ds.GetGeoTransform()[1]
        print('=' * 88)
        print('%s  %s\n    probes: %s' % (t['id'], t['title'], t['probes']))
        pred_s = cfv.gm_spacing(cell, maxx - minx, maxy - miny)
        print('    spacing: predicted %s%s' % (
            'n/a (geographic CRS)' if geographic else '%.9g m' % pred_s,
            '' if t['id'] not in seen_spacing else
            ' | Global Mapper showed %.9g m' % seen_spacing[t['id']]))

        models = area_models(geom, srs_wkt, geographic)
        ref = cfv.read_gm_report(report) if have else None
        gm_area = None
        if ref is not None:
            h = ref['BASE_HEIGHT']
            net = ref['CUT_VOLUME'] - ref['FILL_VOLUME']
            gm_area = -np.polyfit(h, net, 1)[0]
            print('    Global Mapper area (from report): %s m2' % format(gm_area, ',.1f'))
        print('    area model                    area m2       %s' % ('GM vs model' if ref is not None else ''))
        for name, val in models.items():
            if val is None:
                continue
            extra = '   %+.4f %%' % pct(gm_area, val) if gm_area else ''
            print('      %-26s %14s%s' % (name, format(val, ',.1f'), extra))

        if geographic:
            continue
        # Interpolation / 3D hypotheses, all on the sphere-model factor.
        k = models['sphere 6,367,449 (tool)'] / models['planar map grid']
        hts = (ref['BASE_HEIGHT'] if ref is not None else
               cfv.make_heights(t['base_from'], t['base_to'], t['base_step']))
        a, cw, i, j, fx, fy, dA = fine_samples(ds, geom, cell / 20.0)
        horn = horn_factor(a, cw, i, j, fx, fy)
        rows = []
        for sname in SURFACES:
            z, slope = surface(a, cw, i, j, fx, fy, sname)
            for tname, f3 in (('own slope', slope), ('Horn (tool)', horn)):
                if sname == 'nearest cell' and tname == 'Horn (tool)':
                    continue
                res = cfv.compute_cut_fill(z, f3, dA, hts)
                rows.append(('%s + %s 3D' % (sname, tname), res))
        # The tool itself, default settings (GM spacing, auto factor).
        tool = cfv.cut_fill_for_polygon(os.path.join(folder, 'dem.tif'),
                                        geom.ExportToWkt(), t['base_step'],
                                        t['base_from'], t['base_to'])
        rows.append(('THE TOOL (default settings)', tool['res']))
        keys = ('CUT_VOLUME', 'FILL_VOLUME', 'CUT_AREA', 'FILL_AREA',
                'CUT_AREA_3D', 'FILL_AREA_3D')
        if ref is None:
            mid = len(hts) // 2
            print('    prediction at base %g m (x sphere factor):' % hts[mid])
            print('      %-48s %14s %14s %12s %12s' % ('hypothesis', 'CUT m3', 'FILL m3', 'CUT_3D m2', 'FILL_3D m2'))
            for name, res in rows:
                print('      %-48s %14s %14s %12s %12s' % (
                    name, format(res['CUT_VOLUME'][mid] * k, ',.1f'),
                    format(res['FILL_VOLUME'][mid] * k, ',.1f'),
                    format(res['CUT_AREA_3D'][mid] * k, ',.0f'),
                    format(res['FILL_AREA_3D'][mid] * k, ',.0f')))
        else:
            print('    max |difference| from Global Mapper over all rows (values > 100):')
            print('      %-48s' % 'hypothesis' + ''.join('%14s' % kk[:12] for kk in keys))
            for name, res in rows:
                cells = []
                for kk in keys:
                    mine, gm = res[kk] * k, ref[kk]
                    big = np.abs(gm) > 100
                    cells.append('%13.3f%%' % (np.max(np.abs(mine[big] / gm[big] - 1)) * 100)
                                 if big.any() else '%14s' % '-')
                print('      %-48s' % name + ''.join(cells))


if __name__ == '__main__':
    main()
