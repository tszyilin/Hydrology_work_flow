"""What the three tabs share: the catchment picker, derived fields, exports.

The tabs differ in which method they run, but they ask the same three
questions first -- which catchment, how big is it, where is it -- and they all
report a depth against duration and want it exported with its provenance.  All
of that lives here so the three tabs stay thin and cannot drift apart.

The one idea worth stating explicitly is :class:`DerivedField`.  Most of this
plugin's inputs are read off a Bureau figure or grid at the catchment centroid
rather than typed in.  A number that appears in a box by itself is a number
nobody can check, so every such field carries three things: the value, a button
to read it again, and a line saying where it came from.  That provenance line
is then carried into the CSV export, because a depth table under a different
MAF is a different PMP and a table on its own cannot be audited.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox

from ..qt_compat import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFont,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QObject,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    pyqtSignal,
)

#: Above this many features the derived fields stop looking themselves up on
#: every layer change: finding a centroid means dissolving them all, which is
#: cheap for a catchment layer and slow for a whole state's worth of polygons.
#: Past the threshold the "From centroid" buttons are still there.
AUTO_LOOKUP_MAX_FEATURES = 2_000

#: Point size used across the tabs, matching the Drain Design Toolbox.
FONT_POINT_SIZE = 9

_STYLE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "style", "buttons.qss")

#: Table cell tints, reused from the Drain Design Toolbox's results tables.
TINT_EDITABLE = "#eef5f7"
TINT_HIGHLIGHT = "#e4f4f4"
TINT_ERROR = "#ffd6d6"
INK_ERROR = "#a80000"


def apply_style(widget: QWidget) -> None:
    """Apply the plugin's stylesheet and font to one tab.

    Deliberately per-widget and never on ``QApplication``: a stylesheet set on
    the application would repaint every button in QGIS.
    """
    font = QFont()
    font.setPointSize(FONT_POINT_SIZE)
    widget.setFont(font)
    try:
        with open(_STYLE_PATH, "r", encoding="utf-8") as fh:
            widget.setStyleSheet(fh.read())
    except OSError:
        # Styling is decoration; a missing or unreadable qss must not stop the
        # tab from being usable.
        pass


def style_table(table: QTableWidget, stretch: bool = True) -> None:
    """The shared look for a results table: 9 pt, compact rows, read-only."""
    font = QFont()
    font.setPointSize(FONT_POINT_SIZE)
    table.setFont(font)
    table.horizontalHeader().setFont(font)
    table.verticalHeader().setDefaultSectionSize(20)
    table.verticalHeader().setVisible(False)
    # Headers may carry a newline to avoid eliding in a narrow table, so the
    # header row has to be tall enough for two lines of 9 pt.
    table.horizontalHeader().setMinimumHeight(34)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    if stretch:
        table.horizontalHeader().setSectionResizeMode(HeaderStretch)
    else:
        # Wide tables size to their contents and scroll. Sharing the width out
        # equally would elide every header at once, which is worse than a
        # scrollbar the user can see and drag.
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)


HeaderStretch = QHeaderView.ResizeMode.Stretch


def fit_table_height(table: QTableWidget) -> None:
    """Fix a small table to exactly the height of its rows plus its header.

    Worth doing rather than guessing a maximum: a four-row summary that
    scrolls, or clips its last row, reads as broken.
    """
    height = table.horizontalHeader().height() + 2 * table.frameWidth()
    for row in range(table.rowCount()):
        height += table.rowHeight(row)
    table.setMinimumHeight(height)
    table.setMaximumHeight(height)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def cell(text: str, align_right: bool = True, tint: str | None = None,
         bold: bool = False, ink: str | None = None) -> QTableWidgetItem:
    """A results-table cell, with the shared alignment and tinting rules."""
    from ..qt_compat import QColor

    item = QTableWidgetItem(text)
    item.setTextAlignment(
        (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if align_right
        else Qt.AlignmentFlag.AlignCenter
    )
    if tint:
        item.setBackground(QColor(tint))
    if ink:
        item.setForeground(QColor(ink))
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


# --------------------------------------------------------------- catchment


@dataclass
class Catchment:
    """A dissolved catchment, as the tabs see it.

    Mirrors ``qgis_bridge.CatchmentSummary`` but is defined here so the tabs
    can be reasoned about (and type-checked) without importing QGIS.
    """

    area_km2: float
    lat: float
    lon: float
    geometry: object
    crs: object
    feature_count: int
    layer_name: str
    selected_only: bool


class CatchmentPicker(QGroupBox):
    """Choose a catchment layer; report its area and centroid.

    This is the part the Toolbox website cannot do.  There, the engineer reads
    an area and a centroid off a GIS and retypes them into a form.  Here the
    polygon is already open, so the numbers are derived from it and shown with
    enough precision to be checked against whatever produced the layer.

    Emits :attr:`catchmentChanged` with a :class:`Catchment`, or with ``None``
    when the selection is unusable -- no layer, nothing selected, or a
    geographic CRS.  Tabs connect to it rather than to the layer combo, so the
    dissolve happens once per change however many tabs are listening.
    """

    catchmentChanged = pyqtSignal(object)
    # Emitted (list[FeatureCatchment] | None) when the auto "one case per
    # feature" mode is on and the layer / selection / name-attribute has
    # changed. Tabs listen and rebuild their Cases sidebar from it.
    featureCatchmentsChanged = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__("Catchment", parent)
        self._catchment: Catchment | None = None
        self._error = ""
        self._external: tuple[str, float, float] | None = None
        # In auto mode, the current catchment is set by whichever case is
        # active, not by dissolving the layer. Tabs push the case's stored
        # FeatureCatchment in via set_current_feature_catchment().
        self._auto_current_fc = None

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
        self._layer_row_label = QLabel("Layer")
        row.addWidget(self._layer_row_label)
        row.addWidget(self.layer_combo, stretch=1)
        self.selected_only = QCheckBox("Selected features only")
        row.addWidget(self.selected_only)
        layout.addLayout(row)

        # Auto-cases row: one case per feature, with the case name pulled from
        # a chosen attribute. Off by default; tabs can toggle it, and turning
        # it on re-emits featureCatchmentsChanged so cases refresh.
        auto_row = QHBoxLayout()
        self.auto_cases = QCheckBox("Cases: one per feature (auto)")
        self.auto_cases.setToolTip(
            "Auto-populate the Cases list from every polygon feature in the "
            "layer (or from selected features only). Add / Rename / Remove "
            "controls in the Cases sidebar are hidden while this is on — "
            "the layer drives the list."
        )
        self.name_attr_label = QLabel("Name from:")
        self.name_attr_combo = QComboBox()
        self.name_attr_combo.setToolTip(
            "Which attribute names each case. Falls back to the feature ID "
            "when the value is empty."
        )
        auto_row.addWidget(self.auto_cases)
        auto_row.addWidget(self.name_attr_label)
        auto_row.addWidget(self.name_attr_combo, stretch=1)
        layout.addLayout(auto_row)
        # Hide the name-attr controls until auto mode is on.
        self.name_attr_label.setVisible(False)
        self.name_attr_combo.setVisible(False)

        # Manual area — only visible when an external location is active.
        self._ext_row = QHBoxLayout()
        self._ext_row_label = QLabel("Area (km²):")
        self.ext_area = QDoubleSpinBox()
        self.ext_area.setRange(0.0, 1_000_000.0)
        self.ext_area.setDecimals(3)
        self.ext_area.setValue(100.0)
        self.ext_area.valueChanged.connect(self.refresh)
        self._ext_row.addWidget(self._ext_row_label)
        self._ext_row.addWidget(self.ext_area)
        self._ext_row.addStretch(1)
        self._ext_row_widget = QLabel("")  # placeholder to hold the layout
        layout.addLayout(self._ext_row)
        self._ext_row_label.setVisible(False)
        self.ext_area.setVisible(False)

        self.summary = provenance_label()
        layout.addWidget(self.summary)

        self.layer_combo.layerChanged.connect(self._on_layer_changed)
        self.selected_only.stateChanged.connect(self.refresh)
        self.auto_cases.toggled.connect(self._on_auto_cases_toggled)
        self.name_attr_combo.currentIndexChanged.connect(
            lambda _i: self._emit_feature_catchments() if self.auto_cases.isChecked() else None
        )
        # Seed the name-attr combo from the initial layer, if any.
        self._on_layer_changed()

    # -- External binding (Rainfall plugin integration) -----------------
    def set_external_location(self, name: str | None,
                              lat: float | None, lon: float | None) -> None:
        """Bind this picker to an externally-supplied lat/lon.

        When set, the layer combo is disabled and the picker emits a Catchment
        built from the outer location plus a manual area (spin box). Pass
        ``(None, None, None)`` to release the binding.
        """
        if lat is None or lon is None:
            self._external = None
            self._layer_row_label.setEnabled(True)
            self.layer_combo.setEnabled(True)
            self.selected_only.setEnabled(True)
            self._ext_row_label.setVisible(False)
            self.ext_area.setVisible(False)
        else:
            self._external = (name or "external", lat, lon)
            self._layer_row_label.setEnabled(False)
            self.layer_combo.setEnabled(False)
            self.selected_only.setEnabled(False)
            self._ext_row_label.setVisible(True)
            self.ext_area.setVisible(True)
        self.refresh()

    # The refresh is deliberately public: a tab shown for the first time calls
    # it so it starts populated rather than waiting for the user to touch the
    # combo.
    def refresh(self, *_args) -> None:
        from .. import qgis_bridge

        # External-location path: build a synthetic Catchment from the outer
        # lat/lon and the manual area. crs is filled with EPSG:4326 so tabs
        # that call ``crs.authid()`` don't crash. geometry is None — the
        # Areal GSDM tab needs a real polygon and will therefore be limited
        # without one; the other two tabs work on lat/lon + area only.
        if self.auto_cases.isChecked():
            # Auto mode: the picker's catchment is set by whichever case is
            # active (via set_current_catchment_from_feature). Layer or
            # selected_only changes here re-emit the full list of features.
            self._emit_feature_catchments()
            return

        if self._external is not None:
            name, lat, lon = self._external
            from qgis.core import QgsCoordinateReferenceSystem
            self._catchment = Catchment(
                area_km2=float(self.ext_area.value()),
                lat=lat, lon=lon,
                geometry=None,
                crs=QgsCoordinateReferenceSystem("EPSG:4326"),
                feature_count=0,
                layer_name=name,
                selected_only=False,
            )
            self.summary.setText(
                f"External (Rainfall plugin): <b>{name}</b> @ "
                f"{describe_latlon(lat, lon)}  •  area {self.ext_area.value():,.3f} km²"
                "  •  (Areal GSDM needs a polygon layer — pick one to enable it)"
            )
            self.catchmentChanged.emit(self._catchment)
            return

        layer = self.layer_combo.currentLayer()
        self._catchment = None
        self._error = ""

        if layer is None:
            self.summary.setText("No polygon layer selected.")
            self.catchmentChanged.emit(None)
            return

        selected_only = self.selected_only.isChecked()
        if selected_only and layer.selectedFeatureCount() == 0:
            self._error = f"Nothing is selected in '{layer.name()}'."
            self.summary.setText(self._error)
            self.catchmentChanged.emit(None)
            return

        try:
            found = qgis_bridge.catchment_summary(layer, selected_only)
        except (ValueError, qgis_bridge.ProjectionError) as exc:
            self._error = str(exc)
            self.summary.setText(self._error)
            self.catchmentChanged.emit(None)
            return

        self._catchment = Catchment(
            area_km2=found.area_km2,
            lat=found.lat,
            lon=found.lon,
            geometry=found.geometry,
            crs=found.crs,
            feature_count=found.feature_count,
            layer_name=layer.name(),
            selected_only=selected_only,
        )
        self.summary.setText(
            f"{found.area_km2:,.3f} km²  •  centroid {describe_latlon(found.lat, found.lon)}"
            f"  •  {found.crs.authid()}  •  "
            f"{found.feature_count:,} feature{'s' if found.feature_count != 1 else ''}"
        )
        self.catchmentChanged.emit(self._catchment)

    def catchment(self) -> Catchment | None:
        return self._catchment

    def error(self) -> str:
        """Why there is no catchment, for a tab to put in a message box."""
        return self._error or "Select a catchment polygon layer."

    # ---------------------------------------------------- auto (per-feature)
    def auto_mode(self) -> bool:
        return self.auto_cases.isChecked()

    def _on_layer_changed(self, *_args):
        """Refresh the name-attr combo and re-run refresh()."""
        combo = self.name_attr_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(feature ID)", None)
        layer = self.layer_combo.currentLayer()
        if layer is not None:
            for field in layer.fields():
                combo.addItem(field.name(), field.name())
        combo.blockSignals(False)
        self.refresh()

    def _on_auto_cases_toggled(self, on: bool):
        self.name_attr_label.setVisible(on)
        self.name_attr_combo.setVisible(on)
        if on:
            self._emit_feature_catchments()
        else:
            self.featureCatchmentsChanged.emit(None)
            self._auto_current_fc = None
            self.refresh()

    def _emit_feature_catchments(self):
        """Enumerate features and emit them for tabs to rebuild cases from."""
        from .. import qgis_bridge

        layer = self.layer_combo.currentLayer()
        if layer is None:
            self.featureCatchmentsChanged.emit([])
            self.summary.setText("Auto cases: pick a polygon layer.")
            self._catchment = None
            self.catchmentChanged.emit(None)
            return

        name_field = self.name_attr_combo.currentData()
        selected_only = self.selected_only.isChecked()
        try:
            fcs = qgis_bridge.feature_catchments(
                layer, name_field=name_field, selected_only=selected_only
            )
        except (ValueError, qgis_bridge.ProjectionError) as exc:
            self._error = str(exc)
            self.summary.setText(str(exc))
            self.featureCatchmentsChanged.emit([])
            self._catchment = None
            self.catchmentChanged.emit(None)
            return

        self.summary.setText(
            f"Auto cases: {len(fcs)} feature{'s' if len(fcs) != 1 else ''} "
            f"from '{layer.name()}'"
            + (" (selected only)" if selected_only else "")
        )
        self.featureCatchmentsChanged.emit(fcs)
        # Land the picker's current catchment on the first feature so the
        # tab has something to compute against before a case is selected.
        if fcs:
            self.set_current_catchment_from_feature(fcs[0])

    def set_current_catchment_from_feature(self, fc) -> None:
        """Push a specific feature's catchment as the picker's current one.

        Tabs call this when the user switches cases in auto mode: the case
        carries the FeatureCatchment; setting it here lets every tab's calc
        continue to read ``picker.catchment()`` unchanged.
        """
        summary = fc.summary
        layer = self.layer_combo.currentLayer()
        self._auto_current_fc = fc
        self._catchment = Catchment(
            area_km2=summary.area_km2,
            lat=summary.lat,
            lon=summary.lon,
            geometry=summary.geometry,
            crs=summary.crs,
            feature_count=1,
            layer_name=(layer.name() if layer is not None else "layer"),
            selected_only=False,
        )
        self.catchmentChanged.emit(self._catchment)


class WrapLabel(QLabel):
    """A word-wrapped label that actually reserves the height it needs.

    Qt's own answer -- word wrap plus a ``heightForWidth`` size policy -- is
    not enough inside a ``QFormLayout``: the row settles its height before the
    label knows its width, so a note that wraps to two lines gets its second
    line clipped. Setting the minimum height from the wrapped height on every
    resize is blunt, but it is the thing that works, and a provenance note
    that is half visible is worse than useless.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)

    def _fit(self):
        width = self.width()
        if width <= 0:
            return
        needed = self.heightForWidth(width)
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def setText(self, text):  # noqa: N802 -- Qt API
        super().setText(text)
        self._fit()


