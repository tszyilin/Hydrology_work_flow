"""Placement search: GSDM section 6 Step 1, automated."""

import math

import numpy as np
import pytest

from pmp_toolbox.core import ellipses
from pmp_toolbox.core.gsdm import Inputs, weight_profile
from pmp_toolbox.core.optimiser import (
    OUTSIDE,
    CatchmentRaster,
    SearchCancelled,
    optimise,
    score_placement,
)

INPUTS = Inputs(duration_hr=3.0, smooth=1.0, rough=0.0, maf=0.7, eaf=1.0)


@pytest.fixture(scope="module")
def weights():
    return np.array([weight_profile(INPUTS).get(l, 0.0) for l in ellipses.LABELS])


def disc_raster(radius_m, cx=0.0, cy=0.0, step=None):
    """A circular catchment -- the one shape whose optimum is knowable a priori."""
    step = step or radius_m / 60.0
    grid_x = np.arange(cx - radius_m, cx + radius_m + step, step)
    grid_y = np.arange(cy - radius_m, cy + radius_m + step, step)
    gx, gy = np.meshgrid(grid_x, grid_y)
    gx, gy = gx.ravel(), gy.ravel()
    keep = np.hypot(gx - cx, gy - cy) <= radius_m
    return CatchmentRaster(np.column_stack((gx[keep], gy[keep])), step**2 / 1.0e6)


class TestCatchmentRaster:
    def test_area_approximates_the_disc(self):
        raster = disc_raster(4000.0)
        assert raster.area_km2 == pytest.approx(math.pi * 4.0**2, rel=0.01)

    def test_centroid_recovers_the_centre(self):
        raster = disc_raster(4000.0, cx=500000.0, cy=7000000.0)
        cx, cy = raster.centroid
        assert (cx, cy) == pytest.approx((500000.0, 7000000.0), abs=50.0)

    def test_from_polygon_rasterises_a_disc(self):
        def contains(xs, ys):
            return np.hypot(xs - 10.0, ys - 20.0) <= 3000.0

        raster = CatchmentRaster.from_polygon(
            contains, (-2990.0, -2980.0, 3010.0, 3020.0), cell_m=30.0
        )
        assert raster.area_km2 == pytest.approx(math.pi * 9.0, rel=0.02)

    def test_from_polygon_rejects_an_empty_result(self):
        with pytest.raises(ValueError):
            CatchmentRaster.from_polygon(
                lambda xs, ys: np.zeros(len(xs), bool), (0, 0, 100, 100)
            )


class TestScorePlacement:
    def test_ring_areas_sum_to_the_catchment_area(self, weights):
        raster = disc_raster(5000.0)
        _k, _score, areas = score_placement(raster, weights, 0.0, 0.0, 0.0)
        assert areas.sum() == pytest.approx(raster.area_km2)

    def test_k_reports_the_enclosing_ellipse(self, weights):
        """A disc of radius r is enclosed by the first ellipse with b >= r."""
        for target in (1, 3, 5):
            radius = ellipses.SEMI_MINOR_M[target] * 0.95
            raster = disc_raster(radius)
            k, _score, _areas = score_placement(raster, weights, 0.0, 0.0, 0.0)
            assert k == target

    def test_a_catchment_larger_than_ellipse_J_is_infeasible(self, weights):
        raster = disc_raster(ellipses.SEMI_MINOR_M[-1] * 1.2)
        k, _score, _areas = score_placement(raster, weights, 0.0, 0.0, 0.0)
        assert k == OUTSIDE

    def test_score_falls_as_the_template_slides_off(self, weights):
        raster = disc_raster(3000.0)
        centred = score_placement(raster, weights, 0.0, 0.0, 0.0)[1]
        for offset in (2000.0, 5000.0, 12000.0):
            shifted = score_placement(raster, weights, offset, 0.0, 0.0)[1]
            assert shifted < centred


