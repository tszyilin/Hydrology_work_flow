import math
import os
import traceback

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)
import processing


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "wind_fetch_dialog_base.ui")
)


class WindFetchDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.cmbPointLayer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.cmbLineLayer.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.cmbPolyLayer.setFilters(QgsMapLayerProxyModel.PolygonLayer)

        self.radPoint.toggled.connect(self._update_mode)
        self.radLine.toggled.connect(self._update_mode)
        self._update_mode()

        self.btnRun.clicked.connect(self.on_run)

    def _update_mode(self):
        line_mode = self.radLine.isChecked()
        self.cmbPointLayer.setEnabled(not line_mode)
        self.lblPoint.setEnabled(not line_mode)
        self.cmbLineLayer.setEnabled(line_mode)
        self.lblLine.setEnabled(line_mode)
        self.spnSpacing.setEnabled(line_mode)
        self.lblSpacing.setEnabled(line_mode)

    def log(self, text):
        self.txtSummary.appendPlainText(text)

    def on_run(self):
        self.txtSummary.clear()
        try:
            self._run_pipeline()
        except Exception as exc:
            self.log(f"Error: {exc}")
            self.log(traceback.format_exc())

    def _collect_source_points(self):
        """Return (list of QgsPointXY, source CRS) in the coordinate system to use for fetch calc."""
        if self.radLine.isChecked():
            layer = self.cmbLineLayer.currentLayer()
            if layer is None or layer.featureCount() < 1:
                self.log("Select a line layer with at least one feature.")
                return None, None
            spacing = float(self.spnSpacing.value())
            sampled = processing.run(
                "native:pointsalonglines",
                {"INPUT": layer, "DISTANCE": spacing, "OUTPUT": "memory:"},
            )["OUTPUT"]
            pts = []
            for f in sampled.getFeatures():
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                pts.append(g.asPoint() if not g.isMultipart() else g.asMultiPoint()[0])
            if not pts:
                self.log("Line sampling produced no points — check spacing vs. line length.")
                return None, None
            return pts, layer.crs()

        layer = self.cmbPointLayer.currentLayer()
        if layer is None or layer.featureCount() < 1:
            self.log("Select a point layer with at least one feature.")
            return None, None
        pts = []
        for f in layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            pts.append(g.asPoint() if not g.isMultipart() else g.asMultiPoint()[0])
        return pts, layer.crs()

    def _run_pipeline(self):
        water_layer = self.cmbPolyLayer.currentLayer()
        radius = float(self.spnRadius.value())
        interval = float(self.spnInterval.value())
        out_name = self.txtOutput.text().strip() or "Wind_Fetch"

        if water_layer is None:
            self.log("Select a water body polygon layer.")
            return

        source_points, source_crs = self._collect_source_points()
        if not source_points:
            return

        water_source = water_layer
        if water_layer.crs() != source_crs:
            self.log(f"Reprojecting water layer to {source_crs.authid()}.")
            water_source = processing.run(
                "native:reprojectlayer",
                {"INPUT": water_layer, "TARGET_CRS": source_crs, "OUTPUT": "memory:"},
            )["OUTPUT"]

        n = max(1, int(round(360.0 / interval)))
        self.log(
            f"Embankment sample points: {len(source_points)}. "
            f"Fetch rays per point: {n} (interval {interval}°, radius {radius} m)."
        )

        lines_layer = QgsVectorLayer(
            f"LineString?crs={source_crs.authid()}", "fetch_lines_tmp", "memory"
        )
        prov = lines_layer.dataProvider()
        prov.addAttributes(
            [
                QgsField("point_id", QVariant.Int),
                QgsField("origin_x", QVariant.Double),
                QgsField("origin_y", QVariant.Double),
                QgsField("bearing", QVariant.Double),
            ]
        )
        lines_layer.updateFields()

        feats = []
        for pid, pt in enumerate(source_points):
            px, py = pt.x(), pt.y()
            for i in range(n):
                bearing = i * 360.0 / n
                theta = math.radians(bearing)
                x = px + radius * math.sin(theta)
                y = py + radius * math.cos(theta)
                f = QgsFeature(lines_layer.fields())
                f.setGeometry(
                    QgsGeometry.fromPolylineXY([QgsPointXY(px, py), QgsPointXY(x, y)])
                )
                f.setAttributes([pid, px, py, bearing])
                feats.append(f)
        prov.addFeatures(feats)
        lines_layer.updateExtents()

        clipped = processing.run(
            "native:clip",
            {"INPUT": lines_layer, "OVERLAY": water_source, "OUTPUT": "memory:"},
        )["OUTPUT"]

        clipped.setName(out_name)
        clipped.dataProvider().addAttributes([QgsField("fetch_m", QVariant.Double)])
        clipped.updateFields()
        fetch_idx = clipped.fields().indexOf("fetch_m")

        clipped.startEditing()
        rays_by_point = {}
        max_fetch = 0.0
        max_bearing = None
        max_pid = None
        max_x = None
        max_y = None
        for f in clipped.getFeatures():
            g = f.geometry()
            length = 0.0 if g is None or g.isEmpty() else g.length()
            clipped.changeAttributeValue(f.id(), fetch_idx, float(length))
            pid = f.attribute("point_id")
            bearing = f.attribute("bearing")
            ox = f.attribute("origin_x")
            oy = f.attribute("origin_y")
            rays_by_point.setdefault(pid, {"origin": (ox, oy), "rays": []})
            rays_by_point[pid]["rays"].append((bearing, length))
            if length > max_fetch:
                max_fetch = length
                max_bearing = bearing
                max_pid = pid
                max_x = ox
                max_y = oy
        clipped.commitChanges()

        QgsProject.instance().addMapLayer(clipped)

        if max_bearing is None or max_fetch <= 0.0:
            self.log("No fetch: no rays intersect the water body.")
        else:
            self.log(
                f"Longest single ray: {max_fetch:,.1f} m at bearing {max_bearing:.1f}° "
                f"(point #{max_pid} @ {max_x:,.1f}, {max_y:,.1f})."
            )

        if self.grpEff.isChecked():
            half_angle = float(self.spnHalfAngle.value())
            if self.chkSweep.isChecked():
                candidate_dirs = [i * 360.0 / n for i in range(n)]
            else:
                candidate_dirs = [float(self.spnWindDir.value())]

            best = self._sweep_effective_fetch(rays_by_point, candidate_dirs, half_angle)
            if best is None:
                self.log("Effective fetch: no rays available.")
            else:
                f_eff, wind_dir, pid, ox, oy = best
                self.log(
                    f"Effective fetch (Saville, ±{half_angle:.1f}°): "
                    f"F_eff = {f_eff:,.1f} m at wind direction {wind_dir:.1f}° "
                    f"(point #{pid} @ {ox:,.1f}, {oy:,.1f})."
                )

        self.log(f"Loaded layer '{out_name}' with {clipped.featureCount()} lines.")

    @staticmethod
    def _sweep_effective_fetch(rays_by_point, candidate_dirs, half_angle):
        """Saville effective fetch: F_eff = sum(F_i cos^2 a_i) / sum(cos a_i),
        where a_i is angle from wind direction, |a_i| <= half_angle.
        Returns (F_eff, wind_dir, point_id, ox, oy) for the maximum across
        (points x candidate directions), or None."""
        best = None
        for pid, data in rays_by_point.items():
            ox, oy = data["origin"]
            rays = data["rays"]
            for wind_dir in candidate_dirs:
                num = 0.0
                den = 0.0
                for bearing, length in rays:
                    delta = ((bearing - wind_dir + 180.0) % 360.0) - 180.0
                    if abs(delta) > half_angle:
                        continue
                    ca = math.cos(math.radians(delta))
                    if ca <= 0:
                        continue
                    num += length * ca * ca
                    den += ca
                if den <= 0:
                    continue
                f_eff = num / den
                if best is None or f_eff > best[0]:
                    best = (f_eff, wind_dir, pid, ox, oy)
        return best
