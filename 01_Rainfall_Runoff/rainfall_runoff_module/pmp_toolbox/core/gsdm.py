"""GSDM section 6 Steps 2-9: the design spatial distribution of PMP.

Pure Python + numpy, no QGIS imports, so the calculation is testable outside
QGIS.  The reference implementation is Appendix 2.2 of the Bulletin, reproduced
in ``test/test_gsdm.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import ellipses
from .dda import MAX_AREA_KM2, MIN_AREA_KM2, DDACurves, Table2

#: Nominal enclosed area of each ellipse, by label.
ELLIPSE_AREA = dict(zip(ellipses.LABELS, ellipses.AREAS_KM2))

#: Areas are compared against the nominal ellipse areas with this relative
#: tolerance when deciding "does the catchment completely fill this ellipse?".
FILL_TOLERANCE = 1.0e-3

#: Warn about Step 8's conditioning once ``CEnc_i / CBtn_i`` exceeds this.  An
#: error of 1 mm in AMRD_i moves MRD_i by roughly that ratio times MAF * EAF;
#: ring E of the Bulletin's own worked example sits at 8.0.
THIN_RING_RATIO = 5.0

#: A ring holding less than this is treated as empty.  Polygon intersection
#: leaves slivers of a few square metres along a shared boundary, and without a
#: floor they would nominate an outermost ellipse the catchment never reaches.
EMPTY_RING_KM2 = 1.0e-4  # 100 m2


@dataclass
class Inputs:
    """Everything the Bulletin needs besides the geometry."""

    duration_hr: float
    smooth: float = 1.0  # fraction of catchment in 'smooth' terrain
    rough: float = 0.0  # fraction in 'rough' terrain; smooth + rough == 1
    maf: float = 1.0  # moisture adjustment factor, GSDM Figure 3
    eaf: float = 1.0  # elevation adjustment factor, GSDM section 4.3

    #: Round IMRD and AMRD to whole millimetres before the volume steps, as the
    #: Bulletin's worked example does.  This is not cosmetic: Step 8 divides a
    #: difference of enclosed volumes by a thin ring area, so it amplifies any
    #: drift in AMRD by roughly ``CEnc_i / CBtn_i`` -- a factor of 8 for the
    #: outermost ring of Appendix 2.2.  Rounding as published keeps results
    #: reproducible against the Bulletin; turn it off for a smoother surface.
    round_intermediates: bool = True

    def __post_init__(self):
        total = self.smooth + self.rough
        if not math.isclose(total, 1.0, abs_tol=1.0e-6):
            raise ValueError(f"smooth + rough must equal 1.0, got {total}")


@dataclass
class RingResult:
    """One row of Bulletin Table A2.2, columns a-h."""

    label: str
    ellipse_area_km2: float
    cbtn: float = 0.0  # b, step 2: catchment area between ellipses (km2)
    cenc: float = 0.0  # c, step 3: catchment area enclosed (km2)
    imrd: float | None = None  # d, step 4: initial mean rainfall depth (mm)
    amrd: float | None = None  # e, step 5: adjusted for moisture and elevation
    venc: float | None = None  # f, step 6: enclosed volume (mm.km2)
    vbtn: float | None = None  # g, step 7: volume between ellipses
    mrd: float | None = None  # h, step 8: the depth mapped onto this ring
    source: str = ""  # "table2" | "dda" -- which lookup produced imrd


@dataclass
class Result:
    rings: list[RingResult]
    outermost: str
    catchment_area_km2: float
    inputs: Inputs
    warnings: list[str] = field(default_factory=list)

    @property
    def closure_error_km2(self) -> float:
        """Step 3's check: CEnc of the outermost ellipse vs the catchment area."""
        return self.rings[-1].cenc - self.catchment_area_km2

    @property
    def pmp_mm(self) -> float | None:
        """Unrounded PMP over the whole catchment (== AMRD of the outermost)."""
        return self.rings[-1].amrd


def elevation_adjustment_factor(mean_elevation_m: float) -> float:
    """GSDM section 4.3: 1.0 up to 1500 m, then -0.05 per 300 m, floor 0.85."""
    if mean_elevation_m <= 1500.0:
        return 1.0
    return max(0.85, 1.0 - 0.05 * (mean_elevation_m - 1500.0) / 300.0)


def round_pmp(value_mm: float) -> int:
    """GSDM section 4: PMP is quoted to the nearest 10 mm."""
    return int(round(value_mm / 10.0) * 10)


def _initial_depth(
    label: str,
    cenc: float,
    inputs: Inputs,
    dda: DDACurves,
    table2: Table2,
    warnings: list[str],
) -> tuple[float, str]:
    """Step 4.  Table 2 when the catchment fills the ellipse, else DDA curves."""
    fills = math.isclose(cenc, ELLIPSE_AREA[label], rel_tol=FILL_TOLERANCE)

    if fills and table2.has(label):
        return (
            table2.weighted_depth(label, inputs.duration_hr, inputs.smooth, inputs.rough),
            "table2",
        )

    if cenc > MAX_AREA_KM2:
        warnings.append(
            f"Ellipse {label}: enclosed area {cenc:.1f} km2 exceeds the "
            f"{MAX_AREA_KM2:.0f} km2 areal limit of the DDA curves; depth clamped."
        )
    elif 0.0 < cenc < MIN_AREA_KM2:
        warnings.append(
            f"Ellipse {label}: enclosed area {cenc:.2f} km2 is below the "
            f"{MIN_AREA_KM2:.0f} km2 lower limit of the DDA curves; depth clamped."
        )
    return (
        dda.weighted_depth(inputs.duration_hr, cenc, inputs.smooth, inputs.rough),
        "dda",
    )


