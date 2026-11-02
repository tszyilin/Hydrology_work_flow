"""Zone-map tab: plots the PMP application zones + the case's centroid.

Reads polygons straight from ``pmp_toolbox/data/zones_all.json`` (via
``core.zones.ZONES``) so no new data ships with this tab. matplotlib-only,
no QGIS canvas — plays nicely with the rest of the vendored plugin.
"""
from __future__ import annotations

from ....qt_compat import (
    QLabel,
    QVBoxLayout,
    QWidget,
)


# Palette matched to the Bureau's official "PMP method zones" reference map
# (see gtsmr_hrs8.pdf p. 26): light-green GTSMR Coastal, warm-tan GTSMR
# Inland, khaki SW-WA Winter, pale-yellow GSAM Inland, teal GSAM Coastal,
# bright-yellow-green Coastal Transition, pale-cream WA Transition, teal
# West Coast Tasmania (the "unnamed" polygon in the CD's zone shapefile).
_ZONE_COLOURS = {
    "GTSMR Coastal Zone": "#cbe28a",       # light yellow-green
    "GTSMR Inland Zone": "#e8b76e",        # warm tan
    "GTSMR SW WA Winter Zone": "#b0a37d",  # khaki / dun
    "GSAM Coastal Zone": "#3ca39c",        # strong teal
    "GSAM Inland Zone": "#faf3b3",         # very pale yellow
    "GSAM-GTSMR Coastal Transition Zone": "#c8e26a",  # bright yellow-green
    "GSAM-GTSMR WA Transition Zone": "#f2d970",       # mustard — distinct
                                                      # from the pale-yellow
                                                      # GSAM Inland it borders
    # West Coast Tasmania Method Zone is a GSAM sub-region, so it reads
    # as the same teal family — but a lighter tint so it's still
    # distinguishable from the GSAM Coastal strip that runs past it.
    "(unnamed)": "#96d3cd",
}
# Fill alpha for the zone patches. High enough to read as solid colour.
_ZONE_ALPHA = 0.85

# On-map label text (falls back to the raw zone key otherwise).
_ZONE_LABELS = {
    "GTSMR Coastal Zone": "GTSMR\nCoastal Zone",
    "GTSMR Inland Zone": "GTSMR\nInland Zone",
    "GTSMR SW WA Winter Zone": "GTSMR\nSW WA\nWinter Zone",
    "GSAM Coastal Zone": "GSAM\nCoastal Zone",
    "GSAM Inland Zone": "GSAM\nInland Zone",
    "GSAM-GTSMR Coastal Transition Zone": "GSAM-GTSMR\nCoastal\nTransition Zone",
    "GSAM-GTSMR WA Transition Zone": "GSAM-GTSMR\nWA Transition\nZone",
    "(unnamed)": "West Coast\nTasmania\nMethod Zone",
}
# Positions for on-map labels. Each value is a dict with keys:
#   pos: (lon, lat) of the label text.
#   arrows: optional list of (arrow_lon, arrow_lat) targets — every entry
#           draws an arrow from the label to that point.
# Mirrors the Bureau's reference figure, which uses arrows for the four
# narrow / coastal zones and inline labels for the bigger regions.
_ZONE_LABEL_POS = {
    "GTSMR Coastal Zone": {"pos": (134.0, -15.0)},
    "GTSMR Inland Zone": {"pos": (135.0, -24.0)},
    "GSAM Inland Zone": {"pos": (140.0, -30.0)},
    "GSAM-GTSMR WA Transition Zone": {"pos": (124.0, -30.5)},
    "GTSMR SW WA Winter Zone": {
        "pos": (112.0, -31.0),
        "arrows": [(116.5, -32.5)],
    },
    "GSAM Coastal Zone": {
        # Long thin strip along Vic + eastern Tas; two arrows show both
        # ends, matching the Bureau reference.
        "pos": (149.5, -40.5),
        "arrows": [(146.5, -38.5), (148.3, -41.7)],
    },
    "GSAM-GTSMR Coastal Transition Zone": {
        "pos": (155.0, -30.5),
        "arrows": [(152.5, -32.0)],
    },
    "(unnamed)": {
        "pos": (142.5, -42.2),
        "arrows": [(145.7, -42.2)],
    },
}


