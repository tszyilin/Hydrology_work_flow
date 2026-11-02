"""Bathtub-flood a DEM to a given water level and polygonise the result.

Mirrors the GDAL+OGR approach used by ``raster_footprint/footprint_core.py``:
pure GDAL/OGR, no dependency on QGIS Processing. The dialog is responsible
for reprojecting any user-supplied extent into the DEM's CRS before calling
``compute_flood_polygon`` — the core does not reproject.
"""
from __future__ import annotations

import math
import os
import tempfile

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def _delete_shapefile(path):
    drv = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(path):
        drv.DeleteDataSource(path)


def _resolve_srs(ds, srs_wkt, crs_authid):
    """Prefer EPSG authority id > caller WKT > DEM projection WKT."""
    if crs_authid and crs_authid.upper().startswith('EPSG:'):
        try:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(int(crs_authid.split(':', 1)[1]))
            return srs
        except Exception:
            pass
    proj_wkt = srs_wkt or ds.GetProjection()
    if proj_wkt:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(proj_wkt)
        return srs
    return None


def _window_from_extent(gt, raster_xs, raster_ys, extent):
    """Convert a world-coord bbox to a pixel window (xoff, yoff, xs, ys).

    Assumes a north-up geotransform (``gt[2] == gt[4] == 0``), which is true
    for every DEM we expect to see from QGIS.
    """
    xmin, ymin, xmax, ymax = extent
    origin_x, px_w, _, origin_y, _, px_h = gt  # px_h is negative for north-up
    col_a = (xmin - origin_x) / px_w
    col_b = (xmax - origin_x) / px_w
    row_a = (ymax - origin_y) / px_h  # ymax -> smaller row index
    row_b = (ymin - origin_y) / px_h
    col_lo, col_hi = sorted((col_a, col_b))
    row_lo, row_hi = sorted((row_a, row_b))
    xoff = max(0, int(math.floor(col_lo)))
    yoff = max(0, int(math.floor(row_lo)))
    xend = min(raster_xs, int(math.ceil(col_hi)))
    yend = min(raster_ys, int(math.ceil(row_hi)))
    xs = max(0, xend - xoff)
    ys = max(0, yend - yoff)
    return xoff, yoff, xs, ys


def _window_geotransform(gt, xoff, yoff):
    return (
        gt[0] + xoff * gt[1] + yoff * gt[2],
        gt[1], gt[2],
        gt[3] + xoff * gt[4] + yoff * gt[5],
        gt[4], gt[5],
    )


def _build_flood_mask(dem_band, nodata, water_level, xoff, yoff, xs, ys,
                      gt_window, projection, progress_cb=None):
    """Materialise the (dem <= water_level) byte mask as a georeferenced GTiff.

    Chunk-read so we don't blow memory on large DEMs — same 1024-row chunking
    pattern used by ``footprint_core._georeferenced_mask``.
    """
    tmp_path = tempfile.mktemp(suffix='_flood.tif')
    drv = gdal.GetDriverByName('GTiff')
    tmp_ds = drv.Create(
        tmp_path, xs, ys, 1, gdal.GDT_Byte,
        options=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
    )
    tmp_ds.SetGeoTransform(gt_window)
    if projection:
        tmp_ds.SetProjection(projection)
    out_band = tmp_ds.GetRasterBand(1)
    out_band.SetNoDataValue(0)

    any_flooded = False
    chunk = 1024
    rows_done = 0
    for y in range(0, ys, chunk):
        h = min(chunk, ys - y)
        arr = dem_band.ReadAsArray(xoff, yoff + y, xs, h).astype(np.float64)
        flooded = arr <= water_level
        if nodata is not None:
            flooded &= arr != nodata
        # Also drop NaNs that some DEMs use instead of a nodata value.
        flooded &= ~np.isnan(arr)
        out_band.WriteArray(flooded.astype(np.uint8), 0, y)
        if flooded.any():
            any_flooded = True
        rows_done += h
        if progress_cb is not None:
            # Reserve 0.0 -> 0.6 of the progress bar for mask-building,
            # Polygonize gets 0.6 -> 1.0.
            progress_cb(0.6 * rows_done / ys, 'Building flood mask')
    out_band.FlushCache()
    return tmp_path, tmp_ds, out_band, any_flooded


