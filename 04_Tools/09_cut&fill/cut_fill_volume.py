"""
Cut & Fill (stage-volume) tool for QGIS Processing.

Reproduces the Global Mapper "cut-and-fill volumes" report: for each base
height, the DEM is treated as a bilinear-interpolated surface sampled on a
fine lattice inside the polygon, and

    CUT  = sum(max(z - base, 0)) * dA   (ground above the base height)
    FILL = sum(max(base - z, 0)) * dA   (space below the base height)

Areas are the plan area where z > base (cut) or z < base (fill); the 3D
areas weight each sample by the slope factor sqrt(1 + p^2 + q^2) of Horn's
3x3 gradient per DEM cell, as Global Mapper does.

Results follow Global Mapper (see GM_SCALE_FACTOR_EXPLANATION): its
automatic sample spacing, and areas / volumes scaled by the GM factor, by
default worked out per polygon from Global Mapper's sphere model (or set by
hand / by calibrate_gm_factor from a Global Mapper report).

Install in QGIS: Processing Toolbox > Scripts (python icon) >
"Add Script to Toolbox..." and pick this file.

The numpy/GDAL core (sample_dem_in_polygon, compute_cut_fill,
make_heights, format_gm_report) has no QGIS dependency, so it can be
imported by validate_cut_fill.py from a plain Python with GDAL.
"""

import math
import os
import re

import numpy as np
from osgeo import gdal, ogr, osr

# Global Mapper measures polygon area on a sphere of this radius: the GRS80
# rectifying radius, at which 1 degree of latitude = 111,132.95 m (its mean
# length on the ellipsoid). Fitted on two Global Mapper reports; see
# GM_SCALE_FACTOR_EXPLANATION.
GM_SPHERE_RADIUS = 6367449.146
# Calibrated factor for Example 1 (Landgate clay pan, MGA52). The tool now
# works the factor out per polygon (scale 0 = auto); kept for the validator.
GM_SCALE_FACTOR = 1.002303
# Default sample spacing follows Global Mapper (gm_spacing), but is
# coarsened above this many samples to keep memory in check (~1.5 GB peak).
MAX_DEFAULT_SAMPLES = 20000000

# Shown in the Processing help, the Cut & Fill window and the Excel Notes
# sheet. One paragraph per list item.
GM_SCALE_FACTOR_EXPLANATION = [
    'How the GM area scale factor is worked out',
    'Global Mapper measures a polygon\'s area on a sphere of radius '
    '6,367,449 m: the GRS80 rectifying radius, at which one degree of '
    'latitude is 111,133 m, its average length on the ellipsoid. So the GM '
    'factor for a polygon is its area on that sphere divided by its planar '
    'map-grid area. By default (factor 0 = auto) the tool works this out for '
    'every polygon, so it applies at any location and in any map zone.',
    'Evidence from two Global Mapper reports. In any report, '
    'CUT_VOLUME - FILL_VOLUME falls by exactly the polygon area for every '
    'metre the base height rises, so a straight line through all the rows '
    'gives the area Global Mapper used:',
    '- Example 1, Landgate clay pan (20 m DEM, MGA zone 52, 22.3 S, 62 km '
    'west of the central meridian): Global Mapper area 977,797 m2, planar '
    '975,551 m2, so factor 1.002303. Sphere model: 1.002139 (0.016 % lower).',
    '- Example 2, storage area (0.5 m LiDAR, MGA zone 55, 23.2 S, 137 km '
    'east of the central meridian): Global Mapper area 1,011,369 m2, planar '
    '1,009,729 m2, so factor 1.001624. Sphere model: 1.001627 (0.0003 % '
    'higher).',
    'The ellipsoidal (GRS80) area matches neither report (it is 0.16 % and '
    '0.13 % lower), nor does a sphere of the usual 6,371 km mean radius (0.10 '
    'and 0.11 % higher).',
    'Sample spacing. Global Mapper\'s automatic spacing is min(DEM cell / 2, '
    'smaller side of the polygon\'s bounding box / 200), confirmed against '
    'its Volume Calculation dialog on six polygons: Clay Pans A-E on the 20 m '
    'DEM (e.g. Clay Pan B, the Example 1 polygon: 1,130.79 m / 200 = 5.654 '
    'm; A and C, whose smaller side is the width, rule out height / 200) and '
    'Example 2 (0.5 m cell / 2 = 0.25 m). Adding up '
    'bilinear samples on that grid matches Example 2 within 0.001 % but is '
    '0.2-2 % off Example 1, so for coarse DEMs Global Mapper does more than '
    'sum its samples. This tool uses Global Mapper\'s spacing by default '
    '(coarsened only above 20 million samples, to limit memory); the results '
    'match both reports within 0.1 % on volumes. On coarse DEMs a few 2D '
    'areas differ by up to about 50 samples where a contour crosses many of '
    'them. The small '
    'remaining area gap on Example 1 (0.016 %, about 160 m2) is the size of '
    'a few of its 5.654 m samples along the polygon boundary.',
    'With the sphere-model factor, volumes match both reports within 0.06 %, '
    'with no calibration. 2D areas match within the reports\' printed '
    'rounding. 3D areas use Horn\'s slope of each DEM cell (as GDAL\'s slope '
    'tool), which matches Global Mapper within about 0.1-0.2 %.',
    'To override the factor, type a value, or use "Calibrate from GM '
    'report..." in the Cut & Fill window with a Global Mapper report for one '
    'polygon: it fits CUT_VOLUME - FILL_VOLUME against base height and '
    'divides the resulting area by the polygon\'s planar area. Set the factor '
    'back to 0 for auto, or to 1 to make GM equal to planar.',
]

RESULT_KEYS = ('CUT_VOLUME', 'CUT_AREA', 'CUT_AREA_3D',
               'FILL_VOLUME', 'FILL_AREA', 'FILL_AREA_3D')


# --------------------------------------------------------------------------
# Core (numpy + GDAL only)
# --------------------------------------------------------------------------

