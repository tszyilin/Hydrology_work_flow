"""The GSDM and GTSMR/GSAM tabs, driven the way a user drives them.

The calculation behind these tabs is already pinned down by
``test_depth_parity`` and ``test_worked_examples``.  What is untested until
here is the wiring: that choosing a layer fills the derived fields in, that
pressing Calculate puts the right numbers on screen, that a value typed by hand
survives, and that the export carries the provenance without which the table
cannot be audited.

Needs QGIS, so the whole file skips outside it.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")

from qgis.core import QgsProject, QgsVectorLayer  # noqa: E402

CATCHMENTS = ROOT / "01_example catchments"


@pytest.fixture(scope="module")
def _app(qgis_app):
    return qgis_app


def _dispose(*tabs):
    """Destroy tab widgets now rather than whenever Python gets round to it.

    A tab holds a QgsMapLayerComboBox, which is connected to the project.  If
    Python frees the widget after QgsApplication has shut down -- which is
    exactly what happens when the garbage collector runs late in a session --
    the interpreter segfaults.  Deleting them here keeps that deterministic.
    """
    from qgis.PyQt.QtWidgets import QApplication

    for tab in tabs:
        tab.picker.layer_combo.setLayer(None)
        tab.setParent(None)
        tab.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def catchment_layer(_app):
    path = CATCHMENTS / "catchment_B_area.shp"
    if not path.exists():
        pytest.skip("example catchment not found")
    layer = QgsVectorLayer(str(path), "catchment_B", "ogr")
    assert layer.isValid()
    QgsProject.instance().addMapLayer(layer)
    yield layer
    QgsProject.instance().removeMapLayer(layer.id())


@pytest.fixture
def silent(monkeypatch):
    """Record message boxes instead of showing them; a modal would hang."""
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


# ------------------------------------------------------------------ GSDM tab


@pytest.fixture
def gsdm(_app, catchment_layer):
    from pmp_toolbox.tabs.gsdm_tab import GsdmTab

    tab = GsdmTab()
    tab.picker.layer_combo.setLayer(catchment_layer)
    yield tab
    _dispose(tab)


class TestGsdmTab:
    def test_the_catchment_fills_area_and_centroid_in(self, gsdm):
        catchment = gsdm.picker.catchment()
        assert catchment is not None
        # The example catchments are in central Australia.
        assert -44.0 < catchment.lat < -8.0
        assert 110.0 < catchment.lon < 156.0
        assert catchment.area_km2 > 0
        assert f"{catchment.area_km2:,.3f}" in gsdm.picker.summary.text()

    def test_the_maf_is_read_off_figure_3(self, gsdm):
        assert gsdm.maf.value() == pytest.approx(0.83, abs=0.05)
        assert "Figure 3" in gsdm.maf.note.text()

    def test_the_duration_limit_is_read_off_figure_2(self, gsdm):
        assert gsdm.duration_limit.currentData() in (3.0, 6.0)
        assert "Figure 2" in gsdm.duration_note.text() or "intermediate" in (
            gsdm.duration_note.text()
        )

    def test_calculate_populates_the_table(self, gsdm, silent):
        gsdm.run()
        assert silent == [], f"a message box was raised: {silent}"
        assert gsdm.table.rowCount() > 0
        assert gsdm.export_button.isEnabled()
        assert "PMP" in gsdm.summary.text()

    def test_every_row_is_at_or_below_the_duration_limit(self, gsdm, silent):
        gsdm.run()
        limit = gsdm.duration_limit.currentData()
        durations = [
            float(gsdm.table.item(r, 0).text()) for r in range(gsdm.table.rowCount())
        ]
        assert durations, "no durations in the table"
        assert max(durations) <= limit

    def test_the_areal_depth_never_exceeds_the_point_depth(self, gsdm, silent):
        """Areal reduction only ever takes depth away."""
        gsdm.run()
        for r in range(gsdm.table.rowCount()):
            areal = float(gsdm.table.item(r, 1).text().replace(",", ""))
            point = float(gsdm.table.item(r, 2).text().replace(",", ""))
            assert areal <= point, f"row {r}: areal {areal} > point {point}"

    def test_a_typed_maf_is_not_overwritten_by_the_next_lookup(self, gsdm):
        gsdm.maf.spin.setValue(0.42)
        gsdm.picker.refresh()  # as a layer change would
        assert gsdm.maf.value() == pytest.approx(0.42)
        assert gsdm.maf.provenance() == "entered by hand"

    def test_the_button_overrides_a_typed_value(self, gsdm):
        gsdm.maf.spin.setValue(0.42)
        gsdm.maf.button.click()
        assert gsdm.maf.value() != pytest.approx(0.42)
        assert "Figure 3" in gsdm.maf.provenance()

    def test_a_larger_maf_gives_a_deeper_pmp(self, gsdm, silent):
        """The moisture factor multiplies through, so this must be monotonic."""
        gsdm.maf.spin.setValue(0.60)
        gsdm.run()
        low = float(gsdm.table.item(0, 1).text().replace(",", ""))
        gsdm.maf.spin.setValue(1.10)
        gsdm.run()
        high = float(gsdm.table.item(0, 1).text().replace(",", ""))
        assert high > low

    def test_the_export_records_what_produced_the_table(
        self, gsdm, silent, tmp_path, monkeypatch
    ):
        from pmp_toolbox.tabs import common

        gsdm.run()
        target = tmp_path / "gsdm.csv"
        monkeypatch.setattr(
            common.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        gsdm._export()

        rows = list(csv.reader(target.open(encoding="utf-8-sig")))
        assert rows[0][0] == "Duration (hr)", "the table must stay on row 1"
        recorded = {r[0]: r[1] for r in rows if len(r) == 2}
        assert recorded["Method"] == "GSDM (catchment-average)"
        assert recorded["MAF (Figure 3)"] == f"{gsdm.maf.value():.2f}"
        assert recorded["MAF source"]
        assert recorded["Duration limit source"]
        assert float(recorded["Area (km2)"]) > 0
        assert float(recorded["PMP (mm)"]) > 0

    def test_running_without_a_layer_warns_rather_than_crashing(self, gsdm, silent):
        gsdm.picker.layer_combo.setLayer(None)
        gsdm.run()
        assert silent, "expected a warning"
        assert not gsdm.export_button.isEnabled()


# ------------------------------------------------------------ GTSMR/GSAM tab


@pytest.fixture
def gtsmr(_app, catchment_layer):
    from pmp_toolbox.tabs.gtsmr_tab import GtsmrTab

    tab = GtsmrTab()
    tab.picker.layer_combo.setLayer(catchment_layer)
    yield tab
    _dispose(tab)


class TestGtsmrTab:
    def test_the_zone_lookup_decides_which_methods_are_offered(self, gtsmr):
        """A method the catchment is not in must not be runnable."""
        assert gtsmr.use_gtsmr.isEnabled() or gtsmr.use_gsam.isEnabled(), (
            "neither method offered for a catchment in central Australia"
        )
        # Whatever is disabled must also be unchecked, or Calculate would run it.
        for box in (gtsmr.use_gtsmr, gtsmr.use_gsam):
            if not box.isEnabled():
                assert not box.isChecked()

    def test_the_grid_factors_are_sampled(self, gtsmr):
        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        assert gtsmr.gtsmr_epw_s.value() > 0
        assert gtsmr.gtsmr_taf.value() > 0
        assert gtsmr.gtsmr_epw_s.provenance() == "sampled at centroid"

    def test_the_two_guidebooks_standards_are_not_confused(self, gtsmr):
        """GSAM's standard EPW is not GTSMR's; carrying one across is a real
        and easy mistake, so the defaults are asserted explicitly."""
        assert gtsmr.gtsmr_std_s.value() == pytest.approx(120.0)
        assert gtsmr.gtsmr_std_w.value() == pytest.approx(82.3)
        assert gtsmr.gsam_std_s.value() == pytest.approx(80.8)
        assert gtsmr.gsam_std_a.value() == pytest.approx(71.0)

    def test_calculate_populates_the_table(self, gtsmr, silent):
        if not (gtsmr.use_gtsmr.isEnabled() or gtsmr.use_gsam.isEnabled()):
            pytest.skip("no method applies here")
        gtsmr.run()
        assert silent == [], f"a message box was raised: {silent}"
        assert gtsmr.table.rowCount() > 0
        assert "Governing" in gtsmr.summary.text()
        assert gtsmr.export_button.isEnabled()

    def test_the_durations_are_the_long_ones(self, gtsmr, silent):
        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        gtsmr.run()
        durations = []
        for r in range(gtsmr.table.rowCount()):
            text = gtsmr.table.item(r, 0).text()
            if not text.startswith("—"):
                durations.append(float(text))
        assert min(durations) >= 24.0
        assert max(durations) <= 120.0

    def test_running_with_nothing_selected_warns(self, gtsmr, silent):
        gtsmr.use_gtsmr.setChecked(False)
        gtsmr.use_gsam.setChecked(False)
        gtsmr.run()
        assert silent, "expected a warning"

    def test_the_export_records_the_grid_factors(
        self, gtsmr, silent, tmp_path, monkeypatch
    ):
        from pmp_toolbox.tabs import common

        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        gtsmr.run()
        target = tmp_path / "gtsmr.csv"
        monkeypatch.setattr(
            common.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (str(target), "")),
        )
        gtsmr._export()

        rows = list(csv.reader(target.open(encoding="utf-8-sig")))
        assert rows[0][0] == "Duration (hr)"
        recorded = {r[0]: r[1] for r in rows if len(r) == 2}
        assert recorded["Grid sampling"] == "at the catchment centroid"
        assert float(recorded["GTSMR EPW summer (mm)"]) > 0
        assert float(recorded["GTSMR TAF"]) > 0
        assert recorded["Governing method"] in ("GTSMR", "GSAM")
        assert float(recorded["Governing PMP (mm)"]) > 0


# -------------------------------------------------------------- all together


class TestAllThreeTabs:
    def test_they_agree_on_the_catchment(self, _app, catchment_layer):
        """One layer, three tabs, one area and one centroid.

        The tabs each hold their own picker, so this is the check that they
        are all deriving the catchment the same way rather than three
        subtly different ways.
        """
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab
        from pmp_toolbox.tabs.gsdm_tab import GsdmTab
        from pmp_toolbox.tabs.gtsmr_tab import GtsmrTab

        tabs = [GsdmTab(), ArealGsdmTab(iface=None), GtsmrTab()]
        try:
            for tab in tabs:
                tab.picker.layer_combo.setLayer(catchment_layer)
            found = [tab.picker.catchment() for tab in tabs]
            assert all(c is not None for c in found)
            areas = {round(c.area_km2, 6) for c in found}
            centroids = {(round(c.lat, 9), round(c.lon, 9)) for c in found}
            assert len(areas) == 1, areas
            assert len(centroids) == 1, centroids
        finally:
            _dispose(*tabs)

    def test_the_gsdm_tabs_agree_on_the_moisture_factor(self, _app, catchment_layer):
        """Both GSDM tabs read the same Figure 3 through the same helper."""
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab
        from pmp_toolbox.tabs.gsdm_tab import GsdmTab

        tabs = [GsdmTab(), ArealGsdmTab(iface=None)]
        try:
            for tab in tabs:
                tab.picker.layer_combo.setLayer(catchment_layer)
            assert tabs[0].maf.value() == pytest.approx(tabs[1].maf.value())
        finally:
            _dispose(*tabs)


class TestWebsiteDefaults:
    """The tabs must open on the same defaults as the Toolbox website.

    The arithmetic agreeing is not enough for the two to agree: the answer a
    user actually sees depends just as much on what the form is set to when it
    opens.  The terrain split is the sharp case -- the rough curves are about
    a quarter deeper than the smooth ones at 3 hours, so a tab defaulting to
    smooth would disagree with the website on every catchment while every
    parity test still passed.
    """

    def test_the_gsdm_tab_opens_on_the_website_terrain_split(self, gsdm):
        assert gsdm.smooth.value() == 0
        assert "100 % rough" in gsdm.rough_label.text()

    def test_the_areal_tab_agrees_with_it(self, _app, catchment_layer):
        """Two tabs offering GSDM must not disagree about the default terrain."""
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab

        tab = ArealGsdmTab(iface=None)
        try:
            assert tab.smooth.value() == 0
            assert tab.inputs().rough == pytest.approx(1.0)
        finally:
            _dispose(tab)

    def test_the_gsdm_tab_reproduces_the_website_backend(self, gsdm, silent):
        """End to end: derived inputs in, website's own calculate() alongside.

        Skips where the website checkout or pandas is unavailable, which is the
        normal case under the QGIS interpreter -- so this is a plain-Python
        check that happens to need QGIS for the tab.
        """
        backend = ROOT.parent / "18_Toolbox_website" / "backend"
        if not backend.is_dir():
            pytest.skip(f"Toolbox website checkout not found at {backend}")
        pytest.importorskip("pandas", reason="the website backend needs pandas")
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from calculators import pmp as website

        catchment = gsdm.picker.catchment()
        gsdm.run()
        mine = [
            (float(gsdm.table.item(r, 0).text()),
             float(gsdm.table.item(r, 1).text().replace(",", "")))
            for r in range(gsdm.table.rowCount())
        ]

        theirs_result = website.calculate([{
            "name": "t",
            "area": catchment.area_km2,
            "gsdm_enabled": True,
            "gsdm": {
                "duration_limit": gsdm.duration_limit.currentData(),
                "smooth_fraction": gsdm.smooth.value(),
                "rough_fraction": 100 - gsdm.smooth.value(),
                "elevation_factor": 1.0,
                "moisture_factor": gsdm.maf.value(),
            },
        }])[0]["gsdm"]
        theirs = [
            (float(d["duration_hr"]), float(d["pmp_mm"]))
            for d in theirs_result["by_duration"]
        ]

        assert mine == theirs


class TestCases:
    """Cases are independent runs, and switching between them must be lossless.

    The trap here is that a tab holds one set of widgets shared by every case,
    so a case is only as good as the capture-and-restore around a switch.  The
    first version of this dropped each case's *results* on switching away,
    because capturing the inputs replaced the dict they were stored in -- the
    inputs came back correctly and the answer silently did not.  These tests
    check both halves.
    """

    def test_a_tab_starts_with_one_case(self, gsdm):
        assert [c.name for c in gsdm.cases.cases()] == ["Case 1"]
        assert gsdm.cases.current() is not None

    def test_adding_a_case_copies_the_current_inputs(self, gsdm):
        gsdm.smooth.setValue(40)
        gsdm.cases.add_case("Second")
        assert gsdm.smooth.value() == 40, "a new case starts from the current one"
        assert [c.name for c in gsdm.cases.cases()] == ["Case 1", "Second"]

    def test_cases_keep_their_own_inputs(self, gsdm):
        gsdm.smooth.setValue(0)
        gsdm.cases.add_case("Half smooth")
        gsdm.smooth.setValue(50)

        gsdm.cases.list.setCurrentRow(0)
        assert gsdm.smooth.value() == 0
        gsdm.cases.list.setCurrentRow(1)
        assert gsdm.smooth.value() == 50

    def test_switching_away_and_back_keeps_the_results(self, gsdm, silent):
        gsdm.run()
        first = gsdm.summary.text()
        first_rows = gsdm.table.rowCount()
        assert first and first_rows

        gsdm.cases.add_case("Second")
        gsdm.smooth.setValue(50)
        gsdm.run()
        assert gsdm.summary.text() != first

        gsdm.cases.list.setCurrentRow(0)
        assert gsdm.summary.text() == first
        assert gsdm.table.rowCount() == first_rows
        assert gsdm.export_button.isEnabled()

    def test_an_uncalculated_case_shows_nothing_rather_than_the_last_one(
        self, gsdm, silent
    ):
        """Stale results under a different case's name would be worse than none."""
        gsdm.run()
        assert gsdm.table.rowCount() > 0
        gsdm.cases.add_case("Not yet run")
        assert gsdm.table.rowCount() == 0
        assert not gsdm.export_button.isEnabled()
        assert "Not calculated" in gsdm.summary.text()

    def test_a_different_terrain_split_gives_a_different_answer(self, gsdm, silent):
        """The two cases must not quietly share one result object."""
        gsdm.smooth.setValue(0)
        gsdm.run()
        rough_only = float(gsdm.table.item(gsdm.table.rowCount() - 1, 1)
                           .text().replace(",", ""))

        gsdm.cases.add_case("All smooth")
        gsdm.smooth.setValue(100)
        gsdm.run()
        smooth_only = float(gsdm.table.item(gsdm.table.rowCount() - 1, 1)
                            .text().replace(",", ""))

        # Rough terrain is the deeper curve at 3 hours.
        assert rough_only > smooth_only

    def test_calculate_all_cases_runs_every_one(self, gsdm, silent):
        gsdm.cases.add_case("Second")
        gsdm.smooth.setValue(50)
        gsdm.cases.add_case("Third")
        gsdm.smooth.setValue(100)

        gsdm.run_all()
        assert silent == [], f"a message box was raised: {silent}"
        assert all(c.result is not None for c in gsdm.cases.cases())

    def test_removing_the_last_case_clears_rather_than_deleting_it(
        self, gsdm, silent
    ):
        """A tab with no cases has nowhere to put the inputs on screen."""
        gsdm.run()
        gsdm.cases.remove_current()
        assert len(gsdm.cases.cases()) == 1
        assert gsdm.cases.current().result is None
        assert gsdm.table.rowCount() == 0

    def test_removing_a_case_leaves_the_others(self, gsdm, silent):
        gsdm.cases.add_case("Second")
        gsdm.cases.add_case("Third")
        gsdm.cases.remove_current()
        assert [c.name for c in gsdm.cases.cases()] == ["Case 1", "Second"]

    def test_the_all_cases_plot_has_a_column_per_calculated_case(
        self, gsdm, silent
    ):
        if not gsdm.plots.available:
            pytest.skip("matplotlib not available")
        gsdm.run()
        gsdm.cases.add_case("Second")
        gsdm.smooth.setValue(50)
        gsdm.run()

        table = gsdm.plots._pages["All cases"]["table"]
        assert table is not None
        assert table.headers == ["Duration (hr)", "Case 1", "Second"]
        assert len(table.rows) == gsdm.table.rowCount()

    def test_the_plot_panel_offers_both_views(self, gsdm):
        if not gsdm.plots.available:
            pytest.skip("matplotlib not available")
        titles = [gsdm.plots.tabText(i) for i in range(gsdm.plots.count())]
        assert "Depth-duration" in titles and "All cases" in titles


