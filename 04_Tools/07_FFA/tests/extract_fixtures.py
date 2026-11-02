"""Extract AMS fixtures from the BestFit .bestfit SQLite files.

Not shipped with the plugin — a one-off tool for validation.
"""
import csv
import os
import sqlite3
import xml.etree.ElementTree as ET

HERE = os.path.dirname(__file__)

FIXTURES = [
    # (bestfit_file, example_name, output_csv, value_header)
    ("arr-flike-examples.bestfit", "Example #3",
     "hunter_singleton_ams.csv", "Flow_cms"),
    ("bulletin-17c.bestfit", "Example #1",
     "moose_victory_ams.csv", "Flow_cfs"),
]


def extract_ams(bestfit_path, example_name):
    with sqlite3.connect(bestfit_path) as c:
        row = c.execute(
            'SELECT DataFrame FROM "Input Data" WHERE Name = ?', (example_name,)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Example {example_name!r} not in {bestfit_path}")
    root = ET.fromstring(row[0])
    series = root.find("ExactSeries")
    out = []
    for ed in series.findall("ExactData"):
        year = int(ed.get("Index"))
        value = float(ed.get("Value"))
        out.append((year, value))
    out.sort(key=lambda yv: yv[0])
    return out


def main():
    for src, example, out_name, val_header in FIXTURES:
        src_path = os.path.join(HERE, src)
        out_path = os.path.join(HERE, out_name)
        series = extract_ams(src_path, example)
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Year", val_header])
            for yr, v in series:
                w.writerow([yr, v])
        print(f"{out_name}: {len(series)} rows "
              f"({series[0][0]}–{series[-1][0]}), "
              f"min {min(v for _, v in series):.1f} "
              f"max {max(v for _, v in series):.1f}")


if __name__ == "__main__":
    main()
