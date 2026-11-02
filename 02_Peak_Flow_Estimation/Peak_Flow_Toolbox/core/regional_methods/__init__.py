"""Registry of Australian regional flood methods.

Each entry:
    id: (label, callable, applicable_regions_or_None)

Callables take a context dict and return {aep_label: peak_flow_m3s or None}
for the six AEPs `50%, 20%, 10%, 5%, 2%, 1%`. Callables that need
extra inputs (stream length, slope, IFD intensities, subregion) must be
tolerant of missing values — return None for AEPs they can't compute.
"""

from . import arr1987_rational, davies_yip_wa, flavell_wa, northfield_nt

AEPS = ["50%", "20%", "10%", "5%", "2%", "1%"]

REGISTRY = {
    "arr1987": (
        "ARR1987 (Probabilistic Rational)",
        arr1987_rational.compute,
        None,  # nationwide
    ),
    "flavell": (
        "Flavell 2012 (WA)",
        flavell_wa.compute,
        {"WA"},
    ),
    "davies_yip": (
        "Davies & Yip 2014 (WA)",
        davies_yip_wa.compute,
        {"WA"},
    ),
    "northfield": (
        "Northfield 2021 (Arid / NT)",
        northfield_nt.compute,
        {"NT", "SA"},
    ),
}

FLAVELL_SUBREGIONS = ["", "Pilbara", "Goldfields Leinster", "Wheatbelt", "Kimberley"]


def applicable(region_code):
    out = []
    for mid, (_label, _fn, regions) in REGISTRY.items():
        if regions is None or (region_code and region_code in regions):
            out.append(mid)
    return out


def label(method_id):
    return REGISTRY[method_id][0]


def run(method_id, context):
    return REGISTRY[method_id][1](context)
