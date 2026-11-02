"""GSDM Figure 3, read by coordinate.

No QGIS needed: the lookup is pure Python over the digitised contours.  The
value it returns feeds Step 5 as a straight multiplier on every depth, so a
silent 0.05 error here moves the whole PMP by 7 percent -- hence the pinned
reference points below.
"""

import math

import pytest

from pmp_toolbox.core import maf

#: Places with a known moisture climate, and the factor Figure 3 gives there.
#: Tolerance is one 0.05 contour interval: these pin the map's shape, not the
#: digitiser's last pixel.
PLACES = [
    ("Darwin", -12.46, 130.84, 1.00),
    ("Alice Springs", -23.70, 133.88, 0.80),
    ("Sydney", -33.87, 151.21, 0.70),
    ("Perth", -31.95, 115.86, 0.63),
    ("Melbourne", -37.81, 144.96, 0.53),
    ("Hobart", -42.88, 147.33, 0.51),
]


class TestLookup:
    @pytest.mark.parametrize("name,lat,lon,expected", PLACES)
    def test_known_places(self, name, lat, lon, expected):
        assert maf.lookup(lat, lon)["maf"] == pytest.approx(expected, abs=0.05)

    def test_it_gets_wetter_towards_the_tropics(self):
        """Figure 3's dominant gradient: moisture falls away from the north."""
        along_135e = [maf.lookup(lat, 135.0)["maf"] for lat in (-12, -18, -24, -30)]
        assert along_135e == sorted(along_135e, reverse=True)

    def test_the_value_stays_within_the_drawn_contours(self):
        for lat in range(-40, -10, 3):
            for lon in range(115, 152, 4):
                value = maf.lookup(lat, lon)["maf"]
                assert maf.MIN_VALUE <= value <= maf.MAX_VALUE

    def test_it_reports_the_contours_it_interpolated_between(self):
        reading = maf.lookup(-23.70, 133.88)
        assert reading["lower"] <= reading["maf"] <= reading["upper"]
        assert reading["bracketed"] in (True, False)

    def test_the_value_is_rounded_to_the_map_s_precision(self):
        """A hand-drawn 0.05 contour map cannot support finer than 0.005."""
        for lat, lon in ((-20.0, 140.0), (-30.5, 125.25), (-35.0, 148.0)):
            value = maf.lookup(lat, lon)["maf"]
            assert value / maf.STEP == pytest.approx(round(value / maf.STEP))

    def test_nearby_points_give_nearby_values(self):
        """Continuity: 0.05 degrees is ~5 km, about the digitising accuracy."""
        base = maf.lookup(-25.0, 140.0)["maf"]
        for dlat, dlon in ((0.05, 0), (-0.05, 0), (0, 0.05), (0, -0.05)):
            assert maf.lookup(-25.0 + dlat, 140.0 + dlon)["maf"] == pytest.approx(
                base, abs=0.02
            )


class TestOutsideTheMap:
    """Figure 3 covers Australia; beyond it there is no answer to give."""

    @pytest.mark.parametrize(
        "lat,lon",
        [
            (-5.0, 140.0),    # north of the sheet
            (-50.0, 145.0),   # south of it
            (-25.0, 100.0),   # west
            (-25.0, 170.0),   # east (New Zealand)
        ],
    )
    def test_refuses_rather_than_extrapolating(self, lat, lon):
        with pytest.raises(ValueError):
            maf.lookup(lat, lon)

    def test_the_corners_of_the_stated_range_are_accepted(self):
        for lat in maf.LAT_RANGE:
            for lon in maf.LON_RANGE:
                assert maf.lookup(lat, lon)["maf"] > 0


class TestProjection:
    """The sheet's Albers parameters, recovered from the printed graticule."""

    def test_the_page_position_is_finite_across_the_map(self):
        for lat in (-10.0, -25.0, -43.0):
            for lon in (111.0, 135.0, 155.0):
                x, y = maf.to_page(lat, lon)
                assert math.isfinite(x) and math.isfinite(y)

    def test_moving_south_moves_down_the_page(self):
        _x1, y1 = maf.to_page(-20.0, 135.0)
        _x2, y2 = maf.to_page(-30.0, 135.0)
        assert y2 < y1

    def test_moving_east_moves_right(self):
        x1, _y1 = maf.to_page(-25.0, 130.0)
        x2, _y2 = maf.to_page(-25.0, 140.0)
        assert x2 > x1


def test_the_data_file_ships_with_the_plugin():
    """A missing data file would only show up when a user opens the dialog."""
    import os

    assert os.path.exists(maf._DATA)
    assert len(maf._CONTOURS) > 100
    assert maf.SOURCE
