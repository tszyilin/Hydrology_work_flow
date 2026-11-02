"""ARR2019 Areal Reduction Factor — pure-Python port.

Port of Tony Ladson's R implementation
(https://gist.github.com/TonyLadson/fffaee298888267b214065451884952b),
which follows ARR2019 Book 2 Chapter 4. No Qt / QGIS imports so the
math is testable in isolation.
"""
from __future__ import annotations

import math
from typing import Iterable

# Regions in the same order as the Shiny app's dropdown.
REGIONS: tuple[str, ...] = (
    "East Coast North",
    "Semi-arid Inland QLD",
    "Tasmania",
    "SW WA",
    "Central NSW",
    "SE Coast",
    "Southern Semi-arid",
    "Southern Temperate",
    "Northern Coastal",
    "Inland Arid",
)

# Long-duration regional parameters (a, b, c, d, e, f, g, h, i).
PARAMS: dict[str, tuple[float, ...]] = {
    "East Coast North":     (0.327,  0.241, 0.448, 0.36,  0.00096,   0.48,  -0.21,   0.012,   -0.0013),
    "Semi-arid Inland QLD": (0.159,  0.283, 0.25,  0.308, 7.3e-07,   1.0,    0.039,  0.0,      0.0),
    "Tasmania":             (0.0605, 0.347, 0.2,   0.283, 0.00076,   0.347,  0.0877, 0.012,   -0.00033),
    "SW WA":                (0.183,  0.259, 0.271, 0.33,  3.845e-06, 0.41,   0.55,   0.00817, -0.00045),
    "Central NSW":          (0.265,  0.241, 0.505, 0.321, 0.00056,   0.414, -0.021,  0.015,   -0.00033),
    "SE Coast":             (0.06,   0.361, 0.0,   0.317, 8.11e-05,  0.651,  0.0,    0.0,      0.0),
    "Southern Semi-arid":   (0.254,  0.247, 0.403, 0.351, 0.0013,    0.302,  0.058,  0.0,      0.0),
    "Southern Temperate":   (0.158,  0.276, 0.372, 0.315, 0.000141,  0.41,   0.15,   0.01,    -0.0027),
    "Northern Coastal":     (0.326,  0.223, 0.442, 0.323, 0.0013,    0.58,  -0.374,  0.013,   -0.0015),
    "Inland Arid":          (0.297,  0.234, 0.449, 0.344, 0.00142,   0.216,  0.129,  0.0,      0.0),
}

# Short-duration national parameters (a, b, c, d, e, f, g, h, i, j).
_SHORT = (
    0.287,   # a
    0.265,   # b
    0.439,   # c
    0.36,    # d
    0.00226, # e
    0.226,   # f
    0.125,   # g
    0.0141,  # h
    -0.021,  # i
    0.213,   # j
)

# Validation bounds — mirror the R Shiny app.
AREA_MIN, AREA_MAX = 0.0, 30000.0
DURATION_MIN, DURATION_MAX = 0.0, 7 * 24 * 60  # 10080 min
AEP_MIN, AEP_MAX = 0.0005, 0.5  # fractional


class ArfInputError(ValueError):
    """Raised when inputs are out of range for the ARR2019 method."""


def _check(area: float, duration: float, aep: float) -> None:
    if not (AREA_MIN <= area <= AREA_MAX):
        raise ArfInputError("Area must be between 0 and 30,000 km^2.")
    if not (AEP_MIN <= aep <= AEP_MAX):
        raise ArfInputError("AEP must be between 0.05% and 50% (0.0005-0.5 as a fraction).")
    if not (DURATION_MIN <= duration <= DURATION_MAX):
        raise ArfInputError("Duration must be between 0 and 10,080 min (7 days).")
    if duration <= 720 and area > 1000:
        raise ArfInputError(
            "Generalised equations are not applicable for durations <= 12 h "
            "(720 min) when the catchment area exceeds 1000 km^2."
        )


def arf_long(area: float, duration: float, aep: float, region: str) -> float:
    """Long-duration ARF (≥ 24 h), region-specific."""
    if region not in PARAMS:
        raise ArfInputError(
            f'Invalid region "{region}". Valid regions are: {", ".join(REGIONS)}.'
        )
    a, b, c, d, e, f, g, h, i = PARAMS[region]
    log_dur = math.log10(duration)
    log_aep = math.log10(aep)
    val = (
        1
        - a * (area ** b - c * log_dur) * duration ** -d
        + e * area ** f * duration ** g * (0.3 + log_aep)
        + h * 10 ** (i * area * duration / 1440.0) * (0.3 + log_aep)
    )
    return min(1.0, val)


def arf_short(area: float, duration: float, aep: float) -> float:
    """Short-duration ARF (≤ 12 h), national parameters."""
    a, b, c, d, e, f, g, h, i, j = _SHORT
    log_dur = math.log10(duration)
    log_aep = math.log10(aep)
    val = (
        1
        - a * (area ** b - c * log_dur) * duration ** -d
        + e * area ** f * duration ** g * (0.3 + log_aep)
        + h * area ** j
          * 10 ** (i * (1.0 / 1440.0) * (duration - 180) ** 2)
          * (0.3 + log_aep)
    )
    return min(1.0, val)


def arf(area: float, duration: float, aep: float, region: str | None = None) -> float:
    """ARR2019 ARF router.

    ``region`` is only required when the long-duration branch is used
    (duration > 12 h). Returns a value in [0, 1].
    """
    _check(area, duration, aep)

    if area <= 1:
        return 1.0

    # ≥ 24 h — long-duration branch.
    if duration >= 1440:
        if region is None:
            raise ArfInputError("Region is required for durations ≥ 24 h.")
        if area >= 10:
            return arf_long(area, duration, aep, region)
        arf_long_10 = arf_long(10, duration, aep, region)
        return 1 - 0.6614 * (1 - arf_long_10) * (area ** 0.4 - 1)

    # ≤ 12 h — short-duration branch.
    if duration <= 720:
        if area >= 10:
            return max(0.0, arf_short(area, duration, aep))
        arf_short_10 = arf_short(10, duration, aep)
        return 1 - 0.6614 * (1 - arf_short_10) * (area ** 0.4 - 1)

    # 12 h < duration < 24 h — interpolate between the short-12 h and long-24 h
    # endpoints. The long-duration endpoint needs a region.
    if region is None:
        raise ArfInputError(
            "Region is required for durations between 12 h and 24 h "
            "(the 24-hour end of the interpolation is region-specific)."
        )

    if area < 10:
        arf_long_24 = arf_long(10, 1440, aep, region)
        arf_short_12 = arf_short(10, 720, aep)
        arf_interp_10 = arf_short_12 + (arf_long_24 - arf_short_12) * (duration - 720) / 720
        return 1 - 0.6614 * (1 - arf_interp_10) * (area ** 0.4 - 1)

    arf_long_24 = arf_long(area, 1440, aep, region)
    arf_short_12 = arf_short(area, 720, aep)
    return arf_short_12 + (arf_long_24 - arf_short_12) * (duration - 720) / 720


def arf_curve(
    durations: Iterable[float],
    area: float,
    aep: float,
    region: str | None = None,
) -> list[float]:
    """ARF for a sequence of durations — used by the plot tab."""
    return [arf(area, d, aep, region) for d in durations]
