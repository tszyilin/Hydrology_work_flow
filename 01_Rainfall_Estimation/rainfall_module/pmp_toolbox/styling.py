"""Renderers for the output layers."""

from __future__ import annotations

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsRendererCategory,
    QgsSimpleLineSymbolLayer,
    QgsSymbol,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsPalLayerSettings,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from .palette import OUTLINE, RAMP  # noqa: F401 -- re-exported for callers


def style_rainfall(layer: QgsVectorLayer, labels: list[str]) -> None:
    """Categorise the clipped rings by ellipse, innermost wettest."""
    categories = []
    for i, label in enumerate(labels):
        symbol = QgsFillSymbol.createSimple(
            {
                "color": RAMP[min(i, len(RAMP) - 1)],
                "outline_color": "#33000000",
                "outline_width": "0.2",
            }
        )
        categories.append(QgsRendererCategory(label, symbol, f"Ellipse {label}"))
    layer.setRenderer(QgsCategorizedSymbolRenderer("Ellipse", categories))
    _label_by(layer, "MRD")
    layer.triggerRepaint()


def style_outlines(layer: QgsVectorLayer) -> None:
    """Hollow outlines so the template reads over any basemap."""
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.deleteSymbolLayer(0)
    line = QgsSimpleLineSymbolLayer(QColor(OUTLINE), 0.4)
    line.setPenStyle(Qt.PenStyle.DashLine)
    symbol.appendSymbolLayer(line)
    layer.renderer().setSymbol(symbol)
    _label_by(layer, "Ellipse")
    layer.triggerRepaint()


def _label_by(layer: QgsVectorLayer, field: str) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = (
        f'"{field}"' if field == "Ellipse" else f"round(\"{field}\", 0) || ' mm'"
    )
    settings.isExpression = field != "Ellipse"
    text = QgsTextFormat()
    # Leave the font family to Qt's default. "Sans" is an fontconfig alias that
    # does not resolve on Windows, where it renders as boxes.
    text.setSize(9)
    buffer = text.buffer()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    buffer.setColor(QColor("white"))
    text.setBuffer(buffer)
    settings.setFormat(text)
    settings.placement = QgsPalLayerSettings.Placement.Horizontal
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
