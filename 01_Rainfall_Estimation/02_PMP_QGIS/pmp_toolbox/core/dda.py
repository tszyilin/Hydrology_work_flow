"""Depth-Duration-Area tables: GSDM Figure 4, GSDM Table 2, GTSMR and GSAM.

Every dataset is shipped as CSV under ``data/`` and read with the standard
library, so the plugin needs nothing beyond numpy at runtime.  QGIS does not
reliably ship pandas, which is why the Toolbox website's DataFrame lookups are
reimplemented here over plain sorted lists.

``dda_gsdm.csv`` is built from sheet ``Raw data`` of
``GSDM_Depth_Area_Curves_Digitise.xlsx``; ``table2.csv`` is transcribed from
Table 2 of ``GSDM.pdf``; ``dda_gtsmr.csv`` and ``dda_gsam.csv`` come from the
Bureau's GTSMR CD (2005).

Two lookups live here because they answer different questions:

``DDACurves``
    The ellipse path (GSDM section 6).  Areas are clamped to the 1-1000 km2
    range of the printed curves, and it interpolates in *duration* as well as
    area because a placement may be scored at an untabulated duration.

``AreaDepthTable``
    The catchment-average path, and GTSMR/GSAM.  Only tabulated durations are
    ever asked for, the point value (area 1e-5) participates in the
    interpolation, and areas above the table extrapolate off the last two
    rows.  This reproduces the Toolbox website's ``_lookup_depth`` exactly.
"""

from __future__ import annotations

import csv
import math
from bisect import bisect_left
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: The eleven durations the Bulletin tabulates, in hours.
DURATIONS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)

#: Areal limit of the DDA curves (GSDM section 4.5).  Ellipses I and J exceed it.
MAX_AREA_KM2 = 1000.0
MIN_AREA_KM2 = 1.0

#: The area the tables use to stand for a point.  Rows at this area are the
#: point rainfall depths, not an areal value, so ``DDACurves`` keeps them out
#: of the curve it interpolates along.
POINT_AREA_KM2 = 1e-5


def _interp(x, x0, x1, y0, y1):
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


class DDACurves:
    """Depth lookup over the digitised Figure 4 envelope curves.

    Interpolation is logarithmic in area (the curves are drawn on a log area
    axis) and linear in duration between the tabulated durations.
    """

    def __init__(self, path: Path | None = None):
        path = Path(path) if path else DATA_DIR / "dda_gsdm.csv"
        # {terrain: {duration: {area: depth}}}
        raw: dict[str, dict[float, dict[float, float]]] = {"S": {}, "R": {}}
        #: {(terrain, duration): depth} -- the point rows, held aside.
        self.point_depths: dict[tuple[str, float], float] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                terrain = row["terrain"].upper()
                duration = float(row["duration"])
                area = float(row["area"])
                depth = float(row["rainfall"])
                if area < MIN_AREA_KM2:
                    # The point value is not on the areal curve; keeping it out
                    # leaves this class's 1 km2 floor exactly where it was when
                    # the Table A2.2 fixture was written.
                    self.point_depths[(terrain, duration)] = depth
                    continue
                raw[terrain].setdefault(duration, {})[area] = depth

        self.durations = sorted(raw["S"])
        self.areas = sorted(raw["S"][self.durations[0]])
        self._log_areas = [math.log(a) for a in self.areas]
        # {terrain: {duration: [depth per area, in self.areas order]}}
        self._depths = {
            terrain: {d: [by_area[a] for a in self.areas] for d, by_area in by_dur.items()}
            for terrain, by_dur in raw.items()
        }

    def _depth_at_area(self, terrain: str, duration: float, area_km2: float) -> float:
        """Depth for one tabulated duration, log-interpolated in area."""
        depths = self._depths[terrain][duration]
        area = min(max(area_km2, self.areas[0]), self.areas[-1])
        i = bisect_left(self.areas, area)
        if i == 0:
            return depths[0]
        if area == self.areas[i]:
            return depths[i]
        return _interp(
            math.log(area),
            self._log_areas[i - 1],
            self._log_areas[i],
            depths[i - 1],
            depths[i],
        )

    def depth(self, terrain: str, duration_hr: float, area_km2: float) -> float:
        """Initial mean rainfall depth (mm) for one terrain category.

        ``area_km2`` is clamped to the 1-1000 km2 range of the curves; the
        caller is responsible for warning when that clamp bites.
        """
        terrain = terrain.upper()
        if terrain not in self._depths:
            raise ValueError(f"terrain must be 'S' or 'R', got {terrain!r}")

        durs = self.durations
        d = min(max(duration_hr, durs[0]), durs[-1])
        i = bisect_left(durs, d)
        if i == 0 or d == durs[i]:
            return self._depth_at_area(terrain, durs[i], area_km2)
        lo = self._depth_at_area(terrain, durs[i - 1], area_km2)
        hi = self._depth_at_area(terrain, durs[i], area_km2)
        return _interp(d, durs[i - 1], durs[i], lo, hi)

    def weighted_depth(
        self, duration_hr: float, area_km2: float, smooth: float, rough: float
    ) -> float:
        """``S * D_S + R * D_R`` (GSDM section 4.2). ``smooth + rough`` must be 1."""
        return smooth * self.depth("S", duration_hr, area_km2) + rough * self.depth(
            "R", duration_hr, area_km2
        )


