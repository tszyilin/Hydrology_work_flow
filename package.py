"""Build the installable zip for the Hydrology Workflow Suite.

Produces ``Hydrology_Workflow_Suite.zip`` in the project root, containing a
single top-level ``Hydrology_Workflow_Suite/`` folder as QGIS's "Install from
ZIP" expects.

Per PROJECT_GOAL.md, each stage's source-of-truth lives in its own top-level
folder (``01_Rainfall_Estimation/`` etc.) and this script *syncs* those into
``Hydrology_Workflow_Suite/modules/<stage>/`` before zipping. This keeps the
suite copies as pure build artifacts.

Never packages ``02_Peak_Flow_Estimation/01_Rffe_plugin/`` — it carries a
~260 MB geology shapefile. See DO_NOT_ZIP_RFFE.md.

    python package.py
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(ROOT, "Hydrology_Workflow_Suite")
OUT_ZIP = os.path.join(ROOT, "Hydrology_Workflow_Suite.zip")

# (source_folder, destination_inside_suite[, only_these_files])
# Entries are synced in order, and tools_module replaces all of
# modules/tools, so tool folders nested inside it must come after it.
STAGE_SOURCES = [
    (os.path.join(ROOT, "01_Rainfall_Runoff", "rainfall_runoff_module"),
     os.path.join(PLUGIN_DIR, "modules", "rainfall_runoff")),
    (os.path.join(ROOT, "04_Tools", "tools_module"),
     os.path.join(PLUGIN_DIR, "modules", "tools")),
    (os.path.join(ROOT, "04_Tools", "06_Raster_Footprint", "raster_footprint"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "raster_footprint")),
    (os.path.join(ROOT, "04_Tools", "07_FFA", "ffa"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "ffa")),
    (os.path.join(ROOT, "04_Tools", "08_Flood", "flood_tool"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "flood_tool")),
    # Scripts only: the validator and the example DEM/shapefile stay out.
    (os.path.join(ROOT, "04_Tools", "09_cut&fill"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "cut_fill"),
     ("cut_fill_volume.py", "cut_fill_dialog.py")),
    # Qt dialog + shared logic only: the Tk app, its settings json (holds an
    # email) and the sample workbook stay out.
    (os.path.join(ROOT, "04_Tools", "10_SILO_data"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "silo"),
     ("silo_core.py", "silo_dialog.py")),
    # Standalone downloader (run in Anaconda by satellite_launcher.py):
    # the app and its engine only; the original plugin UI, sentinel_open
    # and the .bat stay out.
    (os.path.join(ROOT, "04_Tools", "11_Satellite_imagery_downloader"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "satellite_downloader"),
     ("fast_engine.py", "landsat_gui.py")),
    (os.path.join(ROOT, "04_Tools", "11_Satellite_imagery_downloader",
                  "Landsat-Download"),
     os.path.join(PLUGIN_DIR, "modules", "tools", "satellite_downloader",
                  "Landsat-Download"),
     ("engine.py",)),
]

EXCLUDE_DIRS = {"__pycache__", ".git", ".idea", ".vscode", ".pytest_cache"}
EXCLUDE_EXTS = {".pyc", ".pyo", ".qix", ".cpg"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}


def sync_stage_sources():
    """Mirror each stage folder's source into its place in the suite."""
    for src, dst, *only in STAGE_SOURCES:
        if not os.path.isdir(src):
            print(f"  skip: source not found: {src}")
            continue
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        if only:
            os.makedirs(dst)
            for name in only[0]:
                shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
            init = os.path.join(dst, "__init__.py")
            if not os.path.exists(init):
                open(init, "w").close()
            print(f"  synced {', '.join(only[0])} from {os.path.relpath(src, ROOT)} "
                  f"-> {os.path.relpath(dst, ROOT)}")
            continue
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns(
                *EXCLUDE_DIRS, *(f"*{e}" for e in EXCLUDE_EXTS), *EXCLUDE_NAMES
            ),
        )
        print(f"  synced {os.path.relpath(src, ROOT)} -> {os.path.relpath(dst, ROOT)}")


def iter_files():
    for dirpath, dirnames, filenames in os.walk(PLUGIN_DIR):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for name in sorted(filenames):
            if name in EXCLUDE_NAMES:
                continue
            if os.path.splitext(name)[1].lower() in EXCLUDE_EXTS:
                continue
            yield os.path.join(dirpath, name)


def main():
    if not os.path.isdir(PLUGIN_DIR):
        sys.exit("Plugin folder not found: " + PLUGIN_DIR)

    sync_stage_sources()

    if os.path.exists(OUT_ZIP):
        os.remove(OUT_ZIP)

    count = 0
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_files():
            arcname = os.path.join(
                "Hydrology_Workflow_Suite",
                os.path.relpath(path, PLUGIN_DIR),
            ).replace(os.sep, "/")
            zf.write(path, arcname)
            count += 1

    size_mb = os.path.getsize(OUT_ZIP) / (1024 * 1024)
    print("Wrote {0}".format(OUT_ZIP))
    print("  {0} files, {1:.1f} MB".format(count, size_mb))


if __name__ == "__main__":
    main()
