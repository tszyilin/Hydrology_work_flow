"""Tab 3: GTSMR and GSAM, the long-duration methods.

GTSMR (Generalised Tropical Storm Method, Revised) covers 24 to 120 hours;
GSAM (Generalised Southeast Australia Method) covers 24 to 96 and has no decay
amplitude factor.  Which of them applies is a matter of where the catchment is,
so the zone lookup drives the tab: the method a catchment's centroid does not
fall in is disabled rather than left available to be run wrongly.

Both methods take their moisture adjustment as the catchment's extreme
precipitable water over a standard value.  The standards differ between the two
guidebooks -- GTSMR uses 120.0 mm summer and 82.3 mm winter (section 2.3.1),
GSAM 80.8 mm summer and 71.0 mm autumn (section 2.3) -- which is easy to get
wrong by carrying one pair across, so each method carries its own.

The EPW, TAF and DAF grids are sampled at the catchment centroid.  The GTSMR
guidebook asks for an average over the catchment outline; the centroid value is
what the worked spreadsheets use, and it reproduces them to within 0.03%.  That
note is on the tab rather than only in this docstring, because it is a choice a
reviewer should be able to see.
"""

from __future__ import annotations

from ..core import depth as depth_core
from ..core import grids as grids_lookup
from ..core import zones as zones_lookup
from ..qt_compat import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
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
    PlotPanel,
    ResultTable,
    annotate_points,
    apply_style,
    build_shell,
    copy_to_clipboard,
    describe_latlon,
    export_cases_xlsx,
    export_csv,
    fill_table,
    provenance_label,
    input_pane,
    scrollable,
    style_axes,
    style_table,
    wrap_form,
)

#: GSAM guidebook section 2.3.  Different from GTSMR's, deliberately.
GSAM_STANDARD_SUMMER = 80.8
GSAM_STANDARD_AUTUMN = 71.0

#: Wrapped over two lines: beside a full inputs column the table is narrow
#: enough that single-line headers elide, and a header reading "overning (m"
#: is worse than one that takes an extra row.
HEADERS = [
    "Duration (hr)",
    "Summer (mm)",
    "Winter / autumn (mm)",
    "Governing (mm)",
]

#: The same headers wrapped over two lines, for the narrow on-screen table.
#: Only the flat ones above are exported.
DISPLAY_HEADERS = [
    "Duration\n(hr)",
    "Summer\n(mm)",
    "Winter /\nautumn (mm)",
    "Governing\n(mm)",
]

PLOT_CASE = "Depth-duration"
PLOT_ALL = "All cases"

#: A colour per case on the comparison plot, cycled.
CASE_COLOURS = ["#0f8b8d", "#B8672A", "#14304d", "#7a5ba6", "#1a7a1a", "#a80000"]


class _FactorRow:
    """One sampled grid factor: a spin box and the value it was filled with."""

    def __init__(self, label, minimum, maximum, decimals, step, suffix="", tooltip=""):
        self.label = label
        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        if suffix:
            self.spin.setSuffix(suffix)
        if tooltip:
            self.spin.setToolTip(tooltip)
        self._auto: float | None = None
        self.overridden = False
        self.spin.valueChanged.connect(self._on_edited)

    def _on_edited(self, value):
        if self._auto is None or abs(value - self._auto) > 1e-9:
            self.overridden = True

    def set_sampled(self, value: float | None, force: bool = False):
        if value is None:
            return
        if self.overridden and not force:
            return
        self._auto = value
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)
        self.overridden = False

    def set_locked(self, locked: bool):
        """Make the field read-only, or hand it back to the user.

        Read-only rather than disabled: a disabled spin box greys its value
        out, and these are the values the engineer most needs to be able to
        read. The stepper arrows go with the lock, so there is no control
        that looks like it should work and does not.
        """
        self.spin.setReadOnly(locked)
        self.spin.setButtonSymbols(
            QDoubleSpinBox.ButtonSymbols.NoButtons
            if locked
            else QDoubleSpinBox.ButtonSymbols.UpDownArrows
        )
        self.spin.setStyleSheet("background: #f1f3f3;" if locked else "")

    def set_stored(self, value: float, overridden: bool):
        """Restore a value from a case, override flag and all.

        Distinct from :meth:`set_sampled`, which refuses to overwrite a value
        the user typed. Here the stored value *is* the truth for that case.
        """
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)
        self.overridden = overridden
        if not overridden:
            self._auto = value

    def value(self) -> float:
        return self.spin.value()

    def provenance(self) -> str:
        if self.overridden:
            return "entered by hand"
        return "sampled at centroid" if self._auto is not None else "default"