def provenance_label(text: str = "") -> QLabel:
    """A muted, word-wrapped note saying where a value came from."""
    label = WrapLabel(text)
    label.setObjectName("provenance")
    return label


def describe_latlon(lat: float, lon: float) -> str:
    """``-21.955, 116.292`` as ``21.955°S 116.292°E``.

    Signed decimal degrees are easy to transpose and hard to sanity-check at a
    glance; hemispheres are not.
    """
    return (
        f"{abs(lat):.3f}°{'S' if lat < 0 else 'N'} "
        f"{abs(lon):.3f}°{'E' if lon >= 0 else 'W'}"
    )


# ------------------------------------------------------------ derived field


class DerivedField(QObject):
    """A value read off a Bureau figure or grid, with its provenance shown.

    Bundles a spin box, a "From centroid" button and a provenance label, and
    owns the rule that the user's own typing is never overwritten by a later
    automatic lookup.  That rule matters: an engineer who has deliberately
    entered a MAF read by eye off the printed A3 should not have it silently
    replaced when they tick "selected features only".

    ``lookup`` is called as ``lookup(lat, lon)`` and must return
    ``(value, provenance)``, or raise ``ValueError`` with a message to show in
    place of a value.
    """

    def __init__(self, label, lookup, minimum, maximum, decimals=2, step=0.05,
                 suffix="", tooltip="", default=None, parent=None):
        super().__init__(parent)
        self.label = label
        self._lookup = lookup
        self._overridden = False

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        if suffix:
            self.spin.setSuffix(suffix)
        if tooltip:
            self.spin.setToolTip(tooltip)
        if default is not None:
            # Set before the signal is connected: a default is what the field
            # shows until a lookup or the user replaces it, and treating it as
            # a user override would stop it ever filling itself in.
            self.spin.setValue(default)

        self.button = QPushButton("From centroid")
        self.button.setObjectName("lookupButton")
        self.button.setToolTip(f"Read {label} again at the catchment centroid.")

        self.note = provenance_label()

        # Not "entered by hand": a default is what the field happens to show
        # before anything has looked it up, and treating it as a user override
        # would stop the lookup ever running.
        self._provenance = "default"
        self._auto_value: float | None = None

        self.button.clicked.connect(self._on_button)
        self.spin.valueChanged.connect(self._on_edited)

    def widget(self) -> QWidget:
        """The value and its lookup button, as one form field.

        The provenance note is deliberately *not* in here -- see
        :meth:`add_to_form`. Nesting a word-wrapped label inside a form field
        makes the row settle its height before it knows its width, and the
        spin box ends up a sliver.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.spin)
        row.addWidget(self.button)
        row.addStretch(1)
        return holder

    def add_to_form(self, form, label: str) -> None:
        """Add the value row and its provenance row to a ``QFormLayout``."""
        form.addRow(label, self.widget())
        form.addRow("", self.note)

    # ---- state

    def value(self) -> float:
        return self.spin.value()

    def provenance(self) -> str:
        return self._provenance

    def _on_edited(self, value):
        # Only a change away from what the lookup put there counts as an
        # override; setValue() during a lookup blocks this signal outright, so
        # anything arriving here came from the user.
        if self._auto_value is None or abs(value - self._auto_value) > 1e-12:
            self._overridden = True
            self._provenance = "entered by hand"
            self.note.setText("Entered by hand.")

    def _on_button(self):
        # Pressing the button is an explicit request, so it clears an override.
        self._overridden = False
        self.update_from(self._catchment, force=True)

    # ---- lookups

    _catchment = None

    def set_value(self, value: float, provenance: str) -> None:
        """Restore a stored value without it counting as the user typing.

        Used when switching cases: the value came from that case, so the
        override flag and the provenance line are restored with it rather
        than being recomputed.
        """
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)
        self._provenance = provenance
        self._overridden = provenance == "entered by hand"
        self.note.setText(
            "Entered by hand."
            if self._overridden
            else ("" if provenance == "default" else provenance)
        )

    def update_from(self, catchment, force: bool = False) -> None:
        """Re-read the value for a new catchment, unless the user has typed."""
        self._catchment = catchment
        if catchment is None:
            if not self._overridden:
                self.note.setText("")
            return
        if self._overridden and not force:
            return
        if (
            catchment.feature_count > AUTO_LOOKUP_MAX_FEATURES
            and not force
        ):
            self.note.setText(
                f"{catchment.feature_count:,} features — press “From centroid”."
            )
            return

        try:
            value, provenance = self._lookup(catchment.lat, catchment.lon)
        except ValueError as exc:
            # Outside the drawn map or off the grid: leave whatever is in the
            # box rather than substituting a number the guidebook does not
            # support.
            self._provenance = f"not available ({exc})"
            self.note.setText(str(exc))
            return

        self._auto_value = value
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(blocked)
        self._overridden = False
        self._provenance = provenance
        self.note.setText(provenance)


# ------------------------------------------------------------------ export


@dataclass
class ResultTable:
    """A table of results plus the inputs that produced it.

    Held as data rather than read back off the widget at export time, because
    the user may change a parameter after a run and the export must describe
    the run it came from.
    """

    headers: list[str]
    rows: list[list[str]]
    run_inputs: list[tuple[str, str]]
    warnings: list[str]
    title: str = ""
    #: Optional wrapped versions of :attr:`headers`, used on screen only. A
    #: narrow table elides a long header; the export must still carry the flat
    #: one, because a newline inside a CSV cell is legal and unreadable.
    display_headers: "list[str] | None" = None


def export_csv(parent: QWidget, table: ResultTable, suggested_name: str) -> None:
    """Write a result table to CSV, with its Run inputs block appended.

    The block is appended rather than prepended so the result table stays on
    row 1 for anything already reading these files.
    """
    path, _ = QFileDialog.getSaveFileName(
        parent, f"Export {table.title or 'results'}", suggested_name, "CSV files (*.csv)"
    )
    if not path:
        return
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(table.headers)
            writer.writerows(table.rows)
            writer.writerow([])
            writer.writerow(["Run inputs"])
            for name, value in table.run_inputs:
                writer.writerow([name, value])
            if table.warnings:
                writer.writerow([])
                for warning in table.warnings:
                    writer.writerow(["WARNING", warning])
    except OSError as exc:
        QMessageBox.critical(parent, "Export failed", str(exc))
    else:
        QMessageBox.information(parent, "Exported", f"Results written to {path}")


_INVALID_SHEET_CHARS = set(r'[]:*?/\\')

SUMMARY_SHEET_NAME = "Summary"
SUMMARY_NAME_HEADER = "Case Name"


def _safe_sheet_name(name: str, used: set) -> str:
    """A workbook-legal, unique sheet name (max 31 chars, no []:*?/\\)."""
    cleaned = "".join(c if c not in _INVALID_SHEET_CHARS else "_" for c in name).strip()
    cleaned = cleaned[:31] or "Case"
    base, i = cleaned, 2
    while cleaned in used:
        suffix = f" ({i})"
        cleaned = (base[: 31 - len(suffix)] + suffix)
        i += 1
    used.add(cleaned)
    return cleaned


def _atomic_save(wb, path: str) -> None:
    """Translate the Windows 'file is in use' error into an actionable one,
    same pattern as Drain Design's xlsx_export._atomic_save."""
    import errno
    try:
        wb.save(path)
    except PermissionError as exc:
        if exc.errno == errno.EACCES:
            raise PermissionError(
                f"Could not save '{path}': the file is open in another "
                "program (usually Excel) and locked for writing. Close it "
                "there and try again."
            ) from exc
        raise


