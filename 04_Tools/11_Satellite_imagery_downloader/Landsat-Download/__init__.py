# -*- coding: utf-8 -*-
"""
Entry point of the "Landsat Download" plugin.
QGIS calls this function when the plugin is enabled.
© Grzegorz Górniak
"""


def classFactory(iface):
    from .plugin import LandsatDownload
    return LandsatDownload(iface)
