import os
import tempfile
import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QFileDialog, QMessageBox, QProgressBar
)
from qgis.core import QgsVectorLayer, QgsProject, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox

from .footprint_core import extract_footprint


def _clean_source_path(src):
    """QGIS raster sources sometimes include provider options after '|'."""
    if not src:
        return src
    return src.split('|', 1)[0]


class RasterFootprintDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle('Raster Footprint to Shapefile')
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Input raster — pick from loaded project raster layers
        layout.addWidget(QLabel('Input raster layer:'))
        row = QHBoxLayout()
        self.in_combo = QgsMapLayerComboBox()
        self.in_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.in_combo.layerChanged.connect(self._on_layer_changed)
        row.addWidget(self.in_combo)
        layout.addLayout(row)

        # Temporary (scratch) layer option
        self.temp_cb = QCheckBox('Save as temporary (scratch) layer')
        self.temp_cb.toggled.connect(self._on_temp_toggled)
        layout.addWidget(self.temp_cb)

        # Output shapefile
        self.out_label = QLabel('Output shapefile:')
        layout.addWidget(self.out_label)
        row2 = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.browse_out_btn = QPushButton('Browse...')
        self.browse_out_btn.clicked.connect(self._pick_output)
        row2.addWidget(self.out_edit)
        row2.addWidget(self.browse_out_btn)
        layout.addLayout(row2)

        # Options
        self.dissolve_cb = QCheckBox('Dissolve into a single feature')
        self.dissolve_cb.setChecked(True)
        layout.addWidget(self.dissolve_cb)

        self.add_layer_cb = QCheckBox('Add result to project')
        self.add_layer_cb.setChecked(True)
        layout.addWidget(self.add_layer_cb)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton('Extract Footprint')
        self.run_btn.clicked.connect(self._run)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btn_row.addStretch()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_layer_changed(self, layer):
        if layer is None:
            return
        src = _clean_source_path(layer.source())
        if src and not self.out_edit.text():
            base, _ = os.path.splitext(src)
            self.out_edit.setText(base + '_footprint.shp')

    def _on_temp_toggled(self, checked):
        self.out_label.setEnabled(not checked)
        self.out_edit.setEnabled(not checked)
        self.browse_out_btn.setEnabled(not checked)

    def _pick_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save shapefile', self.out_edit.text() or '',
            'ESRI Shapefile (*.shp)'
        )
        if path:
            if not path.lower().endswith('.shp'):
                path += '.shp'
            self.out_edit.setText(path)

    def _run(self):
        layer = self.in_combo.currentLayer()
        if layer is None:
            QMessageBox.warning(self, 'Missing input',
                                'Please load a raster into the project and select it.')
            return
        in_path = _clean_source_path(layer.source())
        if not in_path or not os.path.isfile(in_path):
            QMessageBox.warning(self, 'Invalid input',
                                f'Selected layer source is not a readable file:\n{in_path}')
            return

        temp_mode = self.temp_cb.isChecked()
        if temp_mode:
            stem = os.path.splitext(os.path.basename(in_path))[0] or 'footprint'
            out_path = os.path.join(
                tempfile.gettempdir(),
                f'{stem}_footprint_{int(time.time())}.shp',
            )
        else:
            out_path = self.out_edit.text().strip()
            if not out_path:
                QMessageBox.warning(self, 'Missing output',
                                    'Please choose an output shapefile path '
                                    'or tick "Save as temporary (scratch) layer".')
                return

        self.run_btn.setEnabled(False)
        self.progress.setValue(5)
        try:
            def cb(frac, _msg=''):
                self.progress.setValue(int(5 + frac * 90))
                return 1  # continue

            layer_crs = layer.crs()
            srs_wkt = layer_crs.toWkt() if layer_crs.isValid() else None
            crs_authid = layer_crs.authid() if layer_crs.isValid() else None
            extract_footprint(
                in_path, out_path,
                dissolve=self.dissolve_cb.isChecked(),
                progress_cb=cb,
                srs_wkt=srs_wkt,
                crs_authid=crs_authid,
            )
            self.progress.setValue(100)

            if self.add_layer_cb.isChecked() or temp_mode:
                name = os.path.splitext(os.path.basename(out_path))[0]
                if temp_mode:
                    self._add_as_memory_layer(out_path, name, layer_crs)
                else:
                    lyr = QgsVectorLayer(out_path, name, 'ogr')
                    if lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr)
                    else:
                        QMessageBox.warning(
                            self, 'Load failed',
                            'Shapefile was written but could not be loaded as a layer.')

            if temp_mode:
                QMessageBox.information(self, 'Done',
                                        'Footprint added as a temporary scratch layer.')
            else:
                QMessageBox.information(self, 'Done',
                                        f'Footprint written to:\n{out_path}')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to extract footprint:\n{e}')
        finally:
            self.run_btn.setEnabled(True)
            self.progress.setValue(0)

    def _add_as_memory_layer(self, shp_path, name, layer_crs):
        """Copy a written shapefile into an in-memory scratch layer and clean up."""
        src = QgsVectorLayer(shp_path, name, 'ogr')
        if not src.isValid():
            QMessageBox.warning(self, 'Load failed',
                                'Footprint was written to a temp file but could not be read.')
            return

        geom_type = 'MultiPolygon'
        crs_part = layer_crs.authid() if layer_crs.isValid() and layer_crs.authid() else ''
        uri = f'{geom_type}?crs={crs_part}' if crs_part else geom_type
        mem = QgsVectorLayer(uri, name, 'memory')
        mem_dp = mem.dataProvider()
        mem_dp.addAttributes(src.fields().toList())
        mem.updateFields()
        mem_dp.addFeatures(list(src.getFeatures()))
        mem.updateExtents()
        QgsProject.instance().addMapLayer(mem)

        # Drop the on-disk sidecar now that it's materialised in memory
        src = None
        for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            p = shp_path[:-4] + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
