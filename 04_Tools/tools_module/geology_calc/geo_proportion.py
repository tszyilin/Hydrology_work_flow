from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

from .geo_proportion_provider import GeoProportionProvider


class GeoProportionPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.provider = None

    def initGui(self):
        icon = QIcon(':/images/themes/default/mIconPolygonLayer.svg')
        self.action = QAction(icon, 'Geological Proportion by Sub-Catchment',
                              self.iface.mainWindow())
        self.action.setToolTip('Calculate geological area proportions per sub-catchment')
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&Geological Tools', self.action)

        self.provider = GeoProportionProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        self.iface.removePluginMenu('&Geological Tools', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
        del self.action

        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def run(self):
        from .geo_proportion_dialog import GeoProportionDialog
        if self.dialog is None:
            self.dialog = GeoProportionDialog(self.iface.mainWindow())
        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
