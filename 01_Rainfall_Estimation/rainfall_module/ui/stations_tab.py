"""Rainfall Stations tab — per catchment. Reads/writes catchment.stations_*."""
from __future__ import annotations

from ....qt_compat import (
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QObject,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QThread,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from ..core import bom_client
from ..core.station_index import load_stations

try:
    from qgis.core import (
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsVectorLayer,
    )
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


class _CsvWorker(QObject):
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, sid):
        super().__init__(); self.sid = sid

    def run(self):
        try:
            df, info = bom_client.build_daily_df(self.sid, distribute=True)
            self.finished.emit(df, info)
        except Exception as e:
            self.failed.emit(str(e))


class StationsTab(QWidget):
    COLS = ["Distance km", "Site ID", "Name", "State", "Start", "End", "% Complete"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catchment = None
        self._save_path = None
        self._thread = None
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Radius (km):"))
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(1.0, 1000.0)
        self.radius_spin.setDecimals(1)
        self.radius_spin.setValue(50.0)
        self.radius_spin.valueChanged.connect(self._on_radius_changed)
        controls.addWidget(self.radius_spin)

        self.find_button = QPushButton("Find nearby")
        self.find_button.setEnabled(False)
        self.find_button.clicked.connect(self._on_find)
        controls.addWidget(self.find_button)

        self.map_button = QPushButton("Add to map")
        self.map_button.setEnabled(False)
        self.map_button.clicked.connect(self._on_add_to_map)
        controls.addWidget(self.map_button)

        self.csv_button = QPushButton("Download CSV…")
        self.csv_button.setEnabled(False)
        self.csv_button.clicked.connect(self._on_download_csv)
        controls.addWidget(self.csv_button)
        controls.addStretch(1)
        root.addLayout(controls)

        self.status = QLabel("Choose a catchment location to enable search.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        root.addWidget(self.status)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_selection)
        root.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    def set_catchment(self, cat):
        self._catchment = cat
        if cat is None or not cat.has_location():
            self.find_button.setEnabled(False)
            self.map_button.setEnabled(False)
            self.csv_button.setEnabled(False)
            self._populate([])
            self.status.setText("Pick a location for this catchment.")
            return
        self.find_button.setEnabled(True)
        self.radius_spin.blockSignals(True)
        self.radius_spin.setValue(cat.stations_radius_km)
        self.radius_spin.blockSignals(False)
        self._populate(cat.stations_filtered)
        self.map_button.setEnabled(QGIS_AVAILABLE and bool(cat.stations_filtered))
        self.status.setText(
            f"{cat.name}: {len(cat.stations_filtered)} station(s) cached at radius "
            f"{cat.stations_radius_km:.1f} km."
            if cat.stations_filtered
            else f"{cat.name}: ready. Click 'Find nearby' to search."
        )

    def _on_radius_changed(self, v):
        if self._catchment is not None:
            self._catchment.stations_radius_km = float(v)

    # ------------------------------------------------------------------
    def _on_find(self):
        cat = self._catchment
        if cat is None or not cat.has_location():
            return
        try:
            stations = load_stations()
        except Exception as e:
            QMessageBox.warning(self, "Station index", str(e)); return

        import numpy as np
        lats = np.array([s["lat"] for s in stations], dtype=float)
        lons = np.array([s["lon"] for s in stations], dtype=float)
        dists = bom_client.haversine_km(cat.lat, cat.lon, lats, lons)

        radius = self.radius_spin.value()
        rows = []
        for i, s in enumerate(stations):
            d = float(dists[i])
            if d <= radius:
                r = dict(s); r["distance_km"] = round(d, 1)
                rows.append(r)
        rows.sort(key=lambda x: x["distance_km"])
        cat.stations_filtered = rows
        cat.stations_radius_km = radius
        self._populate(rows)
        self.map_button.setEnabled(QGIS_AVAILABLE and bool(rows))
        self.status.setText(f"{cat.name}: found {len(rows)} station(s) within {radius:.1f} km.")

    def _populate(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            vals = [
                s["distance_km"], s["id"], s["name"], s["state"],
                s.get("start_year") or "", s.get("end_year") or "",
                s.get("pct_complete") if s.get("pct_complete") is not None else "",
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem()
                if isinstance(v, (int, float)) and v != "":
                    item.setData(Qt.EditRole, v)
                else:
                    item.setText(str(v))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def _on_selection(self):
        self.csv_button.setEnabled(len(self.table.selectedItems()) > 0)

    def _selected_station_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.text() if item else None

    # ------------------------------------------------------------------
    def _on_download_csv(self):
        sid = self._selected_station_id()
        if not sid:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save station rainfall CSV",
            f"bom_rainfall_{sid}.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        self._save_path = path
        self.csv_button.setEnabled(False)
        self.status.setText(f"Downloading station {sid} from BoM…")
        self._thread = QThread(self)
        self._worker = _CsvWorker(sid)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_csv_ready)
        self._worker.failed.connect(self._on_csv_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_csv_ready(self, df, info):
        try:
            import pandas as pd
            df2 = df.copy()
            df2["Date"] = pd.to_datetime(df2["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df2.to_csv(self._save_path, index=False)
            self.status.setText(
                f"Saved {len(df2):,} rows → {self._save_path}  ({info.get('name','')})"
            )
        except Exception as e:
            QMessageBox.warning(self, "CSV write failed", str(e))
        finally:
            self.csv_button.setEnabled(True)

    def _on_csv_error(self, msg):
        self.csv_button.setEnabled(True)
        self.status.setText("Download failed.")
        QMessageBox.warning(self, "BoM download failed", msg)

    # ------------------------------------------------------------------
    def _on_add_to_map(self):
        cat = self._catchment
        if not QGIS_AVAILABLE or cat is None or not cat.stations_filtered:
            return
        layer = QgsVectorLayer(
            "Point?crs=EPSG:4326"
            "&field=id:string(6)&field=name:string(120)"
            "&field=state:string(4)&field=start:integer&field=end:integer"
            "&field=pct:double&field=dist_km:double",
            f"BoM Stations — {cat.name}",
            "memory",
        )
        prov = layer.dataProvider()
        feats = []
        for s in cat.stations_filtered:
            if s["lat"] is None or s["lon"] is None:
                continue
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(s["lon"], s["lat"])))
            f.setAttributes([
                s["id"], s["name"], s["state"],
                s.get("start_year"), s.get("end_year"),
                s.get("pct_complete"), s["distance_km"],
            ])
            feats.append(f)
        prov.addFeatures(feats)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.status.setText(f"Added {len(feats)} stations to the map.")
