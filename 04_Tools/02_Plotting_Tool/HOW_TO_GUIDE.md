# Flood Frequency / RORB Flow Comparison Tool — How to Use

## Running it
Requires `pandas`, `matplotlib`, and `tkinter` (tkinter ships with standard
Python on Windows/Mac; on Linux you may need `sudo apt install python3-tk`).

```
python flow_comparison_gui.py
```

On startup you'll be prompted for two things, in order:
1. **Browse to the workbook** (a standard file-picker window).
2. **Pick which sheet/tab** in that workbook holds the data (a small
   dropdown dialog listing every sheet in the file — skipped
   automatically if the workbook only has one sheet).

If you cancel either prompt, the tool exits without opening.

**Skipping the prompts:** you can still pass the file and/or sheet name
directly on the command line, which skips the corresponding prompt —
handy for quick re-runs:
```
python flow_comparison_gui.py path\to\workbook.xlsx
python flow_comparison_gui.py path\to\workbook.xlsx SheetName
```

## Layout
The window has a shared sidebar on the left (Location, Method, Variant,
Colour Style) and two tabs on the right:

* **Flow Comparison** — Qpeak vs ARI, as before.
* **Growth Curves** — each currently-ticked curve normalised by its own
  value at a reference event (default 1 in 10).

Both tabs plot whichever Method/Variant combinations are ticked in the
shared sidebar — you don't select curves separately for each tab.

## Shared sidebar controls
| Control | What it does |
|---|---|
| **Location** | Pick one site from the dropdown. |
| **Method** | Tick/untick which method(s) to include (e.g. RORB, FFA). |
| **Variant** | Tick/untick individual variants of whichever Method(s) are checked — this list rebuilds automatically. |
| **Colour Style** | *Distinct marker/line per variant* (default): one colour per Method, with marker shape and line dash varying per Variant. *Shades of one colour per method*: marker and line dash become uniform (solid line, circle marker), and each Variant instead gets its own lightness shade of that Method's colour — darkest to lightest. Applies to both tabs. |

Method/Variant on/off choices persist by name as you move between
locations — e.g. turn RORB off once, it stays off everywhere until you
turn it back on.

## Flow Comparison tab
| Control | What it does |
|---|---|
| **Axis Limits** | **Scale**: choose Log or Linear independently for X and Y. **Limits**: leave on *Auto* (default), or untick Auto X/Y, type your own min/max, and hit **Apply**. **Reset to auto** reverts both axes' limits (not their scale). Custom limits stay fixed even if you switch location; Auto recalculates fresh each time. Switching an axis's scale resets that axis back to Auto limits, since a manual range from the old scale may not make sense in the new one. Note: a log-scale axis requires a positive minimum (can't include zero). |
| **Export** | *Export chart as image* saves the current view (PNG/PDF/SVG/JPEG). *Export plotted data as CSV* saves the underlying data for whichever curves are currently ticked on. |

## Growth Curves tab
| Control | What it does |
|---|---|
| **Reference Event** | Type the AEP (as "1 in X") you want every curve normalised against — e.g. `10` for the 1 in 10 event — and hit **Apply**. Default is 10. |
| **Axis Limits** | Same idea as the Flow Comparison tab (independent X/Y scale and Auto/Custom limits), but the Y axis is the dimensionless growth factor rather than Qpeak. A dashed horizontal line at growth = 1 is always drawn (marking the reference event), and Auto Y limits keep it in view. |
| **Export** | Same as the Flow Comparison tab, saving the growth-curve chart/data instead. |

**How the growth factor is calculated:** for each ticked curve, the tool
looks for a data point at *exactly* the reference AEP (within floating-
point rounding) and divides every point on that curve by the Qpeak at
that point. **No interpolation is performed.** If a curve has no data
point at the reference AEP, it isn't plotted — instead it's listed in a
note above the chart (e.g. "*Not plotted (no data point at 1 in 10):
FFA: LP3*"), so you always know which curves were left out and why. Add
a row at that AEP for the method/variant in question if you want it
included.

## Formatting the input spreadsheet
The sheet you point the tool at (any name — you choose it at startup)
needs these five column headers in row 1 (order doesn't matter):

| Location | AEP (1 in X) | Qpeak (m3/s) | Method | Variant |
|---|---|---|---|---|
| M3 | 1 | 32.4677 | RORB | m3_PL_areal_tp01 |
| 707002 | 100 | 8763.2 | FFA | LP3 |

- **One row per data point** (one Location + Method + Variant + AEP combination).
- `Location`, `Method`, `Variant` can be any text or number — they're
  treated as labels (e.g. a gauge ID like `707002` is fine).
- `AEP (1 in X)` and `Qpeak (m3/s)` must be numeric.
- Blank cells in any of these five columns → that row is skipped automatically.
- A variant named **Observed** (or Obs/Gauged/Recorded, case-insensitive)
  is drawn as markers only, no line — use this for empirical/gauged points
  as distinct from a fitted distribution curve. It still needs a row at
  the reference AEP to appear on the Growth Curves tab.
- Add new rows, locations, methods, or variants any time — no code
  changes needed, the tool reads whatever's currently in the sheet. The
  Growth Curves tab is computed live from this same data, so there's no
  separate sheet or column to maintain for it.

An extra sheet (e.g. `Sources`) can exist for your own traceability —
you'll just see it as another option in the sheet-picker dialog and can
ignore it by picking your actual data sheet instead.
