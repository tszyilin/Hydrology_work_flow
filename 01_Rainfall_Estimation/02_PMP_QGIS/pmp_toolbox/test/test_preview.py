"""Smoke tests for the live search preview.

Painting is the point of this module, so the tests actually render it: a widget
that raises in ``paintEvent`` fails silently in production (Qt swallows the
traceback to a warning), and ``grab()`` is the cheapest way to be sure it does
not.  Needs Qt; skipped without the QGIS Python environment.
"""

import math
import os

import numpy as np
import pytest

pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pmp_toolbox.core import ellipses  # noqa: E402
from pmp_toolbox.core.gsdm import Inputs, distribute  # noqa: E402
from pmp_toolbox.core.optimiser import SearchCancelled, Trial  # noqa: E402

CX, CY = 500_000.0, 7_000_000.0
RADIUS = 4_000.0


def square_catchment(half=RADIUS):
    ring = np.array(
        [
            (CX - half, CY - half),
            (CX + half, CY - half),
            (CX + half, CY + half),
            (CX - half, CY + half),
            (CX - half, CY - half),
        ]
    )
    return [[ring]]


def trials(count=200, k=4):
    """A plausible sweep: a spiral of placements, improving now and then."""
    out = []
    for i in range(count):
        angle = i / 12.0
        out.append(
            Trial(
                index=i + 1,
                total=count,
                phase="coarse" if i < count - 20 else "refine",
                cx=CX + 900.0 * math.cos(angle),
                cy=CY + 900.0 * math.sin(angle),
                theta=(i / count) * math.pi,
                k=k,
                score=1000.0 + i,
                is_best=(i % 37 == 0),
            )
        )
    return out


@pytest.fixture
def preview(qgis_app):
    from pmp_toolbox.preview import SearchPreviewDialog

    dialog = SearchPreviewDialog()
    dialog.begin()
    dialog.on_catchment(square_catchment())
    yield dialog
    dialog.end_run()
    dialog.close()


def rendered(preview):
    pixmap = preview.canvas.grab()
    assert not pixmap.isNull()
    # paintEvent swallows exceptions so a drawing bug cannot abort QGIS; that
    # makes this flag the only evidence the painting actually worked.
    assert preview.canvas._failure is None, preview.canvas._failure
    image = pixmap.toImage()
    colours = {
        image.pixel(x, y)
        for x in range(0, image.width(), 7)
        for y in range(0, image.height(), 7)
    }
    return colours


class TestFraming:
    def test_the_view_covers_catchment_and_template(self, preview):
        xmin, ymin, xmax, ymax = preview.canvas._bounds
        assert xmin < CX - RADIUS and xmax > CX + RADIUS
        assert ymin < CY - RADIUS and ymax > CY + RADIUS
        # Wide enough for the ellipse that encloses the catchment, but not for
        # ellipse J -- that would shrink the catchment to a dot.
        assert (xmax - xmin) / 2.0 > ellipses.SEMI_MAJOR_M[preview.canvas._draw_to - 1]
        assert (xmax - xmin) / 2.0 < ellipses.SEMI_MAJOR_M[-1] * 2.2

    def test_a_larger_ellipse_widens_the_view(self, preview):
        before = preview.canvas._bounds
        preview.canvas.frame_for(len(ellipses.LABELS) - 1)
        after = preview.canvas._bounds
        assert after[2] - after[0] > before[2] - before[0]

    def test_the_frame_tightens_as_the_best_ellipse_shrinks(self, preview):
        """``k`` never grows for a new best, so the view closes in and settles."""
        preview.canvas.frame_for(len(ellipses.LABELS) - 1)
        widths = []
        for k in (7, 5, 3):
            preview.canvas.frame_for(k)
            widths.append(preview.canvas._bounds[2] - preview.canvas._bounds[0])
        assert widths == sorted(widths, reverse=True)

    def test_the_frame_never_goes_tighter_than_the_catchment(self, preview):
        preview.canvas.frame_for(0)
        assert preview.canvas._draw_to >= preview.canvas._fits
        xmin, _ymin, xmax, _ymax = preview.canvas._bounds
        assert xmin < CX - RADIUS and xmax > CX + RADIUS

    def test_an_escaping_placement_does_not_reframe(self, preview):
        """k == OUTSIDE would zoom out to ellipse J and never come back."""
        before = preview.canvas._bounds
        preview.canvas.frame_for(len(ellipses.LABELS))
        assert preview.canvas._bounds == before

    def test_it_still_paints_after_the_view_widens(self, preview):
        """Reframing invalidates the cached catchment path -- and its cache key.

        Leaving the key behind left paintEvent with a matching key and a path of
        None, and an exception escaping a Qt virtual method aborts the process.
        """
        preview(trials(5)[0])
        rendered(preview)
        preview.canvas.frame_for(len(ellipses.LABELS) - 1)
        assert preview.canvas._path is None
        assert len(rendered(preview)) > 1

    def test_the_frame_does_not_move_between_trials(self, preview):
        preview(trials(30)[0])
        first = preview.canvas._bounds
        for trial in trials(30)[1:]:
            preview(trial)
        assert preview.canvas._bounds == first


