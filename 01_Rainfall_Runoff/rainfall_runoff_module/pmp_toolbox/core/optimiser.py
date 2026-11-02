"""Automates GSDM section 6 Step 1 -- positioning the Figure 6 template.

The Bulletin has an analyst overlay Figure 6 on the catchment map and shuffle it
by hand "to obtain the best fit by the smallest possible ellipse".  That is
restated here as a three-parameter optimisation over the template centre
``(cx, cy)`` and rotation ``theta``, with a lexicographic objective:

1. minimise ``k``, the index of the smallest ellipse fully containing the
   catchment (the Bulletin's own criterion, and a hard constraint);
2. among placements achieving that ``k``, maximise ``sum(w_i * CBtn_i)``, which
   pulls catchment area into the inner, wetter rings.

Scoring rasterises the catchment once into cell-centre points, then classifies
every point analytically -- no per-candidate geometry operations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import ellipses

#: Dominates any achievable score, so ``k`` sorts ahead of it lexicographically.
_K_PENALTY = 1.0e12

#: Ring index returned for points outside the outermost ellipse.
OUTSIDE = len(ellipses.LABELS)


class SearchCancelled(RuntimeError):
    """Raised by an observer to abandon the search; propagates out of ``optimise``."""


@dataclass(frozen=True)
class Trial:
    """One candidate placement, as seen by an observer.

    Emitted only when an observer is attached, so the search costs nothing extra
    when nobody is watching.
    """

    index: int  # 1-based, counted across the whole run
    total: int  # size of the coarse sweep; refinement trials run past it
    phase: str  # "coarse" | "refine"
    cx: float
    cy: float
    theta: float
    k: int
    score: float
    is_best: bool  # improved on the best cost seen so far this run


@dataclass
class Placement:
    cx: float
    cy: float
    theta: float  # radians, anticlockwise from +x to the major axis
    k: int  # index into ellipses.LABELS of the enclosing ellipse
    score: float
    ring_areas_km2: dict[str, float]
    feasible: bool

    @property
    def label(self) -> str:
        return ellipses.LABELS[self.k] if self.feasible else "none"

    @property
    def bearing_deg(self) -> float:
        """Major-axis bearing in degrees clockwise from grid north."""
        return (90.0 - math.degrees(self.theta)) % 180.0


class CatchmentRaster:
    """Cell-centre points of a catchment, with each point's area weight."""

    def __init__(self, points: np.ndarray, cell_area_km2: float):
        self.points = np.ascontiguousarray(points, dtype=float)
        self.cell_area_km2 = float(cell_area_km2)

    @property
    def area_km2(self) -> float:
        return len(self.points) * self.cell_area_km2

    @property
    def centroid(self) -> tuple[float, float]:
        c = self.points.mean(axis=0)
        return float(c[0]), float(c[1])

    def max_radius(self, cx: float, cy: float) -> float:
        d = self.points - np.array([cx, cy])
        return float(np.hypot(d[:, 0], d[:, 1]).max())

    @classmethod
    def from_polygon(cls, contains, bounds, cell_m: float = 50.0):
        """Sample via a callable ``contains(xs, ys) -> bool array``.

        ``bounds`` is ``(xmin, ymin, xmax, ymax)`` in the same projected CRS;
        ``cell_m`` is the spacing between sample points, in metres.
        """
        xmin, ymin, xmax, ymax = bounds
        if cell_m <= 0:
            raise ValueError("sampling distance must be greater than zero")
        cell = float(cell_m)
        xs = np.arange(xmin + cell / 2.0, xmax, cell)
        ys = np.arange(ymin + cell / 2.0, ymax, cell)
        gx, gy = np.meshgrid(xs, ys)
        gx, gy = gx.ravel(), gy.ravel()
        inside = contains(gx, gy)
        pts = np.column_stack((gx[inside], gy[inside]))
        if len(pts) == 0:
            raise ValueError("sampling the catchment produced no points")
        return cls(pts, (cell * cell) / 1.0e6)


def score_placement(
    raster: CatchmentRaster, weights: np.ndarray, cx: float, cy: float, theta: float
) -> tuple[int, float, np.ndarray]:
    """Return ``(k, score, ring_areas_km2)`` for one candidate placement."""
    idx = ellipses.ring_index(raster.points, cx, cy, theta)
    counts = np.bincount(idx, minlength=OUTSIDE + 1)
    ring_areas = counts[:OUTSIDE] * raster.cell_area_km2
    k = int(idx.max())
    score = float(np.dot(weights, ring_areas))
    return k, score, ring_areas


def _cost(k: int, score: float) -> float:
    """Lexicographic objective flattened to a single number to minimise."""
    return k * _K_PENALTY - score


