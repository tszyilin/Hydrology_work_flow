# -*- coding: utf-8 -*-
"""
LANDSAT BULK DOWNLOADER — standalone GUI (runs outside QGIS).

Same data and products as the "Landsat Download" QGIS plugin
(engine.py in ./Landsat-Download), but:
  - many parallel band downloads (up to 32) instead of 4 scenes
  - search split per year (2001 / 2002 / 2003 ...) with one
    sub-folder per year
  - no scene limit, no QGIS layers loaded -> nothing to crash QGIS
  - Stop button, live speed / ETA, resumable (re-run = continue)

Run:  Run_Landsat_Downloader.bat   (or: python landsat_gui.py)
      python landsat_gui.py --aoi area.geojson --out D:/imagery
      (the QGIS suite's Tools tab starts it this way, with the
      selected catchment as the area of interest)
"""

import os
import sys
import json
import argparse
import time
import threading

import fast_engine
from fast_engine import engine

from osgeo import ogr, osr
from PySide6.QtCore import Qt, QDate, QTimer, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QSpinBox, QDateEdit, QCheckBox,
    QRadioButton, QGroupBox, QFileDialog, QMessageBox, QPlainTextEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QSplitter, QHeaderView, QDoubleSpinBox)

COLOR = "#00bde7"
COLOR_HOVER = "#009ec2"


# =============================================================================
#  AREA OF INTEREST (OGR, no QGIS)
# =============================================================================

def list_layers(path):
    source = ogr.Open(path)
    if source is None:
        raise RuntimeError(f"Could not open the file: {path}")
    return [source.GetLayer(i).GetName()
            for i in range(source.GetLayerCount())]


def geojson_from_file(path, layer_name=None):
    """Union of all features -> WGS84 -> convex hull if multi-part ->
    simplified GeoJSON geometry (same recipe as the plugin)."""
    source = ogr.Open(path)
    if source is None:
        raise RuntimeError(f"Could not open the file: {path}")
    layer = source.GetLayerByName(layer_name) if layer_name \
        else source.GetLayer(0)
    if layer is None:
        raise RuntimeError(f"Layer not found: {layer_name}")

    union = None
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        geometry = geometry.Clone()
        union = geometry if union is None else union.Union(geometry)
    if union is None:
        raise RuntimeError("The layer has no features with geometry.")

    source_srs = layer.GetSpatialRef()
    if source_srs is not None:
        wgs84 = osr.SpatialReference()
        wgs84.ImportFromEPSG(4326)
        wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        union.Transform(osr.CoordinateTransformation(source_srs, wgs84))

    union.FlattenTo2D()
    if union.GetGeometryCount() > 1 and \
            union.GetGeometryType() != ogr.wkbPolygon:
        union = union.ConvexHull()
    union = union.SimplifyPreserveTopology(0.001)
    return json.loads(union.ExportToJson())


def geojson_from_bbox(west, south, east, north):
    return {"type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north],
                             [west, north], [west, south]]]}


# =============================================================================
#  MAIN WINDOW
# =============================================================================

