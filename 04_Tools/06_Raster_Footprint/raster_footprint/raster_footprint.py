from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class RasterFootprintPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(':/images/themes/default/mIconRaster.svg')
        self.action = QAction(icon, 'Raster Footprint to Shapefile',
                              self.iface.mainWindow())
        self.action.setToolTip('Extract the valid-data footprint of a GeoTIFF as a polygon shapefile')
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&Raster Footprint', self.action)

    def unload(self):
        self.iface.removePluginMenu('&Raster Footprint', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
        del self.action

    def run(self):
        from .raster_footprint_dialog import RasterFootprintDialog
        if self.dialog is None:
            self.dialog = RasterFootprintDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
