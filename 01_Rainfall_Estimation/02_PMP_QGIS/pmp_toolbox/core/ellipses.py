"""The GSDM Figure 6 spatial distribution template, generated parametrically.

The supplied reference shapefile (``GSDM/Shapefiles/ellipses_all_*_28350.shp``)
is *not* concentric: successive centroids step 619.9 m along bearing 353.14
degrees, so A and J are 5.6 km apart.  It is also in EPSG:28350 while catchment
data is typically in another MGA zone.  Since all ten ellipses share a constant
axis ratio and are fully determined by their enclosed area, we regenerate them
about a common centre in the catchment's own CRS and keep the shapefile only as
a QA fixture (see ``test/test_ellipses.py``).
"""

from __future__ import annotations

import math

import numpy as np

#: Semi-major / semi-minor, measured as a constant 1.2217 across all ten
#: ellipses of the reference shapefile.
AXIS_RATIO = 1.2217

#: Enclosed area of each ellipse in km2.  A-H are the values tabulated in GSDM
#: Table 2; I and J are from the reference shapefile (the Bulletin omits them
#: because they exceed the 1000 km2 areal limit of the DDA curves).
LABELS = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")
AREAS_KM2 = (2.6, 16.0, 65.0, 153.0, 280.0, 433.0, 635.0, 847.0, 1117.0, 1398.0)

#: Ellipses I and J have no Table 2 depths.
TABULATED_LABELS = LABELS[:8]


def semi_axes(area_km2: float) -> tuple[float, float]:
    """Semi-major and semi-minor axes in metres for an enclosed area in km2."""
    area_m2 = area_km2 * 1.0e6
    b = math.sqrt(area_m2 / (math.pi * AXIS_RATIO))
    return AXIS_RATIO * b, b


#: Semi-minor axis of each ellipse, ascending.  Because every ellipse shares a
#: centre, an orientation and ``AXIS_RATIO``, a single normalised radius per
#: point classifies it into a ring by searching this array -- which is what
#: makes the optimiser's scoring loop O(N) rather than O(N * 10) geometry ops.
SEMI_MINOR_M = np.array([semi_axes(a)[1] for a in AREAS_KM2])
SEMI_MAJOR_M = SEMI_MINOR_M * AXIS_RATIO


def ring_index(
    points: np.ndarray, cx: float, cy: float, theta: float
) -> np.ndarray:
    """Ring index 0..9 for each point; 10 means outside the outermost ellipse.

    ``theta`` is the template rotation in radians, measured anticlockwise from
    the +x axis to the major axis.
    """
    dx = points[:, 0] - cx
    dy = points[:, 1] - cy
    c, s = math.cos(-theta), math.sin(-theta)
    # Rotate into the template frame, then squash the major axis so the nested
    # ellipses become nested circles of radius SEMI_MINOR_M.
    xr = (c * dx - s * dy) / AXIS_RATIO
    yr = s * dx + c * dy
    rho = np.hypot(xr, yr)
    return np.searchsorted(SEMI_MINOR_M, rho)


def polygon(
    cx: float, cy: float, theta: float, area_km2: float, segments: int = 180
) -> np.ndarray:
    """Closed (segments+1, 2) vertex ring for one ellipse."""
    a, b = semi_axes(area_km2)
    t = np.linspace(0.0, 2.0 * math.pi, segments + 1)
    x, y = a * np.cos(t), b * np.sin(t)
    c, s = math.cos(theta), math.sin(theta)
    return np.column_stack((cx + c * x - s * y, cy + s * x + c * y))


def template(cx: float, cy: float, theta: float, segments: int = 180):
    """Yield ``(label, area_km2, vertices)`` for A through J."""
    for label, area in zip(LABELS, AREAS_KM2):
        yield label, area, polygon(cx, cy, theta, area, segments)