def _rasterize_mask(polygon_wkt, srs_wkt, gt, nx, ny):
    """Mask of lattice cells whose centre falls inside the polygon."""
    mem = gdal.GetDriverByName('MEM').Create('', nx, ny, 1, gdal.GDT_Byte)
    mem.SetGeoTransform(gt)
    if srs_wkt:
        mem.SetProjection(srs_wkt)
    vdrv = ogr.GetDriverByName('MEM')  # GDAL >= 3.11 (raster + vector)
    if vdrv is None or vdrv.GetMetadataItem('DCAP_VECTOR') != 'YES':
        vdrv = ogr.GetDriverByName('Memory')
    vds = vdrv.CreateDataSource('mask')
    srs = osr.SpatialReference(wkt=srs_wkt) if srs_wkt else None
    lyr = vds.CreateLayer('poly', srs, ogr.wkbUnknown)
    feat = ogr.Feature(lyr.GetLayerDefn())
    feat.SetGeometry(ogr.CreateGeometryFromWkt(polygon_wkt))
    lyr.CreateFeature(feat)
    gdal.RasterizeLayer(mem, [1], lyr, burn_values=[1])
    return mem.GetRasterBand(1).ReadAsArray().astype(bool)


def _geodesic_area(geom, srs_wkt):
    """Area of ``geom`` on its CRS's ellipsoid (true ground area), or None
    when the CRS is unknown or GDAL is older than 3.9."""
    if not srs_wkt or not hasattr(geom, 'GeodesicArea'):
        return None
    g = geom.Clone()
    srs = osr.SpatialReference(wkt=srs_wkt)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    g.AssignSpatialReference(srs)
    try:
        area = g.GeodesicArea()
    except Exception:
        return None
    return area if area and area > 0 else None


def _gm_sphere_area(geom, srs_wkt):
    """Area of ``geom`` the way Global Mapper measures it: vertices to
    longitude/latitude, then area on a sphere of radius GM_SPHERE_RADIUS.
    None when the CRS is unknown."""
    if not srs_wkt:
        return None
    try:
        srs = osr.SpatialReference(wkt=srs_wkt)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        geo = srs.CloneGeogCS()
        geo.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        g = geom.Clone()
        g.Transform(osr.CoordinateTransformation(srs, geo))
    except Exception:
        return None
    flat = ogr.GT_Flatten(g.GetGeometryType())
    polys = ([g] if flat == ogr.wkbPolygon
             else [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())])
    total = 0.0
    for poly in polys:
        for r in range(poly.GetGeometryCount()):
            pts = np.array(poly.GetGeometryRef(r).GetPoints())[:, :2]
            lon, lat = np.radians(pts[:, 0]), np.radians(pts[:, 1])
            ring = abs(0.5 * np.sum((np.roll(lon, -1) - lon)
                                    * (np.sin(lat) + np.sin(np.roll(lat, -1)))))
            total += ring if r == 0 else -ring
    area = total * GM_SPHERE_RADIUS ** 2
    return area if area > 0 else None


def gm_spacing(cellsize, width, height):
    """Global Mapper's automatic sample spacing: min(DEM cell / 2, smaller
    side of the polygon's bounding box / 200). Confirmed against its Volume
    Calculation dialog on six polygons (Clay Pans A-E, Example 2)."""
    return min(cellsize / 2.0, min(width, height) / 200.0)


def default_spacing(cellsize, width, height, area,
                    max_samples=MAX_DEFAULT_SAMPLES):
    """Global Mapper's spacing (gm_spacing), coarsened only when it would
    put more than ``max_samples`` samples in ``area``, to protect memory
    (e.g. half-cell LiDAR sampling over many km2). Coarsening uses cell / n,
    then half-cell steps, skipping odd whole numbers of cells: that lattice
    sits on cell centres and stops interpolating the DEM (it missed Global
    Mapper's small fill volumes by ~0.3 % on Example 2).
    Returns (spacing, coarsened)."""
    s = gm_spacing(cellsize, width, height)
    if s > 0 and area / (s * s) <= max_samples:
        return s, False
    need = math.sqrt(max(area, 0.0) / max_samples)
    if need <= cellsize / 2.0:
        return cellsize / math.floor(cellsize / need), True
    m = math.ceil(2.0 * need / cellsize) / 2.0
    if m == int(m) and int(m) % 2 == 1:
        m += 0.5
    return cellsize * m, True


def _horn_slope_factor(a, cw, ch):
    """sqrt(1 + p^2 + q^2) per DEM cell from Horn's 3x3 gradient (as GDAL
    slope; this is what reproduces Global Mapper's 3D areas). Edge cells
    copy their inner neighbour; NaN where the 3x3 window touches nodata."""
    p = ((a[:-2, 2:] + 2 * a[1:-1, 2:] + a[2:, 2:])
         - (a[:-2, :-2] + 2 * a[1:-1, :-2] + a[2:, :-2])) / (8.0 * cw)
    q = ((a[2:, :-2] + 2 * a[2:, 1:-1] + a[2:, 2:])
         - (a[:-2, :-2] + 2 * a[:-2, 1:-1] + a[:-2, 2:])) / (8.0 * ch)
    out = np.full(a.shape, np.nan)
    if out.shape[0] < 3 or out.shape[1] < 3:
        return out
    out[1:-1, 1:-1] = np.sqrt(1.0 + p * p + q * q)
    out[0, :], out[-1, :] = out[1, :], out[-2, :]
    out[:, 0], out[:, -1] = out[:, 1], out[:, -2]
    return out


