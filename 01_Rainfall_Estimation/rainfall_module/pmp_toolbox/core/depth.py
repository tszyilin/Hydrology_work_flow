"""Catchment-average PMP depth: GSDM, GTSMR and GSAM.

A port of the Toolbox website's ``backend/calculators/pmp``. The arithmetic is
unchanged and a parity test asserts that; the one substantive difference is
that the DDA tables are read through ``dda.AreaDepthTable`` (standard-library
``csv`` over sorted lists) instead of pandas, because QGIS does not reliably
ship pandas.

The three methods answer the same question over different ranges:

===========  ==================  ==========================================
Method       Durations           Adjustments
===========  ==================  ==========================================
GSDM         0.25 - 6 hr         terrain-weighted depth, then EAF and MAF
GTSMR        24 - 120 hr         TAF, DAF and MAF; summer and winter
GSAM         24 - 96 hr          TAF and MAF only, no DAF; summer and autumn
===========  ==================  ==========================================

Every method picks its controlling duration on the *unrounded* depths and only
then rounds to 10 mm, so a rounding tie can never move the controlling
duration.  This module holds no GIS: the caller supplies area in km2, having
got it from the catchment layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dda import DATA_DIR, MAX_AREA_KM2, AreaDepthTable

#: PMP depths are reported to the nearest 10 mm.
PMP_ROUNDING_MM = 10

#: The GTSMR and GSAM tables both start at 1 km2.
MIN_LONG_DURATION_AREA_KM2 = 1.0

_gsdm = AreaDepthTable(DATA_DIR / "dda_gsdm.csv")
_gtsmr = AreaDepthTable(DATA_DIR / "dda_gtsmr.csv")
_gsam = AreaDepthTable(DATA_DIR / "dda_gsam.csv")

#: The durations each GSDM terrain curve is tabulated at, in hours.
GSDM_DURATIONS = _gsdm.durations("S")


def round_pmp(value_mm: float) -> float:
    """Round a PMP depth to the nearest 10 mm, as every method reports it."""
    return float(round(value_mm / PMP_ROUNDING_MM) * PMP_ROUNDING_MM)


def storm_volume_m3(pmp_mm: float, area_km2: float) -> float:
    """PMP (mm) over an area (km2) as a volume in m3.

    ``mm x km2 x 1e6 m2/km2 x 1e-3 m/mm`` collapses to a factor of 1e3.
    """
    return round(pmp_mm * area_km2 * 1e3, 0)


@dataclass
class DurationDepth:
    duration_hr: float
    pmp_mm: float


@dataclass
class SeasonResult:
    """One season, or for GSDM the single all-year case."""

    label: str
    by_duration: list[DurationDepth]
    controlling_duration_hr: float
    pmp_mm: float
    zone: str | None = None
    maf: float | None = None

    def depth_at(self, duration_hr: float) -> float | None:
        for d in self.by_duration:
            if d.duration_hr == duration_hr:
                return d.pmp_mm
        return None


@dataclass
class MethodResult:
    """A method's answer, over one season (GSDM) or two (GTSMR, GSAM)."""

    method: str
    seasons: list[SeasonResult]
    governing_season: str
    pmp_mm: float
    controlling_duration_hr: float
    area_km2: float
    warnings: list[str] = field(default_factory=list)

    @property
    def volume_m3(self) -> float:
        return storm_volume_m3(self.pmp_mm, self.area_km2)

    def season(self, label: str) -> SeasonResult | None:
        for s in self.seasons:
            if s.label == label:
                return s
        return None


def _series(depths: dict[float, float], label: str, **extra) -> SeasonResult:
    """Pick the controlling duration unrounded, then round the whole series."""
    if not depths:
        raise ValueError(f"No durations available for {label}.")
    controlling = max(depths, key=depths.get)
    rounded = {d: round_pmp(v) for d, v in depths.items()}
    return SeasonResult(
        label=label,
        by_duration=[DurationDepth(d, rounded[d]) for d in sorted(rounded)],
        controlling_duration_hr=controlling,
        pmp_mm=rounded[controlling],
        **extra,
    )


