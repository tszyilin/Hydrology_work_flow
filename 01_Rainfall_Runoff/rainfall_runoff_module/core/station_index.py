"""BoM rainfall station index loaded from a bundled shapefile.

Reads ``modules/rainfall/data/AUS_BoM_RF_Stations.shp`` using geopandas/fiona
when available, and falls back to a pure-Python shapefile+DBF reader so the
plugin works on a bare QGIS install.
"""
from __future__ import annotations

import math
import struct
from functools import lru_cache
from pathlib import Path

import pandas as pd

SHAPEFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "AUS_BoM_RF_Stations.shp"


def _read_shapefile_pure(shp_path: Path) -> pd.DataFrame:
    """Pure-Python .shp + .dbf reader for point layers (no external deps)."""
    dbf_path = shp_path.with_suffix(".dbf")

    with open(dbf_path, "rb") as f:
        f.read(4)
        n_records = struct.unpack("<I", f.read(4))[0]
        header_size = struct.unpack("<H", f.read(2))[0]
        struct.unpack("<H", f.read(2))[0]  # record_size
        f.read(20)

        field_defs = []
        while f.tell() < header_size - 1:
            data = f.read(32)
            if not data or data[0] == 0x0D:
                break
            name = data[:11].replace(b"\x00", b"").decode("ascii", "ignore")
            ftype = chr(data[11])
            flen = data[16]
            field_defs.append((name, ftype, flen))

        f.seek(header_size)
        records = []
        for _ in range(n_records):
            del_flag = f.read(1)
            if not del_flag:
                break
            row = {}
            for name, ftype, flen in field_defs:
                raw = f.read(flen).decode("ascii", "ignore").strip()
                if ftype == "N":
                    try:
                        row[name] = float(raw) if "." in raw else int(raw)
                    except ValueError:
                        row[name] = None
                else:
                    row[name] = raw
            records.append(row)

    df = pd.DataFrame(records)

    with open(shp_path, "rb") as f:
        f.read(100)
        lats, lons = [], []
        while True:
            rec_header = f.read(8)
            if len(rec_header) < 8:
                break
            content_len = struct.unpack(">I", rec_header[4:8])[0] * 2
            content = f.read(content_len)
            if len(content) < 4:
                break
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type == 1 and len(content) >= 20:
                x = struct.unpack("<d", content[4:12])[0]
                y = struct.unpack("<d", content[12:20])[0]
                lons.append(x); lats.append(y)
            else:
                lons.append(None); lats.append(None)

    n = min(len(df), len(lats))
    df = df.iloc[:n].copy()
    df["_LAT"] = lats[:n]
    df["_LON"] = lons[:n]
    return df


def _infer_state(lat: float, lon: float) -> str:
    if lon < 129:
        if lat > -22:
            return "NT"
        if lon < 126:
            return "WA"
        return "NT"
    if lon < 138:
        if lat > -26:
            return "NT"
        if lat > -31:
            return "SA"
        return "SA" if lon < 141 else "VIC"
    if lon < 141:
        if lat < -31.5:
            return "VIC"
        if lat < -26:
            return "SA"
        return "QLD"
    if lon < 153.5:
        if lat < -38:
            return "TAS"
        if lat < -34:
            return "VIC"
        if lat < -28.5:
            return "NSW"
        return "QLD"
    return "NSW"


@lru_cache(maxsize=1)
def load_stations() -> list[dict]:
    """Return list of dicts with keys: id, name, lat, lon, state, start_year,
    end_year, pct_complete. Cached for the lifetime of the QGIS session."""
    if not SHAPEFILE_PATH.exists():
        raise RuntimeError(f"Shapefile missing: {SHAPEFILE_PATH}")

    gdf = None
    try:
        import geopandas as gpd
        gdf = gpd.read_file(str(SHAPEFILE_PATH))
    except Exception:
        pass

    if gdf is None:
        try:
            import fiona
            recs = []
            with fiona.open(str(SHAPEFILE_PATH)) as src:
                for feat in src:
                    props = dict(feat["properties"])
                    geom = feat["geometry"]
                    if geom and geom["type"] == "Point":
                        props["_LON"] = geom["coordinates"][0]
                        props["_LAT"] = geom["coordinates"][1]
                    recs.append(props)
            gdf = pd.DataFrame(recs)
        except Exception:
            pass

    if gdf is None:
        gdf = _read_shapefile_pure(SHAPEFILE_PATH)

    cols_upper = {c.upper(): c for c in gdf.columns}
    col_map = {}
    for key, candidates in [
        ("id", ["SITE_ID", "STATIONID", "STN_ID", "ID"]),
        ("name", ["SITE_NAME", "STATION_NAME", "NAME", "STATION"]),
        ("lat", ["LAT", "_LAT", "LATITUDE"]),
        ("lon", ["LONG", "LON", "_LON", "LONGITUDE"]),
        ("start_year", ["START_Y", "START_YEAR", "STARTYEAR"]),
        ("end_year", ["END_Y", "END_YEAR", "ENDYEAR"]),
        ("pct", ["PC_COMPLET", "PCT_COMPLETE", "COMPLETENESS"]),
        ("state", ["STATE", "ST"]),
    ]:
        for c in candidates:
            if c in cols_upper:
                col_map[key] = cols_upper[c]
                break

    if hasattr(gdf, "geometry") and hasattr(gdf.geometry, "x"):
        if "lat" not in col_map:
            gdf = gdf.copy()
            gdf["_lat"] = gdf.geometry.y
            gdf["_lon"] = gdf.geometry.x
            col_map["lat"] = "_lat"
            col_map["lon"] = "_lon"

    def _int_safe(row, col):
        try:
            return int(float(row[col]))
        except Exception:
            return None

    def _float_safe(row, col):
        try:
            v = float(row[col])
            return None if math.isnan(v) else round(v, 1)
        except Exception:
            return None

    results = []
    for _, row in gdf.iterrows():
        try:
            sid = str(int(float(row[col_map["id"]]))).zfill(6)
        except Exception:
            continue
        try:
            lat = float(row[col_map["lat"]])
            lon = float(row[col_map["lon"]])
        except Exception:
            lat = lon = None

        state = "?"
        if "state" in col_map:
            state = str(row[col_map["state"]]).strip().upper()
        elif lat is not None and lon is not None:
            state = _infer_state(lat, lon)

        results.append({
            "id": sid,
            "name": str(row[col_map["name"]]).strip() if "name" in col_map else sid,
            "lat": lat,
            "lon": lon,
            "state": state,
            "start_year": _int_safe(row, col_map["start_year"]) if "start_year" in col_map else None,
            "end_year": _int_safe(row, col_map["end_year"]) if "end_year" in col_map else None,
            "pct_complete": _float_safe(row, col_map["pct"]) if "pct" in col_map else None,
        })

    return results
