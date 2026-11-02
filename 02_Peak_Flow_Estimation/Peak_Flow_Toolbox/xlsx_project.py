"""Project save/load: one .xlsx workbook per project.

Layout mirrors `21_Drain_Design/xlsx_export.py`:
    Summary sheet — one row per case with inputs + method toggles
    {case_name} sheet — per-case inputs, peak-flow table, RORB detail

Only inputs and toggle state are trusted on import; results are re-runnable.
"""

from __future__ import annotations

import errno
import re

AEPS = ["50%", "20%", "10%", "5%", "2%", "1%"]

SUMMARY_SHEET = "Summary"
NAME_HEADER = "Case Name"

INPUT_FIELDS = [
    ("Catchment Layer", "catchment_layer_name"),
    ("Catchment Feature ID", "catchment_feature_id"),
    ("Outlet Layer", "outlet_layer_name"),
    ("Outlet Feature ID", "outlet_feature_id"),
    ("Area (km²)", "area_km2"),
    ("Outlet Lon", "outlet_lon"),
    ("Outlet Lat", "outlet_lat"),
    ("Centroid Lon", "centroid_lon"),
    ("Centroid Lat", "centroid_lat"),
    ("RFFE Enabled", "rffe_enabled"),
    ("Regional Methods", "regional_methods_csv"),
    ("RORB Enabled", "rorb_enabled"),
    ("RORB Folder", "rorb_folder"),
    ("Recommended Region", "recommended_region"),
    ("Stream Length (km)", "stream_length_km"),
    ("Slope (m/km)", "slope_m_per_km"),
    ("Flavell Subregion", "subregion"),
    ("C10", "c10"),
    ("IFD I(tc,ARI) mm/hr", "ifd_itc_per_ari_csv"),
    ("IFD I(1hr,50yr) mm/hr", "ifd_i1hr_50yr"),
    ("IFD I(1hr,2yr) mm/hr", "ifd_i1hr_2yr"),
    ("IFD R12(2yr) mm", "ifd_r12_2yr"),
    ("IFD R24(10yr) mm", "ifd_r24_10yr"),
]

_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
        return openpyxl
    except ImportError as exc:
        raise ImportError(
            "This feature needs 'openpyxl'. Install with:  pip install openpyxl"
        ) from exc


def _safe_sheet_name(name, used):
    cleaned = _INVALID_SHEET_CHARS.sub("_", name).strip()[:31] or "Case"
    candidate, n = cleaned, 2
    while candidate in used:
        suffix = f" ({n})"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate


def _itc_to_csv(case):
    d = case.get("ifd_itc_per_ari") or {}
    return ",".join(f"{ari}:{d[str(ari)]}" for ari in (2, 5, 10, 20, 50, 100) if str(ari) in d)


def _itc_from_csv(text):
    out = {}
    for tok in str(text or "").split(","):
        if ":" not in tok:
            continue
        k, v = tok.split(":", 1)
        try:
            out[k.strip()] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _flatten_case_for_summary(case):
    row = [case.get("name", "")]
    for _label, key in INPUT_FIELDS:
        if key == "regional_methods_csv":
            row.append(",".join(case.get("regional_methods", []) or []))
        elif key == "ifd_itc_per_ari_csv":
            row.append(_itc_to_csv(case))
        elif key.endswith("_enabled"):
            row.append(bool(case.get(key)))
        else:
            row.append(case.get(key, ""))
    return row


def export_project(path, cases):
    openpyxl = _require_openpyxl()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    summary = wb.create_sheet(SUMMARY_SHEET, index=0)
    summary.append([NAME_HEADER] + [label for label, _ in INPUT_FIELDS])
    for case in cases:
        summary.append(_flatten_case_for_summary(case))

    used = set()
    for case in cases:
        _write_case_sheet(wb, case, used)

    _atomic_save(wb, path)


