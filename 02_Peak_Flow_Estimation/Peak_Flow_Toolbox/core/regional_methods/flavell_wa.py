"""Flavell (2012) — WA regional flood estimation.

Four sub-region formulas (coefficients from
`WA_Regional_method.xlsx` sheet `flavell_2012_ref`):

    Pilbara            Q = X1 × (A·Se^0.5)^X2 × LAT^X3 × LONG^X4 × (L²/A)^X5
    Goldfields Leinster Q = X1 × (A·Se^X2)^X3 × (L²/A)^X4
    Wheatbelt          Q = X1 × A^X2 × R12^X3 × (L²/A)^X4
    Kimberley          Q = X1 × (A·Se^X2)^X3 × R24^X4

Sub-region selected via `context['subregion']`. Coefficients here are
the *slope-included* rows (`Slope*` = 'Y') per the spreadsheet, which is
the standard usage; the alternative no-slope rows require different
inputs and are omitted from this first cut.
"""

_AEP_ARI = {"50%": 2, "20%": 5, "10%": 10, "5%": 20, "2%": 50, "1%": 100}

# Slope-included rows from flavell_2012_ref
_GOLDFIELDS = {  # (X1, X2, X3, X4)
    2:   (0.16, 0.5, 0.82, -0.35),
    5:   (0.48, 0.5, 0.84, -0.33),
    10:  (0.89, 0.5, 0.84, -0.34),
    20:  (1.45, 0.5, 0.85, -0.33),
    50:  (2.44, 0.5, 0.82, -0.36),
    100: (3.28, 0.5, 0.83, -0.35),
}

_PILBARA = {  # (X1, X2, X3, X4, X5)
    2:   (1.72e-64, 0.80, -12.17, 38.77, -1.05),
    5:   (7.47e-46, 0.81, -14.62, 31.40, -0.68),
    10:  (2.36e-34, 0.81, -15.24, 26.28, -0.39),
    20:  (1.98e-23, 0.79, -15.08, 20.91,  0.00),
    # Pilbara reference gives no 50/100-yr coefficient rows; scale from 20-yr
    # using a nominal growth factor (the spreadsheet warns against extrapolation).
    50:  None,
    100: None,
}

_WHEATBELT = {  # (X1, X2, X3, X4)
    2:  (0.00453,   0.67, 1.20,  0.00),
    5:  (0.00439,   0.64, 1.32,  0.00),
    10: (0.00199,   0.67, 1.70, -0.48),
    20: (0.000238,  0.65, 2.28, -0.56),
    50: None, 100: None,
}

_KIMBERLEY = {  # (X1, X2, X3, X4) — slope Y rows
    2:   (16.10, 0.5, 0.507, 0.000),
    5:   (16.20, 0.5, 0.572, 0.000),
    10:  ( 0.82, 0.5, 0.616, 0.575),
    20:  ( 0.52, 0.5, 0.639, 0.658),
    50:  ( 0.26, 0.5, 0.670, 0.775),
    100: ( 0.15, 0.5, 0.694, 0.870),
}


def _q_goldfields(ari, area, se, l2a):
    c = _GOLDFIELDS.get(ari)
    if c is None:
        return None
    x1, x2, x3, x4 = c
    return x1 * ((area * (se ** x2)) ** x3) * (l2a ** x4)


def _q_pilbara(ari, area, se, l2a, lat, lon):
    c = _PILBARA.get(ari)
    if c is None:
        return None
    x1, x2, x3, x4, x5 = c
    ase05 = area * (se ** 0.5)
    return x1 * (ase05 ** x2) * (abs(lat) ** x3) * (lon ** x4) * (l2a ** x5)


def _q_wheatbelt(ari, area, l2a, r12):
    c = _WHEATBELT.get(ari)
    if c is None:
        return None
    x1, x2, x3, x4 = c
    return x1 * (area ** x2) * (r12 ** x3) * (l2a ** x4)


def _q_kimberley(ari, area, se, r24):
    c = _KIMBERLEY.get(ari)
    if c is None:
        return None
    x1, x2, x3, x4 = c
    return x1 * ((area * (se ** x2)) ** x3) * (r24 ** x4)


def compute(context):
    area = float(context.get("area_km2") or 0.0)
    stream_length = float(context.get("stream_length_km") or 0.0)
    se = float(context.get("slope_m_per_km") or 0.0)
    subregion = (context.get("subregion") or "").strip().lower()
    lat = context.get("lat"); lon = context.get("lon")
    r12 = context.get("ifd_r12_2yr")  # for Wheatbelt (2yr, 12hr)
    r24 = context.get("ifd_r24_10yr")  # for Kimberley (10yr, 24hr)

    if area <= 0 or stream_length <= 0:
        return {aep: None for aep in _AEP_ARI}
    l2a = (stream_length ** 2) / area

    out = {}
    for aep, ari in _AEP_ARI.items():
        try:
            if subregion == "goldfields leinster" and se > 0:
                q = _q_goldfields(ari, area, se, l2a)
            elif subregion == "pilbara" and se > 0 and lat is not None and lon is not None:
                q = _q_pilbara(ari, area, se, l2a, lat, lon)
            elif subregion == "wheatbelt" and r12 is not None:
                q = _q_wheatbelt(ari, area, l2a, float(r12))
            elif subregion == "kimberley" and se > 0 and r24 is not None:
                q = _q_kimberley(ari, area, se, float(r24))
            else:
                q = None
        except (ValueError, ZeroDivisionError, TypeError):
            q = None
        out[aep] = round(q, 2) if q is not None else None
    return out
