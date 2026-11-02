"""Smoke tests for the dialog and renderers.

These catch the API drift that headless calculation tests cannot -- wrong enum
paths, renamed Qt flags, field types the provider rejects.  Needs the QGIS
Python environment and a QApplication; skipped otherwise.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (  # noqa: E402
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)

from pmp_toolbox.core import ellipses  # noqa: E402
from pmp_toolbox.core.gsdm import Inputs  # noqa: E402

CATCHMENTS = Path(__file__).resolve().parents[2] / "01_example catchments"


#: The session-wide QgsApplication from conftest is already GUI-enabled.
@pytest.fixture(scope="session")
def gui_app(qgis_app):
    return qgis_app


@pytest.fixture
def dialog(gui_app):
    """The Areal GSDM tab.

    Still called ``dialog`` throughout this file: it was one until the plugin
    grew three tabs, and its inputs, results table and export are unchanged.
    ``iface`` is None because nothing these tests touch reaches for it -- only
    ``run()`` does, and that is exercised in test_plugin_run.py.
    """
    from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab

    return ArealGsdmTab(iface=None)


class TestDialog:
    def test_constructs_with_defaults(self, dialog):
        assert dialog.duration.currentData() == 3.0
        # 0% smooth / 100% rough, matching the Toolbox website. Asserted again
        # in test_tabs.TestWebsiteDefaults alongside the GSDM tab, so the two
        # tabs offering GSDM cannot drift apart.
        assert dialog.smooth.value() == 0
        assert dialog.inputs().rough == 1.0

    def test_weights_populate_for_every_ellipse(self, dialog):
        weights = dialog.weights()
        assert sorted(weights) == sorted(ellipses.LABELS)
        tabulated = [weights[l] for l in ellipses.TABULATED_LABELS]
        assert tabulated == sorted(tabulated, reverse=True)
        assert tabulated[0] > 0

    def test_terrain_split_always_sums_to_one(self, dialog):
        for percent in (0, 35, 100):
            dialog.smooth.setValue(percent)
            inputs = dialog.inputs()
            assert inputs.smooth + inputs.rough == pytest.approx(1.0)
            assert f"{100 - percent} % rough" == dialog.rough_label.text()

    def test_elevation_drives_the_eaf(self, dialog):
        dialog.elevation.setValue(2100.0)
        assert dialog.inputs().eaf == pytest.approx(0.90)
        assert "0.90" in dialog.eaf_label.text()

    def test_weights_follow_the_duration(self, dialog):
        dialog.duration.setCurrentIndex(0)  # 0.25 hour
        quarter = dialog.weights()["A"]
        dialog.duration.setCurrentIndex(dialog.duration.count() - 1)  # 6 hours
        assert dialog.weights()["A"] > quarter

    def test_weights_follow_the_terrain(self, dialog):
        dialog.duration.setCurrentIndex(dialog.duration.count() - 1)
        dialog.smooth.setValue(100)
        smooth = dialog.weights()["A"]
        dialog.smooth.setValue(0)
        assert dialog.weights()["A"] > smooth

    def test_overridden_weights_are_read_back(self, dialog):
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        dialog.weights_table.setItem(0, 0, QTableWidgetItem("42.5"))
        assert dialog.weights()["A"] == pytest.approx(42.5)

    def test_rejects_a_non_numeric_weight(self, dialog):
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        dialog.weights_table.setItem(0, 2, QTableWidgetItem("wet"))
        with pytest.raises(ValueError):
            dialog.weights()

    def test_rejects_all_zero_weights(self, dialog):
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        for column in range(len(ellipses.LABELS)):
            dialog.weights_table.setItem(0, column, QTableWidgetItem("0"))
        with pytest.raises(ValueError):
            dialog.weights()

    def test_export_is_disabled_until_a_run_completes(self, dialog):
        assert not dialog.export_button.isEnabled()


class TestMafLookup:
    """Figure 3 read at the catchment centroid, instead of typed in by eye."""

    @pytest.fixture
    def with_layer(self, dialog, gui_app):
        path = CATCHMENTS / "catchment_B_area.shp"
        if not path.exists():
            pytest.skip("example catchment not found")
        layer = QgsVectorLayer(str(path), "catchment_B", "ogr")
        QgsProject.instance().addMapLayer(layer)
        dialog.picker.layer_combo.setLayer(layer)
        yield dialog, layer
        dialog.picker.layer_combo.setLayer(None)
        QgsProject.instance().removeMapLayer(layer.id())

    def test_selecting_a_layer_fills_the_maf_in(self, with_layer):
        """The example catchments sit in central Australia, around MAF 0.83."""
        dialog, _layer = with_layer
        assert dialog.maf.value() == pytest.approx(0.83, abs=0.05)
        assert dialog.inputs().maf == pytest.approx(dialog.maf.value())

    def test_it_shows_where_the_value_came_from(self, with_layer):
        dialog, _layer = with_layer
        note = dialog.maf.note.text()
        assert "Figure 3" in note and "°S" in note and "°E" in note

    def test_the_button_agrees_with_the_bridge(self, with_layer):
        from pmp_toolbox.core import maf as maf_module
        from pmp_toolbox import qgis_bridge

        dialog, layer = with_layer
        lon, lat = qgis_bridge.centroid_lonlat(layer)
        dialog.maf.spin.setValue(0.10)
        dialog.maf.update_from(dialog.picker.catchment(), force=True)
        assert dialog.maf.value() == pytest.approx(maf_module.lookup(lat, lon)["maf"])

    def test_a_typed_value_survives_until_the_catchment_changes(self, with_layer):
        dialog, _layer = with_layer
        dialog.maf.spin.setValue(0.55)
        dialog.refresh_weights()
        assert dialog.inputs().maf == pytest.approx(0.55)

    def test_a_catchment_off_the_map_is_left_to_the_user(self, dialog, gui_app):
        """Outside Australia there is no Figure 3 value to give.

        The layer is projected (UTM 31N, over Belgium) rather than EPSG:4326,
        because a geographic layer is refused earlier for a different reason --
        see TestGeographicCrsIsRefused -- and would never reach the lookup.
        """
        layer = QgsVectorLayer("Polygon?crs=EPSG:32631", "elsewhere", "memory")
        feature = QgsFeature()
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((500000 5540000, 510000 5540000, "
                "510000 5550000, 500000 5550000, 500000 5540000))"
            )
        )
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        try:
            dialog.maf.spin.setValue(0.66)
            dialog.picker.layer_combo.setLayer(layer)
            dialog.maf.update_from(dialog.picker.catchment(), force=True)
            assert dialog.maf.value() == pytest.approx(0.66)  # untouched
            assert "outside GSDM Figure 3" in dialog.maf.note.text()
        finally:
            dialog.picker.layer_combo.setLayer(None)
            QgsProject.instance().removeMapLayer(layer.id())

    def test_the_centroid_comes_back_in_degrees(self, with_layer):
        from pmp_toolbox import qgis_bridge

        _dialog, layer = with_layer
        lon, lat = qgis_bridge.centroid_lonlat(layer)
        assert -44.0 < lat < -8.0 and 110.0 < lon < 156.0
        # The layer is projected; the answer must not be metres.
        assert layer.crs().authid() != "EPSG:4326"


class TestSamplingEstimate:
    """The spacing is in metres, so the user needs to see what it will cost."""

    @pytest.fixture
    def with_layer(self, dialog, gui_app):
        path = CATCHMENTS / "catchment_B_area.shp"
        if not path.exists():
            pytest.skip("example catchment not found")
        layer = QgsVectorLayer(str(path), "catchment_B", "ogr")
        QgsProject.instance().addMapLayer(layer)
        dialog.picker.layer_combo.setLayer(layer)
        yield dialog, layer
        dialog.picker.layer_combo.setLayer(None)
        QgsProject.instance().removeMapLayer(layer.id())

    def test_nothing_is_claimed_without_a_layer(self, dialog):
        dialog.picker.layer_combo.setLayer(None)
        dialog.refresh_sample_estimate()
        assert dialog.sample_estimate.text() == ""

    def test_the_estimate_matches_the_bounding_box(self, with_layer):
        dialog, layer = with_layer
        from pmp_toolbox import qgis_bridge

        dialog.sampling.setValue(50)
        box = layer.extent()
        expected = qgis_bridge.estimate_points(box.width(), box.height(), 50)
        assert f"{expected:,}" in dialog.sample_estimate.text()

    def test_a_finer_spacing_means_more_points(self, with_layer):
        dialog, _layer = with_layer

        def count(metres):
            dialog.sampling.setValue(metres)
            return int(
                "".join(c for c in dialog.sample_estimate.text() if c.isdigit())
            )

        assert count(25) > count(100)

    def test_too_fine_a_spacing_is_called_out_before_running(self, with_layer):
        dialog, _layer = with_layer
        dialog.sampling.setValue(5)
        text = dialog.sample_estimate.text()
        assert "too many" in text
        # It must name a spacing that would actually work, not just complain.
        workable = int("".join(c for c in text.split("use")[1] if c.isdigit()))
        dialog.sampling.setValue(workable)
        assert "too many" not in dialog.sample_estimate.text()


@pytest.fixture(scope="module")
def run_output(gui_app):
    from pmp_toolbox import qgis_bridge

    path = CATCHMENTS / "catchment_B_area.shp"
    if not path.exists():
        pytest.skip("example catchment not found")
    layer = QgsVectorLayer(str(path), "B", "ogr")
    return qgis_bridge.run(
        layer, Inputs(3.0, 1.0, 0.0, 0.70, 1.0), cell_m=105.0
    )


class TestResultsRendering:
    def test_summary_and_table_populate(self, dialog, run_output):
        result, placement, coarse, *_rest = run_output
        dialog.show_result(result, placement, coarse)
        assert dialog.results_table.rowCount() == len(result.rings)
        assert result.outermost in dialog.summary.text()
        assert "PMP" in dialog.summary.text()
        assert dialog.export_button.isEnabled()

    def test_warnings_panel_reflects_the_result(self, dialog, run_output):
        result, placement, coarse, *_rest = run_output
        dialog.show_result(result, placement, coarse)
        assert dialog.warnings.isVisibleTo(dialog) == bool(result.warnings)

    def test_csv_export_writes_every_ring(self, dialog, run_output, tmp_path, monkeypatch):
        import csv

        from pmp_toolbox.tabs import common as dialog_module

        result, placement, coarse, *_rest = run_output
        dialog.show_result(result, placement, coarse)

        target = tmp_path / "out.csv"
        monkeypatch.setattr(
            dialog_module.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        monkeypatch.setattr(
            dialog_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
        )
        dialog.export_csv()

        rows = list(csv.reader(target.open(encoding="utf-8-sig")))
        assert rows[0][0] == "Ellipse"
        labels = [r[0] for r in rows[1 : 1 + len(result.rings)]]
        assert labels == [r.label for r in result.rings]

    def test_csv_export_records_the_inputs_behind_the_numbers(
        self, dialog, run_output, tmp_path, monkeypatch
    ):
        """The same rings under a different MAF are a different PMP, so the
        export has to say which MAF produced them."""
        import csv

        from pmp_toolbox.tabs import common as dialog_module

        result, placement, coarse, *_rest = run_output
        dialog.show_result(result, placement, coarse)

        target = tmp_path / "out.csv"
        monkeypatch.setattr(
            dialog_module.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        monkeypatch.setattr(
            dialog_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
        )
        dialog.export_csv()

        rows = list(csv.reader(target.open(encoding="utf-8-sig")))
        assert rows[0][0] == "Ellipse", "the ring table must stay on row 1"
        recorded = {r[0]: r[1] for r in rows if len(r) == 2}
        assert recorded["MAF (Figure 3)"] == f"{result.inputs.maf:.2f}"
        assert recorded["MAF source"]
        assert recorded["Duration (hr)"] == f"{result.inputs.duration_hr:g}"
        assert recorded["Outermost ellipse"] == result.outermost
        assert float(recorded["PMP (mm)"]) > 0

    def test_the_export_describes_the_run_not_the_dialog_s_later_state(
        self, dialog, run_output, tmp_path, monkeypatch
    ):
        """Changing a spin box after a run must not rewrite what it recorded."""
        import csv

        from pmp_toolbox.tabs import common as dialog_module

        result, placement, coarse, *_rest = run_output
        dialog.show_result(result, placement, coarse)
        dialog.maf.spin.setValue(0.31)  # fiddling after the fact

        target = tmp_path / "out.csv"
        monkeypatch.setattr(
            dialog_module.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        monkeypatch.setattr(
            dialog_module.QMessageBox, "information", staticmethod(lambda *a, **k: None)
        )
        dialog.export_csv()

        rows = list(csv.reader(target.open(encoding="utf-8-sig")))
        recorded = {r[0]: r[1] for r in rows if len(r) == 2}
        assert recorded["MAF (Figure 3)"] == f"{result.inputs.maf:.2f}" != "0.31"

    def test_styling_applies_without_error(self, run_output):
        from pmp_toolbox import qgis_bridge, styling

        result, placement, _coarse, clipped, crs, _raster = run_output
        outlines, rings = qgis_bridge.build_output_layers(
            result, placement, clipped, crs
        )
        styling.style_rainfall(rings, [r.label for r in result.rings])
        styling.style_outlines(outlines)

        assert rings.renderer().classAttribute() == "Ellipse"
        assert len(rings.renderer().categories()) == len(result.rings)
        assert rings.labelsEnabled()
        assert outlines.labelsEnabled()

    def test_output_fields_survive_the_provider(self, run_output):
        from pmp_toolbox import qgis_bridge

        result, placement, _coarse, clipped, crs, _raster = run_output
        outlines, _rings = qgis_bridge.build_output_layers(
            result, placement, clipped, crs
        )
        names = [f.name() for f in outlines.fields()]
        assert names == [n for n, _t, _l in qgis_bridge.OUTPUT_FIELDS]
        feature = next(outlines.getFeatures())
        assert feature["Ellipse"] == result.rings[0].label
        assert feature["MRD"] == pytest.approx(result.rings[0].mrd)
        assert feature.geometry().area() > 0


class TestTemporaryShapefiles:
    """Outputs written to .shp rather than held as in-memory scratch layers."""

    @pytest.fixture
    def written(self, run_output, tmp_path):
        from pmp_toolbox import qgis_bridge

        result, placement, _coarse, clipped, crs, _raster = run_output
        outlines, rings = qgis_bridge.build_output_layers(
            result, placement, clipped, crs, name_prefix="GSDM test"
        )
        return (
            *qgis_bridge.save_as_temp_shapefiles(outlines, rings, tmp_path),
            result,
        )

    def test_files_land_on_disk(self, written):
        _outlines, _rings, folder, _result = written
        shapefiles = sorted(p.name for p in folder.glob("*.shp"))
        assert len(shapefiles) == 2
        for shp in folder.glob("*.shp"):
            # A shapefile is only usable with its sidecars.
            for suffix in (".dbf", ".shx", ".prj"):
                assert shp.with_suffix(suffix).exists(), f"missing {suffix}"

    def test_layers_are_file_backed(self, written):
        outlines, rings, _folder, _result = written
        for layer in (outlines, rings):
            assert layer.isValid()
            assert layer.dataProvider().name() == "ogr"
            assert layer.source().endswith(".shp")

    def test_no_field_name_is_truncated(self, written):
        """DBF caps attribute names at 10 characters; ours must already fit."""
        from pmp_toolbox import qgis_bridge

        outlines, _rings, _folder, _result = written
        names = [f.name() for f in outlines.fields()]
        assert names == [n for n, _t, _l in qgis_bridge.OUTPUT_FIELDS]
        assert all(len(n) <= 10 for n in names)

    def test_attributes_and_geometry_survive_the_round_trip(self, written):
        outlines, _rings, _folder, result = written
        assert outlines.featureCount() == len(result.rings)
        by_label = {f["Ellipse"]: f for f in outlines.getFeatures()}
        for ring in result.rings:
            feature = by_label[ring.label]
            assert feature["MRD"] == pytest.approx(ring.mrd, abs=1e-6)
            assert feature["CBtn"] == pytest.approx(ring.cbtn, abs=1e-6)
            assert feature["EllipseKm2"] == pytest.approx(ring.ellipse_area_km2)
            assert feature.geometry().area() > 0

    def test_crs_is_preserved(self, written, run_output):
        outlines, rings, _folder, _result = written
        crs = run_output[4]
        for layer in (outlines, rings):
            assert layer.crs().authid() == crs.authid()

    def test_ellipse_areas_match_the_template(self, written):
        """The written geometry really is the GSDM template, not a bounding box."""
        outlines, _rings, _folder, _result = written
        for feature in outlines.getFeatures():
            assert feature.geometry().area() / 1.0e6 == pytest.approx(
                feature["EllipseKm2"], rel=1e-3
            )

    def test_two_runs_do_not_collide(self, run_output):
        """Each run gets its own folder, so a second run cannot overwrite a first."""
        from pmp_toolbox import qgis_bridge

        result, placement, _coarse, clipped, crs, _raster = run_output
        made = []
        for _ in range(2):
            outlines, rings = qgis_bridge.build_output_layers(
                result, placement, clipped, crs, name_prefix="GSDM test"
            )
            made.append(qgis_bridge.save_as_temp_shapefiles(outlines, rings)[2])
        assert made[0] != made[1]
        assert all(len(list(f.glob("*.shp"))) == 2 for f in made)

    def test_styling_applies_to_the_written_layers(self, written):
        from pmp_toolbox import styling

        outlines, rings, _folder, result = written
        styling.style_rainfall(rings, [r.label for r in result.rings])
        styling.style_outlines(outlines)
        assert rings.renderer().classAttribute() == "Ellipse"
        assert rings.labelsEnabled()


class TestPluginEntryPoint:
    def test_class_factory_builds_the_plugin(self, gui_app):
        """The path QGIS itself takes when loading the plugin."""
        import pmp_toolbox
        from pmp_toolbox.plugin import PmpToolboxPlugin

        plugin = pmp_toolbox.classFactory(iface=None)
        assert isinstance(plugin, PmpToolboxPlugin)
        assert plugin.action is None  # not built until initGui

    def test_metadata_declares_what_qgis_requires(self):
        import configparser

        parser = configparser.ConfigParser()
        parser.read(
            Path(__file__).resolve().parents[1] / "metadata.txt", encoding="utf-8"
        )
        general = parser["general"]
        for key in ("name", "qgisMinimumVersion", "description", "version", "author"):
            assert general.get(key), f"metadata.txt is missing {key}"
        import pmp_toolbox

        assert general["version"] == pmp_toolbox.__version__


class TestGeographicCrsIsRefused:
    """Areas and axis lengths are ground distances, so degrees will not do.

    The picker refuses rather than guessing a projection, and it does so in one
    place, which is what makes the refusal identical on all three tabs.
    """

    @pytest.fixture
    def geographic_layer(self, gui_app):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "degrees", "memory")
        feature = QgsFeature()
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((133 -24, 134 -24, 134 -23, 133 -23, 133 -24))"
            )
        )
        layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        yield layer
        QgsProject.instance().removeMapLayer(layer.id())

    def _picker_for(self, tab, layer):
        tab.picker.layer_combo.setLayer(layer)
        return tab.picker

    def test_the_areal_tab_refuses_it(self, dialog, geographic_layer):
        picker = self._picker_for(dialog, geographic_layer)
        try:
            assert picker.catchment() is None
            assert "geographic" in picker.error().lower()
        finally:
            picker.layer_combo.setLayer(None)

    def test_the_gsdm_tab_refuses_it(self, gui_app, geographic_layer):
        from pmp_toolbox.tabs.gsdm_tab import GsdmTab

        tab = GsdmTab()
        picker = self._picker_for(tab, geographic_layer)
        try:
            assert picker.catchment() is None
            assert "geographic" in picker.error().lower()
        finally:
            picker.layer_combo.setLayer(None)

    def test_the_gtsmr_tab_refuses_it(self, gui_app, geographic_layer):
        from pmp_toolbox.tabs.gtsmr_tab import GtsmrTab

        tab = GtsmrTab()
        picker = self._picker_for(tab, geographic_layer)
        try:
            assert picker.catchment() is None
            assert "geographic" in picker.error().lower()
        finally:
            picker.layer_combo.setLayer(None)
