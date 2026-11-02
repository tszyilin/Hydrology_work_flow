def classFactory(iface):
    from .raster_footprint import RasterFootprintPlugin
    return RasterFootprintPlugin(iface)
