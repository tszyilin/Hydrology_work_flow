"""The Bulletin's own worked example is the reference for Steps 2-8.

GSDM Appendix 2.2, Table A2.2: a 110 km2 NSW catchment, 3-hour PMP, 10% smooth
/ 90% rough terrain, EAF 0.96, MAF 0.60, best fit by ellipse E.
"""

import math

import pytest

from pmp_toolbox.core import ellipses
from pmp_toolbox.core.dda import DDACurves, Table2
from pmp_toolbox.core.gsdm import (
    Inputs,
    distribute,
    elevation_adjustment_factor,
    round_pmp,
    weight_profile,
)

# Column b of Table A2.2 -- catchment area between successive ellipses.
CBTN = {"A": 2.6, "B": 13.4, "C": 37.7, "D": 42.6, "E": 13.7}

# Columns c, d, e and h of Table A2.2.
EXPECTED = {
    #        cenc,  imrd, amrd, mrd
    "A": (2.6, 881, 507, 507),
    "B": (16.0, 793, 457, 447),
    "C": (53.7, 716, 412, 393),
    "D": (96.3, 673, 388, 358),
    "E": (110.0, 663, 382, 340),
}

INPUTS = Inputs(duration_hr=3.0, smooth=0.1, rough=0.9, maf=0.60, eaf=0.96)

# Two sources of truth are deliberately kept apart:
#
#  * Steps 5-8 are pure arithmetic and must reproduce Table A2.2 exactly.  They
#    are tested against ``BulletinDDA`` below, which replays the depths the
#    Bulletin's author read off Figure 4.
#  * Step 4 depends on how finely Figure 4 was digitised.  Our curves give
#    586.0/731.5 mm at 53.7 km2 where the author read 585/731 -- a ~0.15%
#    disagreement between two reads of the same printed graph.  Step 8 divides
#    a difference of enclosed volumes by a thin ring area, so it magnifies that
#    by CEnc/CBtn (a factor of 8 for ring E).  Demanding an exact match on
#    column h from the digitised curves would be overfitting to one person's
#    eye, so Step 4 is checked within a stated digitisation tolerance instead.
DIGITISATION_TOLERANCE_MM = 2.0


class BulletinDDA:
    """Replays column d of Table A2.2, so Steps 5-8 can be checked exactly.

    These are the published weighted initial mean rainfall depths for the three
    ellipses the catchment only partially fills.
    """

    QUOTED = {53.7: 716, 96.3: 673, 110.0: 663}

    def weighted_depth(self, duration_hr, area_km2, smooth, rough):
        assert duration_hr == 3.0
        return self.QUOTED[min(self.QUOTED, key=lambda a: abs(a - area_km2))]


@pytest.fixture(scope="module")
def tables():
    return DDACurves(), Table2()


@pytest.fixture(scope="module")
def appendix_result(tables):
    """Steps 5-8 driven by the Bulletin's own Figure 4 reads."""
    return distribute(CBTN, INPUTS, BulletinDDA(), tables[1])


@pytest.fixture(scope="module")
def digitised_result(tables):
    """The same catchment run end to end on our digitised curves."""
    return distribute(CBTN, INPUTS, *tables)


def test_outermost_ellipse_is_E(appendix_result):
    assert appendix_result.outermost == "E"
    assert [r.label for r in appendix_result.rings] == ["A", "B", "C", "D", "E"]


def test_closure_check(appendix_result):
    assert appendix_result.catchment_area_km2 == pytest.approx(110.0)
    assert appendix_result.closure_error_km2 == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("label", list(EXPECTED))
def test_table_a2_2_columns(appendix_result, label):
    """Steps 3, 5, 6, 7 and 8 reproduce the published table to the millimetre."""
    ring = next(r for r in appendix_result.rings if r.label == label)
    cenc, imrd, amrd, mrd = EXPECTED[label]
    assert ring.cenc == pytest.approx(cenc, abs=0.05)
    assert ring.imrd == pytest.approx(imrd, abs=0.5)
    assert ring.amrd == pytest.approx(amrd, abs=0.5)
    assert round(ring.mrd) == mrd