def optimise(
    raster: CatchmentRaster,
    weights,
    thetas_deg: int = 12,
    coarse_seeds: int = 5,
    refine_iterations: int = 60,
    progress=None,
    observer=None,
) -> tuple[Placement, Placement]:
    """Search for the best template placement.

    Returns ``(coarse_best, refined_best)`` so the value added by refinement is
    visible to the user.  ``weights`` is the static ring profile from
    :func:`gsdm.weight_profile`, as a dict or an A..J-ordered sequence.

    ``observer``, if given, is called with a :class:`Trial` for every candidate
    of the coarse sweep and for every accepted refinement move.  It may raise
    :class:`SearchCancelled` to abandon the search.  Rejected refinement probes
    are not reported: they are noise, and the accepted moves are what shows the
    template settling into place.
    """
    if isinstance(weights, dict):
        weights = [weights.get(l, 0.0) for l in ellipses.LABELS]
    w = np.asarray(weights, dtype=float)
    if w.shape != (len(ellipses.LABELS),):
        raise ValueError(f"expected {len(ellipses.LABELS)} weights, got {w.shape}")

    cx0, cy0 = raster.centroid

    # The template centre can never usefully sit further from the catchment
    # centroid than the outermost semi-minor axis, and the search only needs to
    # resolve features at the scale of the innermost ellipse.
    reach = max(ellipses.SEMI_MINOR_M[-1] - raster.max_radius(cx0, cy0), 0.0)
    reach = max(reach, ellipses.SEMI_MINOR_M[0])
    step = max(ellipses.SEMI_MINOR_M[0] / 2.0, reach / 12.0)
    offsets = np.arange(-reach, reach + step / 2.0, step)
    # A rotation by pi maps the template onto itself, so half a turn suffices.
    angles = np.linspace(0.0, math.pi, thetas_deg, endpoint=False)

    candidates: list[tuple[float, float, float, float, int, np.ndarray]] = []
    total = len(angles) * len(offsets) ** 2
    done = 0

    # Closed over so the trial counter and the running best stay continuous
    # across the coarse sweep and the refinement that follows it.
    state = {"index": 0, "best": math.inf}

    def emit(phase, cx, cy, theta, k, score, cost):
        state["index"] += 1
        improved = cost < state["best"]
        if improved:
            state["best"] = cost
        observer(
            Trial(state["index"], total, phase, cx, cy, theta, k, score, improved)
        )

    for theta in angles:
        for dx in offsets:
            for dy in offsets:
                cx, cy = cx0 + dx, cy0 + dy
                k, score, areas = score_placement(raster, w, cx, cy, theta)
                cost = _cost(k, score)
                candidates.append((cost, cx, cy, theta, k, areas))
                done += 1
                if observer is not None:
                    emit("coarse", cx, cy, theta, k, score, cost)
        if progress:
            progress(done / total)

    candidates.sort(key=lambda c: c[0])
    coarse = _to_placement(candidates[0], w, raster)

    # Local refinement by pattern search from the best few coarse seeds; the
    # ellipse geometry makes the surface multi-modal, so multi-start matters.
    best = candidates[0]
    seen: set[tuple[int, int, int]] = set()
    seeds = []
    for cand in candidates:
        key = (int(cand[1] / step), int(cand[2] / step), int(cand[3] * 100))
        if key in seen:
            continue
        seen.add(key)
        seeds.append(cand)
        if len(seeds) >= coarse_seeds:
            break

    for seed in seeds:
        result = _pattern_search(
            raster, w, seed, step, refine_iterations, emit if observer else None
        )
        if result[0] < best[0]:
            best = result

    return coarse, _to_placement(best, w, raster)


def _pattern_search(raster, w, seed, step, iterations, emit=None):
    """Compass search on ``(cx, cy, theta)`` with a geometrically shrinking step."""
    cost, cx, cy, theta, k, areas = seed
    h = step
    dtheta = math.radians(10.0)
    for _ in range(iterations):
        improved = False
        for dx, dy, dt in (
            (h, 0, 0), (-h, 0, 0), (0, h, 0), (0, -h, 0),
            (0, 0, dtheta), (0, 0, -dtheta),
        ):
            nk, nscore, nareas = score_placement(
                raster, w, cx + dx, cy + dy, theta + dt
            )
            ncost = _cost(nk, nscore)
            if ncost < cost:
                cost, cx, cy, theta = ncost, cx + dx, cy + dy, theta + dt
                k, areas = nk, nareas
                improved = True
                if emit is not None:
                    emit("refine", cx, cy, theta, k, nscore, cost)
                break
        if not improved:
            h /= 2.0
            dtheta /= 2.0
            if h < 1.0:  # sub-metre: finer than the rasterisation warrants
                break
    return cost, cx, cy, theta % math.pi, k, areas


def _to_placement(cand, w, raster) -> Placement:
    _cost_value, cx, cy, theta, k, areas = cand
    feasible = k < OUTSIDE
    return Placement(
        cx=cx,
        cy=cy,
        theta=theta % math.pi,
        k=min(k, OUTSIDE - 1),
        score=float(np.dot(w, areas)),
        ring_areas_km2=dict(zip(ellipses.LABELS, areas.tolist())),
        feasible=feasible,
    )
