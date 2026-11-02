"""Davies & Yip (2014) — WA regional flood estimation.

From `02_Regional_Method_Examples/WA_Regional_method.xlsx` sheet
`davies_yip_2014_ref`:

    Q_ARI = X1 × A^X2 × I1hr,ARI^X3 × FF

Coefficients by catchment size:
    Small  (0 - 1000 km²):     X1=7.32e-8,  X2=0.651, X3=5.251,  I1hr@ARI=2
    Medium (1000 - 10000):     X1=2.72e-7,  X2=0.797, X3=3.506,  I1hr@ARI=50
    Large  (>10000):           X1=4.26e-6,  X2=0.783, X3=2.815,  I1hr@ARI=50

Frequency factors (FF) applied to the base-ARI flow to get other ARIs.

The base call needs I1hr at the size class's reference ARI (2 or 50 yr),
supplied via `context['ifd_i1hr_2yr']` / `context['ifd_i1hr_50yr']`
(mm/hr). If missing, method returns None for all AEPs.
"""

_SIZES = [
    # (max_area_km2, X1, X2, X3, base_ari)
    (1000, 7.32e-8, 0.651, 5.251, 2),
    (10_000, 2.72e-7, 0.797, 3.506, 50),
    (float("inf"), 4.26e-6, 0.783, 2.815, 50),
]

_FF = {2: 0.31, 5: 1.00, 10: 1.70, 20: 2.58, 50: 4.15, 100: 5.82}

# AEP ↔ ARI mapping
_AEP_ARI = {"50%": 2, "20%": 5, "10%": 10, "5%": 20, "2%": 50, "1%": 100}


def compute(context):
    area = float(context.get("area_km2") or 0.0)
    if area <= 0:
        return {aep: None for aep in _AEP_ARI}

    for max_area, x1, x2, x3, base_ari in _SIZES:
        if area <= max_area:
            break

    key = "ifd_i1hr_2yr" if base_ari == 2 else "ifd_i1hr_50yr"
    i1hr = context.get(key)
    if i1hr is None or float(i1hr) <= 0:
        return {aep: None for aep in _AEP_ARI}
    i1hr = float(i1hr)

    q_ref = x1 * (area ** x2) * (i1hr ** x3)
    # `q_ref` is the "reference discharge" from the regression; the actual
    # Q at each ARI is that reference multiplied by the frequency factor
    # (verified against WA_Regional_method.xlsx Catchment A Q2 = 13.04).
    return {aep: round(q_ref * _FF[ari], 2) for aep, ari in _AEP_ARI.items()}
