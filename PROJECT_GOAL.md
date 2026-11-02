# QGIS Hydrology Workflow — Project Goal

## Main goal

Build a **QGIS plugin suite for catchment hydrology**, made up of **three plugins**
that mirror the three stages of a design-flood assessment. Each stage lives in its
own top-level sub-folder of this repository, and each sub-folder is the
source-of-truth for one plugin.

| # | Sub-folder | Plugin | Stage of the workflow |
|---|------------|--------|-----------------------|
| 1 | `01_Rainfall_Estimation` | **Rainfall Estimation** | Design rainfall depths / IFD inputs for a catchment |
| 2 | `02_Peak_Flow_Estimation` | **Peak Flow Toolbox** | Peak-flow estimates from RFFE, ARR regional methods and RORB |
| 3 | `03_Check` | **Hydrology Checks** | Independent sanity checks on the estimated flows |

The three plugins share a common look, a common Qt import shim (`qt_compat.py`),
and a common project-file convention, so a user can move from rainfall → peak flow
→ check without leaving QGIS.

## Stage 1 — Rainfall Estimation (`01_Rainfall_Estimation`)

**Status: not started — folder is currently empty.**

Intended scope: derive design rainfall for a catchment polygon — BoM IFD 2016
depths, areal reduction, temporal patterns and pre-burst — and hand the result to
Stage 2. A placeholder module is already wired into the suite so the tab appears
and the plumbing can be tested before the hydrology is implemented.

## Stage 2 — Peak Flow Estimation (`02_Peak_Flow_Estimation`)

**Status: working — the most complete part of the project.**

`Peak_Flow_Toolbox/` is a functioning dockable QGIS plugin that compares peak-flow
estimates across methods for one or more catchment "cases":

- **RFFE** — queries the RFFE 2021 web service (`rffe-2021.wmawater.com.au`) for a
  catchment outlet, via the vendored client in `core/vendor/`.
- **ARR regional methods** — `core/regional_methods/` implements
  ARR 1987 Rational, Flavell (WA), Davies & Yip (WA) and Northfield (NT), with a
  `recommender.py` that suggests which method suits a given catchment.
- **RORB** — `core/rorb_parser.py` imports peak flows from RORB model output.
- **Project I/O** — `xlsx_project.py` saves/loads the whole comparison as `.xlsx`.

Supporting material in the same folder: `01_Rffe_plugin/` (the standalone RFFE
plugin that the toolbox vendors from), `02_Regional_Method_Examples/` (spreadsheet
and paper references for the regional equations) and `03_Example/` (a worked
example catchment, `Catchment_A`).

> **Packaging note:** never zip `01_Rffe_plugin/` — it carries a ~260 MB geology
> shapefile. See `02_Peak_Flow_Estimation/DO_NOT_ZIP_RFFE.md`.

## Stage 3 — Checks (`03_Check`)

**Status: prototype — one standalone Tk script, not yet a QGIS plugin.**

`01_Regime_Flow_Check/regime_flow_gui.py` is a Tkinter tool that overlays a user's
channel geometry (width `B_R`, depth `h_R`, slope `S_R`) onto the regime-flow
reference chart (`01_Main_Plot/main_plot.png`) and lets the user drop vertical
Q markers to read off a discharge. It is the first of what is expected to become a
family of checks; the plugin is therefore named **Hydrology Checks** rather than
after this one test.

Port work required: replace Tkinter with Qt, and replace the hard-coded absolute
`IMAGE_PATH` with a path resolved relative to the plugin.

## Delivery approach

The three plugins are developed inside **one suite package**,
`Hydrology_Workflow_Suite`, with one module per stage under `modules/`. This keeps
the shared code in one place and gives a single zip to install and test while the
suite is incomplete. Each module is written so it can be split out into its own
standalone plugin (its own `metadata.txt` + `classFactory`) once the suite is
stable — the module boundary is already the future plugin boundary.

## Target environment

- QGIS 3.16+ (PyQt5), Windows
- Python deps beyond QGIS: `matplotlib`, `numpy`, `openpyxl`, `requests`

## Notes for tools

- **Plotting Tool** (`04_Tools/tools_module/plotting_tool/`) is a standalone
  PyQt5 desktop app launched as a detached subprocess by
  `tools_module/tools_dialog.py::_launch_plotting`. It uses QGIS's bundled
  Python (which ships PyQt5 + matplotlib but **not** tkinter — hence the port
  from the original Tk implementation). Any future standalone tools should
  follow the same pattern (Qt-based, launched via QGIS's Python), matching the
  sibling Drain Design Toolbox.
- **Source of truth vs. plugin copy.** Stage folders under
  `04_Tools/tools_module/` and `01_Rainfall_Runoff/rainfall_runoff_module/`
  are the source of truth. `package.py` mirrors them into
  `Hydrology_Workflow_Suite/modules/<stage>/` before zipping — never edit the
  copies under `Hydrology_Workflow_Suite/modules/` directly; they will be
  overwritten on the next build.
