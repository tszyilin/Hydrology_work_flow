"""Default colour-by-family palette + linestyle/marker options for the
comparison plot. Every series belongs to one of three families (RFFE /
Regional / RORB); within a family individual series get progressively
lighter shades so a "same approach → same colour" glance still works."""

_FAMILY_BASE = {
    "RFFE": "#1f77b4",      # blue
    "Regional": "#2ca02c",  # green
    "RORB": "#d62728",      # red
}

LINESTYLES = ["-", "--", "-.", ":"]
MARKERS = ["o", "s", "^", "D", "v", "x", "+", "*", "none"]
COLOR_CHOICES = [
    "#1f77b4", "#2ca02c", "#d62728", "#ff7f0e", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#111111",
]


def family_of(series_id: str) -> str:
    if series_id.startswith("RFFE"):
        return "RFFE"
    if series_id.startswith("Regional"):
        return "Regional"
    if series_id.startswith("RORB"):
        return "RORB"
    return "Other"


def default_style(series_id: str, family_index: int) -> dict:
    """Return {color, linestyle, marker} for a given series.
    RFFE upper/lower bounds are always dashed in the family colour."""
    fam = family_of(series_id)
    base = _FAMILY_BASE.get(fam, "#333333")
    if series_id in ("RFFE_lower", "RFFE_upper"):
        return {"color": base, "linestyle": "--", "marker": "none"}
    # Vary linestyle across series within the same family, keep colour stable
    ls = LINESTYLES[family_index % len(LINESTYLES)] if family_index > 0 else "-"
    mk = MARKERS[family_index % len(MARKERS)]
    return {"color": base, "linestyle": ls, "marker": mk}
