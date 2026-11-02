"""Per-catchment state — the unit each tab reads from and writes to.

Mirrors the Drain Design Toolbox "cases" pattern: the sidebar owns a list of
Catchments, and every tab has a reference to the currently selected one.
When the user switches catchments, the tabs repaint from that Catchment's
stored inputs and results; when a fetch completes, the result is written
back onto the Catchment so switching away and back does not re-fetch.

A single Catchment now backs both the Rainfall and Peak Flow tabs, so all
peak-flow method inputs live here too (area, coordinates, per-method
parameters). ``selected_methods`` is the set of method IDs the user ticked
on the top-level Inputs tab.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Method IDs — single source of truth for the Inputs tab picker ────────
RAINFALL_METHODS = ("ifd", "station", "pmp")
PEAK_FLOW_METHODS = ("rffe", "arr1987", "flavell", "davies_yip", "northfield", "rorb")
REGIONAL_METHODS = ("arr1987", "flavell", "davies_yip", "northfield")
ALL_METHODS = RAINFALL_METHODS + PEAK_FLOW_METHODS

METHOD_LABELS = {
    "ifd": "IFD",
    "station": "Rainfall Station",
    "pmp": "PMP",
    "rffe": "RFFE",
    "arr1987": "ARR 1987 Rational",
    "flavell": "Flavell WA",
    "davies_yip": "Davies & Yip",
    "northfield": "Northfield NT",
    "rorb": "RORB",
}


@dataclass
class Catchment:
    name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = ""                       # human-readable "how the location was set"

    # ── Which methods this catchment runs (Inputs tab picker) ───────────
    selected_methods: set = field(default_factory=set)

    # ── Shared peak-flow inputs (common across most methods) ────────────
    area_km2: Optional[float] = None
    outlet_lon: Optional[float] = None
    outlet_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    centroid_lat: Optional[float] = None
    catchment_layer_id: str = ""
    catchment_feature_id: int = 0
    outlet_layer_id: str = ""
    outlet_feature_id: int = 0

    # ── Per-method peak-flow parameters ─────────────────────────────────
    c10: Optional[float] = None                     # ARR 1987
    ifd_itc_per_ari: dict = field(default_factory=dict)   # ARR 1987 — {ARI: mm/hr}
    subregion: str = ""                             # Flavell
    stream_length_km: Optional[float] = None        # Flavell
    slope_m_per_km: Optional[float] = None          # Flavell
    ifd_r12_2yr: Optional[float] = None             # Flavell (Wheatbelt)
    ifd_r24_10yr: Optional[float] = None            # Flavell (Kimberley)
    ifd_i1hr_2yr: Optional[float] = None            # Davies & Yip
    ifd_i1hr_50yr: Optional[float] = None           # Davies & Yip
    rorb_folder: str = ""                           # RORB

    # ── IFD tab state (rainfall) ────────────────────────────────────────
    ifd_result: Optional[dict] = None      # {"durations", "aep_cols", "table"}
    ifd_aeps_selected: Optional[list] = None   # None = all; else subset of aep_cols

    # ── Stations tab state (rainfall) ───────────────────────────────────
    stations_radius_km: float = 50.0
    stations_filtered: list = field(default_factory=list)

    def has_location(self) -> bool:
        return self.lat is not None and self.lon is not None
