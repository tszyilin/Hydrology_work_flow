"""Qt dialog for the FFA tool. Keeps all UI concerns out of ffa_core."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import ffa_core


_DISTRIBUTIONS = ("LP3", "GEV", "Gumbel", "GPD")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class FfaDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle('Flood Frequency Analysis')
        self.setMinimumSize(760, 560)

        self._ams_keys = None   # years (ints) once resolved
        self._ams_vals = None   # numpy array
        self._last_results = None  # (headers, rows, fits_with_ci)

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_input_tab(), 'Input')
        self.tabs.addTab(self._build_fit_tab(), 'Fit')
        self.tabs.addTab(self._build_results_tab(), 'Results')
        root.addWidget(self.tabs, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        root.addLayout(btns)

    def _build_input_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # CSV file row
        row = QHBoxLayout()
        row.addWidget(QLabel('CSV file:'))
        self.csv_edit = QLineEdit()
        self.csv_edit.setPlaceholderText('Path to AMS or continuous-series CSV')
        row.addWidget(self.csv_edit, 1)
        browse = QPushButton('Browse...')
        browse.clicked.connect(self._pick_csv)
        row.addWidget(browse)
        v.addLayout(row)

        # Mode toggle
        mode_box = QGroupBox('Input mode')
        mode_l = QHBoxLayout(mode_box)
        self.rb_ams = QRadioButton('Annual max series (year, value)')
        self.rb_ams.setChecked(True)
        self.rb_cont = QRadioButton('Continuous (date, value)')
        self.rb_ams.toggled.connect(self._on_mode_changed)
        mode_l.addWidget(self.rb_ams)
        mode_l.addWidget(self.rb_cont)
        mode_l.addStretch()
        v.addWidget(mode_box)

        # Column mapping
        cols_box = QGroupBox('Columns')
        cols = QFormLayout(cols_box)
        self.col_key = QComboBox()
        self.col_val = QComboBox()
        self.key_label = QLabel('Year column:')
        cols.addRow(self.key_label, self.col_key)
        cols.addRow('Value column:', self.col_val)
        self.wy_month = QComboBox()
        self.wy_month.addItems(_MONTHS)
        self.wy_month.setCurrentIndex(6)  # July
        self.wy_label = QLabel('Water-year start month:')
        cols.addRow(self.wy_label, self.wy_month)
        v.addWidget(cols_box)

        # Resolve + preview
        resolve_row = QHBoxLayout()
        self.resolve_btn = QPushButton('Resolve AMS')
        self.resolve_btn.clicked.connect(self._resolve_ams)
        resolve_row.addWidget(self.resolve_btn)
        resolve_row.addStretch()
        self.ams_count = QLabel('No AMS resolved yet.')
        resolve_row.addWidget(self.ams_count)
        v.addLayout(resolve_row)

        self.ams_preview = QTableWidget(0, 2)
        self.ams_preview.setHorizontalHeaderLabels(['Year', 'Value'])
        self.ams_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.ams_preview, 1)

        self._on_mode_changed()
        return w

    def _build_fit_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        dist_box = QGroupBox('Distributions to fit')
        dl = QHBoxLayout(dist_box)
        self.dist_checks = {}
        for d in _DISTRIBUTIONS:
            cb = QCheckBox(d)
            cb.setChecked(d in ('LP3', 'GEV'))
            dl.addWidget(cb)
            self.dist_checks[d] = cb
        dl.addStretch()
        v.addWidget(dist_box)

        method_box = QGroupBox('Fitting method')
        ml = QHBoxLayout(method_box)
        self.rb_lmom = QRadioButton('L-moments (recommended)')
        self.rb_lmom.setChecked(True)
        self.rb_mle = QRadioButton('MLE')
        ml.addWidget(self.rb_lmom)
        ml.addWidget(self.rb_mle)
        ml.addStretch()
        v.addWidget(method_box)

        boot_box = QGroupBox('Bootstrap confidence interval')
        bl = QFormLayout(boot_box)
        self.n_boot = QSpinBox()
        self.n_boot.setRange(0, 20000)
        self.n_boot.setValue(1000)
        self.n_boot.setToolTip('0 to skip bootstrap')
        self.alpha = QDoubleSpinBox()
        self.alpha.setDecimals(3)
        self.alpha.setRange(0.001, 0.5)
        self.alpha.setSingleStep(0.01)
        self.alpha.setValue(0.05)
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2_147_483_647)
        self.seed.setValue(-1)
        self.seed.setToolTip('-1 = random')
        bl.addRow('Resamples:', self.n_boot)
        bl.addRow('Alpha (1-CI):', self.alpha)
        bl.addRow('Random seed:', self.seed)
        v.addWidget(boot_box)

        aris_row = QHBoxLayout()
        aris_row.addWidget(QLabel('ARIs (years, comma-separated):'))
        self.aris_edit = QLineEdit('2,5,10,20,50,100,200,500,1000')
        aris_row.addWidget(self.aris_edit, 1)
        v.addLayout(aris_row)

        self.run_btn = QPushButton('Run FFA')
        self.run_btn.clicked.connect(self._run)
        v.addWidget(self.run_btn)
        v.addStretch()
        return w

    def _build_results_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.results_table = QTableWidget(0, 0)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.results_table, 1)

        self.plot_container = QWidget()
        self.plot_container_layout = QVBoxLayout(self.plot_container)
        self.plot_container_layout.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.plot_container, 2)

        row = QHBoxLayout()
        row.addStretch()
        self.export_csv_btn = QPushButton('Export CSV...')
        self.export_csv_btn.clicked.connect(self._export_csv)
        self.export_csv_btn.setEnabled(False)
        self.export_png_btn = QPushButton('Export PNG...')
        self.export_png_btn.clicked.connect(self._export_png)
        self.export_png_btn.setEnabled(False)
        row.addWidget(self.export_csv_btn)
        row.addWidget(self.export_png_btn)
        v.addLayout(row)
        return w

    # ── Input helpers ──────────────────────────────────────────────────
    def _on_mode_changed(self):
        is_ams = self.rb_ams.isChecked()
        self.key_label.setText('Year column:' if is_ams else 'Date column:')
        self.wy_month.setEnabled(not is_ams)
        self.wy_label.setEnabled(not is_ams)

    def _pick_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select CSV', self.csv_edit.text() or '',
            'CSV files (*.csv);;All files (*.*)',
        )
        if not path:
            return
        self.csv_edit.setText(path)
        self._populate_columns(path)

    def _populate_columns(self, path):
        try:
            headers = ffa_core.read_csv_headers(path)
        except Exception as e:
            QMessageBox.warning(self, 'CSV error', f'Could not read headers:\n{e}')
            return
        for cb in (self.col_key, self.col_val):
            cb.clear()
            cb.addItems(headers)
        # Reasonable defaults by common names
        self._guess_column(self.col_key, headers,
                           ('year', 'wy', 'date', 'datetime', 'time'))
        self._guess_column(self.col_val, headers,
                           ('q', 'flow', 'discharge', 'peak', 'value', 'stage'))

    @staticmethod
    def _guess_column(combo, headers, needles):
        lower = [h.lower() for h in headers]
        for n in needles:
            for i, h in enumerate(lower):
                if n in h:
                    combo.setCurrentIndex(i)
                    return

    def _resolve_ams(self):
        path = self.csv_edit.text().strip()
        if not os.path.isfile(path):
            QMessageBox.warning(self, 'Missing CSV', 'Pick a CSV first.')
            return
        key = self.col_key.currentText()
        val = self.col_val.currentText()
        if not key or not val:
            QMessageBox.warning(self, 'Columns',
                                'Choose the year/date and value columns.')
            return
        try:
            if self.rb_ams.isChecked():
                keys, vals = ffa_core.load_series_csv(path, val, year_col=key)
            else:
                keys, vals = ffa_core.load_series_csv(path, val, date_col=key)
                keys, vals = ffa_core.extract_ams(
                    keys, vals, water_year_start_month=self.wy_month.currentIndex() + 1,
                )
        except Exception as e:
            QMessageBox.critical(self, 'Resolve AMS', f'{type(e).__name__}: {e}')
            return

        self._ams_keys = list(keys)
        self._ams_vals = vals
        self._fill_preview(keys, vals)
        self.ams_count.setText(
            f'{len(keys)} years, min {vals.min():.3g}, max {vals.max():.3g}'
        )

    def _fill_preview(self, keys, vals):
        self.ams_preview.setRowCount(len(keys))
        for i, (k, v) in enumerate(zip(keys, vals)):
            self.ams_preview.setItem(i, 0, QTableWidgetItem(str(k)))
            self.ams_preview.setItem(i, 1, QTableWidgetItem(f'{v:.6g}'))

    # ── Fit / results ──────────────────────────────────────────────────
    def _parse_aris(self):
        raw = self.aris_edit.text()
        out = []
        for part in raw.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                t = float(part)
            except ValueError:
                raise ValueError(f'Not a number: {part!r}')
            if t <= 1:
                raise ValueError(f'ARI must be > 1 year: {part}')
            out.append(t)
        if not out:
            raise ValueError('Enter at least one ARI.')
        return tuple(out)

    def _run(self):
        if self._ams_vals is None or len(self._ams_vals) < 5:
            QMessageBox.warning(self, 'No AMS',
                                'Resolve an AMS of at least 5 years first.')
            return
        dists = [d for d, cb in self.dist_checks.items() if cb.isChecked()]
        if not dists:
            QMessageBox.warning(self, 'Pick a distribution',
                                'Tick at least one distribution to fit.')
            return
        try:
            aris = self._parse_aris()
        except ValueError as e:
            QMessageBox.warning(self, 'ARIs', str(e))
            return

        method = 'lmom' if self.rb_lmom.isChecked() else 'mle'
        n_boot = int(self.n_boot.value())
        alpha = float(self.alpha.value())
        seed = None if self.seed.value() < 0 else int(self.seed.value())

        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        try:
            def cb(i, n, kept):
                if n:
                    self.progress.setValue(int(100 * i / n))

            headers, rows, fits_with_ci = ffa_core.results_table(
                self._ams_vals, distributions=dists, method=method,
                aris=aris, n_boot=n_boot, alpha=alpha, seed=seed,
                progress_cb=cb,
            )
            self.progress.setValue(100)
            self._last_results = (headers, rows, fits_with_ci)
            self._fill_results_table(headers, rows)
            self._draw_plot(fits_with_ci, aris)
            self.export_csv_btn.setEnabled(True)
            self.export_png_btn.setEnabled(True)
            self.tabs.setCurrentIndex(2)
        except Exception as e:
            QMessageBox.critical(self, 'FFA', f'{type(e).__name__}: {e}')
        finally:
            self.run_btn.setEnabled(True)
            self.progress.setValue(0)

    def _fill_results_table(self, headers, rows):
        self.results_table.clear()
        self.results_table.setColumnCount(len(headers))
        self.results_table.setRowCount(len(rows))
        self.results_table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                if isinstance(v, float):
                    txt = f'{v:.4g}' if abs(v) < 1e6 else f'{v:.6g}'
                else:
                    txt = str(v)
                self.results_table.setItem(r, c, QTableWidgetItem(txt))

    def _draw_plot(self, fits_with_ci, aris):
        # Clear any existing canvas
        for i in reversed(range(self.plot_container_layout.count())):
            item = self.plot_container_layout.takeAt(i)
            if item.widget():
                item.widget().deleteLater()

        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

        fig = ffa_core.plot_probability(
            self._ams_vals, fits_with_ci, aris=aris,
            title='Flood frequency plot',
        )
        canvas = FigureCanvasQTAgg(fig)
        self.plot_container_layout.addWidget(canvas)
        canvas.draw()

    # ── Export ─────────────────────────────────────────────────────────
    def _export_csv(self):
        if not self._last_results:
            return
        default = ''
        src = self.csv_edit.text().strip()
        if src:
            base, _ = os.path.splitext(src)
            default = base + '_ffa.csv'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save results CSV', default, 'CSV (*.csv)',
        )
        if not path:
            return
        headers, rows, _ = self._last_results
        try:
            ffa_core.write_results_csv(path, headers, rows)
        except Exception as e:
            QMessageBox.critical(self, 'Export CSV', f'{type(e).__name__}: {e}')
            return
        QMessageBox.information(self, 'Export CSV', f'Written to:\n{path}')

    def _export_png(self):
        if not self._last_results:
            return
        default = ''
        src = self.csv_edit.text().strip()
        if src:
            base, _ = os.path.splitext(src)
            default = base + '_ffa.png'
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save plot PNG', default, 'PNG (*.png)',
        )
        if not path:
            return
        _, _, fits_with_ci = self._last_results
        try:
            aris = self._parse_aris()
            ffa_core.plot_probability(
                self._ams_vals, fits_with_ci, aris=aris,
                title='Flood frequency plot', out_png=path,
            )
        except Exception as e:
            QMessageBox.critical(self, 'Export PNG', f'{type(e).__name__}: {e}')
            return
        QMessageBox.information(self, 'Export PNG', f'Written to:\n{path}')
