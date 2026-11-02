"""Fit the six-coefficient MDR design curve.

Model (matching MATLAB `MDR_DesignCurveFit2022.m`):

    P(D, ARI) = AA(D) + BB(D) * ln(ARI)
        AA(D) = a1 + a2 * (D^a3 - 1)
        BB(D) = a4 + a5 * (D^a6 - 1)

    a = [Ao, A1, A2, Bo, B1, B2]

The MATLAB used hand-rolled Gauss-Newton with per-stage weights; here we use
`scipy.optimize.least_squares` (Levenberg-Marquardt / TRF), which is a drop-in
replacement for the same weighted-ratio residual and converges more reliably.

Restricted-sampling multipliers (2022 version): 1d=1.10, 2d=1.07, 3d=1.02.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

RESTRICTED_MULT = {1: 1.10, 2: 1.07, 3: 1.02}


@dataclass
class FitResult:
    a: np.ndarray  # 6-element coefficient array
    nash: float
    r2: float
    rmse: float
    nbias: float
    observed_vs_predicted: pd.DataFrame  # Duration, Rank, ARI, Observed, Predicted
    n_points: int


def _mdr_predict(a: np.ndarray, D: np.ndarray, ARI: np.ndarray) -> np.ndarray:
    Ao, A1, A2, Bo, B1, B2 = a
    AA = Ao + A1 * (D ** A2 - 1.0)
    BB = Bo + B1 * (D ** B2 - 1.0)
    return AA + BB * np.log(ARI)


def _nash_sutcliffe(obs: np.ndarray, prd: np.ndarray) -> tuple[float, float, float, float]:
    obs = np.asarray(obs, dtype=float)
    prd = np.asarray(prd, dtype=float)
    resid = obs - prd
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    denom = float(np.sum((obs - obs.mean()) ** 2))
    nash = float(1.0 - np.sum(resid ** 2) / denom) if denom > 0 else float("nan")
    if obs.std() > 0 and prd.std() > 0:
        r = float(np.corrcoef(obs, prd)[0, 1])
        r2 = r * r
    else:
        r2 = float("nan")
    nbias = float(np.mean(resid) / obs.mean()) if obs.mean() != 0 else float("nan")
    return nash, r2, rmse, nbias


def _density(durations: np.ndarray) -> np.ndarray:
    """Point-density weighting: 2/(D[i+1]-D[i-1]) with edges copied inward."""
    d = np.sort(np.unique(durations))
    dens = np.zeros_like(d, dtype=float)
    if len(d) < 2:
        return np.ones_like(dens)
    for i in range(1, len(d) - 1):
        dens[i] = 2.0 / (d[i + 1] - d[i - 1])
    dens[0] = dens[1]
    dens[-1] = dens[-2]
    return dict(zip(d, dens))  # type: ignore[return-value]


def fit_mdr_curve(
    mdr_table: pd.DataFrame,
    ari_wgt_pwr: float = 0.5,
    d_wgt_pwr: float = 0.0,
    ari_min: float = 2.0,
    initial: np.ndarray | None = None,
) -> FitResult:
    """Fit `a[1..6]` from a ranked-maxima table (as produced by mdr_build.build_mdr).

    Filters to ARI >= ari_min, applies the 2022 restricted-sampling multipliers
    to durations {1,2,3}, then does weighted-ratio least squares.
    """
    df = mdr_table.copy()
    df = df[df["ARI"] >= ari_min]
    if df.empty:
        raise ValueError(f"No data points with ARI >= {ari_min}")

    D = df["Duration"].to_numpy(dtype=float)
    ARI = df["ARI"].to_numpy(dtype=float)
    Y = df["MDR_mm"].to_numpy(dtype=float).copy()

    mult = np.array([RESTRICTED_MULT.get(int(d), 1.0) for d in D])
    Y = Y * mult

    # Weights
    dens_map: dict[float, float] = _density(D)  # type: ignore[assignment]
    dens = np.array([dens_map[float(d)] for d in D])
    w = (ARI ** ari_wgt_pwr) * (D ** d_wgt_pwr) / np.sqrt(dens)
    w = w / w.sum()

    # Initial estimates: linear regression Y vs ln(ARI) per duration → AA(D),BB(D)
    if initial is None:
        durs = np.sort(np.unique(D))
        AA = []
        BB = []
        for d in durs:
            mask = D == d
            x = np.log(ARI[mask])
            y = Y[mask]
            if len(x) < 2:
                slope, intercept = 0.0, float(y.mean())
            else:
                slope, intercept = np.polyfit(x, y, 1)
            AA.append(intercept)
            BB.append(slope)
        AA = np.array(AA)
        BB = np.array(BB)

        Ao = float(AA[0]) if durs[0] == 1 else float(AA[0])
        Bo = float(BB[0]) if durs[0] == 1 else float(BB[0])

        # Fit AA(D) = Ao + A1*(D^A2 - 1) to (durs, AA)
        def _resid_pow(p, x, target, base):
            k1, k2 = p
            return (base + k1 * (x ** k2 - 1.0)) - target

        try:
            sol_a = least_squares(
                _resid_pow, x0=[float(np.median(np.diff(AA)) if len(AA) > 1 else 5.0), 0.6],
                args=(durs, AA, Ao),
                bounds=([0.01, 0.05], [np.inf, 1.5]),
            )
            A1, A2 = float(sol_a.x[0]), float(sol_a.x[1])
        except Exception:
            A1, A2 = 5.0, 0.6

        try:
            sol_b = least_squares(
                _resid_pow, x0=[float(np.median(np.diff(BB)) if len(BB) > 1 else 2.0), 0.6],
                args=(durs, BB, Bo),
                bounds=([0.01, 0.05], [np.inf, 1.5]),
            )
            B1, B2 = float(sol_b.x[0]), float(sol_b.x[1])
        except Exception:
            B1, B2 = 2.0, 0.6

        initial = np.array([Ao, A1, A2, Bo, B1, B2])

    # Final joint fit on all 6 coefficients using weighted ratio residuals.
    def _resid_full(a: np.ndarray) -> np.ndarray:
        prd = _mdr_predict(a, D, ARI)
        # Ratio residual matches the MATLAB formulation exactly.
        return w * (prd / Y - 1.0)

    bounds = (
        [0.1, 0.01, 0.05, 0.1, 0.01, 0.05],
        [np.inf, np.inf, 1.5, np.inf, np.inf, 1.5],
    )
    sol = least_squares(_resid_full, x0=initial, bounds=bounds, max_nfev=2000)
    a = sol.x

    prd_all = _mdr_predict(a, D, ARI)
    nash, r2, rmse, nbias = _nash_sutcliffe(Y, prd_all)

    obs_vs_prd = pd.DataFrame(
        {
            "Duration": D.astype(int),
            "Rank": df["Rank"].values,
            "ARI": ARI,
            "Observed_mm": Y,
            "Predicted_mm": prd_all,
        }
    ).sort_values(["Duration", "Rank"]).reset_index(drop=True)

    return FitResult(
        a=a,
        nash=nash,
        r2=r2,
        rmse=rmse,
        nbias=nbias,
        observed_vs_predicted=obs_vs_prd,
        n_points=len(Y),
    )
