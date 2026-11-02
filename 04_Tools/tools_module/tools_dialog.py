"""Stage 3 — Tools start page.

Lists the tools bundled with the suite. Clicking Launch opens the tool in
a floating QDockWidget that can be docked to any side of QGIS.

Adding a new tool = append one entry to ``TOOLS`` and write its
``ToolLauncher._launch_<key>`` method, which should hand its widget to
``_launch_dockable``. Tools are vendored under
``tools_module/<tool_name>/`` so they ship with the plugin zip. Every entry
in ``TOOLS`` also appears in the Processing Toolbox (see
``processing_provider.py``), so it is searchable there and in the locator.
"""
from __future__ import annotations

from ...qt_compat import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QObject,
    QPushButton,
    QScrollArea,
    Qt,
    QVBoxLayout,
    QWidget,
)

try:
    from qgis.PyQt.QtCore import QEvent
except ImportError:
    from PyQt5.QtCore import QEvent


class _DockCloseFilter(QObject):
    """Close the containing dock when the embedded dialog receives a Close
    event (e.g. the dialog's own Close button is clicked).

    Only ``QEvent.Close`` is handled on purpose. ``QEvent.Hide`` fires any
    time Qt reparents the widget — which happens on every float/dock drag —
    and closing the dock mid-reparent crashes Qt with a pure-virtual call
    (``_purecall`` in ``QDockWidget::event`` → ``QWidget::setParent``).
    """
    def __init__(self, dock):
        super().__init__(dock)
        self._dock = dock

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Close:
            self._dock.close()
        return False


# ── Tool registry ────────────────────────────────────────────────────
# ``key`` is the Processing algorithm id (``hydrology_suite:<key>``) and
# selects ``ToolLauncher._launch_<key>``. ``tags`` feed Processing search.
TOOLS = [
    {"key": "geology",
     "name": "Geology Calculator",
     "badge": "QGIS",
     "description":
        "Intersect a geology polygon layer with sub-catchment polygons "
        "and write a percentage-by-geology CSV. Opens as a floating "
        "window inside QGIS.",
     "tags": ["geology", "catchment", "intersect", "percentage", "proportion"]},
    {"key": "plotting",
     "name": "Plotting Tool",
     "badge": "QGIS",
     "description":
        "Paste-and-plot app: paste data from Excel, build one plot per "
        "case, and save projects to JSON. Opens as a floating window "
        "inside QGIS.",
     "tags": ["plot", "chart", "graph", "paste"]},
    {"key": "arf",
     "name": "ARF Calculator",
     "badge": "QGIS",
     "description":
        "Compute the ARR2019 Areal Reduction Factor for a catchment "
        "given region, area, duration and AEP. Single-value, batch "
        "CSV and ARF-vs-duration plot modes.",
     "tags": ["arf", "areal reduction factor", "arr2019", "rainfall", "aep"]},
    {"key": "raster_footprint",
     "name": "Raster Footprint",
     "badge": "QGIS",
     "description":
        "Extract the valid-data footprint of a GeoTIFF as a polygon "
        "shapefile.",
     "tags": ["raster", "footprint", "extent", "boundary", "polygonize"]},
    {"key": "ffa",
     "name": "Flood Frequency Analysis",
     "badge": "QGIS",
     "description":
        "Fit LP3/GEV/Gumbel/GPD to an annual-maximum series via "
        "L-moments or MLE. Produces return-period estimates with "
        "bootstrap confidence intervals and a probability plot.",
     "tags": ["ffa", "flood frequency", "lp3", "gev", "gumbel", "gpd",
              "l-moments", "annual maximum", "return period"]},
    {"key": "water_level",
     "name": "Water Level",
     "badge": "QGIS",
     "description":
        "Flood a DEM to a given water level and output the flooded "
        "area as a polygon layer. Optional extent restriction and "
        "inline colour/opacity.",
     "tags": ["water level", "flood", "inundation", "bathtub", "dem",
              "polygonize"]},
    # The window has a Results tab; the same calculation is also registered
    # as a Processing algorithm (hydrology_suite:cutfillvolume) for batch
    # runs and the Model Builder — see processing_provider.py.
    {"key": "cut_fill",
     "name": "Cut & Fill Volume",
     "badge": "QGIS",
     "description":
        "Stage-volume table for each polygon over a range of base heights "
        "(cut above, fill below, m3 and ML), matching the Global Mapper "
        "cut-and-fill report (same sample spacing and area model). Results "
        "tab per area, Save to Excel with a Summary sheet and one sheet per "
        "area.",
     "tags": ["cut", "fill", "volume", "storage", "stage", "earthworks",
              "megalitre", "excel"]},
    {"key": "silo",
     "name": "SILO Station Data",
     "badge": "QGIS",
     "description":
        "Search a SILO Patched Point station by number or name, download "
        "daily rainfall, temperature, evaporation and more, and split each "
        "value into Actual (observed) or Synthetic (interpolated), saved to "
        "Excel.",
     "tags": ["silo", "rainfall", "weather", "climate", "station",
              "evaporation", "temperature", "longpaddock"]},
    # Runs in its own Anaconda process, not inside QGIS — see
    # satellite_launcher.py for why.
    {"key": "satellite",
     "name": "Satellite Imagery Downloader",
     "badge": "External",
     "description":
        "Bulk-download Landsat and Sentinel-2 scenes (RGB, NDVI, raw bands) "
        "for the selected polygons. Opens in its own window so long "
        "downloads never slow down QGIS; needs Anaconda Python.",
     "tags": ["satellite", "landsat", "sentinel", "imagery", "ndvi",
              "download", "remote sensing"]},
    {"key": "satellite_load",
     "name": "Add Downloaded Imagery",
     "badge": "QGIS",
     "description":
        "Load every GeoTIFF in a downloader output folder into the map, "
        "one layer group per sub-folder (year).",
     "tags": ["satellite", "landsat", "sentinel", "imagery", "load",
              "geotiff", "raster"]},
]


