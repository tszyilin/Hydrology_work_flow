"""The generated template must match the digitised Figure 6 shapefile.

``GSDM/Shapefiles/ellipses_all_A_B_C_D_E_F_G_H_I_J_28350.shp`` is the reference
digitisation.  We do not use its geometry -- its ellipses are not concentric --
but its areas are the ground truth for what we generate.
"""

import math
import struct
from pathlib import Path

import numpy as np
import pytest

from pmp_toolbox.core import ellipses

SHAPEFILE = (
    Path(__file__).resolve().parents[2]
    / "GSDM"
    / "Shapefiles"
    / "ellipses_all_A_B_C_D_E_F_G_H_I_J_28350"
)


def _read_dbf_areas(path: Path) -> list[tuple[str, float]]:
    """Minimal DBF reader for the reference shapefile's Name / Area columns.

    Returns records in file order -- which is *not* A..J -- so callers can pair
    them with the geometry records.
    """
    data = path.read_bytes()
    n_records, header_len, record_len = struct.unpack("<I2H", data[4:12])
    fields = []
    offset = 32
    while data[offset] != 0x0D:
        raw = data[offset : offset + 32]
        name = raw[:11].split(b"\x00")[0].decode("ascii")
        fields.append((name, raw[16]))
        offset += 32
    areas = []
    for i in range(n_records):
        rec = data[header_len + i * record_len : header_len + (i + 1) * record_len]
        pos = 1  # skip the deletion flag
        row = {}
        for name, size in fields:
            row[name] = rec[pos : pos + size].decode("ascii", "replace").strip()
            pos += size
        label = row["Name"].replace("Ellipse", "").strip().upper()
        areas.append((label, float(row["Area (km2)"])))
    return areas


def _read_shp_rings(path: Path) -> list[np.ndarray]:
    """Minimal ESRI shapefile reader for single-ring polygons."""
    data = path.read_bytes()
    rings = []
    offset = 100
    while offset < len(data):
        _num, content_len = struct.unpack(">2i", data[offset : offset + 8])
        body = offset + 8
        shape_type = struct.unpack("<i", data[body : body + 4])[0]
        assert shape_type == 5, f"expected polygon, got {shape_type}"
        n_parts, n_points = struct.unpack("<2i", data[body + 36 : body + 44])
        assert n_parts == 1
        pts_at = body + 44 + 4 * n_parts
        pts = np.frombuffer(data, dtype="<f8", count=2 * n_points, offset=pts_at)
        rings.append(pts.reshape(n_points, 2))
        offset = body + content_len * 2
    return rings


