"""PMP tab — session-level cases, each = one catchment shapefile.

Layout:

    Session bar (Open / Save / Save As)
    ┌── Cases ─────┬── Catchment: [layer combo]  [Calculate] ──┐
    │  Case 1      │    1-feature status                       │
    │  Case 2      │  ┌── GSDM ──┬── GTSMR / GSAM ──┐          │
    │  + Rename −  │  │          │                  │          │
    └──────────────┴──┴──────────┴──────────────────┴──────────┘

Each session case is bound 1:1 to a sub-case in every method sub-tab
(GSDM, GTSMR/GSAM) — same name in each. Selecting a case in the session
sidebar drives selection in the sub-tabs. Adding / renaming / removing a
session case mirrors into every sub-tab. The Calculate button snapshots
the current case's catchment and runs both methods; results land on each
sub-tab's sub-case as normal, so ``workbook.save_project`` writes them.

Areal GSDM is hidden for now — a session is one catchment, one GSDM
depth-duration + one GTSMR/GSAM long-duration set.
"""
from __future__ import annotations

from pathlib import Path

from ....qt_compat import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    Qt,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from qgis.core import QgsMapLayerProxyModel
    from qgis.gui import QgsMapLayerComboBox
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


TAB_KEYS = ("GSDM", "GTSMR")

_INVALID_SHEET_CHARS = set(r'[]:*?/\\')

_GSDM_HEADERS = ["Duration (hr)", "Areal (mm)", "Point (mm)", "Areal / point"]
_GTSMR_HEADERS = [
    "Duration (hr)",
    "Raw summer (mm)", "MAF × TAF × DAF (S)", "Summer PMP (mm)",
    "Raw winter (mm)", "MAF × TAF × DAF (W)", "Winter PMP (mm)",
    "Governing (mm)",
]
_GSAM_HEADERS = [
    "Duration (hr)",
    "Raw summer (mm)", "MAF × TAF (S)", "Summer PMP (mm)",
    "Raw autumn (mm)", "MAF × TAF (A)", "Autumn PMP (mm)",
    "Governing (mm)",
]


def _safe_sheet_name(name: str, used: set) -> str:
    cleaned = "".join(c if c not in _INVALID_SHEET_CHARS else "_" for c in name).strip()
    cleaned = (cleaned[:31] or "Case")
    base, i = cleaned, 2
    while cleaned in used:
        suf = f" ({i})"
        cleaned = base[: 31 - len(suf)] + suf
        i += 1
    used.add(cleaned)
    return cleaned


def _sub_case(sub_tab, idx):
    if sub_tab is None:
        return None
    cases = sub_tab.cases.cases()
    if 0 <= idx < len(cases):
        return cases[idx]
    return None


def _cols(block):
    return len(block[0]) if block else 4


def _gsdm_block(case) -> list[list]:
    """The GSDM depth-duration block for a case: header + rows.

    Rows come from the case's own ResultTable (built by gsdm_tab._render).
    """
    if case is None or getattr(case, "table", None) is None:
        return [list(_GSDM_HEADERS)]
    table = case.table
    rows = [list(table.headers)]
    for row in table.rows:
        rows.append(list(row))
    return rows


def _gtsmr_block(case) -> list[list]:
    """The GTSMR depth-duration block: pulled from case.result[0] if present."""
    return _method_block(case, method="GTSMR", headers=_GTSMR_HEADERS)


def _gsam_block(case) -> list[list]:
    return _method_block(case, method="GSAM", headers=_GSAM_HEADERS)