class GtsmrTab(QWidget):
    """GTSMR and GSAM, long-duration PMP."""

    def __init__(self, parent=None):
        super().__init__(parent)
        #: Set while inputs are being written from a case, so the widget
        #: signals that fire do not write straight back into it.
        self._loading = False
        self._current = None
        self._zone_reading: dict | None = None
        self._results: list = []
        self._build()
        apply_style(self)
        self.picker.refresh()
        self.cases.add_case("Case 1", self._capture())
        self._current = self.cases.current()

    # ------------------------------------------------------------- build

    def _build(self):
        # Two input columns: the catchment and what was read from it on the
        # left, the two method blocks beside it. One column held all of it
        # until the sampled-values panel arrived, and it had become a
        # scroll-hunt.
        inputs = input_pane(self._inputs_column(), self._buttons(), width=330)
        methods = scrollable(self._methods_column(), width=350)

        self.cases = CaseSidebar()
        self.cases.currentCaseChanged.connect(self._on_case_changed)
        self.cases.casesChanged.connect(self._refresh_all_plot)
        # Auto per-feature cases: when the picker enumerates the layer's
        # features, rebuild the Cases sidebar to mirror it.
        self.picker.featureCatchmentsChanged.connect(self._on_feature_catchments)

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
                middle=methods,
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
        column.addWidget(self._zone_group())
        column.addStretch(1)
        return holder

    def _methods_column(self):
        """The editable per-method inputs, in a column of their own.

        The two guidebooks want eleven numbers between them. Beside the
        catchment they crowded everything else off the screen; here they have
        room, and the left column stays a summary you can read at a glance.
        """
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._gtsmr_group())
        column.addWidget(self._gsam_group())
        column.addStretch(1)
        return holder

    def _zone_group(self):
        group = QGroupBox("Applicable methods")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.use_gtsmr = QCheckBox("GTSMR")
        self.use_gsam = QCheckBox("GSAM")
        self.resample_button = QPushButton("Resample at centroid")
        self.resample_button.setObjectName("lookupButton")
        self.resample_button.clicked.connect(lambda: self._sample(force=True))
        self.use_gtsmr.toggled.connect(self._touched)
        self.use_gsam.toggled.connect(self._touched)
        row.addWidget(self.use_gtsmr)
        row.addWidget(self.use_gsam)
        row.addWidget(self.resample_button)
        row.addStretch(1)
        layout.addLayout(row)

        # Small-area handling for A < 1 km². Off = clamp at 1 km² (Bureau's
        # Toolbox website / guidebook default). On = log-linearly extrapolate
        # off the 1 & 1.5 km² rows (matches the PSM PMP_Estimation workbook).
        small_row = QHBoxLayout()
        self.extrapolate_below_min = QCheckBox(
            "Extrapolate below 1 km² (log-linear from 1 & 1.5 km² rows)"
        )
        self.extrapolate_below_min.setToolTip(
            "Off: use the 1 km² depth for any smaller catchment (Bureau website "
            "and GTSMR/GSAM guidebook default).\n"
            "On: log-linearly extrapolate off the two smallest tabulated rows "
            "(matches the PSM PMP_Estimation workbook)."
        )
        self.extrapolate_below_min.toggled.connect(self._touched)
        small_row.addWidget(self.extrapolate_below_min)
        small_row.addStretch(1)
        layout.addLayout(small_row)

        self.zone_note = provenance_label()
        layout.addWidget(self.zone_note)

        note = provenance_label(
            "Grid factors are sampled at the catchment centroid. The GTSMR "
            "guidebook averages them over the catchment outline; the centroid "
            "value is what the worked spreadsheets use and reproduces them to "
            "within 0.03%. Type over any field to use your own value."
        )
        layout.addWidget(note)
        return group

    def _gtsmr_group(self):
        group = QGroupBox("GTSMR  (24–120 hr)")
        form = QFormLayout(group)
        wrap_form(form)

        self.gtsmr_zone_s = QLabel("—")
        self.gtsmr_zone_w = QLabel("—")
        form.addRow("Summer zone", self.gtsmr_zone_s)
        form.addRow("Winter zone", self.gtsmr_zone_w)

        self.gtsmr_epw_s = _FactorRow(
            "EPW summer", 0.0, 300.0, 3, 1.0, " mm",
            "Average extreme precipitable water, summer, from the Bureau's "
            "annual grid.",
        )
        self.gtsmr_epw_w = _FactorRow(
            "EPW winter", 0.0, 300.0, 3, 1.0, " mm",
            "Average extreme precipitable water, winter.",
        )
        self.gtsmr_std_s = _FactorRow(
            "EPW standard summer", 1.0, 300.0, 2, 1.0, " mm",
            "GTSMR guidebook section 2.3.1: 120.0 mm.",
        )
        self.gtsmr_std_w = _FactorRow(
            "EPW standard winter", 1.0, 300.0, 2, 1.0, " mm",
            "GTSMR guidebook section 2.3.1: 82.3 mm.",
        )
        self.gtsmr_std_s.spin.setValue(grids_lookup.EPW_STANDARD_SUMMER)
        self.gtsmr_std_w.spin.setValue(grids_lookup.EPW_STANDARD_WINTER)
        self.gtsmr_taf = _FactorRow(
            "TAF", 0.0, 5.0, 4, 0.01, "", "Topographic adjustment factor."
        )
        self.gtsmr_daf = _FactorRow(
            "DAF", 0.0, 5.0, 4, 0.01, "", "Decay amplitude factor. GTSMR only."
        )

        form.addRow("EPW summer", self.gtsmr_epw_s.spin)
        form.addRow("EPW standard (summer)", self.gtsmr_std_s.spin)
        form.addRow("EPW winter", self.gtsmr_epw_w.spin)
        form.addRow("EPW standard (winter)", self.gtsmr_std_w.spin)
        form.addRow("TAF", self.gtsmr_taf.spin)
        form.addRow("DAF", self.gtsmr_daf.spin)
        self.gtsmr_maf_label = QLabel("")
        self.gtsmr_maf_label.setObjectName("provenance")
        form.addRow("MAF", self.gtsmr_maf_label)

        # Locked by default, following the Toolbox website: these six numbers
        # come off the Bureau's grids and the guidebook, and a stray scroll
        # over a spin box should not quietly replace one.
        self.lock_button = QPushButton()
        self.lock_button.setObjectName("lookupButton")
        self.lock_button.setCheckable(True)
        self.lock_button.toggled.connect(self._on_lock_toggled)
        form.addRow("", self.lock_button)
        self.lock_note = provenance_label()
        form.addRow("", self.lock_note)
        for row in (self.gtsmr_epw_s, self.gtsmr_epw_w, self.gtsmr_std_s,
                    self.gtsmr_std_w):
            row.spin.valueChanged.connect(self._update_maf_labels)
        for row in (self.gtsmr_epw_s, self.gtsmr_epw_w, self.gtsmr_std_s,
                    self.gtsmr_std_w, self.gtsmr_taf, self.gtsmr_daf):
            row.spin.valueChanged.connect(self._touched)
        self.gtsmr_group = group
        self._apply_lock()
        return group

    def _gtsmr_locked_rows(self):
        """The six numbers that come off the Bureau's grids and guidebook."""
        return (
            self.gtsmr_epw_s, self.gtsmr_std_s,
            self.gtsmr_epw_w, self.gtsmr_std_w,
            self.gtsmr_taf, self.gtsmr_daf,
        )

    def locked(self) -> bool:
        """True when the grid-derived fields are read-only."""
        return not self.lock_button.isChecked()

    def _on_lock_toggled(self, _unlocked: bool):
        self._apply_lock()
        self._touched()

    def _apply_lock(self):
        """Reflect the lock in the fields, the button and the note."""
        locked = self.locked()
        for row in self._gtsmr_locked_rows():
            row.set_locked(locked)
        self.lock_button.setText(
            "\U0001F512 Unlock to override"
            if locked
            else "\U0001F513 Overridden \u2014 relock"
        )
        catchment = self.picker.catchment() if hasattr(self, "picker") else None
        where = (
            describe_latlon(catchment.lat, catchment.lon)
            if catchment is not None
            else "the catchment centroid"
        )
        self.lock_note.setText(
            f"Read at {where}, so these are locked to the "
            "Bureau's data. Unlock only to substitute a value you derived "
            "yourself \u2014 for example an EPW averaged over the catchment "
            "outline, which is what \u00A72.3.1 actually asks for."
            if locked
            else "Unlocked \u2014 edits here replace the Bureau's gridded "
            "values. Resampling at the centroid will refill them."
        )

    def _gsam_group(self):
        group = QGroupBox("GSAM  (24–96 hr)")
        form = QFormLayout(group)
        wrap_form(form)

        self.gsam_zone_s = QLabel("—")
        self.gsam_zone_a = QLabel("—")
        form.addRow("Summer zone", self.gsam_zone_s)
        form.addRow("Autumn zone", self.gsam_zone_a)

        self.gsam_epw_s = _FactorRow("EPW summer", 0.0, 300.0, 3, 1.0, " mm")
        self.gsam_epw_a = _FactorRow("EPW autumn", 0.0, 300.0, 3, 1.0, " mm")
        self.gsam_std_s = _FactorRow(
            "EPW standard summer", 1.0, 300.0, 2, 1.0, " mm",
            "GSAM guidebook section 2.3: 80.8 mm — not GTSMR's 120.0.",
        )
        self.gsam_std_a = _FactorRow(
            "EPW standard autumn", 1.0, 300.0, 2, 1.0, " mm",
            "GSAM guidebook section 2.3: 71.0 mm — not GTSMR's 82.3.",
        )
        self.gsam_std_s.spin.setValue(GSAM_STANDARD_SUMMER)
        self.gsam_std_a.spin.setValue(GSAM_STANDARD_AUTUMN)
        self.gsam_taf = _FactorRow("TAF", 0.0, 5.0, 4, 0.01)

        form.addRow("EPW summer", self.gsam_epw_s.spin)
        form.addRow("EPW standard (summer)", self.gsam_std_s.spin)
        form.addRow("EPW autumn", self.gsam_epw_a.spin)
        form.addRow("EPW standard (autumn)", self.gsam_std_a.spin)
        form.addRow("TAF", self.gsam_taf.spin)
        form.addRow("", QLabel("No decay amplitude factor — GSAM has none."))
        self.gsam_maf_label = QLabel("")
        self.gsam_maf_label.setObjectName("provenance")
        form.addRow("MAF", self.gsam_maf_label)

        # Lock the five grid-derived / guidebook GSAM fields the same way
        # the GTSMR block does its six. Unlock to substitute a hand-derived
        # value (e.g. an EPW averaged over the catchment outline).
        self.gsam_lock_button = QPushButton()
        self.gsam_lock_button.setObjectName("lookupButton")
        self.gsam_lock_button.setCheckable(True)
        self.gsam_lock_button.toggled.connect(self._on_gsam_lock_toggled)
        form.addRow("", self.gsam_lock_button)
        self.gsam_lock_note = provenance_label()
        form.addRow("", self.gsam_lock_note)

        for row in (self.gsam_epw_s, self.gsam_epw_a, self.gsam_std_s,
                    self.gsam_std_a):
            row.spin.valueChanged.connect(self._update_maf_labels)
        for row in (self.gsam_epw_s, self.gsam_epw_a, self.gsam_std_s,
                    self.gsam_std_a, self.gsam_taf):
            row.spin.valueChanged.connect(self._touched)
        self.gsam_group = group
        self._apply_gsam_lock()
        return group

    def _gsam_locked_rows(self):
        return (
            self.gsam_epw_s, self.gsam_std_s,
            self.gsam_epw_a, self.gsam_std_a,
            self.gsam_taf,
        )

    def gsam_locked(self) -> bool:
        return not self.gsam_lock_button.isChecked()

    def _on_gsam_lock_toggled(self, _unlocked: bool):
        self._apply_gsam_lock()
        self._touched()

    def _apply_gsam_lock(self):
        locked = self.gsam_locked()
        for row in self._gsam_locked_rows():
            row.set_locked(locked)
        self.gsam_lock_button.setText(
            "\U0001F512 Unlock to override"
            if locked
            else "\U0001F513 Overridden — relock"
        )
        catchment = self.picker.catchment() if hasattr(self, "picker") else None
        where = (
            describe_latlon(catchment.lat, catchment.lon)
            if catchment is not None
            else "the catchment centroid"
        )
        self.gsam_lock_note.setText(
            f"Read at {where}, so these are locked to the "
            "Bureau's GSAM data. Unlock only to substitute a value you "
            "derived yourself — for example an EPW averaged over the "
            "catchment outline, which is what §2.3 actually asks for."
            if locked
            else "Unlocked — edits here replace the Bureau's gridded "
            "values. Resampling at the centroid will refill them."
        )

    def _buttons(self):
        row = QHBoxLayout()
        self.run_button = QPushButton("Calculate")
        self.run_button.clicked.connect(self.run)
        self.run_all_button = QPushButton("Calculate all cases")
        self.run_all_button.clicked.connect(self.run_all)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_csv)
        self.export_xlsx_button = QPushButton("Export Excel…")
        self.export_xlsx_button.setEnabled(False)
        self.export_xlsx_button.clicked.connect(self.export_xlsx)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)
        grid = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(self.run_button)
        top.addWidget(self.run_all_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.export_button)
        bottom.addWidget(self.export_xlsx_button)
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
        self.table.setHorizontalHeaderLabels(DISPLAY_HEADERS)
        style_table(self.table)
        layout.addWidget(self.table, stretch=1)

        self.warnings = QTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(70)
        self.warnings.setVisible(False)
        layout.addWidget(self.warnings)
        return group

    # ----------------------------------------------------------- signals

    def _on_catchment(self, catchment: Catchment | None):
        self._sample()
        self._touched()

    def _sample(self, force: bool = False):
        """Read the zones and grids at the centroid and fill the fields."""
        catchment = self.picker.catchment()
        if catchment is None:
            self.zone_note.setText("")
            return

        try:
            zoning = zones_lookup.lookup(catchment.lat, catchment.lon)
        except ValueError as exc:
            self._zone_reading = None
            self.zone_note.setText(str(exc))
            self._set_enabled(False, False)
            return

        self._zone_reading = zoning
        self._show_zones(zoning)

        parts = [
            f"{', '.join(zoning['zones']) or 'no PMP zone'} at "
            f"{describe_latlon(catchment.lat, catchment.lon)}."
        ]
        parts += list(zoning.get("notes") or [])
        self.zone_note.setText(" ".join(parts))

        try:
            sampled = self._sample_grids(catchment)
        except ValueError as exc:
            self.zone_note.setText(f"{self.zone_note.text()}  {exc}")
            return

        self.gtsmr_epw_s.set_sampled(sampled["epw_summer"], force)
        self.gtsmr_epw_w.set_sampled(sampled["epw_winter"], force)
        self.gtsmr_taf.set_sampled(sampled["taf"], force)
        self.gtsmr_daf.set_sampled(sampled["daf"], force)
        # GSAM has its own grids (Oct 2006 GSAM CD): summer EPW = annual EPW,
        # autumn EPW is a separate grid, and TAF is a GSAM-specific grid too.
        # Fall back to the GTSMR value only when the GSAM grid does not cover
        # this point.
        self.gsam_epw_s.set_sampled(
            sampled.get("gsam_epw_summer") or sampled["epw_summer"], force
        )
        self.gsam_epw_a.set_sampled(
            sampled.get("gsam_epw_autumn") or sampled["epw_winter"], force
        )
        self.gsam_taf.set_sampled(
            sampled.get("gsam_taf") or sampled["taf"], force
        )
        self._apply_lock()
        self._apply_gsam_lock()
        self._update_maf_labels()
        self._touched()

    def _sample_grids(self, catchment):
        """Average every grid over the catchment polygon (§2.3 wording).

        Falls back to a single centroid sample when the catchment has no
        polygon (external-lat/lon mode) or the polygon covers no grid cell
        centres — in either case the centroid value is what the Bureau's
        worked spreadsheets use, so parity with them is preserved.
        """
        geometry = getattr(catchment, "geometry", None)
        crs = getattr(catchment, "crs", None)
        if geometry is None or crs is None:
            return grids_lookup.lookup(catchment.lat, catchment.lon)
        from .. import qgis_bridge
        points = qgis_bridge.catchment_grid_points(
            geometry, crs,
            cellsize_deg=grids_lookup.CELLSIZE,
            top_lat=grids_lookup.TOP_LAT,
            left_lon=grids_lookup.LEFT_LON,
        )
        if not points:
            return grids_lookup.lookup(catchment.lat, catchment.lon)
        return grids_lookup.average_at_points(points)

    def _show_zones(self, zoning: dict):
        """Put a zone reading on screen: labels, and which methods apply.

        Split out of :meth:`_sample` because switching to a stored case has to
        restore exactly this, without re-reading the zone file.
        """
        self._set_enabled(zoning["gtsmr_applicable"], zoning["gsam_applicable"])
        self.gtsmr_zone_s.setText(zoning["gtsmr_summer"] or "—")
        self.gtsmr_zone_w.setText(zoning["gtsmr_winter"] or "—")
        self.gsam_zone_s.setText(zoning["gsam_summer"] or "—")
        self.gsam_zone_a.setText(zoning["gsam_autumn"] or "—")

    def _set_enabled(self, gtsmr: bool, gsam: bool):
        self.use_gtsmr.setChecked(gtsmr)
        self.use_gtsmr.setEnabled(gtsmr)
        self.gtsmr_group.setEnabled(gtsmr)
        self.use_gsam.setChecked(gsam)
        self.use_gsam.setEnabled(gsam)
        self.gsam_group.setEnabled(gsam)

    def _update_maf_labels(self, *_args):
        def ratio(a, b):
            return a.value() / b.value() if b.value() else float("nan")

        self.gtsmr_maf_label.setText(
            f"summer {ratio(self.gtsmr_epw_s, self.gtsmr_std_s):.4f}   "
            f"winter {ratio(self.gtsmr_epw_w, self.gtsmr_std_w):.4f}"
        )
        self.gsam_maf_label.setText(
            f"summer {ratio(self.gsam_epw_s, self.gsam_std_s):.4f}   "
            f"autumn {ratio(self.gsam_epw_a, self.gsam_std_a):.4f}"
        )


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

    # ------------------------------------------------------------- cases

    def _factor_rows(self) -> dict:
        """Every editable grid factor, by the name a case stores it under."""
        return {
            "gtsmr_epw_s": self.gtsmr_epw_s, "gtsmr_epw_w": self.gtsmr_epw_w,
            "gtsmr_std_s": self.gtsmr_std_s, "gtsmr_std_w": self.gtsmr_std_w,
            "gtsmr_taf": self.gtsmr_taf, "gtsmr_daf": self.gtsmr_daf,
            "gsam_epw_s": self.gsam_epw_s, "gsam_epw_a": self.gsam_epw_a,
            "gsam_std_s": self.gsam_std_s, "gsam_std_a": self.gsam_std_a,
            "gsam_taf": self.gsam_taf,
        }

    def _capture(self) -> dict:
        """The current widget state, as a plain dict for a case to hold.

        The override flag travels with each factor: whether a value was
        sampled or typed is part of the case, and it is what the export
        reports as provenance.
        """
        # Preserve the case's FeatureCatchment (auto mode) — it never lives
        # in a widget, so it would be lost if we rebuilt the dict from
        # scratch on every _touched() re-capture.
        fc = None
        if self._current is not None:
            fc = self._current.inputs.get("_feature_catchment")
        base = {
            "layer": self.picker.layer_combo.currentLayer(),
            "selected_only": self.picker.selected_only.isChecked(),
            "use_gtsmr": self.use_gtsmr.isChecked(),
            "use_gsam": self.use_gsam.isChecked(),
            "extrapolate_below_min": self.extrapolate_below_min.isChecked(),
            "factors": {
                name: (row.value(), row.overridden)
                for name, row in self._factor_rows().items()
            },
            "zone_reading": self._zone_reading,
            "zone_note": self.zone_note.text(),
            "gtsmr_unlocked": self.lock_button.isChecked(),
            "gsam_unlocked": self.gsam_lock_button.isChecked(),
        }
        if fc is not None:
            base["_feature_catchment"] = fc
        return base

    def _on_feature_catchments(self, fcs):
        """Rebuild the Cases sidebar when the picker enumerates a layer.

        ``fcs`` is a list of FeatureCatchment (auto mode on) or ``None``
        (auto mode off, restore normal buttons).
        """
        if fcs is None:
            self.cases.set_auto_mode(False)
            return
        self.cases.set_auto_mode(True)
        # Wipe existing cases and rebuild — one per feature. Each case
        # remembers its FeatureCatchment (kept under an underscore key so
        # the workbook writer skips it — QgsGeometry is not serialisable).
        base_inputs = self._capture()
        base_inputs.pop("_feature_catchment", None)
        named = []
        for fc in fcs:
            inputs = dict(base_inputs)
            inputs["_feature_catchment"] = fc
            label = f"{fc.name} ({fc.summary.area_km2:,.3f} km²)"
            named.append((label, inputs))
        self.cases.reset(named)
        # ``reset`` selects row 0; make sure the picker's catchment matches.
        current = self.cases.current()
        if current is not None:
            fc = current.inputs.get("_feature_catchment")
            if fc is not None:
                self.picker.set_current_catchment_from_feature(fc)

    def _apply(self, inputs: dict):
        """Write a case's inputs back into the widgets."""
        self._loading = True
        try:
            # In auto mode the case carries a specific feature; push it to
            # the picker so ``picker.catchment()`` reflects that feature.
            fc = inputs.get("_feature_catchment")
            if fc is not None:
                self.picker.set_current_catchment_from_feature(fc)
            if inputs.get("layer") is not None:
                self.picker.layer_combo.setLayer(inputs["layer"])
            self.picker.selected_only.setChecked(bool(inputs.get("selected_only")))
            self._zone_reading = inputs.get("zone_reading")
            self.zone_note.setText(inputs.get("zone_note", ""))
            if self._zone_reading:
                self._show_zones(self._zone_reading)
            rows = self._factor_rows()
            for name, stored in (inputs.get("factors") or {}).items():
                row = rows.get(name)
                if row is not None:
                    row.set_stored(*stored)
            self.use_gtsmr.setChecked(bool(inputs.get("use_gtsmr")))
            self.use_gsam.setChecked(bool(inputs.get("use_gsam")))
            self.extrapolate_below_min.setChecked(
                bool(inputs.get("extrapolate_below_min"))
            )
            self.lock_button.setChecked(bool(inputs.get("gtsmr_unlocked")))
            self._apply_lock()
            self.gsam_lock_button.setChecked(bool(inputs.get("gsam_unlocked")))
            self._apply_gsam_lock()
            self._update_maf_labels()
        finally:
            self._loading = False

    def _touched(self, *_args):
        if self._loading or self._current is None:
            return
        self._current.inputs = self._capture()

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
        self._results = case.result or []
        if case.table is None:
            self.table.setRowCount(0)
            self.summary.setText("Not calculated yet.")
            self.warnings.setVisible(False)
            self.export_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.export_xlsx_button.setEnabled(
                any(c.table is not None for c in self.cases.cases())
            )
            self.plots.set_data(PLOT_CASE, None)
            ax = self.plots.page(PLOT_CASE)
            if ax is not None:
                style_axes(ax)
                self.plots.draw(PLOT_CASE)
            return
        fill_table(self.table, case.table)
        self.summary.setText(case.summary)
        self.warnings.setVisible(bool(case.table.warnings))
        self.warnings.setPlainText(
            "\n".join("• " + w for w in case.table.warnings)
        )
        self.export_button.setEnabled(True)
        self.export_xlsx_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self._plot_case(case)

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
        """Calculate every case, then come back to the current one."""
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
        """Run one case, storing its results on it. True if it ran."""
        catchment = self.picker.catchment()
        if catchment is None:
            if complain:
                QMessageBox.warning(self, "No catchment", self.picker.error())
            return False
        if not (self.use_gtsmr.isChecked() or self.use_gsam.isChecked()):
            if complain:
                QMessageBox.warning(
                    self,
                    "No method selected",
                    "Neither GTSMR nor GSAM is selected. The zone lookup enables "
                    "whichever applies at the catchment centroid.",
                )
            return False
        zoning = self._zone_reading or {}

        results = []
        try:
            extrapolate = self.extrapolate_below_min.isChecked()
            if self.use_gtsmr.isChecked():
                results.append(
                    depth_core.calc_gtsmr(
                        catchment.area_km2,
                        zoning.get("gtsmr_summer"),
                        zoning.get("gtsmr_winter"),
                        self.gtsmr_epw_s.value(),
                        self.gtsmr_std_s.value(),
                        self.gtsmr_epw_w.value(),
                        self.gtsmr_std_w.value(),
                        self.gtsmr_taf.value(),
                        self.gtsmr_daf.value(),
                        extrapolate_below_min=extrapolate,
                    )
                )
            if self.use_gsam.isChecked():
                results.append(
                    depth_core.calc_gsam(
                        catchment.area_km2,
                        zoning.get("gsam_summer"),
                        zoning.get("gsam_autumn"),
                        self.gsam_epw_s.value(),
                        self.gsam_std_s.value(),
                        self.gsam_epw_a.value(),
                        self.gsam_std_a.value(),
                        self.gsam_taf.value(),
                        extrapolate_below_min=extrapolate,
                    )
                )
        except ValueError as exc:
            if complain:
                QMessageBox.critical(self, "Cannot run", str(exc))
            return False

        case.result = results
        case.table, summary = self._render(catchment, results)
        case.summary = summary
        return True

    def _render(self, catchment, results):
        """Build the results table and the summary line for a finished run."""
        rows: list[list[str]] = []
        warnings: list[str] = []
        for result in results:
            warnings.extend(result.warnings)
            seasons = " / ".join(s.label for s in result.seasons)
            rows.append([f"— {result.method} ({seasons}) —", "", "", ""])
            first = result.seasons[0]
            # A method can come back with one season: the GTSMR inland zone has
            # no winter equivalent, and depth.calc_gtsmr leaves it out rather
            # than substituting the coastal one.
            second = result.seasons[1] if len(result.seasons) > 1 else None
            for d in first.by_duration:
                other = second.depth_at(d.duration_hr) if second else None
                governing = max(d.pmp_mm, other or 0.0)
                rows.append(
                    [
                        f"{d.duration_hr:g}",
                        f"{d.pmp_mm:,.0f}",
                        f"{other:,.0f}" if other is not None else "—",
                        f"{governing:,.0f}",
                    ]
                )

        for note in (self._zone_reading or {}).get("notes", []):
            warnings.append(note)

        governing_result = max(results, key=lambda r: r.pmp_mm)
        table = ResultTable(
            headers=HEADERS,
            display_headers=DISPLAY_HEADERS,
            rows=rows,
            run_inputs=self._describe_run(catchment, results, governing_result),
            warnings=warnings,
            title="GTSMR / GSAM results",
        )

        pieces = [
            f"{r.method} {r.pmp_mm:,.0f} mm at {r.controlling_duration_hr:g} h "
            f"({r.governing_season})"
            for r in results
        ]
        summary = (
            f"<b>Governing: {governing_result.method} "
            f"{governing_result.pmp_mm:,.0f} mm at "
            f"{governing_result.controlling_duration_hr:g} hours</b> "
            f"({governing_result.governing_season}) over "
            f"{catchment.area_km2:,.2f} km\u00b2 &nbsp;\u2022&nbsp; storm volume "
            f"{governing_result.volume_m3:,.0f} m\u00b3<br>"
            + " &nbsp;\u2022&nbsp; ".join(pieces)
        )
        return table, summary

    # -------------------------------------------------------------- plots

    def _plot_case(self, case):
        """This case: a line per method and season, values labelled."""
        ax = self.plots.page(PLOT_CASE)
        if ax is None or not case.result:
            return
        colours = {"GTSMR": "#0f8b8d", "GSAM": "#B8672A"}
        styles = {0: "-", 1: "--"}
        for result in case.result:
            for i, season in enumerate(result.seasons):
                xs = [d.duration_hr for d in season.by_duration]
                ys = [d.pmp_mm for d in season.by_duration]
                ax.plot(
                    xs, ys,
                    marker="o",
                    linestyle=styles.get(i, ":"),
                    color=colours.get(result.method, "#14304d"),
                    label=f"{result.method} {season.label}",
                )
                # Only the governing season is labelled: every season labelled
                # turns the chart into a wall of numbers.
                if season.label == result.governing_season:
                    annotate_points(ax, xs, ys)
        ax.set_xlabel("Duration (hours)")
        ax.set_ylabel("PMP (mm)")
        ax.set_title(case.name, fontsize=9, loc="left")
        ax.legend(frameon=False, fontsize=8)
        style_axes(ax)
        self.plots.set_data(PLOT_CASE, case.table)
        self.plots.draw(PLOT_CASE)

    def _refresh_all_plot(self, *_args):
        """Every calculated case on one axes, governing season only.

        Comparing cases is comparing the number that governs, so the other
        season is left off: it is in each case's own plot and in the table.
        """
        ax = self.plots.page(PLOT_ALL)
        if ax is None:
            return
        done = [c for c in self.cases.cases() if c.result]

        durations: list[float] = []
        for i, case in enumerate(done):
            governing = max(case.result, key=lambda r: r.pmp_mm)
            season = governing.season(governing.governing_season)
            xs = [d.duration_hr for d in season.by_duration]
            ys = [d.pmp_mm for d in season.by_duration]
            ax.plot(
                xs, ys,
                marker="o",
                color=CASE_COLOURS[i % len(CASE_COLOURS)],
                label=f"{case.name} ({governing.method} {season.label})",
            )
            durations = sorted(set(durations) | set(xs))
            if len(done) == 1:
                annotate_points(ax, xs, ys)

        ax.set_xlabel("Duration (hours)")
        ax.set_ylabel("Governing PMP (mm)")
        if done:
            ax.legend(frameon=False, fontsize=8)
        else:
            ax.set_title("No case has been calculated yet.", fontsize=9, loc="left")
        style_axes(ax)

        if done and durations:
            headers = ["Duration (hr)"] + [c.name for c in done]
            rows = []
            for duration in durations:
                row = [f"{duration:g}"]
                for case in done:
                    governing = max(case.result, key=lambda r: r.pmp_mm)
                    season = governing.season(governing.governing_season)
                    value = season.depth_at(duration)
                    row.append(f"{value:,.0f}" if value is not None else "")
                rows.append(row)
            self.plots.set_data(PLOT_ALL, ResultTable(
                headers=headers,
                rows=rows,
                run_inputs=[("Plot", "Governing PMP, all calculated cases")],
                warnings=[],
                title="All cases",
            ))
        else:
            self.plots.set_data(PLOT_ALL, None)
        self.plots.draw(PLOT_ALL)

    def _describe_run(self, catchment, results, governing):
        rows = [
            ("Method", " + ".join(r.method for r in results)),
            ("Catchment layer", catchment.layer_name),
            ("Selected features only", "yes" if catchment.selected_only else "no"),
            ("CRS", catchment.crs.authid()),
            ("Area (km2)", f"{catchment.area_km2:.4f}"),
            ("Centroid", describe_latlon(catchment.lat, catchment.lon)),
            ("Centroid lat", f"{catchment.lat:.5f}"),
            ("Centroid lon", f"{catchment.lon:.5f}"),
            ("Grid sampling", "at the catchment centroid"),
            ("Zones", ", ".join((self._zone_reading or {}).get("zones", []))),
        ]
        for result in results:
            if result.method == "GTSMR":
                rows += [
                    ("GTSMR summer zone", _zone_of(result, "summer")),
                    ("GTSMR winter zone", _zone_of(result, "winter")),
                    ("GTSMR EPW summer (mm)", f"{self.gtsmr_epw_s.value():.3f}"),
                    ("GTSMR EPW summer source", self.gtsmr_epw_s.provenance()),
                    ("GTSMR EPW standard summer (mm)", f"{self.gtsmr_std_s.value():g}"),
                    ("GTSMR EPW winter (mm)", f"{self.gtsmr_epw_w.value():.3f}"),
                    ("GTSMR EPW winter source", self.gtsmr_epw_w.provenance()),
                    ("GTSMR EPW standard winter (mm)", f"{self.gtsmr_std_w.value():g}"),
                    ("GTSMR TAF", f"{self.gtsmr_taf.value():.4f}"),
                    ("GTSMR DAF", f"{self.gtsmr_daf.value():.4f}"),
                ]
            else:
                rows += [
                    ("GSAM summer zone", _zone_of(result, "summer")),
                    ("GSAM autumn zone", _zone_of(result, "autumn")),
                    ("GSAM EPW summer (mm)", f"{self.gsam_epw_s.value():.3f}"),
                    ("GSAM EPW standard summer (mm)", f"{self.gsam_std_s.value():g}"),
                    ("GSAM EPW autumn (mm)", f"{self.gsam_epw_a.value():.3f}"),
                    ("GSAM EPW standard autumn (mm)", f"{self.gsam_std_a.value():g}"),
                    ("GSAM TAF", f"{self.gsam_taf.value():.4f}"),
                ]
            rows += [
                (f"{result.method} governing season", result.governing_season),
                (
                    f"{result.method} controlling duration (hr)",
                    f"{result.controlling_duration_hr:g}",
                ),
                (f"{result.method} PMP (mm)", f"{result.pmp_mm:.0f}"),
            ]
        rows += [
            ("Governing method", governing.method),
            ("Governing PMP (mm)", f"{governing.pmp_mm:.0f}"),
            ("Storm volume (m3)", f"{governing.volume_m3:.0f}"),
        ]
        return rows

    def export_csv(self):
        case = self.cases.current()
        if case is not None and case.table is not None:
            export_csv(self, case.table, "gtsmr_gsam_depth_duration.csv")

    def export_xlsx(self):
        """Save every calculated case to one .xlsx, one sheet per case."""
        export_cases_xlsx(self, self.cases.cases(), "gtsmr_gsam_cases.xlsx")

    #: Kept so the tests and the other tabs share one spelling.
    _export = export_csv

    def _copy(self):
        case = self.cases.current()
        if case is not None and case.table is not None:
            copy_to_clipboard(case.table)


def _zone_of(result, label: str) -> str:
    """The zone a season used, or a dash if that season was not run."""
    season = result.season(label)
    return (season.zone or "") if season is not None else "— not applicable —"
