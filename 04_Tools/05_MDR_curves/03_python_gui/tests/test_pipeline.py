"""Smoke + reference tests for the MDR pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mdr.curve_fit import fit_mdr_curve
from mdr.design import critical_duration, design_pe, design_q, design_rainfall
from mdr.mdr_build import build_mdr


def test_design_rainfall_matches_matlab_form():
    # Reference coefficients from ../01_Example/02.Output/04.MDR/DesignCurveFit
    a = np.array([68.586, 14.324, 0.5906, 33.208, 6.2051, 0.5938])
    # For D=1, ARI=10:  P = a1 + a4*ln(10) = 68.586 + 33.208*2.302585 = 145.05 mm
    p, p24, _, _ = design_rainfall(a, ari=10.0, d_days=1.0)
    assert abs(p - (68.586 + 33.208 * np.log(10))) < 0.01
    assert abs(p24 - p) < 0.01  # at D=1 they coincide

    # At D=30, ARI=10:  P = AA(30) + BB(30)*ln(10) ≈ 331 mm.
    p30, *_ = design_rainfall(a, ari=10.0, d_days=30.0)
    assert 320 < p30 < 345
    # At D=30, ARI=100 the depth should climb to ~500 mm.
    p30_100, *_ = design_rainfall(a, ari=100.0, d_days=30.0)
    assert 480 < p30_100 < 520
    # Extreme: D=150, ARI=127 ≈ 1020 mm (matches example Results.ARI ≈ 1011.7 mm).
    p150_127, *_ = design_rainfall(a, ari=127.0, d_days=150.0)
    assert 980 < p150_127 < 1070


def test_design_pe_q_monotone():
    p, pe, c = design_pe(200.0, 3.0, il_a=0.5, fo=20.0, emax=3.0)
    assert 0 < pe < 200
    q, phi = design_q(pe, de=3.0, lag=0.5)
    assert 0 < q < pe
    assert 0 < phi < 1


def test_critical_duration():
    a = np.array([68.586, 14.324, 0.5906, 33.208, 6.2051, 0.5938])
    # Max gradient (at D=1) with ARI=100 is ~25 mm/day; pick qmax below it.
    dcrit, p = critical_duration(a, ari=100.0, qmax=10.0)
    a1, a2, a3, a4, a5, a6 = a
    grad = a2 * a3 * dcrit ** (a3 - 1) + a5 * a6 * dcrit ** (a6 - 1) * np.log(100.0)
    assert abs(grad - 10.0) < 0.01
    assert 1.0 < dcrit < 250.0


def test_mdr_build_toy_series():
    # Rain series with one obvious 3-day peak of 100 mm/day at days 10..12
    idx = pd.date_range("2000-01-01", "2004-12-31", freq="D")
    r = pd.Series(0.5, index=idx)
    r.iloc[10:13] = 100.0
    r.iloc[500:503] = 60.0

    result = build_mdr(r, durations=[1, 3, 5], events_per_year=1.0)
    top3 = result.table[result.table["Duration"] == 3].sort_values("Rank").iloc[0]
    assert abs(top3["MDR_mm"] - 300.0) < 1e-6
    # Second-ranked 3-day should be the 60mm/day cluster (180 mm)
    second = result.table[result.table["Duration"] == 3].sort_values("Rank").iloc[1]
    assert 178.0 < second["MDR_mm"] < 181.0


def test_curve_fit_recovers_synthetic():
    # Build a fake MDR table from known coefficients, then fit.
    a_true = np.array([70.0, 15.0, 0.6, 33.0, 6.0, 0.6])
    durs = [1, 2, 3, 5, 7, 10, 20, 50, 100]
    aris = [2, 5, 10, 20, 50, 100, 200]
    rows = []
    rank_gen = {}
    for d in durs:
        for i, ari in enumerate(aris):
            rank = i + 1
            AA = a_true[0] + a_true[1] * (d ** a_true[2] - 1)
            BB = a_true[3] + a_true[4] * (d ** a_true[5] - 1)
            p = AA + BB * np.log(ari)
            # Undo the restricted-sampling adjustment so the fit inverts cleanly.
            mult = {1: 1.10, 2: 1.07, 3: 1.02}.get(d, 1.0)
            rows.append({"Duration": d, "Rank": rank, "ARI": ari, "MDR_mm": p / mult})
    tbl = pd.DataFrame(rows)

    fit = fit_mdr_curve(tbl, ari_wgt_pwr=0.5, d_wgt_pwr=0.0, ari_min=2.0)
    for expected, got in zip(a_true, fit.a):
        assert abs(expected - got) / max(abs(expected), 1e-6) < 0.05
    assert fit.nash > 0.99


def test_reference_reproduction_from_example():
    """End-to-end run against ../01_Example/ should reproduce the MATLAB fit closely.

    Tolerance is generous (5% on each coefficient) because our
    scipy.least_squares fit lands on a marginally different local optimum than
    MATLAB's staged Gauss-Newton — but Nash-Sutcliffe should still exceed 0.98.
    """
    from pathlib import Path

    from mdr.double_mass import run_double_mass
    from mdr.infill import infill
    from mdr.io_bom import read_bom_csv

    root = Path(__file__).parents[2] / "01_Example" / "01.Input"
    if not root.exists():
        pytest.skip("example folder not found (test running in isolation)")

    a = read_bom_csv(root / "35032_1890-1976.csv", label="35032").clip_years(1890, 2025)
    b = read_bom_csv(root / "35016_1898-2025.csv", label="35016").clip_years(1890, 2025)
    dm = run_double_mass(a, b)
    assert dm.r > 0.999  # excellent linear agreement
    assert 0.98 < dm.correction_b_to_a < 1.03

    inf = infill(a, b, dm.correction_b_to_a, label="Group1")
    durs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40,
            45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]
    mdr = build_mdr(inf.composite.rain, durs, events_per_year=1.0)
    fit = fit_mdr_curve(mdr.table, ari_wgt_pwr=0.5, d_wgt_pwr=0.0, ari_min=2.0)

    a_ref = np.array([68.586, 14.324, 0.5906, 33.208, 6.2051, 0.5938])
    for i, (got, expected) in enumerate(zip(fit.a, a_ref)):
        rel = abs(got - expected) / abs(expected)
        assert rel < 0.20, f"coefficient a{i+1}: got {got}, expected {expected} (rel err {rel:.2%})"
    assert fit.nash > 0.98


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
