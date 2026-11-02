"""The PSM6186 worked examples, end to end.

``01_PMP/PSM6186_examples.xlsx`` is a real job: two catchments near Kalgoorlie
(M3, 361.255 km2 and M1, 29.187 km2) carried through GSDM and GTSMR by hand in
a spreadsheet, with every intermediate depth shown.  It is the strongest
fixture available, because it was produced independently of this code and of
the Toolbox website, from the Bureau's own tables.

Two separate things are checked, and it matters that they are separate:

1. **The arithmetic** -- given the spreadsheet's own inputs, do we reproduce
   its 46 rounded depths exactly?  This is a hard equality: the guidebook
   rounds to 10 mm, so there is no tolerance to hide in.

2. **The grid sampling** -- reading EPW and TAF at the catchment centroid from
   the resampled 0.05 degree grids, do we recover the values the spreadsheet's
   author read off the Bureau's full-resolution 0.005 degree grids?  This one
   has a real tolerance, because it compares two different samplings of the
   same field, and it is the evidence behind the decision to sample at the
   centroid rather than average over the catchment outline.

If (1) ever fails the calculation is wrong.  If only (2) drifts, the resampled
grids are the suspect, not the maths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pmp_toolbox.core import depth, grids

WORKBOOK = Path(__file__).resolve().parents[2] / "01_PMP" / "PSM6186_examples.xlsx"

#: Grid factors are compared as a relative difference.  The module docstring of
#: ``core.grids`` reports agreement to within 0.03% against these very
#: catchments; 0.1% leaves room for a resample without hiding a real error.
GRID_TOLERANCE = 0.001


class Catchment:
    """One column of the workbook's Input sheet, transcribed."""

    def __init__(self, name, area_km2, lat, lon, epw_s, epw_w, taf, daf, maf):
        self.name = name
        self.area_km2 = area_km2
        self.lat = lat
        self.lon = lon
        self.epw_summer = epw_s
        self.epw_winter = epw_w
        self.taf = taf
        self.daf = daf
        self.maf = maf


M3 = Catchment(
    "M3", 361.255, -21.955, 116.292, 104.7388, 75.2724, 1.038, 1.0, 1.01
)
M1 = Catchment(
    "M1", 29.187, -21.913, 116.126, 104.9934, 75.4778, 1.049, 1.0, 1.01
)

# Both catchments: 6 hour limit, 0% smooth / 100% rough, EAF 1.0, MAF 1.01.
GSDM_DURATION_LIMIT = 6.0
GSDM_SMOOTH = 0.0
GSDM_ROUGH = 1.0
GSDM_EAF = 1.0

#: Sheet M3 / M1, column "PMP Rounded" of section 6.
GSDM_EXPECTED = {
    "M3": [
        (0.25, 140), (0.5, 200), (0.75, 250), (1.0, 310), (1.5, 400), (2.0, 460),
        (2.5, 530), (3.0, 570), (4.0, 650), (5.0, 690), (6.0, 740),
    ],
    "M1": [
        (0.25, 200), (0.5, 290), (0.75, 370), (1.0, 430), (1.5, 560), (2.0, 650),
        (2.5, 720), (3.0, 780), (4.0, 890), (5.0, 980), (6.0, 1040),
    ],
}

#: Sheet M3 / M1, column "PMP Rounded" of the summer and winter GTSMR blocks.
GTSMR_EXPECTED = {
    "M3": {
        "summer": [(24, 1170), (36, 1410), (48, 1630), (72, 2030), (96, 2280), (120, 2400)],
        "winter": [(24, 730), (36, 890), (48, 1000), (72, 1110), (96, 1140), (120, 1180)],
    },
    "M1": {
        "summer": [(24, 1240), (36, 1520), (48, 1780), (72, 2240), (96, 2510), (120, 2630)],
        "winter": [(24, 800), (36, 960), (48, 1060), (72, 1190), (96, 1220), (120, 1260)],
    },
}

