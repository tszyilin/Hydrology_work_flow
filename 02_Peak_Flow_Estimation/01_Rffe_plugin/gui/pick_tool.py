"""Map tool for picking the outlet / centroid off the canvas."""

from __future__ import annotations

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsPointXY, QgsProject)
from qgis.gui import QgsMapToolEmitPoint, QgsVertexMarker
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


class PointPicker(QgsMapToolEmitPoint):
    """Emits ``picked(lon, lat)`` in WGS84 and leaves a marker on the canvas.

    The canvas may be in any CRS, so the clicked point is transformed to
    EPSG:4326 -- which is what the RFFE service expects.
    """

    picked = pyqtSignal(float, float)

    def __init__(self, canvas, colour: str = "#e00000", shape=None):
        super().__init__(canvas)
        self.canvas = canvas
        self._marker = QgsVertexMarker(canvas)
        self._marker.setColor(QColor(colour))
        self._marker.setPenWidth(3)
        self._marker.setIconSize(14)
        self._marker.setIconType(shape or QgsVertexMarker.ICON_CROSS)
        self._marker.hide()

    def canvasReleaseEvent(self, event):  # noqa: N802 (QGIS API name)
        pt = self.toMapCoordinates(event.pos())
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs != WGS84:
            tr = QgsCoordinateTransform(canvas_crs, WGS84, QgsProject.instance())
            pt = tr.transform(pt)
        self.show_at(pt.x(), pt.y())
        self.picked.emit(pt.x(), pt.y())

    def show_at(self, lon: float, lat: float) -> None:
        """Place the marker at a WGS84 position, transforming to canvas CRS."""
        pt = QgsPointXY(lon, lat)
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        if canvas_crs != WGS84:
            tr = QgsCoordinateTransform(WGS84, canvas_crs, QgsProject.instance())
            pt = tr.transform(pt)
        self._marker.setCenter(pt)
        self._marker.show()

    def clear(self) -> None:
        self._marker.hide()

    def deactivate(self):  # noqa: N802 (QGIS API name)
        super().deactivate()
