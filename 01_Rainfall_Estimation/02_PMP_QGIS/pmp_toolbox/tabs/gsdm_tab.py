"""Tab 1: catchment-average GSDM PMP against duration.

The Generalised Short-Duration Method for storms of 0.25 to 6 hours over
catchments up to 1000 km2.  This tab answers the depth question -- how much
rain, over the whole catchment, at each duration -- and leaves the spatial
distribution of that rain to the Areal GSDM tab.

Three of the four adjustments are read at the catchment centroid rather than
typed: the moisture factor off Figure 3, the duration limit off Figure 2, and
the elevation factor from a mean elevation via section 4.3.  Each shows where
it came from, and each can be typed over.

The point value is shown beside the areal one because it is the number most
often wanted for comparison, and because seeing how far the areal depth has
fallen below it is the clearest statement of what areal reduction is doing.

Laid out as cases | inputs | results over a plot panel, following the Drain
Design Toolbox.  Cases are what make that layout earn its keep here: varying
the terrain split or the duration limit and seeing both curves at once is the
common question, and the **All cases** plot answers it directly.
"""

from __future__ import annotations

from ..core import depth as depth_core
from ..core import duration as duration_lookup
from ..core.gsdm import elevation_adjustment_factor
from ..qt_compat import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from .common import (
    Catchment,
    CaseSidebar,
    CatchmentPicker,
    DerivedField,
    PlotPanel,
    ResultTable,
    annotate_points,
    apply_style,
    build_shell,
    copy_to_clipboard,
    describe_latlon,
    export_csv,
    fill_table,
    maf_lookup,
    provenance_label,
    input_pane,
    scrollable,
    style_axes,
    style_table,
    wrap_form,
)

HEADERS = ["Duration (hr)", "Areal (mm)", "Point (mm)", "Areal / point"]

PLOT_CASE = "Depth-duration"
PLOT_ALL = "All cases"

#: A colour per case on the comparison plot, cycled.
CASE_COLOURS = ["#0f8b8d", "#B8672A", "#14304d", "#7a5ba6", "#1a7a1a", "#a80000"]


