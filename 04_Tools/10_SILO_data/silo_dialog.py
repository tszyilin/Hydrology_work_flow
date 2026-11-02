"""Qt dialog for the SILO Station Data tool.

Qt port of the Tk app in silo_gui.py, so it can dock inside QGIS (whose
Python has no tkinter). Search a SILO Patched Point station by number or
name, download its daily data and save an Actual / Synthetic workbook.
Network calls run on a QThread so QGIS stays responsive.

The download and classification live in silo_core.py, shared with the Tk app.
Settings (email, folder, variables) are kept in QSettings rather than a json
file next to the code, so they survive reinstalling the plugin.
"""
from __future__ import annotations

import datetime as dt
import os
import re

from qgis.PyQt.QtCore import QDate, QObject, QSettings, Qt, QThread, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateEdit, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

try:
    from .silo_core import EMAIL_RE, FIRST_DATE, VARIABLES, download_to_excel, search_stations
except ImportError:  # run from the 10_SILO_data folder, not as a package
    from silo_core import EMAIL_RE, FIRST_DATE, VARIABLES, download_to_excel, search_stations

SETTINGS_GROUP = 'HydrologyWorkflowSuite/silo'
COLUMNS = (('number', 'No.', 70), ('name', 'Name', 280), ('state', 'State', 60),
           ('lat', 'Lat', 80), ('lon', 'Lon', 80), ('elevation', 'Elev (m)', 80))


def _qdate(d):
    return QDate(d.year, d.month, d.day)


def _pydate(q):
    return dt.date(q.year(), q.month(), q.day())


class _Worker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, work):
        super().__init__()
        self.work = work

    def run(self):
        try:
            self.finished.emit(self.work())
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)


