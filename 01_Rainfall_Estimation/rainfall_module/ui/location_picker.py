"""Location picker for the currently selected catchment.

Writes lat/lon (WGS84) back to the catchment via ``location_changed``. Three
input paths: pick a polygon layer's centroid, click on the map canvas, or
type manual lat/lon.
"""
from __future__ import annotations

from ....qt_compat import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

try:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsMapLayerProxyModel,
        QgsPointXY,
        QgsProject,
    )
    from qgis.gui import QgsMapLayerComboBox, QgsMapToolEmitPoint
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


WGS84 = "EPSG:4326"


class LocationPicker(QGroupBox):
    """Emits (lat, lon, source_label) in WGS84 whenever the point changes."""

    location_changed = pyqtSignal(float, float, str)

    def __init__(self, iface=None, parent=None):
        super().__init__("Location", parent)
        self.iface = iface
        self._map_tool = None
        self._prev_tool = None
        self._suppress = False
        self._build()

    def _build(self):
        form = QFormLayout(self)

        if QGIS_AVAILABLE and self.iface is not None:
            self.layer_combo = QgsMapLayerComboBox()
            self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
            self.layer_combo.setAllowEmptyLayer(True)
            self.layer_combo.layerChanged.connect(self._on_layer_changed)
        else:
            self.layer_combo = QComboBox()
        form.addRow("Catchment layer:", self.layer_combo)

        latlon_row = QHBoxLayout()
        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(5)
        self.lat_spin.setSingleStep(0.001)
        self.lat_spin.valueChanged.connect(self._on_manual_changed)
        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(5)
        self.lon_spin.setSingleStep(0.001)
        self.lon_spin.valueChanged.connect(self._on_manual_changed)
        latlon_row.addWidget(QLabel("Lat"))
        latlon_row.addWidget(self.lat_spin)
        latlon_row.addWidget(QLabel("Lon"))
        latlon_row.addWidget(self.lon_spin)
        form.addRow("Manual:", self._wrap(latlon_row))

        self.pick_button = QPushButton("Pick on map")
        self.pick_button.setCheckable(True)
        self.pick_button.setEnabled(QGIS_AVAILABLE and self.iface is not None)
        self.pick_button.toggled.connect(self._toggle_pick_tool)
        form.addRow("", self.pick_button)

        self.status_label = QLabel("No location selected.")
        self.status_label.setStyleSheet("color: #555;")
        form.addRow("Current:", self.status_label)

    def _wrap(self, layout):
        w = QWidget(); w.setLayout(layout); return w

    # ------------------------------------------------------------------
    def load_from_catchment(self, cat):
        """Silently populate the spins from a catchment; suppresses signals."""
        self._suppress = True
        if cat.has_location():
            self.lat_spin.setValue(cat.lat)
            self.lon_spin.setValue(cat.lon)
            self.status_label.setText(
                f"{cat.lat:.5f}, {cat.lon:.5f}  ({cat.source or 'stored'})"
            )
        else:
            self.lat_spin.setValue(0.0)
            self.lon_spin.setValue(0.0)
            self.status_label.setText("No location — pick a layer, click the map, or type lat/lon.")
        self._suppress = False

    # ------------------------------------------------------------------
    def _on_manual_changed(self, *_):
        if self._suppress:
            return
        lat, lon = self.lat_spin.value(), self.lon_spin.value()
        self._emit(lat, lon, "manual entry")

    def _on_layer_changed(self, layer):
        if not QGIS_AVAILABLE or layer is None:
            return
        try:
            if layer.selectedFeatureCount() > 0:
                geom = next(layer.getSelectedFeatures()).geometry()
                pt = geom.centroid().asPoint()
            else:
                extent = layer.extent()
                pt = QgsPointXY(extent.center().x(), extent.center().y())
            src_crs = layer.crs()
            dst_crs = QgsCoordinateReferenceSystem(WGS84)
            if src_crs.authid() != WGS84:
                xf = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                pt = xf.transform(pt)
            self._set(pt.y(), pt.x(), f"centroid of '{layer.name()}'")
        except Exception as e:
            self.status_label.setText(f"Centroid failed: {e}")

    def _toggle_pick_tool(self, checked):
        if not QGIS_AVAILABLE or self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        if checked:
            self._prev_tool = canvas.mapTool()
            self._map_tool = QgsMapToolEmitPoint(canvas)
            self._map_tool.canvasClicked.connect(self._on_map_click)
            canvas.setMapTool(self._map_tool)
            self.status_label.setText("Click on the map to pick a location…")
        else:
            if self._prev_tool is not None:
                canvas.setMapTool(self._prev_tool)
            self._map_tool = None

    def _on_map_click(self, pt, _button):
        if not QGIS_AVAILABLE or self.iface is None:
            return
        canvas = self.iface.mapCanvas()
        src_crs = canvas.mapSettings().destinationCrs()
        dst_crs = QgsCoordinateReferenceSystem(WGS84)
        try:
            if src_crs.authid() != WGS84:
                xf = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                pt = xf.transform(pt)
            self._set(pt.y(), pt.x(), "map click")
        finally:
            self.pick_button.setChecked(False)

    def _set(self, lat, lon, source):
        self._suppress = True
        self.lat_spin.setValue(lat)
        self.lon_spin.setValue(lon)
        self._suppress = False
        self._emit(lat, lon, source)

    def _emit(self, lat, lon, source):
        self.status_label.setText(f"{lat:.5f}, {lon:.5f}  ({source})")
        self.location_changed.emit(lat, lon, source)