CATCHMENTS = {"M3": M3, "M1": M1}


@pytest.mark.parametrize("name", ["M3", "M1"])
def test_gsdm_reproduces_worked_example(name):
    c = CATCHMENTS[name]
    result = depth.calc_gsdm(
        c.area_km2, GSDM_DURATION_LIMIT, GSDM_SMOOTH, GSDM_ROUGH, GSDM_EAF, c.maf
    )
    got = [(d.duration_hr, d.pmp_mm) for d in result.seasons[0].by_duration]
    assert got == [(d, float(v)) for d, v in GSDM_EXPECTED[name]]
    # The longest duration governs for both catchments, the curves being
    # monotonic in duration.
    assert result.controlling_duration_hr == 6.0
    assert result.pmp_mm == float(GSDM_EXPECTED[name][-1][1])


@pytest.mark.parametrize("name", ["M3", "M1"])
def test_gtsmr_reproduces_worked_example(name):
    c = CATCHMENTS[name]
    result = depth.calc_gtsmr(
        c.area_km2,
        "COAST_S",
        "COAST_W",
        c.epw_summer,
        120.0,
        c.epw_winter,
        82.3,
        c.taf,
        c.daf,
    )
    for season, expected in GTSMR_EXPECTED[name].items():
        got = [(d.duration_hr, d.pmp_mm) for d in result.season(season).by_duration]
        assert got == [(float(d), float(v)) for d, v in expected], season

    # Summer governs at both sites, at the longest duration.
    assert result.governing_season == "summer"
    assert result.controlling_duration_hr == 120.0
    assert result.pmp_mm == float(GTSMR_EXPECTED[name]["summer"][-1][1])


@pytest.mark.parametrize("name", ["M3", "M1"])
def test_grid_factors_at_centroid_match_worked_example(name):
    """The resampled grids, read at the centroid, recover the job's own values.

    The spreadsheet's author read the Bureau's full-resolution 0.005 degree
    grids; this reads a 0.05 degree resample of them.  Agreement here is what
    justifies shipping the 1.1 MB resample instead of 1.7 GB of ASCII.
    """
    c = CATCHMENTS[name]
    sampled = grids.lookup(c.lat, c.lon)

    for key, expected in [
        ("epw_summer", c.epw_summer),
        ("epw_winter", c.epw_winter),
        ("taf", c.taf),
        ("daf", c.daf),
    ]:
        got = sampled[key]
        assert got is not None, key
        assert abs(got - expected) / expected < GRID_TOLERANCE, (
            f"{name} {key}: sampled {got} vs workbook {expected}"
        )


@pytest.mark.parametrize("name", ["M3", "M1"])
def test_sampled_factors_still_give_the_worked_answer(name):
    """The whole chain: centroid -> grids -> GTSMR depths.

    The two tests above check the halves separately.  This one runs them
    joined, which is what the plugin actually does, and asserts the rounded
    answer is unchanged.  A resampling error small enough to pass the tolerance
    above but large enough to move a 10 mm rounding boundary would show up
    here and nowhere else.
    """
    c = CATCHMENTS[name]
    sampled = grids.lookup(c.lat, c.lon)
    result = depth.calc_gtsmr(
        c.area_km2,
        "COAST_S",
        "COAST_W",
        sampled["epw_summer"],
        sampled["epw_standard_summer"],
        sampled["epw_winter"],
        sampled["epw_standard_winter"],
        sampled["taf"],
        sampled["daf"],
    )
    for season, expected in GTSMR_EXPECTED[name].items():
        got = [(d.duration_hr, d.pmp_mm) for d in result.season(season).by_duration]
        assert got == [(float(d), float(v)) for d, v in expected], season


def test_workbook_is_present():
    """The fixture above is a transcription; this is the file it came from.

    Kept as its own test so that a missing workbook reads as one clear failure
    rather than leaving the transcribed numbers looking self-certifying.
    """
    assert WORKBOOK.is_file(), f"Worked-example workbook not found at {WORKBOOK}"
