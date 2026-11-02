"""Whole-pipeline runs against the three example catchments.

Requires the QGIS Python environment; skipped otherwise.  Run with:

    "C:\\Program Files\\QGIS 3.44.11\\bin\\python-qgis-ltr.bat" -m pytest \\
        pmp_toolbox/test/test_end_to_end.py
"""

from pathlib import Path

import numpy as np
import pytest

qgis_core = pytest.importorskip("qgis.core", reason="needs the QGIS Python environment")

from pmp_toolbox.core import ellipses  # noqa: E402
from pmp_toolbox.core.gsdm import Inputs, weight_profile  # noqa: E402
from pmp_toolbox.core.optimiser import score_placement  # noqa: E402

CATCHMENTS = Path(__file__).resolve().parents[2] / "01_example catchments"

# The `area` attribute each shapefile carries, and the number of polygon parts.
EXPECTED = {
    "A": (91.699, 1),
    "B": (54.954, 1),
    "C": (52.102, 4),
}

INPUTS = Inputs(duration_hr=3.0, smooth=1.0, rough=0.0, maf=0.70, eaf=1.0)


@pytest.fixture(params=sorted(EXPECTED), scope="module")
def catchment(request):
    from qgis.core import QgsVectorLayer

    path = CATCHMENTS / f"catchment_{request.param}_area.shp"
    if not path.exists():
        pytest.skip(f"example catchment not found: {path}")
    layer = QgsVectorLayer(str(path), request.param, "ogr")
    assert layer.isValid(), path
    return request.param, layer


@pytest.fixture(scope="module")
def run_result(qgis_app, catchment):
    from pmp_toolbox import qgis_bridge

    name, layer = catchment
    return name, layer, qgis_bridge.run(layer, INPUTS, cell_m=53.0)


def test_layer_area_matches_its_attribute(run_result):
    """Guards the dissolve: catchment C is 4 parts and must not lose any."""
    name, _layer, (result, *_rest) = run_result
    expected, _parts = EXPECTED[name]
    assert result.catchment_area_km2 == pytest.approx(expected, rel=2.0e-3)


def test_closure_check_passes(run_result):
    """GSDM Step 3: CEnc of the outermost ellipse equals the catchment area."""
    _name, _layer, (result, *_rest) = run_result
    assert result.closure_error_km2 == pytest.approx(0.0, abs=1.0e-6)


def test_catchment_is_contained(run_result):
    _name, _layer, (result, placement, *_rest) = run_result
    assert placement.feasible
    assert result.outermost == placement.label


def test_outermost_ellipse_is_large_enough(run_result):
    _name, _layer, (result, *_rest) = run_result
    area = dict(zip(ellipses.LABELS, ellipses.AREAS_KM2))[result.outermost]
    assert area >= result.catchment_area_km2


def test_no_empty_outermost_ring(run_result):
    """Intersection slivers must not nominate a ring the catchment never reaches."""
    _name, _layer, (result, *_rest) = run_result
    assert result.rings[-1].cbtn > 0.01


def test_depths_decrease_outward(run_result):
    _name, _layer, (result, *_rest) = run_result
    depths = [r.mrd for r in result.rings if r.mrd is not None]
    assert depths == sorted(depths, reverse=True)
    assert not any("not monotonically" in w for w in result.warnings)


def test_inner_ellipse_is_fully_covered(run_result):
    """All three catchments dwarf ellipse A, so Step 4 should use Table 2."""
    _name, _layer, (result, *_rest) = run_result
    assert result.rings[0].cbtn == pytest.approx(ellipses.AREAS_KM2[0], rel=1e-3)
    assert result.rings[0].source == "table2"


def test_refinement_does_not_regress(run_result):
    _name, _layer, (_result, placement, coarse, *_rest) = run_result
    assert (placement.k, -placement.score) <= (coarse.k, -coarse.score)


def test_optimum_beats_the_naive_centroid_placement(run_result):
    """The plugin's reason to exist, measured on real catchments."""
    _name, _layer, (_result, placement, _coarse, _clipped, _crs, raster) = run_result
    weights = np.array(
        [weight_profile(INPUTS).get(l, 0.0) for l in ellipses.LABELS]
    )
    cx, cy = raster.centroid
    naive_k, naive_score, _ = score_placement(raster, weights, cx, cy, 0.0)
    assert (placement.k, -placement.score) <= (naive_k, -naive_score)


def test_exact_areas_agree_with_the_raster(run_result):
    """The sample points only steer the search; polygon intersection sets the numbers."""
    _name, _layer, (result, placement, _coarse, _clipped, _crs, raster) = run_result
    assert result.catchment_area_km2 == pytest.approx(raster.area_km2, rel=5.0e-3)


def test_output_layers_are_built(run_result):
    from pmp_toolbox import qgis_bridge

    _name, _layer, (result, placement, _coarse, clipped, crs, _raster) = run_result
    outlines, rings = qgis_bridge.build_output_layers(result, placement, clipped, crs)
    assert outlines.isValid() and rings.isValid()
    assert outlines.featureCount() == len(result.rings)
    assert rings.featureCount() >= len(result.rings) - 1
    assert outlines.crs().authid() == crs.authid()


