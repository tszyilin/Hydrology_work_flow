"""Qt dialog for the Water Level tool."""
from __future__ import annotations

import os
import tempfile
import time

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout,
)
from qgis.core import (
    QgsCoordinateTransform, QgsFillSymbol, QgsGeometry, QgsMapLayerProxyModel,
    QgsProject, QgsVectorLayer,
)
from qgis.gui import QgsColorButton, QgsExtentWidget, QgsMapLayerComboBox

from .flood_core import compute_flood_polygon


def _clean_source_path(src):
    """QGIS raster sources sometimes include provider options after '|'."""
    if not src:
        return src
    return src.split('|', 1)[0]


class FloodDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent or (iface.mainWindow() if iface else None))
        self.iface = iface
        self.setWindowTitle('Water Level')
        self.setMinimumWidth(560)
        self._build_ui()
        self._on_layer_changed(self.in_combo.currentLayer())

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel('DEM raster layer:'))
        self.in_combo = QgsMapLayerComboBox()
        self.in_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.in_combo.layerChanged.connect(self._on_layer_changed)
        layout.addWidget(self.in_combo)

        wl_row = QHBoxLayout()
        wl_row.addWidget(QLabel('Water level:'))
        self.level_spin = QDoubleSpinBox()
        self.level_spin.setDecimals(3)
        self.level_spin.setRange(-10000.0, 10000.0)
        self.level_spin.setValue(0.0)
        self.level_spin.setSingleStep(0.1)
        wl_row.addWidget(self.level_spin, 1)
        wl_hint = QLabel('(same units as the DEM, usually metres)')
        wl_hint.setStyleSheet('color:#555;')
        wl_row.addWidget(wl_hint)
        layout.addLayout(wl_row)

        self.full_extent_cb = QCheckBox('Use full DEM extent')
        self.full_extent_cb.setChecked(True)
        self.full_extent_cb.toggled.connect(self._on_full_extent_toggled)
        layout.addWidget(self.full_extent_cb)

        layout.addWidget(QLabel('Flood extent (rectangular):'))
        self.extent_widget = QgsExtentWidget()
        if self.iface is not None:
            self.extent_widget.setMapCanvas(self.iface.mapCanvas())
        layout.addWidget(self.extent_widget)

        clip_label = QLabel(
            'Clip to polygon layer (optional) — keeps only the flooded area '
            'inside the chosen polygons.'
        )
        clip_label.setWordWrap(True)
        clip_label.setStyleSheet('color:#555;')
        layout.addWidget(clip_label)
        self.clip_combo = QgsMapLayerComboBox()
        self.clip_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.clip_combo.setAllowEmptyLayer(True, '(none — rectangular extent only)')
        self.clip_combo.setCurrentIndex(0)
        layout.addWidget(self.clip_combo)

        self.temp_cb = QCheckBox('Save as temporary (scratch) layer')
        self.temp_cb.toggled.connect(self._on_temp_toggled)
        layout.addWidget(self.temp_cb)

        self.out_label = QLabel('Output shapefile:')
        layout.addWidget(self.out_label)
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.browse_out_btn = QPushButton('Browse...')
        self.browse_out_btn.clicked.connect(self._pick_output)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(self.browse_out_btn)
        layout.addLayout(out_row)

        # Style controls
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel('Fill colour:'))
        self.color_btn = QgsColorButton()
        self.color_btn.setColor(QColor(51, 136, 204))  # #3388cc
        self.color_btn.setAllowOpacity(False)  # opacity handled by the slider
        style_row.addWidget(self.color_btn)
        style_row.addSpacing(16)
        style_row.addWidget(QLabel('Opacity:'))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_label = QLabel('50%')
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_label.setText(f'{v}%'))
        style_row.addWidget(self.opacity_slider, 1)
        style_row.addWidget(self.opacity_label)
        layout.addLayout(style_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton('Run flood')
        self.run_btn.clicked.connect(self._run)
        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        btn_row.addStretch()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._on_full_extent_toggled(self.full_extent_cb.isChecked())
        self._on_temp_toggled(self.temp_cb.isChecked())

    # ── Signal handlers ─────────────────────────────────────────────
    def _on_layer_changed(self, layer):
        if layer is None:
            return
        src = _clean_source_path(layer.source())
        if src and not self.out_edit.text():
            base, _ = os.path.splitext(src)
            self.out_edit.setText(base + '_flood.shp')
        crs = layer.crs()
        if crs.isValid():
            self.extent_widget.setOutputCrs(crs)
            self.extent_widget.setOriginalExtent(layer.extent(), crs)
            self.extent_widget.setCurrentExtent(layer.extent(), crs)

    def _on_full_extent_toggled(self, checked):
        self.extent_widget.setEnabled(not checked)

    def _on_temp_toggled(self, checked):
        self.out_label.setEnabled(not checked)
        self.out_edit.setEnabled(not checked)
        self.browse_out_btn.setEnabled(not checked)

    def _pick_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save flood polygon', self.out_edit.text() or '',
            'ESRI Shapefile (*.shp)'
        )
        if path:
            if not path.lower().endswith('.shp'):
                path += '.shp'
            self.out_edit.setText(path)

    # ── Run ─────────────────────────────────────────────────────────
    def _run(self):
        layer = self.in_combo.currentLayer()
        if layer is None:
            QMessageBox.warning(self, 'Missing input',
                                'Please load a DEM raster into the project and select it.')
            return
        in_path = _clean_source_path(layer.source())
        if not in_path or not os.path.isfile(in_path):
            QMessageBox.warning(self, 'Invalid input',
                                f'Selected layer source is not a readable file:\n{in_path}')
            return

        water_level = float(self.level_spin.value())

        extent = None
        if not self.full_extent_cb.isChecked():
            rect = self.extent_widget.outputExtent()
            if rect is None or rect.isEmpty():
                QMessageBox.warning(
                    self, 'No extent',
                    'Pick an extent on the map (or tick "Use full DEM extent").')
                return
            extent = (rect.xMinimum(), rect.yMinimum(),
                      rect.xMaximum(), rect.yMaximum())

        temp_mode = self.temp_cb.isChecked()
        if temp_mode:
            stem = os.path.splitext(os.path.basename(in_path))[0] or 'flood'
            # Keep timestamp in the on-disk filename so re-runs don't clash
            # with still-open shapefile locks, but the QGIS layer name
            # itself is just "<dem>_<water level>" (set below).
            out_path = os.path.join(
                tempfile.gettempdir(),
                f'{stem}_{water_level:g}_{int(time.time())}.shp',
            )
        else:
            out_path = self.out_edit.text().strip()
            if not out_path:
                QMessageBox.warning(self, 'Missing output',
                                    'Choose an output shapefile path or '
                                    'tick "Save as temporary (scratch) layer".')
                return
            if not out_path.lower().endswith('.shp'):
                out_path += '.shp'

        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        try:
            def cb(frac, _msg=''):
                self.progress.setValue(int(100 * frac))

            layer_crs = layer.crs()
            if not (layer_crs.isValid() and layer_crs.authid()):
                proj_crs = QgsProject.instance().crs()
                if proj_crs.isValid():
                    QMessageBox.warning(
                        self, 'DEM has no CRS',
                        'The selected DEM has no CRS assigned. Falling back '
                        f'to the project CRS: {proj_crs.authid()}.\n\n'
                        'Set the raster layer CRS explicitly if the flood '
                        'polygon ends up in the wrong place.')
                    layer_crs = proj_crs
            srs_wkt = layer_crs.toWkt() if layer_crs.isValid() else None
            crs_authid = layer_crs.authid() if layer_crs.isValid() else None

            out_shp, feat_count = compute_flood_polygon(
                in_path, out_path, water_level,
                extent=extent,
                progress_cb=cb,
                srs_wkt=srs_wkt,
                crs_authid=crs_authid,
            )
            self.progress.setValue(100)

            if feat_count == 0:
                QMessageBox.information(
                    self, 'No flooded cells',
                    f'No DEM cells are at or below {water_level}. '
                    'Nothing to add to the project.')
                return

            clip_layer = self.clip_combo.currentLayer()
            if clip_layer is not None:
                feat_count = self._clip_output_to_layer(
                    out_shp, clip_layer, layer_crs,
                )
                if feat_count == 0:
                    QMessageBox.information(
                        self, 'Nothing left after clip',
                        'The flooded area does not overlap the clip polygon. '
                        'Nothing to add to the project.')
                    return

            if temp_mode:
                dem_stem = os.path.splitext(os.path.basename(in_path))[0] or 'flood'
                name = f'{dem_stem}_{water_level:g}'
                added = self._add_as_memory_layer(out_shp, name, layer_crs)
            else:
                name = os.path.splitext(os.path.basename(out_shp))[0]
                added = QgsVectorLayer(out_shp, name, 'ogr')
                if added.isValid():
                    self._apply_style(added)
                    QgsProject.instance().addMapLayer(added)
                else:
                    QMessageBox.warning(
                        self, 'Load failed',
                        'Shapefile was written but could not be loaded as a layer.')
                    return

            # Zoom the map canvas to the new flood layer so the user can see
            # where it landed — crucial if the DEM has no CRS and the flood
            # ends up at the raw raster coordinates.
            if added is not None and self.iface is not None:
                canvas = self.iface.mapCanvas()
                canvas.setExtent(added.extent())
                canvas.refresh()

            msg = ('Flood polygon added as a temporary scratch layer.'
                   if temp_mode else f'Flood polygon written to:\n{out_shp}')
            QMessageBox.information(self, 'Done', msg)
        except Exception as e:
            QMessageBox.critical(self, 'Error',
                                 f'Failed to compute flood:\n{e}')
        finally:
            self.run_btn.setEnabled(True)
            self.progress.setValue(0)

    # ── Helpers ─────────────────────────────────────────────────────
    def _clip_output_to_layer(self, out_shp, clip_layer, dem_crs):
        """Intersect the single flood feature in ``out_shp`` with the
        dissolved geometry of ``clip_layer`` (reprojected to the DEM CRS).

        Returns the number of non-empty features left in ``out_shp``.
        """
        clip_geom = QgsGeometry()
        for f in clip_layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            clip_geom = g if clip_geom.isEmpty() else clip_geom.combine(g)
        if clip_geom.isEmpty():
            return 0

        if clip_layer.crs().isValid() and dem_crs.isValid() \
                and clip_layer.crs() != dem_crs:
            xform = QgsCoordinateTransform(
                clip_layer.crs(), dem_crs, QgsProject.instance(),
            )
            clip_geom.transform(xform)

        flood_lyr = QgsVectorLayer(out_shp, '_flood_edit', 'ogr')
        if not flood_lyr.isValid():
            return 0
        flood_lyr.startEditing()
        remaining = 0
        for feat in flood_lyr.getFeatures():
            intersected = feat.geometry().intersection(clip_geom)
            if intersected is None or intersected.isEmpty():
                flood_lyr.deleteFeature(feat.id())
            else:
                flood_lyr.changeGeometry(feat.id(), intersected)
                remaining += 1
        flood_lyr.commitChanges()
        flood_lyr = None  # release the shapefile handle before we re-open it
        return remaining

    def _apply_style(self, layer):
        c = self.color_btn.color()
        rgba = f'{c.red()},{c.green()},{c.blue()},255'
        sym = QgsFillSymbol.createSimple({
            'color': rgba,
            'outline_color': '0,0,0,255',
            'outline_width': '0.2',
        })
        layer.renderer().setSymbol(sym)
        layer.setOpacity(self.opacity_slider.value() / 100.0)
        layer.triggerRepaint()

    def _add_as_memory_layer(self, shp_path, name, layer_crs):
        """Copy a written shapefile into an in-memory scratch layer and clean up."""
        src = QgsVectorLayer(shp_path, name, 'ogr')
        if not src.isValid():
            QMessageBox.warning(self, 'Load failed',
                                'Flood polygon was written to a temp file but could not be read.')
            return None

        crs_part = layer_crs.authid() if layer_crs.isValid() and layer_crs.authid() else ''
        uri = f'MultiPolygon?crs={crs_part}' if crs_part else 'MultiPolygon'
        mem = QgsVectorLayer(uri, name, 'memory')
        mem_dp = mem.dataProvider()
        mem_dp.addAttributes(src.fields().toList())
        mem.updateFields()
        mem_dp.addFeatures(list(src.getFeatures()))
        mem.updateExtents()
        self._apply_style(mem)
        QgsProject.instance().addMapLayer(mem)

        src = None
        for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            p = shp_path[:-4] + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return mem
