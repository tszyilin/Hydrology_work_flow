"""Launcher for the Plotting Tool (PyQt5).

Wraps ``plotting_tool.main()`` so we can set a Windows taskbar icon and
capture any startup error to ``plotting_tool.log`` next to this file.

For running the tool on its own, outside QGIS. Inside QGIS the suite docks
``PlottingToolApp(embedded=True)`` in-process instead
(``tools_dialog.py::_launch_plotting``).
"""
from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(HERE, "icon.png")
LOG_PATH = os.path.join(HERE, "plotting_tool.log")
APP_ID = "HydrologyWorkflowSuite.PlottingTool"


def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except Exception:
        pass


def _set_windows_app_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception as exc:
        _log(f"[warn] SetCurrentProcessExplicitAppUserModelID failed: {exc}")


def main():
    _log(f"[info] launcher starting; python={sys.executable}; exec_prefix={sys.exec_prefix}")
    try:
        _set_windows_app_id()
        sys.path.insert(0, HERE)

        try:
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtGui import QIcon
        except ImportError:
            from qgis.PyQt.QtWidgets import QApplication
            from qgis.PyQt.QtGui import QIcon

        import plotting_tool

        app = QApplication.instance() or QApplication(sys.argv)
        icon = QIcon(ICON_PATH) if os.path.isfile(ICON_PATH) else None
        if icon is None:
            _log(f"[warn] icon not found at {ICON_PATH}")
        else:
            app.setWindowIcon(icon)

        win = plotting_tool.PlottingToolApp()
        if icon is not None:
            win.setWindowIcon(icon)
        if len(sys.argv) > 1 and hasattr(win, "open_project"):
            win.open_project(sys.argv[1])
        win.show()
        _log("[info] entering event loop")
        sys.exit(app.exec_())
    except Exception:
        _log("[error] launcher crashed:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
