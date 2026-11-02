"""Drives the Run button end to end, the way clicking it in QGIS does.

The bridge is covered elsewhere; what this file covers is ``plugin.run`` itself
-- the glue that reads the dialog, calls the bridge, and puts layers into the
project. A failure here looks to the user like "I hit Run and nothing appeared".
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsProject, QgsVectorLayer  # noqa: E402

CATCHMENTS = Path(__file__).resolve().parents[2] / "01_example catchments"


class FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=None, duration=None):
        self.messages.append((title, text))

    def pushInfo(self, title, text):
        self.messages.append((title, text))


class FakeCanvas:
    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


class FakeIface:
    """Only the handful of iface calls the plugin actually makes."""

    def __init__(self):
        self.bar = FakeMessageBar()
        self.canvas = FakeCanvas()
        self.active = None
        self.zoomed = 0
        self.docks = []

    def mainWindow(self):
        return None

    def messageBar(self):
        return self.bar

    def mapCanvas(self):
        return self.canvas

    def setActiveLayer(self, layer):
        self.active = layer

    def zoomToActiveLayer(self):
        self.zoomed += 1

    def addPluginToMenu(self, menu, action):
        pass

    def addToolBarIcon(self, action):
        pass

    def removePluginMenu(self, menu, action):
        pass

    def removeToolBarIcon(self, action):
        pass

    def addDockWidget(self, area, dock):
        # QGIS reparents the dock into its main window; with no main window
        # there is nothing to reparent to, and the dock stands alone quite
        # happily for the duration of a test.
        self.docks.append(dock)

    def removeDockWidget(self, dock):
        if dock in self.docks:
            self.docks.remove(dock)


@pytest.fixture
def project(qgis_app):
    QgsProject.instance().removeAllMapLayers()
    yield QgsProject.instance()
    QgsProject.instance().removeAllMapLayers()


@pytest.fixture
def catchment_layer(project):
    path = CATCHMENTS / "catchment_B_area.shp"
    if not path.exists():
        pytest.skip("example catchment not found")
    layer = QgsVectorLayer(str(path), "catchment_B", "ogr")
    assert layer.isValid()
    project.addMapLayer(layer)
    return layer


@pytest.fixture
def plugin(qgis_app, catchment_layer, monkeypatch):
    """A plugin with its dock built and the catchment selected on the tab.

    ``plugin.dialog`` is the Areal GSDM tab: it was a standalone dialog before
    the plugin grew three tabs, and everything below still exercises the same
    inputs, run and results.
    """
    from pmp_toolbox import plugin as plugin_module
    from pmp_toolbox.tabs import areal_gsdm_tab, common

    # Any modal box would hang the test and, in QGIS, would be the visible
    # symptom of a failed run -- so record them instead of showing them.  Both
    # modules that can raise one are patched: the tab for run-time failures,
    # common for the export.
    raised = []
    for module in (areal_gsdm_tab, common):
        for name in ("warning", "critical", "information"):
            monkeypatch.setattr(
                module.QMessageBox,
                name,
                staticmethod(lambda *a, _n=name, **k: raised.append((_n, a[1], a[2]))),
            )

    iface = FakeIface()
    obj = plugin_module.PmpToolboxPlugin(iface)
    obj._build_dock()
    obj.dialog = obj.areal_tab
    obj.run = obj.areal_tab.run
    obj.dialog.picker.layer_combo.setLayer(catchment_layer)
    obj.dialog.sampling.setValue(105)
    obj.dialog.rotations.setValue(4)
    obj.raised = raised
    yield obj

    # Drop every reference to project layers before the project fixture removes
    # them; a dangling one crashes the interpreter on teardown.
    iface.active = None
    obj.dialog.picker.layer_combo.setLayer(None)
    obj.unload()


def _output_layers(project):
    return {
        name: layer
        for name, layer in project.mapLayers().items()
        if layer.name().startswith("GSDM")
    }


class TestRunAddsLayers:
    def test_run_reports_no_error(self, plugin):
        plugin.run()
        assert plugin.raised == [], f"a message box was raised: {plugin.raised}"

    def test_both_layers_reach_the_project(self, plugin, project):
        plugin.run()
        names = sorted(l.name() for l in _output_layers(project).values())
        assert len(names) == 2, f"expected 2 GSDM layers, got {names}"
        assert any(n.endswith("rainfall") for n in names), names
        assert any(n.endswith("ellipses") for n in names), names

    def test_layers_are_valid_and_have_features(self, plugin, project):
        plugin.run()
        for layer in _output_layers(project).values():
            assert layer.isValid(), layer.name()
            assert layer.featureCount() > 0, layer.name()

    def test_layers_are_file_backed_shapefiles(self, plugin, project):
        plugin.run()
        for layer in _output_layers(project).values():
            assert layer.source().endswith(".shp"), layer.name()
            assert Path(layer.source()).exists(), layer.source()

    def test_canvas_is_zoomed_to_the_template(self, plugin):
        """Without this the ellipses render outside the current view."""
        plugin.run()
        assert plugin.iface.zoomed == 1
        assert plugin.iface.active is not None
        assert plugin.iface.active.name().endswith("ellipses")

    def test_rainfall_layer_is_styled(self, plugin, project):
        plugin.run()
        rings = next(
            l for l in _output_layers(project).values() if l.name().endswith("rainfall")
        )
        assert rings.renderer().classAttribute() == "Ellipse"
        assert len(rings.renderer().categories()) > 0
        assert rings.labelsEnabled()

    def test_results_table_is_populated(self, plugin):
        plugin.run()
        assert plugin.dialog.results_table.rowCount() > 0
        assert plugin.dialog.export_button.isEnabled()

    def test_folder_is_reported_to_the_user(self, plugin):
        plugin.run()
        assert any("written to" in text for _t, text in plugin.iface.bar.messages)

    def test_scratch_layer_mode_still_adds_layers(self, plugin, project):
        plugin.dialog.as_shapefile.setChecked(False)
        plugin.run()
        layers = _output_layers(project)
        assert len(layers) == 2
        for layer in layers.values():
            assert layer.dataProvider().name() == "memory"

    def test_two_runs_add_two_pairs(self, plugin, project):
        plugin.run()
        plugin.run()
        assert len(_output_layers(project)) == 4

    def test_ui_is_re_enabled_afterwards(self, plugin):
        plugin.run()
        assert plugin.dialog.run_button.isEnabled()
        assert not plugin.dialog.progress.isVisible()


class TestPreviewDuringARun:
    """The preview is on by default, so every test above already drives it."""

    def test_the_search_is_recorded_and_replayed(self, plugin):
        """A finished run replays itself by default, ending on the result."""
        plugin.run()
        preview = plugin.preview
        assert preview is not None
        assert preview.history, "no trials reached the preview"
        assert preview.canvas.final, "the final rings were never handed over"
        assert preview._timer.isActive() and preview.slider.value() == 0
        preview.show_final()
        assert preview.canvas.show_final
        assert preview.canvas._failure is None, preview.canvas._failure

    def test_the_result_is_shown_at_once_without_the_replay(self, plugin):
        plugin.run()  # builds the preview, so the setting can be reached
        plugin.preview.auto_replay.setChecked(False)
        plugin.run()
        assert plugin.preview.canvas.show_final
        assert not plugin.preview._timer.isActive()

    def test_a_second_run_starts_a_fresh_history(self, plugin):
        plugin.run()
        first = len(plugin.preview.history)
        plugin.dialog.rotations.setValue(2)
        plugin.run()
        assert first > 0 and len(plugin.preview.history) < first

    def test_cancelling_mid_search_adds_no_layers(self, plugin, project):
        """Pressing Cancel is a choice, not a failure: no layers, no error box."""
        from pmp_toolbox.preview import SearchPreviewDialog

        class CancelsItself(SearchPreviewDialog):
            def __call__(self, trial):
                if trial.index >= 25:
                    self._cancel()
                return super().__call__(trial)

        plugin.preview = CancelsItself()
        plugin.run()

        assert not _output_layers(project)
        assert not plugin.raised, plugin.raised
        assert any("cancelled" in text.lower() for _t, text in plugin.iface.bar.messages)
        assert plugin.dialog.run_button.isEnabled()

    def test_the_preview_can_be_turned_off(self, plugin, project):
        plugin.dialog.show_preview.setChecked(False)
        plugin.run()
        assert plugin.preview is None
        assert len(_output_layers(project)) == 2


class TestRunGuards:
    def test_no_layer_selected_warns_and_stops(self, plugin, project):
        plugin.dialog.picker.layer_combo.setLayer(None)
        plugin.run()
        assert plugin.raised and plugin.raised[0][0] == "warning"
        assert not _output_layers(project)

    def test_bad_weight_warns_and_stops(self, plugin, project):
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        plugin.dialog.weights_table.setItem(0, 0, QTableWidgetItem("not a number"))
        plugin.run()
        assert plugin.raised and plugin.raised[0][0] == "warning"
        assert not _output_layers(project)

    def test_selected_only_with_no_selection_warns(self, plugin, project):
        plugin.dialog.picker.selected_only.setChecked(True)
        plugin.run()
        assert plugin.raised and plugin.raised[0][0] == "warning"
        assert not _output_layers(project)
