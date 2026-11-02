"""PMP application zones for a catchment centroid.

Uses the Bureau's own zone polygons from the GTSMR CD (September 2005),
`pmp_zones/zones_all.shp` — GTSMR coastal / inland / SW WA winter, GSAM coastal /
inland, and the two transition zones. This replaces an earlier boundary traced by
hand off GSDM Figure 1, which could not represent the SW WA winter zone and
approximated the GTSMR/GSAM divide with a straight chord.

Zones deliberately overlap: south-west WA is inside both the GTSMR Coastal Zone
and the GTSMR SW WA Winter Zone, because the coastal zone supplies the summer
depths and the SW WA zone the winter ones.

The rings are simplified to about 0.9 km and islands under roughly 40 km2 are
dropped, taking 308,000 points down to 11,700 (233 KB). A centroid on a small
island may therefore fall outside every zone.

Vendored from the Toolbox website project
(``backend/calculators/gtsmr_zones``), changed only in the data path so a fix
in either can be carried across.
"""
import json
import math
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "zones_all.json")

with open(_DATA, "r", encoding="utf-8") as fh:
    _MAP = json.load(fh)

ZONES = _MAP["zones"]
SOURCE = _MAP["source"]

GTSMR_COASTAL = "GTSMR Coastal Zone"
GTSMR_INLAND = "GTSMR Inland Zone"
GTSMR_SWWA = "GTSMR SW WA Winter Zone"
GSAM_COASTAL = "GSAM Coastal Zone"
GSAM_INLAND = "GSAM Inland Zone"
COASTAL_TRANSITION = "GSAM-GTSMR Coastal Transition Zone"
WA_TRANSITION = "GSAM-GTSMR WA Transition Zone"
TRANSITIONS = (COASTAL_TRANSITION, WA_TRANSITION)

LAT_RANGE = (-44.0, -9.0)
LON_RANGE = (110.0, 158.0)


def _inside(zone, lon, lat):
    """Even-odd ray casting across every ring, so holes fall out naturally."""
    x0, y0, x1, y1 = zone["bbox"]
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        return False
    hit = False
    for ring in zone["rings"]:
        for i in range(len(ring) - 1):
            xa, ya = ring[i]
            xb, yb = ring[i + 1]
            if (ya > lat) != (yb > lat):
                xint = xa + (lat - ya) * (xb - xa) / (yb - ya)
                if lon < xint:
                    hit = not hit
    return hit


def _distance_to_edge(zone, lon, lat):
    """Rough degrees to the nearest ring vertex — used only to flag marginal calls."""
    best = None
    for ring in zone["rings"]:
        for x, y in ring:
            d = (x - lon) ** 2 + (y - lat) ** 2
            if best is None or d < best:
                best = d
    return math.sqrt(best) if best is not None else None


def lookup(lat: float, lon: float) -> dict:
    """Which PMP application zones a catchment centroid falls in."""
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]):
        raise ValueError(f"Latitude {lat} is outside the zone data.")
    if not (LON_RANGE[0] <= lon <= LON_RANGE[1]):
        raise ValueError(f"Longitude {lon} is outside the zone data.")

    hits = [z["zone"] for z in ZONES if _inside(z, lon, lat)]
    notes = []

    gtsmr_summer = gtsmr_winter = None
    if GTSMR_COASTAL in hits:
        gtsmr_summer = "COAST_S"
        gtsmr_winter = "COAST_W"
    elif GTSMR_INLAND in hits:
        gtsmr_summer = "INLAND_S"

    # The SW WA winter zone overrides the coastal winter depths.
    if GTSMR_SWWA in hits:
        gtsmr_winter = "SWWA_W"

    if gtsmr_summer == "INLAND_S" and gtsmr_winter is None:
        notes.append(
            "The GTSMR inland zone has no winter equivalent — the winter zone list "
            "offers only COAST_W and SWWA_W. Left unset; choose manually if needed."
        )

    gsam_summer = gsam_autumn = None
    if GSAM_COASTAL in hits:
        gsam_summer, gsam_autumn = "GSAM_CS", "GSAM_CA"
    elif GSAM_INLAND in hits:
        gsam_summer, gsam_autumn = "GSAM_IS", "GSAM_IA"

    # Transition zones sit on the GSAM/GTSMR boundary. The guidebook is
    # explicit that both methods may apply; run both and pick the higher
    # (or whatever the guidebook recommends for that transition). If the
    # centroid is only in the transition polygon and not in a GSAM zone,
    # seed a sensible GSAM zone from which transition it is so the tab is
    # usable rather than greyed out.
    if COASTAL_TRANSITION in hits and gsam_summer is None:
        gsam_summer, gsam_autumn = "GSAM_CS", "GSAM_CA"
    if WA_TRANSITION in hits and gsam_summer is None:
        gsam_summer, gsam_autumn = "GSAM_IS", "GSAM_IA"

    for t in TRANSITIONS:
        if t in hits:
            notes.append(
                f"Also inside the {t} — both methods may apply here; check the "
                "guidebook before discarding either."
            )

    unnamed = [h for h in hits if h == "(unnamed)"]
    if unnamed:
        notes.append(
            "Also inside an unnamed zone in the Bureau's shapefile covering western "
            "Tasmania (Figure 1 labels this the West Coast Tasmania Varied Zone)."
        )

    gtsmr_applicable = gtsmr_summer is not None
    gsam_applicable = gsam_summer is not None

    if not hits:
        notes.append(
            "This centroid is not inside any PMP application zone. Small islands are "
            "dropped when the zone outlines are simplified, so check the zone map if "
            "the catchment is coastal."
        )

    named = [h for h in hits if h != "(unnamed)"]
    if named:
        label = " + ".join(named)
    else:
        label = "Outside the PMP zones"

    # Flag a centroid sitting close to a boundary.
    for z in ZONES:
        if z["zone"] in hits:
            d = _distance_to_edge(z, lon, lat)
            if d is not None and d < 0.15:
                notes.append(
                    f"About {d * 111:.0f} km from the edge of the {z['zone']} — "
                    "close enough to be worth checking on the zone map."
                )
                break

    return {
        "zone": ", ".join(named) if named else "outside",
        "zone_label": label,
        "zones": hits,
        "gtsmr_applicable": gtsmr_applicable,
        "gsam_applicable": gsam_applicable,
        "gtsmr_summer": gtsmr_summer,
        "gtsmr_winter": gtsmr_winter,
        "gsam_summer": gsam_summer,
        "gsam_autumn": gsam_autumn,
        "notes": notes,
    }
