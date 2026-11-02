"""Tab 2: the GSDM spatial distribution, by optimised ellipse placement.

This is GSDM section 6.  Where the GSDM tab gives one depth for the whole
catchment, this one gives the *design spatial distribution*: the Figure 6
storm template placed over the catchment, and a mean rainfall depth for each
ring between successive ellipses.

The Bulletin's Step 1 asks an analyst to overlay the template on a catchment
map and shuffle it by hand "to obtain the best fit by the smallest possible
ellipse".  Here that is an explicit search over the template centre and
rotation, and the preview window shows it happening.

Moved from the plugin's original standalone dialog; the calculation, the
optimiser, the preview and the output styling are unchanged.  What changed is
the shell: a tab rather than a dialog, laid out as cases | inputs | results
over a plot panel like the Drain Design Toolbox, with the catchment coming
from the shared picker.

Cases mean something slightly different here than on the other two tabs: a
search is expensive, so **Calculate all cases** re-runs the optimiser for each
one.  What that buys is the ring-depth comparison on the **All cases** plot --
the same catchment at two durations, or two terrain splits, side by side.
"""

from __future__ import annotations

from ..core import ellipses
from ..core.dda import DURATIONS
from ..core.gsdm import Inputs, elevation_adjustment_factor, round_pmp, weight_profile
from ..qt_compat import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    Qt,
)
from .common import (
    CaseSidebar,
    Catchment,
    CatchmentPicker,
    DerivedField,
    PlotPanel,
    ResultTable,
    apply_style,
    build_shell,
    copy_to_clipboard,
    describe_latlon,
    export_csv,
    maf_lookup,
    provenance_label,
    input_pane,
    scrollable,
    style_axes,
    style_table,
    wrap_form,
)

PLOT_CASE = "Ring depths"
PLOT_ALL = "All cases"

#: A colour per case on the comparison plot, cycled.
CASE_COLOURS = ["#0f8b8d", "#B8672A", "#14304d", "#7a5ba6", "#1a7a1a", "#a80000"]

RESULT_COLUMNS = [
    ("Ellipse", "label", None),
    ("CBtn (km²)", "cbtn", "{:.3f}"),
    ("CEnc (km²)", "cenc", "{:.3f}"),
    ("IMRD (mm)", "imrd", "{:.0f}"),
    ("AMRD (mm)", "amrd", "{:.0f}"),
    ("VEnc (mm·km²)", "venc", "{:,.0f}"),
    ("VBtn (mm·km²)", "vbtn", "{:,.0f}"),
    ("MRD (mm)", "mrd", "{:.0f}"),
    ("Step 4 source", "source", None),
]


