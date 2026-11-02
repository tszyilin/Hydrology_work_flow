def classFactory(iface):
    from .wind_fetch import WindFetchPlugin
    return WindFetchPlugin(iface)
