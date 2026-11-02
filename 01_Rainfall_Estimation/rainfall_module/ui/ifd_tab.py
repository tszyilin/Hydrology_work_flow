"""IFD tab — per-catchment. Reads/writes ``catchment.ifd_result``."""
from __future__ import annotations

from ....qt_compat import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QObject,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QThread,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from ..core import bom_client
from ..core.ifd_export import csv_filename, write_all_design_csv


class _IfdWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, lat, lon):
        super().__init__(); self.lat, self.lon = lat, lon

    def run(self):
        try:
            self.finished.emit(bom_client.fetch_ifd(self.lat, self.lon))
        except Exception as e:
            self.failed.emit(str(e))


class IfdTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._catchment = None
        self._thread = None
        self._worker = None
        self._aep_checks: dict[str, QCheckBox] = {}
        self._suppress_check = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        buttons = QHBoxLayout()
        self.fetch_button = QPushButton("Fetch IFD")
        self.fetch_button.setEnabled(False)
        self.fetch_button.clicked.connect(self._on_fetch)
        buttons.addWidget(self.fetch_button)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._on_copy)
        buttons.addWidget(self.copy_button)

        self.save_button = QPushButton("Save CSV…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.status = QLabel("Choose a catchment location to enable IFD fetch.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        root.addWidget(self.status)

        # AEP / EY column picker — populated after a fetch.
        self.aep_group = QGroupBox("AEPs to include")
        self.aep_group.setVisible(False)
        aep_outer = QVBoxLayout(self.aep_group)
        select_row = QHBoxLayout()
        self.all_btn = QPushButton("All")
        self.none_btn = QPushButton("None")
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        select_row.addWidget(self.all_btn)
        select_row.addWidget(self.none_btn)
        select_row.addStretch(1)
        aep_outer.addLayout(select_row)
        self.aep_row = QHBoxLayout()
        aep_outer.addLayout(self.aep_row)
        root.addWidget(self.aep_group)

        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    def set_catchment(self, cat):
        self._catchment = cat
        if cat is None or not cat.has_location():
            self.fetch_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self._clear_table()
            self.status.setText("Pick a location for this catchment.")
            return

        in_cov = bom_client.within_ifd_coverage(cat.lat, cat.lon)
        self.fetch_button.setEnabled(in_cov)
        if cat.ifd_result is not None:
            self._populate(cat.ifd_result)
            self._build_aep_checks(cat.ifd_result["aep_cols"], cat.ifd_aeps_selected)
            self._apply_column_visibility()
            self.save_button.setEnabled(True)
            self.copy_button.setEnabled(True)
            self.status.setText(
                f"{cat.name}: cached IFD ({cat.lat:.3f}, {cat.lon:.3f}) — "
                f"{len(cat.ifd_result['durations'])} durations."
            )
        else:
            self._clear_table()
            self.save_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            if in_cov:
                self.status.setText(
                    f"{cat.name}: ready. Click 'Fetch IFD' to query BoM (5–15 s)."
                )
            else:
                self.status.setText(
                    f"({cat.lat:.3f}, {cat.lon:.3f}) is outside BoM Revised IFD 2016 coverage."
                )

    # ------------------------------------------------------------------
    def _on_fetch(self):
        cat = self._catchment
        if cat is None or not cat.has_location():
            return
        self.fetch_button.setEnabled(False)
        self.status.setText(f"{cat.name}: fetching BoM Revised IFD 2016…")
        self._thread = QThread(self)
        self._worker = _IfdWorker(cat.lat, cat.lon)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_result)
        self._worker.failed.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_result(self, result):
        cat = self._catchment
        if cat is not None:
            cat.ifd_result = result
        self._populate(result)
        self._build_aep_checks(result["aep_cols"],
                               cat.ifd_aeps_selected if cat is not None else None)
        self._apply_column_visibility()
        self.fetch_button.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.save_button.setEnabled(True)
        if cat is not None:
            self.status.setText(
                f"{cat.name}: BoM Revised IFD 2016 at {cat.lat:.3f}, {cat.lon:.3f} — "
                f"{len(result['durations'])} durations × {len(result['aep_cols'])} AEPs."
            )

    def _on_error(self, msg):
        self.fetch_button.setEnabled(True)
        self.status.setText("IFD fetch failed.")
        QMessageBox.warning(self, "IFD fetch failed", msg)

    def _clear_table(self):
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._clear_aep_checks()

    def _clear_aep_checks(self):
        for cb in self._aep_checks.values():
            cb.deleteLater()
        self._aep_checks.clear()
        while self.aep_row.count():
            item = self.aep_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.aep_group.setVisible(False)

    def _build_aep_checks(self, aep_cols, selected):
        self._clear_aep_checks()
        if not aep_cols:
            return
        self._suppress_check = True
        chosen = set(aep_cols) if selected is None else set(selected)
        for aep in aep_cols:
            cb = QCheckBox(str(aep))
            cb.setChecked(aep in chosen)
            cb.toggled.connect(self._on_aep_toggled)
            self.aep_row.addWidget(cb)
            self._aep_checks[aep] = cb
        self.aep_row.addStretch(1)
        self.aep_group.setVisible(True)
        self._suppress_check = False

    def _selected_aeps(self) -> list[str]:
        return [aep for aep, cb in self._aep_checks.items() if cb.isChecked()]

    def _apply_column_visibility(self):
        # Column 0 is Duration; AEP columns follow in the order they were added.
        cat = self._catchment
        aeps_all = list(self._aep_checks.keys())
        for i, aep in enumerate(aeps_all, start=1):
            self.table.setColumnHidden(i, not self._aep_checks[aep].isChecked())
        if cat is not None:
            selected = self._selected_aeps()
            # Store None when everything is checked so the default stays "all".
            cat.ifd_aeps_selected = None if selected == aeps_all else selected

    def _on_aep_toggled(self, _checked):
        if self._suppress_check:
            return
        self._apply_column_visibility()

    def _set_all(self, checked):
        self._suppress_check = True
        for cb in self._aep_checks.values():
            cb.setChecked(checked)
        self._suppress_check = False
        self._apply_column_visibility()

    def _populate(self, result):
        durations = result["durations"]; aeps = result["aep_cols"]; table = result["table"]
        self.table.clear()
        self.table.setRowCount(len(durations))
        self.table.setColumnCount(len(aeps) + 1)
        self.table.setHorizontalHeaderLabels(["Duration"] + list(aeps))
        for r, dur in enumerate(durations):
            self.table.setItem(r, 0, QTableWidgetItem(str(dur)))
            for c, aep in enumerate(aeps, start=1):
                val = table.get(dur, {}).get(aep)
                self.table.setItem(r, c, QTableWidgetItem("" if val is None else f"{val:.1f}"))
        self.table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    def _on_copy(self):
        cat = self._catchment
        if cat is None or cat.ifd_result is None:
            return
        r = cat.ifd_result
        aeps = self._selected_aeps() or list(r["aep_cols"])
        lines = ["\t".join(["Duration"] + list(aeps))]
        for dur in r["durations"]:
            vals = [dur] + [
                "" if r["table"].get(dur, {}).get(a) is None else f"{r['table'][dur][a]:.1f}"
                for a in aeps
            ]
            lines.append("\t".join(vals))
        QApplication.clipboard().setText("\n".join(lines))
        self.status.setText("IFD table copied to clipboard.")

    def _on_save(self):
        cat = self._catchment
        if cat is None or cat.ifd_result is None:
            return
        default = csv_filename(cat.lat, cat.lon)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save IFD CSV (BoM 'all design' format)", default, "CSV files (*.csv)"
        )
        if not path:
            return
        write_all_design_csv(
            path, cat.lat, cat.lon, cat.ifd_result,
            location_label=cat.name,
            aeps=self._selected_aeps() or None,
        )
        self.status.setText(f"Saved -> {path}")