def test_table_a2_2_volumes(appendix_result):
    """Columns f and g."""
    venc = {r.label: round(r.venc) for r in appendix_result.rings}
    vbtn = {r.label: round(r.vbtn) for r in appendix_result.rings}
    assert venc == {"A": 1318, "B": 7312, "C": 22124, "D": 37364, "E": 42020}
    assert vbtn == {"A": 1318, "B": 5994, "C": 14812, "D": 15240, "E": 4656}


@pytest.mark.parametrize("label", list(EXPECTED))
def test_step_4_from_the_digitised_curves(digitised_result, label):
    """Our Figure 4 digitisation agrees with the author's read within tolerance."""
    ring = next(r for r in digitised_result.rings if r.label == label)
    assert ring.imrd == pytest.approx(
        EXPECTED[label][1], abs=DIGITISATION_TOLERANCE_MM
    )


def test_step4_source_matches_the_bulletin(appendix_result):
    """A and B fill their ellipses (Table 2); C, D, E only partially (DDA)."""
    sources = {r.label: r.source for r in appendix_result.rings}
    assert sources == {
        "A": "table2",
        "B": "table2",
        "C": "dda",
        "D": "dda",
        "E": "dda",
    }


def test_worked_example_intermediate_depths(tables):
    """The Bulletin quotes these two lookups explicitly in Step 4."""
    dda, table2 = tables
    # 3 hr, ellipse A: smooth 705, rough 901 -> weighted 881
    assert table2.depth("A", "S", 3.0) == 705
    assert table2.depth("A", "R", 3.0) == 901
    assert table2.weighted_depth("A", 3.0, 0.1, 0.9) == pytest.approx(881.4, abs=0.5)
    # 3 hr, 53.7 km2: smooth 585, rough 731 -> weighted 716
    assert dda.depth("S", 3.0, 53.7) == pytest.approx(585, abs=3)
    assert dda.depth("R", 3.0, 53.7) == pytest.approx(731, abs=3)
    assert dda.weighted_depth(3.0, 53.7, 0.1, 0.9) == pytest.approx(716, abs=3)


def test_volumes_telescope(appendix_result):
    """Why weight_profile must freeze its weights: the volume sum is degenerate."""
    total = sum(r.vbtn for r in appendix_result.rings)
    assert total == pytest.approx(appendix_result.rings[-1].venc)
    assert total == pytest.approx(
        appendix_result.pmp_mm * appendix_result.catchment_area_km2
    )


def test_depths_decrease_outward(appendix_result):
    depths = [r.mrd for r in appendix_result.rings]
    assert depths == sorted(depths, reverse=True)


def test_step_8_is_reproduced_exactly(appendix_result):
    """Column h, the depths actually painted on the map."""
    got = {r.label: round(r.mrd) for r in appendix_result.rings}
    assert got == {"A": 507, "B": 447, "C": 393, "D": 358, "E": 340}


def test_thin_rings_amplify_depth_error(tables):
    """Step 8 magnifies any drift in AMRD by roughly CEnc / CBtn.

    Reading Figure 4 1 mm high for the outermost ellipse alone -- well inside
    what two people reading the same graph would differ by -- moves ring E's
    mapped depth by 110/13.7 * MAF * EAF = 4.6 mm, while the inner rings do not
    move at all.  This conditioning is why ``round_intermediates`` defaults to
    the Bulletin's behaviour and why ``distribute`` warns on thin rings.
    """
    unrounded = Inputs(3.0, 0.1, 0.9, 0.60, 0.96, round_intermediates=False)

    class OutermostHigh(BulletinDDA):
        def weighted_depth(self, duration_hr, area_km2, smooth, rough):
            depth = super().weighted_depth(duration_hr, area_km2, smooth, rough)
            return depth + 1.0 if area_km2 > 100.0 else depth

    base = {r.label: r.mrd for r in distribute(CBTN, unrounded, BulletinDDA(), tables[1]).rings}
    bumped = {r.label: r.mrd for r in distribute(CBTN, unrounded, OutermostHigh(), tables[1]).rings}

    assert bumped["A"] == pytest.approx(base["A"])
    assert bumped["D"] == pytest.approx(base["D"])
    assert bumped["E"] - base["E"] == pytest.approx(
        1.0 * 0.60 * 0.96 * 110.0 / 13.7, abs=0.01
    )


