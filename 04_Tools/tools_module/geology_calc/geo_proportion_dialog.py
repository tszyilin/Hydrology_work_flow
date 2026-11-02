import os

from qgis.PyQt.QtCore import Qt, QMetaType, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QFileDialog, QMessageBox, QApplication, QTableWidgetItem,
)
from qgis.PyQt import uic

from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsWkbTypes,
    QgsField,
)

from .geo_proportion_core import run_geo_proportion

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'geo_proportion_dialog.ui')
)

# Column indices in the batch queue table
_COL_GEO_LAYER  = 0
_COL_GEO_FIELD  = 1
_COL_CATCH_LAYER = 2
_COL_CATCH_FIELD = 3
_COL_OUTPUT      = 4


class GeoProportionDialog(QDialog, FORM_CLASS):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._batch_jobs = []   # list of dicts: {geo_layer_id, geo_field, catch_layer_id, catch_field, output_csv}
        self._connect_signals()
        self.tblBatch.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        # Single tab
        self.cmbGeoLayer.currentIndexChanged.connect(self._on_geo_layer_changed)
        self.cmbCatchLayer.currentIndexChanged.connect(self._on_catch_layer_changed)
        self.btnBrowse.clicked.connect(self._browse_output)

        # Batch tab
        self.cmbBGeoLayer.currentIndexChanged.connect(self._on_bgeo_layer_changed)
        self.cmbBCatchLayer.currentIndexChanged.connect(self._on_bcatch_layer_changed)
        self.btnBBrowse.clicked.connect(self._browse_batch_output)
        self.btnAddJob.clicked.connect(self._add_batch_job)
        self.btnRemoveJob.clicked.connect(self._remove_batch_job)

        # Shared
        self.tabWidget.currentChanged.connect(self._on_tab_changed)
        self.btnRun.clicked.connect(self._on_run)
        self.btnClose.clicked.connect(self.close)

    # ------------------------------------------------------------------
    # Layer / field population
    # ------------------------------------------------------------------

    def refresh_layers(self):
        """Repopulate all layer dropdowns from the current QGIS project."""
        for cmb in (self.cmbGeoLayer, self.cmbCatchLayer,
                    self.cmbBGeoLayer, self.cmbBCatchLayer):
            cmb.blockSignals(True)
            cmb.clear()

        for layer_id, layer in QgsProject.instance().mapLayers().items():
            if (layer.type() == QgsMapLayer.VectorLayer
                    and layer.geometryType() == QgsWkbTypes.PolygonGeometry):
                for cmb in (self.cmbGeoLayer, self.cmbCatchLayer,
                             self.cmbBGeoLayer, self.cmbBCatchLayer):
                    cmb.addItem(layer.name(), layer_id)

        for cmb in (self.cmbGeoLayer, self.cmbCatchLayer,
                    self.cmbBGeoLayer, self.cmbBCatchLayer):
            cmb.blockSignals(False)

        self._on_geo_layer_changed()
        self._on_catch_layer_changed()
        self._on_bgeo_layer_changed()
        self._on_bcatch_layer_changed()

    def _on_geo_layer_changed(self):
        self._populate_fields(self.cmbGeoLayer, self.cmbGeoField)

    def _on_catch_layer_changed(self):
        self._populate_fields(self.cmbCatchLayer, self.cmbCatchField)

    def _on_bgeo_layer_changed(self):
        self._populate_fields(self.cmbBGeoLayer, self.cmbBGeoField)

    def _on_bcatch_layer_changed(self):
        self._populate_fields(self.cmbBCatchLayer, self.cmbBCatchField)

    def _populate_fields(self, layer_combo, field_combo):
        field_combo.clear()
        layer_id = layer_combo.currentData()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return
        for field in layer.fields():
            field_combo.addItem(field.name())

    # ------------------------------------------------------------------
    # Tab switching — update Run button label
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index):
        if self.tabWidget.widget(index) is self.tabBatch:
            self.btnRun.setText('Run All')
        else:
            self.btnRun.setText('Run')

    # ------------------------------------------------------------------
    # Output path helpers
    # ------------------------------------------------------------------

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Output CSV', '', 'CSV files (*.csv);;All files (*.*)')
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            self.txtOutput.setText(path)

    def _browse_batch_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Output CSV', '', 'CSV files (*.csv);;All files (*.*)')
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            self.txtBOutput.setText(path)

    # ------------------------------------------------------------------
    # Batch queue management
    # ------------------------------------------------------------------

    def _add_batch_job(self):
        geo_layer_id  = self.cmbBGeoLayer.currentData()
        catch_layer_id = self.cmbBCatchLayer.currentData()
        geo_field     = self.cmbBGeoField.currentText().strip()
        catch_field   = self.cmbBCatchField.currentText().strip()
        output_csv    = self.txtBOutput.text().strip()

        geo_layer   = QgsProject.instance().mapLayer(geo_layer_id)   if geo_layer_id   else None
        catch_layer = QgsProject.instance().mapLayer(catch_layer_id) if catch_layer_id else None

        if not geo_layer or not catch_layer:
            QMessageBox.warning(self, 'Missing Input',
                                'Please select both a geological layer and a sub-catchment layer.')
            return
        if geo_layer_id == catch_layer_id:
            QMessageBox.warning(self, 'Same Layer',
                                'The geological layer and sub-catchment layer must be different.')
            return
        if not geo_field:
            QMessageBox.warning(self, 'Missing Field', 'Please select a geology type field.')
            return
        if not catch_field:
            QMessageBox.warning(self, 'Missing Field', 'Please select a sub-catchment ID field.')
            return
        if not output_csv:
            QMessageBox.warning(self, 'No Output Path', 'Please specify an output CSV file path.')
            return

        job = dict(
            geo_layer_id=geo_layer_id,
            geo_field=geo_field,
            catch_layer_id=catch_layer_id,
            catch_field=catch_field,
            output_csv=output_csv,
        )
        self._batch_jobs.append(job)
        self._refresh_batch_table()
        self.txtBOutput.clear()

    def _remove_batch_job(self):
        rows = sorted({idx.row() for idx in self.tblBatch.selectedIndexes()}, reverse=True)
        for row in rows:
            self.tblBatch.removeRow(row)
            del self._batch_jobs[row]

    def _refresh_batch_table(self):
        self.tblBatch.setRowCount(len(self._batch_jobs))
        for row, job in enumerate(self._batch_jobs):
            geo_layer   = QgsProject.instance().mapLayer(job['geo_layer_id'])
            catch_layer = QgsProject.instance().mapLayer(job['catch_layer_id'])
            geo_name   = geo_layer.name()   if geo_layer   else job['geo_layer_id']
            catch_name = catch_layer.name() if catch_layer else job['catch_layer_id']
            self.tblBatch.setItem(row, _COL_GEO_LAYER,   QTableWidgetItem(geo_name))
            self.tblBatch.setItem(row, _COL_GEO_FIELD,   QTableWidgetItem(job['geo_field']))
            self.tblBatch.setItem(row, _COL_CATCH_LAYER, QTableWidgetItem(catch_name))
            self.tblBatch.setItem(row, _COL_CATCH_FIELD, QTableWidgetItem(job['catch_field']))
            self.tblBatch.setItem(row, _COL_OUTPUT,      QTableWidgetItem(job['output_csv']))
        self.tblBatch.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _set_status(self, message, progress=None):
        self.lblStatus.setText(message)
        if progress is not None:
            self.progressBar.setValue(progress)
        QApplication.processEvents()

    # ------------------------------------------------------------------
    # Run dispatcher
    # ------------------------------------------------------------------

    def _on_run(self):
        if self.tabWidget.currentWidget() is self.tabBatch:
            self.run_batch()
        else:
            self.run_analysis()

    # ------------------------------------------------------------------
    # Single analysis
    # ------------------------------------------------------------------

    def run_analysis(self):
        geo_layer_id  = self.cmbGeoLayer.currentData()
        catch_layer_id = self.cmbCatchLayer.currentData()
        geo_field     = self.cmbGeoField.currentText().strip()
        catch_field   = self.cmbCatchField.currentText().strip()
        output_csv    = self.txtOutput.text().strip()

        geo_layer   = QgsProject.instance().mapLayer(geo_layer_id)   if geo_layer_id   else None
        catch_layer = QgsProject.instance().mapLayer(catch_layer_id) if catch_layer_id else None

        if not geo_layer or not catch_layer:
            QMessageBox.warning(self, 'Missing Input',
                                'Please select both a geological layer and a sub-catchment layer.')
            return
        if geo_layer_id == catch_layer_id:
            QMessageBox.warning(self, 'Same Layer',
                                'The geological layer and sub-catchment layer must be different.')
            return
        if not geo_field:
            QMessageBox.warning(self, 'Missing Field', 'Please select a geology type field.')
            return
        if not catch_field:
            QMessageBox.warning(self, 'Missing Field', 'Please select a sub-catchment ID field.')
            return
        if not output_csv:
            QMessageBox.warning(self, 'No Output Path', 'Please specify an output CSV file path.')
            return

        self.btnRun.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._run_single(geo_layer, catch_layer, geo_field, catch_field, output_csv)
        except Exception as exc:
            self._set_status(f'Error: {exc}', 0)
            QMessageBox.critical(self, 'Error', str(exc))
        finally:
            self.btnRun.setEnabled(True)
            QApplication.restoreOverrideCursor()

    def _run_single(self, geo_layer, catch_layer, geo_field, catch_field, output_csv):
        self._set_status('Step 1/3 — Running intersection and calculating areas...', 5)
        result = run_geo_proportion(geo_layer, catch_layer, geo_field, catch_field, output_csv)
        rows    = result['rows']
        n_catch = result['n_catchments']
        n_geo   = result['n_geology_types']

        self._set_status('Step 2/3 — CSV written...', 70)
        if self.chkLoadIntersection.isChecked():
            self._set_status('Step 3/3 — Loading intersection layer...', 85)
            int_layer = result['int_layer']
            self._add_area_to_layer(int_layer, result['feature_areas'])
            int_layer.setName('Geology_Intersection')
            QgsProject.instance().addMapLayer(int_layer)
        else:
            self._set_status('Step 3/3 — Skipped (intersection layer not loaded).', 85)

        warnings = result.get('area_warnings', [])
        self._set_status(
            f'Done.  {len(rows)} rows written  '
            f'({n_catch} sub-catchments × ~{n_geo} geology types).'
            + (f'  {len(warnings)} area warning(s).' if warnings else ''),
            100,
        )

        if warnings:
            QMessageBox.warning(
                self, 'Area Mismatch Detected',
                'The geology layer does not fully cover the following sub-catchments.\n'
                'Portions may not sum to 1.0 for these catchments.\n\n'
                + '\n'.join(warnings),
            )

        QMessageBox.information(
            self, 'Analysis Complete',
            f'Results written to:\n{output_csv}\n\n'
            f'Sub-catchments: {n_catch}\n'
            f'Geology types:  {n_geo}\n'
            f'CSV rows:       {len(rows)}',
        )

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def run_batch(self):
        if not self._batch_jobs:
            QMessageBox.warning(self, 'Empty Queue', 'No jobs in the batch queue.')
            return

        self.btnRun.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        total   = len(self._batch_jobs)
        passed  = 0
        failed  = []

        try:
            for i, job in enumerate(self._batch_jobs):
                geo_layer   = QgsProject.instance().mapLayer(job['geo_layer_id'])
                catch_layer = QgsProject.instance().mapLayer(job['catch_layer_id'])

                if not geo_layer or not catch_layer:
                    failed.append((i + 1, 'Layer no longer available in project.'))
                    continue

                pct_start = int(i / total * 100)
                pct_end   = int((i + 1) / total * 100)
                self._set_status(
                    f'Job {i + 1}/{total}: {geo_layer.name()} × {catch_layer.name()}...',
                    pct_start,
                )
                try:
                    result = run_geo_proportion(
                        geo_layer, catch_layer,
                        job['geo_field'], job['catch_field'],
                        job['output_csv'],
                    )
                    passed += 1
                    for w in result.get('area_warnings', []):
                        failed.append((i + 1, f'Area warning: {w}'))
                    self.progressBar.setValue(pct_end)
                    QApplication.processEvents()
                except Exception as exc:
                    failed.append((i + 1, str(exc)))

        finally:
            self.btnRun.setEnabled(True)
            QApplication.restoreOverrideCursor()

        if failed:
            details = '\n'.join(f'  Job {n}: {msg}' for n, msg in failed)
            self._set_status(f'Batch done with errors — {passed}/{total} succeeded.', 100)
            QMessageBox.warning(
                self, 'Batch Complete with Errors',
                f'{passed} of {total} jobs succeeded.\n\nFailed jobs:\n{details}',
            )
        else:
            self._set_status(f'Batch complete — all {total} jobs succeeded.', 100)
            QMessageBox.information(
                self, 'Batch Complete',
                f'All {total} jobs completed successfully.',
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_area_to_layer(layer, feature_areas):
        layer.startEditing()
        # QVariant.Double is gone in PyQt6 (QGIS 4); QMetaType is its successor
        double = QVariant.Double if hasattr(QVariant, 'Double') else QMetaType.Type.Double
        layer.addAttribute(QgsField('area_km2', double, 'double', 15, 6))
        layer.updateFields()
        area_idx = layer.fields().indexOf('area_km2')
        for feat_id, area_ha in feature_areas.items():
            layer.changeAttributeValue(feat_id, area_idx, area_ha)
        layer.commitChanges()
