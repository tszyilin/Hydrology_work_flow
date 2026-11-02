"""ARR2019 ARF Calculator — Qt dialog.

Three tabs:
- Single: one region + area/duration/AEP → one ARF value.
- Batch:  CSV in (area, duration, aep, [region]) → CSV out with an
  ``arf`` column appended. Rows that fail validation get an error string
  instead of a number.
- Plot:   ARF vs. duration curve for the selected region/area/AEP,
  rendered on an embedded matplotlib canvas.
"""
from __future__ import annotations

import csv
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .arf_core import (
    AEP_MAX,
    AEP_MIN,
    AREA_MAX,
    AREA_MIN,
    ArfInputError,
    DURATION_MAX,
    DURATION_MIN,
    PARAMS,
    REGIONS,
    arf,
    arf_curve,
)

_RESOURCES = os.path.join(os.path.dirname(__file__), "resources")
_REGIONS_MAP = os.path.join(_RESOURCES, "ARFregions.png")


class ArfDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ARR2019 ARF Calculator")
        self.setMinimumWidth(720)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._build_single_tab(), "Single")
        tabs.addTab(self._build_batch_tab(), "Batch (CSV)")
        tabs.addTab(self._build_plot_tab(), "Plot")
        root.addWidget(tabs)

        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(close)
        root.addLayout(row)

    # ── Single tab ───────────────────────────────────────────────────
    def _build_single_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)

        # Left: inputs + result.
        left = QWidget()
        form = QFormLayout(left)

        self.cmbRegion = QComboBox()
        self.cmbRegion.addItems(REGIONS)
        form.addRow("Region:", self.cmbRegion)

        self.spnArea = _area_spin()
        form.addRow("Area (km²):", self.spnArea)

        self.spnDuration = _duration_spin()
        form.addRow("Duration (min):", self.spnDuration)

        self.spnAep = _aep_spin()
        form.addRow("AEP (%):", self.spnAep)

        btn = QPushButton("Calculate")
        btn.clicked.connect(self._on_single_calc)
        form.addRow(btn)

        self.lblResult = QLabel("—")
        f = self.lblResult.font(); f.setPointSize(f.pointSize() + 4); f.setBold(True)
        self.lblResult.setFont(f)
        form.addRow("ARF:", self.lblResult)

        self.lblSingleError = QLabel("")
        self.lblSingleError.setStyleSheet("color: #a00;")
        self.lblSingleError.setWordWrap(True)
        form.addRow(self.lblSingleError)

        outer.addWidget(left, 1)

        # Right: regions map (falls back to a hint if the PNG is absent).
        outer.addWidget(_regions_image_widget(), 1)
        return page

    def _on_single_calc(self):
        self.lblSingleError.setText("")
        try:
            value = arf(
                area=self.spnArea.value(),
                duration=self.spnDuration.value(),
                aep=self.spnAep.value() / 100.0,
                region=self.cmbRegion.currentText(),
            )
        except ArfInputError as exc:
            self.lblResult.setText("—")
            self.lblSingleError.setText(str(exc))
            return
        self.lblResult.setText(f"{value:.3f}")

    # ── Batch tab ────────────────────────────────────────────────────
    def _build_batch_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        blurb = QLabel(
            "Input CSV columns (case-insensitive): <b>area</b>, <b>duration</b>, "
            "<b>aep</b>, and optionally <b>region</b>. "
            "<code>area</code> is km², <code>duration</code> is minutes, "
            "<code>aep</code> is a fraction (0.01 = 1%). "
            "If <code>region</code> is missing, the Single-tab region is used. "
            "The output CSV mirrors the input and appends an <code>arf</code> column."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        row_in = QHBoxLayout()
        self.lblBatchIn = QLabel("(no input file selected)")
        btn_in = QPushButton("Select input CSV…")
        btn_in.clicked.connect(self._pick_batch_in)
        row_in.addWidget(btn_in); row_in.addWidget(self.lblBatchIn, 1)
        layout.addLayout(row_in)

        row_out = QHBoxLayout()
        self.lblBatchOut = QLabel("(no output file selected)")
        btn_out = QPushButton("Select output CSV…")
        btn_out.clicked.connect(self._pick_batch_out)
        row_out.addWidget(btn_out); row_out.addWidget(self.lblBatchOut, 1)
        layout.addLayout(row_out)

        btn_run = QPushButton("Run batch")
        btn_run.clicked.connect(self._on_batch_run)
        layout.addWidget(btn_run)

        self.lblBatchStatus = QLabel("")
        self.lblBatchStatus.setWordWrap(True)
        layout.addWidget(self.lblBatchStatus)
        layout.addStretch()

        self._batch_in: str | None = None
        self._batch_out: str | None = None
        return page

    def _pick_batch_in(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select input CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            self._batch_in = path
            self.lblBatchIn.setText(path)

    def _pick_batch_out(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Select output CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            self._batch_out = path
            self.lblBatchOut.setText(path)

    def _on_batch_run(self):
        self.lblBatchStatus.setText("")
        if not self._batch_in or not self._batch_out:
            QMessageBox.warning(self, "ARF batch", "Select both input and output CSV files.")
            return
        try:
            n_ok, n_err = _run_batch(
                self._batch_in, self._batch_out, self.cmbRegion.currentText()
            )
        except Exception as exc:  # unexpected — file IO, malformed CSV, etc.
            QMessageBox.critical(
                self, "ARF batch",
                f"Batch failed:\n{type(exc).__name__}: {exc}",
            )
            return
        msg = f"Wrote {n_ok + n_err} rows to {self._batch_out} — {n_ok} ok, {n_err} errored."
        self.lblBatchStatus.setText(msg)

    # ── Plot tab ─────────────────────────────────────────────────────
    def _build_plot_tab(self) -> QWidget:
        # matplotlib is a hard requirement of the suite (declared in
        # PROJECT_GOAL.md); if the import fails at plugin load time we
        # still want the Single/Batch tabs to work, so degrade gracefully.
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        except ImportError as exc:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(QLabel(
                f"matplotlib is not available in this QGIS Python:\n{exc}\n\n"
                "Single and Batch tabs still work."
            ))
            return page

        page = QWidget()
        layout = QVBoxLayout(page)

        blurb = QLabel(
            "ARF vs. duration for the region/area/AEP set on the Single tab. "
            "Click <b>Refresh</b> after changing those inputs."
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self._plot_fig = Figure(figsize=(6, 4), tight_layout=True)
        self._plot_ax = self._plot_fig.add_subplot(111)
        self._plot_canvas = FigureCanvas(self._plot_fig)
        self._plot_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._plot_canvas, 1)

        btn = QPushButton("Refresh")
        btn.clicked.connect(self._on_plot_refresh)
        layout.addWidget(btn)
        return page

    def _on_plot_refresh(self):
        if not hasattr(self, "_plot_ax"):
            return
        ax = self._plot_ax
        ax.clear()

        area = self.spnArea.value()
        aep = self.spnAep.value() / 100.0
        region = self.cmbRegion.currentText()

        # Log-spaced durations from 1 min to 7 days.
        n = 120
        d_min, d_max = 1.0, DURATION_MAX
        import math
        step = (math.log10(d_max) - math.log10(d_min)) / (n - 1)
        durations = [10 ** (math.log10(d_min) + i * step) for i in range(n)]

        try:
            values = arf_curve(durations, area, aep, region)
        except ArfInputError as exc:
            ax.set_title(f"Cannot plot: {exc}", fontsize=9, color="#a00")
            self._plot_canvas.draw()
            return

        ax.plot(durations, values, "-", color="#1f4e79")
        ax.set_xscale("log")
        ax.set_xlabel("Duration (min)")
        ax.set_ylabel("ARF")
        ax.set_ylim(0, 1.02)
        ax.grid(True, which="both", alpha=0.3)
        ax.set_title(f"{region} — area = {area:g} km², AEP = {aep * 100:g}%", fontsize=10)
        self._plot_canvas.draw()


# ── helpers ──────────────────────────────────────────────────────────

def _area_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(3); s.setRange(AREA_MIN, AREA_MAX); s.setValue(100.0)
    s.setSuffix(" km²")
    return s


def _duration_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(0); s.setRange(DURATION_MIN, DURATION_MAX); s.setValue(1440.0)
    s.setSuffix(" min")
    return s


def _aep_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(3); s.setRange(AEP_MIN * 100, AEP_MAX * 100); s.setValue(1.0)
    s.setSuffix(" %")
    return s


def _regions_image_widget() -> QWidget:
    """Show ARFregions.png if present; otherwise a placeholder hint."""
    wrap = QWidget()
    layout = QVBoxLayout(wrap); layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if os.path.isfile(_REGIONS_MAP):
        pix = QPixmap(_REGIONS_MAP).scaledToWidth(360, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pix)
    else:
        label.setText(
            "Regions map not found.\n\n"
            "Drop ARFregions.png into\n"
            f"{_RESOURCES}\n"
            "to display it here."
        )
        label.setStyleSheet("color: #666; padding: 12px;")
        label.setWordWrap(True)
    layout.addWidget(label); layout.addStretch()
    return wrap


def _run_batch(input_csv: str, output_csv: str, default_region: str) -> tuple[int, int]:
    """Read (area, duration, aep, [region]) rows, write with an ``arf`` column.

    Returns (n_ok, n_error). Rows with unparseable numbers or out-of-range
    inputs get an error message in the ``arf`` column rather than a number.
    """
    n_ok = 0
    n_err = 0

    with open(input_csv, "r", newline="", encoding="utf-8-sig") as fh_in:
        reader = csv.DictReader(fh_in)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row.")

        header_map = {name.lower().strip(): name for name in reader.fieldnames}
        for required in ("area", "duration", "aep"):
            if required not in header_map:
                raise ValueError(
                    f"Input CSV is missing required column '{required}'. "
                    f"Found columns: {reader.fieldnames}"
                )
        has_region = "region" in header_map

        out_fields = list(reader.fieldnames) + ["arf"]

        with open(output_csv, "w", newline="", encoding="utf-8") as fh_out:
            writer = csv.DictWriter(fh_out, fieldnames=out_fields)
            writer.writeheader()

            for row in reader:
                out_row = dict(row)
                try:
                    area = float(row[header_map["area"]])
                    duration = float(row[header_map["duration"]])
                    aep = float(row[header_map["aep"]])
                    region = (
                        row[header_map["region"]] if has_region and row[header_map["region"]]
                        else default_region
                    )
                    out_row["arf"] = f"{arf(area, duration, aep, region):.4f}"
                    n_ok += 1
                except (ArfInputError, ValueError, KeyError) as exc:
                    out_row["arf"] = f"ERROR: {exc}"
                    n_err += 1
                writer.writerow(out_row)

    return n_ok, n_err
