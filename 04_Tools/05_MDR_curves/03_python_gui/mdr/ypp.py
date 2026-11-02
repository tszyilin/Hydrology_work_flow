"""Year-per-page (YPP) format helpers.

The MATLAB YPP format is a text file per station-year, laid out as a 12-column
by 31-row grid of daily rainfall (with -1 for missing and -2 for impossible
dates such as Feb 30). Here we produce the same logical grid as a pandas
DataFrame, plus monthly and annual summaries.
"""

from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .io_bom import Station


def year_grid(rain: pd.Series, year: int) -> pd.DataFrame:
    """Return a 31x12 DataFrame (rows=day 1..31, cols=Jan..Dec).

    Missing days are NaN; impossible dates (Feb 30, etc.) are also NaN.
    """
    idx = rain.index[rain.index.year == year]
    days = rain.loc[idx]

    grid = pd.DataFrame(
        np.nan,
        index=range(1, 32),
        columns=[calendar.month_abbr[m] for m in range(1, 13)],
    )
    for date, val in days.items():
        grid.loc[date.day, calendar.month_abbr[date.month]] = val
    return grid


def monthly_totals(rain: pd.Series) -> pd.DataFrame:
    """One row per (year, month) with total, days_present, days_expected."""
    df = pd.DataFrame({"rain": rain})
    df["year"] = df.index.year
    df["month"] = df.index.month
    agg = (
        df.groupby(["year", "month"])["rain"]
        .agg(total="sum", present=lambda s: s.notna().sum(), days="size")
        .reset_index()
    )
    return agg


def annual_totals(rain: pd.Series) -> pd.DataFrame:
    """One row per year with total, days_present, pct_complete."""
    m = monthly_totals(rain)
    agg = m.groupby("year").agg(total=("total", "sum"), present=("present", "sum"), days=("days", "sum"))
    agg["pct_complete"] = 100 * agg["present"] / agg["days"]
    return agg.reset_index()


def write_ypp(station: Station, out_dir: str | "os.PathLike") -> None:
    """Write one CSV per year plus a summary XLSX to out_dir/<station.code>/."""
    from pathlib import Path

    sub = Path(out_dir) / station.code
    sub.mkdir(parents=True, exist_ok=True)

    years = sorted(set(station.rain.index.year))
    for y in years:
        grid = year_grid(station.rain, y)
        grid.to_csv(sub / f"{station.code}_{y}.csv", float_format="%.2f")

    summary = sub / f"{station.code}_summary.xlsx"
    with pd.ExcelWriter(summary, engine="openpyxl") as xw:
        annual_totals(station.rain).to_excel(xw, sheet_name="annual", index=False)
        wide = (
            monthly_totals(station.rain)
            .pivot(index="year", columns="month", values="total")
            .rename(columns={i: calendar.month_abbr[i] for i in range(1, 13)})
        )
        wide.to_excel(xw, sheet_name="monthly")
