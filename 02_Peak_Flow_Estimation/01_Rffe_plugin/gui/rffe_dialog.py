"""The RFFE query dialog: pick points on the map, run, load results as layers."""

from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import QThread, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QLineEdit, QMessageBox, QPushButton, QTableWidget,
                                 QTableWidgetItem, QVBoxLayout, QDoubleSpinBox)

from ..core.rffe_client import AEPS, BASE as RFFE_URL, RffeError, query_site
from ..core.rffe_output import (FFA_LAYER_SUFFIX, build_layers,
                                catchments_in_geology, compute_rock_alluvial,
                                write_outputs)
from .pick_tool import PointPicker


class _QueryThread(QThread):
    """Runs the RFFE query off the GUI thread so QGIS stays responsive."""

    done = pyqtSignal(object)     # (site, models, region, polygon)
    failed = pyqtSignal(str)

    def __init__(self, lon, lat, area, clon, clat):
        super().__init__()
        self._args = (lon, lat, area, clon, clat)

    def run(self):
        try:
            self.done.emit(query_site(*self._args))
        except RffeError as e:
            self.failed.emit(str(e))
        except Exception as e:                        # noqa: BLE001 - surface anything
            self.failed.emit(f"Unexpected error: {e}")


class RffeDialog(QDialog):
    """Pick an outlet and centroid on the map, run RFFE, load the results."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.setWindowTitle("RFFE 2021 Query")
        self.setMinimumWidth(560)

        self._thread = None
        self._result = None
        self._prev_tool = None

        self._outlet_tool = PointPicker(self.canvas, "#d40000",
                                        QgsVertexMarker.ICON_CROSS)
        self._centroid_tool = PointPicker(self.canvas, "#0068d4",
                                          QgsVertexMarker.ICON_X)
        self._outlet_tool.picked.connect(self._on_outlet)
        self._centroid_tool.picked.connect(self._on_centroid)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        loc = QGroupBox("Catchment", self)
        form = QFormLayout(loc)

        self.name_edit = QLineEdit("Site_1", self)
        form.addRow("Name:", self.name_edit)

        self.outlet_lon = self._coord_box()
        self.outlet_lat = self._coord_box()
        self.pick_outlet_btn = QPushButton("Pick on map", self)
        self.pick_outlet_btn.setCheckable(True)
        self.pick_outlet_btn.toggled.connect(
            lambda on: self._activate(self._outlet_tool, self.pick_outlet_btn, on))
        form.addRow("Outlet:", self._coord_row(self.outlet_lon, self.outlet_lat,
                                               self.pick_outlet_btn))

        self.cent_lon = self._coord_box()
        self.cent_lat = self._coord_box()
        self.pick_cent_btn = QPushButton("Pick on map", self)
        self.pick_cent_btn.setCheckable(True)
        self.pick_cent_btn.toggled.connect(
            lambda on: self._activate(self._centroid_tool, self.pick_cent_btn, on))
        form.addRow("Centroid:", self._coord_row(self.cent_lon, self.cent_lat,
                                                 self.pick_cent_btn))

        self.auto_centroid = QCheckBox(
            "Derive centroid automatically (~0.07° upstream of outlet)", self)
        self.auto_centroid.setChecked(True)
        self.auto_centroid.toggled.connect(self._toggle_centroid)
        form.addRow("", self.auto_centroid)

        self.area_box = QDoubleSpinBox(self)
        self.area_box.setRange(0.1, 1_000_000.0)
        self.area_box.setDecimals(3)
        self.area_box.setValue(88.0)
        self.area_box.setSuffix(" km²")
        area_note = QLabel("Area drives the fitted catchment shape - use the real value.",
                           self)
        area_note.setStyleSheet("color: #666;")
        arow = QHBoxLayout()
        arow.addWidget(self.area_box)
        arow.addWidget(area_note, 1)
        form.addRow("Area:", arow)

        layout.addWidget(loc)

        out = QGroupBox("Output", self)
        oform = QFormLayout(out)
        self.out_edit = QLineEdit(self)
        self.out_edit.setPlaceholderText("Folder for CSV/JSON and GeoPackage layers")
        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._browse)
        orow = QHBoxLayout()
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(browse)
        oform.addRow("Output folder:", orow)

        self.add_layers = QCheckBox("Add catchment, points and stations to the map", self)
        self.add_layers.setChecked(True)
        oform.addRow("", self.add_layers)
        layout.addWidget(out)

        self.status = QLabel("Pick an outlet, set the area, then Run.", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["AEP", "Flow (m³/s)", "Lower 90%", "Upper 90%"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(190)
        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox(self)
        self.run_btn = self.buttons.addButton("Run RFFE", QDialogButtonBox.AcceptRole)
        self.open_btn = self.buttons.addButton("Open RFFE website",
                                               QDialogButtonBox.ActionRole)
        self.open_btn.setToolTip(
            "Open the RFFE site and copy this site's coordinates to the clipboard.\n"
            "The site cannot accept coordinates in the URL, so paste them in.")
        self.buttons.addButton(QDialogButtonBox.Close)
        self.run_btn.clicked.connect(self._run)
        self.open_btn.clicked.connect(self._open_website)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._toggle_centroid(True)

    def _coord_box(self):
        box = QDoubleSpinBox(self)
        box.setRange(-180.0, 180.0)
        box.setDecimals(6)
        return box

    def _coord_row(self, lon_box, lat_box, button):
        row = QHBoxLayout()
        row.addWidget(QLabel("Lon", self))
        row.addWidget(lon_box)
        row.addWidget(QLabel("Lat", self))
        row.addWidget(lat_box)
        row.addWidget(button)
        return row

    # ------------------------------------------------------------------
    # Map picking
    # ------------------------------------------------------------------
    def _activate(self, tool, button, on):
        """Toggle a picker, making the two picker buttons mutually exclusive."""
        if on:
            for other, obtn in ((self._outlet_tool, self.pick_outlet_btn),
                                (self._centroid_tool, self.pick_cent_btn)):
                if obtn is not button and obtn.isChecked():
                    obtn.blockSignals(True)
                    obtn.setChecked(False)
                    obtn.blockSignals(False)
            self._prev_tool = self.canvas.mapTool()
            self.canvas.setMapTool(tool)
            button.setText("Picking...")
            self.status.setText("Click on the map to place the point.")
        else:
            button.setText("Pick on map")
            if self.canvas.mapTool() is tool:
                self.canvas.unsetMapTool(tool)
                if self._prev_tool is not None:
                    self.canvas.setMapTool(self._prev_tool)

    def _on_outlet(self, lon, lat):
        self.outlet_lon.setValue(lon)
        self.outlet_lat.setValue(lat)
        self.pick_outlet_btn.setChecked(False)
        self.status.setText(f"Outlet set to {lat:.5f}, {lon:.5f}")

    def _on_centroid(self, lon, lat):
        self.auto_centroid.setChecked(False)
        self.cent_lon.setValue(lon)
        self.cent_lat.setValue(lat)
        self.pick_cent_btn.setChecked(False)
        self.status.setText(f"Centroid set to {lat:.5f}, {lon:.5f}")

    def _toggle_centroid(self, auto):
        for w in (self.cent_lon, self.cent_lat, self.pick_cent_btn):
            w.setEnabled(not auto)
        if auto:
            self._centroid_tool.clear()

    def _open_website(self):
        """Open the RFFE site in a browser, with this site's inputs on the clipboard.

        The app has no dcc.Location and no callback reads the query string, so
        coordinates cannot be passed in the URL -- it always loads at its default
        Sydney catchment. Copying the values is the next best thing.
        """
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices
        from qgis.PyQt.QtWidgets import QApplication

        lon, lat = self.outlet_lon.value(), self.outlet_lat.value()
        if lon or lat:
            if self.auto_centroid.isChecked():
                clon, clat = lon, lat - 0.07
            else:
                clon, clat = self.cent_lon.value(), self.cent_lat.value()
            text = (f"Outlet lon {lon:.6f}\tlat {lat:.6f}\n"
                    f"Centroid lon {clon:.6f}\tlat {clat:.6f}\n"
                    f"Area {self.area_box.value():g} km2")
            QApplication.clipboard().setText(text)
            self.status.setText(
                "Opened the RFFE website. Coordinates copied to the clipboard - "
                "the site cannot take them in the URL, so paste them into its "
                "Outlet/Centroid boxes.")
        QDesktopServices.openUrl(QUrl(RFFE_URL))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder",
                                             self.out_edit.text() or "")
        if d:
            self.out_edit.setText(d)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def _run(self):
        if not (self.outlet_lon.value() and self.outlet_lat.value()):
            QMessageBox.warning(self, "RFFE", "Set an outlet first (pick it on the map).")
            return
        out_dir = self.out_edit.text().strip()
        if out_dir and not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "RFFE", f"Cannot create output folder:\n{e}")
                return

        clon = clat = None
        if not self.auto_centroid.isChecked():
            clon, clat = self.cent_lon.value(), self.cent_lat.value()

        self.run_btn.setEnabled(False)
        self.status.setText("Querying RFFE 2021 (this takes a few seconds)...")
        self.table.setRowCount(0)

        self._thread = _QueryThread(self.outlet_lon.value(), self.outlet_lat.value(),
                                    self.area_box.value(), clon, clat)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(lambda: self.run_btn.setEnabled(True))
        self._thread.start()

    def _on_failed(self, message):
        self.status.setText("Failed.")
        QMessageBox.critical(self, "RFFE", message)

    def _on_done(self, result):
        site, models, region, polygon = result
        self._result = result
        name = self.name_edit.text().strip() or "Site"

        rec = models.get("Recommended Model")
        rec_model = models.get(rec, {})
        self.table.setRowCount(len(AEPS))
        for i, aep in enumerate(AEPS):
            vals = [aep, rec_model.get("Flow", [])[i],
                    rec_model.get("05pct", [])[i], rec_model.get("95pct", [])[i]]
            for c, v in enumerate(vals):
                text = v if isinstance(v, str) else f"{v:,.1f}"
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, item)

        n_stn = sum(len(t.get("index", [])) for t in region.values()
                    if isinstance(t, dict))
        msg = (f"{site.get('Basin', '?')} | {site.get('Region Name', '?')} | "
               f"model: {rec} | {n_stn} gauged stations")

        out_dir = self.out_edit.text().strip()
        if out_dir:
            try:
                written = write_outputs(out_dir, name, site, models, region, polygon)
                msg += f"\nWrote {len(written)} file(s) to {out_dir}"
            except OSError as e:
                msg += f"\nCould not write outputs: {e}"

        if self.add_layers.isChecked():
            try:
                built = build_layers(site, models, region, polygon, name,
                                     out_dir or None)
                for lyr in built:
                    QgsProject.instance().addMapLayer(lyr)
                msg += "\nLayers added to the project."
                self._maybe_offer_rock_alluvial(built, msg)
                return
            except Exception as e:                    # noqa: BLE001
                msg += f"\nCould not build layers: {e}"

        self.status.setText(msg)

    def _maybe_offer_rock_alluvial(self, layers, msg):
        """If any FFA catchment falls within the NT geology extent, offer to
        compute rock/alluvial proportion for each. Updates status either way."""
        ffa = next((l for l in layers if l.name().endswith(FFA_LAYER_SUFFIX)), None)
        if ffa is None or not catchments_in_geology(ffa):
            self.status.setText(msg)
            return
        answer = QMessageBox.question(
            self, "Rock / alluvial proportion",
            "One or more FFA station catchments fall within the NT geology "
            "coverage. Calculate the rock and alluvial (unconsolidated) "
            "proportion for each catchment?\n\n"
            "This can take a minute for large catchments.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            self.status.setText(msg)
            return
        Qt_cursor = Qt.WaitCursor
        self.setCursor(Qt_cursor)
        try:
            n = compute_rock_alluvial(ffa)
            msg += f"\nRock/alluvial computed for {n} catchment(s)."
        except Exception as e:                        # noqa: BLE001
            msg += f"\nCould not compute rock/alluvial: {e}"
        finally:
            self.unsetCursor()
        self.status.setText(msg)

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 (Qt API name)
        for tool, btn in ((self._outlet_tool, self.pick_outlet_btn),
                          (self._centroid_tool, self.pick_cent_btn)):
            if btn.isChecked():
                btn.setChecked(False)
            tool.clear()
        super().closeEvent(event)