def tool_by_key(key):
    for tool in TOOLS:
        if tool["key"] == key:
            return tool
    raise KeyError(key)


class ToolLauncher:
    """Opens the bundled tools. Shared by the Tools panel and the
    Processing Toolbox entries so a tool opens the same way from either.

    ``parent`` is the widget used for message boxes; it defaults to the
    QGIS main window.
    """
    def __init__(self, iface=None, parent=None):
        self.iface = iface
        self.parent = parent
        # Hold refs so launched dialogs / processes aren't GC'd.
        self._launched_dialogs = []
        self._launched_procs = []

    def _message_parent(self):
        if self.parent is not None:
            return self.parent
        return self.iface.mainWindow() if self.iface else None

    def launch(self, key):
        tool = tool_by_key(key)
        try:
            getattr(self, "_launch_" + key)()
        except Exception as exc:
            QMessageBox.critical(
                self._message_parent(), tool["name"],
                f"Could not launch:\n{type(exc).__name__}: {exc}"
            )

    # ── Dockable launcher plumbing ───────────────────────────────────
    def _launch_dockable(self, dialog, title):
        """Wrap ``dialog`` in a QDockWidget, add it to the QGIS main window
        and float it. The user can then drag the dock title bar to attach
        it to any side of QGIS, or leave it floating like before.
        Returns the dock.
        """
        if self.iface is not None:
            main_win = self.iface.mainWindow()
        else:
            main_win = self.parent.window() if self.parent is not None else None
        dock = QDockWidget(title, main_win)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        # Make sure the dialog is not styled as a top-level window once
        # it's embedded — flags set earlier (if any) are cleared.
        dialog.setWindowFlags(Qt.WindowType.Widget)
        dock.setWidget(dialog)
        dialog.installEventFilter(_DockCloseFilter(dock))
        # Keep the dock title in step with the tool, e.g. when the Plotting
        # Tool opens a project and puts its name in the title.
        dialog.windowTitleChanged.connect(dock.setWindowTitle)
        if self.iface is not None:
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)
        dock.show()
        # Hold refs so neither the dock nor its dialog is GC'd.
        self._launched_dialogs.append(dock)
        self._launched_dialogs.append(dialog)
        return dock

    # ── Launchers ────────────────────────────────────────────────────
    def _launch_geology(self):
        from .geology_calc.geo_proportion_dialog import GeoProportionDialog
        dlg = GeoProportionDialog()
        self._launch_dockable(dlg, "Geology Calculator")

    def _launch_arf(self):
        from .arf_calculator.arf_dialog import ArfDialog
        dlg = ArfDialog()
        self._launch_dockable(dlg, "ARR2019 ARF Calculator")

    def _launch_raster_footprint(self):
        from .raster_footprint.raster_footprint_dialog import RasterFootprintDialog
        dlg = RasterFootprintDialog(self.iface)
        self._launch_dockable(dlg, "Raster Footprint to Shapefile")

    def _launch_ffa(self):
        from .ffa.ffa_dialog import FfaDialog
        dlg = FfaDialog(self.iface)
        self._launch_dockable(dlg, "Flood Frequency Analysis")

    def _launch_water_level(self):
        from .flood_tool.flood_dialog import FloodDialog
        dlg = FloodDialog(self.iface)
        self._launch_dockable(dlg, "Water Level")

    def _launch_cut_fill(self):
        from .cut_fill.cut_fill_dialog import CutFillDialog
        dlg = CutFillDialog(self.iface)
        self._launch_dockable(dlg, "Cut & Fill Volume")

    def _launch_silo(self):
        from .silo.silo_dialog import SiloDialog
        dlg = SiloDialog(self.iface)
        self._launch_dockable(dlg, "SILO Station Data")

    def _launch_satellite(self):
        from . import satellite_launcher
        proc = satellite_launcher.launch(self.iface, self._message_parent())
        if proc is not None:
            self._launched_procs.append(proc)

    def _launch_satellite_load(self):
        from . import satellite_launcher
        satellite_launcher.load_results(self.iface, self._message_parent())

    def _launch_plotting(self):
        from .plotting_tool.plotting_tool import PlottingToolApp
        win = PlottingToolApp(embedded=True)
        dock = self._launch_dockable(win, "Plotting Tool")
        # The plot + data table need room; start the floating dock large.
        dock.resize(1400, 850)


class ToolsDialog(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setMinimumWidth(720)
        self._launcher = ToolLauncher(iface, parent=self)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        heading = QLabel("Stage 3 — Tools")
        font = heading.font(); font.setBold(True); font.setPointSize(font.pointSize() + 2)
        heading.setFont(font)
        root.addWidget(heading)

        subtitle = QLabel(
            "Pick a tool and click Launch. Each tool opens in a floating panel "
            "that you can dock to any side of QGIS."
        )
        subtitle.setStyleSheet("color: #555;")
        root.addWidget(subtitle)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); inner_l = QVBoxLayout(inner)
        for tool in TOOLS:
            inner_l.addWidget(self._tool_card(tool))
        inner_l.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    def _tool_card(self, tool):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background: #f5f8fa; border: 1px solid #b6c9d8; "
            "border-radius: 4px; padding: 4px; }"
        )
        row = QHBoxLayout(frame)
        text = QVBoxLayout()
        title = QLabel(f"<b>{tool['name']}</b>")
        badge = tool.get("badge")
        if badge:
            title.setText(f"<b>{tool['name']}</b>  <span style='color:#0d3d66;'>[{badge}]</span>")
        desc = QLabel(tool["description"])
        desc.setWordWrap(True); desc.setStyleSheet("color: #333;")
        text.addWidget(title); text.addWidget(desc)
        row.addLayout(text, 1)
        btn = QPushButton("Launch")
        btn.setFixedWidth(120)
        btn.clicked.connect(lambda _=False, k=tool["key"]: self._launcher.launch(k))
        row.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return frame
