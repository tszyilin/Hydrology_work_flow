"""Qt dialog for the Cut & Fill Volume tool.

Inputs tab: DEM, polygons, base heights, sampling and the GM scale factor.
Results tab: a Summary of every area plus each area's stage-volume table,
computed the way Global Mapper does, with Save to Excel (Summary + one
sheet per area + Notes), Save GM CSVs and Copy table. "Calibrate from GM report..." derives the GM scale
factor from a Global Mapper report for one polygon.

The calculation itself lives in cut_fill_volume.py, shared with the
Processing algorithm.
"""
from __future__ import annotations

import os

from osgeo import ogr
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from qgis.core import (
    Qgis, QgsCoordinateTransform, QgsDistanceArea, QgsMapLayerProxyModel,
    QgsProject,
)
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox, QgsRasterBandComboBox

try:
    from .cut_fill_volume import (
        AREA_COLUMNS, GM_SCALE_FACTOR,
        GM_SCALE_FACTOR_EXPLANATION, SUMMARY_COLUMNS, _area_rows,
        _gm_sphere_area, calibrate_gm_factor, gm_factor_label,
        _sheet_names, _summary_row, area_summary_text, cut_fill_for_polygon,
        write_excel, write_gm_csvs,
    )
except ImportError:  # run from the 09_cut&fill folder, not as a package
    from cut_fill_volume import (
        AREA_COLUMNS, GM_SCALE_FACTOR,
        GM_SCALE_FACTOR_EXPLANATION, SUMMARY_COLUMNS, _area_rows,
        _gm_sphere_area, calibrate_gm_factor, gm_factor_label,
        _sheet_names, _summary_row, area_summary_text, cut_fill_for_polygon,
        write_excel, write_gm_csvs,
    )

SUMMARY_KEY = '__summary__'
NUMBER_FORMATS = {'m3': '{:,.1f}', 'ML': '{:,.3f}', 'm2': '{:,.0f}',
                  'm': '{:.3f}', None: '{}'}
MAX_COLUMN_WIDTH = 220   # px; long area names would otherwise fill the table


