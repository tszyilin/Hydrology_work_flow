"""
Validate cut_fill_volume.py against Global Mapper cut-and-fill reports.

Runs every example in EXAMPLES (or one given on the command line) with the
tool's defaults: Global Mapper's automatic sample spacing and the automatic
GM factor (Global Mapper's sphere model). Each must match its report on
every row.

Run from any Python with numpy + GDAL (>= 3.9 for the ellipsoidal area):
    python -I validate_cut_fill.py
    python -I validate_cut_fill.py report.txt dem.tif polygon.shp
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402

from cut_fill_volume import (  # noqa: E402
    GM_SCALE_FACTOR, RESULT_KEYS, calibrate_gm_factor, compute_cut_fill,
    format_gm_report, read_gm_report, sample_dem_in_polygon)

gdal.UseExceptions()
ogr.UseExceptions()

EX2 = os.path.join(HERE, '02_Example 2')
EXAMPLES = [
    ('Example 1: Landgate clay pan, 20 m DEM, MGA52',
     os.path.join(HERE, 'example_cut.txt'),
     os.path.join(HERE, 'Landgate_DEM_20m.flt'),
     os.path.join(HERE, 'clay pan.shp')),
    ('Example 2: storage area, 0.5 m LiDAR, MGA55',
     os.path.join(EX2, 'Example2.txt'),
     os.path.join(EX2, 'Lidar_0.5m_7855.tif'),
     os.path.join(EX2, 'storage_curve_area.shp')),
]

# GM prints areas to 3-4 significant figures (0.689 sq km = +/- 500 m2), so
# the area tolerance is that print rounding plus a relative margin.
VOL_REL, VOL_ABS = 1.5e-3, 10.0       # 0.15 % or 10 m3
AREA_REL, AREA_ABS = 1e-3, 0.0005e6   # 0.1 % + 0.0005 km2, in m2
AREA3D_REL = 3e-3                     # 3D: 0.3 % + 0.0005 km2
# Areas are counted in whole samples, so where a base height's contour runs
# through many samples (coarse spacing, flat ground) the area can be off by
# a few dozen of them. Allow 50 samples on top (200 m2 at 2 m spacing; 1,600
# m2 at Global Mapper's 5.654 m on Example 1).
AREA_SAMPLES = 50


def check(res, ref, factor, sample_area=0.0):
    fails, worst = {}, {}
    for k in RESULT_KEYS:
        mine = res[k] * factor
        diff = np.abs(mine - ref[k])
        if k.endswith('VOLUME'):
            ok = (diff <= VOL_ABS) | (diff <= VOL_REL * np.abs(ref[k]))
        else:
            rel = AREA3D_REL if k.endswith('3D') else AREA_REL
            ok = diff <= (AREA_ABS + AREA_SAMPLES * sample_area * factor
                          + rel * np.abs(ref[k]))
        fails[k] = int((~ok).sum())
        big = ref[k] > 1e4
        worst[k] = (float(np.max(np.abs(mine[big] / ref[k][big] - 1))) * 100
                    if big.any() else 0.0)
    return fails, worst


def run_example(name, ref_path, dem, shp):
    print('=' * 78)
    print(name)
    ref = read_gm_report(ref_path)
    heights = ref['BASE_HEIGHT']
    ds = ogr.Open(shp)
    feat = ds.GetLayer().GetNextFeature()
    wkt = feat.GetGeometryRef().ExportToWkt()

    z, slope, dA, info = sample_dem_in_polygon(dem, wkt)
    res = compute_cut_fill(z, slope, dA, heights)
    planar = info['polygon_area']
    print('Samples: %s at %.6g m, %s (polygon %s m2, nodata %d)'
          % (format(info['n_samples'], ','), info['spacing'],
             info['spacing_rule'], format(planar, ',.1f'), info['n_nodata']))

    cal = calibrate_gm_factor(ref_path, planar)
    auto = info['gm_sphere_area'] / planar
    ell = info.get('ellipsoidal_area')
    print('GM factor  calibrated from report: %.6f (GM area %s m2, fit miss %.1e)'
          % (cal['factor'], format(cal['gm_area'], ',.1f'), cal['rel_residual']))
    print('           auto (sphere model):    %.6f (%+.4f %% vs calibrated)'
          % (auto, 100 * (auto / cal['factor'] - 1)))
    print('ELL factor (true ground area):     %s'
          % ('n/a (GDAL < 3.9)' if ell is None else '%.6f' % (ell / planar)))

    f_plan, _ = check(res, ref, 1.0, dA)
    f_auto, w_auto = check(res, ref, auto, dA)
    f_cal, w_cal = check(res, ref, cal['factor'], dA)
    print('\n%-14s %13s %13s %13s' % ('column', 'auto: fails', 'max diff %', 'calib: fails'))
    for k in RESULT_KEYS:
        print('%-14s %13d %13.3f %13d' % (k, f_auto[k], w_auto[k], f_cal[k]))
    n = len(heights) * len(RESULT_KEYS)
    print('Planar (no factor): %d of %d values outside tolerance'
          % (sum(f_plan.values()), n))

    mine_txt = format_gm_report(heights, res, auto).splitlines()
    with open(ref_path) as f:
        ref_txt = f.read().splitlines()
    print('Header matches GM file: %s' % (mine_txt[0] == ref_txt[0]))

    ok = sum(f_auto.values()) == 0
    if os.path.basename(ref_path) == 'example_cut.txt':
        # The constant kept in the module is Example 1's calibration.
        ok = ok and abs(cal['factor'] - GM_SCALE_FACTOR) < 5e-6
    print('-> %s' % ('PASS' if ok else 'FAIL'))
    return ok


def main():
    examples = EXAMPLES
    if len(sys.argv) > 3:
        examples = [('Command line', sys.argv[1], sys.argv[2], sys.argv[3])]
    results = []
    for name, ref_path, dem, shp in examples:
        if not all(os.path.exists(p) for p in (ref_path, dem, shp)):
            print('=' * 78)
            print('%s: files not found, skipped' % name)
            continue
        results.append(run_example(name, ref_path, dem, shp))
    ok = bool(results) and all(results)
    print('\nRESULT: %s (%d example(s))' % ('PASS' if ok else 'FAIL', len(results)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
