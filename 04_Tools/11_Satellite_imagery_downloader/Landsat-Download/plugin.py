# -*- coding: utf-8 -*-
"""
Main class of the "Landsat Download" plugin — adds a toolbar button
with an icon and the "Landsat Download" label; a click opens the
main window. © Grzegorz Górniak
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolButton


class LandsatDownload:

    def __init__(self, iface):
        self.iface = iface        # handle to QGIS
        self.action = None
        self.toolbar = None
        self.dialog = None

    def initGui(self):
        """Called by QGIS on startup — add the button and menu."""
        folder = os.path.dirname(__file__)
        icon = QIcon(os.path.join(folder, "icon.svg"))
        if icon.isNull():
            icon = QIcon(os.path.join(folder, "icon.png"))

        self.action = QAction(icon, "Landsat Download",
                              self.iface.mainWindow())
        self.action.setToolTip("Bulk download of Landsat imagery "
                               "with ready-to-use products")
        self.action.triggered.connect(self.run)

        # own toolbar with an "icon + text" button
        self.toolbar = self.iface.addToolBar("Landsat Download")
        self.toolbar.setObjectName("LandsatDownloadToolbar")
        button = QToolButton()
        button.setDefaultAction(self.action)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.addWidget(button)

        self.iface.addPluginToMenu("&Landsat Download", self.action)

    def unload(self):
        """Called by QGIS when the plugin is disabled — clean up."""
        self.iface.removePluginMenu("&Landsat Download", self.action)
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None

    def run(self):
        """Button click = open the main window (kept alive so the
        log and a running download survive closing the window)."""
        from .dialogs import MainDialog
        if self.dialog is None:
            self.dialog = MainDialog(self.iface,
                                     self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
