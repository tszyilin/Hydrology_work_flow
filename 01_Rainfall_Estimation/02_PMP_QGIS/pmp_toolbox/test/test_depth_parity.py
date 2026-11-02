"""``core.depth`` must agree with the Toolbox website it was ported from.

The port swapped pandas DataFrames for standard-library ``csv`` over sorted
lists, because QGIS does not reliably ship pandas.  That is exactly the kind of
change that can be subtly wrong -- an off-by-one in a bisect, a clamp applied at
the wrong end, a duration series drawn from the wrong zone -- while still
looking plausible.  So the two are run side by side here and asserted equal to
the millimetre.

The Toolbox backend needs pandas, which QGIS's interpreter usually lacks, so
every test skips cleanly when it cannot be imported.  That means these tests
are expected to run under a plain Python with pandas installed, and to skip
under ``python-qgis-ltr.bat``.  Skipping is not passing: if the whole file
skips everywhere, the port is unverified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pmp_toolbox.core import depth

#: The Toolbox website checkout this plugin's calculations were ported from.
TOOLBOX_BACKEND = (
    Path(__file__).resolve().parents[3] / "18_Toolbox_website" / "backend"
)


@pytest.fixture(scope="module")
def toolbox():
    """The Toolbox website's own ``calculate``, or a skip if it is unavailable."""
    if not TOOLBOX_BACKEND.is_dir():
        pytest.skip(f"Toolbox website checkout not found at {TOOLBOX_BACKEND}")
    pytest.importorskip("pandas", reason="the Toolbox backend reads its CSVs with pandas")
    if str(TOOLBOX_BACKEND) not in sys.path:
        sys.path.insert(0, str(TOOLBOX_BACKEND))
    from calculators import pmp  # noqa: PLC0415 -- deliberately late, after sys.path

    return pmp


# A spread that exercises every branch of the area lookup: below the table
# minimum, on a tabulated breakpoint, between breakpoints, and above the top of
# the table where the lookup extrapolates rather than clamps.
AREAS = [0.5, 1.0, 2.0, 53.7, 110.0, 999.0, 1000.0, 4200.0, 150_000.0]

GSDM_CASES = [
    # (duration_limit, smooth %, rough %, eaf, maf)
    (3.0, 10.0, 90.0, 0.96, 0.60),
    (6.0, 100.0, 0.0, 1.00, 1.00),
    (6.0, 0.0, 100.0, 0.85, 1.15),
    (3.0, 55.0, 45.0, 0.90, 0.73),
]


@pytest.mark.parametrize("area", AREAS)
@pytest.mark.parametrize("limit,smooth,rough,eaf,maf", GSDM_CASES)
def test_gsdm_matches_toolbox(toolbox, area, limit, smooth, rough, eaf, maf):
    theirs = toolbox.calculate(
        [
            {
                "name": "t",
                "area": area,
                "gsdm_enabled": True,
                "gsdm": {
                    "duration_limit": limit,
                    "smooth_fraction": smooth,
                    "rough_fraction": rough,
                    "elevation_factor": eaf,
                    "moisture_factor": maf,
                },
            }
        ]
    )[0]["gsdm"]

    ours = depth.calc_gsdm(area, limit, smooth / 100, rough / 100, eaf, maf)

    assert ours.pmp_mm == theirs["pmp_mm"]
    assert ours.controlling_duration_hr == theirs["controlling_duration_hr"]
    assert [(d.duration_hr, d.pmp_mm) for d in ours.seasons[0].by_duration] == [
        (d["duration_hr"], d["pmp_mm"]) for d in theirs["by_duration"]
    ]


GTSMR_CASES = [
    # (zone_summer, zone_winter, epw_s, epw_w, taf, daf)
    ("COAST_S", "COAST_W", 98.5, 69.7, 1.0, 1.0),
    ("COAST_S", "COAST_W", 120.0, 82.3, 1.35, 0.82),
    ("INLAND_S", "SWWA_W", 74.2, 55.1, 1.08, 0.95),
]