def _case_input_pairs(table):
    """The Input/Value pairs for a case's detail sheet, from its Run inputs."""
    return list(table.run_inputs)


def export_cases_xlsx(parent, cases, suggested_name: str) -> None:
    """Save every calculated case to one .xlsx.

    Layout mirrors Drain Design's xlsx export:

    * ``Summary`` sheet — one row per case, columns:
      ``Case Name | <shared input columns> | <depth-duration output columns>``.
    * One detailed sheet per case: title, blank, ``Input | Value`` block,
      blank, ``Parameter | Value | Units`` block for the depth-duration
      table, warnings appended as ``WARNING`` rows.

    Requires openpyxl (see workbook.INSTALL_HINT).
    """
    ready = [c for c in cases if getattr(c, "table", None) is not None]
    if not ready:
        QMessageBox.information(
            parent, "Export Excel",
            "No calculated cases to export. Run 'Calculate' or 'Calculate all "
            "cases' first."
        )
        return

    path, _ = QFileDialog.getSaveFileName(
        parent, "Export cases to Excel", suggested_name,
        "Excel workbook (*.xlsx)"
    )
    if not path:
        return
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"

    try:
        from ..workbook import _openpyxl
        openpyxl = _openpyxl()
    except Exception as exc:  # noqa: BLE001 - forwarded to the user
        QMessageBox.critical(parent, "Export failed", str(exc))
        return

    # Union of input labels across every case, in first-seen order — the
    # Summary sheet needs one column per label. Output columns are the union
    # of the depth-duration headers.
    input_labels: list[str] = []
    seen_inputs: set[str] = set()
    output_headers: list[str] = []
    seen_outputs: set[str] = set()
    for case in ready:
        for label, _value in case.table.run_inputs:
            if label not in seen_inputs:
                input_labels.append(label)
                seen_inputs.add(label)
        for h in case.table.headers[1:]:  # skip the "Duration" column
            if h not in seen_outputs:
                output_headers.append(h)
                seen_outputs.add(h)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop the default blank sheet

    # ---- Summary sheet (index 0) --------------------------------------
    summary = wb.create_sheet(title=SUMMARY_SHEET_NAME, index=0)
    header_row = [SUMMARY_NAME_HEADER] + input_labels + [
        "Governing method",
        "Controlling duration (hr)",
        "Governing PMP (mm)",
    ]
    summary.append(header_row)

    for case in ready:
        inputs_map = {label: value for label, value in case.table.run_inputs}
        row = [case.name]
        for label in input_labels:
            row.append(inputs_map.get(label, ""))
        results = case.result or []
        if results:
            governing = max(results, key=lambda r: r.pmp_mm)
            row += [
                governing.method,
                float(governing.controlling_duration_hr),
                float(governing.pmp_mm),
            ]
        else:
            row += ["", "", ""]
        summary.append(row)

    # ---- Per-case detail sheets ---------------------------------------
    used = {SUMMARY_SHEET_NAME}
    for case in ready:
        ws = wb.create_sheet(_safe_sheet_name(case.name, used))
        title = case.table.title or "Case"
        ws.append([f"{title} - {case.name}"])
        ws.append([])
        ws.append(["Input", "Value"])
        for label, value in _case_input_pairs(case.table):
            ws.append([label, value])
        ws.append([])
        ws.append(list(case.table.headers))
        for row in case.table.rows:
            ws.append(list(row))
        if case.table.warnings:
            ws.append([])
            for w in case.table.warnings:
                ws.append(["WARNING", w])

    try:
        _atomic_save(wb, path)
    except (OSError, PermissionError) as exc:
        QMessageBox.critical(parent, "Export failed", str(exc))
        return
    QMessageBox.information(
        parent, "Exported",
        f"{len(ready)} case{'s' if len(ready) != 1 else ''} written to {path}"
    )


