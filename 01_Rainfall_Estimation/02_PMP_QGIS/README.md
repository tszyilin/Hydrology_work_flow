# PMP Toolbox

A QGIS plugin that estimates **Probable Maximum Precipitation** for a catchment
polygon, following the Bureau of Meteorology's generalised methods.

The point of doing this in QGIS is that the catchment is already open. Area,
centroid, moisture adjustment, duration limit, PMP zone and the extreme
precipitable water, topographic and decay factors are all derivable from the
polygon, and every one of them is otherwise read off a map by eye and retyped.
The plugin derives them, and — because a number that appears in a box by itself
is a number nobody can check — shows where each one came from and lets you type
over it.

Three tabs, in one floating dock:

| Tab | Method | Durations | Output |
|---|---|---|---|
| **GSDM** | Generalised Short-Duration Method | 0.25–6 hr | Catchment-average depth against duration, beside the point value |
| **Areal GSDM** | GSDM section 6 | 0.25–6 hr | The design *spatial distribution*: the Figure 6 storm template placed by optimisation, and a depth per ring |
| **GTSMR / GSAM** | Generalised Tropical Storm Method Revised, and Generalised Southeast Australia Method | 24–120 hr | Depth against duration for each applicable method and season |

## Installation

Copy or symlink `pmp_toolbox/` into your QGIS plugin directory:

```
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
```

Then enable **PMP Toolbox** in Plugins → Manage and Install Plugins. Requires
QGIS 3.28+ and numpy (bundled with QGIS). Nothing else — the calculation reads
its tables with the standard library, deliberately, because QGIS does not
reliably ship pandas.

The toolbar button toggles the dock. It floats by default; the tabs are wider
than a comfortable docked panel.

### Uninstalling, and why it used to fail

If a version before 0.7.2 is installed, uninstalling it reports:

```
Failed to remove the directory: .../python/plugins/pmp_toolbox
Check permissions or remove it manually
```

That is a file lock, not a permissions problem. `core.grids` read the EPW/TAF/
DAF archive with `np.load(...)`, which returns a lazily-loading `NpzFile` that
keeps the archive **open** until closed — and holding it in a module global kept
the handle open for the whole QGIS session. Windows will not delete a directory
containing an open file.

Fixed in 0.7.2 by reading the arrays inside a `with` block. To clear a stuck
install: close QGIS, delete the `pmp_toolbox` folder by hand, start QGIS and
install the new ZIP.

The bug came in with the code vendored from the Toolbox website, where it is
harmless — a server process never uninstalls itself. `test_no_file_locks.py`
now copies the package, imports it, and tries to delete it, because nothing
inside the plugin can notice this for itself.

### Restart QGIS after installing

**Install from ZIP, then restart QGIS** — always, not only the first time.

Installing over a running QGIS can leave this in the log:

```
AttributeError: module 'pmp_toolbox' has no attribute 'classFactory'
```

That is not a broken download. QGIS creates the plugin folder and then extracts
into it; for the moment before `__init__.py` lands, `pmp_toolbox` looks to
Python like a *namespace package* — a module with no attributes at all. If
anything imports the name in that window, `sys.modules` keeps the empty module
for the rest of the session, and every later load finds nothing in it. The
`AttributeError` rather than an `ImportError` is the tell.

Restarting clears it. The same caching is why the version sits in the dock
title: an already-imported module is not replaced by a reinstall until QGIS
starts again, so `PMP Toolbox v0.7.0` is how you confirm which build is
actually loaded.

## The catchment

Every tab's inputs column starts with the same picker: a polygon layer,
optionally restricted to the selected features, dissolved to one geometry. It
reports the area, the centroid in degrees, and the CRS. The catchment is an
input like any other, which is why it sits with the inputs rather than in a
band across the top — the top belongs to the project row.

**The layer must be in a projected CRS in metres** (e.g. an MGA zone). The
plugin refuses a geographic CRS rather than silently computing areas in square
degrees — on all three tabs, from one place, so the refusal cannot drift.

Past 2,000 features the automatic lookups go quiet, because finding a centroid
means dissolving them all. The **From centroid** buttons still work.

## Layout, and cases