def sample_dem_in_polygon(dem_path, polygon_wkt, spacing=None, band=1):
    """Sample the bilinear DEM surface on a lattice inside the polygon.

    The polygon must be in the DEM's CRS. The lattice is aligned to the DEM
    origin; each sample is the centre of a spacing x spacing lattice cell.
    spacing None / 0 uses default_spacing. The 3D slope factor of a sample
    is the bilinear blend of the Horn factors of the four nearest cells.

    Returns (z, slope, dA, info) where z and slope are 1-D arrays of the
    valid samples, dA is the plan area per sample (polygon area / number of
    lattice samples inside it) and info is a dict.
    """
    ds = gdal.Open(dem_path)
    if ds is None:
        raise RuntimeError('Cannot open DEM: %s' % dem_path)
    gt = ds.GetGeoTransform()
    if gt[2] != 0 or gt[4] != 0:
        raise RuntimeError('Rotated DEMs are not supported.')
    x0, cw, y0, ch = gt[0], gt[1], gt[3], -gt[5]
    rb = ds.GetRasterBand(band)
    nodata = rb.GetNoDataValue()
    cols, rows = ds.RasterXSize, ds.RasterYSize

    geom = ogr.CreateGeometryFromWkt(polygon_wkt)
    minx, maxx, miny, maxy = geom.GetEnvelope()
    gm_s = gm_spacing(min(cw, ch), maxx - minx, maxy - miny)
    if not spacing or spacing <= 0:
        spacing, coarsened = default_spacing(min(cw, ch), maxx - minx,
                                             maxy - miny, geom.GetArea())
        spacing_rule = ('coarsened from Global Mapper\'s %.6g m to limit '
                        'memory' % gm_s if coarsened else 'Global Mapper auto')
    else:
        spacing_rule = 'set by user; Global Mapper auto would be %.6g m' % gm_s
    s = float(spacing)

    # Sample lattice aligned to the DEM origin
    mx0 = x0 + math.floor((minx - x0) / s) * s
    my0 = y0 - math.floor((y0 - maxy) / s) * s
    nx = max(1, int(math.ceil((maxx - mx0) / s)))
    ny = max(1, int(math.ceil((my0 - miny) / s)))
    mask = _rasterize_mask(polygon_wkt, ds.GetProjection(),
                           (mx0, s, 0.0, my0, 0.0, -s), nx, ny)

    # DEM window covering the bbox +/- 2 cells
    c0 = max(0, int(math.floor((minx - x0) / cw)) - 2)
    c1 = min(cols, int(math.ceil((maxx - x0) / cw)) + 2)
    r0 = max(0, int(math.floor((y0 - maxy) / ch)) - 2)
    r1 = min(rows, int(math.ceil((y0 - miny) / ch)) + 2)
    if c1 - c0 < 2 or r1 - r0 < 2:
        raise RuntimeError('Polygon does not overlap the DEM.')
    a = rb.ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(np.float64)
    if nodata is not None:
        a[a == nodata] = np.nan
    a[~np.isfinite(a)] = np.nan
    horn = _horn_slope_factor(a, cw, ch)
    wx0, wy0 = x0 + c0 * cw, y0 - r0 * ch
    h, w = a.shape

    zs, ss = [], []
    n_nodata = 0
    xs = mx0 + (np.arange(nx) + 0.5) * s
    block = max(1, 2000000 // nx)
    for i0 in range(0, ny, block):
        sub = mask[i0:i0 + block]
        ii, jj = np.nonzero(sub)
        if ii.size == 0:
            continue
        x = xs[jj]
        y = my0 - (ii + i0 + 0.5) * s
        # Fractional position relative to cell centres
        c = (x - wx0) / cw - 0.5
        r = (wy0 - y) / ch - 0.5
        j = np.clip(np.floor(c).astype(np.int64), 0, w - 2)
        i = np.clip(np.floor(r).astype(np.int64), 0, h - 2)
        fx = np.clip(c - j, 0.0, 1.0)
        fy = np.clip(r - i, 0.0, 1.0)
        z00 = a[i, j]
        z01 = a[i, j + 1]
        z10 = a[i + 1, j]
        z11 = a[i + 1, j + 1]
        z = (z00 * (1 - fx) * (1 - fy) + z01 * fx * (1 - fy)
             + z10 * (1 - fx) * fy + z11 * fx * fy)
        slope = (horn[i, j] * (1 - fx) * (1 - fy) + horn[i, j + 1] * fx * (1 - fy)
                 + horn[i + 1, j] * (1 - fx) * fy + horn[i + 1, j + 1] * fx * fy)
        # Next to nodata Horn has no full 3x3 window: use the bilinear
        # surface's own gradient there.
        edge = ~np.isfinite(slope)
        if edge.any():
            dzdx = ((z01 - z00) * (1 - fy) + (z11 - z10) * fy) / cw
            dzdy = ((z10 - z00) * (1 - fx) + (z11 - z01) * fx) / ch
            slope[edge] = np.sqrt(1.0 + dzdx * dzdx + dzdy * dzdy)[edge]
        ok = np.isfinite(z)
        n_nodata += int((~ok).sum())
        zs.append(z[ok])
        ss.append(slope[ok])

    z = np.concatenate(zs) if zs else np.empty(0)
    slope = np.concatenate(ss) if ss else np.empty(0)
    # Each sample stands for an equal share of the exact polygon area, so
    # the samples add up to the polygon's area rather than to a whole number
    # of spacing x spacing squares (which is off by the samples straddling
    # the boundary: -0.037 % vs Global Mapper on Example 1, -0.016 % with
    # this). Nodata samples keep their share missing.
    n_all = z.size + n_nodata
    dA = geom.GetArea() / n_all if n_all else s * s
    info = {
        'spacing': s,
        'gm_spacing': gm_s,
        'spacing_rule': spacing_rule,
        'cellsize': (cw, ch),
        'n_samples': int(z.size),
        'n_nodata': n_nodata,
        'polygon_area': geom.GetArea(),
        'ellipsoidal_area': _geodesic_area(geom, ds.GetProjection()),
        'gm_sphere_area': _gm_sphere_area(geom, ds.GetProjection()),
        'sampled_area': z.size * dA,
        'z_min': float(z.min()) if z.size else None,
        'z_max': float(z.max()) if z.size else None,
    }
    return z, slope, dA, info


def compute_cut_fill(z, slope, dA, heights):
    """Cut/fill volumes and areas for every base height (planar units).

    Sorts z once and uses cumulative sums, so all heights cost one
    O(n log n) pass. Returns a dict of arrays keyed by RESULT_KEYS.
    """
    heights = np.asarray(heights, dtype=np.float64)
    n = z.size
    out = {k: np.zeros(heights.size) for k in RESULT_KEYS}
    if n == 0:
        return out
    zref = float(np.min(z))
    order = np.argsort(z, kind='stable')
    zs = z[order] - zref
    ss = slope[order]
    cz = np.concatenate(([0.0], np.cumsum(zs)))
    cs = np.concatenate(([0.0], np.cumsum(ss)))
    hr = heights - zref
    lt = np.searchsorted(zs, hr, side='left')    # samples with z < h
    le = np.searchsorted(zs, hr, side='right')   # samples with z <= h
    gt = n - le                                  # samples with z > h
    out['FILL_VOLUME'] = np.maximum(hr * lt - cz[lt], 0.0) * dA
    out['FILL_AREA'] = lt * dA
    out['FILL_AREA_3D'] = cs[lt] * dA
    out['CUT_VOLUME'] = np.maximum((cz[n] - cz[le]) - hr * gt, 0.0) * dA
    out['CUT_AREA'] = gt * dA
    out['CUT_AREA_3D'] = (cs[n] - cs[le]) * dA
    return out


def make_heights(start, end, step):
    """Inclusive list of base heights from start to end by step."""
    if step <= 0:
        raise ValueError('Step must be positive.')
    if end < start:
        start, end = end, start
    n = int(math.floor((end - start) / step + 1e-9)) + 1
    return np.round(start + step * np.arange(n), 6)


def default_range(z, step):
    """Base height range covering z, rounded outward to the step."""
    lo = math.floor(float(np.min(z)) / step) * step
    hi = math.ceil(float(np.max(z)) / step) * step
    return lo, hi


def cut_fill_for_polygon(dem_path, polygon_wkt, step, start=None, end=None,
                         spacing=None, band=1, name=''):
    """Full calculation for one polygon (in the DEM CRS).

    start / end of None use the DEM range inside the polygon. Returns an
    area dict {name, heights, res, info, ellipsoidal_area} as used by
    write_excel, or None when the polygon has no valid DEM samples.
    ellipsoidal_area is None if GDAL cannot measure it; callers inside QGIS
    fill it in with QgsDistanceArea.
    """
    z, slope, dA, info = sample_dem_in_polygon(dem_path, polygon_wkt,
                                               spacing, band)
    if z.size == 0:
        return None
    lo, hi = default_range(z, step)
    heights = make_heights(lo if start is None else start,
                           hi if end is None else end, step)
    return {'name': name, 'heights': heights,
            'res': compute_cut_fill(z, slope, dA, heights), 'info': info,
            'ellipsoidal_area': info['ellipsoidal_area']}


def _sig(value, digits):
    if value == 0:
        return '0'
    return np.format_float_positional(value, precision=digits,
                                      fractional=False, trim='-')


def _fmt_area_km2(value_m2):
    """km2 with 3 sig figs when the leading digit is >= 5, else 4 (as GM)."""
    v = value_m2 / 1e6
    if v == 0:
        return '0'
    lead = int(('%e' % abs(v))[0])
    return _sig(v, 3 if lead >= 5 else 4)


def format_gm_report(heights, res, scale=1.0):
    """Global Mapper style CSV text (CRLF line endings)."""
    lines = ['BASE_HEIGHT,CUT_VOLUME,CUT_AREA,CUT_AREA_3D,'
             'FILL_VOLUME,FILL_AREA,FILL_AREA_3D']
    for k, h in enumerate(heights):
        lines.append(','.join([
            '%s  m' % _sig(float(h), 10),
            '%s cubic meters' % _sig(res['CUT_VOLUME'][k] * scale, 8),
            '%s sq km' % _fmt_area_km2(res['CUT_AREA'][k] * scale),
            '%s sq km' % _fmt_area_km2(res['CUT_AREA_3D'][k] * scale),
            '%s cubic meters' % _sig(res['FILL_VOLUME'][k] * scale, 8),
            '%s sq km' % _fmt_area_km2(res['FILL_AREA'][k] * scale),
            '%s sq km' % _fmt_area_km2(res['FILL_AREA_3D'][k] * scale),
        ]))
    return '\r\n'.join(lines) + '\r\n'


def write_gm_report(path, heights, res, scale=1.0):
    with open(path, 'w', newline='') as f:
        f.write(format_gm_report(heights, res, scale))


def _safe_name(text):
    return re.sub(r'[^\w\-. ]+', '_', str(text)).strip() or 'feature'


def write_gm_csvs(folder, areas, scale):
    """<name>.csv per area in Global Mapper text format; duplicate names get
    _2, _3... Returns the paths written."""
    os.makedirs(folder, exist_ok=True)
    used, paths = set(), []
    for area in areas:
        stem = _safe_name(area['name'])
        base, k = stem, 2
        while base.lower() in used:
            base = '%s_%d' % (stem, k)
            k += 1
        used.add(base.lower())
        factor = gm_factor(area, scale)
        if factor is None:
            continue
        path = os.path.join(folder, base + '.csv')
        write_gm_report(path, area['heights'], area['res'], factor)
        paths.append(path)
    return paths


def area_summary_text(area, scale):
    """One-line description of an area's polygon and sampling."""
    info, heights = area['info'], area['heights']
    gm_f = gm_factor(area, scale)
    return ('%s: area %s m2 (Global Mapper method, factor %s, %s); %s samples '
            'at %.6g m spacing (%s), %d nodata samples skipped; base %g to %g m.'
            % (area['name'],
               '-' if gm_f is None else format(info['polygon_area'] * gm_f, ',.1f'),
               '-' if gm_f is None else '%.6f' % gm_f,
               'manual' if scale and scale > 0 else 'auto',
               format(info['n_samples'], ','), info['spacing'],
               info.get('spacing_rule', ''), info['n_nodata'],
               heights[0], heights[-1]))


# --------------------------------------------------------------------------
# Global Mapper report reading and scale-factor calibration
# --------------------------------------------------------------------------

# Units Global Mapper can print in a cut-and-fill report -> SI multiplier.
_GM_UNITS = {
    '': 1.0, 'm': 1.0, 'meters': 1.0, 'metres': 1.0,
    'ft': 0.3048, 'feet': 0.3048,
    'cubic meters': 1.0, 'cubic metres': 1.0, 'cubic m': 1.0,
    'cubic feet': 0.028316846592, 'cubic yards': 0.764554857984,
    'acre-feet': 1233.48183754752, 'acre feet': 1233.48183754752,
    'sq km': 1e6, 'sq m': 1.0, 'sq meters': 1.0, 'sq metres': 1.0,
    'square meters': 1.0, 'hectares': 1e4, 'ha': 1e4,
    'sq ft': 0.09290304, 'acres': 4046.8564224, 'sq mi': 2589988.110336,
}


def read_gm_report(path):
    """Parse a Global Mapper cut-and-fill report (values like
    ``5525264.1 cubic meters``) into arrays in metres, m3 and m2."""
    with open(path, encoding='utf-8-sig') as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        raise ValueError('The report is empty.')
    header = [h.strip().upper() for h in lines[0].split(',')]
    for need in ('BASE_HEIGHT', 'CUT_VOLUME', 'FILL_VOLUME'):
        if need not in header:
            raise ValueError('Not a Global Mapper cut-and-fill report: no %s '
                             'column.' % need)
    cols = {name: [] for name in header}
    for ln in lines[1:]:
        cells = ln.split(',')
        if len(cells) != len(header):
            continue
        for name, cell in zip(header, cells):
            parts = cell.split()
            unit = ' '.join(parts[1:]).lower()
            if unit not in _GM_UNITS:
                raise ValueError('Unknown unit "%s" in %s.' % (unit, name))
            cols[name].append(float(parts[0]) * _GM_UNITS[unit])
    return {k: np.array(v) for k, v in cols.items()}


def calibrate_gm_factor(report_path, planar_area):
    """GM scale factor for one polygon from a Global Mapper report of it.

    At every base height h, CUT - FILL = A x (mean ground level - h), so the
    net volume falls by exactly the polygon area A (as Global Mapper measures
    it) for each metre the base rises. A straight line through all rows gives
    A; the factor is A / planar_area. Returns a dict with factor, gm_area,
    rows and rel_residual (the fit's largest miss / largest net volume).
    """
    rep = read_gm_report(report_path)
    h = rep['BASE_HEIGHT']
    net = rep['CUT_VOLUME'] - rep['FILL_VOLUME']
    if h.size < 2 or np.ptp(h) == 0:
        raise ValueError('The report needs at least two different base heights.')
    slope, icpt = np.polyfit(h, net, 1)
    gm_area = -float(slope)
    if gm_area <= 0:
        raise ValueError('The report does not give a positive polygon area.')
    resid = net - (slope * h + icpt)
    rel = float(np.max(np.abs(resid)) / max(float(np.max(np.abs(net))), 1.0))
    return {'factor': gm_area / planar_area, 'gm_area': gm_area,
            'rows': int(h.size), 'rel_residual': rel}


# --------------------------------------------------------------------------
# Excel workbook: Summary sheet + one sheet per area + Notes
# --------------------------------------------------------------------------

M3_PER_ML = 1000.0   # 1 megalitre = 1,000 m3

# Result groups: (column suffix, heading). One group: results computed the
# way Global Mapper does (its spacing, its area model).
BASES = (('', 'Global Mapper method'),)


def gm_factor(area, scale):
    """GM factor for an area: ``scale`` when it is > 0 (typed in or
    calibrated), otherwise automatic = Global Mapper's sphere-model area /
    planar area for this polygon (None if the CRS is unknown)."""
    if scale and scale > 0:
        return float(scale)
    sphere, planar = area['info'].get('gm_sphere_area'), area['info']['polygon_area']
    return sphere / planar if sphere and planar else None


def gm_factor_label(scale):
    """How the GM factor was set, for notes and messages."""
    if scale and scale > 0:
        return '%.6f (set by user / calibrated)' % scale
    return 'auto (Global Mapper sphere model, per area)'


def basis_factor(area, basis, scale):
    """Multiplier from planar results to the reported (Global Mapper) values."""
    return gm_factor(area, scale)


# (name, unit, basis); basis None = shown with every group.
SUMMARY_COLUMNS = [
    ('AREA_NAME', None, None), ('SHEET', None, None),
    ('POLYGON_AREA', 'm2', None),
    ('DEM_MIN', 'm', None), ('DEM_MAX', 'm', None),
    ('BASE_START', 'm', None), ('BASE_END', 'm', None), ('BASE_STEP', 'm', None),
    ('MAX_FILL_VOLUME', 'm3', None), ('MAX_FILL_VOLUME_ML', 'ML', None),
    ('SAMPLES', None, None), ('SAMPLE_SPACING', 'm', None),
    ('NODATA_SAMPLES', None, None),
]
FACTOR_COLUMNS = ()


def _unit(key):
    return 'm3' if key.endswith('VOLUME') else 'm2'


def _area_columns():
    """(name, result key, basis, unit) for each per-area output column.

    Every volume column is followed by the same volume in ML.
    """
    cols = [('BASE_HEIGHT', None, None, 'm')]
    for basis, _label in BASES:
        for k in RESULT_KEYS:
            cols.append((k + basis, k, basis, _unit(k)))
            if k.endswith('VOLUME'):
                cols.append((k + basis + '_ML', k, basis, 'ML'))
    return cols


AREA_COLUMNS = _area_columns()
GROUP_WIDTH = (len(AREA_COLUMNS) - 1) // len(BASES)   # columns per group


def _sheet_names(labels):
    """Unique Excel-safe sheet names (<= 31 chars, no []:*?/\\)."""
    used = {'summary', 'notes'}
    out = []
    for label in labels:
        base = re.sub(r'[\[\]:*?/\\]', '_', str(label)).strip().strip("'")
        base = (base or 'Area')[:31]
        name, n = base, 2
        while name.lower() in used:
            suffix = ' (%d)' % n
            name = base[:31 - len(suffix)] + suffix
            n += 1
        used.add(name.lower())
        out.append(name)
    return out


def _summary_row(area, sheet, scale):
    info, res, heights = area['info'], area['res'], area['heights']
    step = float(heights[1] - heights[0]) if len(heights) > 1 else 0.0
    f = gm_factor(area, scale)
    max_fill = None if f is None else float(res['FILL_VOLUME'][-1]) * f
    return [
        str(area['name']), sheet,
        None if f is None else info['polygon_area'] * f,
        info.get('z_min'), info.get('z_max'),
        float(heights[0]), float(heights[-1]), round(step, 6),
        max_fill, None if max_fill is None else max_fill / M3_PER_ML,
        info['n_samples'], info['spacing'], info['n_nodata'],
    ]


def _area_rows(area, scale):
    """Rows of values matching AREA_COLUMNS (None where a group's factor is
    unknown)."""
    res, heights = area['res'], area['heights']
    factors = {b: basis_factor(area, b, scale) for b, _l in BASES}
    rows = []
    for k, h in enumerate(heights):
        row = []
        for _name, key, basis, unit in AREA_COLUMNS:
            if key is None:
                row.append(float(h))
                continue
            f = factors[basis]
            if f is None:
                row.append(None)
                continue
            v = float(res[key][k]) * f
            row.append(v / M3_PER_ML if unit == 'ML' else v)
        rows.append(row)
    return rows


def _notes(scale):
    return (GM_SCALE_FACTOR_EXPLANATION
            + ['', 'GM scale factor in this workbook: %s' % gm_factor_label(scale)])


def write_excel(path, areas, scale):
    """Write a Summary sheet, one sheet per area and a Notes sheet
    explaining how the results match Global Mapper.

    areas: list of dicts with keys name, heights, res, info and optionally
    ellipsoidal_area. Uses openpyxl (formatted) when available, otherwise
    GDAL's XLSX driver (same sheets, no formatting). Returns the writer used.
    """
    sheets = _sheet_names([a['name'] for a in areas])
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        _write_excel_gdal(path, areas, sheets, scale)
        return 'gdal'
    _write_excel_openpyxl(path, areas, sheets, scale)
    return 'openpyxl'


def _write_excel_openpyxl(path, areas, sheets, scale):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.hyperlink import Hyperlink

    bold = Font(bold=True)
    fills = {None: PatternFill('solid', fgColor='EDEDED'),
             '': PatternFill('solid', fgColor='DDEBF7')}
    thin = Side(style='thin', color='999999')
    box = Border(bottom=thin)
    centre = Alignment(horizontal='center', vertical='center', wrap_text=True)
    fmt = {'m3': '#,##0.0', 'ML': '#,##0.000', 'm2': '#,##0', 'm': '0.000',
           None: 'General'}

    def put(ws, r, c, value, unit):
        """Write a cell; ML cells are formulas on the m3 cell to their left."""
        if unit == 'ML' and value is not None:
            value = '=%s%d/%g' % (get_column_letter(c - 1), r, M3_PER_ML)
        cell = ws.cell(r, c, value)
        cell.number_format = fmt[unit]
        return cell

    def link_to(cell, sheet):
        """Internal link to another sheet in this workbook."""
        cell.hyperlink = Hyperlink(ref=cell.coordinate,
                                   location="'%s'!A1" % sheet.replace("'", "''"))
        cell.font = Font(color='0563C1', underline='single')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Summary'
    ws['A1'] = 'Cut & fill summary'
    ws['A1'].font = Font(bold=True, size=13)
    ws['A2'] = ('Areas and volumes are computed the way Global Mapper does '
                '(GM factor: %s). MAX_FILL_VOLUME is the fill volume at the '
                'highest base height. 1 ML = 1,000 m3.' % gm_factor_label(scale))
    ws['A3'] = 'How the results match Global Mapper: see Notes'
    link_to(ws['A3'], 'Notes')
    hdr = 4
    for c, (name, unit, basis) in enumerate(SUMMARY_COLUMNS, 1):
        cell = ws.cell(hdr, c, name + (' (%s)' % unit if unit else ''))
        cell.font, cell.fill, cell.alignment, cell.border = bold, fills[basis], centre, box
    for r, (area, sheet) in enumerate(zip(areas, sheets), hdr + 1):
        for c, value in enumerate(_summary_row(area, sheet, scale), 1):
            cell = put(ws, r, c, value, SUMMARY_COLUMNS[c - 1][1])
            if SUMMARY_COLUMNS[c - 1][0] in FACTOR_COLUMNS:
                cell.number_format = '0.000000'
        link_to(ws.cell(r, 2), sheet)
    ws.freeze_panes = ws.cell(hdr + 1, 2)
    for c, (name, _u, _b) in enumerate(SUMMARY_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(c)].width = max(12, min(28, len(name) + 4))
    ws.row_dimensions[hdr].height = 32

    ncol = len(AREA_COLUMNS)
    for area, sheet in zip(areas, sheets):
        ws = wb.create_sheet(sheet)
        ws['A1'] = str(area['name'])
        ws['A1'].font = Font(bold=True, size=13)
        ws['A2'] = area_summary_text(area, scale)
        ws['A3'] = '<- Summary'
        link_to(ws['A3'], 'Summary')
        # Group headers (row 4) and column headers (row 5)
        ws.cell(4, 1).fill = fills[None]
        for g, (basis, label) in enumerate(BASES):
            c0 = 2 + g * GROUP_WIDTH
            ws.merge_cells(start_row=4, start_column=c0, end_row=4,
                           end_column=c0 + GROUP_WIDTH - 1)
            f = basis_factor(area, basis, scale)
            ws.cell(4, c0, label if basis == '' else '%s (x %s)' % (
                label, 'n/a' if f is None else '%.6f' % f))
        for c, (name, _k, basis, unit) in enumerate(AREA_COLUMNS, 1):
            g = ws.cell(4, c)
            g.font, g.alignment, g.fill = bold, centre, fills[basis]
            cell = ws.cell(5, c, '%s (%s)' % (name, unit))
            cell.font, cell.alignment, cell.border = bold, centre, box
            cell.fill = fills[basis]
        for r, row in enumerate(_area_rows(area, scale), 6):
            for c, value in enumerate(row, 1):
                put(ws, r, c, value, AREA_COLUMNS[c - 1][3])
        ws.freeze_panes = 'B6'
        ws.row_dimensions[5].height = 32
        for c in range(1, ncol + 1):
            ws.column_dimensions[get_column_letter(c)].width = 16

    ws = wb.create_sheet('Notes')
    ws.column_dimensions['A'].width = 110
    wrap = Alignment(wrap_text=True, vertical='top')
    titles = {GM_SCALE_FACTOR_EXPLANATION[0]}
    notes = _notes(scale)
    for r, text in enumerate(notes, 1):
        cell = ws.cell(r, 1, text or None)
        cell.alignment = wrap
        if text in titles:
            cell.font = Font(bold=True, size=13)
    ws.cell(len(notes), 1).font = bold
    link_to(ws.cell(len(notes) + 1, 1, '<- Summary'), 'Summary')
    wb.save(path)


def _write_excel_gdal(path, areas, sheets, scale):
    drv = gdal.GetDriverByName('XLSX')
    if drv is None:
        raise RuntimeError('Neither openpyxl nor the GDAL XLSX driver is available.')
    if os.path.exists(path):
        drv.Delete(path)
    ds = drv.Create(path, 0, 0, 0, gdal.GDT_Unknown)

    def add_layer(name, columns, rows):
        lyr = ds.CreateLayer(name, geom_type=ogr.wkbNone)
        for col, kind in columns:
            lyr.CreateField(ogr.FieldDefn(col, kind))
        defn = lyr.GetLayerDefn()
        for row in rows:
            f = ogr.Feature(defn)
            for i, v in enumerate(row):
                if v is not None:
                    f.SetField(i, v)
            lyr.CreateFeature(f)

    text = {'AREA_NAME', 'SHEET'}
    add_layer('Summary',
              [(n, ogr.OFTString if n in text else ogr.OFTReal)
               for n, _u, _b in SUMMARY_COLUMNS],
              [_summary_row(a, s, scale) for a, s in zip(areas, sheets)])
    cols = [(name, ogr.OFTReal) for name, _k, _b, _u in AREA_COLUMNS]
    for area, sheet in zip(areas, sheets):
        add_layer(sheet, cols, _area_rows(area, scale))
    add_layer('Notes', [('NOTE', ogr.OFTString)], [[t] for t in _notes(scale)])
    ds = None


# --------------------------------------------------------------------------
# QGIS Processing algorithm (only defined when running inside QGIS)
# --------------------------------------------------------------------------

try:
    from qgis.core import (
        Qgis,
        QgsCoordinateTransform,
        QgsDistanceArea,
        QgsFeature,
        QgsFeatureSink,
        QgsField,
        QgsFields,
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingException,
        QgsProcessingParameterBand,
        QgsProcessingParameterFeatureSink,
        QgsProcessingParameterFeatureSource,
        QgsProcessingParameterField,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterNumber,
        QgsProcessingParameterRasterLayer,
        QgsWkbTypes,
    )
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False


if HAS_QGIS:

    def _enum(*getters):
        """First enum value that exists (QGIS 3.28 - 4.x API differences)."""
        for g in getters:
            try:
                return g()
            except AttributeError:
                continue
        raise AttributeError('No matching enum found')

    _POLYGON = _enum(lambda: Qgis.ProcessingSourceType.VectorPolygon,
                     lambda: QgsProcessing.TypeVectorPolygon)
    _VECTOR_ANY = _enum(lambda: Qgis.ProcessingSourceType.Vector,
                        lambda: QgsProcessing.TypeVector)
    _DOUBLE = _enum(lambda: Qgis.ProcessingNumberParameterType.Double,
                    lambda: QgsProcessingParameterNumber.Double)
    _FOLDER = _enum(lambda: Qgis.ProcessingFileParameterBehavior.Folder,
                    lambda: QgsProcessingParameterFile.Folder)
    _NO_GEOM = _enum(lambda: Qgis.WkbType.NoGeometry,
                     lambda: QgsWkbTypes.NoGeometry)
    _FAST_INSERT = _enum(lambda: QgsFeatureSink.Flag.FastInsert,
                         lambda: QgsFeatureSink.FastInsert)

    def _field(name, kind):
        try:
            from qgis.PyQt.QtCore import QMetaType
            t = QMetaType.Type.Double if kind == 'double' else QMetaType.Type.QString
            return QgsField(name, t)
        except (ImportError, AttributeError, TypeError):
            from qgis.PyQt.QtCore import QVariant
            t = QVariant.Double if kind == 'double' else QVariant.String
            return QgsField(name, t)

    class CutFillVolumeAlgorithm(QgsProcessingAlgorithm):
        INPUT_DEM = 'INPUT_DEM'
        BAND = 'BAND'
        INPUT_POLYGONS = 'INPUT_POLYGONS'
        NAME_FIELD = 'NAME_FIELD'
        START = 'START'
        END = 'END'
        STEP = 'STEP'
        SPACING = 'SPACING'
        SCALE = 'SCALE'
        OUTPUT_FOLDER = 'OUTPUT_FOLDER'
        OUTPUT_XLSX = 'OUTPUT_XLSX'
        OUTPUT = 'OUTPUT'

        def name(self):
            return 'cutfillvolume'

        def displayName(self):
            return 'Cut & Fill Volume (stage-volume)'

        def group(self):
            return 'Hydrology tools'

        def groupId(self):
            return 'hydrologytools'

        def tags(self):
            return ['cut', 'fill', 'volume', 'storage', 'stage', 'dem',
                    'earthworks', 'global mapper', 'base height']

        def shortHelpString(self):
            return (
                'Cut and fill volumes inside each polygon for a range of base '
                'heights, matching the Global Mapper cut-and-fill report.\n\n'
                'CUT = ground above the base height; FILL = space below it. '
                'The DEM is sampled as a bilinear surface on a fine lattice '
                '(by default Global Mapper\'s automatic spacing: min(DEM cell / '
                '2, smaller side of the polygon\'s bounding box / 200)). 3D areas use the Horn slope of each DEM cell, as '
                'Global Mapper does.\n\n'
                'Results are computed the way Global Mapper does. The GM '
                'area scale factor default 0 works it out for each polygon '
                'from Global Mapper\'s area model, so it applies at any '
                'location; type a value, or use "Calibrate from GM report..." '
                'in the Cut & Fill window, to override it.\n\n'
                'Base heights run from Start to End in Step increments, as '
                'in Global Mapper\'s "Range of Base Heights" (all required). '
                'If an output folder is given, <name>.csv is written per area '
                'in Global Mapper text format.\n\n'
                'Excel workbook (optional): a Summary sheet with one row per '
                'area (area, DEM range, maximum fill volume, links), one '
                'sheet per area, and a Notes sheet explaining how the results '
                'match Global Mapper. '
                'Use the Name field to label the areas and sheets.\n\n'
                + '\n\n'.join(GM_SCALE_FACTOR_EXPLANATION))

        def createInstance(self):
            return CutFillVolumeAlgorithm()

        def initAlgorithm(self, config=None):
            self.addParameter(QgsProcessingParameterRasterLayer(
                self.INPUT_DEM, 'DEM'))
            self.addParameter(QgsProcessingParameterBand(
                self.BAND, 'Band', 1, self.INPUT_DEM))
            self.addParameter(QgsProcessingParameterFeatureSource(
                self.INPUT_POLYGONS, 'Polygons', [_POLYGON]))
            self.addParameter(QgsProcessingParameterField(
                self.NAME_FIELD, 'Name field (optional)',
                parentLayerParameterName=self.INPUT_POLYGONS, optional=True))
            self.addParameter(QgsProcessingParameterNumber(
                self.START, 'Base height from (m)', _DOUBLE))
            self.addParameter(QgsProcessingParameterNumber(
                self.END, 'Base height to (m)', _DOUBLE))
            self.addParameter(QgsProcessingParameterNumber(
                self.STEP, 'Base height step (m)', _DOUBLE,
                minValue=0.000001))
            self.addParameter(QgsProcessingParameterNumber(
                self.SPACING, 'Sample spacing (0 = auto, as Global Mapper: '
                'min(DEM cell / 2, smaller bbox side / 200))',
                _DOUBLE, 0.0, minValue=0.0))
            self.addParameter(QgsProcessingParameterNumber(
                self.SCALE, 'GM area scale factor '
                '(0 = auto, Global Mapper sphere model)',
                _DOUBLE, 0.0, minValue=0.0))
            self.addParameter(QgsProcessingParameterFile(
                self.OUTPUT_FOLDER, 'Folder for Global Mapper format CSVs',
                behavior=_FOLDER, optional=True))
            self.addParameter(QgsProcessingParameterFileDestination(
                self.OUTPUT_XLSX,
                'Excel workbook (Summary + one sheet per area)',
                'Excel files (*.xlsx)', optional=True, createByDefault=False))
            self.addParameter(QgsProcessingParameterFeatureSink(
                self.OUTPUT, 'Cut & fill table', _VECTOR_ANY))

        def processAlgorithm(self, parameters, context, feedback):
            dem = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
            if dem is None or dem.providerType() != 'gdal':
                raise QgsProcessingException('DEM must be a GDAL raster layer.')
            dem_path = dem.source().split('|')[0]
            band = self.parameterAsInt(parameters, self.BAND, context) or 1
            source = self.parameterAsSource(parameters, self.INPUT_POLYGONS, context)
            if source is None:
                raise QgsProcessingException('Invalid polygon layer.')
            name_field = self.parameterAsString(parameters, self.NAME_FIELD, context)
            start = self.parameterAsDouble(parameters, self.START, context)
            end = self.parameterAsDouble(parameters, self.END, context)
            step = self.parameterAsDouble(parameters, self.STEP, context)
            if end <= start or step <= 0:
                raise QgsProcessingException(
                    'Base heights: "to" must be above "from", and the step '
                    'must be positive.')
            spacing = self.parameterAsDouble(parameters, self.SPACING, context)
            scale = self.parameterAsDouble(parameters, self.SCALE, context)
            folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
            if folder:
                os.makedirs(folder, exist_ok=True)
            xlsx = self.parameterAsFileOutput(parameters, self.OUTPUT_XLSX, context)
            if xlsx and not xlsx.lower().endswith('.xlsx'):
                xlsx += '.xlsx'
            areas = []

            fields = QgsFields()
            fields.append(_field('FEATURE', 'string'))
            for name, _k, _b, _u in AREA_COLUMNS:
                fields.append(_field(name, 'double'))
            for name in FACTOR_COLUMNS:
                fields.append(_field(name, 'double'))
            sink, dest_id = self.parameterAsSink(
                parameters, self.OUTPUT, context, fields, _NO_GEOM)
            if sink is None:
                raise QgsProcessingException('Cannot create output table.')

            dem_crs = dem.crs()
            xform = None
            if source.sourceCrs() != dem_crs:
                xform = QgsCoordinateTransform(
                    source.sourceCrs(), dem_crs, context.transformContext())
            da = QgsDistanceArea()
            da.setSourceCrs(dem_crs, context.transformContext())
            da.setEllipsoid(context.ellipsoid() or dem_crs.ellipsoidAcronym()
                            or 'EPSG:7019')

            total = source.featureCount() or 1
            for n, feat in enumerate(source.getFeatures()):
                if feedback.isCanceled():
                    break
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                if xform is not None:
                    geom.transform(xform)
                label = (str(feat[name_field]) if name_field
                         and feat[name_field] is not None else str(feat.id()))

                area = cut_fill_for_polygon(dem_path, geom.asWkt(), step,
                                            start, end, spacing, band, label)
                if area is None:
                    feedback.reportError(
                        '%s: no valid DEM samples inside polygon.' % label)
                    continue
                if area['ellipsoidal_area'] is None:   # GDAL < 3.9
                    try:
                        area['ellipsoidal_area'] = da.measureArea(geom)
                    except Exception:
                        pass
                feedback.pushInfo(area_summary_text(area, scale))
                factors = []
                for row in _area_rows(area, scale):
                    f = QgsFeature(fields)
                    f.setAttributes([label] + row + factors)
                    sink.addFeature(f, _FAST_INSERT)
                areas.append(area)
                feedback.setProgress(100.0 * (n + 1) / total)

            if folder and areas:
                for path in write_gm_csvs(folder, areas, scale):
                    feedback.pushInfo('Wrote %s' % path)

            if xlsx and areas:
                folder_x = os.path.dirname(xlsx)
                if folder_x:
                    os.makedirs(folder_x, exist_ok=True)
                writer = write_excel(xlsx, areas, scale)
                feedback.pushInfo('Wrote Excel workbook %s (%d area sheets + '
                                  'Summary, via %s)' % (xlsx, len(areas), writer))
                if writer == 'gdal':
                    feedback.pushWarning(
                        'openpyxl is not installed in this QGIS, so the '
                        'workbook was written without formatting.')

            return {self.OUTPUT: dest_id, self.OUTPUT_FOLDER: folder,
                    self.OUTPUT_XLSX: xlsx or None}