def copy_to_clipboard(table: ResultTable) -> None:
    """The result table as TSV, for pasting straight into a spreadsheet."""
    from ..qt_compat import QApplication

    lines = ["\t".join(table.headers)]
    lines += ["\t".join(str(c) for c in row) for row in table.rows]
    QApplication.clipboard().setText("\n".join(lines))


def fill_table(widget: QTableWidget, table: ResultTable,
               highlight_row: int | None = None) -> None:
    """Put a :class:`ResultTable` into a ``QTableWidget``."""
    widget.setColumnCount(len(table.headers))
    widget.setHorizontalHeaderLabels(table.display_headers or table.headers)
    widget.setRowCount(len(table.rows))
    for r, row in enumerate(table.rows):
        for c, text in enumerate(row):
            widget.setItem(
                r,
                c,
                cell(
                    str(text),
                    align_right=(c > 0),
                    tint=TINT_HIGHLIGHT if r == highlight_row else None,
                    bold=(r == highlight_row),
                ),
            )


# -------------------------------------------------------------------- plot


def make_canvas():
    """A matplotlib canvas, or ``None`` if matplotlib is unavailable.

    QGIS bundles matplotlib, but a plot is decoration around a table that
    already carries every number.  Returning ``None`` lets a tab drop the chart
    and keep working rather than failing to load.
    """
    try:
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
    except ImportError:
        return None, None

    figure = Figure(figsize=(6.0, 3.0), tight_layout=True)
    return figure, FigureCanvasQTAgg(figure)