class TestGtsmrCases:
    """The same case machinery, on the tab whose inputs are grid factors."""

    def test_a_typed_factor_survives_a_case_switch(self, gtsmr):
        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        gtsmr.gtsmr_taf.spin.setValue(1.4321)
        gtsmr.cases.add_case("Second")
        gtsmr.gtsmr_taf.spin.setValue(1.0)

        gtsmr.cases.list.setCurrentRow(0)
        assert gtsmr.gtsmr_taf.value() == pytest.approx(1.4321)
        assert gtsmr.gtsmr_taf.overridden, (
            "a value typed by hand must still read as typed after a switch"
        )

    def test_cases_keep_their_own_results(self, gtsmr, silent):
        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        gtsmr.run()
        first = gtsmr.summary.text()

        gtsmr.cases.add_case("Double TAF")
        gtsmr.gtsmr_taf.spin.setValue(gtsmr.gtsmr_taf.value() * 2)
        gtsmr.run()
        assert gtsmr.summary.text() != first

        gtsmr.cases.list.setCurrentRow(0)
        assert gtsmr.summary.text() == first


class TestArealCases:
    """The Areal GSDM tab, where each case costs a full placement search."""

    @pytest.fixture
    def areal(self, _app, catchment_layer):
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab

        tab = ArealGsdmTab(iface=None)
        tab.picker.layer_combo.setLayer(catchment_layer)
        tab.show_preview.setChecked(False)
        tab.sampling.setValue(140)
        tab.rotations.setValue(3)
        yield tab
        _dispose(tab)

    def test_it_starts_with_one_case(self, areal):
        assert [c.name for c in areal.cases.cases()] == ["Case 1"]

    def test_inputs_are_kept_per_case(self, areal):
        areal.sampling.setValue(140)
        areal.cases.add_case("Finer")
        areal.sampling.setValue(90)

        areal.cases.list.setCurrentRow(0)
        assert areal.sampling.value() == 140
        areal.cases.list.setCurrentRow(1)
        assert areal.sampling.value() == 90

    def test_an_edited_weight_is_not_reset_by_a_case_switch(self, areal):
        """An edited weight is a deliberate override, not a stale default."""
        from pmp_toolbox.qt_compat import QTableWidgetItem

        areal.weights_table.setItem(0, 0, QTableWidgetItem("999.9"))
        areal.cases.add_case("Second")
        areal.cases.list.setCurrentRow(0)
        assert areal.weights_table.item(0, 0).text() == "999.9"

    def test_the_plot_panel_offers_both_views(self, areal):
        if not areal.plots.available:
            pytest.skip("matplotlib not available")
        titles = [areal.plots.tabText(i) for i in range(areal.plots.count())]
        assert "Ring depths" in titles and "All cases" in titles


