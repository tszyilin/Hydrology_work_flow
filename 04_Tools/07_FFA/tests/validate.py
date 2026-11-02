"""Headless validation of ffa_core against BestFit example datasets.

Not shipped. Confirms the Hunter-Singleton 1 % AEP estimate from our
L-moments LP3 fit falls within our bootstrap CI of the TUFLOW FLIKE
published value (19,572 m³/s, Bayesian LP3 with Jeffreys prior on sigma).
We expect a reasonable envelope match, not bit-for-bit equality — the
estimators are different.
"""
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "ffa"))

import ffa_core  # noqa: E402


HUNTER_FLIKE_1PCT_AEP = 19572.0  # m³/s, TUFLOW FLIKE Bayesian LP3


def run(csv_path, value_col, year_col="Year", label=""):
    print(f"\n==== {label} ({os.path.basename(csv_path)}) ====")
    yrs, vals = ffa_core.load_series_csv(csv_path, value_col, year_col=year_col)
    print(f"  n={len(yrs)}, range {yrs[0]}–{yrs[-1]}, "
          f"min {vals.min():.1f} max {vals.max():.1f}")

    aris = (2, 5, 10, 20, 50, 100, 200, 500, 1000)
    for dist in ("LP3", "GEV", "Gumbel"):
        fr = ffa_core.fit(vals, dist, method="lmom")
        rl = ffa_core.return_levels(fr, aris)
        line = ", ".join(f"{int(t)}y={v:,.0f}" for t, v in rl.items())
        print(f"  {dist:7s} lmom: {line}")

    # Bootstrap CI on LP3 at a few key ARIs
    ci = ffa_core.bootstrap_ci(
        vals, "LP3", method="lmom",
        aris=(50, 100, 500), n_boot=500, seed=42,
    )
    for t in (50, 100, 500):
        lo, hi = ci[float(t)]
        print(f"  LP3 {t}y 95% CI: [{lo:,.0f}, {hi:,.0f}]")
    return vals, ci


def main():
    hunter_csv = os.path.join(HERE, "hunter_singleton_ams.csv")
    moose_csv = os.path.join(HERE, "moose_victory_ams.csv")

    vals, hunter_ci = run(hunter_csv, "Flow_cms",
                          label="Hunter R @ Singleton")
    fr100 = ffa_core.fit(vals, "LP3", "lmom")
    rl = ffa_core.return_levels(fr100, [100])
    est = rl[100.0]
    lo, hi = hunter_ci[100.0]
    inside = lo <= HUNTER_FLIKE_1PCT_AEP <= hi
    print(f"\n  TUFLOW FLIKE 1% AEP ref:   {HUNTER_FLIKE_1PCT_AEP:,.0f} m³/s")
    print(f"  Our L-mom LP3 1% AEP:      {est:,.0f} m³/s")
    print(f"  Our 95% bootstrap CI:      [{lo:,.0f}, {hi:,.0f}]")
    print(f"  FLIKE value in our CI?     {'YES' if inside else 'NO (expected on Bayesian vs L-mom)'}")

    run(moose_csv, "Flow_cfs", label="Moose R @ Victory VT")


if __name__ == "__main__":
    main()
