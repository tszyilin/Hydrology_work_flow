"""Stage 1 — Rainfall Estimation panel.

Layout mirrors the Drain Design Toolbox: a Catchments sidebar on the left,
a shared LocationPicker at the top of the right panel, and three tabs
(IFD / Rainfall Station / PMP) below. Each tab reads and writes state onto
the currently selected Catchment, so switching catchments swaps the whole
inputs+results view without re-fetching.

The **PMP** tab hosts the vendored ``pmp_toolbox`` — its own three method
tabs still manage their own cases internally; per-catchment PMP integration
is a follow-up.
"""
from __future__ import annotations

import os
from pathlib import Path

from ...qt_compat import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    Qt,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .core.ifd_export import csv_filename, write_all_design_csv
from .ui.catchments_sidebar import CatchmentsSidebar
from .ui.ifd_tab import IfdTab
from .ui.location_picker import LocationPicker
from .ui.pmp_tab import PmpTab
from .ui.stations_tab import StationsTab

STYLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "style",
    "buttons.qss",
)


class RainfallDialog(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setMinimumWidth(880)
        self._build()
        self._apply_style()
        # Fire the first selection so the tabs render for Catchment 1.
        cat = self.sidebar.current()
        if cat is not None:
            self._on_catchment_changed(cat)

    def _build(self):
        root = QVBoxLayout(self)

        heading = QLabel("Stage 1 — Rainfall Estimation")
        font = heading.font(); font.setBold(True); font.setPointSize(font.pointSize() + 2)
        heading.setFont(font)
        root.addWidget(heading)

        splitter = QSplitter(Qt.Horizontal)

        # ── Left: catchments sidebar ─────────────────────────────────
        self.sidebar = CatchmentsSidebar(iface=self.iface)
        self.sidebar.setMinimumWidth(240)
        splitter.addWidget(self.sidebar)

        # ── Right: picker + tabs ─────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.picker = LocationPicker(iface=self.iface)
        right_layout.addWidget(self.picker)

        self.tabs = QTabWidget()
        self.ifd_tab = IfdTab()
        self.stations_tab = StationsTab()
        self.pmp_tab = PmpTab(iface=self.iface)
        self.tabs.addTab(self.ifd_tab, "IFD")
        self.tabs.addTab(self.stations_tab, "Rainfall Station")
        self.tabs.addTab(self.pmp_tab, "PMP")
        right_layout.addWidget(self.tabs, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # ── Wiring ────────────────────────────────────────────────────
        self.sidebar.catchment_changed.connect(self._on_catchment_changed)
        self.sidebar.batch_export_requested.connect(self._on_batch_export)
        self.picker.location_changed.connect(self._on_location_changed)

    def _apply_style(self):
        if os.path.isfile(STYLE_PATH):
            with open(STYLE_PATH, "r", encoding="utf-8") as h:
                self.setStyleSheet(h.read())

    # ------------------------------------------------------------------
    def _on_catchment_changed(self, cat):
        # Repaint the picker + every tab from the selected catchment.
        self.picker.load_from_catchment(cat)
        self.ifd_tab.set_catchment(cat)
        self.stations_tab.set_catchment(cat)
        self.pmp_tab.set_catchment(cat)

    def _on_location_changed(self, lat, lon, source):
        cat = self.sidebar.current()
        if cat is None:
            return
        cat.lat, cat.lon, cat.source = lat, lon, source
        # A location change invalidates cached results for that catchment.
        cat.ifd_result = None
        cat.stations_filtered = []
        self.sidebar.refresh_current_label()
        # Refresh tabs so they show 'ready to fetch' rather than stale data.
        self.ifd_tab.set_catchment(cat)
        self.stations_tab.set_catchment(cat)

    # ------------------------------------------------------------------
    def _on_batch_export(self):
        cats = [c for c in self.sidebar.catchments()
                if c.has_location() and c.ifd_result is not None]
        skipped = [c for c in self.sidebar.catchments()
                   if not (c.has_location() and c.ifd_result is not None)]
        if not cats:
            QMessageBox.information(
                self, "Batch export",
                "No catchments have both a location and a fetched IFD yet. "
                "Fetch the IFD on the IFD tab for each catchment first."
            )
            return

        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not folder:
            return

        written = []
        for c in cats:
            path = Path(folder) / csv_filename(c.lat, c.lon)
            write_all_design_csv(
                str(path), c.lat, c.lon, c.ifd_result,
                location_label=c.name, aeps=c.ifd_aeps_selected,
            )
            written.append(path.name)

        msg = f"Wrote {len(written)} CSV(s) to:\n{folder}\n\n" + "\n".join(written)
        if skipped:
            msg += f"\n\nSkipped {len(skipped)} catchment(s) with missing location or IFD."
        QMessageBox.information(self, "Batch export complete", msg)
