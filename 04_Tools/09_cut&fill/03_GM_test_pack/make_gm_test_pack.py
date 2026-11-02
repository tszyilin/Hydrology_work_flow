"""
Build the synthetic Global Mapper test pack: one folder per test with a
GeoTIFF DEM (dem.tif) and a one-polygon shapefile (area.shp), plus
tests.json describing each test (base heights to run, what it probes).

Each surface has a known answer, so the Global Mapper reports that come
back pin down how it measures area, interpolates the DEM, measures 3D area
and handles the polygon boundary. analyse_gm_tests.py compares the reports
with each hypothesis.

    python -I make_gm_test_pack.py
"""

import json
import math
import os

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))


def srs_of(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(epsg)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def to_crs(epsg, lon, lat):
    """lon/lat (GDA2020) -> x, y in epsg."""
    t = osr.CoordinateTransformation(srs_of(7844), srs_of(epsg))
    x, y, _ = t.TransformPoint(lon, lat)
    return x, y


def write_dem(path, epsg, x0, y0, cell, z):
    """z[row, col], row 0 at the top; (x0, y0) = top-left corner."""
    drv = gdal.GetDriverByName('GTiff')
    ds = drv.Create(path, z.shape[1], z.shape[0], 1, gdal.GDT_Float32,
                    options=['COMPRESS=DEFLATE'])
    ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell))
    ds.SetProjection(srs_of(epsg).ExportToWkt())
    ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
    ds = None


def write_polygon(path, epsg, ring, name):
    drv = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    ds = drv.CreateDataSource(path)
    lyr = ds.CreateLayer('area', srs_of(epsg), ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('Name', ogr.OFTString))
    poly = ogr.Geometry(ogr.wkbPolygon)
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ring:
        r.AddPoint_2D(x, y)
    r.CloseRings()
    poly.AddGeometry(r)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetField('Name', name)
    f.SetGeometry(poly)
    lyr.CreateFeature(f)
    ds = None


