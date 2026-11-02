"""PMP Toolbox -- a QGIS plugin for Probable Maximum Precipitation.

Three methods, three tabs:

``GSDM``
    Catchment-average PMP depth against duration, 0.25 to 6 hours, for
    catchments up to 1000 km2.

``Areal GSDM``
    GSDM section 6: the Figure 6 storm template positioned over the catchment
    by optimisation, giving the design spatial distribution of PMP.

``GTSMR / GSAM``
    The long-duration methods, 24 to 120 hours, driven by the Bureau's
    extreme-precipitable-water, topographic and decay grids.

The ``core`` package imports nothing from QGIS, so the whole calculation is
testable with plain Python.  Only ``plugin``, ``qgis_bridge``, ``styling`` and
the ``tabs`` package touch the QGIS API, and they are imported lazily below so
that ``import pmp_toolbox`` works outside QGIS.
"""

__version__ = "0.8.3"


def classFactory(iface):  # noqa: N802 -- name mandated by the QGIS plugin API
    from .plugin import PmpToolboxPlugin

    return PmpToolboxPlugin(iface)
