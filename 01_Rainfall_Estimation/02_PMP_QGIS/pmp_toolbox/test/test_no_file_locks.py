"""Importing the plugin must not hold any of its own files open.

Windows will not delete a directory containing an open file, so a single
lingering handle makes the plugin impossible to uninstall or reinstall without
quitting QGIS — and the error QGIS shows ("Failed to remove the directory")
says nothing about which file or why.

This bit us once. ``core.grids`` did::

    _Z = np.load(".../gtsmr_grids.npz")
    _GRIDS = {k: _Z[k] for k in (...)}

``np.load`` on an ``.npz`` returns a lazily-loading ``NpzFile`` that keeps the
archive open until it is closed, and holding it in a module global kept that
handle open for the whole session. The code was vendored verbatim from the
Toolbox website, where it is harmless: a server process never uninstalls
itself. A plugin does.

Nothing inside the plugin can notice this, which is exactly why it needs a
test: copy the package somewhere disposable, import every module that reads
data, and try to delete it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]

#: Every module that opens a file at import time.
DATA_MODULES = ("dda", "depth", "duration", "grids", "maf", "zones")


def test_no_module_holds_a_data_file_open(tmp_path):
    """Import the package from a copy, then delete the copy.

    Run in a subprocess so the import happens in a process that exits, rather
    than leaving this session's ``sys.modules`` holding a package whose files
    have just been deleted underneath it.
    """
    root = tmp_path / "install"
    root.mkdir()
    shutil.copytree(
        PLUGIN,
        root / "pmp_toolbox",
        ignore=shutil.ignore_patterns("__pycache__", "test", "*.pyc"),
    )

    script = textwrap.dedent(
        f"""
        import shutil, sys
        sys.path.insert(0, {str(root)!r})
        from pmp_toolbox.core import {", ".join(DATA_MODULES)}

        # Touch each lookup so nothing is deferred past the import.
        grids.lookup(-22.755, 135.724)
        zones.lookup(-22.755, 135.724)
        maf.lookup(-22.755, 135.724)
        duration.lookup(-22.755, 135.724)
        depth.calc_gsdm(100.0, 3.0, 0.0, 1.0, 1.0, 0.8)

        try:
            shutil.rmtree({str(root / "pmp_toolbox")!r})
        except OSError as exc:
            print("LOCKED:", exc)
            raise SystemExit(1)
        print("OK")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        "the plugin folder could not be deleted while imported, so QGIS will "
        "not be able to uninstall it:\n" + result.stdout + result.stderr
    )


def test_the_npz_is_read_and_closed():
    """The specific mistake, guarded at the source.

    Asserting on the source rather than only on behaviour: the behavioural
    test above needs a subprocess and a full copy, so it is the kind of test
    that gets skipped on a slow day. This one is instant and names the trap.
    """
    source = (PLUGIN / "core" / "grids.py").read_text(encoding="utf-8")
    assert "with np.load(" in source, (
        "np.load on an .npz must be used as a context manager, or the archive "
        "stays open and the plugin cannot be uninstalled on Windows"
    )


@pytest.mark.parametrize("name", DATA_MODULES)
def test_data_files_are_opened_with_a_context_manager(name):
    """No bare ``open(...)`` left holding a handle."""
    source = (PLUGIN / "core" / f"{name}.py").read_text(encoding="utf-8")
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or "open(" not in stripped:
            continue
        assert stripped.startswith(("with ", "def ", '"""')) or "with " in stripped, (
            f"{name}.py:{number} opens a file outside a with-block: {stripped}"
        )