The dock is a project row over three tabs, and every tab is laid out the same
way, following the Drain Design Toolbox:

```
Project   name · path ·············· [Open project] [Save] [Save As]
+-- GSDM --+-- Areal GSDM --+-- GTSMR / GSAM --------------------------+
| +------- vertical splitter ---------------------------------------+ |
| | Cases | catchment      | methods    | results table             | |
| |       | + inputs       | (GTSMR     |                           | |
| |       |   (scrolls)    |  only)     |                           | |
| |       | ---------------|            |                           | |
| |       | Calculate  All |            |                           | |
| |       | Export CSV Copy|            |                           | |
| +------------------------------------------------------------------+ |
| |  plot tabs, each with its own Export CSV / Copy                  | |
| +------------------------------------------------------------------+ |
+----------------------------------------------------------------------+
```

The columns are a **draggable splitter**: only the results pane grows when you
widen the dock, and none of them can be collapsed to nothing.

The Calculate and export buttons sit at the **foot of the inputs pane**, under
the parameters they act on, so a tab reads downwards in the order the work
happens: pick a catchment, set the inputs, press the button. They are pinned
*outside* the scrolling part — inside it, a tall form put Calculate below the
fold, which is the one control nobody should have to hunt for.

GTSMR carries a **third column** for its two method blocks. Eleven editable
numbers across two guidebooks, stacked under the catchment and the sampled
values, had made that column a scroll-hunt; beside it, everything fits.

**Cases** are independent runs. Each keeps its own catchment, its own inputs
*and its own results*, so switching between them restores exactly what you saw.
Add one with **+** — it starts from the current case's inputs, because the usual
reason to add one is to vary a single parameter. Drag to reorder, double-click
to rename, and a tick beside the name means it has been calculated.

Every tab's plot panel carries two views: the current case, and an **All cases**
overlay of every case that has been calculated. That comparison is what cases
are for — the same catchment at two durations, or two terrain splits, read off
one chart. Both views export their own numbers, and the All-cases export is a
row per duration and a column per case, which is the shape you want to paste
into a report.

**Calculate all cases** re-runs every case in turn. On the Areal GSDM tab it is
labelled **Run all cases** and is genuinely expensive — each case is a full
placement search — so it runs without opening the preview window.

## The project file

**Save As** writes the whole job — every tab, every case — to one `.xlsx`, and
**Open project** reads it back. One job is one file, because a PMP estimate is
rarely a single run and the three methods belong to the same catchment.

| Sheet | Holds |
|---|---|
| `Summary` | One row per case across all three tabs: the layer, area, centroid, whether it has been calculated, and its headline result. |
| `<tab> Inputs` | One row per case, a column per input. This is the sheet reopening reads. |
| `<tab> Results` | Each calculated case's result table, followed by its **Run inputs** block. |

Three details worth knowing:

- **Results are not read back.** They are output. Reopening restores the inputs
  and clears the results, and the message bar says to press Calculate. A
  workbook someone has edited must not be able to put numbers on screen that no
  calculation produced.
- **The catchment layer is stored by name** and resolved against whatever is
  open when the file is read. If that layer is not loaded the case keeps every
  other input and you repick the layer, rather than the open failing.
- **Opening replaces the cases**, it does not merge. Opening a project means
  that project, not that project plus whatever was on screen.

Saving and opening need `openpyxl`, which QGIS does not bundle. Without it the
buttons explain how to install it and everything else — including each tab's
CSV export — carries on working.

Values are labelled at each point on the depth-duration plots. Where labels
would collide on the flat part of a curve some are dropped; the table beside
the plot always has every number.

---

## Tab: GSDM

Catchment-average PMP depth for storms of 0.25 to 6 hours, over catchments up to
1000 km².

| Input | Where it comes from |
|---|---|
| Duration limit | GSDM Figure 2, read at the centroid. In the intermediate band between the three-hour and six-hour zones **both** are offered rather than one being chosen for you. |
| Terrain | Smooth/rough split, areally weighted (§4.2). Defaults to **0% smooth / 100% rough**, matching the Toolbox website and the PSM6186 worked examples — rough is the conservative half, so defaulting to smooth would quietly under-report. Irrelevant below 1 hour: the curves coincide. |
| MAF | Figure 3, read at the centroid from contours digitised from the Bureau's vector PDF. The note beside it gives the coordinates and the two contours the value falls between. |
| EAF | From a mean elevation by §4.3: 1.0 up to 1500 m, then −0.05 per 300 m, floor 0.85. |

