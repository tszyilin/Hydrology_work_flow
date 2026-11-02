"""matplotlib figures for the GUI and file export."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # Safe default; the GUI switches to TkAgg on import.

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .design import design_rainfall


def double_mass_figure(cum_df: pd.DataFrame, correction: float, label_a: str, label_b: str):
    """Cumulative A vs cumulative B scatter + the correction line."""
    fig, ax = plt.subplots(figsize=(6, 5), dpi=100)
    ax.plot(cum_df["cumB"], cum_df["cumA"], ".", ms=2, alpha=0.6, label="daily cum. pairs")
    xs = np.array([0.0, cum_df["cumB"].max()])
    ax.plot(xs, xs * correction, "r-", lw=1.5, label=f"slope = {correction:.4f}")
    ax.set_xlabel(f"cumulative rainfall — {label_b} (mm)")
    ax.set_ylabel(f"cumulative rainfall — {label_a} (mm)")
    ax.set_title("Double-mass curve")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def design_curves_figure(
    coefs: np.ndarray,
    aris: list[float],
    max_duration: float = 150,
    n_points: int = 200,
    p1_on_p24: float = 0.4,
    log_x: bool = True,
    title: str = "MDR design curves",
):
    """Depth-vs-duration curves, one line per ARI."""
    if log_x:
        durations = np.logspace(np.log10(0.05), np.log10(max_duration), n_points)
    else:
        durations = np.linspace(0.05, max_duration, n_points)

    fig, ax = plt.subplots(figsize=(7, 5), dpi=100)
    for ari in aris:
        depths = [design_rainfall(coefs, ari, d, p1_on_p24)[0] for d in durations]
        ax.plot(durations, depths, label=f"ARI = {ari:g} yr")

    if log_x:
        ax.set_xscale("log")
    ax.set_xlabel("duration (days)")
    ax.set_ylabel("rainfall depth (mm)")
    ax.set_title(title)
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    return fig


def observed_vs_predicted_figure(obs_vs_pred: pd.DataFrame, title: str = "Observed vs Predicted MDR"):
    fig, ax = plt.subplots(figsize=(6, 5), dpi=100)
    for d, sub in obs_vs_pred.groupby("Duration"):
        ax.plot(sub["Observed_mm"], sub["Predicted_mm"], "o", ms=3, alpha=0.6, label=f"D={int(d)}d")
    lim = max(obs_vs_pred["Observed_mm"].max(), obs_vs_pred["Predicted_mm"].max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("Observed (mm)")
    ax.set_ylabel("Predicted (mm)")
    ax.set_title(title)
    ax.legend(fontsize=7, ncol=3)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig
