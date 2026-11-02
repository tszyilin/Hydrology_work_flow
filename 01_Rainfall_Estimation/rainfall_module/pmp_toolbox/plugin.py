"""QGIS plugin entry point: the toolbar action, the dock, and the three tabs.

Registration and the project file.  Everything that computes or draws lives in
``tabs`` and ``core``; this module puts a checkable button on the toolbar, hangs
a floating dock off it, and takes both down cleanly on unload.

The dock follows the Drain Design Toolbox: floating and hidden at first, with
the action and the dock's visibility bound to each other so the button always
reflects whether the panel is up, whichever of the two the user operated.

The **Project** row sits above the tabs rather than inside each one, because a
project here is a single ``.xlsx`` covering all three methods.  Drain Design
puts that row in every tab; it can, because its projects are per-tab.
"""

from __future__ import annotations

from pathlib import Path

from .qt_compat import (
    QAction,
    QDockWidget,
    QFileDialog,
    QIcon,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    Qt,
)

MENU = "&PMP Toolbox"
DOCK_OBJECT_NAME = "PmpToolboxDock"

#: The key each tab's sheets are named after, and the order they are written.
TAB_KEYS = ("GSDM", "Areal GSDM", "GTSMR")


class PmpToolboxPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.tabs = None
        self.project = None
        self.preview = None
        self.gsdm_tab = None
        self.areal_tab = None
        self.gtsmr_tab = None

    # ------------------------------------------------------- QGIS plugin API

    def initGui(self):  # noqa: N802 -- name mandated by the QGIS plugin API
        self.action = QAction(
            QIcon(str(Path(__file__).resolve().parent / "icon.png")),
            "PMP Toolbox",
            self.iface.mainWindow(),
        )
        self.action.setCheckable(True)
        self.action.toggled.connect(self._on_action_toggled)
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.preview is not None:
            self.preview.close()
            self.preview = None
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
            self.tabs = None
            self.project = None
            self.gsdm_tab = self.areal_tab = self.gtsmr_tab = None

    # ------------------------------------------------------------------ dock

    def _build_dock(self):
        from . import __version__
        from .tabs.areal_gsdm_tab import ArealGsdmTab
        from .tabs.common import ProjectPanel, apply_style
        from .tabs.gsdm_tab import GsdmTab
        from .tabs.gtsmr_tab import GtsmrTab

        self.tabs = QTabWidget()
        self.gsdm_tab = GsdmTab()
        self.areal_tab = ArealGsdmTab(self.iface, preview_owner=self)
        self.gtsmr_tab = GtsmrTab()

        self.tabs.addTab(self.gsdm_tab, "GSDM")
        self.tabs.addTab(self.areal_tab, "Areal GSDM")
        self.tabs.addTab(self.gtsmr_tab, "GTSMR / GSAM")
        self.tabs.setTabToolTip(0, "Catchment-average PMP depth, 0.25 to 6 hours.")
        self.tabs.setTabToolTip(
            1, "The GSDM Figure 6 storm template placed over the catchment."
        )
        self.tabs.setTabToolTip(2, "Long-duration PMP, 24 to 120 hours.")

        self.project = ProjectPanel()
        self.project.saveRequested.connect(self.save_project)
        self.project.saveAsRequested.connect(self.save_project_as)
        self.project.openRequested.connect(self.open_project)
        apply_style(self.project)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.project)
        layout.addWidget(self.tabs, stretch=1)

        # The version is in the title so it is obvious which build QGIS has
        # actually loaded -- reinstalling from ZIP does not replace an already
        # imported module until QGIS restarts.
        self.dock = QDockWidget(f"PMP Toolbox  v{__version__}", self.iface.mainWindow())
        self.dock.setObjectName(DOCK_OBJECT_NAME)
        self.dock.setWidget(container)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        # Floating by default: the tabs are wider than a comfortable docked
        # panel, and a docked default would squeeze the map on first open.
        self.dock.setFloating(True)
        self.dock.resize(980, 820)
        self.dock.setVisible(False)
        self.dock.visibilityChanged.connect(self._on_dock_visibility)

    def _on_action_toggled(self, checked: bool):
        if self.dock is None:
            self._build_dock()
        self.dock.setVisible(checked)
        if checked:
            self.dock.raise_()

    def _on_dock_visibility(self, visible: bool):
        # Closing the dock by its own X must leave the toolbar button unpressed,
        # or the next click would appear to do nothing.
        if self.action is not None and self.action.isChecked() != visible:
            self.action.blockSignals(True)
            self.action.setChecked(visible)
            self.action.blockSignals(False)

    # --------------------------------------------------------------- project

    def tab_pairs(self):
        """``(sheet key, tab)`` in the order the workbook writes them."""
        return list(
            zip(TAB_KEYS, (self.gsdm_tab, self.areal_tab, self.gtsmr_tab))
        )

    def save_project(self):
        """Save to the known path, or ask for one the first time."""
        if self.project is None:
            return
        path = self.project.path()
        if path is None:
            self.save_project_as()
            return
        self._write(path)

    def save_project_as(self):
        if self.project is None:
            return
        suggested = str(self.project.path() or "pmp_project.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self.dock, "Save PMP project", suggested, "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        self._write(path)

    def _write(self, path):
        from . import workbook

        try:
            workbook.save_project(
                path, self.tab_pairs(), project_name=Path(path).stem
            )
        except workbook.WorkbookError as exc:
            QMessageBox.warning(self.dock, "Could not save the project", str(exc))
            return
        self.project.set_path(path)
        self.iface.messageBar().pushInfo("PMP Toolbox", f"Project saved to {path}")

    def open_project(self):
        from . import workbook

        path, _ = QFileDialog.getOpenFileName(
            self.dock, "Open PMP project", "", "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        try:
            report = workbook.load_project(path, self.tab_pairs())
        except workbook.WorkbookError as exc:
            QMessageBox.warning(self.dock, "Could not open the project", str(exc))
            return

        self.project.set_path(path)
        loaded = ", ".join(f"{k}: {n}" for k, n in report["loaded"].items())
        message = f"Opened {Path(path).name} — cases restored ({loaded})."
        if report["missing"]:
            message += (
                "  No sheet for: " + ", ".join(report["missing"]) + "."
            )
        # Results are inputs' output, not something to trust from a file, so
        # say plainly that they need recomputing rather than leaving the tabs
        # looking half-run.
        message += "  Press Calculate to recompute results."
        self.iface.messageBar().pushInfo("PMP Toolbox", message)

    # --------------------------------------------------------------- preview

    def preview_window(self):
        """The live search window, created on first use and owned here.

        It outlives any one run and has to be closed on unload, which is why
        the Areal GSDM tab asks for it rather than making one of its own.
        """
        if self.preview is None:
            from .preview import SearchPreviewDialog

            self.preview = SearchPreviewDialog(self.iface.mainWindow())
        return self.preview
