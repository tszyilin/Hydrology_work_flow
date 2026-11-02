# -*- coding: utf-8 -*-
"""
DIALOGS of the "Landsat Download" plugin (Qt):
  - MainDialog: settings form + log + progress bar
  - SceneDialog: list of found scenes with checkboxes, month filter
    and strategies (all / manual / top 3 per month)
  - DownloadThread: background downloading so QGIS stays responsive

© Grzegorz Górniak
"""

import os
import json

from qgis.PyQt.QtCore import Qt, QDate, QThread, pyqtSignal, QSettings
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QLineEdit, QPushButton, QSpinBox, QDateEdit, QCheckBox,
    QRadioButton, QGroupBox, QFileDialog, QMessageBox, QTextEdit,
    QProgressBar, QTableWidget, QTableWidgetItem, QButtonGroup,
    QAbstractItemView)
from qgis.core import (QgsProject, QgsVectorLayer, QgsGeometry,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsMapLayerProxyModel)
from qgis.gui import QgsMapLayerComboBox

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import engine

AUTHOR = "© Grzegorz Górniak"
AUTHOR_EMAIL = "gorniakgrzegorz@gmail.com"
COLOR = "#00bde7"        # leading colour of the plugin
COLOR_HOVER = "#009ec2"  # darker shade on hover


def footer():
    """Small author signature: right-aligned, black, no underline,
    yet clickable — a click opens an e-mail to the author."""
    label = QLabel(f'<a href="mailto:{AUTHOR_EMAIL}" '
                   f'style="color:black; text-decoration:none;">'
                   f'{AUTHOR}</a>')
    label.setOpenExternalLinks(True)
    label.setAlignment(Qt.AlignmentFlag.AlignRight)
    label.setStyleSheet("font-size: 8px; color: black;")
    return label


def geojson_from_layer(layer):
    """
    Turns a vector layer into a GeoJSON geometry in WGS84 — the
    format the STAC search API expects. Merges all features into one
    shape, wraps multi-part geometries in a convex hull, simplifies.
    """
    geometries = [feature.geometry() for feature in layer.getFeatures()
                  if feature.hasGeometry()]
    if not geometries:
        raise RuntimeError("The layer has no features with geometry.")
    geometry = QgsGeometry.unaryUnion(geometries)

    transform = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance())
    geometry.transform(transform)

    if geometry.isMultipart():
        geometry = geometry.convexHull()   # one common outline
    geometry = geometry.simplify(0.001)    # smooth (~100 m)
    return json.loads(geometry.asJson(5))


def geojson_from_file(path):
    """Opens a .gpkg file as a QGIS layer and reuses
    geojson_from_layer."""
    layer = QgsVectorLayer(path, "aoi", "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Could not open the file: {path}")
    return geojson_from_layer(layer)


# =============================================================================
#  DOWNLOAD THREAD — all the work in the background, QGIS stays alive
# =============================================================================

class DownloadThread(QThread):
    """
    Downloads scenes in parallel (ThreadPoolExecutor) and builds
    products, reporting progress through signals so the QGIS window
    never freezes.
    """
    message = pyqtSignal(str)          # log line for the dialog
    progress = pyqtSignal(int, int)    # (finished, total)
    finished_all = pyqtSignal(int, int, str, list)  # ok, failed,
    #                                                 report, products

    def __init__(self, scenes, settings):
        super().__init__()
        self.scenes = scenes
        self.s = settings

    def run(self):
        s = self.s
        report, tifs = [], []
        ok, failed, done = 0, 0, 0
        os.makedirs(s["folder"], exist_ok=True)

        def one(item, number):
            return engine.download_scene(
                item, number, len(self.scenes), s["folder"],
                s["products"], s["keep_bands"], self.message.emit)

        with ThreadPoolExecutor(max_workers=s["parallel"]) as team:
            jobs = {team.submit(one, item, number): item
                    for number, item in enumerate(self.scenes,
                                                  start=1)}
            for job in as_completed(jobs):
                item = jobs[job]
                try:
                    created, status, seconds = job.result()
                    ok += 1
                    tifs += created
                except Exception as error:
                    created, seconds = [], 0
                    status = f"failed ({error})"
                    failed += 1
                    self.message.emit(f"OOPS: scene "
                                      f"{item['id'][:40]} — {error}")
                done += 1
                self.progress.emit(done, len(self.scenes))
                report.append({
                    "scene": item["id"],
                    "date": engine.scene_date(item),
                    "platform": engine.scene_platform(item),
                    "clouds_%": engine.scene_clouds(item),
                    "products": len(created),
                    "status": status,
                    "minutes": round(seconds / 60, 1)})

        report_path = engine.save_report(s["folder"], report) \
            if report else ""
        self.finished_all.emit(ok, failed, report_path, tifs)