class TestLiveRun:
    def test_it_draws_something_other_than_the_background(self, preview):
        for trial in trials():
            preview(trial)
        assert len(rendered(preview)) > 3

    def test_every_trial_is_recorded_even_at_full_speed(self, preview):
        preview.full_speed.setChecked(True)
        batch = trials()
        for trial in batch:
            preview(trial)
        assert len(preview.history) == len(batch)

    def test_the_hud_names_the_enclosing_ellipse(self, preview):
        for trial in trials(k=3):
            preview(trial)
        text = " ".join(preview.canvas.hud)
        assert "D" in text and "best so far" in text
        assert "larger than the view" not in text

    def test_the_hud_says_when_the_candidate_outgrows_the_view(self, preview):
        for trial in trials(k=3):
            preview(trial)  # frames on D
        # A candidate that is not the best never reframes, so ellipse I is
        # simply off the edge of the drawing.
        wanderer = trials(k=8)[1]
        assert not wanderer.is_best
        assert "larger than the view" in " ".join(preview._hud(wanderer))

    def test_cancelling_stops_the_next_trial(self, preview):
        preview(trials()[0])
        preview._cancel()
        with pytest.raises(SearchCancelled):
            preview(trials()[1])

    def test_closing_the_window_cancels(self, preview):
        preview(trials()[0])
        preview.close()
        with pytest.raises(SearchCancelled):
            preview(trials()[1])


def run_and_finish(preview):
    """Drive a whole run through the preview, as the plugin does."""
    from pmp_toolbox.core.optimiser import Placement

    for trial in trials():
        preview(trial)
    areas = {"A": 2.6, "B": 13.4, "C": 30.0, "D": 20.0}
    result = distribute(areas, Inputs(3.0, 1.0, 0.0, 0.7, 1.0))
    placement = Placement(
        cx=CX, cy=CY, theta=0.3, k=3, score=1234.0,
        ring_areas_km2=areas, feasible=True,
    )
    polygons = {
        ring.label: [[ellipses.polygon(CX, CY, 0.3, ring.ellipse_area_km2, 48)]]
        for ring in result.rings
    }
    preview.finish(result, placement, polygons, summary="Best fit: ellipse D\nPMP 400 mm")
    return preview, result


@pytest.fixture
def finished(preview):
    """Finished, sitting on the result -- the auto-replay is covered separately."""
    preview.auto_replay.setChecked(False)
    return run_and_finish(preview)


@pytest.fixture
def replaying(preview):
    """Finished with the default: the whole search plays back."""
    preview.auto_replay.setChecked(True)
    return run_and_finish(preview)


