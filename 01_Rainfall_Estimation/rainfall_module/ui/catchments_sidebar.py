"""Sidebar listing catchments (add / rename / delete / import from layer).

Emits ``catchment_changed(Catchment)`` whenever the selection changes.
"Import from layer" turns each polygon feature into one Catchment whose
location is the polygon's centroid in WGS84.
"""
from __future__ import annotations

from ....qt_compat import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    Qt,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from ..catchment import Catchment

try:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsMapLayerProxyModel,
        QgsProject,
    )
    from qgis.gui import QgsMapLayerComboBox
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


WGS84 = "EPSG:4326"


class CatchmentsSidebar(QGroupBox):
    catchment_changed = pyqtSignal(object)   # emits Catchment
    batch_export_requested = pyqtSignal()

    def __init__(self, iface=None, parent=None):
        super().__init__("Catchments", parent)
        self.iface = iface
        self._catchments: list[Catchment] = []
        self._next_number = 1
        self._loading = False
        self._build()
        self.add_catchment()  # start with one

    # ------------------------------------------------------------------
    def _build(self):
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_widget.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        self.list_widget.itemChanged.connect(self._on_item_renamed)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list_widget, 1)

        row1 = QHBoxLayout()
        self.add_btn = QPushButton("+")
        self.add_btn.setToolTip("Add a new catchment")
        self.rename_btn = QPushButton("Rename")
        self.del_btn = QPushButton("−")
        self.del_btn.setToolTip("Delete the selected catchment")
        row1.addWidget(self.add_btn)
        row1.addWidget(self.rename_btn)
        row1.addWidget(self.del_btn)
        layout.addLayout(row1)

        self.add_btn.clicked.connect(self.add_catchment)
        self.rename_btn.clicked.connect(self._rename_current)
        self.del_btn.clicked.connect(self._delete_current)

        # Import from a polygon layer: one catchment per feature.
        row2 = QHBoxLayout()
        if QGIS_AVAILABLE and self.iface is not None:
            self.layer_combo = QgsMapLayerComboBox()
            self.layer_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
            self.layer_combo.setAllowEmptyLayer(True)
            row2.addWidget(self.layer_combo, 1)
            self.import_btn = QPushButton("Import layer")
            self.import_btn.setToolTip("Add one catchment per feature (centroid)")
            self.import_btn.clicked.connect(self._import_from_layer)
            row2.addWidget(self.import_btn)
            layout.addLayout(row2)
        else:
            layout.addWidget(QLabel("(Import from polygon layer requires QGIS.)"))

        self.batch_btn = QPushButton("Batch export IFD CSVs…")
        self.batch_btn.setToolTip(
            "For every catchment with a location and a fetched IFD, write one "
            "depths_{lat}_{lon}_all_design.csv into a chosen folder."
        )
        self.batch_btn.clicked.connect(lambda: self.batch_export_requested.emit())
        layout.addWidget(self.batch_btn)

    # ------------------------------------------------------------------
    def catchments(self) -> list[Catchment]:
        return list(self._catchments)

    def current(self) -> Catchment | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._catchments):
            return self._catchments[row]
        return None

    def refresh_current_label(self):
        """Repaint the current row's label — used when its location changes."""
        row = self.list_widget.currentRow()
        if row < 0:
            return
        cat = self._catchments[row]
        self._loading = True
        self.list_widget.item(row).setText(self._label_for(cat))
        self._loading = False

    def _label_for(self, cat: Catchment) -> str:
        if cat.has_location():
            return f"{cat.name}  ({cat.lat:.3f}, {cat.lon:.3f})"
        return cat.name

    # ------------------------------------------------------------------
    def add_catchment(self, name: str | None = None, lat=None, lon=None, source=""):
        if not name:
            name = f"Catchment {self._next_number}"
            self._next_number += 1
        cat = Catchment(name=name, lat=lat, lon=lon, source=source)
        self._catchments.append(cat)
        item = QListWidgetItem(self._label_for(cat))
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        # Store name-only in the item so double-click editing shows just the name.
        item.setData(Qt.UserRole, cat.name)
        self.list_widget.addItem(item)
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def _rename_current(self):
        cat = self.current()
        if cat is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename catchment", "New name:", text=cat.name)
        if not ok or not new_name.strip():
            return
        cat.name = new_name.strip()
        self.refresh_current_label()

    def _delete_current(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        if len(self._catchments) == 1:
            QMessageBox.information(self, "Delete catchment",
                                    "At least one catchment must exist.")
            return
        cat = self._catchments[row]
        if QMessageBox.question(self, "Delete catchment",
                                f"Delete '{cat.name}'?") != QMessageBox.Yes:
            return
        del self._catchments[row]
        self._loading = True
        self.list_widget.takeItem(row)
        self._loading = False
        self.list_widget.setCurrentRow(min(row, len(self._catchments) - 1))

    def _on_row_changed(self, row):
        if self._loading or row < 0 or row >= len(self._catchments):
            return
        self.catchment_changed.emit(self._catchments[row])

    def _on_item_renamed(self, item: QListWidgetItem):
        if self._loading:
            return
        row = self.list_widget.row(item)
        if row < 0 or row >= len(self._catchments):
            return
        # User edited the visible text — the label includes the coords, so
        # strip them and treat the leading part as the new name.
        text = item.text()
        if "  (" in text:
            text = text.split("  (", 1)[0]
        self._catchments[row].name = text.strip() or self._catchments[row].name
        self.refresh_current_label()

    def _on_rows_moved(self, _p, start, end, _dest, dest_row):
        # Keep our list in sync with the drag-drop reorder.
        moved = self._catchments.pop(start)
        insert_at = dest_row if dest_row < start else dest_row - 1
        self._catchments.insert(insert_at, moved)

    # ------------------------------------------------------------------
    def _import_from_layer(self):
        if not QGIS_AVAILABLE:
            return
        layer = self.layer_combo.currentLayer()
        if layer is None:
            QMessageBox.information(self, "Import layer", "Choose a polygon layer first.")
            return

        src_crs = layer.crs()
        dst_crs = QgsCoordinateReferenceSystem(WGS84)
        xf = None
        if src_crs.authid() != WGS84:
            xf = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

        # Name field: prefer 'name'/'NAME'/'id'/'ID'; else "<layer> #<fid>".
        fields = [f.name() for f in layer.fields()]
        name_field = None
        for candidate in ["name", "NAME", "Name", "id", "ID", "Id"]:
            if candidate in fields:
                name_field = candidate
                break

        n = 0
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            pt = geom.centroid().asPoint()
            if xf is not None:
                pt = xf.transform(pt)
            label = (str(feat[name_field]) if name_field else f"{layer.name()} #{feat.id()}").strip()
            self.add_catchment(name=label, lat=pt.y(), lon=pt.x(),
                               source=f"centroid of '{layer.name()}'")
            n += 1
        QMessageBox.information(self, "Import layer", f"Added {n} catchment(s).")