class GsdmTab(QWidget):
    """Catchment-average GSDM depth-duration, over one or more cases."""

    def __init__(self, parent=None):
        super().__init__(parent)
        #: Set while inputs are being written from a case, so the widget
        #: signals that fire do not write straight back into it.
        self._loading = False
        self._current = None
        self._build()
        apply_style(self)
        self.picker.refresh()
        self.cases.add_case("Case 1", self._capture())
        self._current = self.cases.current()

    # ------------------------------------------------------------- build

    def _build(self):
        inputs = input_pane(self._inputs_column(), self._buttons(), width=340)

        self.cases = CaseSidebar()
        self.cases.currentCaseChanged.connect(self._on_case_changed)
        self.cases.casesChanged.connect(self._refresh_all_plot)

        self.plots = PlotPanel()

        self.setLayout(
            build_shell(
                # No header band: the buttons sit at the foot of the inputs
                # column, under the parameters they act on.
                None,
                self.cases,
                inputs,
                self._results_group(),
                self.plots,
            )
        )

    def _inputs_column(self):
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)

        # The catchment lives at the top of the inputs column, not in a band
        # across the top of the tab: it is an input like any other, and the
        # top of the tab belongs to the project row.
        self.picker = CatchmentPicker()
        self.picker.catchmentChanged.connect(self._on_catchment)
        column.addWidget(self.picker)

        group = QGroupBox("GSDM parameters")
        form = QFormLayout(group)
        wrap_form(form)

        self.duration_limit = QComboBox()
        self.duration_limit.setToolTip(
            "The longest duration the method applies for, from GSDM Figure 2.\n\n"
            "Read at the catchment centroid. In the intermediate band between "
            "the three-hour and six-hour zones both are defensible, so both are "
            "offered rather than one being chosen for you."
        )
        self.duration_limit.currentIndexChanged.connect(self._touched)
        self.duration_note = provenance_label()
        self.duration_button = QPushButton("From centroid")
        self.duration_button.setObjectName("lookupButton")
        self.duration_button.clicked.connect(lambda: self._lookup_duration(force=True))
        row = QHBoxLayout()
        row.addWidget(self.duration_limit, stretch=1)
        row.addWidget(self.duration_button)
        form.addRow("Duration limit (Figure 2)", row)
        form.addRow("", self.duration_note)

        self.smooth = QSpinBox()
        self.smooth.setRange(0, 100)
        # 0% smooth / 100% rough, matching the Toolbox website and the PSM6186
        # worked examples. Rough is the conservative half of the split -- its
        # curves are the deeper ones -- so defaulting to smooth would quietly
        # under-report for anyone who did not set it.
        self.smooth.setValue(0)
        self.smooth.setSuffix(" % smooth")
        self.smooth.valueChanged.connect(self._on_smooth)
        self.rough_label = QLabel("100 % rough")
        row = QHBoxLayout()
        row.addWidget(self.smooth)
        row.addWidget(self.rough_label)
        row.addStretch(1)
        form.addRow("Terrain (§4.2)", row)

        self.maf = DerivedField(
            "MAF",
            maf_lookup,
            minimum=0.10,
            maximum=1.20,
            decimals=2,
            step=0.05,
            tooltip=(
                "Moisture Adjustment Factor, GSDM Figure 3.\n\n"
                "Read at the catchment centroid from contours digitised from "
                "the Bureau's vector PDF. Type over it to use your own reading."
            ),
            default=0.75,
            parent=self,
        )
        self.maf.spin.valueChanged.connect(self._touched)
        self.maf.add_to_form(form, "MAF (Figure 3)")

        self.elevation = QDoubleSpinBox()
        self.elevation.setRange(0.0, 5000.0)
        self.elevation.setSingleStep(50.0)
        self.elevation.setSuffix(" m")
        self.elevation.setToolTip(
            "Mean catchment elevation. GSDM section 4.3: the factor is 1.0 up "
            "to 1500 m, then falls 0.05 per 300 m, with a floor of 0.85."
        )
        self.elevation.valueChanged.connect(self._on_elevation)
        self.eaf_label = QLabel("EAF 1.00")
        row = QHBoxLayout()
        row.addWidget(self.elevation)
        row.addWidget(self.eaf_label)
        row.addStretch(1)
        form.addRow("Mean elevation (§4.3)", row)

        column.addWidget(group)
        column.addStretch(1)
        return holder

    def _buttons(self):
        """Calculate and export, at the foot of the inputs column.

        Below the inputs rather than above them: they act on what is in the
        column, and reading downwards to the button that runs it is the order
        the work happens in.
        """
        row = QHBoxLayout()
        self.run_button = QPushButton("Calculate")
        self.run_button.clicked.connect(self.run)
        self.run_all_button = QPushButton("Calculate all cases")
        self.run_all_button.clicked.connect(self.run_all)
        self.export_button = QPushButton("Export CSV\u2026")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)

        # Two rows of two: four buttons side by side do not fit the column.
        grid = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(self.run_button)
        top.addWidget(self.run_all_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.export_button)
        bottom.addWidget(self.copy_button)
        grid.addLayout(top)
        grid.addLayout(bottom)
        row.addLayout(grid)
        return row

    def _results_group(self):
        group = QGroupBox("Results")
        group.setMinimumWidth(380)
        layout = QVBoxLayout(group)

        self.summary = QLabel("Not calculated yet.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        style_table(self.table)
        layout.addWidget(self.table, stretch=1)

        self.warnings = QTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(64)
        self.warnings.setVisible(False)
        layout.addWidget(self.warnings)
        return group

    # ----------------------------------------------------------- signals

    def _touched(self, *_args):
        """Write a widget change straight back into the current case."""
        if self._loading or self._current is None:
            return
        self._current.inputs = self._capture()

    def _on_smooth(self, value):
        self.rough_label.setText(f"{100 - value} % rough")
        self._touched()

    def _on_elevation(self, value):
        self.eaf_label.setText(f"EAF {elevation_adjustment_factor(value):.2f}")
        self._touched()

    def _on_catchment(self, catchment: Catchment | None):
        self.maf.update_from(catchment)
        self._lookup_duration()
        self._touched()

    def _lookup_duration(self, force: bool = False):
        catchment = self.picker.catchment()
        if catchment is None:
            self.duration_note.setText("")
            return
        try:
            reading = duration_lookup.lookup(catchment.lat, catchment.lon)
        except ValueError as exc:
            self.duration_note.setText(str(exc))
            return

        previous = self.duration_limit.currentData()
        blocked = self.duration_limit.blockSignals(True)
        self.duration_limit.clear()
        for hours in reading["options"]:
            self.duration_limit.addItem(f"{hours:g} hours", hours)
        # Keep the engineer's choice across a re-lookup when it is still on
        # offer -- in the intermediate band, changing catchment should not
        # silently swap a deliberate 3 for a 6.
        if previous in reading["options"] and not force:
            self.duration_limit.setCurrentIndex(reading["options"].index(previous))
        elif reading["recommended"] is not None:
            self.duration_limit.setCurrentIndex(
                reading["options"].index(reading["recommended"])
            )
        self.duration_limit.blockSignals(blocked)

        if reading["zone"] == "intermediate":
            self.duration_note.setText(
                "In the intermediate band of Figure 2 — both limits are "
                f"defensible; the nearer zone is {reading['nearer']:g} hours."
            )
        else:
            self.duration_note.setText(
                f"Figure 2 {reading['zone']} zone at "
                f"{describe_latlon(catchment.lat, catchment.lon)}."
            )

    # ------------------------------------------------------------- cases

    def _capture(self) -> dict:
        """The current widget state, as a plain dict for a case to hold."""
        return {
            "layer": self.picker.layer_combo.currentLayer(),
            "selected_only": self.picker.selected_only.isChecked(),
            "duration_limit": self.duration_limit.currentData(),
            "smooth": self.smooth.value(),
            "maf": self.maf.value(),
            "maf_provenance": self.maf.provenance(),
            "elevation": self.elevation.value(),
            "duration_note": self.duration_note.text(),
        }

    def _apply(self, inputs: dict):
        """Write a case's inputs back into the widgets."""
        self._loading = True
        try:
            if inputs.get("layer") is not None:
                self.picker.layer_combo.setLayer(inputs["layer"])
            self.picker.selected_only.setChecked(bool(inputs.get("selected_only")))
            limit = inputs.get("duration_limit")
            if limit is not None:
                index = self.duration_limit.findData(limit)
                if index < 0:
                    self.duration_limit.addItem(f"{limit:g} hours", limit)
                    index = self.duration_limit.findData(limit)
                self.duration_limit.setCurrentIndex(index)
            self.smooth.setValue(int(inputs.get("smooth", 0)))
            self.rough_label.setText(f"{100 - self.smooth.value()} % rough")
            self.maf.set_value(
                inputs.get("maf", 0.75),
                inputs.get("maf_provenance", "entered by hand"),
            )
            self.elevation.setValue(float(inputs.get("elevation", 0.0)))
            self.eaf_label.setText(
                f"EAF {elevation_adjustment_factor(self.elevation.value()):.2f}"
            )
            self.duration_note.setText(inputs.get("duration_note", ""))
        finally:
            self._loading = False

    def _on_case_changed(self, case):
        # The outgoing case is captured here rather than by the sidebar,
        # because only this tab knows what its widgets hold.
        if self._current is not None and self._current is not case:
            self._current.inputs = self._capture()
        self._current = case
        if case is None:
            return
        self._apply(case.inputs)
        self._show_stored(case)

    def _show_stored(self, case):
        """Put a case's saved results back on screen, or clear them."""
        if case.table is None:
            self.table.setRowCount(0)
            self.summary.setText("Not calculated yet.")
            self.warnings.setVisible(False)
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.plots.set_data(PLOT_CASE, None)
            ax = self.plots.page(PLOT_CASE)
            if ax is not None:
                style_axes(ax)
                self.plots.draw(PLOT_CASE)
            return
        fill_table(self.table, case.table, highlight_row=case.highlight_row)
        self.summary.setText(case.summary)
        self.warnings.setVisible(bool(case.table.warnings))
        self.warnings.setPlainText("\n".join(f"• {w}" for w in case.table.warnings))
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self._plot_case(case)


    def load_cases(self, named_inputs) -> None:
        """Replace this tab's cases with a project's, and show the first.

        Results are not restored from file: they are output, and pressing
        Calculate recomputes them from the inputs that just came back.
        """
        self._current = None
        self.cases.reset(named_inputs)
        self._current = self.cases.current()
        if self._current is not None:
            self._apply(self._current.inputs)
            self._show_stored(self._current)
        self._refresh_all_plot()

    # --------------------------------------------------------------- run

    def run(self):
        """Calculate the current case."""
        case = self.cases.current()
        if case is None:
            return
        self._current = case
        case.inputs = self._capture()
        if not self._calculate(case, complain=True):
            return
        self._show_stored(case)
        self.cases.refresh_labels()
        self._refresh_all_plot()

    def run_all(self):
        """Calculate every case, then come back to the current one.

        Each case carries its own layer and parameters, so this writes each
        one into the widgets in turn and puts the user back where they were.
        """
        cases = self.cases.cases()
        if not cases:
            return
        current = self.cases.current()
        if current is not None:
            current.inputs = self._capture()

        failed = []
        for case in cases:
            self._apply(case.inputs)
            if not self._calculate(case, complain=False):
                failed.append(case.name)

        if current is not None:
            self._current = current
            self._apply(current.inputs)
            self._show_stored(current)
        self.cases.refresh_labels()
        self._refresh_all_plot()

        if failed:
            QMessageBox.warning(
                self,
                "Some cases did not run",
                "These cases could not be calculated:\n  " + "\n  ".join(failed),
            )

    def _calculate(self, case, complain: bool) -> bool:
        """Run one case, storing its result on it. True if it ran."""
        catchment = self.picker.catchment()
        if catchment is None:
            if complain:
                QMessageBox.warning(self, "No catchment", self.picker.error())
            return False

        limit = self.duration_limit.currentData()
        if limit is None:
            if complain:
                QMessageBox.warning(
                    self,
                    "No duration limit",
                    "Figure 2 could not be read at this centroid. Press “From "
                    "centroid” or choose a limit before calculating.",
                )
            return False

        smooth = self.smooth.value() / 100.0
        eaf = elevation_adjustment_factor(self.elevation.value())
        maf = self.maf.value()

        try:
            areal = depth_core.calc_gsdm(
                catchment.area_km2, limit, smooth, 1.0 - smooth, eaf, maf
            )
            point = depth_core.calc_gsdm(0.0, limit, smooth, 1.0 - smooth, eaf, maf)
        except ValueError as exc:
            if complain:
                QMessageBox.critical(self, "Cannot run GSDM", str(exc))
            return False

        case.result = (areal, point)
        table, row, summary = self._render(
            case, catchment, areal, point, limit, smooth, eaf, maf
        )
        case.table = table
        case.summary = summary
        case.highlight_row = row
        return True

    def _render(self, case, catchment, areal, point, limit, smooth, eaf, maf):
        rows = []
        controlling_row = None
        for i, d in enumerate(areal.seasons[0].by_duration):
            point_mm = point.seasons[0].depth_at(d.duration_hr)
            ratio = (d.pmp_mm / point_mm) if point_mm else float("nan")
            rows.append([
                f"{d.duration_hr:g}",
                f"{d.pmp_mm:,.0f}",
                f"{point_mm:,.0f}" if point_mm is not None else "",
                f"{ratio:.2f}",
            ])
            if d.duration_hr == areal.controlling_duration_hr:
                controlling_row = i

        warnings = list(areal.warnings)
        if catchment.area_km2 > 1000.0:
            # calc_gsdm already warns; this says what to do about it.
            warnings.append(
                "Above 1000 km2 the GSDM does not apply — use GTSMR or GSAM "
                "for a catchment this size."
            )

        summary = (
            f"<b>{areal.controlling_duration_hr:g}-hour PMP "
            f"{areal.pmp_mm:,.0f} mm</b> over {catchment.area_km2:,.2f} km² "
            f"&nbsp;•&nbsp; storm volume {areal.volume_m3:,.0f} m³<br>"
            f"MAF {maf:.2f} &nbsp;•&nbsp; EAF {eaf:.2f} &nbsp;•&nbsp; "
            f"{smooth * 100:.0f}% smooth / {(1 - smooth) * 100:.0f}% rough "
            f"&nbsp;•&nbsp; limit {limit:g} hours"
        )
        table = ResultTable(
            headers=HEADERS,
            rows=rows,
            run_inputs=self._describe_run(
                case, catchment, areal, limit, smooth, eaf, maf
            ),
            warnings=warnings,
            title="GSDM results",
        )
        return table, controlling_row, summary

    # -------------------------------------------------------------- plots

    def _plot_case(self, case):
        ax = self.plots.page(PLOT_CASE)
        if ax is None or case.result is None:
            return
        areal, point = case.result
        durations = [d.duration_hr for d in areal.seasons[0].by_duration]
        areal_mm = [d.pmp_mm for d in areal.seasons[0].by_duration]
        point_mm = [point.seasons[0].depth_at(d) for d in durations]

        ax.plot(durations, areal_mm, marker="o", color="#0f8b8d", label="Areal")
        ax.plot(durations, point_mm, marker="s", linestyle="--",
                color="#14304d", label="Point")
        annotate_points(ax, durations, areal_mm)
        ax.set_xlabel("Duration (hours)")
        ax.set_ylabel("PMP (mm)")
        ax.set_title(case.name, fontsize=9, loc="left")
        ax.legend(frameon=False, fontsize=8)
        style_axes(ax)
        self.plots.set_data(PLOT_CASE, case.table)
        self.plots.draw(PLOT_CASE)

    def _refresh_all_plot(self, *_args):
        """Every calculated case on one axes -- the reason cases exist here."""
        ax = self.plots.page(PLOT_ALL)
        if ax is None:
            return
        done = [c for c in self.cases.cases() if c.result is not None]

        durations: list[float] = []
        for i, case in enumerate(done):
            areal = case.result[0]
            xs = [d.duration_hr for d in areal.seasons[0].by_duration]
            ys = [d.pmp_mm for d in areal.seasons[0].by_duration]
            ax.plot(xs, ys, marker="o", label=case.name,
                    color=CASE_COLOURS[i % len(CASE_COLOURS)])
            durations = sorted(set(durations) | set(xs))

        ax.set_xlabel("Duration (hours)")
        ax.set_ylabel("Areal PMP (mm)")
        if done:
            ax.legend(frameon=False, fontsize=8)
            if len(done) == 1:
                annotate_points(ax, durations,
                                [done[0].result[0].seasons[0].depth_at(d)
                                 for d in durations])
        else:
            ax.set_title("No case has been calculated yet.", fontsize=9, loc="left")
        style_axes(ax)

        # One tidy table behind the comparison: a row per duration, a column
        # per case, which is the shape anyone comparing them wants to paste.
        if done and durations:
            headers = ["Duration (hr)"] + [c.name for c in done]
            rows = []
            for duration in durations:
                row = [f"{duration:g}"]
                for case in done:
                    value = case.result[0].seasons[0].depth_at(duration)
                    row.append(f"{value:,.0f}" if value is not None else "")
                rows.append(row)
            self.plots.set_data(PLOT_ALL, ResultTable(
                headers=headers,
                rows=rows,
                run_inputs=[("Plot", "GSDM areal PMP, all calculated cases")],
                warnings=[],
                title="All cases",
            ))
        else:
            self.plots.set_data(PLOT_ALL, None)
        self.plots.draw(PLOT_ALL)

    # ------------------------------------------------------------ export

    def _describe_run(self, case, catchment, result, limit, smooth, eaf, maf):
        """The inputs behind the table, for the export's Run inputs block."""
        return [
            ("Method", "GSDM (catchment-average)"),
            ("Case", case.name),
            ("Catchment layer", catchment.layer_name),
            ("Selected features only", "yes" if catchment.selected_only else "no"),
            ("CRS", catchment.crs.authid()),
            ("Area (km2)", f"{catchment.area_km2:.4f}"),
            ("Centroid", describe_latlon(catchment.lat, catchment.lon)),
            ("Centroid lat", f"{catchment.lat:.5f}"),
            ("Centroid lon", f"{catchment.lon:.5f}"),
            ("Duration limit (hr)", f"{limit:g}"),
            ("Duration limit source", self.duration_note.text() or "chosen by hand"),
            ("Terrain", f"{smooth * 100:.0f}% smooth / {(1 - smooth) * 100:.0f}% rough"),
            ("MAF (Figure 3)", f"{maf:.2f}"),
            ("MAF source", self.maf.provenance()),
            ("Mean elevation (m)", f"{self.elevation.value():g}"),
            ("EAF (section 4.3)", f"{eaf:.2f}"),
            ("Controlling duration (hr)", f"{result.controlling_duration_hr:g}"),
            ("PMP (mm)", f"{result.pmp_mm:.0f}"),
            ("Storm volume (m3)", f"{result.volume_m3:.0f}"),
        ]

    def export_csv(self):
        case = self.cases.current()
        if case is not None and case.table is not None:
            export_csv(self, case.table, "gsdm_depth_duration.csv")

    #: Kept so the tests and the other tabs share one spelling.
    _export = export_csv

    def _copy(self):
        case = self.cases.current()
        if case is not None and case.table is not None:
            copy_to_clipboard(case.table)