The table gives the areal depth at each tabulated duration, the **point** depth
beside it, and their ratio. The point value is a single extra lookup and it is
the number most often wanted for comparison: seeing how far the areal depth has
fallen below it is the clearest statement of what areal reduction is doing. The
controlling duration is highlighted, and the summary carries the storm volume.

No layers are added — this tab answers a depth question, not a spatial one.

---

## Tab: Areal GSDM

This is GSDM section 6, and it is the part of the Bulletin that most resists
being done by hand.

Step 1 asks an analyst to overlay the Figure 6 storm template on a catchment map
and shuffle it about "to obtain the best fit by the smallest possible ellipse".
That is subjective, slow, and hard to reproduce. Here it is an explicit
optimisation, carried through Steps 2–9 to the design spatial distribution.

### How the placement is chosen

Ten nested ellipses (A–J) are positioned by three parameters: the template
centre `(cx, cy)` and its rotation `θ`. The objective is lexicographic:

1. **Minimise `k`**, the smallest ellipse that fully contains the catchment.
   This is the Bulletin's own criterion and a hard constraint.
2. **Among placements achieving that `k`, maximise** `Σ wᵢ · CBtnᵢ`, where
   `CBtnᵢ` is the catchment area in the annulus between ellipse `i-1` and `i`.

Weights descend from A to J, so the score rewards packing catchment area into
the inner, wetter ellipses. They default to the Table 2 mean rainfall depths for
the chosen duration and terrain, making the score a storm depth in mm·km².

### Why the weights are frozen during the search

Tempting as it is to recompute the true GSDM depths for each candidate
placement, doing so makes the objective **degenerate**. Volumes telescope:

```
Σ VBtnᵢ  =  VEnc_k  =  AMRD_k × catchment_area
```

which is identical for every placement sharing the same outermost ellipse `k`.
A recomputed objective cannot tell two placements apart. So the profile is
computed once (under the full-fill assumption `CEncᵢ == Areaᵢ`) and held fixed,
keeping "inner rings are worth more millimetres" as a real gradient. The exact
per-placement GSDM depths are recomputed by `gsdm.distribute` once the optimum
is found.

### How the search stays fast

The catchment polygon is sampled **once** into points on a regular grid, using
real point-in-polygon tests. Because all ten ellipses share a centre, an
orientation and a constant axis ratio, squashing the major axis turns them into
nested circles — so a single normalised radius per point classifies it into its
ring via `searchsorted`. Scoring a candidate is O(N) numpy with no geometry
calls; `k` falls out as `max(ring index)`.

A coarse sweep over translation and rotation is followed by pattern search from
the best few seeds, both anchored on the centroid of the sampled area.

Nothing about this is raster GIS: the points are never written, never form a
layer, and carry no values. Vector goes in and vector comes out. Once the search
picks a placement, the reported areas are recomputed exactly by intersecting the
catchment polygon with each ellipse — the sample points only steer the search,
they never set the numbers.

### Inputs and outputs

| Input | Notes |
|---|---|
| Duration | 0.25–6 hours. §4.1 caps this at 3 hr inland/southern and 6 hr on the tropical coast; the GSDM tab reads that cap off Figure 2. |
| Terrain, MAF, elevation | As the GSDM tab. |
| Search sampling | Metres between the sample points used to compare candidate placements. Closer is slower and makes the choice more reliable; it **cannot change the reported areas**. The count is shown as you set it, and a spacing needing more than 500,000 points is refused. |
| Rotation steps | Across a half turn; 12 steps is 15° apart. |
| Ring weights | Auto-filled from Table 2, and **locked** until you unlock them. |

Outputs two layers — the ellipse outlines and the rings clipped to the catchment
and graduated on `MRD` — plus a results table mirroring Bulletin Table A2.2.