class TestOptimise:
    """A disc has a known answer: the template belongs on its centre."""

    def test_finds_the_centre_of_a_disc(self, weights):
        cx0, cy0 = 612345.0, 7012345.0
        raster = disc_raster(4000.0, cx=cx0, cy=cy0)
        _coarse, best = optimise(raster, weights, thetas_deg=4, coarse_seeds=3)
        assert best.feasible
        assert (best.cx, best.cy) == pytest.approx((cx0, cy0), abs=250.0)

    def test_picks_the_smallest_enclosing_ellipse(self, weights):
        """The containment constraint, GSDM Step 1."""
        radius = ellipses.SEMI_MINOR_M[3] * 0.9
        raster = disc_raster(radius)
        _coarse, best = optimise(raster, weights, thetas_deg=4, coarse_seeds=3)
        assert best.label == "D"

    def test_refinement_never_loses_to_the_coarse_sweep(self, weights):
        raster = disc_raster(4000.0, cx=100.0, cy=-250.0)
        coarse, best = optimise(raster, weights, thetas_deg=6, coarse_seeds=3)
        assert (best.k, -best.score) <= (coarse.k, -coarse.score)

    def test_ring_areas_are_reported_for_every_ellipse(self, weights):
        raster = disc_raster(4000.0)
        _coarse, best = optimise(raster, weights, thetas_deg=4, coarse_seeds=2)
        assert sorted(best.ring_areas_km2) == sorted(ellipses.LABELS)
        assert sum(best.ring_areas_km2.values()) == pytest.approx(raster.area_km2)

    def test_rotation_is_reported_as_a_bearing(self, weights):
        raster = disc_raster(4000.0)
        _coarse, best = optimise(raster, weights, thetas_deg=4, coarse_seeds=2)
        assert 0.0 <= best.bearing_deg < 180.0

    def test_orientation_follows_an_elongated_catchment(self, weights):
        """An east-west sliver should pull the major axis onto a bearing of 90."""
        step = 400.0
        gx, gy = np.meshgrid(
            np.arange(-14000.0, 14000.0, step), np.arange(-2000.0, 2000.0, step)
        )
        raster = CatchmentRaster(
            np.column_stack((gx.ravel(), gy.ravel())), step**2 / 1.0e6
        )
        _coarse, best = optimise(raster, weights, thetas_deg=12, coarse_seeds=4)
        assert min(abs(best.bearing_deg - 90.0), abs(best.bearing_deg - 270.0)) < 20.0

    def test_rejects_a_malformed_weight_vector(self, weights):
        raster = disc_raster(3000.0)
        with pytest.raises(ValueError):
            optimise(raster, [1.0, 2.0, 3.0])

    def test_accepts_weights_as_a_mapping(self, weights):
        raster = disc_raster(3000.0)
        as_dict = dict(zip(ellipses.LABELS, weights))
        _coarse, from_dict = optimise(raster, as_dict, thetas_deg=4, coarse_seeds=2)
        _coarse2, from_array = optimise(raster, weights, thetas_deg=4, coarse_seeds=2)
        assert from_dict.score == pytest.approx(from_array.score)

    def test_progress_is_reported_monotonically(self, weights):
        seen = []
        optimise(
            disc_raster(3000.0),
            weights,
            thetas_deg=4,
            coarse_seeds=1,
            progress=seen.append,
        )
        assert seen == sorted(seen)
        assert seen[-1] == pytest.approx(1.0)


class TestObserver:
    """The hook the live preview watches the search through."""

    def _trials(self, weights, **kwargs):
        seen = []
        coarse, best = optimise(
            disc_raster(3000.0, cx=100.0, cy=-250.0),
            weights,
            thetas_deg=4,
            coarse_seeds=2,
            observer=seen.append,
            **kwargs,
        )
        return seen, coarse, best

    def test_every_coarse_candidate_is_reported_once(self, weights):
        seen, _coarse, _best = self._trials(weights)
        coarse = [t for t in seen if t.phase == "coarse"]
        assert len(coarse) == coarse[0].total
        assert [t.index for t in seen] == list(range(1, len(seen) + 1))

    def test_refinement_is_reported_after_the_sweep(self, weights):
        seen, _coarse, _best = self._trials(weights)
        phases = [t.phase for t in seen]
        assert set(phases) == {"coarse", "refine"}
        assert phases.index("refine") > phases.count("coarse") - 1

    def test_the_best_flag_marks_strict_improvements(self, weights):
        seen, _coarse, best = self._trials(weights)
        improving = [t for t in seen if t.is_best]
        # Each flagged trial beats the last, so the lexicographic cost falls.
        costs = [(t.k, -t.score) for t in improving]
        assert costs == sorted(costs, reverse=True)
        assert improving[-1].k == best.k
        assert improving[-1].score == pytest.approx(best.score)

    def test_watching_does_not_change_the_answer(self, weights):
        seen, _coarse, watched = self._trials(weights)
        _coarse2, unwatched = optimise(
            disc_raster(3000.0, cx=100.0, cy=-250.0),
            weights,
            thetas_deg=4,
            coarse_seeds=2,
        )
        assert seen  # the observer really did run
        assert (watched.cx, watched.cy, watched.theta) == pytest.approx(
            (unwatched.cx, unwatched.cy, unwatched.theta)
        )
        assert watched.score == pytest.approx(unwatched.score)

    def test_an_observer_can_cancel_the_search(self, weights):
        def stop_after_ten(trial):
            if trial.index >= 10:
                raise SearchCancelled("enough")

        with pytest.raises(SearchCancelled):
            optimise(
                disc_raster(3000.0),
                weights,
                thetas_deg=4,
                observer=stop_after_ten,
            )


class TestOptimalityAgainstBruteForce:
    def test_beats_the_naive_centroid_placement(self, weights):
        """The whole point of the plugin: better than dropping it on the centroid.

        A crescent's centroid lies outside the catchment, so the unoptimised
        placement wastes the inner, wettest ellipses on empty ground.
        """
        step = 250.0
        gx, gy = np.meshgrid(
            np.arange(-9000.0, 9000.0, step), np.arange(-9000.0, 9000.0, step)
        )
        gx, gy = gx.ravel(), gy.ravel()
        r = np.hypot(gx, gy)
        keep = (r <= 8000.0) & (np.hypot(gx - 3500.0, gy) > 4500.0)
        raster = CatchmentRaster(np.column_stack((gx[keep], gy[keep])), step**2 / 1.0e6)

        cx0, cy0 = raster.centroid
        naive = score_placement(raster, weights, cx0, cy0, 0.0)[1]
        _coarse, best = optimise(raster, weights, thetas_deg=8, coarse_seeds=5)
        assert best.score > naive
