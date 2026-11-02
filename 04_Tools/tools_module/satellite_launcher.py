"""Satellite Imagery Downloader — QGIS side.

The downloader itself (``satellite_downloader/landsat_gui.py``, PySide6 +
GDAL) runs in its own Anaconda Python process, never inside QGIS: bulk
downloads take hours and building products holds ~1 GB numpy arrays, so a
separate process keeps QGIS responsive and a crash there can't take an
unsaved QGIS project with it. This module only

  * starts that process, handing over the selected polygons as the area
    of interest and a folder next to the project as the output, and
  * loads the finished GeoTIFFs back into the map, one group per folder.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from ...qt_compat import QFileDialog, QMessageBox

try:
    from qgis.PyQt.QtCore import QSettings
except ImportError:
    from PyQt5.QtCore import QSettings

SETTINGS_GROUP = "HydrologySuite/SatelliteDownloader"
GUI_SCRIPT = os.path.join(os.path.dirname(__file__), "satellite_downloader",
                          "landsat_gui.py")
# Where Anaconda / Miniconda usually live; the first hit is used unless the
# user has picked a python.exe before.
PYTHON_CANDIDATES = [
    r"C:\ProgramData\anaconda3\python.exe",
    os.path.expandvars(r"%USERPROFILE%\anaconda3\python.exe"),
    r"C:\ProgramData\miniconda3\python.exe",
    os.path.expandvars(r"%USERPROFILE%\miniconda3\python.exe"),
]
# QGIS points these at its own Python / GDAL / Qt; inherited by Anaconda
# they make it load the wrong modules and DLLs.
QGIS_ENV_VARS = ("PYTHONHOME", "PYTHONPATH", "GDAL_DATA", "GDAL_DRIVER_PATH",
                 "PROJ_LIB", "PROJ_DATA", "QT_PLUGIN_PATH",
                 "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONUTF8")


def _settings_value(key, default=""):
    s = QSettings()
    s.beginGroup(SETTINGS_GROUP)
    value = s.value(key, default) or default
    s.endGroup()
    return value


def _set_settings_value(key, value):
    s = QSettings()
    s.beginGroup(SETTINGS_GROUP)
    s.setValue(key, value)
    s.endGroup()


def find_python(parent=None):
    """Anaconda python.exe with PySide6 + GDAL: the saved one, else a
    usual install location, else ask once and remember."""
    saved = _settings_value("python")
    if saved and os.path.isfile(saved):
        return saved
    for path in PYTHON_CANDIDATES:
        if os.path.isfile(path):
            return path
    QMessageBox.information(
        parent, "Satellite Imagery Downloader",
        "The downloader runs in Anaconda Python (it needs PySide6, GDAL, "
        "numpy and requests), which was not found in the usual places.\n\n"
        "Pick the python.exe to use — it is remembered for next time.")
    path, _ = QFileDialog.getOpenFileName(
        parent, "Anaconda python.exe", "", "python.exe (python.exe)")
    if not path:
        return None
    _set_settings_value("python", path)
    return path


def _clean_env(python):
    """QGIS's environment minus its Python/GDAL/Qt settings, with the
    Anaconda folders first on PATH so its own DLLs win."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in QGIS_ENV_VARS}
    qgis_root = os.environ.get("OSGEO4W_ROOT", "").lower()
    base = os.path.dirname(python)
    conda_dirs = [base, os.path.join(base, "Library", "bin"),
                  os.path.join(base, "Scripts")]
    rest = [p for p in env.get("PATH", "").split(os.pathsep)
            if p and not (qgis_root and p.lower().startswith(qgis_root))]
    env["PATH"] = os.pathsep.join(conda_dirs + rest)
    return env


def export_aoi(iface):
    """Selected features of the active polygon layer (all features when
    none are selected) as a WGS84 GeoJSON in the temp folder. Returns the
    path, or None when the active layer is not a polygon layer."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsProject, QgsVectorFileWriter, QgsVectorLayer,
                           QgsWkbTypes)
    layer = iface.activeLayer() if iface is not None else None
    if not isinstance(layer, QgsVectorLayer) or \
            layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        return None
    path = os.path.join(tempfile.gettempdir(), "hydrology_suite_aoi.geojson")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GeoJSON"
    options.onlySelectedFeatures = layer.selectedFeatureCount() > 0
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if layer.crs() != wgs84:
        options.ct = QgsCoordinateTransform(layer.crs(), wgs84,
                                            QgsProject.instance())
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), options)
    if error[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Could not export the area of interest: {error[1]}")
    return path


def default_output_folder():
    """``satellite_imagery`` next to the saved project, else nothing (the
    downloader then keeps the folder it used last time)."""
    from qgis.core import QgsProject
    home = QgsProject.instance().homePath()
    return os.path.join(home, "satellite_imagery") if home else ""


def launch(iface, parent=None):
    """Start the downloader as a detached process. Returns the Popen."""
    if not os.path.isfile(GUI_SCRIPT):
        raise FileNotFoundError(GUI_SCRIPT)
    python = find_python(parent)
    if not python:
        return None
    args = [python, GUI_SCRIPT]
    aoi = export_aoi(iface)
    if aoi:
        args += ["--aoi", aoi]
    out = default_output_folder()
    if out:
        args += ["--out", out]
    # Errors before the window opens (missing PySide6, bad env) would
    # otherwise vanish with the hidden console — keep them in a log.
    log_path = os.path.join(tempfile.gettempdir(), "satellite_downloader.log")
    log = open(log_path, "w", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        # Own process group, no console window, survives closing QGIS.
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP
                 | subprocess.CREATE_NO_WINDOW)
    proc = subprocess.Popen(
        args, cwd=os.path.dirname(GUI_SCRIPT), env=_clean_env(python),
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=flags, close_fds=True)
    log.close()
    if iface is not None:
        where = "selected polygons" if aoi else "no area passed — pick one in the app"
        iface.messageBar().pushInfo(
            "Satellite Imagery Downloader",
            f"Started in its own window ({where}). Log: {log_path}")
    return proc


def load_results(iface, parent=None):
    """Pick the downloader's output folder and add every GeoTIFF under it,
    one layer group per sub-folder (the yearly folders)."""
    from qgis.core import QgsProject, QgsRasterLayer
    start = _settings_value("results_folder") or default_output_folder()
    folder = QFileDialog.getExistingDirectory(
        parent, "Downloaded imagery folder", start)
    if not folder:
        return 0
    _set_settings_value("results_folder", folder)
    project = QgsProject.instance()
    root = project.layerTreeRoot().insertGroup(0, os.path.basename(folder))
    added, failed = 0, []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        tifs = sorted(f for f in filenames if f.lower().endswith((".tif", ".tiff")))
        if not tifs:
            continue
        rel = os.path.relpath(dirpath, folder)
        group = root if rel == "." else root.addGroup(rel.replace(os.sep, " / "))
        for name in tifs:
            layer = QgsRasterLayer(os.path.join(dirpath, name),
                                   os.path.splitext(name)[0])
            if not layer.isValid():
                failed.append(name)
                continue
            project.addMapLayer(layer, False)
            group.addLayer(layer)
            added += 1
    if not added:
        root.parent().removeChildNode(root)
    message = f"Added {added} raster(s) from {folder}."
    if failed:
        message += f"\n{len(failed)} could not be read: " + ", ".join(failed[:10])
    QMessageBox.information(parent, "Add Downloaded Imagery", message)
    return added