def test_thin_ring_conditioning_is_warned_about(digitised_result):
    assert any("sensitive to rounding" in w for w in digitised_result.warnings)
    assert "E" in next(w for w in digitised_result.warnings if "sensitive" in w)


class TestDDACurves:
    def test_breakpoint_is_exact(self, tables):
        """Querying at a digitised area returns the digitised value untouched."""
        dda = tables[0]
        assert dda.depth("S", 0.25, 1.0) == pytest.approx(245.30685920577616)
        assert dda.depth("S", 0.25, 1000.0) == pytest.approx(102.76774969915765)
        assert dda.depth("R", 6.0, 1000.0) == pytest.approx(587.5852386682711)

    def test_terrain_is_irrelevant_below_one_hour(self, tables):
        """GSDM section 4.2: the R and S curves coincide for durations <= 1 hr."""
        dda = tables[0]
        for duration in (0.25, 0.5, 0.75, 1.0):
            for area in (1.0, 47.9, 1000.0):
                assert dda.depth("S", duration, area) == pytest.approx(
                    dda.depth("R", duration, area)
                )

    def test_terrain_matters_above_one_hour(self, tables):
        dda = tables[0]
        assert dda.depth("R", 6.0, 100.0) > dda.depth("S", 6.0, 100.0)

    def test_depth_decreases_with_area(self, tables):
        dda = tables[0]
        areas = [1, 5, 10, 50, 100, 500, 1000]
        depths = [dda.depth("S", 3.0, a) for a in areas]
        assert depths == sorted(depths, reverse=True)

    def test_area_is_clamped_to_curve_limits(self, tables):
        dda = tables[0]
        assert dda.depth("S", 3.0, 0.1) == pytest.approx(dda.depth("S", 3.0, 1.0))
        assert dda.depth("S", 3.0, 5000.0) == pytest.approx(dda.depth("S", 3.0, 1000.0))

    def test_duration_interpolates_linearly(self, tables):
        dda = tables[0]
        lo = dda.depth("S", 3.0, 100.0)
        hi = dda.depth("S", 4.0, 100.0)
        assert dda.depth("S", 3.5, 100.0) == pytest.approx((lo + hi) / 2.0)

    def test_rejects_unknown_terrain(self, tables):
        with pytest.raises(ValueError):
            tables[0].depth("X", 3.0, 100.0)


class TestTable2:
    def test_ellipses_i_and_j_are_absent(self, tables):
        """The Bulletin omits them: their areas exceed the 1000 km2 DDA limit."""
        table2 = tables[1]
        assert table2.has("H")
        assert not table2.has("I")
        assert not table2.has("J")

    def test_matches_the_dda_curves_at_the_ellipse_areas(self, tables):
        """Table 2 is Figure 4 evaluated at each ellipse area, rounded."""
        dda, table2 = tables
        for label in ("A", "C", "E", "H"):
            area = table2.area_enclosed[label]
            for terrain in ("S", "R"):
                for duration in (0.25, 1.0, 3.0, 6.0):
                    assert table2.depth(label, terrain, duration) == pytest.approx(
                        dda.depth(terrain, duration, area), abs=2.0
                    )

    def test_areas_between_sum_to_areas_enclosed(self, tables):
        table2 = tables[1]
        running = 0.0
        for label in "ABCDEFGH":
            running += table2.area_between[label]
            assert running == pytest.approx(table2.area_enclosed[label], abs=0.05)


