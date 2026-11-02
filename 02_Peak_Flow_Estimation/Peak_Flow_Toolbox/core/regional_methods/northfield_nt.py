"""Northfield, Craig & Hill (2021) arid RFFE — the "NT method".

From `02_Regional_Method_Examples/NT_Regional_method.xlsx` Instructions
sheet:
    MAF (m³/s) = 2.998 × Area^0.559     [R² = 0.40]   (Eq. 3)
    Q_AEP     = Normalised Discharge × MAF

Normalised discharge factors (Table 3):
    20% AEP → 1.65    10% AEP → 2.74
     5% AEP → 3.92     2% AEP → 5.56
     1% AEP → 6.83

Applicability: arid / semi-arid ungauged catchments (MAR ≤ 350 mm,
Area ≤ 1000 km², outside the Generalised Tropical Zone). No 50% AEP
factor is given by the reference; that AEP is returned as None.
"""

_NORMALISED = {
    "50%": None,
    "20%": 1.65,
    "10%": 2.74,
    "5%": 3.92,
    "2%": 5.56,
    "1%": 6.83,
}


def compute(context):
    area = float(context.get("area_km2") or 0.0)
    if area <= 0 or area > 1000:
        return {k: None for k in _NORMALISED}
    maf = 2.998 * (area ** 0.559)
    return {aep: round(nd * maf, 2) if nd is not None else None
            for aep, nd in _NORMALISED.items()}