def _method_block(case, method, headers) -> list[list]:
    """Pull one specific method's series out of a gtsmr_tab case.

    ``case.result`` is a list of ``MethodResult`` — one per method the run
    included. Emits per-duration rows with the raw DDA depth, the combined
    adjustment factor, and the rounded PMP for each season, plus the
    governing PMP column.
    """
    rows = [list(headers)]
    if case is None or not getattr(case, "result", None):
        return rows
    for result in case.result:
        if result.method != method:
            continue
        first = result.seasons[0] if result.seasons else None
        second = result.seasons[1] if len(result.seasons) > 1 else None
        if first is None:
            continue
        # Duration list from whichever season is populated.
        durations = [d.duration_hr for d in first.by_duration]
        for d in first.by_duration:
            raw_1 = d.raw_mm
            pmp_1 = d.pmp_mm
            factor_1 = (pmp_1 / raw_1) if (raw_1 and raw_1 > 0) else None
            # Second season (winter/autumn) at same duration.
            raw_2 = pmp_2 = factor_2 = None
            if second is not None:
                for dd in second.by_duration:
                    if dd.duration_hr == d.duration_hr:
                        raw_2 = dd.raw_mm
                        pmp_2 = dd.pmp_mm
                        factor_2 = (pmp_2 / raw_2) if (raw_2 and raw_2 > 0) else None
                        break
            governing = max(pmp_1 or 0.0, pmp_2 or 0.0)
            rows.append([
                f"{d.duration_hr:g}",
                f"{raw_1:,.3f}" if raw_1 is not None else "—",
                f"{factor_1:.4f}" if factor_1 is not None else "—",
                f"{pmp_1:,.0f}" if pmp_1 is not None else "—",
                f"{raw_2:,.3f}" if raw_2 is not None else "—",
                f"{factor_2:.4f}" if factor_2 is not None else "—",
                f"{pmp_2:,.0f}" if pmp_2 is not None else "—",
                f"{governing:,.0f}",
            ])
        break
    return rows


def _run_inputs(case) -> list[tuple[str, object]]:
    """The 'Run inputs' list stored on a case's ResultTable, or empty."""
    if case is None:
        return []
    table = getattr(case, "table", None)
    if table is None:
        return []
    return list(getattr(table, "run_inputs", []) or [])


