"""One-off helper: enumerate tables in the BestFit SQLite files and
dump the systematic AMS data to CSVs for use as validation fixtures.

Not shipped with the plugin.
"""
import csv
import os
import sqlite3

HERE = os.path.dirname(__file__)
FILES = ("arr-flike-examples.bestfit", "bulletin-17c.bestfit")


def dump_schema():
    for name in FILES:
        p = os.path.join(HERE, name)
        print(f"\n==== {name} ====")
        with sqlite3.connect(p) as c:
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            for t in tables:
                try:
                    (n,) = c.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()
                except Exception as e:
                    n = f"err: {e}"
                print(f"  {t}  (n={n})")


def peek_input_data():
    for name in FILES:
        p = os.path.join(HERE, name)
        print(f"\n==== {name} / Input Data ====")
        with sqlite3.connect(p) as c:
            cols = [r[1] for r in c.execute('PRAGMA table_info("Input Data")')]
            print("cols:", cols)
            rows = c.execute('SELECT * FROM "Input Data"').fetchall()
            for r in rows:
                # Show short preview of long text/blob columns
                preview = tuple(
                    (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v)
                    for v in r
                )
                print(" row:", preview)


def dump_dataframe_xml(filename, example_name, out_xml):
    """Pull the DataFrame XML for a named example to disk for inspection."""
    p = os.path.join(HERE, filename)
    with sqlite3.connect(p) as c:
        row = c.execute(
            'SELECT DataFrame FROM "Input Data" WHERE Name = ?', (example_name,)
        ).fetchone()
    with open(out_xml, "w", encoding="utf-8") as fh:
        fh.write(row[0])
    print(f"wrote {out_xml} ({len(row[0])} chars)")


if __name__ == "__main__":
    # dump_schema()
    # peek_input_data()
    dump_dataframe_xml("arr-flike-examples.bestfit", "Example #3",
                       os.path.join(HERE, "hunter_singleton_dataframe.xml"))
    dump_dataframe_xml("bulletin-17c.bestfit", "Example #1",
                       os.path.join(HERE, "moose_victory_dataframe.xml"))