@pytest.mark.parametrize("area", AREAS)
@pytest.mark.parametrize("zone_s,zone_w,epw_s,epw_w,taf,daf", GTSMR_CASES)
def test_gtsmr_matches_toolbox(toolbox, area, zone_s, zone_w, epw_s, epw_w, taf, daf):
    theirs = toolbox.calculate(
        [
            {
                "name": "t",
                "area": area,
                "gtsmr_enabled": True,
                "gtsmr": {
                    "epw_avg_summer": epw_s,
                    "epw_std_summer": 120.0,
                    "epw_avg_winter": epw_w,
                    "epw_std_winter": 82.3,
                    "decay_factor": daf,
                    "topographic_factor": taf,
                    "zone_summer": zone_s,
                    "zone_winter": zone_w,
                },
            }
        ]
    )[0]["gtsmr"]

    ours = depth.calc_gtsmr(
        area, zone_s, zone_w, epw_s, 120.0, epw_w, 82.3, taf, daf
    )

    assert ours.pmp_mm == theirs["pmp_mm"]
    assert ours.controlling_duration_hr == theirs["controlling_duration_hr"]
    assert ours.governing_season == theirs["governing_season"]
    for label in ("summer", "winter"):
        assert [
            (d.duration_hr, d.pmp_mm) for d in ours.season(label).by_duration
        ] == [(d["duration_hr"], d["pmp_mm"]) for d in theirs[label]["by_duration"]]


GSAM_CASES = [
    # (zone_summer, zone_autumn, epw_s, epw_a, taf)
    ("GSAM_CS", "GSAM_CA", 98.5, 69.7, 1.0),
    ("GSAM_IS", "GSAM_IA", 74.2, 55.1, 1.22),
]


@pytest.mark.parametrize("area", AREAS)
@pytest.mark.parametrize("zone_s,zone_a,epw_s,epw_a,taf", GSAM_CASES)
def test_gsam_matches_toolbox(toolbox, area, zone_s, zone_a, epw_s, epw_a, taf):
    theirs = toolbox.calculate(
        [
            {
                "name": "t",
                "area": area,
                "gsam_enabled": True,
                "gsam": {
                    "epw_avg_summer": epw_s,
                    "epw_std_summer": 120.0,
                    "epw_avg_autumn": epw_a,
                    "epw_std_autumn": 82.3,
                    "topographic_factor": taf,
                    "zone_summer": zone_s,
                    "zone_autumn": zone_a,
                },
            }
        ]
    )[0]["gsam"]

    ours = depth.calc_gsam(area, zone_s, zone_a, epw_s, 120.0, epw_a, 82.3, taf)

    assert ours.pmp_mm == theirs["pmp_mm"]
    assert ours.controlling_duration_hr == theirs["controlling_duration_hr"]
    assert ours.governing_season == theirs["governing_season"]
    for label in ("summer", "autumn"):
        assert [
            (d.duration_hr, d.pmp_mm) for d in ours.season(label).by_duration
        ] == [(d["duration_hr"], d["pmp_mm"]) for d in theirs[label]["by_duration"]]


def test_volume_matches_toolbox(toolbox):
    """The storm volume conversion, which the Toolbox does inline in ``calculate``."""
    theirs = toolbox.calculate(
        [
            {
                "name": "t",
                "area": 110.0,
                "gsdm_enabled": True,
                "gsdm": {
                    "duration_limit": 3.0,
                    "smooth_fraction": 10.0,
                    "rough_fraction": 90.0,
                    "elevation_factor": 0.96,
                    "moisture_factor": 0.60,
                },
            }
        ]
    )[0]

    ours = depth.calc_gsdm(110.0, 3.0, 0.1, 0.9, 0.96, 0.60)
    assert ours.volume_m3 == theirs["volume_m3"]
    assert ours.pmp_mm == theirs["governing_pmp_mm"]