class TestFinalView:
    def test_the_rings_are_shaded(self, finished):
        preview, result = finished
        assert preview.canvas.show_final
        assert len(preview.canvas.final) == len(result.rings)
        assert len(rendered(preview)) > 3

    def test_the_summary_replaces_the_running_hud(self, finished):
        preview, _result = finished
        assert "Best fit" in " ".join(preview.canvas.hud)

    def test_replay_is_enabled_over_the_whole_history(self, finished):
        preview, _result = finished
        assert preview.slider.isEnabled()
        assert preview.slider.maximum() == len(preview.history) - 1

    def test_live_controls_are_disabled_once_the_search_ends(self, finished):
        preview, _result = finished
        assert not preview.pause_button.isEnabled()
        assert not preview.cancel_button.isEnabled()


class TestAutoReplay:
    """The default: the run ends by retracing itself from the first trial."""

    def test_it_starts_at_the_beginning_of_the_search(self, replaying):
        preview, _result = replaying
        assert preview._timer.isActive()
        assert preview.slider.value() == 0
        assert not preview.canvas.show_final
        assert "replay" in " ".join(preview.canvas.hud).lower()
        assert len(rendered(preview)) > 3

    def test_it_settles_on_the_final_result(self, replaying):
        preview, _result = replaying
        for _ in range(500):
            if not preview._timer.isActive():
                break
            preview._advance()
        else:
            pytest.fail("the replay never reached the end")
        assert preview.canvas.show_final
        assert "Best fit" in " ".join(preview.canvas.hud)

    def test_the_step_follows_the_requested_duration(self, replaying):
        preview, _result = replaying
        preview.replay_seconds.setValue(2)
        quick = preview._replay_step()
        preview.replay_seconds.setValue(60)
        assert preview._replay_step() <= quick

    def test_a_long_search_still_replays_in_about_the_asked_time(self, replaying):
        preview, _result = replaying
        preview.history = preview.history * 200  # ~40,000 trials
        preview.slider.setMaximum(len(preview.history) - 1)
        preview.replay_seconds.setValue(10)
        frames = len(preview.history) / preview._replay_step()
        seconds = frames * preview._timer.interval() / 1000.0
        assert 8 <= seconds <= 12

    def test_turning_it_off_goes_straight_to_the_result(self, finished):
        preview, _result = finished
        assert not preview._timer.isActive()
        assert preview.canvas.show_final


class TestReplay:
    def test_scrubbing_walks_the_recorded_trials(self, finished):
        preview, _result = finished
        for index in (0, len(preview.history) // 2, len(preview.history) - 1):
            preview.slider.setValue(index)
            trial = preview.history[index]
            assert preview.canvas.current[:2] == pytest.approx((trial.cx, trial.cy))
            assert not preview.canvas.show_final
            assert len(rendered(preview)) > 3

    def test_the_ghost_is_the_best_up_to_that_point(self, finished):
        preview, _result = finished
        index = len(preview.history) - 1
        preview.slider.setValue(0)
        preview.slider.setValue(index)
        expected = [t for t in preview.history[: index + 1] if t.is_best][-1]
        assert preview.canvas.best[:2] == pytest.approx((expected.cx, expected.cy))

    def test_the_final_button_restores_the_result(self, finished):
        preview, _result = finished
        preview.slider.setValue(0)
        preview.show_final()
        assert preview.canvas.show_final
        assert preview.canvas.current[:2] == pytest.approx((CX, CY))


class TestGeometryConversion:
    """The one QGIS-shaped seam: QgsGeometry to plain coordinate arrays."""

    def test_a_polygon_with_a_hole_keeps_its_rings(self, qgis_app):
        from qgis.core import QgsGeometry

        from pmp_toolbox import qgis_bridge

        geometry = QgsGeometry.fromWkt(
            "POLYGON((0 0, 100 0, 100 100, 0 100, 0 0),"
            "(40 40, 60 40, 60 60, 40 60, 40 40))"
        )
        parts = qgis_bridge.geometry_polygons(geometry)
        assert len(parts) == 1
        assert len(parts[0]) == 2
        assert parts[0][0].shape[1] == 2

    def test_an_empty_geometry_gives_nothing_to_draw(self, qgis_app):
        from qgis.core import QgsGeometry

        from pmp_toolbox import qgis_bridge

        assert qgis_bridge.geometry_polygons(QgsGeometry()) == []
