"""Write pipeline outputs to disk in the layout of ../01_Example/02.Output/."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .curve_fit import FitResult
from .design import curve_table
from .double_mass import DoubleMassResult
from .infill import InfillResult
from .io_bom import Station
from .mdr_build import MDRResult
from .plotting import design_curves_figure, double_mass_figure, observed_vs_predicted_figure
from .ypp import annual_totals, monthly_totals, write_ypp


def _mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_stage1_ypp(stations: list[Station], out_root: Path) -> None:
    root = _mkdir(out_root / "01.DPPToYPP")
    for st in stations:
        write_ypp(st, root)


def write_stage2_double_mass(
    result: DoubleMassResult,
    label_a: str,
    label_b: str,
    out_root: Path,
) -> None:
    root = _mkdir(out_root / "02.DoubleMass")
    result.common.to_csv(root / "double_mass.csv", index_label="date")

    fig = double_mass_figure(result.common, result.correction_b_to_a, label_a, label_b)
    fig.savefig(root / "double_mass.png")

    with pd.ExcelWriter(root / "double_mass_report.xlsx", engine="openpyxl") as xw:
        pd.DataFrame(
            {
                "metric": ["correction (B→A)", "correlation r", "N common days"],
                "value": [result.correction_b_to_a, result.r, result.n_common_days],
            }
        ).to_excel(xw, sheet_name="summary", index=False)


def write_stage3_infill(result: InfillResult, out_root: Path) -> None:
    root = _mkdir(out_root / "03.Infilled")
    comp = result.composite
    daily = comp.rain.rename("rainfall_mm")
    daily.to_csv(root / f"{comp.code}_daily.csv", index_label="date")
    # Per-year YPP-style grids for parity with the MATLAB output tree.
    write_ypp(comp, root)
    with pd.ExcelWriter(root / "infill_summary.xlsx", engine="openpyxl") as xw:
        pd.DataFrame(
            {
                "metric": ["days from A", "days filled from B", "days still missing"],
                "value": [result.days_from_a, result.days_from_b, result.days_still_missing],
            }
        ).to_excel(xw, sheet_name="summary", index=False)
        annual_totals(comp.rain).to_excel(xw, sheet_name="annual", index=False)


def write_stage4_mdr(
    mdr: MDRResult,
    fit: FitResult,
    coefs: np.ndarray,
    plot_aris: list[float],
    plot_max_duration: float,
    p1_on_p24: float,
    out_root: Path,
) -> None:
    root = _mkdir(out_root / "04.MDR")

    # Ranked maxima — same table, two sort orders.
    tbl = mdr.table.copy()
    tbl.sort_values(["ARI", "Duration"], ascending=[False, True]).to_csv(root / "Results_ARI.csv", index=False)
    tbl.sort_values(["Duration", "Rank"]).to_csv(root / "Results_Days.csv", index=False)
    mdr.stats.to_csv(root / "Statistics.csv", index=False)

    # Curve-fit input (Duration, Rank, ARI, MDR_mm) — the "Curve_Fit" file.
    tbl[["Duration", "Rank", "ARI", "MDR_mm"]].to_csv(root / "Curve_Fit.csv", index=False)

    # Design fit summary
    fit_summary = pd.DataFrame(
        {
            "coefficient": ["a1", "a2", "a3", "a4", "a5", "a6"],
            "value": list(coefs),
        }
    )
    stats = pd.DataFrame(
        {
            "metric": ["Nash-Sutcliffe", "R²", "RMSE (mm)", "Normalized bias", "N points"],
            "value": [fit.nash, fit.r2, fit.rmse, fit.nbias, fit.n_points],
        }
    )
    with pd.ExcelWriter(root / "DesignCurveFit.xlsx", engine="openpyxl") as xw:
        fit_summary.to_excel(xw, sheet_name="coefficients", index=False)
        stats.to_excel(xw, sheet_name="fit_stats", index=False)
        fit.observed_vs_predicted.to_excel(xw, sheet_name="obs_vs_pred", index=False)

    # Depth × ARI table for direct engineering use.
    durations_grid = [0.5, 1, 2, 3, 5, 7, 10, 14, 20, 30, 45, 60, 90, 120, 150]
    durations_grid = [d for d in durations_grid if d <= plot_max_duration]
    ct = curve_table(coefs, plot_aris, durations_grid, p1_on_p24)
    ct.to_excel(root / "design_summary.xlsx")

    # Plots
    fig1 = design_curves_figure(coefs, plot_aris, max_duration=plot_max_duration, p1_on_p24=p1_on_p24)
    fig1.savefig(root / "design_curves.png")
    fig2 = observed_vs_predicted_figure(fit.observed_vs_predicted)
    fig2.savefig(root / "observed_vs_predicted.png")
