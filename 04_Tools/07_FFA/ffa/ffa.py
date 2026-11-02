from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class FfaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(':/images/themes/default/mActionShowStatistics.svg')
        self.action = QAction(icon, 'Flood Frequency Analysis',
                              self.iface.mainWindow())
        self.action.setToolTip('Fit LP3/GEV/Gumbel/GPD to an annual maximum series')
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&Flood Frequency Analysis', self.action)

    def unload(self):
        self.iface.removePluginMenu('&Flood Frequency Analysis', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()
        del self.action

    def run(self):
        from .ffa_dialog import FfaDialog
        if self.dialog is None:
            self.dialog = FfaDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
