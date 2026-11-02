"""BoM Climate Data Online + Revised IFD 2016 client.

Ported from ``06_BOM_rainfall/api.py`` (see PROJECT plan). All network access
lives here so the UI layer can stay pure Qt. Callers should invoke these
functions off the GUI thread — the BoM scrapes take several seconds and can
raise ``_NoDataError`` (permanent — do not retry) or ``RuntimeError``.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile

import numpy as np
import pandas as pd
import requests

try:
    from cachetools import TTLCache
except ImportError:  # Minimal fallback so the plugin still loads if cachetools missing.
    class TTLCache(dict):  # type: ignore[no-redef]
        def __init__(self, maxsize=128, ttl=3600):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._t: dict = {}

        def __setitem__(self, k, v):
            if len(self) >= self.maxsize:
                self.clear(); self._t.clear()
            super().__setitem__(k, v)
            self._t[k] = time.time()

        def __contains__(self, k):
            if not super().__contains__(k):
                return False
            if time.time() - self._t.get(k, 0) > self.ttl:
                super().__delitem__(k); self._t.pop(k, None)
                return False
            return True


OBS_CODE = 136
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "http://www.bom.gov.au/climate/data/",
}


class _NoDataError(Exception):
    """Raised when BOM permanently has no rainfall data for a station."""


def haversine_km(lat1: float, lon1: float, lat2, lon2) -> np.ndarray:
    R = 6371.0
    lat2 = np.asarray(lat2, dtype=float)
    lon2 = np.asarray(lon2, dtype=float)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    )
    return 2 * R * np.arcsin(np.sqrt(a))


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.bom.gov.au/climate/data/", timeout=15)
    return s


def _parse_station_info(html: str) -> dict:
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = plain.replace("&deg;", "°").replace("&nbsp;", " ").replace("&amp;", "&")
    plain = re.sub(r"\s+", " ", plain)

    anchor = re.search(r"Number:\s*\d+", plain, re.IGNORECASE)
    if not anchor:
        block = plain
    else:
        start = max(0, anchor.start() - 300)
        end = min(len(plain), anchor.end() + 600)
        block = plain[start:end]

    STOP = r"(?=\s*(?:Number|Opened|Now|Lat|Lon|Elevation|Station|Details)\s*:)"

    def field(label, default="N/A"):
        m = re.search(rf"{label}\s*:\s*(.*?){STOP}", block, re.IGNORECASE)
        return m.group(1).strip() if m else default

    name = field("Station")
    number = field("Number")
    opened = field("Opened")
    now = field("Now")
    lat = field("Lat")
    lon = field("Lon")
    elev_m = re.search(r"Elevation\s*:\s*([\d.]+)\s*m", block, re.IGNORECASE)
    elev = elev_m.group(1) if elev_m else "N/A"
    is_open = ("closed" not in now.lower()) if now != "N/A" else None

    def _parse_coord(s, neg_dir):
        if not s or s == "N/A":
            return None
        num = re.search(r"[\d.]+", s)
        if not num:
            return None
        val = float(num.group())
        if neg_dir.upper() in s.upper():
            val = -val
        return val

    return {
        "name": name,
        "number": number,
        "lat": _parse_coord(lat, "S"),
        "lon": _parse_coord(lon, "W"),
        "opened": opened,
        "now": now,
        "is_open": is_open,
        "elevation": elev,
    }


_station_data_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)


def fetch_station_raw(station_id: str) -> dict:
    """Scrape BoM CDO for a station's daily rainfall zip. Returns {"df", "info"}.

    Cached for 1 hour per station. Raises ``_NoDataError`` (permanent) or
    ``RuntimeError`` (transient — the caller may retry).
    """
    station_id = station_id.strip().zfill(6)
    if station_id in _station_data_cache:
        return _station_data_cache[station_id]

    last_exc = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(1.5)
        try:
            session = _make_session()
            page_url = (
                f"https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av"
                f"?p_nccObsCode={OBS_CODE}&p_display_type=dailyDataFile"
                f"&p_startYear=&p_c=&p_stn_num={station_id}"
            )
            resp = session.get(page_url, timeout=30)
            resp.raise_for_status()
            page_html = resp.text

            if "No data available" in page_html or "Error code: 1001" in page_html:
                raise _NoDataError(
                    f"Station {station_id} has no daily rainfall data in BOM Climate "
                    "Data Online. It may measure a different parameter."
                )

            match = re.search(
                r"p_display_type=dailyZippedDataFile&amp;p_stn_num=\d+&amp;p_c=(-?\d+)"
                r"&amp;p_nccObsCode=\d+&amp;p_startYear=(\d+)",
                page_html,
            )
            if not match:
                raise _NoDataError(
                    f"Station {station_id} does not have a daily rainfall download available."
                )

            p_c, start_year = match.group(1), match.group(2)
            download_url = (
                f"https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av"
                f"?p_display_type=dailyZippedDataFile&p_stn_num={station_id}"
                f"&p_c={p_c}&p_nccObsCode={OBS_CODE}&p_startYear={start_year}"
            )
            resp2 = session.get(download_url, timeout=60)
            resp2.raise_for_status()
            if "html" in resp2.headers.get("Content-Type", ""):
                raise RuntimeError("BoM returned HTML instead of a zip.")

            with zipfile.ZipFile(io.BytesIO(resp2.content)) as z:
                csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
                if not csv_files:
                    raise RuntimeError("No CSV in downloaded zip.")
                with z.open(csv_files[0]) as f:
                    df = pd.read_csv(f)

            info = _parse_station_info(page_html)
            result = {"df": df, "info": info}
            _station_data_cache[station_id] = result
            return result

        except _NoDataError:
            raise
        except (zipfile.BadZipFile, RuntimeError, requests.RequestException) as e:
            last_exc = e
            continue

    raise RuntimeError(f"BoM did not return valid data after 3 attempts. Last error: {last_exc}")


def build_daily_df(station_id: str, distribute: bool = True) -> tuple[pd.DataFrame, dict]:
    """Return (daily_df with Date + Rainfall_mm columns, station_info)."""
    cached = fetch_station_raw(station_id)
    df = cached["df"].copy()
    info = cached["info"]

    df.columns = df.columns.str.strip()
    rain_col = next((c for c in df.columns if "rainfall" in c.lower()), None)
    period_col = next((c for c in df.columns if "period" in c.lower()), None)
    if not rain_col:
        raise RuntimeError("No rainfall column in BoM CSV.")

    df["Date"] = pd.to_datetime(df[["Year", "Month", "Day"]], errors="coerce")
    df[rain_col] = pd.to_numeric(df[rain_col], errors="coerce")

    if period_col and distribute:
        df[period_col] = pd.to_numeric(df[period_col], errors="coerce").fillna(1).clip(lower=1)
        df = df.set_index("Date").sort_index()
        rain_series = df[rain_col].copy()
        for date, row in df[df[period_col] > 1].iterrows():
            p = int(row[period_col])
            r = row[rain_col]
            if pd.isna(r):
                continue
            daily = round(r / p, 1)
            for i in range(p):
                d = date - pd.Timedelta(days=i)
                if d in rain_series.index:
                    rain_series[d] = daily
        df[rain_col] = rain_series
        df = df.reset_index()

    df = df.rename(columns={rain_col: "Rainfall_mm"})
    return df[["Date", "Rainfall_mm"]], info


# ── IFD 2016 ──────────────────────────────────────────────────────────────────
_ifd_cache: TTLCache = TTLCache(maxsize=128, ttl=86400 * 30)


def within_ifd_coverage(lat: float, lon: float) -> bool:
    return -44.5 <= lat <= -9.0 and 112.0 <= lon <= 154.0


def duration_to_minutes(label: str) -> float | None:
    s = label.strip().lower()
    try:
        if "min" in s:
            return float(re.search(r"[\d.]+", s).group())
        if "hour" in s or " h" in s or s.endswith("h"):
            return float(re.search(r"[\d.]+", s).group()) * 60
        if "day" in s:
            return float(re.search(r"[\d.]+", s).group()) * 1440
    except Exception:
        pass
    return None


# AEP column order in BoM's "All Design Rainfall Depth" reference CSV.
# 20% and 0.2EY (and 63.2% and 1EY) are the same probability but come from
# different tables and can differ in the third significant figure — so both
# are kept, in this order, to match BoM's own combined download.
_AEP_ORDER = [
    "12EY", "6EY", "4EY", "3EY", "2EY",
    "63.2%", "50%",
    "1EY", "0.5EY",
    "20%", "0.2EY",
    "10%", "5%", "2%", "1%",
    "1 in 100", "1 in 200", "1 in 500", "1 in 1000", "1 in 2000",
]


def _fetch_ifd_variant(sess, lat: float, lon: float, design: str) -> dict:
    """One BoM call for one 'design' flavor: very_frequent / ifds / rare.

    Returns ``{"columns": [...], "table": {duration: {col: mm}}}`` or an empty
    dict if BoM returned no parseable table for that flavor at this location
    (Rare, in particular, only covers durations 24 h and up).
    """
    base_url = "https://www.bom.gov.au/water/designRainfalls/revised-ifd/"
    post_url = base_url + "?multipoint"
    body = (
        f"design={design}"
        f"&sdmin=true&sdhr=true&sdday=true"
        f"&coordinate_type=dd"
        f"&latitude={lat}&longitude={lon}"
        f"&multi={json.dumps([[lat, lon]])}"
    )
    resp = sess.post(
        post_url, data=body,
        headers={"Content-type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.text
    html = re.sub(r"<abbr[^>]*>([^<]*)</abbr>", r"\1", html, flags=re.IGNORECASE)
    html = re.sub(r'\s+width="[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r'\s+colspan="100%"', "", html, flags=re.IGNORECASE)

    marker = html.find("ifdDepthTab")
    if marker == -1:
        return {}
    ts = html.find("<table", marker)
    te = html.find("</table>", ts) + len("</table>")
    if ts == -1 or te <= ts:
        return {}

    tables = pd.read_html(io.StringIO(html[ts:te]))
    if not tables:
        return {}

    df = tables[0]
    df = df.set_index(df.columns[0])
    df.index = df.index.astype(str).str.strip()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[-1]).strip() for c in df.columns]
    else:
        df.columns = [str(c).strip() for c in df.columns]
    df.columns = [re.sub(r"[#*†‡]+$", "", c).strip() for c in df.columns]

    columns = list(df.columns)
    table: dict[str, dict[str, float]] = {}
    for idx in df.index:
        if duration_to_minutes(idx) is None:
            continue
        row_data: dict[str, float] = {}
        for col in columns:
            try:
                f = float(df.loc[idx, col])
                if not pd.isna(f):
                    row_data[str(col).strip()] = round(f, 1)
            except (ValueError, TypeError):
                pass
        if row_data:
            table[idx] = row_data
    return {"columns": columns, "table": table}


def fetch_ifd(lat: float, lon: float) -> dict:
    """Fetch Very Frequent + Design + Rare BoM IFD tables and merge them.

    Returns ``{"durations": [...], "aep_cols": [...], "table": {dur: {aep: mm}}}``
    with the column order matching BoM's own "All Design Rainfall Depth" export
    (12EY … 1 in 2000). Cached 30 days per rounded coordinate. Raises
    RuntimeError only if all three BoM calls failed.
    """
    if not within_ifd_coverage(lat, lon):
        raise RuntimeError(
            f"({lat:.3f}, {lon:.3f}) is outside BoM Revised IFD 2016 coverage."
        )

    key = (round(lat, 3), round(lon, 3))
    if key in _ifd_cache:
        return _ifd_cache[key]

    base_url = "https://www.bom.gov.au/water/designRainfalls/revised-ifd/"
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.get(base_url, timeout=15)

    lat3, lon3 = key
    parts: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for flavor in ("very_frequent", "ifds", "rare"):
        try:
            parts[flavor] = _fetch_ifd_variant(sess, lat3, lon3, flavor)
        except Exception as exc:
            errors[flavor] = str(exc)

    # Merge: union of durations (sorted by minutes); AEP columns in BoM order.
    merged_table: dict[str, dict[str, float]] = {}
    seen_cols: set[str] = set()
    for part in parts.values():
        for dur, row in part.get("table", {}).items():
            merged_table.setdefault(dur, {}).update(row)
            seen_cols.update(row.keys())

    if not merged_table:
        raise RuntimeError(
            "No IFD values extracted from BoM. Errors: " + str(errors)
        )

    # AEP order: preferred canonical order first, then any unknown columns tacked on.
    aep_cols = [c for c in _AEP_ORDER if c in seen_cols]
    for c in seen_cols:
        if c not in aep_cols:
            aep_cols.append(c)

    durations = sorted(merged_table.keys(),
                       key=lambda d: duration_to_minutes(d) or 0)

    result = {"durations": durations, "aep_cols": aep_cols, "table": merged_table}
    if errors:
        result["_warnings"] = errors
    _ifd_cache[key] = result
    return result
