"""Shared test setup.

Makes the plugin importable when pytest is run from anywhere, and owns the one
``QgsApplication`` the whole session shares.  Creating a second one in the same
process crashes the interpreter, so every QGIS-dependent test must take the
``qgis_app`` fixture rather than build its own.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def qgis_app():
    pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")
    from qgis.core import QgsApplication

    # GUI enabled so the dialog tests can build widgets; offscreen so nothing
    # actually appears on a display.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QgsApplication([], True)
    app.initQgis()
    yield app
    app.exitQgis()