def square(cx, cy, w, h=None):
    h = w if h is None else h
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
            (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def circle(cx, cy, r, n=720):
    return [(cx + r * math.cos(2 * math.pi * i / n),
             cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def grid_around(ring, cell, margin_cells=30, snap=None):
    """DEM top-left corner and size covering the ring + margin, snapped to
    whole cells (snap = coordinate the grid lines pass through)."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    snap = snap if snap is not None else (0.0, 0.0)
    x0 = snap[0] + math.floor((min(xs) - snap[0]) / cell - margin_cells) * cell
    y1 = snap[1] + math.ceil((max(ys) - snap[1]) / cell + margin_cells) * cell
    nx = int(math.ceil((max(xs) - x0) / cell + margin_cells))
    ny = int(math.ceil((y1 - min(ys)) / cell + margin_cells))
    return x0, y1, nx, ny


def cell_centres(x0, y0, cell, nx, ny):
    xc = x0 + (np.arange(nx) + 0.5) * cell
    yc = y0 - (np.arange(ny) + 0.5) * cell
    return np.meshgrid(xc, yc)


TESTS = []


def add(tid, title, probes, epsg, cell, ring, surface, bases, centre_cell=False):
    folder = os.path.join(HERE, tid)
    os.makedirs(folder, exist_ok=True)
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    snap = (cx - cell / 2, cy - cell / 2) if centre_cell else (cx, cy)
    x0, y0, nx, ny = grid_around(ring, cell, snap=snap)
    X, Y = cell_centres(x0, y0, cell, nx, ny)
    z = surface(X - cx, Y - cy)
    write_dem(os.path.join(folder, 'dem.tif'), epsg, x0, y0, cell, z)
    write_polygon(os.path.join(folder, 'area.shp'), epsg, ring, tid)
    TESTS.append({'id': tid, 'title': title, 'probes': probes, 'epsg': epsg,
                  'cell': cell, 'base_from': bases[0], 'base_to': bases[1],
                  'base_step': bases[2], 'folder': tid})


def flat(dx, dy):
    return np.zeros_like(dx)


# ---- Area model: flat ground at 0, FILL = Global Mapper area x base height
for tid, lon, lat, label in (
        ('T01', 147.0, -25.0, 'MGA55 on the central meridian, 25 S'),
        ('T02', 150.0, -25.0, 'MGA55 300 km east of the central meridian, 25 S'),
        ('T03', 147.0, -40.0, 'MGA55 on the central meridian, 40 S'),
        ('T04', 147.0, -10.0, 'MGA55 on the central meridian, 10 S')):
    x, y = to_crs(7855, lon, lat)
    add(tid, 'Flat, 1 km square, ' + label,
        'area model (latitude / distance from central meridian)',
        7855, 10.0, square(x, y, 1000.0), flat, (1, 3, 1))

add('T05', 'Flat, 0.01 deg square, geographic GDA2020 (EPSG:7844), 25 S',
    'area model in a geographic CRS', 7844, 0.0001,
    square(147.0, -25.0, 0.01), flat, (1, 3, 1))
x, y = to_crs(3857, 147.0, -40.0)
add('T06', 'Flat, 1 km square in Web Mercator (EPSG:3857), 40 S',
    'area model in a strongly distorted projection (Mercator scale 1.31 at 40 S)',
    3857, 10.0, square(x, y, 1000.0), flat, (1, 3, 1))

# ---- Interpolation and 3D area (MGA55, central meridian, 25 S)
x, y = to_crs(7855, 147.0, -25.0)
add('T07', 'Single 10 m spike in one 10 m cell, 200 m square',
    'interpolation (bilinear vs nearest vs triangles), spacing 1 m',
    7855, 10.0, square(x, y, 200.0),
    lambda dx, dy: np.where((np.abs(dx) < 5) & (np.abs(dy) < 5), 10.0, 0.0),
    (0, 10, 1), centre_cell=True)
add('T08', 'Egg-crate surface (sin x . sin y), wavelength 40 m, 10 m DEM, 400 m square',
    'interpolation (bilinear vs triangles, which diagonal) and 3D area, spacing 2 m',
    7855, 10.0, square(x, y, 400.0),
    lambda dx, dy: 10.0 + 5.0 * np.sin(2 * math.pi * dx / 40.0) * np.sin(2 * math.pi * dy / 40.0),
    (5, 15, 1))
add('T09', 'Tilted plane, 10 % slope, 1 km square',
    '3D area scale (exact answer: plan area x sqrt(1.01))',
    7855, 10.0, square(x, y, 1000.0),
    lambda dx, dy: 200.0 + 0.1 * dx, (150, 250, 10))
add('T10', 'Egg-crate surface, wavelength 80 m, coarse 20 m DEM, 1 km square',
    'coarse-DEM integration (the Example 1 puzzle), spacing 5 m',
    7855, 20.0, square(x, y, 1000.0),
    lambda dx, dy: 10.0 + 5.0 * np.sin(2 * math.pi * dx / 80.0) * np.sin(2 * math.pi * dy / 80.0),
    (5, 15, 1))

# ---- Boundary handling and spacing rule
add('T11', 'Flat, circle radius 200 m (720 vertices)',
    'boundary: exact polygon area vs whole samples, spacing 2 m',
    7855, 10.0, circle(x, y, 200.0), flat, (1, 3, 1))
add('T12', 'Flat, thin strip 2000 m x 50 m',
    'spacing rule on a very elongated polygon (expect 0.25 m) and boundary',
    7855, 10.0, square(x, y, 2000.0, 50.0), flat, (1, 3, 1))

with open(os.path.join(HERE, 'tests.json'), 'w') as f:
    json.dump(TESTS, f, indent=2)
print('Wrote %d tests to %s' % (len(TESTS), HERE))