def test_geographic_crs_is_refused(qgis_app):
    """GSDM areas are ground distances; degrees would silently corrupt them."""
    from qgis.core import QgsVectorLayer

    from pmp_toolbox import qgis_bridge

    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "wgs84", "memory")
    with pytest.raises(qgis_bridge.ProjectionError):
        qgis_bridge.catchment_geometry(layer)


class TestSamplingGuards:
    """The spacing is a distance now, so the workload is no longer self-limiting."""

    @pytest.fixture
    def catchment(self, qgis_app):
        from qgis.core import QgsVectorLayer

        from pmp_toolbox import qgis_bridge

        path = CATCHMENTS / "catchment_B_area.shp"
        if not path.exists():
            pytest.skip("example catchment not found")
        return qgis_bridge.catchment_geometry(QgsVectorLayer(str(path), "B", "ogr"))[0]

    def test_the_spacing_sets_the_cell_area(self, catchment):
        from pmp_toolbox import qgis_bridge

        raster = qgis_bridge.rasterise(catchment, 100.0)
        assert raster.cell_area_km2 == pytest.approx(0.01)  # 100 m x 100 m
        assert raster.area_km2 == pytest.approx(catchment.area() / 1.0e6, rel=0.02)

    def test_too_fine_a_spacing_is_refused_with_a_workable_one(self, catchment):
        """And refused *before* the grid is built -- 0.5 m here is ~440 million
        points, which would exhaust memory if it were allocated first."""
        from pmp_toolbox import qgis_bridge

        with pytest.raises(ValueError) as raised:
            qgis_bridge.rasterise(catchment, 0.5)

        box = catchment.boundingBox()
        workable = qgis_bridge.workable_spacing_m(box.width(), box.height())
        assert str(workable) in str(raised.value)
        # The distance it names must itself be accepted.
        assert qgis_bridge.rasterise(catchment, workable).points.size > 0

    def test_a_spacing_wider_than_the_catchment_says_so(self, qgis_app):
        from qgis.core import QgsGeometry

        from pmp_toolbox import qgis_bridge

        sliver = QgsGeometry.fromWkt("POLYGON((0 0, 400 0, 400 5, 0 5, 0 0))")
        with pytest.raises(ValueError, match="Reduce the sampling distance"):
            qgis_bridge.rasterise(sliver, 200.0)

    def test_a_zero_spacing_is_rejected(self, catchment):
        from pmp_toolbox import qgis_bridge

        with pytest.raises(ValueError):
            qgis_bridge.rasterise(catchment, 0.0)


@pytest.fixture(scope="module")
def two_spacings(qgis_app):
    from qgis.core import QgsVectorLayer

    from pmp_toolbox import qgis_bridge

    path = CATCHMENTS / "catchment_A_area.shp"
    if not path.exists():
        pytest.skip("example catchment not found")
    layer = QgsVectorLayer(str(path), "A", "ogr")
    return (
        qgis_bridge.run(layer, INPUTS, cell_m=105.0)[0],
        qgis_bridge.run(layer, INPUTS, cell_m=37.0)[0],
    )


class TestSamplingStability:
    """What the sampling distance may and may not change.

    The sample points only steer the search, so the quantities a user reports must not
    depend on it: the enclosing ellipse, the catchment area, the PMP.  Ring
    depths are a different matter -- two placements can score within a fraction
    of a percent of each other yet put visibly different depths on a thin outer
    ring, because Step 8 divides by that ring's small area.  These tests pin the
    invariants and bound the drift rather than pretending it is absent.
    """

    def test_outermost_ellipse_is_stable(self, two_spacings):
        coarse, fine = two_spacings
        assert coarse.outermost == fine.outermost

    def test_catchment_area_is_stable(self, two_spacings):
        """Areas come from polygon intersection, so they do not depend on the sampling."""
        coarse, fine = two_spacings
        assert coarse.catchment_area_km2 == pytest.approx(
            fine.catchment_area_km2, rel=1e-6
        )

    def test_pmp_is_stable(self, two_spacings):
        coarse, fine = two_spacings
        assert coarse.pmp_mm == pytest.approx(fine.pmp_mm, abs=5.0)

    def test_substantive_rings_are_stable(self, two_spacings):
        """Rings holding at least 5% of the catchment agree to a few mm."""
        coarse, fine = two_spacings
        total = fine.catchment_area_km2
        compared = 0
        for a, b in zip(coarse.rings, fine.rings):
            if min(a.cbtn, b.cbtn) / total < 0.05:
                continue
            assert a.mrd == pytest.approx(b.mrd, abs=10.0)
            compared += 1
        assert compared >= 3

    def test_thin_rings_are_flagged_not_trusted(self, two_spacings):
        """Any ring that does move between spacings is one we warn about."""
        coarse, fine = two_spacings
        for a, b in zip(coarse.rings, fine.rings):
            if a.mrd is None or b.mrd is None or abs(a.mrd - b.mrd) <= 10.0:
                continue
            assert any(
                f"Ellipse {a.label}" in w and "sensitive" in w for w in fine.warnings
            ), f"ring {a.label} moved {abs(a.mrd - b.mrd):.0f} mm without a warning"
