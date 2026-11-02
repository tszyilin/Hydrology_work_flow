"""Ranked multiday-rainfall (MDR) maxima on a partial-series basis.

Port of ../02_original_scripts/MDR_Build2012.m. For each duration D in the user's
list, extract the top N = ceil(Nyr * events_per_year * valid_frac) non-
overlapping D-day totals from the daily record; also grab the antecedent
30-day total and the temporal distribution at 20/40/60/80% of the window.

Missing days in the input are treated as zero (as MATLAB does for DPL inputs),
but the count of valid days is tracked to scale ARI via the plotting-position
formula:  ARI = (Nyr * valid_frac + 1) / rank
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MDRResult:
    """Ranked multiday maxima and their metadata.

    `table` columns: Duration, Rank, ARI, StartDate, EndDate, MDR_mm,
                     Ant_mm, Ant30_mm, R20, R40, R60, R80
    `stats` columns: Duration, Mean, SDev, Cv, Median, Skew, N
    """

    table: pd.DataFrame
    stats: pd.DataFrame
    n_events: int
    valid_frac: float
    n_years: int


def _interp(times: np.ndarray, values: np.ndarray, t: float) -> float:
    """Linear interp of the temporal cumulative-fraction curve at t in [0,1]."""
    return float(np.interp(t, times, values))


def build_mdr(
    rain: pd.Series,
    durations: list[int],
    events_per_year: float = 1.0,
    depth_adj: float = 1.0,
) -> MDRResult:
    if rain.empty:
        raise ValueError("Empty rainfall series")

    dates = rain.index
    valid_mask = rain.notna().to_numpy()
    valid_frac = float(valid_mask.mean())

    r = rain.fillna(0.0).to_numpy(dtype=float) * float(depth_adj)
    L = len(r)
    cs = np.concatenate([[0.0], np.cumsum(r)])  # cs[i] = sum of r[:i]

    start_year = dates[0].year
    end_year = dates[-1].year
    n_years = end_year - start_year + 1
    n_events = int(np.ceil(n_years * events_per_year * valid_frac))
    if n_events < 1:
        n_events = 1

    ari_denoms = np.arange(1, n_events + 1)
    ari_values = (n_years * valid_frac + 1.0) / ari_denoms

    rows: list[dict] = []
    stats_rows: list[dict] = []

    for D in durations:
        if D < 1 or D > L:
            continue

        # Working "removed" copy of daily rain — zero out the D-day window
        # around each picked peak so subsequent peaks cannot overlap.
        rr = r.copy()
        # Immutable cumulative sum used for antecedent windows and temporal
        # distribution — always references the original series.
        cs0 = cs

        picked_totals: list[float] = []
        picked_starts: list[int] = []  # 0-based day index of window start

        for rank in range(1, n_events + 1):
            # Rolling D-day sums of the (mutable) rr array.
            # window[k] covers days k..k+D-1 (0-indexed), for k = 0..L-D
            rr_cs = np.concatenate([[0.0], np.cumsum(rr)])
            window_sums = rr_cs[D:] - rr_cs[: L - D + 1]
            k = int(np.argmax(window_sums))
            total = float(window_sums[k])
            picked_totals.append(total)
            picked_starts.append(k)

            # Zero out the D days of the picked window so nothing overlapping
            # can be selected next round.
            rr[k : k + D] = 0.0

        for rank, (total, k) in enumerate(zip(picked_totals, picked_starts), start=1):
            start_date = dates[k]
            end_date = dates[k + D - 1]

            # Temporal distribution at 20/40/60/80% using the *original* daily
            # series inside the window.
            window_rain = r[k : k + D]
            window_cum = np.concatenate([[0.0], np.cumsum(window_rain)])
            times = np.linspace(0.0, 1.0, D + 1)
            r20 = _interp(times, window_cum, 0.2) / total if total > 0 else np.nan
            r40 = _interp(times, window_cum, 0.4) / total if total > 0 else np.nan
            r60 = _interp(times, window_cum, 0.6) / total if total > 0 else np.nan
            r80 = _interp(times, window_cum, 0.8) / total if total > 0 else np.nan

            # Antecedent D-day total (days immediately before window start)
            if k - D >= 0:
                ant = float(cs0[k] - cs0[k - D])
            else:
                ant = np.nan

            # Antecedent 30-day total
            if k - 30 >= 0:
                ant30 = float(cs0[k] - cs0[k - 30])
            else:
                ant30 = np.nan

            rows.append(
                {
                    "Duration": D,
                    "Rank": rank,
                    "ARI": float(ari_values[rank - 1]),
                    "StartDate": start_date,
                    "EndDate": end_date,
                    "MDR_mm": total,
                    "Ant_mm": ant,
                    "Ant30_mm": ant30,
                    "R20": r20,
                    "R40": r40,
                    "R60": r60,
                    "R80": r80,
                }
            )

        arr = np.array(picked_totals)
        stats_rows.append(
            {
                "Duration": D,
                "Mean": float(arr.mean()),
                "SDev": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                "Cv": float(arr.std(ddof=1) / arr.mean()) if arr.mean() > 0 and len(arr) > 1 else np.nan,
                "Median": float(np.median(arr)),
                "Skew": _skew(arr),
                "N": len(arr),
            }
        )

    return MDRResult(
        table=pd.DataFrame(rows),
        stats=pd.DataFrame(stats_rows),
        n_events=n_events,
        valid_frac=valid_frac,
        n_years=n_years,
    )


def _skew(a: np.ndarray) -> float:
    """Fisher-Pearson skewness (matches MATLAB `skewness(x)` default, biased)."""
    if len(a) < 2:
        return float("nan")
    m = a.mean()
    s = a.std(ddof=0)
    if s == 0:
        return 0.0
    return float(((a - m) ** 3).mean() / s ** 3)