def style_axes(ax) -> None:
    """The shared plot look, copied from the Drain Design Toolbox."""
    from matplotlib.ticker import AutoMinorLocator

    ax.xaxis.set_minor_locator(AutoMinorLocator())
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.grid(which="major", linestyle="-", linewidth=0.6, alpha=0.6)
    ax.grid(which="minor", linestyle=":", linewidth=0.4, alpha=0.4)
    ax.tick_params(which="major", length=6)
    ax.tick_params(which="minor", length=3)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def duration_combo(durations, default=None) -> QComboBox:
    """A duration chooser, labelled in hours."""
    combo = QComboBox()
    for d in durations:
        combo.addItem(f"{d:g} hour" + ("s" if d != 1 else ""), d)
    if default is not None and default in durations:
        combo.setCurrentIndex(list(durations).index(default))
    return combo


def maf_lookup(lat: float, lon: float) -> tuple[float, str]:
    """GSDM Figure 3 at a point, with a sentence saying where it was read.

    Shared by the two tabs that need a moisture factor.  Off the drawn map it
    raises with a message naming the figure, so the field can say what is
    missing rather than reporting a bare latitude range.
    """
    from ..core import maf as maf_module

    where = describe_latlon(lat, lon)
    try:
        reading = maf_module.lookup(lat, lon)
    except ValueError:
        raise ValueError(
            f"{where} is outside GSDM Figure 3 — enter the MAF by hand."
        ) from None
    between = (
        f"between contours {reading['lower']:g} and {reading['upper']:g}"
        if reading.get("bracketed")
        else "nearest contour only"
    )
    return reading["maf"], f"Figure 3 at {where}, {between}."


