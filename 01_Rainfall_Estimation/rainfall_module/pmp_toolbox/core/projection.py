"""The Albers Equal-Area Conic sheet the GSDM figures are drawn on.

GSDM Figure 3 (moisture adjustment) and Figure 2 (duration limit) share one
projection: Figure 2 is a raster, so its boundaries were traced and registered
against Figure 3's coastline.  Both digitisations therefore carry the same
``projection`` block in their JSON, and both need the same forward transform.

The Toolbox website has this maths twice, copied verbatim between
``gsdm_maf`` and ``gsdm_duration``.  Here it lives once: the ellipsoid
constants are fixed, and the sheet-specific parameters arrive per figure via
``Sheet``.  Standard library only.
"""

from __future__ import annotations

import math

#: GRS80.  Both figures are drawn on it, so it is not a per-sheet parameter.
E2 = 0.00669438002290
E = math.sqrt(E2)

#: Rough extent of the drawn maps.  Outside this a reading is extrapolation,
#: so both lookups refuse rather than answer.
LAT_RANGE = (-44.0, -8.0)
LON_RANGE = (110.0, 156.0)


def q(phi: float) -> float:
    """Authalic (equal-area) latitude term, for a latitude in radians."""
    s = math.sin(phi)
    return (1 - E2) * (
        s / (1 - E2 * s * s) - (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s))
    )


class Sheet:
    """One figure's Albers parameters, as recovered from its printed graticule."""

    def __init__(self, projection: dict):
        self.apex_x, self.apex_y = projection["apex"]
        self.a = projection["A"]
        self.b = projection["B"]
        self.n = projection["n"]
        self.lon0 = projection["lon0"]

    def to_page(self, lat: float, lon: float) -> tuple[float, float]:
        """Latitude/longitude -> position on the map sheet, in page units."""
        rho = math.sqrt(self.a - self.b * q(math.radians(lat)))
        theta = self.n * (lon - self.lon0)
        return self.apex_x + rho * math.sin(theta), self.apex_y + rho * math.cos(theta)


def check_range(lat: float, lon: float) -> None:
    """Raise ``ValueError`` if a point falls off the drawn map."""
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        raise ValueError(
            f"Latitude {lat} is outside the map ({LAT_RANGE[0]} to {LAT_RANGE[1]})."
        )
    if not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
        raise ValueError(
            f"Longitude {lon} is outside the map ({LON_RANGE[0]} to {LON_RANGE[1]})."
        )
