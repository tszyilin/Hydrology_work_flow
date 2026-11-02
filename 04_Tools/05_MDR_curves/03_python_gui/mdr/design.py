"""Design rainfall calculations using the fitted MDR curve.

Ports:
    MDR_DesignRainfall2012.m   → design_rainfall
    Interp0_24HrATan2012.m /
    Fit0_24Atan2012.m          → _sub_daily_rainfall (used when D < 1 day)
    MDR_Design_Pe2012.m        → design_pe
    MDR_Design_Q2012.m         → design_q
    MDR_Design_P_Pe_Q2012.m    → design_p_pe_q
    MDR_CriticalDuration.m     → critical_duration
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

BETA = -0.000557  # P1/P24 exponential decay coefficient (hard-coded in MATLAB)


def _fit_atan_params(p1_on_p24: float, g: float) -> tuple[float, float]:
    """Solve for the arctangent-interpolation coefficient `a` and exponent `m`.

    Ports MATLAB `Fit0_24Atan2012`: find a in (0.01, 10) such that
        m*a / (atan(a)*(1+a^2)) - g = 0,   where m = ln(P1/P24)/ln(atan(a/24)/atan(a))
    """

    def _err(a: float) -> float:
        m = np.log(p1_on_p24) / np.log(np.arctan(a / 24.0) / np.arctan(a))
        return m * a / np.arctan(a) / (1.0 + a * a) - g

    a = brentq(_err, 0.01, 10.0, xtol=1e-8)
    m = np.log(p1_on_p24) / np.log(np.arctan(a / 24.0) / np.arctan(a))
    return float(a), float(m)


def _sub_daily_rainfall(coefs: np.ndarray, p1_on_p24_zero: float, ari: float, d_hours: float) -> tuple[float, float]:
    """Sub-24 h interpolation via the arctangent model (D_hours < 24)."""
    a1, a2, a3, a4, a5, a6 = coefs
    p24 = a1 + a4 * np.log(ari)
    p1_on_p24 = (p1_on_p24_zero - 1.0 / 24.0) * np.exp(BETA * p24) + 1.0 / 24.0
    dpdt24 = a2 * a3 + a5 * a6 * np.log(ari)
    g = dpdt24 / p24
    a_atan, m = _fit_atan_params(p1_on_p24, g)

    d_days = d_hours / 24.0
    p = p24 * (np.arctan(a_atan * d_days) ** m) / (np.arctan(a_atan) ** m)
    dpdd = p24 * m * (a_atan / (1.0 + a_atan * a_atan)) * np.arctan(a_atan * d_days) ** (m - 1)
    return float(p), float(dpdd)


def design_rainfall(coefs: np.ndarray, ari: float, d_days: float, p1_on_p24_zero: float = 0.4) -> tuple[float, float, float, float]:
    """Compute design rainfall depth for a given ARI and duration.

    Returns
    -------
    P       depth (mm)
    P24     unrestricted 24 h depth at this ARI (mm)
    dPdD    gradient dP/dD (mm/day)
    Z       critical-duration curve ordinate (1 - (dP/dD) / (P/D))
    """
    a1, a2, a3, a4, a5, a6 = coefs
    p24 = a1 + a4 * np.log(ari)

    if d_days < 1.0:
        p, dpdd = _sub_daily_rainfall(coefs, p1_on_p24_zero, ari, d_days * 24.0)
    else:
        AA = a1 + a2 * (d_days ** a3 - 1.0)
        BB = a4 + a5 * (d_days ** a6 - 1.0)
        p = AA + BB * np.log(ari)
        dpdd = a2 * a3 * d_days ** (a3 - 1.0) + a5 * a6 * (d_days ** (a6 - 1.0)) * np.log(ari)

    z = 1.0 - dpdd / (p / d_days) if p > 0 and d_days > 0 else float("nan")
    return float(p), float(p24), float(dpdd), float(z)


def design_pe(p: float, d_days: float, il_a: float, fo: float, emax: float) -> tuple[float, float, float]:
    """Rainfall excess. Port of `MDR_Design_Pe2012`."""
    f = fo + max(0.0, d_days - 1.0) * emax
    p_star = p - il_a * fo
    if p_star > 0:
        x = p_star / f
        c = np.tanh(x) ** 2
        pe = p_star - f * np.tanh(x)
        de = (1.0 - il_a * fo / p) * d_days if p > 0 else 0.0
        return float(pe), float(de), float(c)
    return 0.0, 0.0, 0.0


def design_q(pe: float, de: float, lag: float) -> tuple[float, float]:
    """Cumulative outflow. Port of `MDR_Design_Q2012`."""
    if de <= 0 or lag <= 0:
        return 0.0, 0.0
    phi = 1.0 - (lag / de) * (1.0 - np.exp(-de / lag))
    return float(phi * pe), float(phi)


@dataclass
class DesignPoint:
    P: float
    Pe: float
    Q: float
    dQdD: float
    d2QdD2: float
    De: float


def design_p_pe_q(
    coefs: np.ndarray,
    p1_on_p24: float,
    ari: float,
    d_days: float,
    il_a: float,
    fo: float,
    emax: float,
    lag: float,
) -> DesignPoint:
    """Combined design query. Port of `MDR_Design_P_Pe_Q2012`.

    Uses a ±2 % duration perturbation for the numerical dQ/dD and d²Q/dD².
    """
    p, _p24, _dpdd, _z = design_rainfall(coefs, ari, d_days, p1_on_p24)
    du = 1.02 * d_days
    dl = 0.98 * d_days
    pu, *_ = design_rainfall(coefs, ari, du, p1_on_p24)
    pl, *_ = design_rainfall(coefs, ari, dl, p1_on_p24)

    pe_u, de_u, _ = design_pe(pu, du, il_a, fo, emax)
    pe, de, _ = design_pe(p, d_days, il_a, fo, emax)
    pe_l, de_l, _ = design_pe(pl, dl, il_a, fo, emax)

    qe_u, _ = design_q(pe_u, de_u, lag)
    q, _phi = design_q(pe, de, lag)
    qe_l, _ = design_q(pe_l, de_l, lag)

    dQdD = (qe_u - qe_l) / (du - dl)
    d2QdD2 = ((2.0 * (qe_u - q) / (du - dl)) - (2.0 * (q - qe_l) / (du - dl))) / ((du - dl) / 2.0)
    return DesignPoint(P=p, Pe=pe, Q=q, dQdD=dQdD, d2QdD2=d2QdD2, De=de)


def critical_duration(coefs: np.ndarray, ari: float, qmax: float, d_lo: float = 1.0, d_hi: float = 250.0) -> tuple[float, float]:
    """Duration at which dP/dD = qmax for the given ARI. Port of `MDR_CriticalDuration`.

    Returns (Dcrit_days, P_at_Dcrit_mm).
    """
    a1, a2, a3, a4, a5, a6 = coefs

    def _grad_minus_qmax(d: float) -> float:
        return qmax - (a2 * a3 * d ** (a3 - 1.0) + a5 * a6 * d ** (a6 - 1.0) * np.log(ari))

    y_lo = _grad_minus_qmax(d_lo)
    y_hi = _grad_minus_qmax(d_hi)
    if y_lo == 0:
        d = d_lo
    elif y_hi == 0:
        d = d_hi
    elif np.sign(y_lo) == np.sign(y_hi):
        g_lo = qmax - y_lo
        g_hi = qmax - y_hi
        raise ValueError(
            f"qmax = {qmax} out of range: gradient at D={d_lo} → {g_lo:.4g}, "
            f"at D={d_hi} → {g_hi:.4g}"
        )
    else:
        d = brentq(_grad_minus_qmax, d_lo, d_hi, xtol=1e-4)
    AA = a1 + a2 * (d ** a3 - 1.0)
    BB = a4 + a5 * (d ** a6 - 1.0)
    p = AA + BB * np.log(ari)
    return float(d), float(p)


def curve_table(coefs: np.ndarray, aris: list[float], durations: list[float], p1_on_p24: float = 0.4) -> "pd.DataFrame":
    """Depth vs (duration, ARI) matrix for plotting/tabulating."""
    import pandas as pd

    depths = np.zeros((len(durations), len(aris)))
    for j, ari in enumerate(aris):
        for i, d in enumerate(durations):
            p, *_ = design_rainfall(coefs, ari, d, p1_on_p24)
            depths[i, j] = p
    return pd.DataFrame(depths, index=durations, columns=[f"ARI_{a:g}" for a in aris]).rename_axis("Duration_days")
