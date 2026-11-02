"""RFFE Query - a QGIS plugin for the RFFE 2021 regional flood frequency model.

QGIS calls ``classFactory`` to instantiate the plugin once the user enables it.
"""


def classFactory(iface):  # noqa: N802 (name fixed by the QGIS plugin API)
    """Load and return the RFFE plugin instance.

    :param iface: the running QgisInterface instance.
    """
    from .rffe_plugin import RffePlugin

    return RffePlugin(iface)
