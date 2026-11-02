"""Rebuild ``pmp_toolbox/data/dda_gsdm.csv`` from the reference workbook.

Run this only if ``GSDM/GSDM_Depth_Area_Curves_Digitise.xlsx`` changes.  The CSV
is committed so the plugin needs no openpyxl at runtime.

    python tools/build_data.py

Two things this script does *not* produce:

``table2.csv``
    Transcribed by hand from Table 2 of ``GSDM/GSDM.pdf``.  ``test_gsdm.py``
    cross-checks it against these curves.

the point rows
    The workbook digitises the areal curves from 1 km2 up.  The point values --
    the rows at ``area = 1e-05``, which is how the tables stand for a point --
    were read separately, so they are carried across from the existing CSV
    rather than regenerated.  If the existing file is missing they are dropped,
    and the script says so: the GSDM tab's point column depends on them.

The GTSMR and GSAM tables are not built here at all; they are vendored from the
Toolbox website project, which took them from the Bureau's GTSMR CD.
"""

import csv
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "GSDM" / "GSDM_Depth_Area_Curves_Digitise.xlsx"
OUT = ROOT / "pmp_toolbox" / "data" / "dda_gsdm.csv"

#: The area a row uses to stand for a point.
POINT_AREA = 1e-05

#: Sheet `Raw data` rows 34-537 hold the curves in tidy form; row 33 is a header.
FIRST_ROW, LAST_ROW = 34, 537

#: Curve labels look like "0.25hr R&S", "1.5hr S", "6hr R".
LABEL = re.compile(r"^\s*([\d.]+)\s*hr\s*(R&S|S|R)\s*$", re.I)

EXPECTED_DURATIONS = 11
EXPECTED_AREAS = 28


def main() -> int:
    if not XLSX.exists():
        print(f"reference workbook not found: {XLSX}", file=sys.stderr)
        return 1

    ws = openpyxl.load_workbook(XLSX, data_only=True)["Raw data"]

    rows = []
    for r in range(FIRST_ROW, LAST_ROW + 1):
        label, area, depth = (ws.cell(r, c).value for c in (1, 2, 3))
        if label is None:
            continue
        m = LABEL.match(str(label))
        if not m:
            print(f"row {r}: unparsed curve label {label!r}", file=sys.stderr)
            return 1
        duration = float(m.group(1))
        # Below 1 hour the Bulletin draws one curve for both terrain categories
        # (section 4.2); expand it so lookups never have to special-case that.
        terrains = ("S", "R") if m.group(2).upper() == "R&S" else (m.group(2).upper(),)
        for terrain in terrains:
            rows.append((duration, terrain, float(area), round(float(depth), 4)))

    rows.sort(key=lambda t: (t[1], t[0], t[2]))

    durations = {d for d, _, _, _ in rows}
    areas = {a for _, _, a, _ in rows}
    if len(durations) != EXPECTED_DURATIONS or len(areas) != EXPECTED_AREAS:
        print(
            f"expected {EXPECTED_DURATIONS} durations and {EXPECTED_AREAS} areas, "
            f"got {len(durations)} and {len(areas)}",
            file=sys.stderr,
        )
        return 1
    if len(rows) != 2 * EXPECTED_DURATIONS * EXPECTED_AREAS:
        print(f"expected a full grid, got {len(rows)} rows", file=sys.stderr)
        return 1

    point_rows = _existing_point_rows()
    if point_rows:
        rows = sorted(rows + point_rows, key=lambda t: (t[1], t[0], t[2]))
    else:
        print(
            f"warning: no point rows found in {OUT.name}; the GSDM tab's point "
            "column will be the 1 km2 value",
            file=sys.stderr,
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["duration", "terrain", "area", "rainfall"])
        writer.writerows(rows)

    print(
        f"wrote {len(rows)} rows to {OUT.relative_to(ROOT)} "
        f"({len(point_rows)} carried-over point rows)"
    )
    return 0


def _existing_point_rows():
    """The point rows already in the CSV, so a rebuild does not lose them."""
    if not OUT.exists():
        return []
    kept = []
    with OUT.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if float(row["area"]) < 1.0:
                kept.append(
                    (
                        float(row["duration"]),
                        row["terrain"],
                        float(row["area"]),
                        float(row["rainfall"]),
                    )
                )
    return kept


if __name__ == "__main__":
    raise SystemExit(main())
