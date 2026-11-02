"""GSDM Figure 2 (duration-limit zones) map.

Shows the scanned Bureau reference figure straight from the plugin data
folder (``pmp_toolbox/data/gsdm_duration_zones.png``) and drops a
catchment centroid marker on top.  The image is georeferenced with a
simple linear (equirectangular) fit between the visible graticule
corners, which is close enough to tell WHICH duration zone a catchment
falls into.

matplotlib-only, no QGIS canvas.
"""
from __future__ import annotations

from ....qt_compat import QLabel, QVBoxLayout, QWidget


# Approximate lat/lon extent of the reference PNG. The scanned figure is
# drawn on an Albers Equal-Area Conic sheet, so this rectangular fit is
# not exact — but the whole image sits well inside the fitted rectangle
# and centroid markers land in the correct duration zone anyway. Numbers
# below were read off the dashed graticule labels in the reference PNG.
_IMAGE_EXTENT = (109.0, 155.5, -42.0, -8.5)   # (lon_min, lon_max, lat_min, lat_max)


class GsdmMapTab(QWidget):
    """Map of GSDM Figure 2 duration-limit regions + catchment centroid marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False
        self._lat = None
        self._lon = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._layout = layout
        self._info = QLabel("Loading GSDM duration-limit figure…")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._built:
            self._build()

    def _build(self):
        try:
            from matplotlib.backends.backend_qt5agg import (
                FigureCanvasQTAgg as FigureCanvas,
            )
            from matplotlib.figure import Figure
            import matplotlib.image as mpimg
        except ImportError:
            self._info.setText(
                "GSDM map needs matplotlib, which is not available in this QGIS."
            )
            return

        try:
            image_path = self._data_dir() / "gsdm_duration_zones.png"
            image = mpimg.imread(str(image_path))
        except Exception as exc:  # noqa: BLE001
            self._info.setText(
                f"Could not load GSDM figure PNG: {type(exc).__name__}: {exc}"
            )
            return

        self._info.deleteLater()
        self._image = image

        self._figure = Figure(figsize=(6.5, 6.5), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._layout.addWidget(self._canvas, 1)

        self._ax = self._figure.add_subplot(111)
        self._draw_base_map()
        self._marker = None
        self._built = True
        self._redraw_marker()

    @staticmethod
    def _data_dir():
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / "pmp_toolbox" / "data"

    def _draw_base_map(self):
        ax = self._ax
        ax.clear()
        ax.set_facecolor("#ffffff")
        lon_min, lon_max, lat_min, lat_max = _IMAGE_EXTENT
        ax.imshow(
            self._image,
            extent=[lon_min, lon_max, lat_min, lat_max],
            aspect="auto",
            interpolation="bilinear",
            zorder=0,
        )
        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°S)")
        ax.set_title(
            "GSDM Figure 2 — duration-limit zones (Bureau of Meteorology)"
        )
        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(lat_min, lat_max)

    # ------------------------------------------------------------- public
    def set_location(self, lat, lon, layer_name: str = ""):
        self._lat = lat
        self._lon = lon
        if self._built:
            self._redraw_marker()

    def clear_location(self):
        self.set_location(None, None, "")

    def _redraw_marker(self):
        if self._marker is not None:
            for artist in self._marker:
                try:
                    artist.remove()
                except Exception:
                    pass
            self._marker = None

        if self._lat is None or self._lon is None:
            self._canvas.draw_idle()
            return

        ax = self._ax
        dot = ax.plot(
            self._lon, self._lat,
            marker="o", markersize=8,
            markerfacecolor="#d43a3a",
            markeredgecolor="#5a1010",
            linestyle="None", zorder=5,
        )
        text = ax.annotate(
            f"{self._lat:.4f}°S, {self._lon:.4f}°E",
            xy=(self._lon, self._lat),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
            color="#5a1010",
            zorder=5,
        )
        self._marker = dot + [text]
        self._canvas.draw_idle()