# -------------------------------------------------------------------- cases


@dataclass
class Case:
    """One named run: its inputs, and whatever the last calculation produced.

    ``inputs`` is a plain dict captured from the tab's widgets, so a tab can
    add or drop an input without this class knowing.  ``result`` is whatever
    the method returned and ``table`` the rendered :class:`ResultTable`, both
    kept so switching back to a case restores its results rather than blanking
    them and making the user press Calculate again.
    """

    id: int
    name: str
    inputs: dict
    result: object = None
    table: "ResultTable | None" = None
    #: The rendered summary line and the row to highlight. Kept as fields
    #: rather than inside ``inputs``, because ``inputs`` is replaced wholesale
    #: every time the widgets change -- which would silently drop them.
    summary: str = ""
    highlight_row: object = None


class CaseSidebar(QGroupBox):
    """The list of cases, with add / rename / remove and drag reordering.

    Each ``QListWidgetItem`` carries only a **stable integer id**, never the
    ``Case`` itself.  PyQt round-trips anything stored on an item through
    QVariant, which copies Python objects; storing the case directly gives you
    a stale duplicate the moment anything mutates it.  Ids are resolved through
    ``_by_id``, and a drag-reorder is read back off the item order.

    Emits :attr:`currentCaseChanged` *after* the selection has moved.  The tab
    captures the outgoing case itself, before switching -- it is the only thing
    that knows what its widgets currently hold.
    """

    currentCaseChanged = pyqtSignal(object)
    casesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Cases", parent)
        self.setFixedWidth(190)
        self._by_id: dict[int, Case] = {}
        self._next_id = 1
        #: Guards against reacting to changes this widget is itself making.
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setToolTip(
            "Cases are independent runs. Drag to reorder; double-click to "
            "rename. Each keeps its own inputs and its own results."
        )
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.model().rowsMoved.connect(lambda *_a: self.casesChanged.emit())
        self.list.itemDoubleClicked.connect(lambda _i: self.rename_current())
        layout.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(3)
        self.add_button = QPushButton("+")
        self.add_button.setObjectName("lookupButton")
        self.add_button.setToolTip("Add a case, copying the current one's inputs.")
        self.add_button.clicked.connect(lambda: self.add_case())
        self.rename_button = QPushButton("Rename")
        self.rename_button.setObjectName("lookupButton")
        self.rename_button.clicked.connect(self.rename_current)
        self.remove_button = QPushButton("−")
        self.remove_button.setObjectName("lookupButton")
        self.remove_button.setToolTip("Remove the current case.")
        self.remove_button.clicked.connect(self.remove_current)
        for button in (self.add_button, self.rename_button, self.remove_button):
            row.addWidget(button)
        layout.addLayout(row)

        # Small note shown while the tab is in auto ("cases per feature") mode.
        self._auto_note = QLabel("Auto: driven by layer features")
        self._auto_note.setStyleSheet("color: #555; font-style: italic;")
        self._auto_note.setVisible(False)
        layout.addWidget(self._auto_note)

    # ---- auto / per-feature mode
    def set_auto_mode(self, on: bool) -> None:
        """Hide Add/Rename/Remove while cases are driven by the layer."""
        for button in (self.add_button, self.rename_button, self.remove_button):
            button.setVisible(not on)
        self._auto_note.setVisible(on)
        # Manual editing (drag-reorder, inline rename) is confusing when the
        # list is being rebuilt on layer changes, so lock the list too.
        self.list.setDragDropMode(
            QAbstractItemView.DragDropMode.NoDragDrop if on
            else QAbstractItemView.DragDropMode.InternalMove
        )
        self.list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers if on
            else QAbstractItemView.EditTrigger.DoubleClicked
        )

    # ---- the cases themselves

    def cases(self) -> list:
        """Every case, in the order shown -- which drag-reordering changes."""
        out = []
        for i in range(self.list.count()):
            case = self._by_id.get(self.list.item(i).data(Qt.ItemDataRole.UserRole))
            if case is not None:
                out.append(case)
        return out

    def current(self):
        item = self.list.currentItem()
        if item is None:
            return None
        return self._by_id.get(item.data(Qt.ItemDataRole.UserRole))

    def add_case(self, name: str | None = None, inputs: dict | None = None) -> Case:
        """Append a case and select it.

        A new case inherits the current one's inputs, because the usual reason
        to add one is to vary a single parameter.
        """
        if inputs is None:
            current = self.current()
            inputs = dict(current.inputs) if current else {}
        case = Case(
            id=self._next_id,
            name=name or f"Case {self._next_id}",
            inputs=dict(inputs),
        )
        self._next_id += 1
        self._by_id[case.id] = case

        item = QListWidgetItem(case.name)
        item.setData(Qt.ItemDataRole.UserRole, case.id)
        self.list.addItem(item)
        self.list.setCurrentItem(item)
        self.casesChanged.emit()
        return case

    def reset(self, named_inputs) -> None:
        """Replace every case at once, for a project being opened.

        Clearing and refilling rather than adding to what is there: opening a
        project means *that* project, not that project merged with whatever the
        panel happened to be showing.
        """
        self._loading = True
        try:
            self.list.clear()
            self._by_id.clear()
        finally:
            self._loading = False
        for name, inputs in named_inputs:
            self.add_case(name, inputs)
        if self.list.count():
            self.list.setCurrentRow(0)

    def rename_current(self):
        case = self.current()
        if case is None:
            return
        name, ok = QInputDialog.getText(self, "Rename case", "Name", text=case.name)
        if not ok or not name.strip():
            return
        case.name = name.strip()
        self.refresh_labels()
        self.casesChanged.emit()

    def remove_current(self):
        """Remove the current case, keeping at least one.

        A tab with no cases has nowhere to put the inputs the user is looking
        at, so the last one is cleared rather than deleted.
        """
        case = self.current()
        if case is None:
            return
        if self.list.count() == 1:
            case.result = None
            case.table = None
            self.refresh_labels()
            self.currentCaseChanged.emit(case)
            self.casesChanged.emit()
            return
        row = self.list.currentRow()
        self._by_id.pop(case.id, None)
        self._loading = True
        self.list.takeItem(row)
        self._loading = False
        self.list.setCurrentRow(min(row, self.list.count() - 1))
        self.casesChanged.emit()

    def _on_current_changed(self, current, _previous):
        if self._loading:
            return
        self.currentCaseChanged.emit(
            self._by_id.get(current.data(Qt.ItemDataRole.UserRole))
            if current is not None
            else None
        )

    def refresh_labels(self):
        """Re-label items, so a case that has been calculated says so."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            case = self._by_id.get(item.data(Qt.ItemDataRole.UserRole))
            if case is not None:
                item.setText(
                    case.name if case.result is None else f"{case.name}  ✓"
                )


# --------------------------------------------------------------- plot panel


class PlotPanel(QTabWidget):
    """The bottom panel: one matplotlib canvas per tab, each exportable.

    Falls back to a single explanatory page if matplotlib is missing, so a tab
    still works without it -- every number on a plot is in a table too.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: dict = {}
        self.available = make_canvas()[1] is not None
        if not self.available:
            page = QWidget()
            layout = QVBoxLayout(page)
            label = QLabel(
                "Plots need matplotlib, which is not available in this QGIS "
                "install. The results table has every value."
            )
            label.setWordWrap(True)
            layout.addWidget(label)
            self.addTab(page, "Plot")

    def page(self, name: str):
        """Fresh axes for a named tab, creating the tab the first time.

        Returns ``None`` when matplotlib is unavailable, which every caller
        treats as "skip the drawing".
        """
        if not self.available:
            return None
        if name not in self._pages:
            self._pages[name] = self._build_page(name)
        entry = self._pages[name]
        entry["figure"].clear()
        ax = entry["figure"].add_subplot(111)
        entry["ax"] = ax
        return ax

    def _build_page(self, name: str) -> dict:
        figure, canvas = make_canvas()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        canvas.setMinimumHeight(170)
        layout.addWidget(canvas, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        export = QPushButton("Export CSV…")
        copy = QPushButton("Copy")
        export.setEnabled(False)
        copy.setEnabled(False)
        row.addWidget(export)
        row.addWidget(copy)
        layout.addLayout(row)

        export.clicked.connect(lambda _checked=False, n=name: self._export(n))
        copy.clicked.connect(lambda _checked=False, n=name: self._copy(n))
        self.addTab(page, name)
        return {
            "figure": figure,
            "canvas": canvas,
            "page": page,
            "table": None,
            "export": export,
            "copy": copy,
        }

    def set_data(self, name: str, table=None):
        """The numbers behind a plot, so its buttons export exactly that plot."""
        entry = self._pages.get(name)
        if entry is None:
            return
        entry["table"] = table
        entry["export"].setEnabled(table is not None)
        entry["copy"].setEnabled(table is not None)

    def draw(self, name: str):
        entry = self._pages.get(name)
        if entry is not None:
            entry["canvas"].draw_idle()

    def _export(self, name: str):
        table = self._pages[name].get("table")
        if table is not None:
            slug = "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()
            export_csv(self, table, f"{slug}.csv")

    def _copy(self, name: str):
        table = self._pages[name].get("table")
        if table is not None:
            copy_to_clipboard(table)


# -------------------------------------------------------------- tab layout


def build_shell(header, sidebar, inputs, results, plots, middle=None) -> QVBoxLayout:
    """Assemble the Drain Design Toolbox anatomy.

    ::

        header                            optional; None when a tab has none
        +--------- vertical splitter ------------------------------------+
        | Cases | inputs      | middle (optional) | results table         |
        +----------------------------------------------------------------+
        | plot tabs                                                      |
        +----------------------------------------------------------------+

    Returns the outer layout, unparented -- the caller sets it on the tab.
    The results table takes the horizontal stretch, because it is the part
    that grows with the answer; the other columns hold their own width.

    ``middle`` is for a tab with more inputs than one column can carry
    without becoming a scroll-hunt. GTSMR uses it for the two method blocks,
    leaving the first column to the catchment and what was read from it.
    """
    outer = QVBoxLayout()
    if header is not None:
        outer.addWidget(header)

    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.setChildrenCollapsible(False)

    top = QSplitter(Qt.Orientation.Horizontal)
    top.setChildrenCollapsible(False)
    top.addWidget(sidebar)
    top.addWidget(inputs)
    widths = [190, 340]
    if middle is not None:
        top.addWidget(middle)
        widths.append(360)
    top.addWidget(results)
    widths.append(460)

    # Only the results pane grows when the dock is widened; the input columns
    # have a natural width and gain nothing from more.
    for index in range(top.count() - 1):
        top.setStretchFactor(index, 0)
    top.setStretchFactor(top.count() - 1, 1)
    top.setSizes(widths)

    splitter.addWidget(top)
    splitter.addWidget(plots)
    splitter.setSizes([390, 300])

    outer.addWidget(splitter, stretch=1)
    return outer


def wrap_form(form) -> None:
    """Let a form put a long label above its field instead of beside it.

    Without this the widest label sets a floor on the whole inputs column, and
    the column pushes the results table off the edge of the dock.
    """
    from ..qt_compat import QFormLayout

    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)