class Table2:
    """Initial mean rainfall depths enclosed by ellipses A-H (GSDM Table 2).

    Used when a catchment *completely fills* an ellipse.  Ellipses I and J are
    absent from the Bulletin because their areas exceed the 1000 km2 areal
    limit of the DDA curves.
    """

    def __init__(self, path: Path | None = None):
        path = Path(path) if path else DATA_DIR / "table2.csv"
        self._depths: dict[tuple[str, str], dict[float, float]] = {}
        self.area_enclosed: dict[str, float] = {}
        self.area_between: dict[str, float] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            duration_cols = [c for c in reader.fieldnames if _is_number(c)]
            for row in reader:
                label = row["ellipse"].strip().upper()
                self.area_enclosed[label] = float(row["area_encl_km2"])
                self.area_between[label] = float(row["area_btwn_km2"])
                self._depths[(label, row["terrain"].upper())] = {
                    float(c): float(row[c]) for c in duration_cols
                }
        self.labels = sorted(self.area_enclosed)

    def has(self, ellipse: str) -> bool:
        return ellipse.upper() in self.area_enclosed

    def depth(self, ellipse: str, terrain: str, duration_hr: float) -> float:
        """Tabulated depth, linearly interpolated between tabulated durations."""
        by_duration = self._depths[(ellipse.upper(), terrain.upper())]
        durs = sorted(by_duration)
        d = min(max(duration_hr, durs[0]), durs[-1])
        i = bisect_left(durs, d)
        if i == 0 or d == durs[i]:
            return by_duration[durs[i]]
        return _interp(d, durs[i - 1], durs[i], by_duration[durs[i - 1]], by_duration[durs[i]])

    def weighted_depth(
        self, ellipse: str, duration_hr: float, smooth: float, rough: float
    ) -> float:
        return smooth * self.depth(ellipse, "S", duration_hr) + rough * self.depth(
            ellipse, "R", duration_hr
        )


def _is_number(s: str) -> bool:
    try:
        float(s)
    except (TypeError, ValueError):
        return False
    return True


class AreaDepthTable:
    """Depth by (zone, duration, area), log-x / linear-y in area.

    A faithful reimplementation of the Toolbox website's ``_lookup_depth``:
    below the first tabulated area the first depth is returned flat, above the
    last the last two rows are extrapolated along, and everything between is
    interpolated logarithmically in area.  Durations are never interpolated --
    callers ask for tabulated ones only.

    The GSDM file names its columns ``terrain``/``rainfall`` and the GTSMR and
    GSAM files ``zone``/``depth``; the column names are taken from the header
    so one class reads all three.
    """

    def __init__(self, path: Path | str):
        path = Path(path)
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            key_col = "zone" if "zone" in fields else "terrain"
            depth_col = "depth" if "depth" in fields else "rainfall"
            # {(zone, duration): {area: depth}}
            raw: dict[tuple[str, float], dict[float, float]] = {}
            for row in reader:
                key = (row[key_col].strip().upper(), float(row["duration"]))
                raw.setdefault(key, {})[float(row["area"])] = float(row[depth_col])

        # {(zone, duration): (areas, log_areas, depths)}, areas ascending.
        self._curves: dict[tuple[str, float], tuple[list, list, list]] = {}
        for key, by_area in raw.items():
            areas = sorted(by_area)
            self._curves[key] = (
                areas,
                [math.log(a) for a in areas],
                [by_area[a] for a in areas],
            )

        self.zones = sorted({z for z, _d in self._curves})
        #: {zone: [durations]} -- GTSMR runs to 120 hr, GSAM only to 96.
        self.durations_by_zone: dict[str, list[float]] = {}
        for zone, duration in self._curves:
            self.durations_by_zone.setdefault(zone, []).append(duration)
        for durations in self.durations_by_zone.values():
            durations.sort()

        #: The smallest area any curve tabulates, the floor callers clamp to.
        self.min_area_km2 = min(areas[0] for areas, _l, _d in self._curves.values())

    def durations(self, zone: str) -> list[float]:
        try:
            return self.durations_by_zone[zone.strip().upper()]
        except KeyError:
            raise ValueError(f"No data for zone {zone!r}") from None

    def depth(self, zone: str, duration_hr: float, area_km2: float) -> float:
        key = (zone.strip().upper(), float(duration_hr))
        try:
            areas, log_areas, depths = self._curves[key]
        except KeyError:
            raise ValueError(
                f"No data for zone={zone!r}, duration={duration_hr!r}"
            ) from None
        if len(areas) < 2:
            raise ValueError(f"No data for zone={zone!r}, duration={duration_hr!r}")

        area = max(float(area_km2), areas[0])
        if area <= areas[0]:
            return depths[0]
        if area >= areas[-1]:
            # Deliberately extrapolating rather than clamping, matching the
            # spreadsheet the Toolbox website was built to reproduce.
            return _interp(
                math.log(area), log_areas[-2], log_areas[-1], depths[-2], depths[-1]
            )
        i = bisect_left(areas, area)
        if area == areas[i]:
            return depths[i]
        return _interp(
            math.log(area), log_areas[i - 1], log_areas[i], depths[i - 1], depths[i]
        )