class SiloDialog(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent or (iface.mainWindow() if iface else None))
        self.iface = iface
        self.stations = []
        self.selected = None
        self._thread = None
        self._worker = None
        self._busy = False
        self._on_done = None
        self.setWindowTitle('SILO Station Data')
        self.setMinimumSize(720, 640)
        self._build_ui()
        self._load_settings()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel('Station number or name:'))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('e.g. 13017 or Giles')
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton('Search')
        self.search_btn.setAutoDefault(False)
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _k, h, _w in COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        for c, (_k, _h, width) in enumerate(COLUMNS):
            self.table.setColumnWidth(c, width)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table, 1)

        self.selected_label = QLabel('No station selected')
        font = self.selected_label.font()
        font.setBold(True)
        self.selected_label.setFont(font)
        layout.addWidget(self.selected_label)

        dates = QHBoxLayout()
        yesterday = dt.date.today() - dt.timedelta(days=1)
        self.start_edit = self._date_edit(FIRST_DATE, yesterday)
        self.end_edit = self._date_edit(yesterday, yesterday)
        dates.addWidget(QLabel('Start:'))
        dates.addWidget(self.start_edit)
        dates.addSpacing(16)
        dates.addWidget(QLabel('End:'))
        dates.addWidget(self.end_edit)
        dates.addStretch()
        layout.addLayout(dates)

        var_box = QGroupBox('Variables')
        grid = QGridLayout(var_box)
        self.var_checks = {}
        for i, (_code, col, label, default) in enumerate(VARIABLES):
            cb = QCheckBox(label)
            cb.setChecked(default)
            grid.addWidget(cb, i // 3, i % 3)
            self.var_checks[col] = cb
        row = len(VARIABLES) // 3 + 1
        self.code15_cb = QCheckBox(
            'Count code 15 (accumulated rain redistributed by SILO) as Actual')
        self.code15_cb.setChecked(True)
        grid.addWidget(self.code15_cb, row, 0, 1, 3)
        self.spread15_cb = QCheckBox(
            "Spread code 15 rain evenly over its days (instead of SILO's split)")
        self.spread15_cb.setChecked(True)
        grid.addWidget(self.spread15_cb, row + 1, 0, 1, 3)
        layout.addWidget(var_box)

        form = QGridLayout()
        form.addWidget(QLabel('Email (SILO API username):'), 0, 0)
        self.email_edit = QLineEdit()
        form.addWidget(self.email_edit, 0, 1, 1, 2)
        form.addWidget(QLabel('Save to folder:'), 1, 0)
        self.out_edit = QLineEdit()
        form.addWidget(self.out_edit, 1, 1)
        browse_btn = QPushButton('Browse…')
        browse_btn.setAutoDefault(False)
        browse_btn.clicked.connect(self._on_browse)
        form.addWidget(browse_btn, 1, 2)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.download_btn = QPushButton('Download')
        self.download_btn.setAutoDefault(False)
        self.download_btn.clicked.connect(self._on_download)
        btn_row.addWidget(self.download_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        btn_row.addWidget(self.progress, 1)
        close_btn = QPushButton('Close')
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.status_label = QLabel(
            'Type a station number (e.g. 13017) or part of a name, then Search.')
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet('color:#555;')
        layout.addWidget(self.status_label)

    @staticmethod
    def _date_edit(value, latest):
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat('yyyy-MM-dd')
        edit.setDateRange(_qdate(FIRST_DATE), _qdate(latest))
        edit.setDate(_qdate(value))
        return edit

    # ── Background work: network calls run off the UI thread ───────
    def _run_bg(self, work, on_done, busy_text):
        self.status_label.setText(busy_text)
        self.progress.setRange(0, 0)
        self.search_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self._busy = True
        self._on_done = on_done
        self._thread = QThread(self)
        self._worker = _Worker(work)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_result)
        self._worker.failed.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _idle(self):
        self._busy = False
        self.progress.setRange(0, 1)
        self.search_btn.setEnabled(True)
        self.download_btn.setEnabled(True)

    def _on_result(self, result):
        self._idle()
        self._on_done(result)

    def _on_error(self, msg):
        self._idle()
        self.status_label.setText('Error: ' + msg.splitlines()[0])
        QMessageBox.critical(self, 'SILO', msg)

    def is_busy(self):
        # A flag, not self._thread.isRunning(): the thread deletes itself
        # when done, leaving a dead Python wrapper behind.
        return self._busy

    # ── Handlers ────────────────────────────────────────────────────
    def _on_search(self):
        text = self.search_edit.text().strip()
        if not text or self.is_busy():
            return
        self._run_bg(lambda: search_stations(text), self._show_results,
                     f"Searching SILO for '{text}'…")

    def _show_results(self, stations):
        # Clear first, so re-selecting row 0 below fires itemSelectionChanged
        self.table.clearSelection()
        self.stations = stations
        self.selected = None
        self.selected_label.setText('No station selected')
        self.table.setRowCount(len(stations))
        center = Qt.AlignmentFlag.AlignCenter
        for r, s in enumerate(stations):
            for c, (key, _h, _w) in enumerate(COLUMNS):
                item = QTableWidgetItem(str(s[key]))
                if key != 'name':
                    item.setTextAlignment(center)
                self.table.setItem(r, c, item)
        if not stations:
            self.status_label.setText('No stations found. Try a shorter part of the name.')
            return
        self.status_label.setText(
            f'{len(stations)} station(s) found. Select one, then Download.')
        if len(stations) == 1:
            self.table.selectRow(0)

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        self.selected = s = self.stations[rows[0].row()]
        self.selected_label.setText(
            f"Selected: {s['number']} – {s['name']} ({s['state']}, {s['lat']}, {s['lon']})")

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, 'Save SILO workbooks to', self.out_edit.text().strip())
        if folder:
            self.out_edit.setText(folder)

    def _on_download(self):
        if self.is_busy():
            return
        if not self.selected:
            QMessageBox.warning(self, 'SILO', 'Search for and select a station first.')
            return
        start, end = _pydate(self.start_edit.date()), _pydate(self.end_edit.date())
        if start > end:
            QMessageBox.warning(self, 'SILO', 'Start date is after end date.')
            return
        email = self.email_edit.text().strip()
        if not re.fullmatch(EMAIL_RE, email):
            QMessageBox.warning(
                self, 'SILO', 'Enter a valid email address — SILO uses it as the API username.')
            return
        columns = [col for col, cb in self.var_checks.items() if cb.isChecked()]
        if not columns:
            QMessageBox.warning(self, 'SILO', 'Tick at least one variable.')
            return
        out_dir = self.out_edit.text().strip() or self._default_folder()
        self.out_edit.setText(out_dir)
        actual_codes = {0, 15} if self.code15_cb.isChecked() else {0}
        spread15 = self.spread15_cb.isChecked()
        station = self.selected
        self._save_settings()

        self._run_bg(
            lambda: download_to_excel(station, start, end, columns, email,
                                      actual_codes, spread15, out_dir),
            self._download_done,
            f"Downloading {station['number']} {station['name']} {start} to {end}…")

    def _download_done(self, result):
        path, summary = result
        lines = [f"{r['Variable']}: {r['Actual %']}% actual" for _, r in summary.iterrows()]
        self.status_label.setText(f'Saved {path}')
        if QMessageBox.question(
                self, 'SILO',
                f'Saved:\n{path}\n\n' + '\n'.join(lines) + '\n\nOpen the file now?'
        ) == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ── Settings ────────────────────────────────────────────────────
    @staticmethod
    def _default_folder():
        downloads = os.path.join(os.path.expanduser('~'), 'Downloads')
        return downloads if os.path.isdir(downloads) else os.path.expanduser('~')

    @staticmethod
    def _bool(value, default):
        if value is None:
            return default
        if isinstance(value, str):
            return value.lower() == 'true'
        return bool(value)

    def _load_settings(self):
        s = QSettings()
        s.beginGroup(SETTINGS_GROUP)
        self.email_edit.setText(s.value('email', '') or '')
        self.out_edit.setText(s.value('output_dir', '') or self._default_folder())
        saved = s.value('variables', '') or ''
        if saved:
            chosen = set(saved.split(','))
            for col, cb in self.var_checks.items():
                cb.setChecked(col in chosen)
        self.code15_cb.setChecked(self._bool(s.value('code15_actual'), True))
        self.spread15_cb.setChecked(self._bool(s.value('spread_code15'), True))
        s.endGroup()

    def _save_settings(self):
        s = QSettings()
        s.beginGroup(SETTINGS_GROUP)
        s.setValue('email', self.email_edit.text().strip())
        s.setValue('output_dir', self.out_edit.text().strip())
        s.setValue('variables',
                   ','.join(col for col, cb in self.var_checks.items() if cb.isChecked()))
        s.setValue('code15_actual', self.code15_cb.isChecked())
        s.setValue('spread_code15', self.spread15_cb.isChecked())
        s.endGroup()
