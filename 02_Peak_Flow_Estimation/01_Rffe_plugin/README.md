# RFFE Query — QGIS plugin

Runs the **RFFE 2021** regional flood frequency model
(https://rffe-2021.wmawater.com.au/) without leaving QGIS. Pick the catchment outlet
and centroid on the map, enter the area, and get design flood estimates plus the
gauged station data behind them, loaded straight into the project.

## Install

Copy the `rffe_plugin` folder into your QGIS profile plugins directory:

```
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\rffe_plugin
```

Then **Plugins → Manage and Install Plugins → Installed** and tick **RFFE Query**.
(Already installed on this machine.)

Requires QGIS 3.22+ and an internet connection. No login, API key or extra Python
packages — it uses only what QGIS already ships.

## Use

1. Click the **RFFE Query** toolbar button.
2. **Outlet** — press *Pick on map* and click the catchment outlet. Works in any
   project CRS; the click is transformed to WGS84 for you.
3. **Centroid** — leave *Derive centroid automatically* ticked, or untick it and
   pick the centroid the same way.
4. **Area** — enter the real catchment area. This genuinely changes the result
   (see Notes), so don't leave it at the default.
5. **Output folder** — optional. If set, CSV/JSON and GeoPackage layers are written
   there; if blank, layers are created in memory only.
6. **Run RFFE.**

The query runs on a background thread, so QGIS stays responsive.

## What you get

**In the dialog** — the recommended model's flows for the 50%, 20%, 10%, 5%, 2% and
1% AEPs with 90% confidence limits, plus the basin, region and station count.

**Layers added to the project:**

| Layer | Contents |
|-------|----------|
| `<name> catchment` | the fitted catchment polygon, with area, basin and region |
| `<name> points` | outlet and centroid; the outlet carries the recommended model's flows |
| `<name> gauges` | the gauged stations the regional models were fitted from |

With no output folder set these are **scratch (memory) layers** — nothing is written to
disk, and they disappear when the project closes unless you save them. Set an output
folder to get GeoPackages instead.

The gauges layer is styled so the two things that decide how much a gauge supports your
estimate read at a glance, each on its own visual channel:

- **Shape — catchment size.** A **circle** means the gauge catchment is within half to
  double your site's area; a **triangle** means it is not (or has no usable area). The
  ratio is also carried as fields: `Area_Ratio` (gauge area ÷ site area) and
  `Size_Class` (`comparable` / `smaller` / `larger` / `unknown`), so you can filter on
  them directly.
- **Colour — distance.** Green under 100 km through to red beyond 1000 km.

Labelled with the station name. Stations serving more than one region appear once, with
`Region_ID` listing each region they belong to (e.g. `6, 7`).

A QGIS legend can only show one shape per class, so it will draw every distance class as
a circle. The shape rule is recorded in the layer's Abstract (Layer Properties →
Information) as a reminder. To see the split explicitly, filter or categorise on
`Size_Class`.

The half-to-double band is set by `SIZE_TOLERANCE` in `core/rffe_output.py` — change that
one constant if you want a tighter or looser definition of "comparable".

**Files written** (when an output folder is set): `_results.csv` (all three models,
every AEP, with confidence limits), `_stations.csv` (the full ~89-column regional
dataset), and a `.json` with everything including the site predictors.

## Opening the RFFE website

**Open RFFE website** launches the site in your browser and copies the current outlet,
centroid and area to the clipboard.

It cannot pre-fill them. The RFFE app has no `dcc.Location` component and no callback
reads the query string, so it ignores URL parameters entirely and always loads at its
default Sydney catchment — verified by fetching the layout with parameters attached and
getting the defaults back. Pasting from the clipboard is the closest thing available;
use it when you want to cross-check the plugin's numbers against the website by hand.

### Why the gauges layer matters

The gauges are the observed data your estimate is extrapolated from. Load them and
check `Dist km`, `Record Length` and `Area_Ratio` against your own catchment — if the
nearest gauges are hundreds of kilometres away, short-record, or orders of magnitude
larger than your catchment, the estimate is poorly constrained no matter how precise
the numbers look.

A map showing mostly far-away triangles is telling you the regression is extrapolating
well outside the data it was fitted to. That is common in arid and sparsely gauged
regions, and it is exactly when the three models diverge most.

## Notes and limitations

- **Area drives the result.** The website approximates the catchment as an ellipse
  built from outlet, centroid and area. The same coordinates with a different area
  give different flows.
- **The outlet must sit on a mapped watercourse** within Australia. If it doesn't,
  the service returns HTTP 500 and the plugin reports that the site was rejected.
- **The three models can disagree sharply** in arid and sparsely gauged regions. The
  plugin shows the recommended model; the full set is in the CSV and JSON.
- **The RFFE website's own dataset zip download is broken server-side** (HTTP 500 when
  building the zip). The regional station data is recovered through a different
  callback, but the catchment/stream-network **shapefiles and map PNGs only ever ship
  inside that zip**, so those are unavailable — through this plugin or the website.
  The catchment polygon layer here is the one returned by the map callback, which is
  the same ellipse the model actually used.

## Structure

```
core/rffe_client.py   HTTP client for the Dash callback API (no Qt/QGIS imports)
core/rffe_output.py   CSV/JSON writers and QGIS layer construction
gui/pick_tool.py      canvas map tool for picking points, with CRS transform
gui/rffe_dialog.py    the dialog; runs queries on a background thread
```

`core/rffe_client.py` is standalone and can be imported outside QGIS — useful for
testing or batch work.

Two things that are easy to get wrong if you extend this:

1. Cloudflare returns **403** to Python's default user-agent, so the client presents a
   browser user-agent.
2. The "Run RFFE" callback takes the catchment polygon as *state*. Sending the page's
   default polygon works only for the site's default Sydney coordinates and returns
   **500** everywhere else, so the client calls the map-sync callback first to build a
   polygon for the actual location.

Since this rides the site's internal API rather than a published one, a redesign of the
website could break it. If it starts failing everywhere, re-check the callback
signatures at `/_dash-dependencies`.

## Related

For running many catchments at once from a spreadsheet, see the batch script in
`Desktop\RFFE Auto Extraction`.