class ZoneMapTab(QWidget):
    """A matplotlib map: PMP zones + centroid marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._built = False
        self._lat = None
        self._lon = None
        self._layer_name = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._layout = layout
        self._info = QLabel("Loading zone map…")
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
        except ImportError:
            self._info.setText(
                "Zone map needs matplotlib, which is not available in this QGIS."
            )
            return
        try:
            from ..pmp_toolbox.core.zones import ZONES
        except Exception as exc:  # noqa: BLE001
            self._info.setText(
                f"Could not load zone polygons: {type(exc).__name__}: {exc}"
            )
            return

        self._info.deleteLater()

        self._zones = ZONES
        self._figure = Figure(figsize=(6.5, 6.5), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._layout.addWidget(self._canvas, 1)

        self._ax = self._figure.add_subplot(111)
        self._draw_base_map()
        self._marker = None
        self._built = True
        self._redraw_marker()

    def _draw_base_map(self):
        ax = self._ax
        ax.clear()
        ax.set_facecolor("#ffffff")
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°S)")
        ax.grid(True, linestyle=":", linewidth=0.5, color="#d6dbe0")

        # Draw the transition zones (and the smaller GSAM Coastal / SW WA
        # Winter) last so their outlines sit on top of the larger base
        # zones they overlap.
        # Draw order: base zones first, then the two transition zones,
        # then West Coast Tasmania. GSAM Coastal Zone is drawn LAST so
        # its thin coastal strip stays visible on top of the West Coast
        # Tas polygon that overlaps eastern Tasmania — otherwise the
        # GSAM Coastal strip along northern/eastern Tas gets over-painted
        # in the lighter mint and reads as two different colours.
        draw_order = [
            "GTSMR Coastal Zone",
            "GTSMR Inland Zone",
            "GSAM Inland Zone",
            "GTSMR SW WA Winter Zone",
            "GSAM-GTSMR WA Transition Zone",
            "GSAM-GTSMR Coastal Transition Zone",
            "(unnamed)",
            "GSAM Coastal Zone",
        ]
        by_name = {z["zone"]: z for z in self._zones}
        for name in draw_order:
            zone = by_name.get(name)
            if zone is None:
                continue
            colour = _ZONE_COLOURS.get(name, "#7f7f7f")
            for ring in zone["rings"]:
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                ax.fill(
                    xs, ys,
                    facecolor=colour, alpha=_ZONE_ALPHA,
                    edgecolor="#3f4a52", linewidth=0.9,
                )

        # On-map zone labels. Inline for the four big zones; outside +
        # arrow for the four narrow / coastal ones. GSAM Coastal gets two
        # arrows (Vic + eastern Tas) so both ends of its long thin strip
        # are called out, matching the Bureau reference figure.
        for name, spec in _ZONE_LABEL_POS.items():
            label = _ZONE_LABELS.get(name, name)
            bbox = dict(
                boxstyle="round,pad=0.2",
                facecolor="#ffffff", alpha=0.85, edgecolor="none",
            )
            label_lon, label_lat = spec["pos"]
            arrows = spec.get("arrows") or []
            if arrows:
                # First arrow goes with the annotate() call carrying the
                # label text; extra arrows are drawn as bare annotations
                # (no text) from the same anchor point.
                first = arrows[0]
                ax.annotate(
                    label,
                    xy=first,
                    xytext=(label_lon, label_lat),
                    fontsize=7.5, ha="center", va="center",
                    color="#12222f",
                    bbox=bbox,
                    arrowprops=dict(
                        arrowstyle="->",
                        color="#3f4a52",
                        lw=0.9,
                        shrinkA=2, shrinkB=2,
                    ),
                )
                for extra in arrows[1:]:
                    ax.annotate(
                        "",
                        xy=extra,
                        xytext=(label_lon, label_lat),
                        arrowprops=dict(
                            arrowstyle="->",
                            color="#3f4a52",
                            lw=0.9,
                            shrinkA=6, shrinkB=2,
                        ),
                    )
            else:
                ax.text(
                    label_lon, label_lat, label,
                    fontsize=7.5, ha="center", va="center",
                    color="#12222f",
                    bbox=bbox,
                )

        ax.set_title("PMP application zones — Bureau of Meteorology")

        # Sensible Australia extent.
        ax.set_xlim(110, 156)
        ax.set_ylim(-45, -9)

    # ------------------------------------------------------------- public
    def set_location(self, lat, lon, layer_name: str = ""):
        """Plot / re-plot the catchment centroid marker."""
        self._lat = lat
        self._lon = lon
        self._layer_name = layer_name or ""
        if self._built:
            self._redraw_marker()

    def clear_location(self):
        self.set_location(None, None, "")

    def _redraw_marker(self):
        # Remove any prior marker + label.
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
            linestyle="None",
        )
        text = ax.annotate(
            f"{self._lat:.4f}°S, {self._lon:.4f}°E",
            xy=(self._lon, self._lat),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
            color="#5a1010",
        )
        self._marker = dot + [text]
        self._canvas.draw_idle()
