"""Double-mass homogeneity check.

Given two overlapping stations A and B, plot cumulative rainfall of A vs B on
their common non-missing dates. A straight line through the origin means the
two records are consistent; the slope is the multiplicative correction factor
that maps B onto A's scale (or vice-versa).

Mirrors the MATLAB `YPP_DoubleMass.m` output but writes a modern
CSV+PNG+XLSX bundle rather than the fixed-width text report.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .io_bom import Station


@dataclass
class DoubleMassResult:
    """Product of `run_double_mass`.

    correction_b_to_a: multiply station B by this factor to match A.
    """

    common: pd.DataFrame  # columns: A, B, cumA, cumB
    correction_b_to_a: float
    r: float
    n_common_days: int


def run_double_mass(a: Station, b: Station) -> DoubleMassResult:
    df = pd.DataFrame({"A": a.rain, "B": b.rain}).dropna()
    if df.empty:
        raise ValueError("No overlapping non-missing dates between the two stations")

    df["cumA"] = df["A"].cumsum()
    df["cumB"] = df["B"].cumsum()

    # Slope through the origin: sum(B*A)/sum(B*B) — maps cumB → cumA.
    slope = float(np.sum(df["cumA"] * df["cumB"]) / np.sum(df["cumB"] ** 2))

    r = float(np.corrcoef(df["cumA"], df["cumB"])[0, 1])
    return DoubleMassResult(
        common=df,
        correction_b_to_a=slope,
        r=r,
        n_common_days=len(df),
    )