def compute_flood_polygon(
    in_dem, out_shp, water_level,
    extent=None,
    band_index=1,
    progress_cb=None,
    srs_wkt=None,
    crs_authid=None,
):
    """Bathtub-flood ``in_dem`` and write the flooded area as a polygon shp.

    Parameters
    ----------
    in_dem : str
        Path to the DEM raster.
    out_shp : str
        Destination shapefile path (``.shp``).
    water_level : float
        Elevation threshold in the DEM's vertical units. Cells with
        ``elevation <= water_level`` are flooded.
    extent : tuple(xmin, ymin, xmax, ymax) or None
        Bounding box in the DEM's CRS. When supplied, the computation is
        restricted to the overlapping pixel window.
    band_index : int
        1-based band to read from the DEM.
    progress_cb : callable(frac: float, msg: str) or None
        Called with ``frac`` in ``[0, 1]`` as work proceeds.
    srs_wkt, crs_authid : str or None
        CRS to tag the output shapefile with. Preference order:
        ``crs_authid`` (EPSG) -> ``srs_wkt`` -> DEM projection.

    Returns
    -------
    (out_shp, feature_count) : (str, int)
        ``feature_count`` is 0 when no cells meet the threshold inside the
        extent — the caller should warn the user in that case.
    """
    ds = gdal.Open(in_dem, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f'Could not open raster: {in_dem}')

    band = ds.GetRasterBand(band_index)
    if band is None:
        raise RuntimeError(f'Raster has no band {band_index}')
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    projection = ds.GetProjection()

    if extent is None:
        xoff, yoff, xs, ys = 0, 0, ds.RasterXSize, ds.RasterYSize
    else:
        xoff, yoff, xs, ys = _window_from_extent(
            gt, ds.RasterXSize, ds.RasterYSize, extent,
        )
        if xs == 0 or ys == 0:
            raise RuntimeError(
                'The chosen extent does not overlap the DEM. Pick an extent '
                'that intersects the DEM, or tick "Use full DEM extent".'
            )
    gt_window = _window_geotransform(gt, xoff, yoff)

    mask_path, mask_ds, mask_band, any_flooded = _build_flood_mask(
        band, nodata, water_level, xoff, yoff, xs, ys,
        gt_window, projection, progress_cb=progress_cb,
    )

    srs = _resolve_srs(ds, srs_wkt, crs_authid)

    _delete_shapefile(out_shp)
    tmp_shp = out_shp.replace('.shp', '_raw.shp')
    _delete_shapefile(tmp_shp)

    drv = ogr.GetDriverByName('ESRI Shapefile')
    try:
        if not any_flooded:
            # Produce an empty but valid shapefile so the caller can still
            # load it (or just report "no flooded cells" and move on).
            out_ds = drv.CreateDataSource(out_shp)
            out_ds.CreateLayer(
                os.path.splitext(os.path.basename(out_shp))[0],
                srs=srs, geom_type=ogr.wkbMultiPolygon,
            )
            out_ds = None
            return out_shp, 0

        raw_ds = drv.CreateDataSource(tmp_shp)
        raw_layer = raw_ds.CreateLayer(
            os.path.splitext(os.path.basename(tmp_shp))[0],
            srs=srs, geom_type=ogr.wkbPolygon,
        )
        raw_layer.CreateField(ogr.FieldDefn('DN', ogr.OFTInteger))
        dn_idx = raw_layer.GetLayerDefn().GetFieldIndex('DN')

        def _gdal_cb(complete, message, _user):
            if progress_cb is not None:
                try:
                    progress_cb(0.6 + 0.4 * float(complete),
                                message or 'Polygonising')
                except Exception:
                    return 1
            return 1

        # Pass the mask band as its own validity mask so only DN=1 pixels
        # produce polygons (DN=0 becomes nodata).
        gdal.Polygonize(mask_band, mask_band, raw_layer, dn_idx,
                        [], callback=_gdal_cb)
        raw_ds = None  # flush
    finally:
        mask_ds = None
        if os.path.exists(mask_path):
            try:
                os.remove(mask_path)
            except OSError:
                pass

    # Dissolve DN=1 polygons into a single MultiPolygon.
    src_ds = ogr.Open(tmp_shp)
    src_layer = src_ds.GetLayer(0)
    union_geom = None
    for feat in src_layer:
        if feat.GetField('DN') != 1:
            continue
        g = feat.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        g = g.Clone()
        if not g.IsValid():
            g = g.MakeValid() if hasattr(g, 'MakeValid') else g.Buffer(0)
        union_geom = g if union_geom is None else union_geom.Union(g)
    src_ds = None

    _delete_shapefile(out_shp)
    out_ds = drv.CreateDataSource(out_shp)
    out_layer = out_ds.CreateLayer(
        os.path.splitext(os.path.basename(out_shp))[0],
        srs=srs, geom_type=ogr.wkbMultiPolygon,
    )
    out_layer.CreateField(ogr.FieldDefn('level', ogr.OFTReal))
    out_layer.CreateField(ogr.FieldDefn('source', ogr.OFTString))

    feature_count = 0
    if union_geom is not None and not union_geom.IsEmpty():
        if union_geom.GetGeometryType() != ogr.wkbMultiPolygon:
            multi = ogr.Geometry(ogr.wkbMultiPolygon)
            if union_geom.GetGeometryType() == ogr.wkbPolygon:
                multi.AddGeometry(union_geom)
            else:
                for i in range(union_geom.GetGeometryCount()):
                    part = union_geom.GetGeometryRef(i)
                    if part.GetGeometryType() == ogr.wkbPolygon:
                        multi.AddGeometry(part)
            union_geom = multi
        feat = ogr.Feature(out_layer.GetLayerDefn())
        feat.SetField('level', float(water_level))
        feat.SetField('source', os.path.basename(in_dem))
        feat.SetGeometry(union_geom)
        out_layer.CreateFeature(feat)
        feat = None
        feature_count = 1
    out_ds = None

    for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
        p = tmp_shp[:-4] + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    if progress_cb is not None:
        progress_cb(1.0, 'Done')
    return out_shp, feature_count
