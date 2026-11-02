"""Standalone IFD popup: LocationPicker + IfdTab, backed by a stub Catchment."""
from __future__ import annotations

from ....qt_compat import QDialog, Qt, QVBoxLayout

from ..catchment import Catchment
from ..ui.ifd_tab import IfdTab
from ..ui.location_picker import LocationPicker


class IfdPopup(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IFD Fetch")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(900, 700)
        self.iface = iface
        self._cat = Catchment(name="IFD")

        root = QVBoxLayout(self)
        self.picker = LocationPicker(iface=iface)
        self.ifd_tab = IfdTab()
        root.addWidget(self.picker)
        root.addWidget(self.ifd_tab, 1)

        self.picker.location_changed.connect(self._on_location)
        self.ifd_tab.set_catchment(self._cat)

    def _on_location(self, lat, lon, source):
        self._cat.lat = lat
        self._cat.lon = lon
        self._cat.source = source
        self._cat.ifd_result = None
        self.ifd_tab.set_catchment(self._cat)