# =============================================================================
#  SCENE SELECTION DIALOG
# =============================================================================

class SceneDialog(QDialog):
    """
    The list of found scenes with checkboxes + strategy + month filter
    + "select all" + a live counter + an "Are you sure?" confirmation.
    After closing, self.selected holds the chosen scenes.
    """

    def __init__(self, scenes, start_strategy, gb_per_scene,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose scenes to download")
        self.resize(780, 620)
        self.selected = []
        self.gb_per_scene = gb_per_scene
        self.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; }} "
            f"QGroupBox::title {{ color: {COLOR}; }}")

        self.entries = []
        for item in scenes:
            date = engine.scene_date(item)
            clouds = engine.scene_clouds(item)
            self.entries.append({
                "item": item, "date": date, "month": date[:7],
                "clouds": clouds if clouds is not None else 101,
                "platform": engine.scene_platform(item)})
        months = sorted({entry["month"] for entry in self.entries})

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>Found {len(scenes)} scenes. "
            f"Which ones shall we download?</b>"))

        # --- strategy ---
        strategy_group = QGroupBox("Selection strategy")
        strategy_layout = QVBoxLayout(strategy_group)
        self.radios = QButtonGroup(self)
        for label, value in engine.STRATEGIES:
            radio = QRadioButton(label)
            radio.setProperty("value", value)
            if value == start_strategy:
                radio.setChecked(True)
            self.radios.addButton(radio)
            strategy_layout.addWidget(radio)
        layout.addWidget(strategy_group)

        # --- month filter ---
        months_group = QGroupBox("Months (untick to skip)")
        months_grid = QGridLayout(months_group)
        self.month_checks = {}
        for number, month in enumerate(months):
            year, mm = month.split("-")
            check = QCheckBox(f"{engine.MONTH_NAMES[mm]} {year}")
            check.setChecked(True)
            months_grid.addWidget(check, number // 4, number % 4)
            self.month_checks[month] = check
        layout.addWidget(months_group)

        # --- select-all + scene table ---
        self.select_all = QCheckBox(
            "Select all (within the chosen months)")
        self.select_all.setChecked(True)
        layout.addWidget(self.select_all)

        self.table = QTableWidget(len(self.entries), 4)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Clouds", "Satellite", "Scene ID"])
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for row, entry in enumerate(self.entries):
            clouds_text = (f"{entry['clouds']:.1f}%"
                           if entry["clouds"] <= 100 else "n/a")
            cell = QTableWidgetItem(entry["date"])
            cell.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                          | Qt.ItemFlag.ItemIsEnabled)
            cell.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, cell)
            self.table.setItem(row, 1, QTableWidgetItem(clouds_text))
            self.table.setItem(row, 2,
                               QTableWidgetItem(entry["platform"]))
            self.table.setItem(row, 3,
                               QTableWidgetItem(entry["item"]["id"]))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        self.counter = QLabel("")
        layout.addWidget(self.counter)

        row_buttons = QHBoxLayout()
        ok_button = QPushButton("DOWNLOAD SELECTED")
        ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR}; color: white; "
            f"font-weight: bold; padding: 6px; border-radius: 4px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_HOVER}; }}")
        ok_button.clicked.connect(self.confirm)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        row_buttons.addWidget(ok_button)
        row_buttons.addWidget(cancel_button)
        layout.addLayout(row_buttons)
        layout.addWidget(footer())

        self.radios.buttonClicked.connect(self.apply_strategy)
        for check in self.month_checks.values():
            check.stateChanged.connect(self.apply_strategy)
        self.select_all.stateChanged.connect(self.toggle_all)
        self.table.itemChanged.connect(lambda _: self.update_counter())

        self.apply_strategy()

    # ---- helpers ------------------------------------------------------------
    def _chosen_months(self):
        return {month for month, check in self.month_checks.items()
                if check.isChecked()}

    def _strategy(self):
        button = self.radios.checkedButton()
        return button.property("value") if button else "ALL"

    def apply_strategy(self, *_):
        """
        Re-ticks the table according to the strategy and month filter:
        ALL — every scene in the chosen months; TOP3 — the 3 least
        cloudy scenes of each month; MANUAL — hands off (except that
        unticked months always drop out).
        """
        self.table.blockSignals(True)
        months = self._chosen_months()
        mode = self._strategy()

        for row, entry in enumerate(self.entries):
            cell = self.table.item(row, 0)
            if entry["month"] not in months:
                cell.setCheckState(Qt.CheckState.Unchecked)
                cell.setFlags(Qt.ItemFlag.ItemIsUserCheckable)
            else:
                cell.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                              | Qt.ItemFlag.ItemIsEnabled)

        if mode == "ALL":
            for row, entry in enumerate(self.entries):
                self.table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked if entry["month"] in months
                    else Qt.CheckState.Unchecked)
        elif mode == "TOP3":
            for month in months:
                in_month = [(row, entry) for row, entry
                            in enumerate(self.entries)
                            if entry["month"] == month]
                in_month.sort(key=lambda pair: pair[1]["clouds"])
                for number, (row, _) in enumerate(in_month):
                    self.table.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if number < 3
                        else Qt.CheckState.Unchecked)
        # MANUAL: leave the ticks as they are

        self.table.blockSignals(False)
        self.update_counter()

    def toggle_all(self, *_):
        """The master checkbox: tick/untick the whole visible list."""
        self.table.blockSignals(True)
        months = self._chosen_months()
        state = (Qt.CheckState.Checked if self.select_all.isChecked()
                 else Qt.CheckState.Unchecked)
        for row, entry in enumerate(self.entries):
            self.table.item(row, 0).setCheckState(
                state if entry["month"] in months
                else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.update_counter()

    def update_counter(self):
        count = sum(
            1 for row in range(len(self.entries))
            if self.table.item(row, 0).checkState()
            == Qt.CheckState.Checked)
        self.counter.setText(
            f"<b>Selected: {count} scenes, roughly "
            f"{count * self.gb_per_scene:.1f} GB of band "
            f"downloads</b>")

    def confirm(self):
        """Collects the ticked scenes and asks 'Are you sure?'."""
        selected = [entry["item"] for row, entry
                    in enumerate(self.entries)
                    if self.table.item(row, 0).checkState()
                    == Qt.CheckState.Checked]
        if not selected:
            QMessageBox.warning(self, "Nothing selected",
                                "Tick at least one scene "
                                "(or click Cancel).")
            return
        gb = len(selected) * self.gb_per_scene
        if QMessageBox.question(
                self, "Are you sure?",
                f"To download: {len(selected)} scenes, roughly "
                f"{gb:.1f} GB.\nMake sure you have enough disk "
                f"space.\n\nProceed?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No) \
                == QMessageBox.StandardButton.Yes:
            self.selected = selected
            self.accept()


# =============================================================================
#  MAIN DIALOG
# =============================================================================

class MainDialog(QDialog):
    """
    The main form — everything in one window: Landsat mission, area
    (project layer or a .gpkg file), parameters, folder, strategy,
    products, the start button, a log and a progress bar.
    No account or sign-in is needed — the data is open.
    """

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.thread = None
        self.setWindowTitle("Landsat Download")
        self.resize(680, 760)
        self.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; }} "
            f"QGroupBox::title {{ color: {COLOR}; }} "
            f"QProgressBar::chunk {{ background-color: {COLOR}; }}")
        stored = QSettings()

        layout = QVBoxLayout(self)

        intro = QLabel(
            "<b>Bulk Landsat downloads with ready-to-use products — "
            "no account needed.</b><br>"
            "Data: USGS Landsat Collection 2 Level-2 (surface "
            "reflectance and temperature, 30 m, global archive since "
            "1982) served openly by the Microsoft Planetary Computer.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- 1. mission ---
        group1 = QGroupBox("1. Which Landsat missions?")
        layout1 = QVBoxLayout(group1)
        self.mission_combo = QComboBox()
        for label, platforms in engine.MISSIONS:
            self.mission_combo.addItem(label, platforms)
        layout1.addWidget(self.mission_combo)
        layout.addWidget(group1)

        # --- 2. area ---
        group2 = QGroupBox("2. Area of interest")
        layout2 = QGridLayout(group2)
        self.radio_layer = QRadioButton("Layer from the project:")
        self.radio_layer.setChecked(True)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(
            QgsMapLayerProxyModel.Filter.PolygonLayer)
        self.radio_file = QRadioButton("GeoPackage file (.gpkg):")
        self.file_edit = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.pick_gpkg)
        layout2.addWidget(self.radio_layer, 0, 0)
        layout2.addWidget(self.layer_combo, 0, 1, 1, 2)
        layout2.addWidget(self.radio_file, 1, 0)
        layout2.addWidget(self.file_edit, 1, 1)
        layout2.addWidget(browse_button, 1, 2)
        layout.addWidget(group2)

        # --- 3. parameters ---
        group3 = QGroupBox("3. Parameters")
        layout3 = QGridLayout(group3)
        self.date_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        self.clouds_spin = QSpinBox()
        self.clouds_spin.setRange(0, 100)
        self.clouds_spin.setValue(20)
        self.clouds_spin.setSuffix(" %")
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 2000)
        self.limit_spin.setValue(200)
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 4)
        self.parallel_spin.setValue(3)
        layout3.addWidget(QLabel("Date FROM:"), 0, 0)
        layout3.addWidget(self.date_from, 0, 1)
        layout3.addWidget(QLabel("Date TO:"), 0, 2)
        layout3.addWidget(self.date_to, 0, 3)
        layout3.addWidget(QLabel("Max clouds:"), 1, 0)
        layout3.addWidget(self.clouds_spin, 1, 1)
        layout3.addWidget(QLabel("Max scenes:"), 1, 2)
        layout3.addWidget(self.limit_spin, 1, 3)
        layout3.addWidget(QLabel("Parallel (1-4):"), 2, 0)
        layout3.addWidget(self.parallel_spin, 2, 1)
        layout.addWidget(group3)

        # --- 4. folder ---
        group4 = QGroupBox("4. Folder for downloaded files")
        layout4 = QHBoxLayout(group4)
        self.folder_edit = QLineEdit(
            stored.value("landsat_download/folder", ""))
        folder_button = QPushButton("Browse...")
        folder_button.clicked.connect(self.pick_folder)
        layout4.addWidget(self.folder_edit)
        layout4.addWidget(folder_button)
        layout.addWidget(group4)

        # --- 5. strategy ---
        group5 = QGroupBox("5. Which scenes to download? (you will "
                           "see the list anyway)")
        layout5 = QVBoxLayout(group5)
        self.strategy_radios = QButtonGroup(self)
        for number, (label, value) in enumerate(engine.STRATEGIES):
            radio = QRadioButton(label)
            radio.setProperty("value", value)
            if number == 0:
                radio.setChecked(True)
            self.strategy_radios.addButton(radio)
            layout5.addWidget(radio)
        layout.addWidget(group5)

        # --- 6. products ---
        group6 = QGroupBox("6. Products from every scene")
        layout6 = QGridLayout(group6)
        self.product_checks = {}
        for number, (key, recipe) in enumerate(
                engine.PRODUCTS.items()):
            check = QCheckBox(recipe["label"])
            check.setChecked(key in ("RGB", "NDVI"))
            layout6.addWidget(check, number // 2, number % 2)
            self.product_checks[key] = check
        self.keep_bands_check = QCheckBox(
            "Keep the raw band files (untick to save disk space)")
        self.keep_bands_check.setChecked(True)
        layout6.addWidget(self.keep_bands_check,
                          (len(engine.PRODUCTS) + 1) // 2 + 1, 0,
                          1, 2)
        self.load_check = QCheckBox(
            "Load the finished products into QGIS when done")
        self.load_check.setChecked(True)   # ticked by default
        self.load_check.setStyleSheet(
            "margin-top: 12px; font-weight: bold;")
        layout6.addWidget(self.load_check,
                          (len(engine.PRODUCTS) + 1) // 2 + 2, 0,
                          1, 2)
        layout.addWidget(group6)

        # --- start + progress + log ---
        self.start_button = QPushButton("START DOWNLOAD")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR}; color: white; "
            f"font-weight: bold; padding: 10px; border-radius: 4px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_HOVER}; }}")
        self.start_button.clicked.connect(self.start)
        layout.addWidget(self.start_button)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText(
            "You will see live progress messages here...")
        layout.addWidget(self.log)
        layout.addWidget(footer())

    # ---- small actions ------------------------------------------------------
    def log_message(self, text):
        self.log.append(text)
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())

    def pick_gpkg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a GeoPackage file", "",
            "GeoPackage (*.gpkg);;All files (*)")
        if path:
            self.file_edit.setText(path)
            self.radio_file.setChecked(True)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Folder for downloaded scenes")
        if path:
            self.folder_edit.setText(path)

    # ---- the main flow ------------------------------------------------------
    def start(self):
        if self.radio_file.isChecked() \
                and not self.file_edit.text().strip():
            QMessageBox.warning(self, "Missing file",
                                "Choose a .gpkg file with your area "
                                "(step 2).")
            return
        if not self.folder_edit.text().strip():
            QMessageBox.warning(self, "Missing folder",
                                "Choose a folder for the downloads "
                                "(step 4).")
            return
        products = {key: check.isChecked()
                    for key, check in self.product_checks.items()}
        if not any(products.values()):
            QMessageBox.warning(self, "No products selected",
                                "Tick at least one product (step 6) "
                                "— that is what decides which bands "
                                "are downloaded.")
            return

        strategy = self.strategy_radios.checkedButton() \
            .property("value")
        settings = {
            "platforms": self.mission_combo.currentData(),
            "date_from": self.date_from.date().toString("yyyy-MM-dd"),
            "date_to": self.date_to.date().toString("yyyy-MM-dd"),
            "clouds": self.clouds_spin.value(),
            "limit": self.limit_spin.value(),
            "parallel": self.parallel_spin.value(),
            "folder": self.folder_edit.text().strip(),
            "products": products,
            "keep_bands": self.keep_bands_check.isChecked(),
        }
        QSettings().setValue("landsat_download/folder",
                             settings["folder"])

        try:
            self.log_message("Preparing the search area...")
            if self.radio_layer.isChecked():
                layer = self.layer_combo.currentLayer()
                if layer is None:
                    QMessageBox.warning(self, "Missing layer",
                                        "Add a polygon layer to the "
                                        "project or choose a file.")
                    return
                aoi = geojson_from_layer(layer)
            else:
                aoi = geojson_from_file(self.file_edit.text().strip())

            self.log_message("Searching the Landsat catalogue "
                             "(no sign-in needed)...")
            scenes = engine.search_scenes(
                aoi, settings["date_from"], settings["date_to"],
                settings["clouds"], settings["platforms"],
                self.log_message)
        except Exception as error:
            QMessageBox.critical(self, "Oops, something went wrong",
                                 str(error))
            return

        if not scenes:
            QMessageBox.information(
                self, "Nothing found",
                "No scenes match these criteria. Increase the cloud "
                "limit, widen the dates or pick another mission "
                "(e.g. Landsat 4+5 for the 1980s and 1990s).")
            return
        if len(scenes) > settings["limit"]:
            self.log_message(
                f"Note: found {len(scenes)} scenes, your limit is "
                f"{settings['limit']} — taking the first "
                f"{settings['limit']}.")
            scenes = scenes[:settings["limit"]]

        # rough download size: bands needed per scene x band size
        bands_count = len(engine.needed_assets(scenes[0], products))
        gb_per_scene = bands_count * engine.GB_PER_BAND

        picker = SceneDialog(scenes, strategy, gb_per_scene, self)
        if (picker.exec() != QDialog.DialogCode.Accepted
                or not picker.selected):
            self.log_message("Selection cancelled — nothing "
                             "downloaded.")
            return
        scenes = picker.selected
        self.log_message(f"Selected for download: {len(scenes)} "
                         f"scenes. Here we go!")

        self.start_button.setDisabled(True)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(scenes))
        self.progress.setValue(0)
        self.thread = DownloadThread(scenes, settings)
        self.thread.message.connect(self.log_message)
        self.thread.progress.connect(
            lambda done, _: self.progress.setValue(done))
        self.thread.finished_all.connect(self.on_finished)
        self.thread.start()

    def on_finished(self, ok, failed, report, tifs):
        """Wrap-up after downloading + optional loading into QGIS."""
        self.start_button.setDisabled(False)
        self.log_message(f"DONE! Succeeded: {ok}, failed: {failed}.")
        if report:
            self.log_message(f"CSV report: {report}")

        if self.load_check.isChecked() and tifs:
            self.log_message(f"Loading {len(tifs)} products into "
                             f"QGIS...")
            for tif in tifs:
                self.iface.addRasterLayer(
                    tif, os.path.basename(tif).replace(".tif", ""))

        QMessageBox.information(
            self, "Done!",
            f"Finished!\nSucceeded: {ok}, failed: {failed}\n"
            f"Files and the CSV report are in the target folder."
            f"\n\n{AUTHOR}")