class TestButtonPlacement:
    """Buttons sit at the foot of the inputs pane, and never scroll away.

    Putting them at the bottom of the inputs *column* was not enough: the
    column scrolls, so on a tall form Calculate ended up below the fold --
    the one control you are looking for being the one you have to hunt for.
    They are pinned outside the scroll area instead.
    """

    @staticmethod
    def _scrolls(widget):
        """True if the widget is inside a scroll area."""
        from qgis.PyQt.QtWidgets import QScrollArea

        node = widget
        while node is not None:
            if isinstance(node, QScrollArea):
                return True
            node = node.parentWidget()
        return False

    def _check(self, tab):
        assert not self._scrolls(tab.run_button), (
            "the Calculate button must not be able to scroll out of view"
        )
        assert not self._scrolls(tab.export_button)
        # The inputs themselves do scroll -- that is what makes the pinning
        # necessary, and what this is contrasted against.
        assert self._scrolls(tab.picker), "the inputs column should scroll"

    def test_the_gsdm_tab(self, gsdm):
        self._check(gsdm)

    def test_the_gtsmr_tab(self, gtsmr):
        self._check(gtsmr)

    def test_the_areal_tab(self, _app, catchment_layer):
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab

        tab = ArealGsdmTab(iface=None)
        try:
            self._check(tab)
            # The progress bar is pinned with the button that fills it.
            assert not self._scrolls(tab.progress)
        finally:
            _dispose(tab)


