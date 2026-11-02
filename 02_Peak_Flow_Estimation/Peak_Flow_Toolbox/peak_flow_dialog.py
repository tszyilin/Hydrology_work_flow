"""Main dockable widget for the Peak Flow Toolbox.

Layout:
    top project bar
    left case sidebar
    right tab widget

Tabs shown/hidden dynamically from the Enable-Methods checkboxes on the
Inputs tab. Regional method selection lives on the Inputs tab (nested
under the Regional checkbox); the Regional tab shows one section per
selected method, each with its own parameters + Run + result table.
"""

from __future__ import annotations

import os
from pathlib import Path

from .qt_compat import (
    Qt,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDesktopServices,
    QDoubleSpinBox,
    QFileDialog,
    QFont,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QObject,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QThread,
    QUrl,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from .core import plot_utils
from .core import regional_methods
from .core.regional_methods import recommender
from .core import rorb_parser
from .xlsx_project import AEPS, export_project, import_project

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

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

STYLE_PATH = os.path.join(os.path.dirname(__file__), "style", "buttons.qss")

# Method IDs whose inputs need a dedicated tab. Order defines the left-to-
# right tab order among the regional tabs.
REGIONAL_METHOD_ORDER = ["arr1987", "flavell", "davies_yip", "northfield"]

# Short tab titles (the full labels are shown as the tab header inside).
_TAB_LABELS = {
    "arr1987": "ARR1987",
    "flavell": "Flavell WA",
    "davies_yip": "Davies & Yip",
    "northfield": "Northfield NT",
}


def _short_label(method_id):
    return _TAB_LABELS.get(method_id, method_id)


def catchment_size_class(area_km2):
    """Davies & Yip (2014) size classes — also the size buckets referenced
    across most Australian regional methods. Returns (label, description)."""
    if area_km2 is None or area_km2 <= 0:
        return ("—", "")
    if area_km2 <= 1000:
        return ("Small", "≤ 1000 km²")
    if area_km2 <= 10_000:
        return ("Medium", "1000 – 10 000 km²")
    return ("Large", "> 10 000 km²")


RFFE_WEBSITE_URL = "https://rffe-2021.wmawater.com.au"


class _RffeThread(QThread):
    """Runs the RFFE query_site on a worker thread; mirrors _QueryThread
    from 01_Rffe_plugin/gui/rffe_dialog.py."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, lon, lat, area, clon, clat):
        super().__init__()
        self._args = (lon, lat, area, clon, clat)

    def run(self):
        try:
            from .core.rffe_bridge import query_site
            self.done.emit(query_site(*self._args))
        except Exception as exc:
            self.failed.emit(str(exc))


class PeakFlowDialog(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface

        if os.path.exists(STYLE_PATH):
            with open(STYLE_PATH, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

        font = QFont()
        font.setPointSize(9)
        self.setFont(font)

        self._cases = []
        self._case_by_id = {}
        self._next_case_id = 1
        self._next_case_number = 1
        self._loading_case = False
        self._current_project_path = None
        self._rffe_thread = None
        self._method_sections = {}  # method_id -> {'group', 'widgets', 'result_table', 'button'}
        self._method_enable_checks = {}  # method_id -> QCheckBox on Inputs tab

        root = QVBoxLayout(self)
        self._build_project_bar(root)

        body = QHBoxLayout()
        root.addLayout(body, stretch=1)
        self._build_case_sidebar(body)
        self._build_tabs(body)

        self._add_case()
        self._update_tab_visibility()

    # ==================================================================
    # Top: Project bar
    # ==================================================================
    def _build_project_bar(self, root_layout):
        panel = QGroupBox("Project")
        row = QHBoxLayout(panel)
        self.labelProjectName = QLabel("Untitled")
        self.labelProjectName.setStyleSheet("font-weight: bold;")
        row.addWidget(self.labelProjectName)
        row.addStretch()

        self.btnImport = QPushButton("Import Project (.xlsx)")
        self.btnRefresh = QPushButton("Refresh")
        self.btnRefresh.setEnabled(False)
        self.btnSave = QPushButton("Save")
        self.btnSaveAs = QPushButton("Save As")
        for b in (self.btnImport, self.btnRefresh, self.btnSave, self.btnSaveAs):
            row.addWidget(b)

        self.btnImport.clicked.connect(self._on_import_project)
        self.btnRefresh.clicked.connect(self._on_refresh_project)
        self.btnSave.clicked.connect(self._on_save_project)
        self.btnSaveAs.clicked.connect(self._on_save_project_as)

        root_layout.addWidget(panel)

    # ==================================================================
    # Sidebar: cases
    # ==================================================================
    def _build_case_sidebar(self, body_layout):
        sidebar = QGroupBox("Cases")
        sidebar.setFixedWidth(180)
        layout = QVBoxLayout(sidebar)

        self.caseList = QListWidget()
        self.caseList.setDragDropMode(QAbstractItemView.InternalMove)
        self.caseList.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.caseList.currentRowChanged.connect(self._on_case_selected)
        self.caseList.itemChanged.connect(self._on_case_item_renamed)
        self.caseList.model().rowsMoved.connect(self._on_case_reordered)
        layout.addWidget(self.caseList)

        row = QHBoxLayout()
        self.btnAdd = QPushButton("+")
        self.btnRename = QPushButton("Rename")
        self.btnDel = QPushButton("−")
        for b in (self.btnAdd, self.btnRename, self.btnDel):
            row.addWidget(b)
        layout.addLayout(row)

        self.btnAdd.clicked.connect(self._add_case)
        self.btnRename.clicked.connect(self._rename_case)
        self.btnDel.clicked.connect(self._delete_case)

        body_layout.addWidget(sidebar)

    # ==================================================================
    # Tabs
    # ==================================================================
    def _build_tabs(self, body_layout):
        self.tabs = QTabWidget()
        self.tabInputs = self._build_inputs_tab()
        self.tabRffe = self._build_rffe_tab()
        # One tab per regional method; each is built in _build_method_tab
        # and stored in _method_sections[mid]["tab"].
        self._method_tabs = {}
        for mid in REGIONAL_METHOD_ORDER:
            self._method_tabs[mid] = self._build_method_tab(mid)
        self.tabRorb = self._build_rorb_tab()
        self.tabResults = self._build_results_tab()

        self.tabs.addTab(self.tabInputs, "Inputs")
        self.tabs.addTab(self.tabRffe, "RFFE")
        for mid in REGIONAL_METHOD_ORDER:
            self.tabs.addTab(self._method_tabs[mid], _short_label(mid))
        self.tabs.addTab(self.tabRorb, "RORB")
        self.tabs.addTab(self.tabResults, "Results & Plot")
        body_layout.addWidget(self.tabs, stretch=1)

    def _update_tab_visibility(self):
        """Show/hide the RFFE / RORB / per-regional-method tabs from the
        Inputs checkboxes. Inputs + Results are always visible; each
        regional-method tab is shown only when that method is ticked on
        the Inputs tab (and the parent 'Regional' toggle is on)."""
        selected_regional = set(self._selected_regional_methods())
        wanted = {
            self.tabRffe: self.chkRffe.isChecked(),
            self.tabRorb: self.chkRorb.isChecked(),
        }
        for mid, tab in self._method_tabs.items():
            wanted[tab] = mid in selected_regional
        for widget, visible in wanted.items():
            idx = self.tabs.indexOf(widget)
            if idx < 0:
                continue
            if hasattr(self.tabs, "setTabVisible"):
                self.tabs.setTabVisible(idx, visible)
            else:
                self.tabs.setTabEnabled(idx, visible)

    # ------------------------------------------------------------------
    # Inputs tab
    # ------------------------------------------------------------------
    def _build_inputs_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w)

        # ---- Layer / coordinate group -------------------------------
        layers_g = QGroupBox("Catchment inputs")
        form = QFormLayout(layers_g)

        if QGIS_AVAILABLE:
            self.cmbCatchment = QgsMapLayerComboBox()
            self.cmbCatchment.setFilters(QgsMapLayerProxyModel.PolygonLayer)
            self.cmbOutletLayer = QgsMapLayerComboBox()
            self.cmbOutletLayer.setFilters(QgsMapLayerProxyModel.PointLayer)
        else:
            self.cmbCatchment = QComboBox()
            self.cmbOutletLayer = QComboBox()

        self.spinCatchFid = QSpinBox(); self.spinCatchFid.setRange(0, 10_000_000)
        self.spinOutletFid = QSpinBox(); self.spinOutletFid.setRange(0, 10_000_000)

        # Show feature count next to each layer's FID spinbox so the user
        # knows how many features the layer has (and gets a warning below
        # when it's > 1, since only the picked FID is used).
        self.lblCatchCount = QLabel("")
        self.lblCatchCount.setStyleSheet("color: #555;")
        self.lblOutletCount = QLabel("")
        self.lblOutletCount.setStyleSheet("color: #555;")

        catch_fid_row = QHBoxLayout()
        catch_fid_row.addWidget(self.spinCatchFid)
        catch_fid_row.addWidget(self.lblCatchCount, stretch=1)
        outlet_fid_row = QHBoxLayout()
        outlet_fid_row.addWidget(self.spinOutletFid)
        outlet_fid_row.addWidget(self.lblOutletCount, stretch=1)

        # Persistent multi-feature warning banner (hidden until triggered).
        self.lblMultiFeatureWarn = QLabel("")
        self.lblMultiFeatureWarn.setStyleSheet(
            "color: #a15c00; background: #fff4d6; border: 1px solid #e6c14d; "
            "padding: 4px; border-radius: 3px;"
        )
        self.lblMultiFeatureWarn.setWordWrap(True)
        self.lblMultiFeatureWarn.setVisible(False)

        form.addRow("Catchment polygon layer:", self.cmbCatchment)
        form.addRow("  Catchment feature ID:", self._wrap_layout(catch_fid_row))
        form.addRow("Outlet point layer:", self.cmbOutletLayer)
        form.addRow("  Outlet feature ID:", self._wrap_layout(outlet_fid_row))
        form.addRow("", self.lblMultiFeatureWarn)

        btn_row = QHBoxLayout()
        self.btnAutoFill = QPushButton("Auto-fill from Layers")
        self.btnAutoFill.clicked.connect(self._auto_fill_from_layers)
        btn_row.addWidget(self.btnAutoFill)
        btn_row.addStretch()
        form.addRow("", self._wrap_layout(btn_row))

        self.spinArea = self._coord_spin(0, 1_000_000, decimals=3, suffix=" km²")
        self.lblSizeClass = QLabel("Size class: —")
        self.lblSizeClass.setStyleSheet("color: #12222f; font-weight: 600;")
        self.spinOutletLon = self._coord_spin(-180, 180, decimals=6)
        self.spinOutletLat = self._coord_spin(-90, 90, decimals=6)
        self.spinCentLon = self._coord_spin(-180, 180, decimals=6)
        self.spinCentLat = self._coord_spin(-90, 90, decimals=6)

        area_row = QHBoxLayout()
        area_row.addWidget(self.spinArea)
        area_row.addWidget(self.lblSizeClass, stretch=1)
        form.addRow("Area (km²):", self._wrap_layout(area_row))
        form.addRow("Outlet Lon:", self.spinOutletLon)
        form.addRow("Outlet Lat:", self.spinOutletLat)
        form.addRow("Centroid Lon:", self.spinCentLon)
        form.addRow("Centroid Lat:", self.spinCentLat)

        outer.addWidget(layers_g)

        # ---- Enable methods -----------------------------------------
        methods_g = QGroupBox("Enable methods")
        m_layout = QVBoxLayout(methods_g)

        top_row = QHBoxLayout()
        self.chkRffe = QCheckBox("RFFE"); self.chkRffe.setChecked(True)
        self.chkRegional = QCheckBox("Regional"); self.chkRegional.setChecked(True)
        self.chkRorb = QCheckBox("RORB"); self.chkRorb.setChecked(False)
        top_row.addWidget(self.chkRffe)
        top_row.addWidget(self.chkRegional)
        top_row.addWidget(self.chkRorb)
        top_row.addStretch()
        m_layout.addLayout(top_row)

        # Nested regional selection (visible only when Regional is checked)
        self.regionalMethodsGroup = QGroupBox("Regional methods to run")
        rm_layout = QVBoxLayout(self.regionalMethodsGroup)
        self.lblRecommended = QLabel("Recommendation: (auto-fill from Layers first)")
        rm_layout.addWidget(self.lblRecommended)
        for mid in REGIONAL_METHOD_ORDER:
            chk = QCheckBox(regional_methods.label(mid))
            self._method_enable_checks[mid] = chk
            chk.toggled.connect(self._on_regional_selection_changed)
            rm_layout.addWidget(chk)
        m_layout.addWidget(self.regionalMethodsGroup)

        outer.addWidget(methods_g)
        outer.addStretch()

        # Wire signals
        for spin in (self.spinArea, self.spinOutletLon, self.spinOutletLat,
                     self.spinCentLon, self.spinCentLat):
            spin.valueChanged.connect(self._sync_current_case)
        self.spinArea.valueChanged.connect(self._refresh_size_class)
        for spin in (self.spinCatchFid, self.spinOutletFid):
            spin.valueChanged.connect(self._sync_current_case)
            spin.valueChanged.connect(lambda *_: self._refresh_feature_counts())
        for chk in (self.chkRffe, self.chkRegional, self.chkRorb):
            chk.toggled.connect(self._on_enable_toggled)
        if QGIS_AVAILABLE:
            self.cmbCatchment.layerChanged.connect(lambda *_: self._on_layer_changed())
            self.cmbOutletLayer.layerChanged.connect(lambda *_: self._on_layer_changed())

        return w

    def _on_layer_changed(self):
        self._refresh_feature_counts()
        self._sync_current_case()

    def _refresh_size_class(self):
        area = self.spinArea.value()
        cls, desc = catchment_size_class(area if area > 0 else None)
        text = f"Size class: {cls}"
        if desc:
            text += f"  ({desc})"
        self.lblSizeClass.setText(text)

    def _refresh_feature_counts(self):
        """Update the counts shown next to each FID spinbox and surface a
        warning if either input layer has more than one feature — only the
        selected FID is used, so the user needs to know which to pick."""
        if not QGIS_AVAILABLE:
            return
        catch = self.cmbCatchment.currentLayer()
        outlet = self.cmbOutletLayer.currentLayer()
        c_n = catch.featureCount() if catch is not None else 0
        o_n = outlet.featureCount() if outlet is not None else 0

        def _fmt(layer, n, kind):
            if layer is None:
                return ""
            fids = _first_feature_ids(layer, limit=5)
            fid_hint = f"  first FIDs: {', '.join(str(f) for f in fids)}" if fids else ""
            return f"({n} feature{'s' if n != 1 else ''} in layer){fid_hint}"

        self.lblCatchCount.setText(_fmt(catch, c_n, "polygon"))
        self.lblOutletCount.setText(_fmt(outlet, o_n, "point"))

        warnings = []
        if catch is not None and c_n > 1:
            warnings.append(
                f"Catchment layer '{catch.name()}' has {c_n} features — "
                "only feature ID {fid} will be used. Set the correct feature ID."
                .format(fid=self.spinCatchFid.value())
            )
        if outlet is not None and o_n > 1:
            warnings.append(
                f"Outlet layer '{outlet.name()}' has {o_n} features — "
                "only feature ID {fid} will be used. Set the correct feature ID."
                .format(fid=self.spinOutletFid.value())
            )
        if warnings:
            self.lblMultiFeatureWarn.setText("⚠  " + "\n⚠  ".join(warnings))
            self.lblMultiFeatureWarn.setVisible(True)
        else:
            self.lblMultiFeatureWarn.setVisible(False)

    def _wrap_layout(self, layout):
        wrap = QWidget(); wrap.setLayout(layout); return wrap

    def _coord_spin(self, lo, hi, decimals, suffix=""):
        s = QDoubleSpinBox()
        s.setRange(lo, hi); s.setDecimals(decimals)
        if suffix:
            s.setSuffix(suffix)
        return s

    def _on_enable_toggled(self):
        # Master Regional toggle mirrors down to all sub-method checkboxes:
        # ticking Regional enables all methods, unticking clears them.
        if self.sender() is self.chkRegional:
            for chk in self._method_enable_checks.values():
                chk.blockSignals(True)
                chk.setChecked(self.chkRegional.isChecked())
                chk.blockSignals(False)
        self.regionalMethodsGroup.setEnabled(self.chkRegional.isChecked())
        self._sync_current_case()
        self._update_tab_visibility()

    def _on_regional_selection_changed(self):
        self._on_sub_regional_toggled()
        self._sync_current_case()
        self._update_tab_visibility()

    def _selected_regional_methods(self):
        # Ticking a sub-method is sufficient — the master 'Regional' box is
        # just a mirror control (bulk on/off), not a gate.
        return [mid for mid, chk in self._method_enable_checks.items() if chk.isChecked()]

    def _on_sub_regional_toggled(self):
        """Keep the master 'Regional' checkbox in sync with the sub-method
        checkboxes: any sub ticked → Regional appears ticked."""
        any_on = any(chk.isChecked() for chk in self._method_enable_checks.values())
        if self.chkRegional.isChecked() != any_on:
            self.chkRegional.blockSignals(True)
            self.chkRegional.setChecked(any_on)
            self.chkRegional.blockSignals(False)

    def _auto_fill_from_layers(self):
        """Compute area + centroid from the catchment polygon (always), and
        outlet lon/lat from the outlet point layer. Both are transformed to
        WGS84 so RFFE can consume them directly."""
        if not QGIS_AVAILABLE:
            QMessageBox.information(self, "Peak Flow", "Requires QGIS runtime.")
            return
        catch_layer = self.cmbCatchment.currentLayer()
        outlet_layer = self.cmbOutletLayer.currentLayer()
        if catch_layer is None or outlet_layer is None:
            QMessageBox.warning(self, "Peak Flow", "Pick a catchment layer and an outlet layer first.")
            return

        # Nudge: if the layer has >1 features, remind the user that only the
        # chosen FID is used before we compute anything from the wrong feature.
        multi = []
        if catch_layer.featureCount() > 1:
            multi.append(f"'{catch_layer.name()}' has {catch_layer.featureCount()} polygons — "
                         f"using feature ID {self.spinCatchFid.value()}")
        if outlet_layer.featureCount() > 1:
            multi.append(f"'{outlet_layer.name()}' has {outlet_layer.featureCount()} points — "
                         f"using feature ID {self.spinOutletFid.value()}")
        if multi:
            resp = QMessageBox.question(
                self, "Peak Flow — Multi-feature layer",
                "Heads-up:\n\n• " + "\n• ".join(multi) +
                "\n\nContinue with these feature IDs?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if resp != QMessageBox.Yes:
                return

        try:
            area_m2, centroid_ll = _catchment_area_and_centroid(
                catch_layer, self.spinCatchFid.value()
            )
            outlet_ll = _feature_lonlat(outlet_layer, self.spinOutletFid.value())
        except ValueError as exc:
            QMessageBox.warning(self, "Peak Flow", str(exc))
            return

        self._loading_case = True
        try:
            self.spinArea.setValue(area_m2 / 1_000_000.0)
            self.spinOutletLon.setValue(outlet_ll[0])
            self.spinOutletLat.setValue(outlet_ll[1])
            self.spinCentLon.setValue(centroid_ll[0])
            self.spinCentLat.setValue(centroid_ll[1])
        finally:
            self._loading_case = False
        self._sync_current_case()

        region = recommender.recommend_region(outlet_ll[0], outlet_ll[1])
        idx = self._selected_case_index()
        if idx >= 0:
            self._cases[idx]["recommended_region"] = region
        self._refresh_regional_recommendation()

    def _refresh_regional_recommendation(self):
        idx = self._selected_case_index()
        if idx < 0:
            return
        region = self._cases[idx].get("recommended_region")
        applicable = set(regional_methods.applicable(region))
        for mid, chk in self._method_enable_checks.items():
            base = regional_methods.label(mid)
            if region and mid in applicable and (regional_methods.REGISTRY[mid][2] is not None):
                chk.setText(f"{base}  (recommended for {region})")
            else:
                chk.setText(base)
        if region:
            self.lblRecommended.setText(f"Recommendation: outlet is in region '{region}'.")
        else:
            self.lblRecommended.setText("Recommendation: could not derive a region from outlet.")

    # ------------------------------------------------------------------
    # RFFE tab
    # ------------------------------------------------------------------
    def _build_rffe_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        row = QHBoxLayout()
        self.btnRunRffe = QPushButton("Run RFFE")
        self.btnRunRffe.clicked.connect(self._run_rffe)
        self.btnShowStations = QPushButton("Show 15 stations on map")
        self.btnShowStations.clicked.connect(self._show_rffe_stations)
        self.btnShowStations.setEnabled(False)
        self.btnOpenRffeSite = QPushButton("Open RFFE website")
        self.btnOpenRffeSite.setToolTip(
            "Open the official RFFE 2021 web app and copy this site's outlet, "
            "centroid and area to the clipboard. Paste them into the site's "
            "input boxes — the site cannot accept coordinates in the URL."
        )
        self.btnOpenRffeSite.clicked.connect(self._open_rffe_website)
        row.addWidget(self.btnRunRffe)
        row.addWidget(self.btnShowStations)
        row.addWidget(self.btnOpenRffeSite)
        row.addStretch()
        v.addLayout(row)

        self.lblRffeStatus = QLabel("Not run.")
        self.lblRffeStatus.setStyleSheet("color: #555;")
        self.lblRffeStatus.setWordWrap(True)
        v.addWidget(self.lblRffeStatus)

        self.tblRffe = QTableWidget(len(AEPS), 4)
        self.tblRffe.setHorizontalHeaderLabels(["AEP", "Flow (m³/s)", "Lower 5%", "Upper 95%"])
        self.tblRffe.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, aep in enumerate(AEPS):
            self.tblRffe.setItem(i, 0, QTableWidgetItem(aep))
        v.addWidget(self.tblRffe, stretch=1)
        return w

    def _run_rffe(self):
        idx = self._selected_case_index()
        if idx < 0:
            return
        self._sync_current_case()

        lon = self.spinOutletLon.value()
        lat = self.spinOutletLat.value()
        area = self.spinArea.value()
        clon = self.spinCentLon.value() or None
        clat = self.spinCentLat.value() or None

        problems = []
        if area <= 0.1:
            problems.append(f"Area must be > 0.1 km² (got {area}).")
        if not (110.0 <= lon <= 155.0):
            problems.append(f"Outlet longitude {lon} is outside Australia (110–155°E).")
        if not (-45.0 <= lat <= -9.0):
            problems.append(f"Outlet latitude {lat} is outside Australia (-45 to -9°S).")
        if problems:
            QMessageBox.warning(
                self, "Peak Flow — RFFE",
                "Cannot run RFFE:\n\n• " + "\n• ".join(problems) +
                "\n\nUse 'Auto-fill from Layers' on the Inputs tab, or edit the spinboxes directly."
            )
            return

        self.btnRunRffe.setEnabled(False)
        self.lblRffeStatus.setText(
            f"Querying RFFE 2021 (outlet {lat:.4f}, {lon:.4f}, area {area:g} km²)…"
        )
        self._rffe_thread = _RffeThread(lon, lat, area, clon, clat)
        self._rffe_thread.done.connect(self._on_rffe_done)
        self._rffe_thread.failed.connect(self._on_rffe_failed)
        self._rffe_thread.finished.connect(lambda: self.btnRunRffe.setEnabled(True))
        self._rffe_thread.start()

    def _on_rffe_failed(self, msg):
        self.lblRffeStatus.setText("Failed.")
        QMessageBox.critical(self, "Peak Flow — RFFE", msg)

    def _on_rffe_done(self, result):
        site, models, region, polygon = result
        from .core.rffe_bridge import flatten_recommended
        rec_name, flat = flatten_recommended(models)
        idx = self._selected_case_index()
        if idx >= 0:
            case = self._cases[idx]
            case["rffe_result"] = flat
            case["rffe_region_raw"] = region
            case["rffe_site_raw"] = site
            case["rffe_models_raw"] = models
            case["rffe_polygon_raw"] = polygon
            case["rffe_recommended_model"] = rec_name
        self.lblRffeStatus.setText(
            f"{site.get('Basin', '?')} | {site.get('Region Name', '?')} | model: {rec_name}"
        )
        for i, aep in enumerate(AEPS):
            v = flat.get(aep, {})
            self.tblRffe.setItem(i, 1, _num_item(v.get("flow")))
            self.tblRffe.setItem(i, 2, _num_item(v.get("lower")))
            self.tblRffe.setItem(i, 3, _num_item(v.get("upper")))
        self.btnShowStations.setEnabled(True)
        self._refresh_results_and_plot()

    def _open_rffe_website(self):
        """Open the RFFE 2021 site in the default browser and drop this
        catchment's outlet/centroid/area on the clipboard. The Dash app
        can't accept coordinates in the URL, so pasting into its input
        boxes is the closest thing to a URL hand-off. Mirrors
        01_Rffe_plugin/gui/rffe_dialog.py::_open_website."""
        self._sync_current_case()
        lon = self.spinOutletLon.value()
        lat = self.spinOutletLat.value()
        area = self.spinArea.value()
        clon = self.spinCentLon.value() or lon
        clat = self.spinCentLat.value() or (lat - 0.07 if lat else 0.0)

        if lon or lat:
            text = (f"Outlet lon {lon:.6f}\tlat {lat:.6f}\n"
                    f"Centroid lon {clon:.6f}\tlat {clat:.6f}\n"
                    f"Area {area:g} km2")
            QApplication.clipboard().setText(text)
            self.lblRffeStatus.setText(
                "Opened the RFFE website. Coordinates copied to the clipboard — "
                "the site can't take them in the URL, so paste them into its "
                "Outlet/Centroid boxes."
            )
        QDesktopServices.openUrl(QUrl(RFFE_WEBSITE_URL))

    def _show_rffe_stations(self):
        """Build the three styled layers RFFE users expect:
          {name} catchment  — the fitted catchment polygon
          {name} points     — outlet + centroid, with headline flows
          {name} gauges     — the 15 nearest gauged stations, graduated by
                              distance (green ≤100 km → red >1000 km)
        Delegates to the vendored `build_layers` from 01_Rffe_plugin so the
        symbology matches that plugin exactly."""
        if not QGIS_AVAILABLE:
            QMessageBox.information(self, "Peak Flow", "Requires QGIS runtime.")
            return
        idx = self._selected_case_index()
        if idx < 0:
            return
        case = self._cases[idx]
        site = case.get("rffe_site_raw")
        models = case.get("rffe_models_raw")
        region = case.get("rffe_region_raw")
        polygon = case.get("rffe_polygon_raw")
        if not (site and models and region and polygon):
            QMessageBox.information(self, "Peak Flow", "Run RFFE first.")
            return

        from .core.rffe_bridge import (FFA_LAYER_SUFFIX, build_layers,
                                        catchments_in_geology,
                                        compute_rock_alluvial,
                                        filter_region_top_n)
        region_top15 = filter_region_top_n(region, n=15)
        try:
            layers = build_layers(site, models, region_top15, polygon,
                                  name=case["name"], out_dir=None)
        except Exception as exc:
            QMessageBox.critical(self, "Peak Flow", f"Could not build layers:\n{exc}")
            return

        from qgis.core import QgsProject
        for lyr in layers:
            QgsProject.instance().addMapLayer(lyr)
        status_extra = f"  Added {len(layers)} layer(s) to the project."

        # Offer to split the 15 station catchments into rock / alluvial %,
        # but only when at least one of them actually overlaps the NT geology
        # coverage — silent no-op elsewhere.
        ffa = next((l for l in layers
                    if l.name().endswith(FFA_LAYER_SUFFIX)), None)
        if ffa is not None and catchments_in_geology(ffa):
            answer = QMessageBox.question(
                self, "Rock / alluvial proportion",
                "One or more of the 15 station catchments fall within the NT "
                "geology coverage. Calculate the rock and alluvial "
                "(unconsolidated) proportion for each of those catchments?\n\n"
                "This can take a minute.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                from qgis.PyQt.QtCore import Qt
                self.setCursor(Qt.WaitCursor)
                try:
                    n = compute_rock_alluvial(ffa)
                    status_extra += f"  Rock/alluvial computed for {n} catchment(s)."
                except Exception as exc:                  # noqa: BLE001
                    QMessageBox.warning(self, "Peak Flow",
                                        f"Rock/alluvial failed:\n{exc}")
                finally:
                    self.unsetCursor()

        self.lblRffeStatus.setText(self.lblRffeStatus.text() + status_extra)

    # ------------------------------------------------------------------
    # Regional method tabs — one tab per method
    # ------------------------------------------------------------------
    def _build_method_tab(self, method_id):
        """Return a QWidget containing this method's inputs + Run button +
        result table. Each regional method gets its own tab; the tab is
        shown only when the method is ticked on the Inputs tab."""
        label = regional_methods.label(method_id)
        outer = QWidget()
        outer_l = QVBoxLayout(outer)
        header = QLabel(f"<b>{label}</b>")
        outer_l.addWidget(header)

        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)

        widgets = {}  # populated per method

        if method_id == "arr1987":
            desc = QLabel(
                "Q_Y = 0.278 × C_Y × I(tc, Y) × A,  C_Y = C10 × FF_Y.  "
                "FF factors: 0.34/0.70/1.00/1.28/1.62/1.91 for 50%/20%/10%/5%/2%/1% AEP."
            )
            desc.setWordWrap(True); desc.setStyleSheet("color: #555;")
            layout.addWidget(desc)

            form = QFormLayout()
            widgets["c10"] = _spin(0, 1, 3, step=0.05)
            form.addRow("C10 (runoff coefficient):", widgets["c10"])
            itc_row = QHBoxLayout()
            widgets["itc"] = {}
            for ari in (2, 5, 10, 20, 50, 100):
                itc_row.addWidget(QLabel(f"{ari}y"))
                sp = _spin(0, 500, 2, max_width=70)
                widgets["itc"][ari] = sp
                itc_row.addWidget(sp)
            form.addRow("I(tc, ARI) mm/hr:", self._wrap_layout(itc_row))
            layout.addLayout(form)

        elif method_id == "flavell":
            desc = QLabel(
                "Regional formulas by WA sub-region: Pilbara / Goldfields Leinster / "
                "Wheatbelt / Kimberley. Reference: Flavell (2012), WA_Regional_method.xlsx."
            )
            desc.setWordWrap(True); desc.setStyleSheet("color: #555;")
            layout.addWidget(desc)

            form = QFormLayout()
            widgets["subregion"] = QComboBox()
            widgets["subregion"].addItems(regional_methods.FLAVELL_SUBREGIONS)
            form.addRow("Sub-region:", widgets["subregion"])
            widgets["stream_length_km"] = _spin(0, 10000, 3, suffix=" km")
            form.addRow("Stream length L:", widgets["stream_length_km"])
            widgets["slope_m_per_km"] = _spin(0, 100, 4, suffix=" m/km")
            form.addRow("Equal-area slope Se:", widgets["slope_m_per_km"])
            widgets["ifd_r12_2yr"] = _spin(0, 500, 2, suffix=" mm")
            form.addRow("R12(2yr) rainfall (Wheatbelt):", widgets["ifd_r12_2yr"])
            widgets["ifd_r24_10yr"] = _spin(0, 500, 2, suffix=" mm")
            form.addRow("R24(10yr) rainfall (Kimberley):", widgets["ifd_r24_10yr"])
            layout.addLayout(form)

        elif method_id == "davies_yip":
            desc = QLabel(
                "Q_ARI = X1 × A^X2 × I1hr^X3 × FF.  Small (≤1000 km²) uses I1hr@2yr; "
                "Medium/Large (>1000 km²) use I1hr@50yr. Reference: Davies & Yip (2014)."
            )
            desc.setWordWrap(True); desc.setStyleSheet("color: #555;")
            layout.addWidget(desc)

            form = QFormLayout()
            widgets["ifd_i1hr_2yr"] = _spin(0, 500, 2, suffix=" mm/hr")
            form.addRow("I(1hr, 2yr):", widgets["ifd_i1hr_2yr"])
            widgets["ifd_i1hr_50yr"] = _spin(0, 500, 2, suffix=" mm/hr")
            form.addRow("I(1hr, 50yr):", widgets["ifd_i1hr_50yr"])
            layout.addLayout(form)

        elif method_id == "northfield":
            desc = QLabel(
                "MAF (m³/s) = 2.998 × Area^0.559;  Q_AEP = Normalised Discharge × MAF. "
                "Applicable to ungauged arid catchments in NT/SA (MAR ≤ 350 mm, Area ≤ 1000 km²). "
                "Reference: Northfield, Craig & Hill (2021)."
            )
            desc.setWordWrap(True); desc.setStyleSheet("color: #555;")
            layout.addWidget(desc)
            # No extra inputs needed — area-only.

        run_row = QHBoxLayout()
        btn = QPushButton(f"Run {label}")
        btn.clicked.connect(lambda _=False, m=method_id: self._run_one_method(m))
        run_row.addWidget(btn); run_row.addStretch()
        layout.addLayout(run_row)

        table = QTableWidget(len(AEPS), 2)
        table.setHorizontalHeaderLabels(["AEP", "Peak Flow (m³/s)"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, aep in enumerate(AEPS):
            table.setItem(i, 0, QTableWidgetItem(aep))
        layout.addWidget(table)

        # Wire signal for input changes → save into current case
        for key, w in widgets.items():
            if isinstance(w, dict):
                for sub in w.values():
                    sub.valueChanged.connect(self._sync_current_case)
            elif isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self._sync_current_case)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(lambda *_: self._sync_current_case())

        outer_l.addWidget(group)
        outer_l.addStretch()

        self._method_sections[method_id] = {
            "tab": outer, "widgets": widgets, "result_table": table, "button": btn,
        }
        return _make_scroll(outer)

    def _method_context(self, case):
        """Build the compute-context dict for a method call from a case."""
        return {
            "lon": case.get("outlet_lon"),
            "lat": case.get("outlet_lat"),
            "area_km2": case.get("area_km2"),
            "centroid_lon": case.get("centroid_lon"),
            "centroid_lat": case.get("centroid_lat"),
            "region": case.get("recommended_region"),
            "stream_length_km": case.get("stream_length_km"),
            "slope_m_per_km": case.get("slope_m_per_km"),
            "subregion": case.get("subregion"),
            "c10": case.get("c10"),
            "ifd_itc_per_ari": case.get("ifd_itc_per_ari") or {},
            "ifd_i1hr_50yr": case.get("ifd_i1hr_50yr"),
            "ifd_i1hr_2yr": case.get("ifd_i1hr_2yr"),
            "ifd_r12_2yr": case.get("ifd_r12_2yr"),
            "ifd_r24_10yr": case.get("ifd_r24_10yr"),
        }

    def _run_one_method(self, method_id):
        idx = self._selected_case_index()
        if idx < 0:
            return
        self._sync_current_case()
        case = self._cases[idx]
        try:
            result = regional_methods.run(method_id, self._method_context(case))
        except Exception as exc:
            QMessageBox.warning(self, "Peak Flow", f"{method_id}: {exc}")
            return
        rr = case.setdefault("regional_results", {})
        rr[method_id] = result
        case["regional_methods"] = self._selected_regional_methods()

        table = self._method_sections[method_id]["result_table"]
        for i, aep in enumerate(AEPS):
            table.setItem(i, 1, _num_item(result.get(aep)))
        self._refresh_results_and_plot()

    # ------------------------------------------------------------------
    # RORB tab
    # ------------------------------------------------------------------
    def _build_rorb_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        row = QHBoxLayout()
        self.editRorbFolder = QLineEdit()
        self.editRorbFolder.setPlaceholderText("Folder containing *_aepN_du*minTPnn.out files")
        btn_browse = QPushButton("Browse…"); btn_browse.clicked.connect(self._browse_rorb)
        btn_scan = QPushButton("Scan & Aggregate"); btn_scan.clicked.connect(self._scan_rorb)
        row.addWidget(self.editRorbFolder, stretch=1); row.addWidget(btn_browse); row.addWidget(btn_scan)
        v.addLayout(row)

        self.lblRorbStatus = QLabel(""); v.addWidget(self.lblRorbStatus)

        self.tblRorb = QTableWidget(len(AEPS), 4)
        self.tblRorb.setHorizontalHeaderLabels(
            ["AEP", "Mean Peak (m³/s)", "Critical Duration (min)", "# TPs"]
        )
        self.tblRorb.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, aep in enumerate(AEPS):
            self.tblRorb.setItem(i, 0, QTableWidgetItem(aep))
        v.addWidget(self.tblRorb, stretch=1)
        return w

    def _browse_rorb(self):
        d = QFileDialog.getExistingDirectory(self, "RORB output folder", self.editRorbFolder.text() or "")
        if d:
            self.editRorbFolder.setText(d); self._sync_current_case()

    def _scan_rorb(self):
        folder = self.editRorbFolder.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Peak Flow", "Pick a valid RORB output folder.")
            return
        rows = rorb_parser.scan_folder(Path(folder))
        if not rows:
            self.lblRorbStatus.setText("No *_aepN_du*_tpNN.out files found.")
            return
        agg = rorb_parser.aggregate_mean_per_aep(rows)
        idx = self._selected_case_index()
        if idx >= 0:
            c = self._cases[idx]
            c["rorb_result"] = agg; c["rorb_detail"] = rows; c["rorb_folder"] = folder
        self.lblRorbStatus.setText(f"Parsed {len(rows)} .out files across {len(agg)} AEPs.")
        for i, aep in enumerate(AEPS):
            info = agg.get(aep, {})
            self.tblRorb.setItem(i, 1, _num_item(info.get("mean_peak")))
            self.tblRorb.setItem(i, 2, _num_item(info.get("critical_duration_min")))
            self.tblRorb.setItem(i, 3, _num_item(info.get("n_tp")))
        self._refresh_results_and_plot()

    # ------------------------------------------------------------------
    # Results & Plot tab
    # ------------------------------------------------------------------
    def _build_results_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        splitter = QSplitter(Qt.Vertical); splitter.setChildrenCollapsible(False)

        top = QWidget(); tl = QVBoxLayout(top)
        self.tblResults = QTableWidget(len(AEPS), 1)
        self.tblResults.setHorizontalHeaderLabels(["AEP"])
        for i, aep in enumerate(AEPS):
            self.tblResults.setItem(i, 0, QTableWidgetItem(aep))
        self.tblResults.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tl.addWidget(self.tblResults)

        er = QHBoxLayout(); er.addStretch()
        b1 = QPushButton("Export CSV…"); b1.clicked.connect(self._export_results_csv)
        b2 = QPushButton("Copy to Clipboard"); b2.clicked.connect(self._copy_results)
        er.addWidget(b1); er.addWidget(b2); tl.addLayout(er)
        splitter.addWidget(top)

        bot = QWidget(); bl = QVBoxLayout(bot)
        self._plot_fig = Figure(figsize=(6, 4))
        self._plot_canvas = FigureCanvas(self._plot_fig)
        self._plot_ax = self._plot_fig.add_subplot(111)
        bl.addWidget(self._plot_canvas, stretch=1)

        self.tblStyle = QTableWidget(0, 4)
        self.tblStyle.setHorizontalHeaderLabels(["Series", "Color", "Line style", "Marker"])
        self.tblStyle.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tblStyle.setMaximumHeight(180)
        bl.addWidget(self.tblStyle)
        splitter.addWidget(bot)
        splitter.setSizes([250, 500])
        v.addWidget(splitter)
        return w

    def _refresh_results_and_plot(self):
        idx = self._selected_case_index()
        if idx < 0:
            self._render_results_table({}); self._redraw_plot({}, {}); return
        case = self._cases[idx]
        series = _collect_case_series(case)
        styles = _ensure_styles(case, series.keys())
        case["plot_style"] = styles
        self._render_results_table(series)
        self._render_style_editor(series.keys(), styles)
        self._redraw_plot(series, styles)

    def _render_results_table(self, series):
        names = list(series.keys())
        self.tblResults.setColumnCount(1 + len(names))
        self.tblResults.setHorizontalHeaderLabels(["AEP"] + names)
        for i, aep in enumerate(AEPS):
            self.tblResults.setItem(i, 0, QTableWidgetItem(aep))
            for j, name in enumerate(names, start=1):
                self.tblResults.setItem(i, j, _num_item(series[name].get(aep)))
        self.tblResults.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _render_style_editor(self, names, styles):
        self.tblStyle.blockSignals(True)
        self.tblStyle.setRowCount(0)
        for name in names:
            row = self.tblStyle.rowCount()
            self.tblStyle.insertRow(row)
            self.tblStyle.setItem(row, 0, QTableWidgetItem(name))
            btn = QPushButton()
            btn.setStyleSheet(f"background: {styles[name]['color']};")
            btn.clicked.connect(lambda _=False, n=name, b=btn: self._pick_color(n, b))
            self.tblStyle.setCellWidget(row, 1, btn)
            cmb_ls = QComboBox(); cmb_ls.addItems(plot_utils.LINESTYLES)
            cmb_ls.setCurrentText(styles[name]["linestyle"])
            cmb_ls.currentTextChanged.connect(lambda v, n=name: self._on_style(n, "linestyle", v))
            self.tblStyle.setCellWidget(row, 2, cmb_ls)
            cmb_mk = QComboBox(); cmb_mk.addItems(plot_utils.MARKERS)
            cmb_mk.setCurrentText(styles[name]["marker"])
            cmb_mk.currentTextChanged.connect(lambda v, n=name: self._on_style(n, "marker", v))
            self.tblStyle.setCellWidget(row, 3, cmb_mk)
        self.tblStyle.blockSignals(False)

    def _pick_color(self, name, button):
        idx = self._selected_case_index()
        if idx < 0:
            return
        cur = self._cases[idx]["plot_style"][name]["color"]
        c = QColorDialog.getColor(QColor(cur), self, f"Color for {name}")
        if c.isValid():
            hx = c.name()
            self._cases[idx]["plot_style"][name]["color"] = hx
            button.setStyleSheet(f"background: {hx};")
            self._redraw_plot_only()

    def _on_style(self, name, key, value):
        idx = self._selected_case_index()
        if idx < 0:
            return
        self._cases[idx]["plot_style"][name][key] = value
        self._redraw_plot_only()

    def _redraw_plot_only(self):
        idx = self._selected_case_index()
        if idx < 0:
            return
        case = self._cases[idx]
        series = _collect_case_series(case)
        self._redraw_plot(series, case.get("plot_style", {}))

    def _redraw_plot(self, series, styles):
        ax = self._plot_ax
        ax.clear()
        aep_values = [float(a.rstrip("%")) for a in AEPS]
        for name, values in series.items():
            xs, ys = [], []
            for x, aep in zip(aep_values, AEPS):
                y = values.get(aep)
                if y is None:
                    continue
                xs.append(x); ys.append(y)
            if not xs:
                continue
            s = styles.get(name, plot_utils.default_style(name, 0))
            mk = s.get("marker", "o"); mk = None if mk == "none" else mk
            ax.plot(xs, ys, label=name, color=s.get("color", "#333"),
                    linestyle=s.get("linestyle", "-"), marker=mk,
                    linewidth=1.6, markersize=5)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("AEP (%)"); ax.set_ylabel("Peak flow (m³/s)")
        ax.invert_xaxis()
        ax.grid(True, which="both", linestyle=":", alpha=0.5)
        if series:
            ax.legend(fontsize=8, loc="best")
        self._plot_canvas.draw()

    def _export_results_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Results CSV", "peak_flows.csv", "CSV Files (*.csv)")
        if not path:
            return
        idx = self._selected_case_index()
        series = _collect_case_series(self._cases[idx]) if idx >= 0 else {}
        import csv
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f); w.writerow(["AEP"] + list(series.keys()))
            for aep in AEPS:
                w.writerow([aep] + [series[n].get(aep, "") for n in series])

    def _copy_results(self):
        idx = self._selected_case_index()
        series = _collect_case_series(self._cases[idx]) if idx >= 0 else {}
        lines = ["AEP\t" + "\t".join(series.keys())]
        for aep in AEPS:
            lines.append(aep + "\t" + "\t".join(str(series[n].get(aep, "")) for n in series))
        QApplication.clipboard().setText("\n".join(lines))

    # ==================================================================
    # Case management
    # ==================================================================
    def _empty_case(self):
        return {
            "id": None, "name": "",
            "catchment_layer_id": "", "catchment_layer_name": "", "catchment_feature_id": 0,
            "outlet_layer_id": "", "outlet_layer_name": "", "outlet_feature_id": 0,
            "area_km2": None, "outlet_lon": None, "outlet_lat": None,
            "centroid_lon": None, "centroid_lat": None,
            "rffe_enabled": True, "regional_methods": [], "rorb_enabled": False,
            "rorb_folder": "", "recommended_region": None,
            "stream_length_km": None, "slope_m_per_km": None, "subregion": "",
            "c10": None, "ifd_itc_per_ari": {}, "ifd_i1hr_50yr": None,
            "ifd_i1hr_2yr": None, "ifd_r12_2yr": None, "ifd_r24_10yr": None,
            "rffe_result": None, "rffe_region_raw": None, "rffe_recommended_model": None,
            "regional_results": {}, "rorb_result": None, "rorb_detail": None,
            "plot_style": {},
        }

    def _add_case(self):
        case = self._empty_case()
        case["id"] = self._next_case_id; self._next_case_id += 1
        case["name"] = f"Case {self._next_case_number}"; self._next_case_number += 1
        self._cases.append(case); self._case_by_id[case["id"]] = case
        item = QListWidgetItem(case["name"])
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setData(Qt.UserRole, case["id"])
        self.caseList.addItem(item); self.caseList.setCurrentRow(len(self._cases) - 1)

    def _rename_case(self):
        idx = self._selected_case_index()
        if idx < 0:
            return
        new, ok = QInputDialog.getText(self, "Rename Case", "Name:", text=self._cases[idx]["name"])
        if ok and new.strip():
            self._cases[idx]["name"] = new.strip()
            self.caseList.item(idx).setText(new.strip())

    def _delete_case(self):
        idx = self._selected_case_index()
        if idx < 0:
            return
        if len(self._cases) == 1:
            QMessageBox.information(self, "Peak Flow", "At least one case is required.")
            return
        del self._case_by_id[self._cases[idx]["id"]]
        del self._cases[idx]
        self.caseList.takeItem(idx)

    def _on_case_item_renamed(self, item):
        case = self._case_by_id.get(item.data(Qt.UserRole))
        if case is None:
            return
        new = item.text().strip()
        if not new:
            item.setText(case["name"]); return
        case["name"] = new

    def _on_case_reordered(self, *_):
        self._cases = [
            self._case_by_id[self.caseList.item(i).data(Qt.UserRole)]
            for i in range(self.caseList.count())
        ]

    def _selected_case_index(self):
        return self.caseList.currentRow()

    def _on_case_selected(self, row):
        if row < 0 or row >= len(self._cases):
            return
        self._load_case_into_fields(self._cases[row])

    # ------------------------------------------------------------------
    # Field <-> case syncing
    # ------------------------------------------------------------------
    def _sync_current_case(self):
        if self._loading_case:
            return
        idx = self._selected_case_index()
        if idx < 0:
            return
        c = self._cases[idx]
        c["area_km2"] = self.spinArea.value() or None
        c["outlet_lon"] = self.spinOutletLon.value() or None
        c["outlet_lat"] = self.spinOutletLat.value() or None
        c["centroid_lon"] = self.spinCentLon.value() or None
        c["centroid_lat"] = self.spinCentLat.value() or None
        c["catchment_feature_id"] = self.spinCatchFid.value()
        c["outlet_feature_id"] = self.spinOutletFid.value()
        c["rffe_enabled"] = self.chkRffe.isChecked()
        c["rorb_enabled"] = self.chkRorb.isChecked()
        c["regional_methods"] = self._selected_regional_methods()
        c["rorb_folder"] = self.editRorbFolder.text().strip()

        if QGIS_AVAILABLE:
            cl = self.cmbCatchment.currentLayer(); ol = self.cmbOutletLayer.currentLayer()
            if cl is not None:
                c["catchment_layer_id"] = cl.id(); c["catchment_layer_name"] = cl.name()
            if ol is not None:
                c["outlet_layer_id"] = ol.id(); c["outlet_layer_name"] = ol.name()

        # Method-section widgets → case
        arr = self._method_sections.get("arr1987", {}).get("widgets", {})
        if arr:
            c["c10"] = arr["c10"].value() or None
            c["ifd_itc_per_ari"] = {
                str(ari): sp.value() for ari, sp in arr["itc"].items() if sp.value() > 0
            }

        fla = self._method_sections.get("flavell", {}).get("widgets", {})
        if fla:
            c["subregion"] = fla["subregion"].currentText()
            c["stream_length_km"] = fla["stream_length_km"].value() or None
            c["slope_m_per_km"] = fla["slope_m_per_km"].value() or None
            c["ifd_r12_2yr"] = fla["ifd_r12_2yr"].value() or None
            c["ifd_r24_10yr"] = fla["ifd_r24_10yr"].value() or None

        dy = self._method_sections.get("davies_yip", {}).get("widgets", {})
        if dy:
            c["ifd_i1hr_2yr"] = dy["ifd_i1hr_2yr"].value() or None
            c["ifd_i1hr_50yr"] = dy["ifd_i1hr_50yr"].value() or None

    def _load_case_into_fields(self, case):
        self._loading_case = True
        try:
            def _sv(spin, v):
                spin.setValue(v if v is not None else 0)
            _sv(self.spinArea, case.get("area_km2"))
            _sv(self.spinOutletLon, case.get("outlet_lon"))
            _sv(self.spinOutletLat, case.get("outlet_lat"))
            _sv(self.spinCentLon, case.get("centroid_lon"))
            _sv(self.spinCentLat, case.get("centroid_lat"))
            self.spinCatchFid.setValue(int(case.get("catchment_feature_id") or 0))
            self.spinOutletFid.setValue(int(case.get("outlet_feature_id") or 0))
            self.chkRffe.setChecked(bool(case.get("rffe_enabled")))
            self.chkRorb.setChecked(bool(case.get("rorb_enabled")))
            self.chkRegional.setChecked(bool(case.get("regional_methods")))
            self.regionalMethodsGroup.setEnabled(self.chkRegional.isChecked())
            for mid, chk in self._method_enable_checks.items():
                chk.setChecked(mid in (case.get("regional_methods") or []))
            self.editRorbFolder.setText(case.get("rorb_folder") or "")

            arr = self._method_sections.get("arr1987", {}).get("widgets", {})
            if arr:
                _sv(arr["c10"], case.get("c10"))
                itc = case.get("ifd_itc_per_ari") or {}
                for ari, sp in arr["itc"].items():
                    _sv(sp, itc.get(str(ari)))
            fla = self._method_sections.get("flavell", {}).get("widgets", {})
            if fla:
                fla["subregion"].setCurrentText(case.get("subregion") or "")
                _sv(fla["stream_length_km"], case.get("stream_length_km"))
                _sv(fla["slope_m_per_km"], case.get("slope_m_per_km"))
                _sv(fla["ifd_r12_2yr"], case.get("ifd_r12_2yr"))
                _sv(fla["ifd_r24_10yr"], case.get("ifd_r24_10yr"))
            dy = self._method_sections.get("davies_yip", {}).get("widgets", {})
            if dy:
                _sv(dy["ifd_i1hr_2yr"], case.get("ifd_i1hr_2yr"))
                _sv(dy["ifd_i1hr_50yr"], case.get("ifd_i1hr_50yr"))
        finally:
            self._loading_case = False

        self._update_tab_visibility()
        self._refresh_regional_recommendation()
        self._refresh_size_class()
        # Populate result tables
        rffe = case.get("rffe_result") or {}
        for i, aep in enumerate(AEPS):
            v = rffe.get(aep, {}) if rffe else {}
            self.tblRffe.setItem(i, 1, _num_item(v.get("flow") if rffe else None))
            self.tblRffe.setItem(i, 2, _num_item(v.get("lower") if rffe else None))
            self.tblRffe.setItem(i, 3, _num_item(v.get("upper") if rffe else None))
        self.btnShowStations.setEnabled(bool(case.get("rffe_region_raw")))

        regional_results = case.get("regional_results") or {}
        for mid, section in self._method_sections.items():
            tbl = section["result_table"]
            data = regional_results.get(mid) or {}
            for i, aep in enumerate(AEPS):
                tbl.setItem(i, 1, _num_item(data.get(aep)))

        rorb = case.get("rorb_result") or {}
        for i, aep in enumerate(AEPS):
            info = rorb.get(aep, {}) if rorb else {}
            self.tblRorb.setItem(i, 1, _num_item(info.get("mean_peak") if rorb else None))
            self.tblRorb.setItem(i, 2, _num_item(info.get("critical_duration_min") if rorb else None))
            self.tblRorb.setItem(i, 3, _num_item(info.get("n_tp") if rorb else None))
        self._refresh_results_and_plot()

    # ==================================================================
    # Project I/O
    # ==================================================================
    def _on_save_project(self):
        if self._current_project_path is None:
            self._on_save_project_as(); return
        try:
            export_project(self._current_project_path, self._cases)
        except (ImportError, PermissionError) as exc:
            QMessageBox.critical(self, "Peak Flow", str(exc))

    def _on_save_project_as(self):
        default = os.path.basename(self._current_project_path) if self._current_project_path else "peak_flow_project.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", default, "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            export_project(path, self._cases)
        except (ImportError, PermissionError) as exc:
            QMessageBox.critical(self, "Peak Flow", str(exc)); return
        self._set_project_path(path)

    def _on_import_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Project (.xlsx)", "", "Excel Files (*.xlsx)")
        if not path:
            return
        self._load_project(path)

    def _on_refresh_project(self):
        if self._current_project_path is not None:
            self._load_project(self._current_project_path)

    def _load_project(self, path):
        try:
            imported = import_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Peak Flow", f"Could not read project:\n{exc}")
            return
        if not imported:
            QMessageBox.information(self, "Peak Flow", "No cases found in that file.")
            return
        self.caseList.blockSignals(True)
        self.caseList.clear(); self.caseList.blockSignals(False)
        self._cases = []; self._case_by_id = {}
        for values in imported:
            case = self._empty_case(); case.update(values)
            case["id"] = self._next_case_id; self._next_case_id += 1
            self._next_case_number += 1
            self._cases.append(case); self._case_by_id[case["id"]] = case
            item = QListWidgetItem(case["name"])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(Qt.UserRole, case["id"])
            self.caseList.addItem(item)
        self._set_project_path(path)
        self.caseList.setCurrentRow(0)

    def _set_project_path(self, path):
        self._current_project_path = path
        name = os.path.splitext(os.path.basename(path))[0]
        self.labelProjectName.setText(name)
        self.btnRefresh.setEnabled(True)


# ==================================================================
# Helpers
# ==================================================================

def _spin(lo, hi, decimals, step=None, suffix="", max_width=None):
    s = QDoubleSpinBox()
    s.setRange(lo, hi); s.setDecimals(decimals)
    if step is not None:
        s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    if max_width is not None:
        s.setMaximumWidth(max_width)
    return s


def _make_scroll(widget):
    try:
        from qgis.PyQt.QtWidgets import QScrollArea
    except ImportError:
        from PyQt5.QtWidgets import QScrollArea
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    return sa


def _num_item(v):
    if v is None or v == "":
        return QTableWidgetItem("")
    try:
        item = QTableWidgetItem(f"{float(v):,.2f}")
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return item
    except (TypeError, ValueError):
        return QTableWidgetItem(str(v))


def _collect_case_series(case):
    out = {}
    rffe = case.get("rffe_result") or {}
    if rffe:
        out["RFFE_Recommended"] = {a: rffe.get(a, {}).get("flow") for a in AEPS}
        out["RFFE_lower"] = {a: rffe.get(a, {}).get("lower") for a in AEPS}
        out["RFFE_upper"] = {a: rffe.get(a, {}).get("upper") for a in AEPS}
    for mid, values in (case.get("regional_results") or {}).items():
        out[f"Regional_{mid}"] = {a: values.get(a) for a in AEPS}
    rorb = case.get("rorb_result") or {}
    if rorb:
        out["RORB_mean"] = {a: rorb.get(a, {}).get("mean_peak") for a in AEPS}
    return out


def _ensure_styles(case, series_names):
    styles = dict(case.get("plot_style") or {})
    counters = {"RFFE": 0, "Regional": 0, "RORB": 0, "Other": 0}
    for name in series_names:
        fam = plot_utils.family_of(name)
        idx = counters[fam]; counters[fam] += 1
        if name not in styles:
            styles[name] = plot_utils.default_style(name, idx)
    return {n: styles[n] for n in series_names if n in styles}


def _catchment_area_and_centroid(layer, feature_id):
    from qgis.core import (
        QgsCoordinateReferenceSystem, QgsCoordinateTransform,
        QgsDistanceArea, QgsProject,
    )
    feat = _get_feature(layer, feature_id)
    if feat is None:
        raise ValueError("Catchment layer has no features.")
    geom = feat.geometry()
    if geom is None or geom.isEmpty():
        raise ValueError("Catchment feature has no geometry.")

    da = QgsDistanceArea()
    da.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
    da.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
    area_m2 = da.measureArea(geom)

    centroid = geom.centroid().asPoint()
    xform = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
    )
    pt = xform.transform(centroid)
    return area_m2, (pt.x(), pt.y())


def _feature_lonlat(layer, feature_id):
    """Return (lon, lat) in WGS84 for a point-layer feature. Accepts both
    Point and MultiPoint geometries; for MultiPoint the first vertex is used."""
    from qgis.core import (
        QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
    )
    feat = _get_feature(layer, feature_id)
    if feat is None:
        raise ValueError("Point layer has no features.")
    geom = feat.geometry()
    if geom is None or geom.isEmpty():
        raise ValueError("Point feature has no geometry.")
    if geom.isMultipart():
        pts = geom.asMultiPoint()
        pt = pts[0] if pts else None
    else:
        pt = geom.asPoint()
    if pt is None:
        raise ValueError("Could not extract a point from the geometry.")
    xform = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
    )
    ll = xform.transform(pt)
    return (ll.x(), ll.y())


def _first_feature_ids(layer, limit=5):
    ids = []
    for f in layer.getFeatures():
        ids.append(f.id())
        if len(ids) >= limit:
            break
    return ids


def _get_feature(layer, feature_id):
    feat = layer.getFeature(int(feature_id))
    if feat.isValid():
        return feat
    for f in layer.getFeatures():
        return f
    return None


def _add_stations_memory_layer(header, rows, layer_name):
    from qgis.core import (
        QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
    )
    from qgis.PyQt.QtCore import QVariant

    lon_col = lat_col = None
    for i, name in enumerate(header):
        low = str(name).lower()
        if lon_col is None and ("lon" in low or "long" in low or "east" in low):
            lon_col = i
        if lat_col is None and ("lat" in low or "north" in low):
            lat_col = i
    if lon_col is None or lat_col is None:
        raise ValueError("RFFE station rows have no lon/lat columns to plot.")

    layer = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
    dp = layer.dataProvider()
    fields = []
    for i, name in enumerate(header):
        if i in (lon_col, lat_col):
            continue
        fields.append(QgsField(str(name)[:60] or f"f{i}", QVariant.String))
    dp.addAttributes(fields); layer.updateFields()

    for row in rows:
        try:
            lon = float(row[lon_col]); lat = float(row[lat_col])
        except (TypeError, ValueError):
            continue
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        attrs = [str(row[i]) for i in range(len(row)) if i not in (lon_col, lat_col)]
        feat.setAttributes(attrs)
        dp.addFeature(feat)
    layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    return layer
