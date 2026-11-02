"""GSDM maximum duration limit looked up by latitude / longitude.

From Figure 2 of the GSDM guidebook (BoM, June 2003), which splits Australia
into a six-hour zone, a three-hour zone, and an intermediate zone between them.
The guidebook interpolates across that band; this reports whole-hour limits
only, and in the band it offers both 3 and 6 for the engineer to choose.

The figure is a raster, so the two zone boundaries were traced from the printed
dashes and placed on the same Albers grid as the moisture-factor map, by
registering the figure's base map against that map's coastline (median 1 page
pixel, about 5 km).

A point is classified by a local test: take the nearest dash on each boundary;
if the two lie in opposite directions the point is inside the band, otherwise it
is beyond the nearer boundary. That needs no assumption that the boundaries are
single-valued, which matters because the band turns south down the east coast.

Vendored from the Toolbox website project
(``backend/calculators/gsdm_duration``), with the projection maths taken from
``projection`` rather than repeated here.
"""

from __future__ import annotations

import json
import math
import os

from .projection import LAT_RANGE, LON_RANGE, Sheet, check_range

_DATA = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "gsdm_duration.json"
)

with open(_DATA, "r", encoding="utf-8") as fh:
    _MAP = json.load(fh)

SHEET = Sheet(_MAP["projection"])
SIX_EDGE = [tuple(p) for p in _MAP["six_hour_edge"]]
THREE_EDGE = [tuple(p) for p in _MAP["three_hour_edge"]]

SIX_HOURS = 6.0
THREE_HOURS = 3.0

__all__ = [
    "LAT_RANGE",
    "LON_RANGE",
    "SIX_HOURS",
    "THREE_HOURS",
    "lookup",
    "to_page",
]


def to_page(lat: float, lon: float) -> tuple[float, float]:
    return SHEET.to_page(lat, lon)


def _nearest(edge, px: float, py: float):
    best = None
    for x, y in edge:
        d = (x - px) ** 2 + (y - py) ** 2
        if best is None or d < best[0]:
            best = (d, x, y)
    return math.sqrt(best[0]), best[1], best[2]


def lookup(lat: float, lon: float) -> dict:
    """Maximum GSDM duration for a catchment centroid -- always 3 or 6 hours."""
    check_range(lat, lon)

    px, py = SHEET.to_page(lat, lon)
    d6, x6, y6 = _nearest(SIX_EDGE, px, py)
    d3, x3, y3 = _nearest(THREE_EDGE, px, py)

    # Opposite directions => the point lies between the two boundaries.
    dot = (x6 - px) * (x3 - px) + (y6 - py) * (y3 - py)
    if dot < 0:
        # In the band either limit is defensible, so offer both and let the
        # engineer decide rather than picking one for them.
        return {
            "zone": "intermediate",
            "options": [THREE_HOURS, SIX_HOURS],
            "recommended": None,
            "nearer": SIX_HOURS if d6 < d3 else THREE_HOURS,
            "distance_px": [round(d6, 1), round(d3, 1)],
        }

    hours, zone = (SIX_HOURS, "six-hour") if d6 < d3 else (THREE_HOURS, "three-hour")
    return {
        "zone": zone,
        "options": [hours],
        "recommended": hours,
        "nearer": hours,
        "distance_px": [round(d6, 1), round(d3, 1)],
    }
