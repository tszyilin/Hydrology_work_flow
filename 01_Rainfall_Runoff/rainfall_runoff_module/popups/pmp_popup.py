"""Standalone PMP popup: wraps the vendored PMP tabs directly.

Each PMP sub-tab (GSDM / Areal GSDM / GTSMR-GSAM) already carries its own
CatchmentPicker (layer combo) and Cases sidebar, so no outer location UI is
needed — the layer is the location.
"""
from __future__ import annotations

from ....qt_compat import QDialog, Qt, QVBoxLayout

from ..ui.pmp_tab import PmpTab


class PmpPopup(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PMP Calculation")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1100, 800)
        self.iface = iface

        root = QVBoxLayout(self)
        self.pmp_tab = PmpTab(iface=iface)
        root.addWidget(self.pmp_tab, 1)