def _shoelace(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return abs(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2.0


@pytest.fixture(scope="module")
def reference():
    """``{label: (stated_area_km2, vertex ring)}`` from the digitised template."""
    if not SHAPEFILE.with_suffix(".dbf").exists():
        pytest.skip(f"reference shapefile not found at {SHAPEFILE}")
    records = _read_dbf_areas(SHAPEFILE.with_suffix(".dbf"))
    rings = _read_shp_rings(SHAPEFILE.with_suffix(".shp"))
    assert len(records) == len(rings) == len(ellipses.LABELS)
    return {label: (area, ring) for (label, area), ring in zip(records, rings)}


class TestAgainstReferenceShapefile:
    def test_every_label_is_present(self, reference):
        assert sorted(reference) == sorted(ellipses.LABELS)

    def test_areas_match(self, reference):
        for label, area in zip(ellipses.LABELS, ellipses.AREAS_KM2):
            assert reference[label][0] == pytest.approx(area, rel=1.0e-3)

    def test_axis_ratio_is_constant(self, reference):
        """Every digitised ellipse has the same 1.2217 semi-major/semi-minor."""
        for _, ring in reference.values():
            centre = ring[:-1].mean(axis=0)
            d = np.hypot(*(ring[:-1] - centre).T)
            assert d.max() / d.min() == pytest.approx(ellipses.AXIS_RATIO, rel=2.0e-3)

    def test_reference_ellipses_are_not_concentric(self, reference):
        """Documents why we regenerate rather than reproject the shapefile.

        Successive centres step ~600 m along the major axis, so A and J are
        ~5 km apart -- the shapefile cannot serve as a nested template as-is.
        """
        centres = np.array(
            [reference[l][1][:-1].mean(axis=0) for l in ellipses.LABELS]
        )
        steps = np.hypot(*np.diff(centres, axis=0).T)
        assert steps.min() > 500.0
        assert np.hypot(*(centres[-1] - centres[0])) > 4500.0

    def test_generated_polygon_area_matches_the_digitised_one(self, reference):
        for label, area_km2 in zip(ellipses.LABELS, ellipses.AREAS_KM2):
            generated = ellipses.polygon(0.0, 0.0, 0.0, area_km2, segments=360)
            assert _shoelace(generated) == pytest.approx(
                _shoelace(reference[label][1]), rel=2.0e-3
            )


class TestSemiAxes:
    def test_area_round_trips(self):
        for area in ellipses.AREAS_KM2:
            a, b = ellipses.semi_axes(area)
            assert math.pi * a * b / 1.0e6 == pytest.approx(area)

    def test_ratio_holds(self):
        for area in ellipses.AREAS_KM2:
            a, b = ellipses.semi_axes(area)
            assert a / b == pytest.approx(ellipses.AXIS_RATIO)

    def test_semi_minor_is_ascending(self):
        assert list(ellipses.SEMI_MINOR_M) == sorted(ellipses.SEMI_MINOR_M)


class TestPolygon:
    def test_is_closed(self):
        ring = ellipses.polygon(100.0, 200.0, 0.4, 65.0)
        assert ring[0] == pytest.approx(ring[-1])

    def test_segmented_area_converges_from_below(self):
        """An inscribed polygon under-reads; 180 segments is within 0.02%."""
        exact = 65.0
        coarse = _shoelace(ellipses.polygon(0, 0, 0, exact, segments=12)) / 1e6
        fine = _shoelace(ellipses.polygon(0, 0, 0, exact, segments=180)) / 1e6
        assert coarse < fine < exact
        assert fine == pytest.approx(exact, rel=3.0e-4)

    def test_rotation_preserves_area(self):
        base = _shoelace(ellipses.polygon(0, 0, 0.0, 153.0))
        for theta in (0.3, 1.1, 2.7):
            assert _shoelace(ellipses.polygon(5.0, -7.0, theta, 153.0)) == pytest.approx(base)

    def test_rotation_orients_the_major_axis(self):
        theta = math.radians(30.0)
        ring = ellipses.polygon(0.0, 0.0, theta, 280.0)
        furthest = ring[np.argmax(np.hypot(ring[:, 0], ring[:, 1]))]
        assert math.atan2(furthest[1], furthest[0]) % math.pi == pytest.approx(
            theta, abs=0.02
        )


class TestRingIndex:
    def test_centre_is_in_the_innermost_ring(self):
        pts = np.array([[10.0, 20.0]])
        assert ellipses.ring_index(pts, 10.0, 20.0, 0.0)[0] == 0

    def test_far_point_is_outside(self):
        pts = np.array([[1.0e6, 0.0]])
        assert ellipses.ring_index(pts, 0.0, 0.0, 0.0)[0] == len(ellipses.LABELS)

    def test_boundaries_land_in_the_expected_ring(self):
        """A point just inside ellipse i's minor-axis end belongs to ring i."""
        for i, b in enumerate(ellipses.SEMI_MINOR_M):
            inside = np.array([[0.0, b * 0.999]])
            outside = np.array([[0.0, b * 1.001]])
            assert ellipses.ring_index(inside, 0.0, 0.0, 0.0)[0] == i
            assert ellipses.ring_index(outside, 0.0, 0.0, 0.0)[0] == i + 1

    def test_major_axis_reaches_further_than_minor(self):
        a, b = ellipses.semi_axes(ellipses.AREAS_KM2[0])
        along_major = np.array([[a * 0.999, 0.0]])
        assert ellipses.ring_index(along_major, 0.0, 0.0, 0.0)[0] == 0

    def test_rotation_carries_the_major_axis_round(self):
        a, _ = ellipses.semi_axes(ellipses.AREAS_KM2[0])
        pt = np.array([[0.0, a * 0.999]])
        # Unrotated, a point that far up the minor axis is outside ellipse A.
        assert ellipses.ring_index(pt, 0.0, 0.0, 0.0)[0] > 0
        # Rotate the template a quarter turn and the major axis now covers it.
        assert ellipses.ring_index(pt, 0.0, 0.0, math.pi / 2)[0] == 0

    def test_counts_reproduce_the_nominal_areas(self):
        """Rasterising the plane and counting rings recovers AREAS_KM2.

        This is the identity the optimiser's scoring relies on.  Cell counting
        errs by roughly one cell per boundary cell, so the tolerance is the
        ellipse perimeter times the cell size rather than a flat percentage --
        ellipse A is only 2.6 km2 and is genuinely coarse at this resolution.
        """
        step = 200.0
        grid = np.arange(-30000.0, 30000.0, step)
        gx, gy = np.meshgrid(grid, grid)
        pts = np.column_stack((gx.ravel(), gy.ravel()))
        idx = ellipses.ring_index(pts, 0.0, 0.0, 0.7)
        counts = np.bincount(idx, minlength=len(ellipses.LABELS) + 1)
        cumulative = np.cumsum(counts[: len(ellipses.LABELS)]) * step**2 / 1.0e6
        for got, expected in zip(cumulative, ellipses.AREAS_KM2):
            a, b = ellipses.semi_axes(expected)
            perimeter = math.pi * (a + b)  # Ramanujan is overkill at this ratio
            tolerance = perimeter * step / 1.0e6
            assert got == pytest.approx(expected, abs=tolerance)