class MainWindow(QWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Landsat / Sentinel-2 Bulk Downloader")
        self.resize(1250, 900)
        self.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; }} "
            f"QGroupBox::title {{ color: {COLOR}; }} "
            f"QProgressBar::chunk {{ background-color: {COLOR}; }}")
        self.settings = QSettings("LandsatBulk", "Downloader")
        self.results = []          # [(label, [items])]
        self.rows = []             # [(label, item)] in table order
        self.rows_source = None    # the source those rows came from
        self.source_key = None
        self.downloader = None
        self.worker = None
        self.search_thread = None
        self.search_stop = threading.Event()
        self.search_events = []
        self.scene_status = {}     # scene id -> (text, key) — survives
        #                            new searches while the queue runs
        self.band_speed = {}       # (scene, band) -> (time, bytes, B/s)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([480, 770])
        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.load_settings()

    # ---- layout ------------------------------------------------------------
    def _build_left(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # 0. source (+ login for sources that need one)
        group = QGroupBox("0. Data source")
        grid = QGridLayout(group)
        self.source_combo = QComboBox()
        for key, source in fast_engine.SOURCES.items():
            self.source_combo.addItem(source["label"], key)
        grid.addWidget(self.source_combo, 0, 0, 1, 2)
        self.login_box = QWidget()
        login = QGridLayout(self.login_box)
        login.setContentsMargins(0, 0, 0, 0)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("e-mail")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("password (not saved)")
        login.addWidget(QLabel("Copernicus login:"), 0, 0)
        login.addWidget(self.user_edit, 0, 1)
        login.addWidget(self.password_edit, 0, 2)
        signup = QLabel('<a href="https://dataspace.copernicus.eu">'
                        'Free account: dataspace.copernicus.eu</a>')
        signup.setOpenExternalLinks(True)
        signup.setStyleSheet("font-weight: normal;")
        login.addWidget(signup, 1, 1, 1, 2)
        grid.addWidget(self.login_box, 1, 0, 1, 2)
        layout.addWidget(group)

        # 1. missions (rebuilt for every source)
        group = QGroupBox("1. Missions")
        self.platform_grid = QGridLayout(group)
        self.platform_checks = {}
        self.source_hint = QLabel("")
        self.source_hint.setWordWrap(True)
        self.source_hint.setStyleSheet("color: gray; font-weight: normal;")
        self.platform_grid.addWidget(self.source_hint, 1, 0, 1, 5)
        layout.addWidget(group)

        # 2. area
        group = QGroupBox("2. Area of interest")
        grid = QGridLayout(group)
        self.radio_file = QRadioButton("File (.gpkg / .shp / .geojson):")
        self.radio_file.setChecked(True)
        self.file_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.pick_aoi)
        self.layer_combo = QComboBox()
        self.radio_bbox = QRadioButton("Bounding box (lon/lat):")
        self.bbox_spins = []
        bbox_row = QHBoxLayout()
        for name, low, high in (("W", -180, 180), ("S", -90, 90),
                                ("E", -180, 180), ("N", -90, 90)):
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(4)
            spin.setPrefix(f"{name} ")
            bbox_row.addWidget(spin)
            self.bbox_spins.append(spin)
        grid.addWidget(self.radio_file, 0, 0, 1, 2)
        grid.addWidget(self.file_edit, 1, 0)
        grid.addWidget(browse, 1, 1)
        grid.addWidget(QLabel("Layer:"), 2, 0)
        grid.addWidget(self.layer_combo, 3, 0, 1, 2)
        grid.addWidget(self.radio_bbox, 4, 0, 1, 2)
        grid.addLayout(bbox_row, 5, 0, 1, 2)
        layout.addWidget(group)

        # 3. dates & filters
        group = QGroupBox("3. Dates and filters")
        grid = QGridLayout(group)
        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
        self.clouds_spin = QSpinBox()
        self.clouds_spin.setRange(0, 100)
        self.clouds_spin.setSuffix(" %")
        self.split_check = QCheckBox("Split search per year "
                                     "(2001, 2002, 2003 ...)")
        self.subfolder_check = QCheckBox("Each year in its own sub-folder")
        grid.addWidget(QLabel("From:"), 0, 0)
        grid.addWidget(self.date_from, 0, 1)
        grid.addWidget(QLabel("To:"), 0, 2)
        grid.addWidget(self.date_to, 0, 3)
        grid.addWidget(QLabel("Max clouds:"), 1, 0)
        grid.addWidget(self.clouds_spin, 1, 1)
        grid.addWidget(self.split_check, 2, 0, 1, 4)
        grid.addWidget(self.subfolder_check, 3, 0, 1, 4)
        layout.addWidget(group)

        # 4. products
        group = QGroupBox("4. Products / bands")
        grid = QGridLayout(group)
        self.product_checks = {}
        for number, key in enumerate(engine.PRODUCTS):
            check = QCheckBox(key)
            check.setToolTip(engine.PRODUCTS[key]["label"])
            grid.addWidget(check, number // 5, number % 5)
            self.product_checks[key] = check
        row = (len(engine.PRODUCTS) + 4) // 5
        self.extra_checks = {}
        for number, (band, label) in enumerate(
                fast_engine.EXTRA_BANDS.items()):
            check = QCheckBox(f"+ {label}")
            grid.addWidget(check, row + number, 0, 1, 5)
            self.extra_checks[band] = check
        row += len(self.extra_checks)
        self.raw_check = QCheckBox("Raw bands only (skip building "
                                   "products — fastest)")
        self.keep_check = QCheckBox("Keep raw band files")
        grid.addWidget(self.raw_check, row, 0, 1, 5)
        grid.addWidget(self.keep_check, row + 1, 0, 1, 5)
        layout.addWidget(group)

        # 5. performance & folder
        group = QGroupBox("5. Speed and output")
        grid = QGridLayout(group)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.builders_spin = QSpinBox()
        self.builders_spin.setRange(1, 8)
        self.folder_edit = QLineEdit()
        folder_button = QPushButton("Browse...")
        folder_button.clicked.connect(self.pick_folder)
        grid.addWidget(QLabel("Parallel band downloads:"), 0, 0)
        grid.addWidget(self.workers_spin, 0, 1)
        grid.addWidget(QLabel("Parallel product builds (RAM!):"), 1, 0)
        grid.addWidget(self.builders_spin, 1, 1)
        grid.addWidget(QLabel("Output folder:"), 2, 0, 1, 2)
        grid.addWidget(self.folder_edit, 3, 0)
        grid.addWidget(folder_button, 3, 1)
        layout.addWidget(group)

        self.search_button = self._big_button("SEARCH SCENES", self.search)
        layout.addWidget(self.search_button)
        layout.addStretch()
        return panel

    def _build_right(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.summary_label = QLabel("Search first — the found scenes "
                                    "appear here.")
        layout.addWidget(self.summary_label)

        tools = QHBoxLayout()
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["Select all",
                                      "Best 3 per month (least clouds)",
                                      "Best 1 per month (least clouds)",
                                      "Select none"])
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.apply_strategy)
        tools.addWidget(QLabel("Selection:"))
        tools.addWidget(self.strategy_combo)
        tools.addWidget(apply_button)
        tools.addStretch()
        layout.addLayout(tools)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Get", "Group", "Date", "Clouds %", "Satellite", "Scene ID",
             "Status"])
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(lambda _: self.update_counter())
        layout.addWidget(self.table, 3)

        buttons = QHBoxLayout()
        self.download_button = self._big_button("DOWNLOAD SELECTED",
                                                self.start_download)
        self.download_button.setEnabled(False)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("padding: 10px; font-weight: bold;")
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.download_button, 3)
        buttons.addWidget(self.stop_button, 1)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.stats_label = QLabel("")
        layout.addWidget(self.stats_label)

        self.active_label = QLabel("<b>Active downloads</b>")
        layout.addWidget(self.active_label)
        self.active_table = QTableWidget(0, 6)
        self.active_table.setHorizontalHeaderLabels(
            ["Scene", "Band", "Progress", "MB", "Speed", "State"])
        self.active_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.active_table.verticalHeader().setVisible(False)
        self.active_table.verticalHeader().setDefaultSectionSize(20)
        header = self.active_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.active_table.setColumnWidth(2, 200)
        layout.addWidget(self.active_table, 3)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)   # never grows forever
        layout.addWidget(self.log, 1)
        return panel

    def _big_button(self, text, slot):
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR}; color: white; "
            f"font-weight: bold; padding: 10px; border-radius: 4px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_HOVER}; }} "
            f"QPushButton:disabled {{ background-color: #b8c4c8; }}")
        button.clicked.connect(slot)
        return button

    # ---- settings ----------------------------------------------------------
    def load_settings(self):
        s = self.settings
        self.user_edit.setText(s.value("cdse_user", ""))
        self.file_edit.setText(s.value("aoi_file", ""))
        self.refresh_layers(s.value("aoi_layer", ""))
        if s.value("aoi_mode", "file") == "bbox":
            self.radio_bbox.setChecked(True)
        for spin, value in zip(self.bbox_spins,
                               s.value("bbox", "0,0,0,0").split(",")):
            spin.setValue(float(value))
        self.date_from.setDate(QDate.fromString(
            s.value("date_from", "2001-01-01"), "yyyy-MM-dd"))
        self.date_to.setDate(QDate.fromString(
            s.value("date_to", "2003-12-31"), "yyyy-MM-dd"))
        self.clouds_spin.setValue(int(s.value("clouds", 20)))
        self.split_check.setChecked(s.value("split", "true") == "true")
        self.subfolder_check.setChecked(
            s.value("subfolders", "true") == "true")
        products = s.value("products", "RGB,NDVI").split(",")
        for key, check in self.product_checks.items():
            check.setChecked(key in products)
        extras = s.value("extras", "").split(",")
        for key, check in self.extra_checks.items():
            check.setChecked(key in extras)
        self.raw_check.setChecked(s.value("raw_only", "false") == "true")
        self.keep_check.setChecked(s.value("keep", "true") == "true")
        self.workers_spin.setValue(int(s.value("workers", 12)))
        self.builders_spin.setValue(int(s.value("builders", 2)))
        self.folder_edit.setText(s.value("folder", ""))

        index = self.source_combo.findData(s.value("source", "landsat"))
        self.source_combo.setCurrentIndex(max(0, index))
        self.on_source_changed()
        self.source_combo.currentIndexChanged.connect(
            self.on_source_changed)

    def current_source(self):
        return fast_engine.SOURCES[self.source_combo.currentData()]

    def on_source_changed(self, *_):
        """Swap missions, hint, extra-band label, login box and the
        raw-only lock to match the chosen source."""
        s = self.settings
        if self.source_key is not None:      # remember the old ticks
            s.setValue(f"platforms_{self.source_key}",
                       ",".join(self.chosen_platforms()))
            if self.raw_check.isEnabled():
                s.setValue("raw_only",
                           str(self.raw_check.isChecked()).lower())
        self.source_key = self.source_combo.currentData()
        source = self.current_source()

        for check in self.platform_checks.values():
            self.platform_grid.removeWidget(check)
            check.deleteLater()
        self.platform_checks = {}
        default = ",".join(source["default_platforms"])
        if self.source_key == "landsat":     # older settings key
            default = s.value("platforms", default)
        ticked = s.value(f"platforms_{self.source_key}", default).split(",")
        for number, (label, value) in enumerate(source["platforms"]):
            check = QCheckBox(label)
            check.setChecked(value in ticked)
            self.platform_grid.addWidget(check, 0, number)
            self.platform_checks[value] = check
        self.source_hint.setText(source["hint"])

        self.extra_checks["qa_pixel"].setText(f"+ {source['extra_label']}")
        self.login_box.setVisible(bool(source["auth"]))
        builds = source["products"]
        self.raw_check.setEnabled(builds)
        self.raw_check.setChecked(
            s.value("raw_only", "false") == "true" if builds else True)
        temp = self.product_checks["TEMP"]
        temp.setEnabled(builds)
        if not builds:
            temp.setChecked(False)
        self.update_counter()

    def save_settings(self):
        s = self.settings
        s.setValue("source", self.source_key)
        s.setValue(f"platforms_{self.source_key}",
                   ",".join(self.chosen_platforms()))
        s.setValue("cdse_user", self.user_edit.text().strip())
        s.setValue("aoi_file", self.file_edit.text().strip())
        s.setValue("aoi_layer", self.layer_combo.currentText())
        s.setValue("aoi_mode",
                   "bbox" if self.radio_bbox.isChecked() else "file")
        s.setValue("bbox", ",".join(str(x.value())
                                    for x in self.bbox_spins))
        s.setValue("date_from",
                   self.date_from.date().toString("yyyy-MM-dd"))
        s.setValue("date_to", self.date_to.date().toString("yyyy-MM-dd"))
        s.setValue("clouds", self.clouds_spin.value())
        s.setValue("split", str(self.split_check.isChecked()).lower())
        s.setValue("subfolders",
                   str(self.subfolder_check.isChecked()).lower())
        s.setValue("products", ",".join(
            k for k, c in self.product_checks.items() if c.isChecked()))
        s.setValue("extras", ",".join(
            k for k, c in self.extra_checks.items() if c.isChecked()))
        if self.raw_check.isEnabled():       # not the forced S2 lock
            s.setValue("raw_only", str(self.raw_check.isChecked()).lower())
        s.setValue("keep", str(self.keep_check.isChecked()).lower())
        s.setValue("workers", self.workers_spin.value())
        s.setValue("builders", self.builders_spin.value())
        s.setValue("folder", self.folder_edit.text().strip())

    # ---- small actions -----------------------------------------------------
    def log_message(self, text):
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")

    def chosen_platforms(self):
        return [v for v, c in self.platform_checks.items() if c.isChecked()]

    def apply_start_options(self, aoi=None, folder=None):
        """Pre-fill the area of interest / output folder given on the
        command line (the QGIS launcher passes both)."""
        if aoi:
            self.file_edit.setText(aoi)
            self.radio_file.setChecked(True)
            self.refresh_layers()
        if folder:
            self.folder_edit.setText(folder)

    def pick_aoi(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Area of interest", self.file_edit.text(),
            "Vector files (*.gpkg *.shp *.geojson *.json *.kml);;"
            "All files (*)")
        if path:
            self.file_edit.setText(path)
            self.radio_file.setChecked(True)
            self.refresh_layers()

    def refresh_layers(self, wanted=""):
        self.layer_combo.clear()
        path = self.file_edit.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            names = list_layers(path)
        except Exception as error:
            self.log_message(str(error))
            return
        self.layer_combo.addItems(names)
        if wanted in names:
            self.layer_combo.setCurrentText(wanted)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Output folder", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def chosen_products(self):
        return {k: c.isChecked() for k, c in self.product_checks.items()}

    # ---- search ------------------------------------------------------------
    def search(self):
        platforms = self.chosen_platforms()
        if not platforms:
            QMessageBox.warning(self, "Missions", "Tick at least one "
                                "mission.")
            return
        try:
            if self.radio_bbox.isChecked():
                west, south, east, north = (s.value()
                                            for s in self.bbox_spins)
                if west >= east or south >= north:
                    raise RuntimeError("Bounding box: W < E and S < N.")
                aoi = geojson_from_bbox(west, south, east, north)
            else:
                path = self.file_edit.text().strip()
                if not path:
                    raise RuntimeError("Choose an area-of-interest file.")
                aoi = geojson_from_file(path,
                                        self.layer_combo.currentText())
        except Exception as error:
            QMessageBox.warning(self, "Area of interest", str(error))
            return
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        if date_from > date_to:
            QMessageBox.warning(self, "Dates", "'From' is after 'To'.")
            return
        self.save_settings()

        self.search_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.search_stop.clear()
        self.search_events = []
        clouds = self.clouds_spin.value()
        split = self.split_check.isChecked()
        source = self.current_source()
        self.log_message(f"Source: {source['label']}")

        def work():
            try:
                result = fast_engine.search_chunks(
                    source, aoi, date_from, date_to, clouds, platforms,
                    split,
                    log=lambda t: self.search_events.append(("log", t)),
                    stop=self.search_stop)
                self.search_events.append(("result", (result, source)))
            except Exception as error:
                self.search_events.append(("error", str(error)))

        self.search_thread = threading.Thread(target=work, daemon=True)
        self.search_thread.start()

    def show_results(self, results, source):
        self.results = results
        self.rows_source = source
        self.rows = [(label, item) for label, items in results
                     for item in items]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for row, (label, item) in enumerate(self.rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                           | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, check)
            clouds = engine.scene_clouds(item)
            values = [label, engine.scene_date(item),
                      "" if clouds is None else f"{clouds:.1f}",
                      engine.scene_platform(item), item["id"]]
            for column, value in enumerate(values, start=1):
                self.table.setItem(row, column, QTableWidgetItem(value))
            self.table.setItem(row, 6, QTableWidgetItem(""))
        self.row_of = {item["id"]: row
                       for row, (_, item) in enumerate(self.rows)}
        for scene_id, (text, key) in self.scene_status.items():
            self.set_status(scene_id, text, key)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        per_group = ", ".join(f"{label}: {len(items)}"
                              for label, items in results)
        self.summary_label.setText(f"<b>Found {len(self.rows)} scenes</b>"
                                   f" — {per_group}")
        self.update_counter()
        self.download_button.setEnabled(bool(self.rows))

    def apply_strategy(self):
        mode = self.strategy_combo.currentIndex()
        keep = set()
        if mode == 0:
            keep = set(range(len(self.rows)))
        elif mode in (1, 2):
            limit = 3 if mode == 1 else 1
            by_month = {}
            for row, (_, item) in enumerate(self.rows):
                by_month.setdefault(engine.scene_date(item)[:7],
                                    []).append(row)
            for rows in by_month.values():
                rows.sort(key=lambda r: engine.scene_clouds(
                    self.rows[r][1]) or 101)
                keep.update(rows[:limit])
        self.table.blockSignals(True)
        for row in range(len(self.rows)):
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if row in keep
                else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.update_counter()

    def selected_rows(self):
        return [self.rows[r] for r in range(len(self.rows))
                if self.table.item(r, 0).checkState()
                == Qt.CheckState.Checked]

    def chosen_extras(self):
        return [b for b, c in self.extra_checks.items() if c.isChecked()]

    def gb_per_scene(self):
        """Rough download size of one scene for the current ticks."""
        if not self.rows:
            return 0
        products = [k for k, on in self.chosen_products().items() if on]
        bands = fast_engine.source_assets(self.rows_source, self.rows[0][1],
                                          products, self.chosen_extras())
        return len(bands) * self.rows_source["gb_per_band"]

    def update_counter(self):
        count = len(self.selected_rows())
        gb = count * self.gb_per_scene()
        self.stats_label.setText(f"Selected: {count} scenes, "
                                 f"~{gb:.1f} GB of band downloads")

    # ---- download ----------------------------------------------------------
    def start_download(self):
        selected = self.selected_rows()
        folder = self.folder_edit.text().strip()
        products = self.chosen_products()
        extras = self.chosen_extras()
        source = self.rows_source
        if not selected:
            QMessageBox.warning(self, "Nothing selected",
                                "Tick at least one scene.")
            return
        if not folder:
            QMessageBox.warning(self, "Folder", "Choose an output folder.")
            return
        if not any(products.values()) and not extras:
            QMessageBox.warning(self, "Products", "Tick at least one "
                                "product or band.")
            return
        self.save_settings()
        login = self.check_login(source)
        if login is False:
            return
        subfolders = self.subfolder_check.isChecked()
        base = os.path.join(folder, source["folder"])
        jobs = [(item, os.path.join(base, label) if subfolders else base,
                 source) for label, item in selected]

        # a run is going: just add to its queue
        if self.downloader is not None:
            if login:
                self.downloader.set_login(source["auth"], *login)
            added = self.downloader.add_jobs(jobs)
            if added is not None:
                self.mark_queued(jobs)
                self.progress.setMaximum(self.downloader.total)
                self.log_message(
                    f"Added {added} scenes to the queue "
                    f"({len(jobs) - added} were already queued). "
                    f"They use the products / bands of the running "
                    f"queue.")
                return
            # the run finished a moment ago — fall through, start anew

        gb = len(selected) * self.gb_per_scene()
        if QMessageBox.question(
                self, "Start?",
                f"Download {len(selected)} scenes (~{gb:.1f} GB) into\n"
                f"{folder}\n\nwith {self.workers_spin.value()} parallel "
                f"downloads?") != QMessageBox.StandardButton.Yes:
            return

        self.mark_queued(jobs)
        self.downloader = fast_engine.BulkDownloader(
            jobs, products, extra_bands=extras,
            raw_only=self.raw_check.isChecked(),
            keep_bands=self.keep_check.isChecked(),
            workers=self.workers_spin.value(),
            builders=self.builders_spin.value())
        if login:
            self.downloader.set_login(source["auth"], *login)
        self.counts = {"ok": 0, "failed": 0, "skipped": 0, "cancelled": 0}
        self.started = time.time()
        self.speed_mark = (time.time(), 0)
        self.speed = 0.0
        self.band_speed = {}
        self.progress.setMaximum(len(jobs))
        self.progress.setValue(0)
        self.download_button.setText("ADD SELECTED TO QUEUE")
        self.stop_button.setEnabled(True)
        self.log_message(f"Starting {len(jobs)} scenes, "
                         f"{self.workers_spin.value()} parallel "
                         f"downloads...")
        self.worker = threading.Thread(target=self.downloader.run,
                                       daemon=True)
        self.worker.start()

    def check_login(self, source):
        """None = no login needed; (user, password) = checked OK;
        False = missing or wrong (the user has been told)."""
        if not source["auth"]:
            return None
        user = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not user or not password:
            QMessageBox.warning(self, "Login", "Enter your Copernicus "
                                "Data Space e-mail and password "
                                "(section 0).")
            return False
        try:
            fast_engine.TokenAuth(fast_engine.make_session(2), user,
                                  password).headers()
        except Exception as error:
            QMessageBox.warning(self, "Login", str(error))
            return False
        return user, password

    def stop(self):
        if self.downloader is not None:
            self.downloader.stop.set()
            self.log_message("Stopping — partial files are kept; "
                             "download again later to resume them.")
        self.search_stop.set()
        self.stop_button.setEnabled(False)

    # ---- polling (all thread -> GUI traffic goes through here) -------------
    def poll(self):
        while self.search_events:
            kind, payload = self.search_events.pop(0)
            if kind == "log":
                self.log_message(payload)
            elif kind == "result":
                self.show_results(*payload)
                self.search_button.setEnabled(True)
            elif kind == "error":
                self.search_button.setEnabled(True)
                self.download_button.setEnabled(bool(self.rows))
                QMessageBox.critical(self, "Search failed", payload)

        if self.downloader is None:
            return
        events = self.downloader.events
        for _ in range(500):
            try:
                kind, payload = events.get_nowait()
            except Exception:
                break
            if kind == "log":
                self.log_message(payload)
            elif kind == "status":
                scene_id, text = payload
                self.set_status(scene_id, text, "active")
            elif kind == "scene":
                self.counts[payload["key"]] += 1
                done = sum(self.counts.values())
                self.progress.setValue(done)
                self.set_status(payload["scene"], payload["status"],
                                payload["key"])
            elif kind == "done":
                self.finish(payload)
                return
        self.update_stats()
        self.update_active()

    # ---- live status -------------------------------------------------------
    STATUS_COLORS = {"ok": "#2e9e44", "failed": "#d0312d",
                     "cancelled": "#b06d00", "skipped": "#808080",
                     "active": COLOR, "queued": "#808080"}

    def set_status(self, scene_id, text, key):
        self.scene_status[scene_id] = (text, key)
        row = getattr(self, "row_of", {}).get(scene_id)
        if row is None:
            return
        cell = self.table.item(row, 6)
        cell.setText(text)
        cell.setForeground(QColor(self.STATUS_COLORS.get(key, "#000")))

    def mark_queued(self, jobs):
        for item, _, _ in jobs:
            text, key = self.scene_status.get(item["id"], ("", ""))
            if key not in ("active", "queued"):
                self.set_status(item["id"], "queued", "queued")

    def update_active(self):
        """One row per band being downloaded, with its own bar."""
        if self.downloader is None:
            return
        now = time.time()
        snapshot = sorted(dict(self.downloader.active).items())
        table = self.active_table
        table.setRowCount(len(snapshot))
        speeds = {}
        for row, (key, entry) in enumerate(snapshot):
            done, total = entry["done"], entry["total"]
            last_time, last_done, speed = self.band_speed.get(
                key, (now, done, 0.0))
            if now - last_time >= 1.5:
                current = max(0, done - last_done) / (now - last_time)
                speed = current if speed == 0 \
                    else 0.6 * speed + 0.4 * current
                last_time, last_done = now, done
            speeds[key] = (last_time, last_done, speed)

            values = {0: entry["scene"], 1: entry["asset"],
                      3: f"{done/1e6:.1f} / {total/1e6:.0f}" if total
                      else f"{done/1e6:.1f}",
                      4: f"{speed/1e3:.0f} KB/s" if speed else "",
                      5: entry["state"]}
            for column, text in values.items():
                cell = table.item(row, column)
                if cell is None:
                    table.setItem(row, column, QTableWidgetItem(text))
                elif cell.text() != text:
                    cell.setText(text)
            bar = table.cellWidget(row, 2)
            if bar is None:
                bar = QProgressBar()
                bar.setMaximum(1000)
                bar.setTextVisible(True)
                table.setCellWidget(row, 2, bar)
            bar.setValue(int(1000 * done / total) if total else 0)
            bar.setFormat(f"{100 * done / total:.0f}%" if total else "…")
        self.band_speed = speeds
        self.active_label.setText(
            f"<b>Active downloads: {len(snapshot)}</b> "
            f"(of {self.downloader.workers} slots)")

    def update_stats(self):
        now = time.time()
        got = self.downloader.bytes_done
        mark_time, mark_bytes = self.speed_mark
        if now - mark_time >= 2:
            current = (got - mark_bytes) / (now - mark_time)
            self.speed = current if self.speed == 0 \
                else 0.7 * self.speed + 0.3 * current
            self.speed_mark = (now, got)
        done = sum(self.counts.values())
        total = self.downloader.total
        self.progress.setMaximum(max(1, total))
        eta = ""
        if done:
            left = (now - self.started) / done * (total - done)
            eta = f", ETA ~{left/60:.0f} min"
        c = self.counts
        self.stats_label.setText(
            f"{done}/{total} scenes — OK {c['ok']}, skipped "
            f"{c['skipped']}, failed {c['failed']} | "
            f"{got/1e9:.2f} GB downloaded, "
            f"{self.speed/1e6:.1f} MB/s{eta}")

    def finish(self, summary):
        self.update_stats()
        self.active_table.setRowCount(0)
        self.active_label.setText("<b>Active downloads</b>")
        self.stop_button.setEnabled(False)
        self.download_button.setText("DOWNLOAD SELECTED")
        self.download_button.setEnabled(bool(self.rows))
        self.search_button.setEnabled(True)
        self.downloader = None
        c = summary
        self.log_message(f"FINISHED — OK {c['ok']}, skipped "
                         f"{c['skipped']}, failed {c['failed']}, "
                         f"cancelled {c['cancelled']}.")
        for path in summary["reports"]:
            self.log_message(f"Report: {path}")
        message = (f"OK: {c['ok']}\nSkipped (already done): "
                   f"{c['skipped']}\nFailed: {c['failed']}\n"
                   f"Cancelled: {c['cancelled']}")
        if c["failed"] or c["cancelled"]:
            message += "\n\nRun the download again to retry / resume."
        QMessageBox.information(self, "Done", message)

    def closeEvent(self, event):
        if self.downloader is not None:
            if QMessageBox.question(
                    self, "Download running",
                    "A download is running. Stop it and quit?") \
                    != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.downloader.stop.set()
            if self.worker is not None:
                self.worker.join(timeout=15)
        self.save_settings()
        event.accept()


def main():
    parser = argparse.ArgumentParser(description="Landsat / Sentinel-2 "
                                     "bulk downloader")
    parser.add_argument("--aoi", help="area-of-interest vector file")
    parser.add_argument("--out", help="output folder")
    args, qt_args = parser.parse_known_args()
    app = QApplication(sys.argv[:1] + qt_args)
    window = MainWindow()
    window.apply_start_options(args.aoi, args.out)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
