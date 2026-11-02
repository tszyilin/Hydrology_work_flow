"""Standalone RFFE popup: reuses PeakFlowDialog in rffe_only mode."""
from __future__ import annotations

from ....qt_compat import QDialog, Qt, QVBoxLayout

from ..peak_flow.peak_flow_dialog import PeakFlowDialog


class RffePopup(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RFFE")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1000, 750)

        root = QVBoxLayout(self)
        self.peak_flow = PeakFlowDialog(iface=iface, rffe_only=True)
        root.addWidget(self.peak_flow, 1)
