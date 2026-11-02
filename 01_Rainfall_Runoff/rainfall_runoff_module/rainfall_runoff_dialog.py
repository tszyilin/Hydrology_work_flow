"""Rainfall Runoff — launcher dialog.

Two tabs. Each tab has buttons that open a self-contained tool popup:

    Rainfall
        [ IFD Fetch       ]  -> IfdPopup
        [ PMP Calculation ]  -> PmpPopup

    Runoff
        [ RFFE            ]  -> RffePopup (PeakFlowDialog in rffe_only mode)

Popups are independent windows with their own LocationPicker.
"""
from __future__ import annotations

from ...qt_compat import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .popups.ifd_popup import IfdPopup
from .popups.pmp_popup import PmpPopup
from .popups.rffe_popup import RffePopup


class RainfallRunoffDialog(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setMinimumWidth(420)
        self._popups = {}   # key -> QDialog kept alive
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        heading = QLabel("Rainfall Runoff")
        font = heading.font(); font.setBold(True); font.setPointSize(font.pointSize() + 2)
        heading.setFont(font)
        root.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self._build_rainfall_tab(), "Rainfall")
        tabs.addTab(self._build_runoff_tab(), "Runoff")
        root.addWidget(tabs, 1)

    def _build_rainfall_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Open a rainfall tool in its own window:"))

        btn_ifd = QPushButton("IFD Fetch")
        btn_ifd.clicked.connect(lambda: self._open_popup("ifd", IfdPopup, "IFD Fetch"))
        v.addWidget(btn_ifd)

        btn_pmp = QPushButton("PMP Calculation")
        btn_pmp.clicked.connect(lambda: self._open_popup("pmp", PmpPopup, "PMP Calculation"))
        v.addWidget(btn_pmp)

        v.addStretch(1)
        return w

    def _build_runoff_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Open a runoff tool in its own window:"))

        btn_rffe = QPushButton("RFFE")
        btn_rffe.clicked.connect(lambda: self._open_popup("rffe", RffePopup, "RFFE"))
        v.addWidget(btn_rffe)

        v.addStretch(1)
        return w

    def _open_popup(self, key, factory, title):
        popup = self._popups.get(key)
        if popup is None:
            popup = factory(iface=self.iface, parent=self)
            self._popups[key] = popup
        popup.show()
        popup.raise_()
        popup.activateWindow()