def _layer_filter(name):
    """Qgis.LayerFilter (QGIS >= 3.34) or the old QgsMapLayerProxyModel enum."""
    scoped = getattr(Qgis, 'LayerFilter', None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(QgsMapLayerProxyModel, name)


def _clean_source_path(src):
    """QGIS raster sources sometimes include provider options after '|'."""
    return src.split('|', 1)[0] if src else src


def _fmt(value, unit):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return NUMBER_FORMATS.get(unit, '{}').format(value)


class CutFillDialog(QDialog):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent or (iface.mainWindow() if iface else None))
        self.iface = iface
        self.areas = []
        self.scale = 0.0   # 0 = auto GM factor per area
        self.setWindowTitle('Cut & Fill Volume')
        self.setMinimumSize(720, 560)
        self._build_ui()
        self._on_dem_changed(self.dem_combo.currentLayer())
        self._on_poly_changed(self.poly_combo.currentLayer())

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_inputs_tab(), 'Inputs')
        self.tabs.addTab(self._build_results_tab(), 'Results')
        self.tabs.setTabEnabled(1, False)

        btn_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        btn_row.addWidget(self.progress, 1)
        self.run_btn = QPushButton('Run')
        self.run_btn.clicked.connect(self._run)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_inputs_tab(self):
        page = QWidget()
        form = QFormLayout(page)

        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(_layer_filter('RasterLayer'))
        self.dem_combo.layerChanged.connect(self._on_dem_changed)
        form.addRow('DEM raster:', self.dem_combo)
        self.band_combo = QgsRasterBandComboBox()
        form.addRow('Band:', self.band_combo)

        self.poly_combo = QgsMapLayerComboBox()
        self.poly_combo.setFilters(_layer_filter('PolygonLayer'))
        self.poly_combo.layerChanged.connect(self._on_poly_changed)
        form.addRow('Polygon layer:', self.poly_combo)
        self.selected_cb = QCheckBox('Selected features only')
        form.addRow('', self.selected_cb)
        self.name_combo = QgsFieldComboBox()
        self.name_combo.setAllowEmptyFieldName(True)
        form.addRow('Name field:', self.name_combo)

        # Base heights are set by the user, as in Global Mapper's
        # "Perform Multiple Calculations Over a Range of Base Heights".
        self.start_spin = self._spin(3, -10000, 10000, 0.0, 0.1)
        self.end_spin = self._spin(3, -10000, 10000, 0.0, 0.1)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel('from'))
        range_row.addWidget(self.start_spin, 1)
        range_row.addWidget(QLabel('to'))
        range_row.addWidget(self.end_spin, 1)
        range_row.addWidget(QLabel('m'))
        form.addRow('Base heights:', range_row)
        self.step_spin = self._spin(3, 0.001, 1000, 0.1, 0.1)
        form.addRow('Step (m):', self.step_spin)

        self.spacing_spin = self._spin(3, 0.0, 10000, 0.0, 0.5)
        self.spacing_spin.setSpecialValueText('Auto (Global Mapper: min(cell / 2, bbox side / 200))')
        form.addRow('Sample spacing (m):', self.spacing_spin)
        self.scale_spin = self._spin(6, 0.0, 10.0, 0.0, 0.0001)
        self.scale_spin.setSpecialValueText('Auto (Global Mapper sphere model)')
        self.scale_spin.setToolTip('\n\n'.join(GM_SCALE_FACTOR_EXPLANATION))
        why_btn = QPushButton('How is it worked out?')
        why_btn.setToolTip('How the Global Mapper scale factor is worked out')
        why_btn.clicked.connect(self._explain_scale_factor)
        cal_btn = QPushButton('Calibrate from GM report...')
        cal_btn.setToolTip(
            'Work out the factor for this site from a Global Mapper '
            'cut-and-fill report of one polygon in the polygon layer')
        cal_btn.clicked.connect(self._calibrate_from_report)
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_spin, 1)
        scale_row.addWidget(why_btn)
        scale_row.addWidget(cal_btn)
        form.addRow('GM area scale factor:', scale_row)

        note = QLabel(
            'Cut = ground above the base height; fill = space below it. '
            'Results are computed the way Global Mapper does: its sample '
            'spacing and its area model (Auto works the factor out for each '
            'polygon at any location, or type / calibrate a value).')
        note.setWordWrap(True)
        note.setStyleSheet('color:#555;')
        form.addRow(note)
        return page

    def _explain_scale_factor(self):
        title, *paragraphs = GM_SCALE_FACTOR_EXPLANATION
        box = QMessageBox(self)
        box.setWindowTitle('GM area scale factor')
        box.setIcon(QMessageBox.Icon.Information)
        box.setText('<b>%s</b>' % title)
        box.setInformativeText('\n\n'.join(paragraphs))
        box.exec()

    def _calibration_polygon(self):
        """(label, planar area, auto GM factor) of the one polygon to
        calibrate against, in the DEM CRS, or None after telling the user
        why not."""
        dem = self.dem_combo.currentLayer()
        polys = self.poly_combo.currentLayer()
        if dem is None or polys is None:
            QMessageBox.warning(self, 'Calibrate',
                                'Select the DEM and the polygon layer first.')
            return None
        feats = list(polys.getSelectedFeatures())
        if not feats and polys.featureCount() == 1:
            feats = list(polys.getFeatures())
        if len(feats) != 1:
            QMessageBox.warning(
                self, 'Calibrate',
                'Select the one polygon the Global Mapper report is for '
                '(%d selected).' % len(feats))
            return None
        feat = feats[0]
        geom = feat.geometry()
        if polys.crs().isValid() and dem.crs().isValid() and polys.crs() != dem.crs():
            geom.transform(QgsCoordinateTransform(polys.crs(), dem.crs(),
                                                  QgsProject.instance()))
        name_field = self.name_combo.currentField()
        label = feat[name_field] if name_field else None
        planar = geom.area()
        sphere = _gm_sphere_area(ogr.CreateGeometryFromWkt(geom.asWkt()),
                                 dem.crs().toWkt())
        auto = sphere / planar if sphere and planar else None
        return str(label if label not in (None, '') else feat.id()), planar, auto

    def _calibrate_from_report(self):
        target = self._calibration_polygon()
        if target is None:
            return
        label, planar, auto = target
        path, _ = QFileDialog.getOpenFileName(
            self, 'Global Mapper cut-and-fill report for %s' % label, '',
            'Global Mapper report (*.txt *.csv);;All files (*)')
        if not path:
            return
        try:
            cal = calibrate_gm_factor(path, planar)
        except Exception as e:
            QMessageBox.critical(self, 'Calibrate', 'Could not read the report:\n%s' % e)
            return
        lines = [
            'Polygon: %s' % label,
            'Report: %s (%d base heights)' % (os.path.basename(path), cal['rows']),
            '',
            'Area Global Mapper used: %s m2' % format(cal['gm_area'], ',.1f'),
            'Planar area of the polygon: %s m2' % format(planar, ',.1f'),
            'GM scale factor = %s / %s = %.6f' % (
                format(cal['gm_area'], ',.1f'), format(planar, ',.1f'), cal['factor']),
        ]
        if auto:
            lines.append('Auto (sphere model) for this polygon: %.6f (%+.3f %%)'
                         % (auto, 100 * (auto / cal['factor'] - 1)))
        warn = []
        if cal['rel_residual'] > 1e-3:
            warn.append('CUT - FILL is not a straight line against base height '
                        '(largest miss %.2f %%), so the report may cover more '
                        'than one polygon or a different surface.'
                        % (100 * cal['rel_residual']))
        if abs(cal['factor'] - 1) > 0.02:
            warn.append('The factor is more than 2 % from 1. Check that the '
                        'report is for this polygon.')
        if warn:
            lines += [''] + ['Warning: ' + w for w in warn]
        lines += ['', 'Use this factor for the GM columns?']
        if QMessageBox.question(self, 'Calibrate from GM report',
                                '\n'.join(lines)) == QMessageBox.StandardButton.Yes:
            self.scale_spin.setValue(round(cal['factor'], 6))

    def _build_results_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)

        top = QHBoxLayout()
        top.addWidget(QLabel('Show:'))
        self.area_combo = QComboBox()
        self.area_combo.currentIndexChanged.connect(self._refresh_table)
        top.addWidget(self.area_combo, 1)
        v.addLayout(top)

        self.info_label = QLabel('')
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet('color:#555;')
        v.addWidget(self.info_label)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.cellDoubleClicked.connect(self._on_summary_double_click)
        v.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.excel_btn = QPushButton('Save to Excel...')
        self.excel_btn.setToolTip('Workbook with a Summary sheet and one sheet per area')
        self.excel_btn.clicked.connect(self._save_excel)
        self.csv_btn = QPushButton('Save GM CSVs...')
        self.csv_btn.setToolTip('<name>.csv per area, in Global Mapper text format')
        self.csv_btn.clicked.connect(self._save_csvs)
        self.copy_btn = QPushButton('Copy table')
        self.copy_btn.setToolTip('Copy the table shown, tab-separated, for pasting into Excel')
        self.copy_btn.clicked.connect(self._copy_table)
        btns.addWidget(self.excel_btn)
        btns.addWidget(self.csv_btn)
        btns.addWidget(self.copy_btn)
        btns.addStretch()
        v.addLayout(btns)
        return page

    @staticmethod
    def _spin(decimals, lo, hi, value, step):
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(lo, hi)
        s.setValue(value)
        s.setSingleStep(step)
        return s

    # ── Signal handlers ─────────────────────────────────────────────
    def _on_dem_changed(self, layer):
        self.band_combo.setLayer(layer)

    def _on_poly_changed(self, layer):
        self.name_combo.setLayer(layer)

    def _on_summary_double_click(self, row, _col):
        if self.area_combo.currentData() == SUMMARY_KEY and row < len(self.areas):
            self.area_combo.setCurrentIndex(row + 1)

    # ── Run ─────────────────────────────────────────────────────────
    def _run(self):
        dem = self.dem_combo.currentLayer()
        polys = self.poly_combo.currentLayer()
        if dem is None or polys is None:
            QMessageBox.warning(self, 'Missing input',
                                'Select a DEM raster and a polygon layer.')
            return
        dem_path = _clean_source_path(dem.source())
        if dem.providerType() != 'gdal' or not os.path.exists(dem_path):
            QMessageBox.warning(self, 'Invalid DEM',
                                f'The DEM must be a file-based raster:\n{dem_path}')
            return
        feats = (list(polys.getSelectedFeatures()) if self.selected_cb.isChecked()
                 else list(polys.getFeatures()))
        if not feats:
            QMessageBox.warning(self, 'No polygons',
                                'The polygon layer has no (selected) features.')
            return

        step = self.step_spin.value()
        start, end = self.start_spin.value(), self.end_spin.value()
        if end <= start:
            QMessageBox.warning(self, 'Base heights',
                                'Enter the base height range: "to" must be '
                                'above "from".')
            return
        n_rows = int((end - start) / step + 1e-9) + 1
        if n_rows > 5000 and QMessageBox.question(
                self, 'Base heights',
                '%d base heights (%g to %g m in %g m steps). Continue?'
                % (n_rows, start, end, step)) != QMessageBox.StandardButton.Yes:
            return
        spacing = self.spacing_spin.value() or None
        band = self.band_combo.currentBand() or 1
        scale = self.scale_spin.value()
        name_field = self.name_combo.currentField()

        project = QgsProject.instance()
        dem_crs = dem.crs()
        xform = None
        if polys.crs().isValid() and dem_crs.isValid() and polys.crs() != dem_crs:
            xform = QgsCoordinateTransform(polys.crs(), dem_crs, project)
        da = QgsDistanceArea()
        da.setSourceCrs(dem_crs, project.transformContext())
        ellipsoid = project.ellipsoid()
        if not ellipsoid or ellipsoid == 'NONE':
            ellipsoid = dem_crs.ellipsoidAcronym() or 'EPSG:7019'
        da.setEllipsoid(ellipsoid)

        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        areas, skipped = [], []
        try:
            for n, feat in enumerate(feats):
                label = feat.id()
                if name_field and feat[name_field] not in (None, ''):
                    label = feat[name_field]
                label = str(label)
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    skipped.append(label)
                    continue
                if xform is not None:
                    geom.transform(xform)
                area = cut_fill_for_polygon(dem_path, geom.asWkt(), step, start,
                                            end, spacing, band, label)
                if area is None:
                    skipped.append(label)
                else:
                    if area['ellipsoidal_area'] is None:   # GDAL < 3.9
                        try:
                            area['ellipsoidal_area'] = da.measureArea(geom)
                        except Exception:
                            pass
                    areas.append(area)
                self.progress.setValue(int(100 * (n + 1) / len(feats)))
                QApplication.processEvents()
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Cut & fill failed:\n{e}')
            return
        finally:
            self.run_btn.setEnabled(True)

        if not areas:
            QMessageBox.warning(self, 'No results',
                                'None of the polygons overlap valid DEM cells.')
            return
        self._show_results(areas, scale)
        if skipped:
            QMessageBox.information(
                self, 'Some areas skipped',
                'No valid DEM cells inside: ' + ', '.join(skipped))

    # ── Results ─────────────────────────────────────────────────────
    def _show_results(self, areas, scale):
        self.areas, self.scale = areas, scale
        self.sheets = _sheet_names([a['name'] for a in areas])
        self.area_combo.blockSignals(True)
        self.area_combo.clear()
        self.area_combo.addItem('Summary (all areas)', SUMMARY_KEY)
        for i, sheet in enumerate(self.sheets):
            self.area_combo.addItem(sheet, i)
        self.area_combo.blockSignals(False)
        self.area_combo.setCurrentIndex(0 if len(areas) > 1 else 1)
        self._refresh_table()
        self.tabs.setTabEnabled(1, True)
        self.tabs.setCurrentIndex(1)

    def _current_table(self):
        """(headers, units, rows) for what the Results tab is showing."""
        key = self.area_combo.currentData()
        if key == SUMMARY_KEY:
            headers = [n for n, _u, _b in SUMMARY_COLUMNS]
            units = [u for _n, u, _b in SUMMARY_COLUMNS]
            rows = [_summary_row(a, s, self.scale)
                    for a, s in zip(self.areas, self.sheets)]
        else:
            headers = [n for n, _k, _b, _u in AREA_COLUMNS]
            units = [u for _n, _k, _b, u in AREA_COLUMNS]
            rows = _area_rows(self.areas[key], self.scale)
        return headers, units, rows

    def _refresh_table(self, *_):
        if not self.areas:
            return
        headers, units, rows = self._current_table()
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ['%s\n(%s)' % (h, u) if u else h for h, u in zip(headers, units)])
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(_fmt(value, units[c]))
                if not isinstance(value, str):
                    item.setTextAlignment(right)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            if self.table.columnWidth(c) > MAX_COLUMN_WIDTH:
                self.table.setColumnWidth(c, MAX_COLUMN_WIDTH)

        key = self.area_combo.currentData()
        if key == SUMMARY_KEY:
            self.info_label.setText(
                '%d areas. Double-click a row to open that area. Computed the '
                'way Global Mapper does (GM factor: %s).'
                % (len(self.areas), gm_factor_label(self.scale)))
        else:
            self.info_label.setText(area_summary_text(self.areas[key], self.scale))

    # ── Saving ──────────────────────────────────────────────────────
    def _default_path(self, suffix):
        layer = self.poly_combo.currentLayer()
        src = _clean_source_path(layer.source()) if layer else ''
        if src and os.path.isfile(src):
            return os.path.splitext(src)[0] + suffix
        return suffix.lstrip('_')

    def _save_excel(self):
        if not self.areas:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save cut & fill results', self._default_path('_cut_fill.xlsx'),
            'Excel workbook (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            writer = write_excel(path, self.areas, self.scale)
        except PermissionError:
            QMessageBox.warning(self, 'File in use',
                                f'Cannot write {path}.\nClose it in Excel and try again.')
            return
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Could not save the workbook:\n{e}')
            return
        note = ('' if writer == 'openpyxl' else
                '\n\nopenpyxl is not installed in this QGIS, so the workbook '
                'has no formatting.')
        QMessageBox.information(
            self, 'Saved',
            f'Saved {len(self.areas)} area sheet(s) plus a Summary sheet to:\n'
            f'{path}{note}')

    def _save_csvs(self):
        if not self.areas:
            return
        folder = QFileDialog.getExistingDirectory(
            self, 'Folder for Global Mapper CSVs',
            os.path.dirname(self._default_path('_x')))
        if not folder:
            return
        try:
            paths = write_gm_csvs(folder, self.areas, self.scale)
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Could not save the CSVs:\n{e}')
            return
        QMessageBox.information(self, 'Saved',
                                f'Wrote {len(paths)} CSV files to:\n{folder}')

    def _copy_table(self):
        if not self.areas:
            return
        headers, units, rows = self._current_table()
        lines = ['\t'.join('%s (%s)' % (h, u) if u else h
                           for h, u in zip(headers, units))]
        for row in rows:
            lines.append('\t'.join('' if v is None else str(v) for v in row))
        QApplication.clipboard().setText('\n'.join(lines))
        self.info_label.setText('Copied %d rows to the clipboard.' % len(rows))
