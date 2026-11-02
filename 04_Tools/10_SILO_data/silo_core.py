"""SILO Patched Point Dataset: station search, download and Actual/Synthetic split.

No UI here, so the standalone Tk app (silo_gui.py) and the Qt dialog used
inside the Hydrology Workflow Suite (silo_dialog.py) share one copy.
"""

import datetime as dt
import io
import re
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

API_URL = "https://www.longpaddock.qld.gov.au/cgi-bin/silo/PatchedPointDataset.php"
FIRST_DATE = dt.date(1889, 1, 1)

# (API letter, CSV column, label, ticked by default)
VARIABLES = [
    ("R", "daily_rain", "Rainfall (mm)", True),
    ("X", "max_temp", "Max temperature (°C)", True),
    ("N", "min_temp", "Min temperature (°C)", True),
    ("J", "radiation", "Solar radiation (MJ/m²)", True),
    ("V", "vp", "Vapour pressure (hPa)", True),
    ("D", "vp_deficit", "Vapour pressure deficit (hPa)", False),
    ("H", "rh_tmax", "RH at Tmax (%)", False),
    ("G", "rh_tmin", "RH at Tmin (%)", False),
    ("E", "evap_pan", "Class A pan evaporation (mm)", True),
    ("S", "evap_syn", "Synthetic evaporation (mm)", False),
    ("C", "evap_comb", "Combination evaporation (mm)", False),
    ("L", "evap_morton_lake", "Morton shallow lake evap (mm)", False),
    ("F", "et_short_crop", "FAO56 short crop ET (mm)", False),
    ("T", "et_tall_crop", "ASCE tall crop ET (mm)", False),
    ("A", "et_morton_actual", "Morton areal actual ET (mm)", False),
    ("P", "et_morton_potential", "Morton point potential ET (mm)", False),
    ("W", "et_morton_wet", "Morton wet-environment ET (mm)", False),
    ("M", "mslp", "Mean sea level pressure (hPa)", False),
]

# https://www.longpaddock.qld.gov.au/silo/about/about-data/
SOURCE_CODES = {
    0: "Official BoM observation",
    15: "Accumulated rainfall redistributed over the days it probably fell",
    25: "Interpolated from daily observations",
    26: "Synthetic Class A pan evaporation",
    35: "Interpolated (anomaly method)",
    42: "Satellite radiation estimate (BoM)",
    75: "Interpolated from long-term daily averages",
}

EMAIL_RE = r"[^@\s']+@[^@\s']+\.[^@\s']+"


# ---------------------------------------------------------------- SILO API

def _request(params):
    url = API_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    with urllib.request.urlopen(url, timeout=300) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_stations(text):
    """Return a list of station dicts matching a station number or name fragment."""
    text = text.strip()
    if not text:
        return []
    if text.isdigit():
        body = _request({"format": "id", "station": text})
    else:
        # SILO rejects spaces in requests; "_" matches any single character instead
        body = _request({"format": "name", "nameFrag": re.sub(r"\s+", "_", text)})
    stations = []
    for line in body.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        stations.append({
            "number": int(parts[0]),
            "name": parts[1].title(),
            "lat": float(parts[2]),
            "lon": float(parts[3]),
            "state": parts[4],
            "elevation": float(parts[5]),
        })
    return stations