The plot panel shows mean rainfall depth per ring as bars, coloured by ring
position in the same ramp the rainfall layer is drawn in, so the chart and the
map agree at a glance. With more than one case the **All cases** view groups
the bars per ring, which is the clearest way to see what changing the duration
or the terrain split does to the distribution.

### Watching the search

The Bulletin's "shuffle it about by hand" is a visible act; the optimisation
that replaces it need not be a black box. A separate preview window shows the
catchment holding still while the template sweeps and rotates through candidate
placements, the best so far ghosted behind the current one, with the trial
count, the enclosing ellipse and the running score.

When the search ends the window **replays the whole thing from the first trial**
— the coarse sweep, then the handover to the pattern-search refinement — and
settles on the chosen placement with the rings shaded and labelled by `MRD`, the
same numbers and colour ramp as the layers added to the map. By then the results
table and the layers are already there, so the replay costs nothing but the
watching.

- **Replay the whole search when it finishes** and the seconds beside it: a
  replay takes about that long whatever the trial count — a ten-thousand-trial
  search simply skips more per frame. Untick to land on the result at once.
- **Replay / slider / Final result** — replay again, scrub by hand to any trial,
  or jump to the answer.
- **Pause / Cancel** — cancelling abandons the run cleanly; no layers are added.
  Closing the window mid-search does the same.
- **fps** and **Run at full speed** control redraw only, never the search. At
  full speed nothing is drawn during the search, every trial is still recorded,
  and the replay afterwards shows you what you missed.

The view frames itself on the best placement's enclosing ellipse, so it tightens
a few times as the search improves and then holds still. Candidates flung clear
of the catchment do not reframe it. Drawing costs a few percent of the run at 20
fps; unticking **Preview** removes the observer entirely.

### The ring weights are locked

The ten weights are read off Table 2 for the chosen duration and terrain, and
are **read-only until unlocked**, the same as the GTSMR grid fields.

They are the sharpest case for a lock in the plugin, because they do not appear
in the result at all. They decide *which placement the search picks*; the ring
depths are then recomputed exactly from that placement. A mistyped weight
therefore changes the answer while leaving nothing on screen that looks wrong.

While locked they track their inputs — change the duration or the terrain split
and they refill. Once unlocked they are yours, and a duration change no longer
overwrites them; **Reset to GSDM depths** puts Table 2 back at any time.

The lock is remembered per case and saved in the project file.

### A caveat worth knowing: thin rings

Step 8 computes `MRDᵢ = VBtnᵢ / CBtnᵢ` — a difference of large enclosed volumes
divided by a small ring area. It therefore **amplifies any depth error by
roughly `CEncᵢ / CBtnᵢ`**. In the Bulletin's own worked example, ring E holds
13.7 of 110 km², so a 1 mm misread of Figure 4 moves that ring's mapped depth by
4.6 mm. For the same reason, two placements scoring within a fraction of a
percent of each other can put visibly different depths on a thin outer ring.

The plugin handles this in three ways: it reproduces the Bulletin's
whole-millimetre rounding of `IMRD` and `AMRD` by default
(`Inputs.round_intermediates`), it warns whenever `CEncᵢ / CBtnᵢ` exceeds 5, and
its tests assert stability only for rings holding at least 5% of the catchment.
Treat a flagged outer ring's depth as indicative.

---

## Tab: GTSMR / GSAM

The long-duration methods, 24 to 120 hours.

**Which method applies is a matter of where the catchment is**, so the zone
lookup drives the tab: a method whose zone the centroid does not fall in is
disabled rather than left available to be run wrongly, and the lookup's notes
are shown verbatim.

That refusal to guess goes further than the interface. The GTSMR **inland zone
has no winter equivalent**. Rather than substituting the coastal winter zone —
which would invent a winter PMP for a catchment nowhere near the coast — that
season is left out, and the table says so with a dash and a warning.

### The GTSMR numbers are locked

Six GTSMR inputs — EPW summer and winter, both standards, TAF and DAF — are
**read-only until you unlock them**. Four come off the Bureau's grids at the
catchment centroid and two are guidebook constants; none is an opinion, and
left as ordinary spin boxes a stray scroll wheel can move a PMP by a hundred
millimetres with nothing on screen to say it happened. The Toolbox website
locks the same six.