class ArealGsdmTab(QWidget):
    """Ellipse placement and the per-ring depths that follow from it."""

    def __init__(self, iface, preview_owner=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        # The preview window outlives any one run and must be closed on
        # unload, so the plugin owns it and hands it over on request rather
        # than the tab creating one of its own.
        self._preview_owner = preview_owner
        #: Set while inputs are being written from a case, so the widget
        #: signals that fire do not write straight back into it.
        self._loading = False
        self._current = None
        self._result = None
        self._table: ResultTable | None = None
        self._build()
        apply_style(self)
        self.picker.refresh()
        self.refresh_weights()
        self.cases.add_case("Case 1", self._capture())
        self._current = self.cases.current()

    # ------------------------------------------------------------- build

    def _build(self):
        inputs = input_pane(self._inputs_column(), self._footer(), width=380)

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
        column.addWidget(self._parameters_group())
        column.addWidget(self._weights_group())
        column.addStretch(1)
        return holder

    def _footer(self):
        """Buttons and the progress bar, pinned below the scrolling inputs."""
        footer = QVBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addLayout(self._buttons())

        # The progress bar belongs with the button that fills it.
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        footer.addWidget(self.progress)
        return footer

    def _parameters_group(self):
        group = QGroupBox("GSDM parameters")
        form = QFormLayout(group)
        wrap_form(form)

        self.duration = QComboBox()
        for d in DURATIONS:
            self.duration.addItem(f"{d:g} hour" + ("s" if d != 1 else ""), d)
        self.duration.setCurrentIndex(DURATIONS.index(3.0))
        self.duration.currentIndexChanged.connect(self.refresh_weights)
        self.duration.currentIndexChanged.connect(self._touched)
        form.addRow("Duration", self.duration)

        self.smooth = QSpinBox()
        self.smooth.setRange(0, 100)
        # 0% smooth / 100% rough, matching the Toolbox website's default and
        # the PSM6186 worked examples. Rough is the conservative half of the
        # split -- its curves are the deeper ones -- so defaulting to smooth
        # would quietly under-report for anyone who did not set it.
        self.smooth.setValue(0)
        self.smooth.setSuffix(" % smooth")
        self.smooth.valueChanged.connect(self._on_smooth_changed)
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
        self.maf.spin.valueChanged.connect(self.refresh_weights)
        self.maf.spin.valueChanged.connect(self._touched)
        self.maf.add_to_form(form, "MAF (Figure 3)")

        self.elevation = QDoubleSpinBox()
        self.elevation.setRange(0.0, 5000.0)
        self.elevation.setSingleStep(50.0)
        self.elevation.setSuffix(" m")
        self.elevation.valueChanged.connect(self._on_elevation_changed)
        self.eaf_label = QLabel("EAF 1.00")
        row = QHBoxLayout()
        row.addWidget(self.elevation)
        row.addWidget(self.eaf_label)
        row.addStretch(1)
        form.addRow("Mean elevation (§4.3)", row)

        self.sampling = QSpinBox()
        self.sampling.setRange(5, 2000)
        self.sampling.setSingleStep(10)
        self.sampling.setValue(50)
        self.sampling.setSuffix(" m")
        self.sampling.setToolTip(
            "How far apart the sample points are while the search compares "
            "candidate placements. Closer together is slower and makes the "
            "choice of placement more reliable.\n\n"
            "It does not change your results: once a placement is chosen, "
            "every ring area is measured exactly from the catchment polygon. "
            "Nothing is rasterised or saved -- the points exist only during "
            "the search."
        )
        self.sampling.valueChanged.connect(self.refresh_sample_estimate)
        self.sampling.valueChanged.connect(self._touched)
        self.sample_estimate = provenance_label()
        row = QHBoxLayout()
        row.addWidget(self.sampling)
        row.addWidget(self.sample_estimate, stretch=1)
        form.addRow("Search sampling", row)

        self.rotations = QSpinBox()
        self.rotations.setRange(1, 72)
        self.rotations.setValue(12)
        self.rotations.valueChanged.connect(self._touched)
        self.rotations.setToolTip(
            "Rotation steps across a half turn. The template may be oriented "
            "in any direction (§6); 12 steps is 15 degrees apart."
        )
        form.addRow("Rotation steps", self.rotations)

        self.show_preview = QCheckBox("Show the search in a preview window")
        self.show_preview.setChecked(True)
        self.show_preview.setToolTip(
            "Opens a window showing the template being shuffled over the "
            "catchment, GSDM Step 1 done visibly. It can be paused, cancelled, "
            "run at full speed, and replayed once the search finishes."
        )
        form.addRow("Preview", self.show_preview)

        self.as_shapefile = QCheckBox("Write output as temporary shapefiles")
        self.as_shapefile.setChecked(True)
        self.as_shapefile.setToolTip(
            "Write the ellipses to .shp files in the QGIS temporary folder and "
            "load those. File-backed layers survive a restart and can be copied "
            "elsewhere. Unchecked, the outputs are temporary scratch layers "
            "held in memory, which are lost when the project closes."
        )
        form.addRow("Output", self.as_shapefile)
        return group

    def _weights_group(self):
        group = QGroupBox("Ring weights")
        layout = QVBoxLayout(group)
        note = provenance_label(
            "Score = Σ (weight × catchment area in that ring). Defaults are the "
            "Table 2 mean rainfall depths for the chosen duration and terrain, "
            "so the search maximises storm depth over the catchment. They are "
            "held fixed during the search; the true GSDM depths are recomputed "
            "exactly once the placement is chosen."
        )
        layout.addWidget(note)

        self.weights_table = QTableWidget(1, len(ellipses.LABELS))
        self.weights_table.setHorizontalHeaderLabels(list(ellipses.LABELS))
        self.weights_table.setVerticalHeaderLabels(["mm"])
        self.weights_table.setMaximumHeight(70)
        self.weights_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.weights_table.itemChanged.connect(self._touched)
        layout.addWidget(self.weights_table)

        # Locked by default, as the GTSMR grid fields are: these ten numbers
        # are read off Table 2 for the chosen duration and terrain, and a
        # mistyped one changes which placement the search picks without
        # changing anything visible about the result.
        row = QHBoxLayout()
        self.weights_lock = QPushButton()
        self.weights_lock.setObjectName("lookupButton")
        self.weights_lock.setCheckable(True)
        self.weights_lock.toggled.connect(self._on_weights_lock_toggled)
        row.addWidget(self.weights_lock)

        self.weights_reset = QPushButton("Reset to GSDM depths")
        self.weights_reset.setObjectName("lookupButton")
        self.weights_reset.clicked.connect(lambda: self.refresh_weights(force=True))
        row.addWidget(self.weights_reset)
        row.addStretch(1)
        layout.addLayout(row)

        self.weights_note = provenance_label()
        layout.addWidget(self.weights_note)

        self._apply_weights_lock()
        return group

    def _tint_weights(self):
        """Grey the cells while they are locked.

        Set on the items rather than through a stylesheet: a background on the
        QTableWidget paints around the cells, and ``::item`` loses to the
        alternating-row colours the table already has. The item's own brush
        is the one thing that reliably wins.
        """
        from ..qt_compat import QColor

        locked = self.weights_locked()
        for column in range(self.weights_table.columnCount()):
            item = self.weights_table.item(0, column)
            if item is not None:
                item.setBackground(
                    QColor("#f1f3f3") if locked else QColor(Qt.GlobalColor.white)
                )

    def weights_locked(self) -> bool:
        """True when the ring weights track Table 2 and cannot be typed over."""
        return not self.weights_lock.isChecked()

    def _on_weights_lock_toggled(self, _unlocked: bool):
        self._apply_weights_lock()
        self._touched()

    def _apply_weights_lock(self):
        """Reflect the lock in the table, the button and the note."""
        locked = self.weights_locked()
        self.weights_table.setEditTriggers(
            QTableWidget.NoEditTriggers
            if locked
            else QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
        )
        self._tint_weights()
        self.weights_lock.setText(
            "\U0001F512 Unlock to override"
            if locked
            else "\U0001F513 Overridden \u2014 relock"
        )
        self.weights_note.setText(
            "Locked to the Table 2 depths, and refilled whenever the duration "
            "or the terrain split changes. Unlock only to weight the search "
            "deliberately \u2014 the weights choose the placement, so an "
            "accidental edit changes the answer without looking like it."
            if locked
            else "Unlocked \u2014 these weights are yours, and changing the "
            "duration or terrain will no longer refill them. "
            "\u201cReset to GSDM depths\u201d puts Table 2 back."
        )

    def _buttons(self):
        row = QHBoxLayout()
        self.run_button = QPushButton("Run search")
        self.run_button.clicked.connect(self.run)
        self.run_all_button = QPushButton("Run all cases")
        self.run_all_button.setToolTip(
            "Re-run the placement search for every case. Each case costs a "
            "full search, so this is slower than the other tabs' equivalent, "
            "and it runs without the preview window."
        )
        self.run_all_button.clicked.connect(self.run_all)
        self.export_button = QPushButton("Export CSV…")
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
        group.setMinimumWidth(420)
        layout = QVBoxLayout(group)
        self.summary = QLabel("Not run yet.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels([c[0] for c in RESULT_COLUMNS])
        # Nine columns: sized to content and scrolled, not shared out equally.
        style_table(self.results_table, stretch=False)
        layout.addWidget(self.results_table, stretch=1)

        self.warnings = QTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(90)
        self.warnings.setVisible(False)
        layout.addWidget(self.warnings)
        return group

    # ----------------------------------------------------------- signals

    def _touched(self, *_args):
        """Write a widget change straight back into the current case."""
        if self._loading or self._current is None:
            return
        self._current.inputs = self._capture()

    def _on_smooth_changed(self, value):
        self.rough_label.setText(f"{100 - value} % rough")
        self.refresh_weights()
        self._touched()

    def _on_elevation_changed(self, value):
        self.eaf_label.setText(f"EAF {elevation_adjustment_factor(value):.2f}")
        self.refresh_weights()
        self._touched()

    def _on_catchment(self, catchment: Catchment | None):
        self.maf.update_from(catchment)
        self.refresh_sample_estimate()
        self._touched()

    # ------------------------------------------------------------- cases

    def _capture(self) -> dict:
        """The current widget state, as a plain dict for a case to hold."""
        return {
            "layer": self.picker.layer_combo.currentLayer(),
            "selected_only": self.picker.selected_only.isChecked(),
            "duration": self.duration.currentData(),
            "smooth": self.smooth.value(),
            "maf": self.maf.value(),
            "maf_provenance": self.maf.provenance(),
            "elevation": self.elevation.value(),
            "sampling": self.sampling.value(),
            "rotations": self.rotations.value(),
            "preview": self.show_preview.isChecked(),
            "as_shapefile": self.as_shapefile.isChecked(),
            "weights": self._weight_texts(),
            "weights_unlocked": self.weights_lock.isChecked(),
        }

    def _weight_texts(self) -> list[str]:
        out = []
        for column in range(len(ellipses.LABELS)):
            item = self.weights_table.item(0, column)
            out.append(item.text() if item else "")
        return out

    def _apply(self, inputs: dict):
        """Write a case's inputs back into the widgets."""
        self._loading = True
        try:
            if inputs.get("layer") is not None:
                self.picker.layer_combo.setLayer(inputs["layer"])
            self.picker.selected_only.setChecked(bool(inputs.get("selected_only")))
            duration = inputs.get("duration")
            if duration is not None:
                index = self.duration.findData(duration)
                if index >= 0:
                    self.duration.setCurrentIndex(index)
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
            self.sampling.setValue(int(inputs.get("sampling", 50)))
            self.rotations.setValue(int(inputs.get("rotations", 12)))
            self.show_preview.setChecked(bool(inputs.get("preview", True)))
            self.as_shapefile.setChecked(bool(inputs.get("as_shapefile", True)))
            # The weights are restored as typed, because an edited weight is a
            # deliberate override that refresh_weights() would silently undo.
            self.weights_lock.setChecked(bool(inputs.get("weights_unlocked")))
            self._apply_weights_lock()
            weights = inputs.get("weights")
            if weights:
                for column, text in enumerate(weights):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.weights_table.setItem(0, column, item)
                # Fresh items carry no brush, and this runs after
                # refresh_weights during construction, so without this the
                # lock tint is created and then immediately thrown away.
                self._tint_weights()
            self.refresh_sample_estimate()
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
        self._result = case.result[0] if case.result else None
        self._table = case.table
        if case.table is None:
            self.results_table.setRowCount(0)
            self.summary.setText("Not run yet.")
            self.warnings.setVisible(False)
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.plots.set_data(PLOT_CASE, None)
            ax = self.plots.page(PLOT_CASE)
            if ax is not None:
                style_axes(ax)
                self.plots.draw(PLOT_CASE)
            return
        self._fill_results_table(case.result[0])
        self.summary.setText(case.summary)
        self.warnings.setVisible(bool(case.table.warnings))
        self.warnings.setPlainText(
            "\n".join("\u2022 " + w for w in case.table.warnings)
        )
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self._plot_case(case)

    # ------------------------------------------------------------ inputs

    def inputs(self) -> Inputs:
        smooth = self.smooth.value() / 100.0
        return Inputs(
            duration_hr=self.duration.currentData(),
            smooth=smooth,
            rough=1.0 - smooth,
            maf=self.maf.value(),
            eaf=elevation_adjustment_factor(self.elevation.value()),
        )

    def refresh_sample_estimate(self, *_args):
        """Show what the chosen spacing costs, before Run finds out the hard way.

        The bounding box count, so an upper bound -- the catchment keeps only
        the points that fall inside it.
        """
        from .. import qgis_bridge

        layer = self.picker.layer_combo.currentLayer()
        if layer is None or layer.crs().isGeographic():
            # A geographic layer is refused outright at run time; an estimate in
            # degrees-as-metres would be nonsense.
            self.sample_estimate.setText("")
            return

        selected_only = self.picker.selected_only.isChecked()
        box = (
            layer.boundingBoxOfSelected()
            if selected_only and layer.selectedFeatureCount()
            else layer.extent()
        )
        try:
            points = qgis_bridge.estimate_points(
                box.width(), box.height(), self.sampling.value()
            )
        except ValueError:
            self.sample_estimate.setText("")
            return

        if points > qgis_bridge.MAX_SEARCH_POINTS:
            workable = qgis_bridge.workable_spacing_m(box.width(), box.height())
            self.sample_estimate.setText(
                f"up to {points:,} points — too many; use {workable} m or more"
            )
        else:
            self.sample_estimate.setText(f"up to {points:,} sample points")

    def refresh_weights(self, *_args, force: bool = False):
        """Repopulate the weight row from Table 2.

        Skipped while the weights are unlocked, unless forced by the reset
        button: once the engineer has taken them over, changing the duration
        must not quietly throw their numbers away. This mirrors the way a
        typed MAF survives a re-lookup.

        ``force`` is keyword-only, and ``*_args`` swallows whatever a signal
        passes. Both matter: this is connected to ``currentIndexChanged``,
        which hands over the new index, and a positional ``force`` would take
        that index as a truthy value and refill every time -- defeating the
        lock for exactly the case it exists to protect.
        """
        if not force and hasattr(self, "weights_lock") and not self.weights_locked():
            return
        profile = weight_profile(self.inputs())
        for column, label in enumerate(ellipses.LABELS):
            item = QTableWidgetItem(f"{profile.get(label, 0.0):.1f}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.weights_table.setItem(0, column, item)
        self._tint_weights()

    def weights(self) -> dict[str, float]:
        out = {}
        for column, label in enumerate(ellipses.LABELS):
            item = self.weights_table.item(0, column)
            try:
                out[label] = float(item.text()) if item else 0.0
            except ValueError:
                raise ValueError(
                    f"Weight for ellipse {label} is not a number: {item.text()!r}"
                )
        if all(v == 0.0 for v in out.values()):
            raise ValueError("At least one ring weight must be non-zero.")
        return out


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
        """Run the search for the current case."""
        case = self.cases.current()
        if case is not None:
            self._current = case
            case.inputs = self._capture()
        self._search(case, complain=True)

    def run_all(self):
        """Re-run the search for every case, then come back to this one.

        Unlike the other tabs this is genuinely expensive -- each case is a
        full placement search -- so it is a separate button rather than
        something that happens on every edit.
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
            if not self._search(case, complain=False, quiet=True):
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
                "These cases could not be run:\n  " + "\n  ".join(failed),
            )

    def _search(self, case, complain: bool = True, quiet: bool = False) -> bool:
        """Dissolve, search, distribute, then add the styled layers to the map.

        Moved verbatim in behaviour from the plugin's old ``run``: the progress
        bar and wait cursor, the clean handling of a cancelled search, the
        shapefile fallback, the zoom, and the message bar summary.
        """
        from .. import qgis_bridge, styling
        from ..core.optimiser import SearchCancelled
        from qgis.core import Qgis, QgsProject

        catchment = self.picker.catchment()
        if catchment is None:
            if complain:
                QMessageBox.warning(self, "No catchment", self.picker.error())
            return False
        layer = self.picker.layer_combo.currentLayer()

        try:
            weights = self.weights()
        except ValueError as exc:
            if complain:
                QMessageBox.warning(self, "Invalid weights", str(exc))
            return False

        observer = None
        preview = None
        # A batch run opens no preview: watching one search is the point of
        # the window, watching five in a row is not.
        if self.show_preview.isChecked() and not quiet and self._preview_owner is not None:
            preview = self._preview_owner.preview_window()
            preview.begin()
            observer = preview

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.run_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        def report(fraction):
            self.progress.setValue(int(fraction * 100))
            QApplication.processEvents()

        try:
            result, placement, coarse, clipped, crs, _raster = qgis_bridge.run(
                layer,
                self.inputs(),
                selected_only=catchment.selected_only,
                cell_m=self.sampling.value(),
                thetas=self.rotations.value(),
                weights=weights,
                progress=report,
                observer=observer,
            )
        except SearchCancelled:
            # Cancelling is a choice, not a failure: no dialog, nothing added.
            if self.iface is not None:
                self.iface.messageBar().pushInfo("PMP Toolbox", "Search cancelled.")
            return False
        except (ValueError, qgis_bridge.ProjectionError) as exc:
            if complain:
                QMessageBox.critical(self, "Cannot run GSDM", str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
            self.progress.setVisible(False)
            self.run_button.setEnabled(True)
            if observer is not None:
                observer.end_run()

        self.show_result(result, placement, coarse)
        if case is not None:
            case.result = (result, placement, coarse)
            case.table = self._table
            case.summary = self.summary.text()
            self.cases.refresh_labels()
        self._plot_case_from(result)
        self._refresh_all_plot()

        if preview is not None:
            preview.finish(
                result,
                placement,
                {
                    label: qgis_bridge.geometry_polygons(geometry)
                    for label, geometry in clipped.items()
                },
                summary=_preview_summary(result, placement),
            )

        prefix = f"GSDM {layer.name()} {result.inputs.duration_hr:g}h"
        outlines, rings = qgis_bridge.build_output_layers(
            result, placement, clipped, crs, name_prefix=prefix
        )

        folder = None
        if self.as_shapefile.isChecked():
            try:
                outlines, rings, folder = qgis_bridge.save_as_temp_shapefiles(
                    outlines, rings
                )
            except OSError as exc:
                # Falling back to scratch layers still shows the result rather
                # than losing a run that has already been computed.
                QMessageBox.warning(
                    self,
                    "Could not write shapefiles",
                    f"{exc}\n\nAdding the results as temporary scratch layers "
                    "instead.",
                )
                folder = None

        # Style after writing: a shapefile round trip would not carry the
        # renderer, so the layers added to the project must be the final ones.
        styling.style_rainfall(rings, [r.label for r in result.rings])
        styling.style_outlines(outlines)
        QgsProject.instance().addMapLayer(rings)
        QgsProject.instance().addMapLayer(outlines)

        # The template reaches well beyond the catchment, so without this the
        # ellipses are usually drawn outside the current view and look missing.
        self.iface.setActiveLayer(outlines)
        self.iface.zoomToActiveLayer()

        if folder is not None:
            self.iface.messageBar().pushInfo(
                "PMP Toolbox", f"Shapefiles written to {folder}"
            )

        level = (
            Qgis.MessageLevel.Warning if result.warnings else Qgis.MessageLevel.Success
        )
        self.iface.messageBar().pushMessage(
            "PMP Toolbox",
            f"Outermost ellipse {result.outermost}; "
            f"{result.inputs.duration_hr:g}-hour PMP "
            f"{round_pmp(result.pmp_mm)} mm"
            + (f" ({len(result.warnings)} warning(s))" if result.warnings else ""),
            level=level,
            duration=8,
        )
        return True

    # ----------------------------------------------------------- results

    def show_result(self, result, placement, coarse):
        """Render a finished run into the summary, the table and the export.

        The catchment is read back off the picker rather than passed in, so a
        result can be shown by a test without one having to be manufactured.
        """
        catchment = self.picker.catchment()
        self._result = result
        gain = placement.score - coarse.score
        self.summary.setText(
            f"<b>Outermost ellipse {result.outermost}</b> "
            f"({dict(zip(ellipses.LABELS, ellipses.AREAS_KM2))[result.outermost]:g} km²) "
            f"&nbsp;•&nbsp; catchment {result.catchment_area_km2:.2f} km² "
            f"(closure {result.closure_error_km2:+.4f} km²)<br>"
            f"Centre {placement.cx:,.1f}, {placement.cy:,.1f} &nbsp;•&nbsp; "
            f"major axis bearing {placement.bearing_deg:.1f}° &nbsp;•&nbsp; "
            f"score {placement.score:,.0f} mm·km² "
            f"({gain:+,.0f} from refinement)<br>"
            f"<b>{result.inputs.duration_hr:g}-hour PMP "
            f"{round_pmp(result.pmp_mm)} mm</b> "
            f"(unrounded {result.pmp_mm:.1f} mm)"
        )

        rows = self._fill_results_table(result)

        # Captured now, not at export time: the user may change the layer or a
        # parameter afterwards, and the export must describe the run it came
        # from.  The MAF provenance in particular is the only record of *where*
        # on Figure 3 the factor was read.
        self._table = ResultTable(
            headers=[c[0] for c in RESULT_COLUMNS],
            rows=rows,
            run_inputs=self._describe_run(catchment, result, placement),
            warnings=list(result.warnings),
            title="Areal GSDM results",
        )

        self.warnings.setVisible(bool(result.warnings))
        self.warnings.setPlainText("\n".join(f"• {w}" for w in result.warnings))
        self.export_button.setEnabled(True)
        self.copy_button.setEnabled(True)

    def _fill_results_table(self, result) -> list[list[str]]:
        """Paint the ring table, and hand back the same values as plain text."""
        rows = []
        self.results_table.setRowCount(len(result.rings))
        for row, ring in enumerate(result.rings):
            values = []
            for column, (_header, attr, fmt) in enumerate(RESULT_COLUMNS):
                value = getattr(ring, attr)
                text = "" if value is None else (fmt.format(value) if fmt else str(value))
                values.append(text)
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if column == 0
                    else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.results_table.setItem(row, column, item)
            rows.append(values)
        return rows

    # -------------------------------------------------------------- plots

    def _plot_case(self, case):
        if case.result:
            self._plot_case_from(case.result[0], case.name)

    def _plot_case_from(self, result, name: str | None = None):
        """Mean rainfall depth per ring, as bars in the map's own ramp.

        Bars rather than a line: the rings are ordered categories, not a
        continuous axis, and the Bulletin's own Table A2.2 reads as a bar
        chart.  The colours are the ones the rainfall layer is drawn in, so
        the plot and the map agree at a glance.
        """
        ax = self.plots.page(PLOT_CASE)
        if ax is None:
            return
        from ..palette import ramp_colour

        labels = [ring.label for ring in result.rings]
        depths = [ring.mrd for ring in result.rings]
        if not labels:
            return
        # Coloured by ring position, exactly as styling.style_rainfall colours
        # the map layer -- index 0 is the innermost and wettest. Colouring by
        # depth instead would look similar and disagree with the map.
        colours = [ramp_colour(i) for i in range(len(labels))]
        ax.bar(labels, depths, color=colours, edgecolor="#12222f", linewidth=0.4)
        for x, depth in zip(labels, depths):
            ax.annotate(
                f"{depth:,.0f}",
                (x, depth),
                textcoords="offset points",
                xytext=(0, 4),
                ha="center",
                fontsize=7,
                color="#12222f",
            )
        ax.set_xlabel("Ellipse ring")
        ax.set_ylabel("MRD (mm)")
        if name:
            ax.set_title(name, fontsize=9, loc="left")
        style_axes(ax)
        ax.grid(axis="x", visible=False)
        self.plots.set_data(PLOT_CASE, self._table)
        self.plots.draw(PLOT_CASE)

    def _refresh_all_plot(self, *_args):
        """Ring depths for every case that has been run, side by side."""
        ax = self.plots.page(PLOT_ALL)
        if ax is None:
            return
        done = [c for c in self.cases.cases() if c.result]

        labels: list[str] = []
        for case in done:
            for ring in case.result[0].rings:
                if ring.label not in labels:
                    labels.append(ring.label)
        labels.sort()

        width = 0.8 / max(len(done), 1)
        for i, case in enumerate(done):
            depths = {r.label: r.mrd for r in case.result[0].rings}
            xs = [j + i * width - 0.4 + width / 2 for j in range(len(labels))]
            ax.bar(
                xs,
                [depths.get(label, 0.0) for label in labels],
                width=width,
                label=case.name,
                color=CASE_COLOURS[i % len(CASE_COLOURS)],
                edgecolor="#12222f",
                linewidth=0.3,
            )

        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels)
        ax.set_xlabel("Ellipse ring")
        ax.set_ylabel("MRD (mm)")
        if done:
            ax.legend(frameon=False, fontsize=8)
        else:
            ax.set_title("No case has been run yet.", fontsize=9, loc="left")
        style_axes(ax)
        ax.grid(axis="x", visible=False)

        if done and labels:
            headers = ["Ring"] + [c.name for c in done]
            rows = []
            for label in labels:
                row = [label]
                for case in done:
                    depths = {r.label: r.mrd for r in case.result[0].rings}
                    value = depths.get(label)
                    row.append(f"{value:.0f}" if value is not None else "")
                rows.append(row)
            self.plots.set_data(PLOT_ALL, ResultTable(
                headers=headers,
                rows=rows,
                run_inputs=[("Plot", "Ring mean rainfall depth, all cases run")],
                warnings=[],
                title="All cases",
            ))
        else:
            self.plots.set_data(PLOT_ALL, None)
        self.plots.draw(PLOT_ALL)

    def _describe_run(self, catchment, result, placement):
        """The inputs behind a result, as ``(name, value)`` rows for the export.

        A ring table on its own cannot be audited: the same geometry gives a
        different PMP under a different MAF, duration or terrain split, so the
        export has to carry them.
        """
        inputs = result.inputs
        where = (
            [
                ("Catchment layer", catchment.layer_name),
                ("Selected features only", "yes" if catchment.selected_only else "no"),
                ("CRS", catchment.crs.authid()),
                ("Centroid", describe_latlon(catchment.lat, catchment.lon)),
            ]
            if catchment is not None
            else []
        )
        return [
            ("Method", "Areal GSDM (spatial distribution)"),
            *where,
            ("Duration (hr)", f"{inputs.duration_hr:g}"),
            (
                "Terrain",
                f"{inputs.smooth * 100:.0f}% smooth / {inputs.rough * 100:.0f}% rough",
            ),
            ("MAF (Figure 3)", f"{inputs.maf:.2f}"),
            ("MAF source", self.maf.provenance()),
            ("Mean elevation (m)", f"{self.elevation.value():g}"),
            ("EAF (section 4.3)", f"{inputs.eaf:.2f}"),
            ("Search sampling (m)", f"{self.sampling.value():g}"),
            ("Rotation steps", f"{self.rotations.value():d}"),
            ("Outermost ellipse", result.outermost),
            ("Catchment area (km2)", f"{result.catchment_area_km2:.4f}"),
            ("Best fit centre x", f"{placement.cx:.1f}"),
            ("Best fit centre y", f"{placement.cy:.1f}"),
            ("Major axis bearing (deg)", f"{placement.bearing_deg:.1f}"),
            ("PMP unrounded (mm)", f"{result.pmp_mm:.1f}"),
            ("PMP (mm)", f"{round_pmp(result.pmp_mm)}"),
        ]

    def export_csv(self):
        if self._table:
            export_csv(self, self._table, "areal_gsdm_results.csv")

    #: Kept so the tests and the other tabs share one spelling.
    _export = export_csv

    def _copy(self):
        if self._table:
            copy_to_clipboard(self._table)


def _preview_summary(result, placement) -> str:
    """The final-view caption, mirroring the tab's summary in plain text."""
    area = dict(zip(ellipses.LABELS, ellipses.AREAS_KM2))[result.outermost]
    return "\n".join(
        [
            f"Best fit: ellipse {result.outermost} ({area:g} km²)   "
            f"catchment {result.catchment_area_km2:.2f} km²",
            f"bearing {placement.bearing_deg:.1f}°   "
            f"score {placement.score:,.0f} mm·km²",
            f"{result.inputs.duration_hr:g}-hour PMP {round_pmp(result.pmp_mm)} mm",
        ]
    )

