"""Build a composite (gap-filled) daily series from two stations.

Priority: use station A where present; fill from station B (scaled by a
user-supplied correction factor) where A is missing. Days missing from both
remain NaN. Mirrors the "Group1" composite in ../01_Example/03.Infilled/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .io_bom import Station


@dataclass
class InfillResult:
    composite: Station
    days_from_a: int
    days_from_b: int
    days_still_missing: int


def infill(a: Station, b: Station, correction_b_to_a: float, label: str = "Composite") -> InfillResult:
    """Merge two stations. `correction_b_to_a` scales B before filling into A."""
    idx = pd.date_range(
        min(a.rain.index.min(), b.rain.index.min()),
        max(a.rain.index.max(), b.rain.index.max()),
        freq="D",
    )
    ra = a.rain.reindex(idx)
    rb = b.rain.reindex(idx) * correction_b_to_a

    combined = ra.copy()
    mask_fill = ra.isna() & rb.notna()
    combined[mask_fill] = rb[mask_fill]

    composite = Station(code=label, label=label, rain=combined)
    return InfillResult(
        composite=composite,
        days_from_a=int(ra.notna().sum()),
        days_from_b=int(mask_fill.sum()),
        days_still_missing=int(combined.isna().sum()),
    )
