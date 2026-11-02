"""RFFE Query main plugin class: toolbar entry and the query dialog."""

from __future__ import annotations

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MENU_NAME = "&RFFE Query"


class RffePlugin:
    """Registers the RFFE toolbar/menu entry and opens the query dialog."""

    def __init__(self, iface):
        self.iface = iface
        self.actions: list[QAction] = []
        self.toolbar = None
        self._dialog = None          # created lazily and reused

    # ------------------------------------------------------------------
    # QGIS plugin lifecycle
    # ------------------------------------------------------------------
    def initGui(self):  # noqa: N802 (QGIS API name)
        self.toolbar = self.iface.addToolBar("RFFE Query")
        self.toolbar.setObjectName("RFFE_Query")

        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "rffe.svg"))
        action = QAction(icon, "RFFE Query", self.iface.mainWindow())
        action.setToolTip("Query the RFFE 2021 model for a catchment picked on the map")
        action.triggered.connect(self.open_dialog)
        self.toolbar.addAction(action)
        self.iface.addPluginToMenu(MENU_NAME, action)
        self.actions.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(MENU_NAME, action)
        self.actions.clear()
        if self.toolbar is not None:
            del self.toolbar
            self.toolbar = None
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    # ------------------------------------------------------------------
    def open_dialog(self):
        from .gui.rffe_dialog import RffeDialog

        if self._dialog is None:
            self._dialog = RffeDialog(self.iface, self.iface.mainWindow())
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
