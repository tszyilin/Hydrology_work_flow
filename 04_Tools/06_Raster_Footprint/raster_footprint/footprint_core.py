import os
import tempfile

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()


def _delete_shapefile(path):
    drv = ogr.GetDriverByName('ESRI Shapefile')
    if os.path.exists(path):
        drv.DeleteDataSource(path)


def _georeferenced_mask(ds, mask_band):
    """Copy the mask band into a scratch GeoTIFF carrying ``ds``'s geotransform.

    ``band.GetMaskBand()`` lives on a derived mask dataset that typically has
    no geotransform/projection, so passing it straight to ``gdal.Polygonize``
    yields pixel-space coordinates. We materialise it into a byte GeoTIFF
    (LZW-compressed, chunked) so Polygonize sees real-world coordinates.
    """
    tmp_path = tempfile.mktemp(suffix='_mask.tif')
    drv = gdal.GetDriverByName('GTiff')
    xs, ys = ds.RasterXSize, ds.RasterYSize
    tmp_ds = drv.Create(
        tmp_path, xs, ys, 1, gdal.GDT_Byte,
        options=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'],
    )
    tmp_ds.SetGeoTransform(ds.GetGeoTransform())
    proj = ds.GetProjection()
    if proj:
        tmp_ds.SetProjection(proj)
    tmp_band = tmp_ds.GetRasterBand(1)

    chunk = 1024
    for y in range(0, ys, chunk):
        h = min(chunk, ys - y)
        arr = mask_band.ReadAsArray(0, y, xs, h)
        tmp_band.WriteArray(arr, 0, y)
    tmp_band.FlushCache()
    return tmp_path, tmp_ds, tmp_band


def extract_footprint(in_raster, out_shp, dissolve=True, band_index=1,
                      progress_cb=None, srs_wkt=None, crs_authid=None):
    """Polygonize the valid-data area of a raster into a shapefile.

    Uses GDAL's per-band mask so any NoData value is honoured. When ``dissolve``
    is True, all valid-data polygons are merged into a single (multi)polygon
    feature. ``crs_authid`` (e.g. ``"EPSG:28350"``) or ``srs_wkt`` override the
    CRS written to the output. The authority ID is preferred when both are
    supplied because round-tripping WKT between QGIS and OSR can lose datum or
    hemisphere information for some projections.
    """
    ds = gdal.Open(in_raster, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f'Could not open raster: {in_raster}')

    band = ds.GetRasterBand(band_index)
    if band is None:
        raise RuntimeError(f'Raster has no band {band_index}')
    mask_band = band.GetMaskBand()

    srs = None
    if crs_authid and crs_authid.upper().startswith('EPSG:'):
        try:
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(int(crs_authid.split(':', 1)[1]))
        except Exception:
            srs = None
    if srs is None:
        proj_wkt = srs_wkt or ds.GetProjection()
        if proj_wkt:
            srs = osr.SpatialReference()
            srs.ImportFromWkt(proj_wkt)

    _delete_shapefile(out_shp)

    drv = ogr.GetDriverByName('ESRI Shapefile')
    tmp_shp = out_shp if not dissolve else out_shp.replace('.shp', '_raw.shp')
    _delete_shapefile(tmp_shp)

    out_ds = drv.CreateDataSource(tmp_shp)
    layer_name = os.path.splitext(os.path.basename(tmp_shp))[0]
    out_layer = out_ds.CreateLayer(layer_name, srs=srs, geom_type=ogr.wkbPolygon)
    out_layer.CreateField(ogr.FieldDefn('DN', ogr.OFTInteger))
    dn_idx = out_layer.GetLayerDefn().GetFieldIndex('DN')

    def _gdal_cb(complete, message, _user):
        if progress_cb is not None:
            try:
                return int(bool(progress_cb(float(complete), message or '')))
            except Exception:
                return 1
        return 1

    mask_path, mask_ds, mask_src = _georeferenced_mask(ds, mask_band)
    try:
        gdal.Polygonize(mask_src, mask_src, out_layer, dn_idx, [], callback=_gdal_cb)
    finally:
        mask_ds = None
        if os.path.exists(mask_path):
            try:
                os.remove(mask_path)
            except OSError:
                pass
    out_ds = None  # flush

    if not dissolve:
        return out_shp

    # Dissolve the raw polygons into one multi-polygon feature.
    src_ds = ogr.Open(tmp_shp)
    src_layer = src_ds.GetLayer(0)

    union_geom = None
    for feat in src_layer:
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
        srs=srs,
        geom_type=ogr.wkbMultiPolygon,
    )
    out_layer.CreateField(ogr.FieldDefn('source', ogr.OFTString))

    feat = ogr.Feature(out_layer.GetLayerDefn())
    feat.SetField('source', os.path.basename(in_raster))
    if union_geom is not None:
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
        feat.SetGeometry(union_geom)
    out_layer.CreateFeature(feat)
    feat = None
    out_ds = None

    # Clean up temporary raw shapefile set
    for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
        p = tmp_shp[:-4] + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    return out_shp
