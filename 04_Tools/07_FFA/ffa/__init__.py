def classFactory(iface):
    from .ffa import FfaPlugin
    return FfaPlugin(iface)
