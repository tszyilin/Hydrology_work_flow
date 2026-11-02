"""Processing Toolbox entries for the Stage 3 tools.

Cut & Fill Volume is also registered as a real Processing algorithm
(``cutfillvolume``) for batch runs and the Model Builder, next to its
launcher. Every tool in ``tools_dialog.TOOLS`` becomes a parameterless "launcher"
algorithm under *Hydrology Workflow Suite → Tools*, so it can be found by
typing in the Processing Toolbox search box or the QGIS locator (Ctrl+K).
Running it opens the tool's normal window exactly as the Tools panel's
Launch button does — the tools themselves are unchanged.

QGIS reaches a launcher by two routes:

* Toolbox double-click: an algorithm with no visible parameters is executed
  straight away on the main thread, so ``processAlgorithm`` opens the tool.
* Locator / search bar: QGIS asks ``createCustomParametersWidget`` for a
  dialog and ``exec()``s it. We open the tool and hand back an invisible
  dialog that closes itself as soon as its event loop starts.
"""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsProcessingAlgorithm, QgsProcessingProvider
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog

from .tools_dialog import TOOLS, ToolLauncher

PROVIDER_ID = "hydrology_suite"
# modules/tools/processing_provider.py -> <plugin>/icons/icon.svg
_ICON_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "icons", "icon.svg"
)


def _alg_flag(name):
    """``Qgis.ProcessingAlgorithmFlag.<name>`` (QGIS ≥ 3.36, required by
    QGIS 4) with a fallback to the old ``QgsProcessingAlgorithm.Flag<name>``."""
    scoped = getattr(Qgis, "ProcessingAlgorithmFlag", None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(QgsProcessingAlgorithm, "Flag" + name)


class ToolLauncherAlgorithm(QgsProcessingAlgorithm):
    def __init__(self, tool, launcher):
        super().__init__()
        self._tool = tool
        self._launcher = launcher

    def createInstance(self):
        return ToolLauncherAlgorithm(self._tool, self._launcher)

    def name(self):
        return self._tool["key"]

    def displayName(self):
        return self._tool["name"]

    def group(self):
        return "Tools"

    def groupId(self):
        return "tools"

    def tags(self):
        return list(self._tool.get("tags", []))

    def shortHelpString(self):
        return (
            self._tool["description"]
            + "\n\nOpens the tool's own window (same as Launch in the "
            "Hydrology Workflow Suite → 3 · Tools panel)."
        )

    def flags(self):
        # Launchers open a UI, so keep them on the main thread and out of
        # the Model Builder, where they would do nothing useful.
        return (super().flags()
                | _alg_flag("NoThreading")
                | _alg_flag("HideFromModeler"))

    def initAlgorithm(self, config=None):
        pass

    def _open_tool_later(self):
        # Defer to the event loop so the tool opens after QGIS has finished
        # its own algorithm bookkeeping. Capture plain values, not ``self``:
        # this algorithm instance may be deleted before the timer fires.
        launcher, key = self._launcher, self._tool["key"]
        QTimer.singleShot(0, lambda: launcher.launch(key))

    def processAlgorithm(self, parameters, context, feedback):
        self._open_tool_later()
        feedback.pushInfo(f"Opening {self._tool['name']}…")
        return {}

    def createCustomParametersWidget(self, parent=None):
        self._open_tool_later()
        dlg = QDialog(parent)
        dlg.setWindowOpacity(0.0)
        QTimer.singleShot(0, dlg.reject)
        return dlg


class HydrologyToolsProvider(QgsProcessingProvider):
    def __init__(self, iface=None):
        super().__init__()
        self._launcher = ToolLauncher(iface)

    def id(self):
        return PROVIDER_ID

    def name(self):
        return "Hydrology Workflow Suite"

    def longName(self):
        return "Hydrology Workflow Suite tools"

    def icon(self):
        if os.path.isfile(_ICON_PATH):
            return QIcon(os.path.normpath(_ICON_PATH))
        return super().icon()

    def loadAlgorithms(self):
        for tool in TOOLS:
            if "processing_id" not in tool:
                self.addAlgorithm(ToolLauncherAlgorithm(tool, self._launcher))
        cut_fill = _cut_fill_algorithm()
        if cut_fill is not None:
            self.addAlgorithm(cut_fill)


def _cut_fill_algorithm():
    """The Cut & Fill algorithm, filed under this provider's Tools group.

    ``cut_fill/`` is copied in from ``04_Tools/09_cut&fill`` by package.py,
    so it is absent when this module runs from the source tree.
    """
    try:
        from .cut_fill.cut_fill_volume import CutFillVolumeAlgorithm
    except ImportError:
        return None

    class CutFillInSuite(CutFillVolumeAlgorithm):
        def displayName(self):
            # Tell it apart from the "Cut & Fill Volume" launcher, which
            # opens the window with the Results tab.
            return "Cut & Fill Volume (batch / Model Builder)"

        def group(self):
            return "Tools"

        def groupId(self):
            return "tools"

        def createInstance(self):
            return CutFillInSuite()

    return CutFillInSuite()