class TestColumns:
    """GTSMR carries its method blocks in a column of their own."""

    def test_the_method_groups_are_not_in_the_catchment_column(self, gtsmr):
        column = gtsmr.picker.parentWidget().layout()
        titles = []
        for i in range(column.count()):
            widget = column.itemAt(i).widget()
            if widget is not None and hasattr(widget, "title"):
                titles.append(widget.title())
        assert titles == ["Catchment", "Applicable methods"]
        assert not any("GTSMR" in t or "GSAM" in t for t in titles), (
            "the method blocks belong in the middle column"
        )

    def test_the_method_groups_share_their_own_column(self, gtsmr):
        column = gtsmr.gtsmr_group.parentWidget().layout()
        titles = []
        for i in range(column.count()):
            widget = column.itemAt(i).widget()
            if widget is not None and hasattr(widget, "title"):
                titles.append(widget.title())
        assert len(titles) == 2
        assert "GTSMR" in titles[0] and "GSAM" in titles[1]

    def test_the_results_pane_cannot_be_squeezed_away(self, gtsmr):
        """Three input columns once left the results table ninety pixels."""
        results = gtsmr.table.parentWidget()
        assert results.minimumWidth() >= 300


class TestGtsmrLock:
    """The grid-derived GTSMR numbers are read-only until deliberately freed.

    Six of the GTSMR inputs are not opinions: four come off the Bureau's grids
    at the catchment centroid and two are guidebook constants. Leaving them as
    ordinary spin boxes means a stray scroll wheel can change a PMP by a
    hundred millimetres with nothing on screen to say it happened. The Toolbox
    website locks the same six; this matches it.

    The lock is not a claim they can never be wrong -- §2.3.1 actually asks for
    an EPW averaged over the catchment outline, which is exactly the case the
    unlock exists for.
    """

    LOCKED_ROWS = ("gtsmr_epw_s", "gtsmr_std_s", "gtsmr_epw_w",
                   "gtsmr_std_w", "gtsmr_taf", "gtsmr_daf")

    def test_it_starts_locked(self, gtsmr):
        assert gtsmr.locked()
        for name in self.LOCKED_ROWS:
            assert getattr(gtsmr, name).spin.isReadOnly(), name

    def test_the_button_says_what_it_will_do(self, gtsmr):
        assert "Unlock" in gtsmr.lock_button.text()
        gtsmr.lock_button.setChecked(True)
        assert "relock" in gtsmr.lock_button.text()

    def test_unlocking_makes_the_fields_editable(self, gtsmr):
        gtsmr.lock_button.setChecked(True)
        assert not gtsmr.locked()
        for name in self.LOCKED_ROWS:
            assert not getattr(gtsmr, name).spin.isReadOnly(), name

    def test_relocking_makes_them_read_only_again(self, gtsmr):
        gtsmr.lock_button.setChecked(True)
        gtsmr.lock_button.setChecked(False)
        assert gtsmr.locked()
        assert gtsmr.gtsmr_epw_s.spin.isReadOnly()

    def test_a_locked_field_keeps_its_stepper_arrows_hidden(self, gtsmr):
        """No control that looks like it should work and does not."""
        from pmp_toolbox.qt_compat import QDoubleSpinBox

        assert (
            gtsmr.gtsmr_taf.spin.buttonSymbols()
            == QDoubleSpinBox.ButtonSymbols.NoButtons
        )
        gtsmr.lock_button.setChecked(True)
        assert (
            gtsmr.gtsmr_taf.spin.buttonSymbols()
            == QDoubleSpinBox.ButtonSymbols.UpDownArrows
        )

    def test_the_note_explains_the_lock_either_way(self, gtsmr):
        locked_note = gtsmr.lock_note.text()
        assert "2.3.1" in locked_note
        # The note carries where the values were read -- either the coordinates
        # themselves, or the phrase standing in for them before a catchment is
        # chosen.
        assert "centroid" in locked_note or "°" in locked_note
        gtsmr.lock_button.setChecked(True)
        assert "replace" in gtsmr.lock_note.text()

    def test_gsam_is_not_locked(self, gtsmr):
        """GSAM's autumn EPW is a stand-in that must be checked by hand.

        It is seeded from the winter grid because the shipped grids have no
        autumn layer, so locking it would be locking in a value the plugin
        does not actually stand behind.
        """
        assert not gtsmr.gsam_epw_a.spin.isReadOnly()
        assert not gtsmr.gsam_taf.spin.isReadOnly()

    def test_resampling_refills_a_locked_field(self, gtsmr):
        """Locked means "the Bureau's number", not "frozen"."""
        if not gtsmr.use_gtsmr.isEnabled():
            pytest.skip("catchment is not in a GTSMR zone")
        sampled = gtsmr.gtsmr_epw_s.value()
        gtsmr._sample(force=True)
        assert gtsmr.gtsmr_epw_s.value() == pytest.approx(sampled)
        assert gtsmr.locked(), "resampling must not silently unlock"

    def test_the_lock_is_remembered_per_case(self, gtsmr):
        gtsmr.lock_button.setChecked(True)
        gtsmr.cases.add_case("Second")
        assert gtsmr.locked() is False, "a new case inherits the current one"

        gtsmr.lock_button.setChecked(False)
        gtsmr.cases.list.setCurrentRow(0)
        assert not gtsmr.locked(), "case 1 was left unlocked"
        gtsmr.cases.list.setCurrentRow(1)
        assert gtsmr.locked(), "case 2 was relocked"


