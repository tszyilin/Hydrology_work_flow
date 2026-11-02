import os.path

from .qt_compat import Qt, QAction, QDockWidget, QIcon
from .peak_flow_dialog import PeakFlowDialog


class PeakFlowToolbox:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icons", "icon.png")
        icon = QIcon(icon_path) if os.path.isfile(icon_path) else QIcon()
        self.action = QAction(icon, "Peak Flow Toolbox", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self._toggle_dock)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Peak Flow Toolbox", self.action)

        self._dialog = PeakFlowDialog(iface=self.iface)

        self.dock = QDockWidget("Peak Flow Toolbox", self.iface.mainWindow())
        self.dock.setObjectName("PeakFlowToolboxDock")
        self.dock.setWidget(self._dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.setFloating(True)
        self.dock.setVisible(False)
        self.dock.visibilityChanged.connect(self.action.setChecked)
        self.action.setChecked(self.dock.isVisible())

    def unload(self):
        self.iface.removePluginMenu("&Peak Flow Toolbox", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    def _toggle_dock(self, checked):
        if self.dock is not None:
            self.dock.setVisible(checked)
