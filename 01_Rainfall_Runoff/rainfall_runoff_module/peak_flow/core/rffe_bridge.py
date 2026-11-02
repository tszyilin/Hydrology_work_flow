"""Wrapper around the vendored RFFE 2021 web-app client.

The client itself lives at `core/vendor/rffe_client.py` so the plugin is
self-contained and works from any install location.
"""

from .vendor.rffe_client import AEPS, RffeError, query_site, station_table
from .vendor.rffe_output import (FFA_LAYER_SUFFIX, build_layers,
                                 catchments_in_geology, compute_rock_alluvial)


def flatten_recommended(models):
    """Return (recommended_model_name, {aep_label: {'flow','lower','upper'}})."""
    rec = models.get("Recommended Model")
    rec_model = models.get(rec, {}) if rec else {}
    flow = rec_model.get("Flow", [])
    lo = rec_model.get("05pct", [])
    hi = rec_model.get("95pct", [])
    out = {}
    for i, aep in enumerate(AEPS):
        out[aep] = {
            "flow": flow[i] if i < len(flow) else None,
            "lower": lo[i] if i < len(lo) else None,
            "upper": hi[i] if i < len(hi) else None,
        }
    return rec, out


def stations_used(region, limit=15):
    """Return up to `limit` stations from the RFFE region tables, closest
    first when a distance column is present. RFFE fits the recommended
    model from these stations, so this is the set 'RFFE actually used'."""
    header, rows = station_table(region)
    if not rows:
        return header, []
    dist_col = None
    for i, col in enumerate(header):
        if "distance" in str(col).lower():
            dist_col = i
            break

    def sort_key(r):
        if dist_col is None or dist_col >= len(r):
            return 0
        try:
            return float(r[dist_col])
        except (TypeError, ValueError):
            return float("inf")

    return header, sorted(rows, key=sort_key)[:limit]


def filter_region_top_n(region, n=15):
    """Return a copy of the RFFE `region` dict with only the `n` nearest
    stations kept (keyed by 'Dist km' when present, otherwise unchanged).

    The RFFE 15-stations layer needs a region dict in the same pandas
    'split' shape that `build_layers` expects — {region_id: {'index',
    'columns', 'data'}} — so we filter rows in place across all
    sub-regions and keep the format intact.
    """
    if not isinstance(region, dict):
        return region
    # Collect (dist, region_id, index_pos, station_index, row) across all
    # sub-regions, then sort by dist ascending and keep the closest N.
    entries = []
    for rid, tbl in region.items():
        if not (isinstance(tbl, dict) and "columns" in tbl and "data" in tbl):
            continue
        cols = list(tbl["columns"])
        dist_col = None
        for i, c in enumerate(cols):
            if "distance" in str(c).lower() or c == "Dist km":
                dist_col = i
                break
        for pos, (stn_idx, row) in enumerate(zip(tbl["index"], tbl["data"])):
            try:
                d = float(row[dist_col]) if dist_col is not None else float("inf")
            except (TypeError, ValueError, IndexError):
                d = float("inf")
            entries.append((d, rid, pos, stn_idx, row))
    entries.sort(key=lambda e: e[0])
    keep = entries[:n]

    # Rebuild per-region tables containing only the kept rows.
    out = {}
    kept_per_region = {}
    for _d, rid, _pos, stn_idx, row in keep:
        kept_per_region.setdefault(rid, []).append((stn_idx, row))
    for rid, tbl in region.items():
        if not (isinstance(tbl, dict) and "columns" in tbl and "data" in tbl):
            out[rid] = tbl
            continue
        rows = kept_per_region.get(rid, [])
        out[rid] = {
            "index": [r[0] for r in rows],
            "columns": tbl["columns"],
            "data": [r[1] for r in rows],
        }
    return out


__all__ = [
    "AEPS", "RffeError", "query_site", "station_table",
    "flatten_recommended", "stations_used", "build_layers", "filter_region_top_n",
    "FFA_LAYER_SUFFIX", "catchments_in_geology", "compute_rock_alluvial",
]
