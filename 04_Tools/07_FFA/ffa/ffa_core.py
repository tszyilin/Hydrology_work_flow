"""Pure-Python flood frequency analysis core.

Fits the four distributions commonly used in Australian hydrology
(Log-Pearson III, Generalised Extreme Value, Gumbel, Generalised Pareto)
to an annual-maximum series via L-moments or MLE, with non-parametric
bootstrap confidence intervals and a Gumbel-reduced-variate probability
plot.

The dialog layer imports from here; keep it UI-free so it can be driven
from the QGIS Python Console for headless validation.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Sequence

import numpy as np
from scipy import stats

# Vendored lmoments3 lives next to this file under ./vendor/
_VENDOR = os.path.join(os.path.dirname(__file__), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
from lmoments3 import distr as lm_distr  # noqa: E402


DEFAULT_ARIS = (2, 5, 10, 20, 50, 100, 200, 500, 1000)

# distribution key -> (scipy.stats dist, lmoments3 fitter, works-on-log)
_DIST_SPECS = {
    "LP3":    (stats.pearson3,   lm_distr.pe3, True),
    "GEV":    (stats.genextreme, lm_distr.gev, False),
    "Gumbel": (stats.gumbel_r,   lm_distr.gum, False),
    "GPD":    (stats.genpareto,  lm_distr.gpa, False),
}


# ── CSV loading ────────────────────────────────────────────────────────

def read_csv_headers(path):
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def load_series_csv(path, value_col, year_col=None, date_col=None):
    """Read a CSV into (keys, values).

    - ``value_col`` names the discharge/level column.
    - If ``year_col`` is set, treat the file as pre-computed AMS: keys = ints.
    - If ``date_col`` is set, parse dates (ISO ``YYYY-MM-DD`` or ``DD/MM/YYYY``)
      and return keys = ``datetime.date`` for continuous time-series mode.
    Rows with blank/non-numeric values are skipped.
    """
    if (year_col is None) == (date_col is None):
        raise ValueError("Specify exactly one of year_col or date_col")

    keys, vals = [], []
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if value_col not in reader.fieldnames:
            raise ValueError(f"Value column '{value_col}' not in CSV header")
        key_col = year_col or date_col
        if key_col not in reader.fieldnames:
            raise ValueError(f"Key column '{key_col}' not in CSV header")
        for row in reader:
            raw_v = (row.get(value_col) or "").strip()
            raw_k = (row.get(key_col) or "").strip()
            if not raw_v or not raw_k:
                continue
            try:
                v = float(raw_v)
            except ValueError:
                continue
            if year_col is not None:
                try:
                    k = int(float(raw_k))
                except ValueError:
                    continue
            else:
                k = _parse_date(raw_k)
                if k is None:
                    continue
            keys.append(k)
            vals.append(v)
    return keys, np.asarray(vals, dtype=float)


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def extract_ams(dates: Sequence[date], values: np.ndarray,
                water_year_start_month: int = 7):
    """Collapse a continuous series to one maximum per water year.

    Default water-year start = July (Australian convention). Returns
    ``(years, maxima)`` where ``years`` labels each water year by the
    *start-month* calendar year (so WY starting Jul 2010 → 2010).
    """
    if len(dates) != len(values):
        raise ValueError("dates and values must be the same length")
    if not 1 <= water_year_start_month <= 12:
        raise ValueError("water_year_start_month must be in [1, 12]")

    buckets: dict[int, float] = {}
    for d, v in zip(dates, values):
        if np.isnan(v):
            continue
        wy = d.year if d.month >= water_year_start_month else d.year - 1
        if wy not in buckets or v > buckets[wy]:
            buckets[wy] = float(v)

    years = sorted(buckets)
    return years, np.asarray([buckets[y] for y in years], dtype=float)


# ── Fitting ────────────────────────────────────────────────────────────

@dataclass
class FitResult:
    distribution: str          # "LP3" | "GEV" | "Gumbel" | "GPD"
    method: str                # "lmom" | "mle"
    params: tuple              # scipy-order params (shape(s), loc, scale)
    n: int
    on_log10: bool = False

    def ppf(self, p):
        """Non-exceedance quantile(s). Handles the log10 back-transform."""
        dist = _DIST_SPECS[self.distribution][0]
        q = dist.ppf(p, *self.params)
        if self.on_log10:
            q = np.power(10.0, q)
        return q


def fit(series: Iterable[float], distribution: str, method: str = "lmom") -> FitResult:
    if distribution not in _DIST_SPECS:
        raise ValueError(f"Unknown distribution: {distribution}")
    if method not in ("lmom", "mle"):
        raise ValueError(f"Unknown method: {method}")

    arr = np.asarray(list(series), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 5:
        raise ValueError("Need at least 5 data points to fit a distribution")

    dist, lm_dist, on_log = _DIST_SPECS[distribution]
    data = np.log10(arr) if on_log else arr
    if on_log and np.any(arr <= 0):
        raise ValueError("LP3 requires strictly positive values (log10 transform)")

    if method == "lmom":
        # lmoments3 returns a scipy "frozen distribution"; pull args/kwds out.
        frozen = lm_dist.lmom_fit(data)
        if isinstance(frozen, dict):
            params = _dict_to_scipy_params(distribution, frozen)
        else:
            params = tuple(frozen.values()) if hasattr(frozen, "values") else tuple(frozen)
    else:  # MLE
        params = dist.fit(data)

    return FitResult(distribution=distribution, method=method,
                     params=tuple(params), n=int(arr.size), on_log10=on_log)


def _dict_to_scipy_params(distribution, d):
    """lmoments3 ≥1.0 returns dicts keyed by the scipy parameter names."""
    if distribution == "LP3":
        return (d["skew"], d["loc"], d["scale"])
    if distribution == "GEV":
        return (d["c"], d["loc"], d["scale"])
    if distribution == "Gumbel":
        return (d["loc"], d["scale"])
    if distribution == "GPD":
        return (d["c"], d["loc"], d["scale"])
    raise KeyError(distribution)


# ── Return levels ──────────────────────────────────────────────────────

def return_levels(fit_result: FitResult, aris: Sequence[float] = DEFAULT_ARIS):
    """Map ARI (years) → quantile estimate."""
    aris = np.asarray(aris, dtype=float)
    p = 1.0 - 1.0 / aris
    q = fit_result.ppf(p)
    return {float(t): float(v) for t, v in zip(aris, np.atleast_1d(q))}


# ── Bootstrap CI ───────────────────────────────────────────────────────

def bootstrap_ci(series, distribution, method="lmom",
                 aris=DEFAULT_ARIS, n_boot=1000, alpha=0.05,
                 seed=None, progress_cb=None):
    """Non-parametric bootstrap CI on return levels.

    Returns ``{ARI: (lo, hi)}`` at the ``1-alpha`` confidence level.
    Resamples that fail to fit are silently dropped — the user sees how
    many were kept via ``progress_cb``.
    """
    arr = np.asarray(list(series), dtype=float)
    arr = arr[np.isfinite(arr)]
    rng = np.random.default_rng(seed)
    aris = tuple(aris)

    draws: list[list[float]] = [[] for _ in aris]
    kept = 0
    for i in range(int(n_boot)):
        sample = rng.choice(arr, size=arr.size, replace=True)
        try:
            fr = fit(sample, distribution, method=method)
            rl = return_levels(fr, aris)
        except Exception:
            continue
        for col, t in enumerate(aris):
            draws[col].append(rl[float(t)])
        kept += 1
        if progress_cb is not None and (i % 25 == 0 or i == n_boot - 1):
            progress_cb(i + 1, n_boot, kept)

    lo_q, hi_q = alpha / 2.0, 1.0 - alpha / 2.0
    out = {}
    for col, t in enumerate(aris):
        if draws[col]:
            lo, hi = np.quantile(draws[col], [lo_q, hi_q])
            out[float(t)] = (float(lo), float(hi))
        else:
            out[float(t)] = (float("nan"), float("nan"))
    return out


# ── Plotting ───────────────────────────────────────────────────────────

def plot_probability(series, fits_with_ci, aris=DEFAULT_ARIS,
                     title=None, out_png=None):
    """Gumbel-reduced-variate probability plot.

    ``fits_with_ci`` is a sequence of ``(FitResult, ci_dict_or_None)``.
    Returns the Matplotlib Figure so the dialog can embed it.
    """
    # Deferred import so the core is importable without a display backend.
    import matplotlib
    if out_png is not None and os.environ.get("MPLBACKEND", "") == "":
        matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    arr = np.sort(np.asarray(list(series), dtype=float))
    arr = arr[np.isfinite(arr)]
    n = arr.size
    # Weibull plotting positions (rank starting at 1, ascending)
    pp = np.arange(1, n + 1) / (n + 1.0)
    y_obs = -np.log(-np.log(pp))

    aris_arr = np.asarray(aris, dtype=float)
    p_grid = np.linspace(0.001, 0.999, 400)
    y_grid = -np.log(-np.log(p_grid))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(y_obs, arr, "ko", ms=4, label=f"Observed (n={n})")

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    for i, (fr, ci) in enumerate(fits_with_ci):
        colour = colors[i % len(colors)]
        q = fr.ppf(p_grid)
        label = f"{fr.distribution} ({fr.method.upper()})"
        ax.plot(y_grid, q, "-", color=colour, lw=1.6, label=label)
        if ci is not None:
            ari_sorted = sorted(ci)
            lo = np.array([ci[t][0] for t in ari_sorted])
            hi = np.array([ci[t][1] for t in ari_sorted])
            y_ci = -np.log(-np.log(1.0 - 1.0 / np.asarray(ari_sorted)))
            ax.fill_between(y_ci, lo, hi, color=colour, alpha=0.15)

    # Secondary x labelling in ARI years
    tick_aris = [a for a in (2, 5, 10, 20, 50, 100, 200, 500, 1000) if a <= max(aris_arr) * 2]
    tick_y = -np.log(-np.log(1.0 - 1.0 / np.asarray(tick_aris, dtype=float)))
    ax.set_xticks(tick_y)
    ax.set_xticklabels([str(a) for a in tick_aris])
    ax.set_xlabel("Return period (years)")
    ax.set_ylabel("Discharge")
    ax.set_yscale("log")
    ax.grid(True, which="both", ls=":", alpha=0.5)
    ax.legend(loc="best", fontsize=9)
    if title:
        ax.set_title(title)
    fig.tight_layout()

    if out_png:
        fig.savefig(out_png, dpi=150)
    return fig


# ── Convenience: full-pipeline table (used by headless validation) ─────

def results_table(series, distributions=("LP3",), method="lmom",
                  aris=DEFAULT_ARIS, n_boot=1000, alpha=0.05,
                  seed=None, progress_cb=None):
    """Return ``(headers, rows, fits_with_ci)`` ready for CSV export."""
    headers = ["ARI_years", "AEP"]
    for d in distributions:
        headers += [f"{d}_estimate", f"{d}_lo{int((1-alpha)*100)}", f"{d}_hi{int((1-alpha)*100)}"]

    fits_with_ci = []
    estimates = {}
    cis = {}
    for d in distributions:
        fr = fit(series, d, method=method)
        rl = return_levels(fr, aris)
        ci = bootstrap_ci(series, d, method=method, aris=aris,
                          n_boot=n_boot, alpha=alpha, seed=seed,
                          progress_cb=progress_cb)
        estimates[d] = rl
        cis[d] = ci
        fits_with_ci.append((fr, ci))

    rows = []
    for t in aris:
        row = [t, 1.0 / t]
        for d in distributions:
            lo, hi = cis[d][float(t)]
            row += [estimates[d][float(t)], lo, hi]
        rows.append(row)
    return headers, rows, fits_with_ci


def write_results_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for r in rows:
            w.writerow(r)