**🔒 Unlock to override** frees them, and says so plainly while they are free.
The lock is not a claim the values cannot be improved — §2.3.1 actually asks
for an EPW averaged over the catchment outline rather than read at the
centroid, and that is exactly the case the unlock exists for. Resampling
refills a locked field without unlocking it, because locked means "the
Bureau's number", not "frozen".

The lock is remembered per case and saved in the project file: whether a number
was the Bureau's or yours is part of the job.

GSAM is deliberately **not** locked. Its autumn EPW is seeded from the winter
grid because the shipped grids carry no autumn layer, so it is a stand-in that
has to be checked by hand — locking it would lock in a value the plugin does
not stand behind.

| Input | Notes |
|---|---|
| EPW summer / winter / autumn | Sampled from the Bureau's grids at the centroid. |
| EPW standards | **GTSMR uses 120.0 mm summer and 82.3 mm winter** (§2.3.1); **GSAM uses 80.8 mm summer and 71.0 mm autumn** (§2.3). Carrying one guidebook's pair across to the other is an easy mistake, so each method carries its own and a test asserts the defaults. |
| TAF | Topographic adjustment factor, sampled. |
| DAF | Decay amplitude factor — **GTSMR only**. GSAM has none. |

The moisture adjustment is the catchment EPW over the standard EPW, computed per
season and shown as you edit the fields it comes from.

### Centroid, not catchment average

The guidebook averages EPW, TAF and DAF over the catchment outline. This samples
them at the centroid, which is what the worked spreadsheets do — and against
`01_PMP/PSM6186_examples.xlsx` the sampled values reproduce the job's own
readings of the full-resolution grids to within **0.03%**, giving identical
rounded depths. The choice is stated on the tab rather than buried here, and
every field is editable, so a catchment-average value can be entered by hand.

---

## Exports

Every tab exports CSV and copies TSV to the clipboard. The result table comes
first, then an appended **Run inputs** block recording the layer, the area, the
centroid, and every factor *with its provenance*.

This is not padding. The same rings under a different MAF are a different PMP,
so a depth table on its own cannot be checked. The block is appended rather than
prepended so the table stays on row 1 for anything already reading these files,
and it records the run as it happened — changing a spin box afterwards does not
rewrite it.

## Data provenance

| File | Source |
|---|---|
| `data/dda_gsdm.csv` | The digitised Figure 4 envelope curves, 11 durations × 2 terrains × 28 area breakpoints, plus a point row per curve. Built by `tools/build_data.py` from sheet `Raw data` of `GSDM/GSDM_Depth_Area_Curves_Digitise.xlsx`; vendored byte-identical from the Toolbox website project. |
| `data/table2.csv` | Transcribed from Table 2 of `GSDM/GSDM.pdf` (8 ellipses × 11 durations × 2 terrains). Ellipses I and J are absent from the Bulletin — their areas exceed the 1000 km² limit of the DDA curves. |
| `data/gsdm_maf.json` | GSDM Figure 3 moisture adjustment contours, digitised from the Bureau's vector PDF: 148 polylines, 6,492 vertices, values 0.50–1.15. |
| `data/gsdm_duration.json` | GSDM Figure 2 duration-limit boundaries, traced from the printed dashes and registered onto Figure 3's Albers grid. |
| `data/dda_gtsmr.csv`, `data/dda_gsam.csv` | The GTSMR and GSAM depth-area tables, from the Bureau's GTSMR CD (September 2005). |
| `data/gtsmr_grids.npz`, `meta.json` | The CD's four continental grids — annual and winter EPW, TAF, DAF — resampled from 0.005° to 0.05° and quantised: 1.1 MB in place of 1.7 GB of ASCII. |
| `data/zones_all.json` | PMP application zones, simplified (~0.9 km, islands under 40 km² dropped) from the CD's `pmp_zones/zones_all.shp`. |

Everything except `table2.csv` is **vendored from the Toolbox website project**
(`18_Toolbox_website/backend/calculators/`), which is where the digitising and
resampling were done, along with the modules that read them — so a fix in either
can be carried across. `test_depth_parity.py` is what keeps the two honest.

