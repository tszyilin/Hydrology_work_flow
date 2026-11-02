import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .wind_fetch_dialog import WindFetchDialog


class WindFetchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.menu = "&Wind Fetch"
        self.dialog = None

    def tr(self, message):
        return QCoreApplication.translate("WindFetch", message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self.action = QAction(icon, self.tr("Wind Fetch Calculator"), self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu(self.menu, self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginVectorMenu(self.menu, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = WindFetchDialog(self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
