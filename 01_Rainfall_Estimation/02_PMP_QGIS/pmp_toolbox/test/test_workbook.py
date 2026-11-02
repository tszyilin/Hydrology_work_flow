"""The project workbook: one .xlsx holding every tab's cases.

The value of a project file is entirely in the round-trip.  A file that saves
but reopens subtly wrong is worse than no file at all, because the difference
is invisible until someone reruns a job months later and gets a different
number.  So most of this file is about reopening, not writing.

Three things need care, and each has a test:

* the catchment **layer** is a live QGIS object, stored by name and resolved
  against whatever is open when the file is read;
* the nested inputs -- sampled grid factors, the zone reading, the ring
  weights -- go into one cell as JSON, and the factor pairs must come back as
  pairs rather than lists;
* **results are not read back**. They are output. A workbook someone has
  edited must not be able to put numbers on screen that no calculation
  produced.

Needs QGIS for the tabs and openpyxl for the file, so it skips without either.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")
openpyxl = pytest.importorskip("openpyxl", reason="project files need openpyxl")

from qgis.core import QgsProject, QgsVectorLayer  # noqa: E402

from pmp_toolbox import workbook  # noqa: E402

CATCHMENTS = ROOT / "01_example catchments"


@pytest.fixture(scope="module")
def _app(qgis_app):
    return qgis_app


def _dispose(*tabs):
    from qgis.PyQt.QtWidgets import QApplication

    for tab in tabs:
        tab.picker.layer_combo.setLayer(None)
        tab.setParent(None)
        tab.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def layer(_app):
    path = CATCHMENTS / "catchment_B_area.shp"
    if not path.exists():
        pytest.skip("example catchment not found")
    lyr = QgsVectorLayer(str(path), "catchment_B", "ogr")
    assert lyr.isValid()
    QgsProject.instance().addMapLayer(lyr)
    yield lyr
    QgsProject.instance().removeMapLayer(lyr.id())


@pytest.fixture
def silent(monkeypatch):
    from pmp_toolbox.tabs import common, gsdm_tab, gtsmr_tab

    raised = []
    for module in (gsdm_tab, gtsmr_tab, common):
        for name in ("warning", "critical", "information"):
            monkeypatch.setattr(
                module.QMessageBox,
                name,
                staticmethod(lambda *a, _n=name, **k: raised.append((_n, a[1]))),
            )
    return raised


@pytest.fixture
def tabs(_app, layer):
    """All three tabs, pointed at one catchment, as the plugin builds them."""
    from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab
    from pmp_toolbox.tabs.gsdm_tab import GsdmTab
    from pmp_toolbox.tabs.gtsmr_tab import GtsmrTab

    gsdm, areal, gtsmr = GsdmTab(), ArealGsdmTab(iface=None), GtsmrTab()
    for tab in (gsdm, areal, gtsmr):
        tab.picker.layer_combo.setLayer(layer)
    areal.show_preview.setChecked(False)
    areal.as_shapefile.setChecked(False)
    areal.sampling.setValue(150)
    areal.rotations.setValue(3)
    pairs = [("GSDM", gsdm), ("Areal GSDM", areal), ("GTSMR", gtsmr)]
    yield pairs
    _dispose(gsdm, areal, gtsmr)


def _snapshot(pairs):
    """The comparable part of every case: its name and its inputs."""
    out = {}
    for key, tab in pairs:
        out[key] = [
            (
                case.name,
                {
                    k: (v.name() if k == "layer" and v is not None else v)
                    for k, v in case.inputs.items()
                    if not k.startswith("_")
                },
            )
            for case in tab.cases.cases()
        ]
    return out


class TestRoundTrip:
    def test_saving_writes_a_sheet_pair_per_tab(self, tabs, tmp_path):
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        names = openpyxl.load_workbook(path).sheetnames
        assert names[0] == "Summary"
        for key in ("GSDM", "Areal GSDM", "GTSMR"):
            assert f"{key} Inputs" in names
            assert f"{key} Results" in names

    def test_the_summary_has_a_row_per_case(self, tabs, tmp_path, silent):
        tabs[0][1].run()
        tabs[0][1].cases.add_case("Second")
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        sheet = openpyxl.load_workbook(path)["Summary"]
        rows = [r for r in sheet.iter_rows(values_only=True) if r and r[0] == "GSDM"]
        assert [r[1] for r in rows] == ["Case 1", "Second"]
        # The case that was calculated says so; the one that was not does not.
        assert [r[5] for r in rows] == ["yes", "no"]

    def test_inputs_survive_the_round_trip(self, tabs, tmp_path, silent):
        gsdm = tabs[0][1]
        gsdm.cases.add_case("50% smooth")
        gsdm.smooth.setValue(50)
        gtsmr = tabs[2][1]
        gtsmr.gtsmr_taf.spin.setValue(1.3)

        before = _snapshot(tabs)
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        # Change everything, then reopen.
        gsdm.smooth.setValue(100)
        gsdm.cases.add_case("junk")
        gtsmr.gtsmr_taf.spin.setValue(9.9)

        report = workbook.load_project(path, tabs)
        assert report["missing"] == []
        assert _snapshot(tabs) == before

    def test_the_layer_comes_back_as_the_open_layer(self, tabs, tmp_path, layer):
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        workbook.load_project(path, tabs)
        for _key, tab in tabs:
            restored = tab.cases.current().inputs.get("layer")
            assert restored is layer, "the layer must resolve to the open one"

    def test_a_missing_layer_is_not_fatal(self, tabs, tmp_path):
        """A project opened without its layer keeps every other input.

        Saved against a throwaway layer which is then closed, rather than
        against the shared fixture: removing a layer from the project destroys
        the underlying C++ object, so it cannot be put back afterwards.
        """
        from qgis.core import QgsFeature, QgsGeometry

        temporary = QgsVectorLayer("Polygon?crs=EPSG:7853", "closed later", "memory")
        feature = QgsFeature()
        feature.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((500000 7480000, 510000 7480000, "
                "510000 7490000, 500000 7490000, 500000 7480000))"
            )
        )
        temporary.dataProvider().addFeatures([feature])
        temporary.updateExtents()
        QgsProject.instance().addMapLayer(temporary)

        gsdm = tabs[0][1]
        gsdm.picker.layer_combo.setLayer(temporary)
        gsdm.smooth.setValue(35)
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        gsdm.picker.layer_combo.setLayer(None)
        QgsProject.instance().removeMapLayer(temporary.id())

        workbook.load_project(path, tabs)
        case = gsdm.cases.current()
        assert case.inputs.get("layer") is None, "the layer is gone"
        assert case.inputs.get("smooth") == 35, "everything else survives"

    def test_grid_factors_come_back_as_pairs(self, tabs, tmp_path):
        """JSON turns tuples into lists; the factor rows expect pairs."""
        gtsmr = tabs[2][1]
        gtsmr.gtsmr_taf.spin.setValue(1.25)
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        workbook.load_project(path, tabs)

        factors = gtsmr.cases.current().inputs["factors"]
        value, overridden = factors["gtsmr_taf"]
        assert value == pytest.approx(1.25)
        assert overridden is True, "a typed value must still read as typed"

    def test_the_gtsmr_lock_survives_the_round_trip(self, tabs, tmp_path):
        """Whether a value was the Bureau's or the engineer's is part of the job.

        A project that reopened unlocked would lose the record that these six
        numbers came off the grids untouched.
        """
        gtsmr = tabs[2][1]
        gtsmr.lock_button.setChecked(True)
        gtsmr.gtsmr_taf.spin.setValue(1.42)

        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        gtsmr.lock_button.setChecked(False)
        workbook.load_project(path, tabs)

        assert not gtsmr.locked(), "the case was saved unlocked"
        assert gtsmr.gtsmr_taf.value() == pytest.approx(1.42)
        assert not gtsmr.gtsmr_taf.spin.isReadOnly()

    def test_a_locked_case_reopens_locked(self, tabs, tmp_path):
        gtsmr = tabs[2][1]
        assert gtsmr.locked()
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        gtsmr.lock_button.setChecked(True)
        workbook.load_project(path, tabs)
        assert gtsmr.locked()
        assert gtsmr.gtsmr_epw_s.spin.isReadOnly()

    def test_opening_replaces_the_cases_rather_than_adding_to_them(
        self, tabs, tmp_path
    ):
        gsdm = tabs[0][1]
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        gsdm.cases.add_case("extra one")
        gsdm.cases.add_case("extra two")
        workbook.load_project(path, tabs)
        assert [c.name for c in gsdm.cases.cases()] == ["Case 1"]

    def test_results_are_not_restored_from_the_file(self, tabs, tmp_path, silent):
        """Results are output. A file must not put numbers on screen."""
        gsdm = tabs[0][1]
        gsdm.run()
        assert gsdm.cases.current().result is not None

        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        workbook.load_project(path, tabs)

        assert all(c.result is None for c in gsdm.cases.cases())
        assert gsdm.table.rowCount() == 0
        assert not gsdm.export_button.isEnabled()

    def test_recomputing_after_a_reopen_gives_the_same_answer(
        self, tabs, tmp_path, silent
    ):
        """The point of the whole exercise."""
        gsdm = tabs[0][1]
        gsdm.run()
        expected = gsdm.summary.text()

        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        workbook.load_project(path, tabs)
        gsdm.run()

        assert gsdm.summary.text() == expected


class TestResultsSheet:
    def test_a_calculated_case_writes_its_table_and_its_inputs(
        self, tabs, tmp_path, silent
    ):
        gsdm = tabs[0][1]
        gsdm.run()
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")

        rows = list(
            openpyxl.load_workbook(path)["GSDM Results"].iter_rows(values_only=True)
        )
        flat = [r[0] for r in rows if r and r[0] is not None]
        assert "Case 1" in flat
        assert "Duration (hr)" in flat, "the header must be the flat one"
        assert "Run inputs" in flat, "a table without its inputs cannot be audited"

    def test_an_uncalculated_tab_says_so_rather_than_leaving_a_blank_sheet(
        self, tabs, tmp_path
    ):
        path = tmp_path / "job.xlsx"
        workbook.save_project(path, tabs, project_name="job")
        sheet = openpyxl.load_workbook(path)["GSDM Results"]
        first = next(sheet.iter_rows(values_only=True))
        assert "No case" in str(first[0])


class TestSerialisation:
    """The conversion either way, without a spreadsheet in the middle."""

    def test_underscore_keys_are_dropped(self):
        out = workbook.serialise_inputs({"smooth": 10, "_summary": "<b>x</b>"})
        assert out == {"smooth": 10}

    def test_nested_values_become_json(self):
        out = workbook.serialise_inputs({"weights": [1.0, 2.0]})
        assert out["weights"] == "[1.0, 2.0]"

    def test_none_becomes_blank_not_the_word_none(self):
        out = workbook.serialise_inputs({"duration_limit": None})
        assert out["duration_limit"] == ""

    def test_json_round_trips(self):
        original = {"factors": {"taf": (1.25, True)}}
        back = workbook.deserialise_inputs(workbook.serialise_inputs(original))
        assert back["factors"]["taf"] == (1.25, True)


class TestWithoutOpenpyxl:
    def test_the_error_says_how_to_fix_it(self, monkeypatch):
        """QGIS does not ship openpyxl, so this is a path users will hit."""
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("no openpyxl")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        with pytest.raises(workbook.WorkbookError) as caught:
            workbook._openpyxl()
        assert "pip install openpyxl" in str(caught.value)
        assert "export CSV" in str(caught.value), (
            "the message should say what still works"
        )