class PmpTab(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._built = False
        self.project = None
        self.gsdm_tab = None
        self.gtsmr_tab = None
        self._layer_combo = None
        self._status_label = None
        self._case_list = None
        # Mirror of the session cases, kept in the same order as the list widget.
        # Each entry: {"name": str, "layer": QgsMapLayer | None}.
        self._session_cases: list[dict] = []
        self._loading = False
        self._build_placeholder()

    def _build_placeholder(self):
        layout = QVBoxLayout(self)
        self._layout = layout
        self._info = QLabel(
            "PMP methods (vendored from pmp_toolbox). Loading on first view…"
        )
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._built:
            self._build_tabs()

    def _build_tabs(self):
        try:
            from ..pmp_toolbox.tabs.gsdm_tab import GsdmTab
            from ..pmp_toolbox.tabs.gtsmr_tab import GtsmrTab
            from ..pmp_toolbox.tabs.common import ProjectPanel, apply_style
        except Exception as exc:
            self._info.setText(
                "Could not load the vendored pmp_toolbox: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        self._info.deleteLater()

        # ── Session bar
        self.project = ProjectPanel()
        self.project.saveRequested.connect(self.save_project)
        self.project.saveAsRequested.connect(self.save_project_as)
        self.project.openRequested.connect(self.open_project)
        self.project.documentationRequested.connect(self.open_documentation)
        apply_style(self.project)
        self._layout.addWidget(self.project)

        # ── Body: cases sidebar | (catchment row + Calculate + sub-tabs)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_cases_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._build_catchment_row())

        tabs = QTabWidget()
        self.gsdm_tab = GsdmTab()
        self.gtsmr_tab = GtsmrTab()
        from .zone_map_tab import ZoneMapTab
        from .gsdm_map_tab import GsdmMapTab
        self.zone_map_tab = ZoneMapTab()
        self.gsdm_map_tab = GsdmMapTab()
        tabs.addTab(self.gsdm_tab, "GSDM")
        tabs.addTab(self.gtsmr_tab, "GTSMR / GSAM")
        tabs.addTab(self.zone_map_tab, "GTSMR/GSAM zone map")
        tabs.addTab(self.gsdm_map_tab, "GSDM zone map")
        right_layout.addWidget(tabs, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 900])
        self._layout.addWidget(splitter, 1)

        # Hide each sub-tab's own picker + cases sidebar — the session
        # bar drives the catchment, and the session case list drives the
        # sub-tabs' internal cases 1:1.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            if getattr(tab, "picker", None) is not None:
                tab.picker.setVisible(False)
            if getattr(tab, "cases", None) is not None:
                tab.cases.setVisible(False)

        # Dirty flag: any input or case-list change flips the project name
        # to italic + burnt-orange until the next Save.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            if getattr(tab, "cases", None) is not None:
                tab.cases.casesChanged.connect(self._mark_dirty)
                tab.cases.currentCaseChanged.connect(self._mark_dirty)

        self._built = True

        # Seed with a single Case 1 that matches whatever the sub-tabs
        # started with. The sub-tabs each add their own "Case 1" at build,
        # so we adopt it as session case 1.
        self._session_cases.append({"name": "Case 1", "layer": None})
        item = QListWidgetItem("Case 1")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._case_list.addItem(item)
        self._case_list.setCurrentRow(0)
        self._on_catchment_layer_changed()

    # -------------------------------------------------------- cases sidebar
    def _build_cases_sidebar(self):
        group = QGroupBox("Cases")
        group.setMinimumWidth(180)
        v = QVBoxLayout(group)

        self._case_list = QListWidget()
        # Drag-to-reorder: the session sidebar drives both sub-tabs' case
        # lists in lock-step, so a drag rearrangement mirrors down into
        # each sub-tab's internal case order.
        self._case_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._case_list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._case_list.currentRowChanged.connect(self._on_case_row_changed)
        self._case_list.itemChanged.connect(self._on_case_renamed)
        self._case_list.model().rowsMoved.connect(self._on_case_rows_moved)
        v.addWidget(self._case_list, 1)

        row = QHBoxLayout()
        add = QPushButton("+")
        rename = QPushButton("Rename")
        remove = QPushButton("−")
        add.clicked.connect(self._add_session_case)
        rename.clicked.connect(self._rename_session_case)
        remove.clicked.connect(self._remove_session_case)
        for b in (add, rename, remove):
            row.addWidget(b)
        v.addLayout(row)
        return group

    def _build_catchment_row(self):
        group = QGroupBox("Catchment shapefile (one polygon feature)")
        row = QHBoxLayout(group)
        row.addWidget(QLabel("Layer:"))
        if QGIS_AVAILABLE:
            self._layer_combo = QgsMapLayerComboBox()
            self._layer_combo.setFilters(QgsMapLayerProxyModel.Filter.PolygonLayer)
            self._layer_combo.layerChanged.connect(self._on_catchment_layer_changed)
            row.addWidget(self._layer_combo, stretch=1)
        else:
            row.addWidget(QLabel("(QGIS not available)"), stretch=1)

        # Right-hand summary: area + centroid lat/lon of the picked feature.
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #12222f;")
        row.addWidget(self._summary_label, stretch=2)

        # Kept for the wrong-feature-count / status message path.
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        row.addWidget(self._status_label, stretch=2)
        return group

    # ---------------------------------------------------- session case ops
    def _current_row(self):
        return self._case_list.currentRow() if self._case_list is not None else -1

    def _current_session_case(self):
        r = self._current_row()
        if 0 <= r < len(self._session_cases):
            return self._session_cases[r]
        return None

    def _add_session_case(self):
        idx = len(self._session_cases) + 1
        name = f"Case {idx}"
        # Guarantee uniqueness against existing names.
        existing = {c["name"] for c in self._session_cases}
        while name in existing:
            idx += 1
            name = f"Case {idx}"

        self._session_cases.append({"name": name, "layer": None})
        # Mirror into each sub-tab's cases.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            tab.cases.add_case(name=name)

        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self._case_list.addItem(item)
        self._case_list.setCurrentRow(self._case_list.count() - 1)

    def _rename_session_case(self):
        case = self._current_session_case()
        if case is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename case", "Case name:", text=case["name"]
        )
        if not ok or not name.strip():
            return
        self._apply_rename(self._current_row(), name.strip())

    def _remove_session_case(self):
        if len(self._session_cases) <= 1:
            QMessageBox.information(
                self, "PMP", "At least one case is required."
            )
            return
        r = self._current_row()
        if r < 0:
            return
        self._session_cases.pop(r)
        self._loading = True
        try:
            self._case_list.takeItem(r)
        finally:
            self._loading = False
        # Mirror removal into each sub-tab.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            sub_cases = tab.cases.cases()
            if r < len(sub_cases):
                tab.cases.list.setCurrentRow(r)
                tab.cases.remove_current()
        self._case_list.setCurrentRow(min(r, self._case_list.count() - 1))

    def _on_case_renamed(self, item):
        if self._loading:
            return
        row = self._case_list.row(item)
        if row < 0 or row >= len(self._session_cases):
            return
        self._apply_rename(row, item.text().strip())

    def _on_case_rows_moved(self, *_args):
        """After a drag, rebuild self._session_cases + sub-tab case orders."""
        if self._loading:
            return
        # New order according to the session list widget.
        new_order = [
            self._case_list.item(i).text().rstrip(" *")
            for i in range(self._case_list.count())
        ]
        # Re-index self._session_cases to match. Case names are unique
        # inside a session, so matching by name is safe.
        old_by_name = {c["name"]: c for c in self._session_cases}
        self._session_cases = [old_by_name[name] for name in new_order]

        # Mirror into each sub-tab's CaseSidebar: reorder the QListWidget
        # items so its `cases()` returns them in the new order too.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            if tab is None:
                continue
            self._reorder_sub_tab(tab, new_order)

        self._mark_dirty()

    @staticmethod
    def _reorder_sub_tab(tab, new_order):
        """Reorder a sub-tab's CaseSidebar QListWidget to match `new_order`."""
        cases = tab.cases
        current = cases.list.currentRow()
        # Take every item out first, then re-insert in the requested order.
        cases.list.blockSignals(True)
        try:
            items_by_name = {}
            for _ in range(cases.list.count()):
                item = cases.list.takeItem(0)
                items_by_name[item.text().rstrip(" *")] = item
            for name in new_order:
                item = items_by_name.pop(name, None)
                if item is not None:
                    cases.list.addItem(item)
            # Any leftovers (shouldn't happen) go on the end.
            for item in items_by_name.values():
                cases.list.addItem(item)
            if 0 <= current < cases.list.count():
                cases.list.setCurrentRow(current)
        finally:
            cases.list.blockSignals(False)

    def _apply_rename(self, row, new_name):
        if not new_name:
            return
        self._session_cases[row]["name"] = new_name
        self._loading = True
        try:
            self._case_list.item(row).setText(new_name)
        finally:
            self._loading = False
        # Mirror into sub-tabs.
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            sub_cases = tab.cases.cases()
            if row < len(sub_cases):
                sub_cases[row].name = new_name
                tab.cases.refresh_labels()

    def _on_case_row_changed(self, row):
        """Switch every sub-tab to the row-th case, and restore its layer."""
        if self._loading or row < 0 or row >= len(self._session_cases):
            return
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            if row < tab.cases.list.count():
                tab.cases.list.setCurrentRow(row)
        # Restore the case's stored catchment layer.
        layer = self._session_cases[row].get("layer")
        if self._layer_combo is not None and layer is not None:
            self._layer_combo.blockSignals(True)
            self._layer_combo.setLayer(layer)
            self._layer_combo.blockSignals(False)
        self._on_catchment_layer_changed()

    # ---------------------------------------------------- catchment
    def _on_catchment_layer_changed(self, *_args):
        if not QGIS_AVAILABLE or self._layer_combo is None:
            return
        layer = self._layer_combo.currentLayer()
        # Remember on the current session case.
        cur = self._current_session_case()
        if cur is not None:
            cur["layer"] = layer

        self._mark_dirty()
        if layer is None:
            self._set_status("Pick a polygon layer.", ok=False)
            self._set_summary("")
            self._push_layer_to_sub_tabs(None)
            return
        n = layer.featureCount()
        if n != 1:
            msg = (
                f"Layer '{layer.name()}' has {n} feature{'s' if n != 1 else ''}. "
                "A PMP case runs against exactly one catchment — pick a "
                "shapefile with one polygon feature (or dissolve first)."
            )
            self._set_status(msg, ok=False)
            self._set_summary("")
            QMessageBox.warning(self, "Wrong feature count", msg)
            self._push_layer_to_sub_tabs(None)
            return

        self._set_status("", ok=True)
        self._push_layer_to_sub_tabs(layer)
        self._refresh_summary()

    def _push_layer_to_sub_tabs(self, layer):
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            if tab is None:
                continue
            picker = getattr(tab, "picker", None)
            if picker is None:
                continue
            picker.layer_combo.setLayer(layer)
            if hasattr(picker, "refresh"):
                picker.refresh()

    def _set_summary(self, text):
        if self._summary_label is not None:
            self._summary_label.setText(text)

    def _mark_dirty(self, *_args):
        """Flip the project name to italic + burnt-orange."""
        if self._loading or self.project is None or not self._built:
            return
        if not self.project.is_dirty():
            self.project.set_dirty(True)

    def _refresh_summary(self):
        """Read area + WGS84 centroid from whichever sub-tab already dissolved."""
        if self._summary_label is None:
            return
        for tab in (self.gsdm_tab, self.gtsmr_tab):
            picker = getattr(tab, "picker", None)
            if picker is None:
                continue
            c = picker.catchment()
            if c is None:
                continue
            self._set_summary(
                f"Area: <b>{c.area_km2:,.4f} km²</b>  •  "
                f"Centroid: <b>{c.lat:.5f}, {c.lon:.5f}</b>"
            )
            if getattr(self, "zone_map_tab", None) is not None:
                self.zone_map_tab.set_location(
                    c.lat, c.lon, c.layer_name or ""
                )
            if getattr(self, "gsdm_map_tab", None) is not None:
                self.gsdm_map_tab.set_location(
                    c.lat, c.lon, c.layer_name or ""
                )
            return
        self._set_summary("")
        if getattr(self, "zone_map_tab", None) is not None:
            self.zone_map_tab.clear_location()
        if getattr(self, "gsdm_map_tab", None) is not None:
            self.gsdm_map_tab.clear_location()

    def _set_status(self, text, ok):
        if self._status_label is None:
            return
        colour = "#0a6b1e" if ok else "#a15c00"
        self._status_label.setStyleSheet(f"color: {colour};")
        self._status_label.setText(text)

    # ------------------------------------------------------------- session
    def _tab_pairs(self):
        return list(zip(TAB_KEYS, (self.gsdm_tab, self.gtsmr_tab)))

    def save_project(self):
        if self.project is None:
            return
        path = self.project.path()
        if path is None:
            self.save_project_as()
            return
        self._write_project(path)

    def save_project_as(self):
        if self.project is None:
            return
        suggested = str(self.project.path() or "pmp_project.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PMP project", suggested, "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        self._write_project(path)

    def _write_project(self, path):
        """Save the project — one sheet per session case, nothing else.

        The four per-method Inputs / Results sheets that
        ``workbook.save_project`` used to write are deliberately skipped —
        the per-case sheets cover the same data in a reader-friendly layout
        and duplicate rows are noise.
        """
        try:
            from ..pmp_toolbox.workbook import _openpyxl
            openpyxl = _openpyxl()
        except Exception as exc:  # noqa: BLE001 - forwarded to user
            QMessageBox.warning(self, "Could not save the project", str(exc))
            return

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        used = set()
        for i, session_case in enumerate(self._session_cases):
            name = _safe_sheet_name(session_case["name"], used)
            ws = wb.create_sheet(title=name)
            self._write_case_sheet(ws, i, session_case)

        try:
            wb.save(path)
        except PermissionError as exc:
            QMessageBox.warning(
                self, "Could not save the project",
                f"Could not write '{path}' — it is probably open in Excel. "
                "Close it there and try again.\n\n{exc}",
            )
            return
        except OSError as exc:
            QMessageBox.warning(self, "Could not save the project", str(exc))
            return
        self.project.set_path(path)

    def _write_case_sheet(self, ws, idx, session_case):
        # Header line: case name + area + centroid (if available).
        ws.append([session_case["name"]])
        gsdm_case = _sub_case(self.gsdm_tab, idx)
        gtsmr_case = _sub_case(self.gtsmr_tab, idx)
        picker_c = self._picker_catchment_for(gtsmr_case, gsdm_case)
        if picker_c is not None:
            ws.append([
                f"Area: {picker_c.area_km2:,.4f} km²",
                "", "", "", "",
                f"Centroid: {picker_c.lat:.5f}, {picker_c.lon:.5f}",
            ])
        ws.append([])

        # Inputs block — the same "Run inputs" list each sub-tab already
        # produces, side-by-side so you can compare GSDM vs GTSMR/GSAM
        # provenance at a glance.
        gsdm_inputs = _run_inputs(gsdm_case)
        gtsmr_gsam_inputs = _run_inputs(gtsmr_case)
        if gsdm_inputs or gtsmr_gsam_inputs:
            ws.append(["Inputs — GSDM", "", "", "", "",
                       "Inputs — GTSMR / GSAM"])
            max_ipt = max(len(gsdm_inputs), len(gtsmr_gsam_inputs))
            for r in range(max_ipt):
                gi = gsdm_inputs[r] if r < len(gsdm_inputs) else ("", "")
                ti = gtsmr_gsam_inputs[r] if r < len(gtsmr_gsam_inputs) else ("", "")
                ws.append([gi[0], gi[1], "", "", "", ti[0], ti[1]])
            ws.append([])

        gsdm_block = _gsdm_block(gsdm_case)
        gtsmr_block = _gtsmr_block(gtsmr_case)
        gsam_block = _gsam_block(gtsmr_case)

        # Section header row: | GSDM ... | | | GTSMR ... | | | GSAM ... |
        section_row = (
            ["GSDM"] + [""] * (max(1, _cols(gsdm_block)) - 1)
            + [""] * 2
            + ["GTSMR"] + [""] * (max(1, _cols(gtsmr_block)) - 1)
            + [""] * 2
            + ["GSAM"] + [""] * (max(1, _cols(gsam_block)) - 1)
        )
        ws.append(section_row)

        # Compose row-by-row, padding shorter blocks with empties.
        max_rows = max(len(gsdm_block), len(gtsmr_block), len(gsam_block))
        for r in range(max_rows):
            gsdm_row = gsdm_block[r] if r < len(gsdm_block) else [""] * _cols(gsdm_block)
            gtsmr_row = gtsmr_block[r] if r < len(gtsmr_block) else [""] * _cols(gtsmr_block)
            gsam_row = gsam_block[r] if r < len(gsam_block) else [""] * _cols(gsam_block)
            ws.append(
                list(gsdm_row)
                + ["", ""]
                + list(gtsmr_row)
                + ["", ""]
                + list(gsam_row)
            )

    def _picker_catchment_for(self, gtsmr_case, gsdm_case):
        for pair, tab in (
            (gtsmr_case, self.gtsmr_tab),
            (gsdm_case, self.gsdm_tab),
        ):
            if pair is not None and getattr(tab, "picker", None) is not None:
                c = tab.picker.catchment()
                if c is not None:
                    return c
        return None

    def open_documentation(self):
        """Open the PMP methodology HTML in the OS default browser."""
        from ....qt_compat import QDesktopServices, QUrl
        doc = Path(__file__).resolve().parent.parent / "docs" / "pmp_methodology.html"
        if not doc.is_file():
            QMessageBox.warning(
                self, "Documentation missing",
                f"Could not find the methodology HTML at:\n{doc}"
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc)))

    def open_project(self):
        from ..pmp_toolbox import workbook

        path, _ = QFileDialog.getOpenFileName(
            self, "Open PMP project", "", "Excel workbook (*.xlsx)"
        )
        if not path:
            return
        try:
            report = workbook.load_project(path, self._tab_pairs())
        except workbook.WorkbookError as exc:
            QMessageBox.warning(self, "Could not open the project", str(exc))
            return
        self.project.set_path(path)
        # Rebuild session case list from whichever sub-tab now has cases.
        source = self.gsdm_tab if self.gsdm_tab.cases.list.count() else self.gtsmr_tab
        self._loading = True
        try:
            self._case_list.clear()
            self._session_cases.clear()
            for case in source.cases.cases():
                self._session_cases.append({"name": case.name, "layer": None})
                item = QListWidgetItem(case.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self._case_list.addItem(item)
        finally:
            self._loading = False
        if self._case_list.count():
            self._case_list.setCurrentRow(0)

        loaded = ", ".join(f"{k}: {n}" for k, n in report["loaded"].items())
        message = f"Opened {Path(path).name} — cases restored ({loaded})."
        if report.get("missing"):
            message += "  No sheet for: " + ", ".join(report["missing"]) + "."
        QMessageBox.information(self, "Project opened", message)