class TestRingWeightLock:
    """The Areal GSDM ring weights are locked to Table 2 until freed.

    These ten numbers are the sharpest case for a lock in the whole plugin.
    They do not appear in the result at all -- they decide *which placement*
    the search picks, and the ring depths are then recomputed exactly from
    that placement. A mistyped weight therefore changes the answer while
    leaving nothing on screen that looks wrong.
    """

    @pytest.fixture
    def areal(self, _app, catchment_layer):
        from pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab

        tab = ArealGsdmTab(iface=None)
        tab.picker.layer_combo.setLayer(catchment_layer)
        tab.show_preview.setChecked(False)
        yield tab
        _dispose(tab)

    def test_it_starts_locked(self, areal):
        from pmp_toolbox.qt_compat import QTableWidget

        assert areal.weights_locked()
        assert areal.weights_table.editTriggers() == QTableWidget.NoEditTriggers
        assert "Unlock" in areal.weights_lock.text()

    def test_unlocking_makes_the_table_editable(self, areal):
        from pmp_toolbox.qt_compat import QTableWidget

        areal.weights_lock.setChecked(True)
        assert not areal.weights_locked()
        assert areal.weights_table.editTriggers() != QTableWidget.NoEditTriggers
        assert "relock" in areal.weights_lock.text()

    def test_locked_weights_follow_the_duration(self, areal):
        """Locked means "the Table 2 depths", so they track their inputs."""
        before = areal._weight_texts()
        index = areal.duration.findData(6.0)
        if index < 0:
            pytest.skip("6 hour not offered")
        areal.duration.setCurrentIndex(index)
        assert areal._weight_texts() != before

    def test_unlocked_weights_are_not_thrown_away_by_a_duration_change(
        self, areal
    ):
        """Once they are the engineer's numbers, they stay the engineer's."""
        from pmp_toolbox.qt_compat import QTableWidgetItem

        areal.weights_lock.setChecked(True)
        areal.weights_table.setItem(0, 0, QTableWidgetItem("123.4"))
        mine = areal._weight_texts()

        index = areal.duration.findData(6.0)
        if index < 0:
            pytest.skip("6 hour not offered")
        areal.duration.setCurrentIndex(index)
        assert areal._weight_texts() == mine

    def test_reset_puts_table_2_back_even_when_unlocked(self, areal):
        from pmp_toolbox.qt_compat import QTableWidgetItem

        areal.weights_lock.setChecked(True)
        areal.weights_table.setItem(0, 0, QTableWidgetItem("123.4"))
        areal.weights_reset.click()
        assert areal.weights_table.item(0, 0).text() != "123.4"

    def test_the_locked_cells_are_tinted(self, areal):
        """The tint survives construction, which is where it was first lost.

        Restoring a case rebuilds the weight items, and that runs *after* the
        initial fill -- so a tint applied only when the values are computed is
        created and immediately thrown away. It reads as unlocked while being
        locked, which is the worst of both.
        """
        item = areal.weights_table.item(0, 0)
        assert item is not None
        assert item.background().color().name() == "#f1f3f3"

        areal.weights_lock.setChecked(True)
        assert areal.weights_table.item(0, 0).background().color().name() != "#f1f3f3"

    def test_the_tint_survives_a_case_switch(self, areal):
        areal.cases.add_case("Second")
        areal.cases.list.setCurrentRow(0)
        assert areal.weights_table.item(0, 0).background().color().name() == "#f1f3f3"

    def test_the_note_explains_the_lock_either_way(self, areal):
        assert "Table 2" in areal.weights_note.text()
        areal.weights_lock.setChecked(True)
        assert "yours" in areal.weights_note.text()

    def test_the_lock_is_remembered_per_case(self, areal):
        areal.weights_lock.setChecked(True)
        areal.cases.add_case("Second")
        areal.weights_lock.setChecked(False)

        areal.cases.list.setCurrentRow(0)
        assert not areal.weights_locked(), "case 1 was left unlocked"
        areal.cases.list.setCurrentRow(1)
        assert areal.weights_locked(), "case 2 was relocked"

    def test_a_locked_run_still_uses_the_table_2_weights(self, areal, silent):
        """The lock must not change what the search is given."""
        from pmp_toolbox.core.gsdm import weight_profile

        expected = weight_profile(areal.inputs())
        got = areal.weights()
        for label, value in got.items():
            assert value == pytest.approx(expected.get(label, 0.0), abs=0.05)