def fetch_data(station, start, end, columns, email):
    """Download daily data for the given CSV column names as a DataFrame."""
    letters = "".join(code for code, col, _, _ in VARIABLES if col in columns)
    body = _request({
        "format": "csv",
        "station": station,
        "start": start.strftime("%Y%m%d"),
        "finish": end.strftime("%Y%m%d"),
        "comment": letters,
        "username": email,
        "password": "apirequest",
    })
    if not body.startswith("station,"):
        raise RuntimeError("SILO returned an error:\n\n" + body.strip()[:1000])
    df = pd.read_csv(io.StringIO(body), skipinitialspace=True)
    # Live responses label the date column "YYYY-MM-DD" and append a "metadata"
    # column whose extra lines (name=, latitude=, ...) have no date
    df = df.rename(columns={"YYYY-MM-DD": "date"}).drop(columns="metadata", errors="ignore")
    df = df.dropna(subset=["date"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    for col in columns:
        df[col + "_source"] = df[col + "_source"].astype(int)
    return df


def code15_runs(df):
    """Find runs of consecutive code-15 rain days and their even split.

    SILO keeps the measured total within each run but distributes it unevenly
    by its own estimate. Two accumulations that touch merge into one run, as
    the response gives no way to tell them apart.
    """
    if "daily_rain" not in df:
        return pd.DataFrame()
    is15 = df["daily_rain_source"].eq(15)
    run_id = (is15 != is15.shift()).cumsum()[is15]
    rows = []
    for _, idx in df[is15].groupby(run_id).groups.items():
        rain = df.loc[idx, "daily_rain"]
        rows.append({
            "Start": df.at[idx[0], "date"].date(),
            "End": df.at[idx[-1], "date"].date(),
            "Days": len(idx),
            "Total (mm)": round(rain.sum(), 1),
            "SILO split (mm)": ", ".join(f"{v:g}" for v in rain),
            "Even split (mm/day)": round(rain.sum() / len(idx), 2),
            "_index": list(idx),
        })
    return pd.DataFrame(rows)


def spread_code15(df, runs):
    """Return a copy of df with each code-15 run's rain spread evenly."""
    out = df.copy()
    for _, run in runs.iterrows():
        out.loc[run["_index"], "daily_rain"] = run["Even split (mm/day)"]
    return out


def split_actual_synthetic(df, columns, actual_codes):
    """Return (actual, synthetic) frames; values outside each class are blank."""
    actual = df[["date"]].copy()
    synthetic = df[["date"]].copy()
    for col in columns:
        is_actual = df[col + "_source"].isin(actual_codes)
        actual[col] = df[col].where(is_actual)
        synthetic[col] = df[col].where(~is_actual)
        synthetic[col + "_source"] = df[col + "_source"].where(~is_actual).astype("Int64")
    # Drop days with nothing in that class so each sheet only lists useful rows
    actual = actual.dropna(subset=columns, how="all")
    synthetic = synthetic.dropna(subset=columns, how="all")
    return actual, synthetic


def summarise(df, columns, actual_codes):
    labels = {col: label for _, col, label, _ in VARIABLES}
    rows = []
    for col in columns:
        src = df[col + "_source"]
        is_actual = src.isin(actual_codes)
        actual_dates = df.loc[is_actual, "date"]
        row = {
            "Variable": labels[col],
            "Days": len(df),
            "Actual days": int(is_actual.sum()),
            "Actual %": round(100 * is_actual.mean(), 1) if len(df) else 0,
            "Synthetic days": int((~is_actual).sum()),
            "First actual": actual_dates.min().date() if len(actual_dates) else None,
            "Last actual": actual_dates.max().date() if len(actual_dates) else None,
        }
        for code, n in src.value_counts().sort_index().items():
            row[f"Code {code} days"] = int(n)
        rows.append(row)
    out = pd.DataFrame(rows)
    code_cols = sorted((c for c in out if c.startswith("Code ")), key=lambda c: int(c.split()[1]))
    out[code_cols] = out[code_cols].fillna(0).astype(int)
    return out[[c for c in out if not c.startswith("Code ")] + code_cols]


def save_excel(path, station, df, actual, synthetic, summary, actual_codes, runs, spread15):
    info = pd.DataFrame([
        ("Station number", station["number"]),
        ("Station name", station["name"]),
        ("State", station["state"]),
        ("Latitude", station["lat"]),
        ("Longitude", station["lon"]),
        ("Elevation (m)", station["elevation"]),
        ("Period", f"{df['date'].min().date()} to {df['date'].max().date()}"),
        ("Downloaded", dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Source", "SILO Patched Point Dataset, Queensland Government"),
        ("Actual = source codes", ", ".join(str(c) for c in sorted(actual_codes))),
        ("Code 15 rain in Actual/Synthetic",
         "Spread evenly over each run of days" if spread15 else "As distributed by SILO"),
    ], columns=["Item", "Value"])
    codes = pd.DataFrame(
        [(c, m, "Actual" if c in actual_codes else "Synthetic") for c, m in SOURCE_CODES.items()],
        columns=["Source code", "Meaning", "Classed as"],
    )

    with pd.ExcelWriter(path, engine="openpyxl", date_format="yyyy-mm-dd",
                        datetime_format="yyyy-mm-dd") as xl:
        info.to_excel(xl, sheet_name="Summary", index=False)
        summary.to_excel(xl, sheet_name="Summary", index=False, startrow=len(info) + 2)
        codes.to_excel(xl, sheet_name="Summary", index=False, startrow=len(info) + len(summary) + 5)
        actual.to_excel(xl, sheet_name="Actual", index=False)
        synthetic.to_excel(xl, sheet_name="Synthetic", index=False)
        if len(runs):
            runs.drop(columns="_index").to_excel(xl, sheet_name="Code 15 rain", index=False)
        df.to_excel(xl, sheet_name="Raw", index=False)
        for ws in xl.sheets.values():
            if ws.title != "Summary":
                ws.freeze_panes = "B2"
            for cells in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in cells[:200])
                ws.column_dimensions[cells[0].column_letter].width = min(max(width + 2, 10), 60)


def download_to_excel(station, start, end, columns, email, actual_codes, spread15, out_dir):
    """Fetch, classify and save one station's data. Returns (path, summary)."""
    df = fetch_data(station["number"], start, end, columns, email)
    runs = code15_runs(df)
    adjusted = spread_code15(df, runs) if spread15 else df
    actual, synthetic = split_actual_synthetic(adjusted, columns, actual_codes)
    summary = summarise(df, columns, actual_codes)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", station["name"]).strip("_")
    path = out_dir / f"SILO_{station['number']}_{safe_name}_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
    save_excel(path, station, df, actual, synthetic, summary, actual_codes, runs, spread15)
    return path, summary