def distribute(
    ring_areas_km2: dict[str, float] | list[float],
    inputs: Inputs,
    dda: DDACurves | None = None,
    table2: Table2 | None = None,
) -> Result:
    """Run Steps 2-8 over the catchment areas between successive ellipses.

    ``ring_areas_km2`` is ``CBtn`` per ellipse -- either a ``{label: area}``
    mapping or a list in A..J order.  Ellipses beyond the outermost non-empty
    one are dropped; that outermost ellipse is the one Step 1 selected.
    """
    dda = dda or DDACurves()
    table2 = table2 or Table2()

    if not isinstance(ring_areas_km2, dict):
        ring_areas_km2 = dict(zip(ellipses.LABELS, ring_areas_km2))

    warnings: list[str] = []

    # Step 1's outcome: the smallest ellipse that still has catchment in or
    # inside it is the outermost of the distribution.
    non_empty = [
        l for l in ellipses.LABELS if ring_areas_km2.get(l, 0.0) > EMPTY_RING_KM2
    ]
    if not non_empty:
        raise ValueError("no catchment area falls inside the ellipse template")
    outermost = non_empty[-1]
    used = ellipses.LABELS[: ellipses.LABELS.index(outermost) + 1]

    if outermost not in ellipses.TABULATED_LABELS:
        warnings.append(
            f"Outermost ellipse is {outermost}, whose area exceeds the 1000 km2 "
            "limit of the GSDM. Results beyond ellipse H are extrapolated and "
            "outside the scope of the Bulletin."
        )

    rings: list[RingResult] = []
    cumulative = 0.0
    previous_venc = 0.0
    for label in used:
        ring = RingResult(label=label, ellipse_area_km2=ELLIPSE_AREA[label])
        ring.cbtn = ring_areas_km2.get(label, 0.0)  # step 2
        cumulative += ring.cbtn
        ring.cenc = cumulative  # step 3

        if ring.cenc > 0.0:
            ring.imrd, ring.source = _initial_depth(
                label, ring.cenc, inputs, dda, table2, warnings
            )
            if inputs.round_intermediates:
                ring.imrd = round(ring.imrd)
            ring.amrd = ring.imrd * inputs.maf * inputs.eaf  # step 5
            if inputs.round_intermediates:
                ring.amrd = round(ring.amrd)
            ring.venc = ring.amrd * ring.cenc  # step 6
            ring.vbtn = ring.venc - previous_venc  # step 7
            if ring.cbtn > 0.0:
                ring.mrd = ring.vbtn / ring.cbtn  # step 8
            previous_venc = ring.venc

        rings.append(ring)

    catchment_area = cumulative
    result = Result(
        rings=rings,
        outermost=outermost,
        catchment_area_km2=catchment_area,
        inputs=inputs,
        warnings=warnings,
    )

    # Step 8 is ill-conditioned for thin rings: it divides a difference of
    # enclosed volumes by CBtn, magnifying any depth error by CEnc / CBtn.
    for ring in rings:
        if ring.cbtn > EMPTY_RING_KM2 and ring.cenc / ring.cbtn > THIN_RING_RATIO:
            result.warnings.append(
                f"Ellipse {ring.label}: the catchment barely reaches this ring "
                f"({ring.cbtn:.2f} of {ring.cenc:.1f} km2 enclosed), so its mean "
                "rainfall depth is sensitive to rounding."
            )

    # The Bulletin's own sanity check on the step function.
    depths = [r.mrd for r in rings if r.mrd is not None]
    if any(b > a + 1.0e-6 for a, b in zip(depths, depths[1:])):
        result.warnings.append(
            "Mean rainfall depth is not monotonically decreasing outward; "
            "check the ring areas."
        )
    return result


def weight_profile(
    inputs: Inputs, dda: DDACurves | None = None, table2: Table2 | None = None
) -> dict[str, float]:
    """The static ring weights the placement optimiser maximises against.

    These are the Step 8 mean rainfall depths under the *full-fill* assumption
    (``CEnc_i == Area_i``), computed once per run and then held fixed.

    Freezing them is load-bearing.  If MRD were recomputed for each candidate
    placement the objective would collapse: volumes telescope, so
    ``sum(VBtn_i) == VEnc_k == AMRD_k * catchment_area``, which is identical for
    every placement sharing the same outermost ellipse ``k``.  A static profile
    keeps "area in the inner ellipses is worth more millimetres" as a real
    gradient for the search to climb, while the true per-placement GSDM depths
    are recomputed exactly by ``distribute`` once the optimum is found.
    """
    dda = dda or DDACurves()
    table2 = table2 or Table2()
    full_fill = {
        label: area - (ellipses.AREAS_KM2[i - 1] if i else 0.0)
        for i, (label, area) in enumerate(zip(ellipses.LABELS, ellipses.AREAS_KM2))
    }
    result = distribute(full_fill, inputs, dda, table2)

    # Beyond ellipse H the Bulletin has no depths and the DDA lookup clamps at
    # its 1000 km2 limit, so the ring depth stops falling and can even tick back
    # up (H 248, I 253, J 281 mm at 3 hr).  Left alone that would reward the
    # optimiser for pushing catchment area *outward*, inverting the whole point
    # of the weighting.  A running minimum floors the tail at H instead.
    profile: dict[str, float] = {}
    floor = math.inf
    for ring in result.rings:
        weight = ring.mrd if ring.mrd is not None else 0.0
        floor = min(floor, weight)
        profile[ring.label] = floor
    return profile
