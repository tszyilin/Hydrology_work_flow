# MDR Curves GUI

Python/Tkinter port of the MATLAB Multi-Day Rainfall (MDR) design-curve pipeline
in `../02_original_scripts/`. Consumes BOM-style daily rainfall CSVs (as in
`../01_Example/01.Input/`) and produces the same four-stage output tree:

```
<output>/
    01.DPPToYPP/         per-year YPP-style matrices + summary XLSX
    02.DoubleMass/       homogeneity check + correction factor + plot
    03.Infilled/         composite gap-filled daily series
    04.MDR/              ranked multiday maxima, curve fit, design curves
```

## Install

```
pip install -r requirements.txt
```

Tkinter ships with CPython on Windows.

## Run

```
python run_gui.py
```

## Layout

- `mdr/io_bom.py`    read BOM CSV → daily `pandas.Series`
- `mdr/ypp.py`       daily → year-per-page monthly/annual summaries
- `mdr/double_mass.py`  double-mass homogeneity check
- `mdr/infill.py`    build composite (gap-filled) daily series
- `mdr/mdr_build.py` ranked partial-series multiday maxima (port of `MDR_Build2012.m`)
- `mdr/curve_fit.py` 6-coefficient MDR curve fit (port of `MDR_DesignCurveFit2022.m`)
- `mdr/design.py`    design rainfall P, excess Pe, outflow Q, critical duration
- `mdr/plotting.py`  matplotlib plots
- `mdr/report.py`    CSV / XLSX / PNG writers
- `mdr/gui/`         Tkinter Notebook tabs

## MDR curve form

```
MDR(D, ARI) = AA + BB * ln(ARI)
    AA = a1 + a2 * (D^a3 - 1)
    BB = a4 + a5 * (D^a6 - 1)
```

Reference fit for the Porgera composite in `01_Example`:
`a = [68.586, 14.324, 0.5906, 33.208, 6.2051, 0.5938]` (Nash-Sutcliffe ≈ 0.99).
