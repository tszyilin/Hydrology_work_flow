"""CSV writer matching the BoM 'All Design Rainfall Depth' export layout.

The example we target lives at
``01_Rainfall_Estimation/01_example/depths_-22.25_128.37_all_design.csv``.

The scrape in ``bom_client.fetch_ifd`` currently returns AEP columns only
(the design table). This writer emits the same header rows and column
structure BoM does, using whichever columns the fetched result contains.
The 'nearest grid cell' row is approximated from the requested coord snapped
to the nearest 0.025° cell — same convention BoM uses.
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from .bom_client import duration_to_minutes


ISSUED_FMT = "%d %B %Y"


def _nearest_cell(coord: float, letter_neg: str, letter_pos: str) -> str:
    """Snap a coord to the nearest 0.025° cell and format like BoM (e.g. '22.2375 (S)')."""
    step = 0.025
    snapped = round(coord / step) * step
    return f"{abs(snapped):.4f} ({letter_neg if snapped < 0 else letter_pos})"


def write_all_design_csv(
    path: str | Path,
    lat: float,
    lon: float,
    ifd_result: dict,
    location_label: str = "",
    aeps: list[str] | None = None,
) -> None:
    """Write ``depths_{lat}_{lon}_all_design.csv`` in the BoM layout.

    Header rows follow BoM's "All Design Rainfall Depth (mm)" export:
        - Copyright
        - blank
        - title
        - Issued date
        - Location label
        - Requested coordinate
        - Nearest grid cell
        - blank
        - two-row column header: (blank / EY grouping / AEP grouping), (Duration / Duration in min / <columns>)
    """
    path = Path(path)
    all_aeps = list(ifd_result.get("aep_cols", []))
    if aeps is None:
        aep_cols = all_aeps
    else:
        # Preserve BoM's column order for the subset the caller asked for.
        selected = set(aeps)
        aep_cols = [a for a in all_aeps if a in selected]
    durations = list(ifd_result.get("durations", []))
    table = ifd_result.get("table", {})

    lat_row = _nearest_cell(lat, "S", "N")
    lon_row = _nearest_cell(lon, "W", "E")
    issued = _dt.date.today().strftime(ISSUED_FMT)

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Copyright Commonwealth of Australia " + str(_dt.date.today().year)
                    + " Bureau of Meteorology (ABN 92 637 533 532)"])
        w.writerow([])
        w.writerow(["All Design Rainfall Depth (mm)"])
        w.writerow(["Issued:", issued])
        w.writerow(["Location Label:", location_label])
        w.writerow(["Requested coordinate:", "Latitude", f"{lat:.2f}",
                    "Longitude", f"{lon:.2f}"])
        w.writerow(["Nearest grid cell:", "Latitude", lat_row,
                    "Longitude", lon_row])
        w.writerow([])
        # Grouping row: EY columns under one label, AEP columns under another.
        first_aep = next((i for i, c in enumerate(aep_cols) if "EY" not in c), len(aep_cols))
        n_ey  = first_aep
        n_aep = len(aep_cols) - first_aep
        group = ["", ""]
        if n_ey > 0:
            group.append("Exceedances per Year (EY)")
            group.extend([""] * (n_ey - 1))
        if n_aep > 0:
            group.append("Annual Exceedance Probability (AEP)")
            group.extend([""] * (n_aep - 1))
        w.writerow(group)
        w.writerow(["Duration", "Duration in min"] + aep_cols)
        for dur in durations:
            row = [dur, duration_to_minutes(dur) or ""]
            for aep in aep_cols:
                v = table.get(dur, {}).get(aep)
                row.append("" if v is None else v)
            w.writerow(row)


def csv_filename(lat: float, lon: float) -> str:
    """``depths_{lat}_{lon}_all_design.csv`` — the format used by the example."""
    return f"depths_{lat:.2f}_{lon:.2f}_all_design.csv"
