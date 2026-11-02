"""ARR 1987 Probabilistic Rational Method.

Q_Y = 0.278 × C_Y × I_tc,Y × A   (A in km², I in mm/hr → Q in m³/s)
    C_Y = C_10 × FF_Y            (with FF_10 = 1)

Frequency factors FF_Y for Arid Interior (WA) — from
`WA_Regional_method.xlsx` sheet `ARR_1987`:
    Q2→0.34, Q5→0.70, Q10→1.00, Q20→1.28, Q50→1.62, Q100→1.91

Requires user inputs:
    C10                       — runoff coefficient for 10-yr event
    ifd_itc_per_ari (dict)    — {'2': I, '5': I, '10': I, '20': I, '50': I, '100': I}
                                 rainfall intensities at time of concentration (mm/hr)

Returns None per AEP if any required input is missing for that ARI.
"""

_FF = {"50%": 0.34, "20%": 0.70, "10%": 1.00, "5%": 1.28, "2%": 1.62, "1%": 1.91}
_AEP_ARI = {"50%": 2, "20%": 5, "10%": 10, "5%": 20, "2%": 50, "1%": 100}


def compute(context):
    area = float(context.get("area_km2") or 0.0)
    c10 = context.get("c10")
    itc = context.get("ifd_itc_per_ari") or {}
    if area <= 0 or c10 is None or float(c10) <= 0 or not itc:
        return {aep: None for aep in _AEP_ARI}
    c10 = float(c10)

    out = {}
    for aep, ari in _AEP_ARI.items():
        i = itc.get(str(ari))
        if i is None or float(i) <= 0:
            out[aep] = None
            continue
        c_y = c10 * _FF[aep]
        out[aep] = round(0.278 * c_y * float(i) * area, 2)
    return out