class TestElevationAdjustment:
    """GSDM section 4.3."""

    @pytest.mark.parametrize(
        "elevation,expected",
        [(0, 1.0), (1000, 1.0), (1500, 1.0), (1800, 0.95), (2100, 0.90), (2400, 0.85)],
    )
    def test_known_values(self, elevation, expected):
        assert elevation_adjustment_factor(elevation) == pytest.approx(expected)

    def test_floors_at_0_85(self):
        assert elevation_adjustment_factor(5000) == 0.85


def test_pmp_rounds_to_nearest_ten():
    assert round_pmp(382.0) == 380
    assert round_pmp(385.0) == 380  # banker's rounding on the .5 boundary
    assert round_pmp(386.0) == 390


class TestWeightProfile:
    def test_descends_from_inner_to_outer(self, tables):
        weights = weight_profile(INPUTS, *tables)
        values = [weights[l] for l in "ABCDEFGH"]
        assert values == sorted(values, reverse=True)
        assert values[0] > 0

    def test_is_non_increasing_all_the_way_to_J(self, tables):
        """The premise of the whole method: inner rings are never worth less.

        Ellipses I and J have no Table 2 depths and the DDA lookup clamps at
        1000 km2, so the raw depths tick back up (H 248, I 253, J 281 mm at
        3 hr). Unfloored, that would reward pushing catchment area outward.
        """
        weights = weight_profile(INPUTS, *tables)
        values = [weights[l] for l in ellipses.LABELS]
        assert values == sorted(values, reverse=True)
        assert weights["I"] <= weights["H"]
        assert weights["J"] <= weights["I"]

    @pytest.mark.parametrize("duration", [0.25, 1.0, 2.5, 6.0])
    @pytest.mark.parametrize("smooth", [0.0, 0.5, 1.0])
    def test_stays_non_increasing_across_the_parameter_space(
        self, tables, duration, smooth
    ):
        weights = weight_profile(
            Inputs(duration, smooth=smooth, rough=1.0 - smooth), *tables
        )
        values = [weights[l] for l in ellipses.LABELS]
        assert values == sorted(values, reverse=True)

    def test_reproduces_table_2_for_the_innermost_ellipse(self, tables):
        """Ellipse A's ring is the whole of ellipse A, so MRD_A == AMRD_A."""
        weights = weight_profile(INPUTS, *tables)
        table2 = tables[1]
        expected = round(table2.weighted_depth("A", 3.0, 0.1, 0.9)) * 0.60 * 0.96
        assert weights["A"] == pytest.approx(round(expected))
        assert weights["A"] == pytest.approx(507)  # matches Table A2.2 column e

    def test_smooth_terrain_gives_lower_weights_than_rough(self, tables):
        smooth = weight_profile(Inputs(3.0, smooth=1.0, rough=0.0), *tables)
        rough = weight_profile(Inputs(3.0, smooth=0.0, rough=1.0), *tables)
        assert all(rough[l] > smooth[l] for l in "ABCDEFGH")


def test_inputs_reject_bad_terrain_split():
    with pytest.raises(ValueError):
        Inputs(duration_hr=3.0, smooth=0.5, rough=0.2)


def test_distribute_rejects_an_empty_template():
    with pytest.raises(ValueError):
        distribute({l: 0.0 for l in "ABCDEFGHIJ"}, INPUTS)


def test_outermost_beyond_H_warns(tables):
    """Ellipses I and J are outside the scope of the Bulletin."""
    areas = {"A": 2.6, "B": 13.4, "C": 49.0, "D": 88.0, "E": 127.0,
             "F": 153.0, "G": 202.0, "H": 212.0, "I": 270.0, "J": 50.0}
    result = distribute(areas, INPUTS, *tables)
    assert result.outermost == "J"
    assert any("outside the scope" in w for w in result.warnings)
    assert any("areal limit" in w for w in result.warnings)