The ellipse template is **generated parametrically**, not loaded from
`GSDM/Shapefiles/ellipses_all_*_28350.shp`. That shapefile's ten ellipses are
not concentric — successive centres step ~600 m along the major axis, leaving A
and J about 5 km apart — and it is in EPSG:28350 while catchment data usually is
not. All ten are exactly determined by their area and a constant axis ratio of
1.2217, so they are rebuilt about a common centre in the catchment's own CRS.
The shapefile is retained as the QA fixture that `test_ellipses.py` checks the
generated areas against.

Note also that the shapefile's records are **not** in A–J order.

## Layout

```
pmp_toolbox/
  plugin.py        Toolbar action, dock, project row, tabs
  workbook.py      The .xlsx project: save, and read back
  qt_compat.py     Qt import shim, so tabs build with or without QGIS
  qgis_bridge.py   Catchment dissolve, rasterise, output layers
  preview.py       The live search window; Qt only, no qgis.core
  styling.py       Renderers and labels
  palette.py       The rainfall ramp, shared by styling and preview
  style/           buttons.qss -- applied per widget, never app-wide
  core/            pure Python; imports no QGIS
    dda.py         GSDM Figure 4 curves, Table 2, and the generic area-depth table
    depth.py       Catchment-average GSDM, GTSMR and GSAM
    gsdm.py        Steps 2-9, EAF, the frozen weight profile
    ellipses.py    Parametric A-J template; the O(N) ring classifier
    optimiser.py   Rasterise, score, coarse sweep, pattern-search refinement
    maf.py         Figure 3 moisture adjustment
    duration.py    Figure 2 duration limit
    zones.py       PMP application zones
    grids.py       EPW / TAF / DAF grid sampling
    projection.py  The Albers sheet Figures 2 and 3 share
  tabs/
    common.py      Catchment picker, derived fields, case sidebar, plot panel,
                   project row, the shared layout shell, tables and exports
    gsdm_tab.py  areal_gsdm_tab.py  gtsmr_tab.py
  data/
  test/
tools/build_data.py
```

Nothing under `core/` imports QGIS, so the whole calculation is testable with
plain Python.

## Tests

Calculation only, no QGIS needed — the QGIS-dependent files skip:

```bash
python -m pytest pmp_toolbox/test -q
```

Everything, including the tabs, the end-to-end runs on the example catchments
and the plugin's own run path:

```bash
"C:\Program Files\QGIS 3.44.11\bin\python-qgis-ltr.bat" -m pytest pmp_toolbox/test -q
```

Three fixtures carry most of the weight:

**Bulletin GSDM Appendix 2.2, Table A2.2** — a 110 km² catchment, 3-hour PMP,
10% smooth / 90% rough, EAF 0.96, MAF 0.60, best fit ellipse E, column h =
507 / 447 / 393 / 358 / 340 mm. Steps 5–8 reproduce it exactly.

Step 4 is checked separately, within a stated ±2 mm digitisation tolerance: our
curves give 586.0/731.5 mm at 53.7 km² where the Bulletin's author read 585/731
off the same printed graph. Demanding an exact match on column h from the
digitised curves would be overfitting to one person's eye.

**`01_PMP/PSM6186_examples.xlsx`** — two real catchments near Kalgoorlie carried
through GSDM and GTSMR by hand in a spreadsheet. All 46 rounded depths are
reproduced exactly, and the grid factors sampled at their centroids match the
job's own readings to within 0.03%. Produced independently of this code and of
the Toolbox website, which is what makes it worth having.

**Parity with the Toolbox website** — `core.depth` is run side by side with
`backend/calculators/pmp.calculate()` over a spread of areas and parameter sets
and asserted equal to the millimetre. This is what catches a slip in the
pandas→csv port. It needs pandas, so it skips under the QGIS interpreter and is
expected to run under a plain Python.

Agreeing on the arithmetic is not the same as agreeing on the answer, though.
What a user sees also depends on what the form is set to when it opens, so the
**defaults** are pinned too: `TestWebsiteDefaults` asserts the terrain split
matches the website on both GSDM tabs, and runs the GSDM tab end to end against
the website's own `calculate()` on a real catchment. Without that, a tab
defaulting to smooth terrain would disagree with the website by about a quarter
on every catchment while every parity test still passed — which is exactly what
happened.