def _write_case_sheet(wb, case, used):
    sheet = wb.create_sheet(title=_safe_sheet_name(case["name"], used))
    sheet.append([f"Peak Flow - {case['name']}"])
    sheet.append([])
    sheet.append(["Input", "Value"])
    for label, key in INPUT_FIELDS:
        if key == "regional_methods_csv":
            value = ",".join(case.get("regional_methods", []) or [])
        elif key == "ifd_itc_per_ari_csv":
            value = _itc_to_csv(case)
        elif key.endswith("_enabled"):
            value = bool(case.get(key))
        else:
            value = case.get(key, "")
        sheet.append([label, value])

    sheet.append([])
    sheet.append(["Peak Flows"])
    series = _collect_series(case)
    sheet.append(["AEP"] + list(series.keys()))
    for aep in AEPS:
        row = [aep]
        for name in series:
            row.append(series[name].get(aep, ""))
        sheet.append(row)

    rorb_detail = case.get("rorb_detail") or []
    if rorb_detail:
        sheet.append([])
        sheet.append(["RORB Detail"])
        sheet.append(["AEP", "Duration (min)", "TP", "Peak (m³/s)", "File"])
        for r in rorb_detail:
            sheet.append([
                r.get("aep_label", ""),
                r.get("duration_min", ""),
                r.get("tp", ""),
                r.get("peak", ""),
                r.get("path", ""),
            ])


def _collect_series(case):
    """Build an ordered {series_name: {aep: flow}} from a case's results."""
    out = {}
    rffe = case.get("rffe_result") or {}
    if rffe:
        out["RFFE_Recommended"] = {aep: rffe.get(aep, {}).get("flow") for aep in AEPS}
        out["RFFE_lower"] = {aep: rffe.get(aep, {}).get("lower") for aep in AEPS}
        out["RFFE_upper"] = {aep: rffe.get(aep, {}).get("upper") for aep in AEPS}
    for method_id, values in (case.get("regional_results") or {}).items():
        out[f"Regional_{method_id}"] = {aep: values.get(aep) for aep in AEPS}
    rorb = case.get("rorb_result") or {}
    if rorb:
        out["RORB_mean"] = {aep: rorb.get(aep, {}).get("mean_peak") for aep in AEPS}
    return out


def _atomic_save(wb, path):
    try:
        wb.save(path)
    except PermissionError as exc:
        if exc.errno == errno.EACCES:
            raise PermissionError(
                f"Could not save '{path}': the file is open in another program "
                "(usually Excel) and locked for writing. Close it there and try again."
            ) from exc
        raise


def import_project(path):
    """Return a list of case dicts read from the Summary sheet. Results
    are not loaded — the caller re-runs the enabled methods."""
    openpyxl = _require_openpyxl()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    for sheet in wb.worksheets:
        if sheet.title == SUMMARY_SHEET:
            cases = _rows_from_summary(sheet)
            wb.close()
            return cases

    wb.close()
    return []


def _rows_from_summary(sheet):
    label_to_key = {label: key for label, key in INPUT_FIELDS}
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h) if h is not None else "" for h in rows[0]]
    if not header or header[0] != NAME_HEADER:
        return []

    cases = []
    for row in rows[1:]:
        if not row or all(cell is None or cell == "" for cell in row):
            continue
        case = {"name": str(row[0]).strip() if row[0] else ""}
        if not case["name"]:
            continue
        for col_idx, col_header in enumerate(header[1:], start=1):
            if col_idx >= len(row):
                break
            key = label_to_key.get(col_header)
            if key is None:
                continue
            raw = row[col_idx]
            if key == "regional_methods_csv":
                case["regional_methods"] = [s.strip() for s in str(raw or "").split(",") if s.strip()]
            elif key == "ifd_itc_per_ari_csv":
                case["ifd_itc_per_ari"] = _itc_from_csv(raw)
            elif key.endswith("_enabled"):
                case[key] = bool(raw) and str(raw).lower() not in ("false", "0", "")
            elif key in ("area_km2", "outlet_lon", "outlet_lat", "centroid_lon", "centroid_lat",
                         "stream_length_km", "slope_m_per_km", "c10",
                         "ifd_i1hr_50yr", "ifd_i1hr_2yr",
                         "ifd_r12_2yr", "ifd_r24_10yr"):
                try:
                    case[key] = float(raw) if raw not in (None, "") else None
                except (TypeError, ValueError):
                    case[key] = None
            else:
                case[key] = raw if raw is not None else ""
        cases.append(case)
    return cases
