# QGIS Plugin: Wind Fetch Calculator — Claude Code Prompt

Build a QGIS Python plugin that automatically calculates wind fetch distances from an embankment point in all directions. This is used in dam/TSF (Tailings Storage Facility) design to determine the maximum wind fetch for wave run-up calculations.

---

## Purpose

Given a point on an embankment crest and a water polygon (reservoir or TSF pond), calculate the fetch distance in multiple wind directions (every 3° or user-defined interval). The longest fetch in the critical wind direction is used for wave height and run-up design per ANCOLD guidelines.

---

## Workflow to Automate (Step by Step)

### Step 1 — User Inputs
- A **point layer** (single point on the embankment crest — the reference location)
- A **polygon layer** representing the water body (reservoir / TSF pond)
- **Fetch radius** (m) — default 2000 m; must be large enough to cover the entire water body
- **Angular interval** (degrees) — default 3°; controls how many directions are sampled
- **Output layer name** — for the fetch lines result

### Step 2 — Generate Circle Points
Use `native:pointsalonglines` on a circle geometry centred on the embankment point:

- Create a circle feature centred on the input point with the specified radius
- Run **Processing → Points along geometry** with distance = `radius × 2 × π × (interval_deg / 360)`
  - Example: radius=2000m, interval=3° → spacing = `2000 × 2 × π × (3/360)` = 104.72 m
- This produces evenly-spaced points around the full 360° circle

### Step 3 — Draw Lines from Circle Points to Embankment Point
Use `native:shortestline` (Shortest line between features):
- Source layer: the circle points from Step 2
- Destination layer: the embankment point
- This draws a straight line from each circle point back to the embankment point

### Step 4 — Clip Lines to Water Polygon
Use `native:clip` to clip the fetch lines to the water body polygon:
- Only the portion of each line that passes over water represents actual fetch
- Lines that don't intersect the water body get clipped to zero / removed

### Step 5 — Calculate Line Lengths
Use the field calculator to add a field `fetch_m` = `$length` (in map units, metres)

### Step 6 — Output
- Load the clipped fetch lines layer into QGIS with `fetch_m` attribute
- Label or colour lines by fetch length
- Print a summary: **maximum fetch distance** and the **bearing (°)** it occurs at

---

## Plugin UI Requirements

Simple dialog with:
- **Embankment point layer** — dropdown (populated from loaded point layers)
- **Water body polygon layer** — dropdown (populated from loaded polygon layers)
- **Fetch radius (m)** — spin box, default 2000
- **Angular interval (°)** — spin box, default 3
- **Output layer name** — text field, default "Wind_Fetch"
- **Run** button
- **Results summary** text box showing: max fetch (m), bearing of max fetch (°)

---

## Technical Requirements

- Python, PyQGIS, QGIS processing framework (`processing.run()`)
- Compatible with QGIS 3.x
- Standard QGIS plugin structure:

```
wind_fetch/
├── __init__.py
├── metadata.txt
├── wind_fetch.py          # Main plugin class
├── wind_fetch_dialog.py   # Dialog logic
├── wind_fetch_dialog.ui   # Qt UI file (XML)
└── icon.png               # Placeholder icon
```

- Use `QgsProject.instance().mapLayers()` to populate layer dropdowns
- Filter dropdowns by geometry type (point layers for embankment, polygon layers for water body)
- Use `processing.run()` calls for all geoprocessing steps:
  - `native:buffer` or geometry generator to create the circle
  - `native:pointsalonglines` for circle point generation
  - `native:shortestline` for fetch lines
  - `native:clip` to clip to water body
  - Field calculator via `QgsField` + `QgsExpression` for `$length`

### Key Formula
```
arc_spacing_m = radius_m × 2 × π × (interval_deg / 360)
```

### Bearing Calculation
After generating lines, calculate the bearing of each line from the embankment point:
```python
import math
bearing = math.degrees(math.atan2(dx, dy)) % 360
```

---

## Deliverable

Installable QGIS plugin — zip the `wind_fetch/` folder and load via:
**Plugins → Manage and Install Plugins → Install from ZIP**

---

## Example Use Case

- TSF embankment at a mine site
- Reservoir radius ~1500 m
- Run with 3° interval → 120 fetch lines
- Max fetch = 1380 m at bearing 285° (WSW)
- Use this fetch distance in ANCOLD wave run-up formula to size freeboard
