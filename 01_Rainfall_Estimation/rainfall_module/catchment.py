"""Per-catchment state — the unit each tab reads from and writes to.

Mirrors the Drain Design Toolbox "cases" pattern: the sidebar owns a list of
Catchments, and every tab has a reference to the currently selected one.
When the user switches catchments, the tabs repaint from that Catchment's
stored inputs and results; when a fetch completes, the result is written
back onto the Catchment so switching away and back does not re-fetch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Catchment:
    name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    source: str = ""                       # human-readable "how the location was set"
    # IFD tab state
    ifd_result: Optional[dict] = None      # {"durations", "aep_cols", "table"}
    ifd_aeps_selected: Optional[list[str]] = None   # None = all; else subset of aep_cols
    # Stations tab state
    stations_radius_km: float = 50.0
    stations_filtered: list[dict] = field(default_factory=list)

    def has_location(self) -> bool:
        return self.lat is not None and self.lon is not None