def input_pane(content, footer=None, width: int = 350) -> QWidget:
    """A scrolling inputs column with its buttons pinned below it.

    The buttons must not scroll with the inputs. Inside the scroll area they
    sit under everything else, which on a tall form puts Calculate below the
    fold -- the one control the user is looking for is the one they have to
    go hunting for.
    """
    pane = QWidget()
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(scrollable(content, width), stretch=1)
    if footer is not None:
        layout.addLayout(footer)
    pane.setMinimumWidth(width)
    return pane


def scrollable(widget, width: int = 350) -> QScrollArea:
    """Put an inputs column in a scroll area so a short dock stays usable.

    A minimum width only: the surrounding splitter decides how wide the column
    actually is, and a maximum here would override it and squeeze whatever
    sits beside it.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setMinimumWidth(width)
    return area


def annotate_points(ax, xs, ys, fmt="{:,.0f}") -> None:
    """Label the value at each plotted point.

    Labels are dropped where they would land on top of the previous one, which
    happens on the flat tail of a depth-duration curve.  A missing label is
    better than two overprinted ones, and the table beside the plot has every
    value regardless.
    """
    pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if not pairs:
        return
    span = max(y for _x, y in pairs) - min(y for _x, y in pairs)
    gap = span * 0.06 if span else 0.0

    last = None
    for x, y in pairs:
        if last is not None and abs(y - last) < gap:
            continue
        last = y
        ax.annotate(
            fmt.format(y),
            (x, y),
            textcoords="offset points",
            xytext=(0, 7),
            ha="center",
            fontsize=7,
            color="#12222f",
        )


# ------------------------------------------------------------ project panel


class ProjectPanel(QGroupBox):
    """The top row: which job this is, and saving or opening it.

    Sits above the tabs rather than inside each one, because a project here is
    one file covering all three methods.  Drain Design puts this row in every
    tab; it can, because its projects are per-tab.

    Owns no data: it emits, and the plugin does the work.  That keeps the
    workbook code out of a widget and lets the panel be built in a test.
    """

    saveRequested = pyqtSignal()
    saveAsRequested = pyqtSignal()
    openRequested = pyqtSignal()
    documentationRequested = pyqtSignal()

    _CLEAN_STYLE = "font-weight: 600; color: #12222f;"
    _DIRTY_STYLE = (
        "font-weight: 600; font-style: italic; color: #b0530f;"
    )

    def __init__(self, parent=None):
        super().__init__("Project", parent)
        self._path = None
        self._dirty = False

        # Match the outline-style (lookupButton) padding to the filled-button
        # padding just inside this panel via the QSS selector
        # `QGroupBox#projectPanel QPushButton#lookupButton` — otherwise the
        # tighter form-row padding leaves Open / Documentation shorter than
        # Save / Save As.
        self.setObjectName("projectPanel")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)

        self.name_label = QLabel("Untitled project")
        self.name_label.setStyleSheet(self._CLEAN_STYLE)
        row.addWidget(self.name_label)

        self.path_label = QLabel("not saved")
        self.path_label.setObjectName("provenance")
        row.addWidget(self.path_label)
        row.addStretch(1)

        self.open_button = QPushButton("Open project…")
        self.open_button.setObjectName("lookupButton")
        self.open_button.setToolTip(
            "Open a .xlsx project: every tab's cases and their inputs come "
            "back. Results are recomputed by pressing Calculate."
        )
        self.open_button.clicked.connect(self.openRequested)

        self.save_button = QPushButton("Save")
        self.save_button.setToolTip(
            "Save every tab's cases, inputs and results to the project file."
        )
        self.save_button.clicked.connect(self.saveRequested)

        self.save_as_button = QPushButton("Save As…")
        self.save_as_button.clicked.connect(self.saveAsRequested)

        self.documentation_button = QPushButton("Documentation")
        self.documentation_button.setObjectName("lookupButton")
        self.documentation_button.setToolTip(
            "Open the PMP methodology reference (HTML). Explains every "
            "calculation step and cites the relevant guidebook sections."
        )
        self.documentation_button.clicked.connect(self.documentationRequested)

        for button in (self.open_button, self.save_button, self.save_as_button,
                       self.documentation_button):
            row.addWidget(button)

    # ---- state

    def path(self):
        return self._path

    def set_path(self, path) -> None:
        """Remember where this project lives, and say so. Also clears dirty."""
        from pathlib import Path

        self._path = Path(path) if path else None
        if self._path is None:
            self.name_label.setText("Untitled project")
            self.path_label.setText("not saved")
        else:
            self.name_label.setText(self._path.stem)
            self.path_label.setText(str(self._path.parent))
        self.set_dirty(False)

    def name(self) -> str:
        return self.name_label.text()

    # ---- dirty flag
    def is_dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, dirty: bool) -> None:
        """Italic + burnt-orange when the project has unsaved changes."""
        self._dirty = bool(dirty)
        self.name_label.setStyleSheet(
            self._DIRTY_STYLE if self._dirty else self._CLEAN_STYLE
        )
        base = self.name_label.text().rstrip(" *")
        self.name_label.setText(base + (" *" if self._dirty else ""))