def calc_gsdm(
    area_km2: float,
    duration_limit_hr: float,
    smooth: float,
    rough: float,
    eaf: float,
    maf: float,
) -> MethodResult:
    """Catchment-average GSDM PMP against duration.

    ``smooth`` and ``rough`` are fractions summing to 1 (GSDM section 4.2),
    ``eaf`` the elevation adjustment of section 4.3 and ``maf`` the moisture
    adjustment read off Figure 3.  ``duration_limit_hr`` is Figure 2's 3 or 6.

    Passing an ``area_km2`` of 0 gives the point value: the table carries a row
    at an area standing for a point, and the lookup clamps up to it.
    """
    warnings: list[str] = []
    depths: dict[float, float] = {}
    for duration in GSDM_DURATIONS:
        if duration > duration_limit_hr + 1e-9:
            continue
        ds = _gsdm.depth("S", duration, area_km2)
        dr = _gsdm.depth("R", duration, area_km2)
        depths[duration] = (smooth * ds + rough * dr) * eaf * maf

    if not depths:
        raise ValueError(
            f"No GSDM durations at or below the {duration_limit_hr:g} hour limit."
        )

    if area_km2 > MAX_AREA_KM2:
        warnings.append(
            f"Catchment area {area_km2:,.1f} km2 exceeds the {MAX_AREA_KM2:,.0f} km2 "
            "areal limit of the GSDM depth-area curves (section 4.5); the depth is "
            "extrapolated off the last two tabulated areas."
        )

    season = _series(depths, "all-year", maf=maf)
    return MethodResult(
        method="GSDM",
        seasons=[season],
        governing_season=season.label,
        pmp_mm=season.pmp_mm,
        controlling_duration_hr=season.controlling_duration_hr,
        area_km2=area_km2,
        warnings=warnings,
    )


def _long_duration(
    table: AreaDepthTable,
    method: str,
    area_km2: float,
    seasons: list[tuple[str, str, float]],
    factor: float,
) -> MethodResult:
    """The shared body of GTSMR and GSAM.

    ``seasons`` is ``(label, zone, maf)`` per season, and ``factor`` the product
    of the non-moisture adjustments: TAF and DAF for GTSMR, TAF alone for GSAM,
    which has no decay amplitude factor.

    A season whose ``zone`` is ``None`` is skipped, and said so in a warning.
    That case is real: the GTSMR inland zone has no winter equivalent, and
    substituting the coastal winter zone for it would invent a number for a
    catchment nowhere near the coast.
    """
    warnings: list[str] = []
    area = max(area_km2, MIN_LONG_DURATION_AREA_KM2)
    if area_km2 < MIN_LONG_DURATION_AREA_KM2:
        warnings.append(
            f"Catchment area {area_km2:,.3f} km2 is below the "
            f"{MIN_LONG_DURATION_AREA_KM2:g} km2 minimum of the {method} tables; "
            f"the {MIN_LONG_DURATION_AREA_KM2:g} km2 depth is used."
        )

    results = []
    for label, zone, maf in seasons:
        if not zone:
            warnings.append(
                f"No {method} {label} zone applies at this catchment, so no "
                f"{label} depths are given."
            )
            continue
        depths = {
            duration: table.depth(zone, duration, area) * factor * maf
            for duration in table.durations(zone)
        }
        results.append(_series(depths, label, zone=zone, maf=maf))

    if not results:
        raise ValueError(
            f"No {method} zone applies at this catchment, in either season."
        )

    # Ties go to the first season listed, which is summer for both methods.
    governing = max(results, key=lambda s: s.pmp_mm)
    return MethodResult(
        method=method,
        seasons=results,
        governing_season=governing.label,
        pmp_mm=governing.pmp_mm,
        controlling_duration_hr=governing.controlling_duration_hr,
        area_km2=area_km2,
        warnings=warnings,
    )


def calc_gtsmr(
    area_km2: float,
    zone_summer: str,
    zone_winter: str,
    epw_summer: float,
    epw_standard_summer: float,
    epw_winter: float,
    epw_standard_winter: float,
    taf: float,
    daf: float,
) -> MethodResult:
    """GTSMR PMP, 24 to 120 hours, over summer and winter.

    The moisture adjustment is the catchment EPW over the standard EPW
    (guidebook section 2.3.1), computed per season.  Either zone may be
    ``None``, in which case that season is left out rather than guessed at.
    """
    return _long_duration(
        _gtsmr,
        "GTSMR",
        area_km2,
        [
            ("summer", zone_summer, epw_summer / epw_standard_summer),
            ("winter", zone_winter, epw_winter / epw_standard_winter),
        ],
        taf * daf,
    )


def calc_gsam(
    area_km2: float,
    zone_summer: str,
    zone_autumn: str,
    epw_summer: float,
    epw_standard_summer: float,
    epw_autumn: float,
    epw_standard_autumn: float,
    taf: float,
) -> MethodResult:
    """GSAM PMP, 24 to 96 hours, over summer and autumn.

    Unlike GTSMR there is no decay amplitude factor.
    """
    return _long_duration(
        _gsam,
        "GSAM",
        area_km2,
        [
            ("summer", zone_summer, epw_summer / epw_standard_summer),
            ("autumn", zone_autumn, epw_autumn / epw_standard_autumn),
        ],
        taf,
    )
