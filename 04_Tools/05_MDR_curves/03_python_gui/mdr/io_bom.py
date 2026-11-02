"""Read BOM-style daily rainfall CSVs into a continuous daily series.

BOM CSV columns (as in ../01_Example/01.Input/*.csv):
    Station Number, Code, Year, Month, Day,
    Rainfall amount (millimetres),
    Period over which rainfall was measured (days)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Station:
    """One BOM station reindexed to a complete daily DatetimeIndex.

    `rain` is a pandas.Series of mm/day indexed by calendar date. Missing days
    (either absent from the CSV or blank in the source) are NaN.
    """

    code: str
    label: str
    rain: pd.Series

    @property
    def start_year(self) -> int:
        return int(self.rain.index.year.min())

    @property
    def end_year(self) -> int:
        return int(self.rain.index.year.max())

    def clip_years(self, start_year: int, end_year: int) -> "Station":
        mask = (self.rain.index.year >= start_year) & (self.rain.index.year <= end_year)
        return Station(self.code, self.label, self.rain.loc[mask])


def read_bom_csv(path: str | Path, label: str | None = None) -> Station:
    """Parse a BOM daily-rainfall CSV into a `Station`."""
    path = Path(path)
    df = pd.read_csv(path)

    rename = {}
    for c in df.columns:
        lc = c.lower()
        if lc.startswith("year"):
            rename[c] = "year"
        elif lc.startswith("month"):
            rename[c] = "month"
        elif lc.startswith("day") and "period" not in lc:
            rename[c] = "day"
        elif "rainfall" in lc and "period" not in lc:
            rename[c] = "rain"
        elif lc.startswith("code"):
            rename[c] = "code"
    df = df.rename(columns=rename)

    for col in ("year", "month", "day"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["rain"] = pd.to_numeric(df["rain"], errors="coerce")
    df = df.dropna(subset=["year", "month", "day"])
    df = df.astype({"year": int, "month": int, "day": int})

    dates = pd.to_datetime(
        dict(year=df["year"], month=df["month"], day=df["day"]),
        errors="coerce",
    )
    df = df.assign(date=dates).dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date"], keep="last")

    rain = df.set_index("date")["rain"].sort_index()
    full_index = pd.date_range(rain.index.min(), rain.index.max(), freq="D")
    rain = rain.reindex(full_index)

    code = str(df["code"].iloc[0]) if "code" in df.columns and not df.empty else path.stem
    return Station(code=code, label=label or code, rain=rain)


def coverage_summary(station: Station) -> pd.DataFrame:
    """Per-year present/missing day counts. Handy for the GUI Infill tab."""
    r = station.rain
    df = pd.DataFrame(
        {
            "year": r.index.year,
            "present": r.notna().astype(int),
        }
    )
    grp = df.groupby("year")["present"]
    days_in_year = np.where(
        pd.to_datetime(df["year"].astype(str) + "-12-31").dt.is_leap_year, 366, 365
    )
    tbl = grp.agg(["sum", "count"]).rename(columns={"sum": "present", "count": "days"})
    tbl["missing"] = tbl["days"] - tbl["present"]
    tbl["pct_complete"] = 100 * tbl["present"] / tbl["days"]
    return tbl.reset_index()
