"""GTSMR catchment factors looked up by latitude / longitude.

The Bureau's GTSMR CD (September 2005) ships four continental grids at 0.005
degrees: annual and winter extreme precipitable water, the topographic
adjustment factor and the decay amplitude factor. Together they are about
1.7 GB of ASCII, so they are resampled here to 0.05 degrees and stored
quantised — 1.1 MB for all four.

That resampling is cheap in accuracy because the fields are smooth: measured
against the full-resolution grids over 4000 sample points, the mean error is
0.010 mm for annual EPW, 0.013 mm for winter EPW, 0.0004 for TAF and 0.0001
for DAF. Against the two worked catchments in PSM6186_examples.xlsx every
value agrees to within 0.03%.

Per section 2.3.1 of the guidebook the moisture adjustment factor is the
catchment EPW divided by the standard EPW — 120.0 mm annual, 82.3 mm winter.
The guidebook averages the EPW grid over the catchment outline; this uses the
value at the centroid, which is what the worked spreadsheets do.

Vendored from the Toolbox website project
(``backend/calculators/gtsmr_grids``), changed only in the data path so a fix
in either can be carried across.
"""
import json
import math
import os

import numpy as np

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

with open(os.path.join(_DIR, "meta.json"), "r", encoding="utf-8") as fh:
    _META = json.load(fh)

# Read the arrays out and *close the file*. np.load on an .npz hands back a
# lazily-loading NpzFile that keeps the archive open until it is closed; held
# in a module global, that handle stays open for the whole QGIS session, and
# Windows then refuses to delete the plugin folder -- so the plugin cannot be
# uninstalled or reinstalled without quitting QGIS first.
#
# The Toolbox website this was vendored from can hold the file open quite
# safely: a server process never uninstalls itself. A plugin does.
with np.load(os.path.join(_DIR, "gtsmr_grids.npz")) as _archive:
    _GRIDS = {
        k: _archive[k] for k in ("epw_summer", "epw_winter", "taf", "daf")
    }

CELLSIZE = _META["cellsize"]
TOP_LAT = _META["top_lat"]
LEFT_LON = _META["left_lon"]
NODATA = _META["nodata"]
SCALE = _META["scale"]

EPW_STANDARD_SUMMER = 120.0     # guidebook section 2.3.1
EPW_STANDARD_WINTER = 82.3

LAT_RANGE = (-44.0, -9.0)
LON_RANGE = (110.0, 158.0)


def _bilinear(arr, scale, lat, lon):
    fr = (TOP_LAT - lat) / CELLSIZE
    fc = (lon - LEFT_LON) / CELLSIZE
    r0, c0 = int(math.floor(fr)), int(math.floor(fc))
    dr, dc = fr - r0, fc - c0
    h, w = arr.shape
    if r0 < 0 or c0 < 0 or r0 + 1 >= h or c0 + 1 >= w:
        r = min(max(int(round(fr)), 0), h - 1)
        c = min(max(int(round(fc)), 0), w - 1)
        v = int(arr[r, c])
        return None if v == NODATA else v / scale

    block = arr[r0:r0 + 2, c0:c0 + 2]
    if (block == NODATA).any():
        # Near the coast, fall back to the nearest cell that has data.
        r = min(max(int(round(fr)), 0), h - 1)
        c = min(max(int(round(fc)), 0), w - 1)
        v = int(arr[r, c])
        if v != NODATA:
            return v / scale
        for rad in range(1, 6):
            r1, r2 = max(0, r - rad), min(h, r + rad + 1)
            c1, c2 = max(0, c - rad), min(w, c + rad + 1)
            patch = arr[r1:r2, c1:c2]
            good = patch[patch != NODATA]
            if good.size:
                return float(good.mean()) / scale
        return None

    q = block.astype(np.float64) / scale
    return float((1 - dr) * ((1 - dc) * q[0, 0] + dc * q[0, 1])
                 + dr * ((1 - dc) * q[1, 0] + dc * q[1, 1]))


def lookup(lat: float, lon: float) -> dict:
    """GTSMR catchment factors at a centroid."""
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        raise ValueError(
            f"Latitude {lat} is outside the GTSMR grids "
            f"({LAT_RANGE[0]} to {LAT_RANGE[1]})."
        )
    if not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
        raise ValueError(
            f"Longitude {lon} is outside the GTSMR grids "
            f"({LON_RANGE[0]} to {LON_RANGE[1]})."
        )

    vals = {k: _bilinear(_GRIDS[k], SCALE[k], lat, lon) for k in _GRIDS}
    if vals["epw_summer"] is None:
        raise ValueError(
            "No GTSMR grid data at this point — it is outside the area the "
            "Bureau's grids cover (offshore, or beyond the GTSMR region)."
        )

    epw_s = vals["epw_summer"]
    epw_w = vals["epw_winter"]
    taf = vals["taf"]
    daf = vals["daf"]

    return {
        "epw_summer": round(epw_s, 3),
        "epw_winter": round(epw_w, 3) if epw_w is not None else None,
        "epw_standard_summer": EPW_STANDARD_SUMMER,
        "epw_standard_winter": EPW_STANDARD_WINTER,
        "maf_summer": round(epw_s / EPW_STANDARD_SUMMER, 4),
        "maf_winter": (round(epw_w / EPW_STANDARD_WINTER, 4)
                       if epw_w is not None else None),
        "taf": round(taf, 4) if taf is not None else None,
        "daf": round(daf, 4) if daf is not None else None,
    }
