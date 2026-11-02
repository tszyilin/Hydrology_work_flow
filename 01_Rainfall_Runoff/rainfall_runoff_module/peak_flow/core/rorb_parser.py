"""Parse a folder of RORB .out files and aggregate mean peak-per-AEP
across the 10 temporal patterns at the critical duration.

parse_out() is a copy of the function in
`14_RORB/04_Testing_Data_Set/compare_results.py` — vendored here so this
plugin has no cross-repo runtime dependency on that testing script.

File-name convention (matches the RORB batch runner in 14_RORB):
    {catchment}_aep{N}_du{duration}min_tp{NN}.out
For example: `Tennant_creek_all_aep1_du20mintp21.out`.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

# 1%, 2%, 5%, 10%, 20%, 50% — same set RFFE reports, mapped from `aep1`, `aep2` etc.
AEP_LABEL_FROM_TOKEN = {
    "1": "1%", "2": "2%", "5": "5%", "10": "10%", "20": "20%", "50": "50%",
}

_FILE_RE = re.compile(
    r"_aep(?P<aep>\d+)_du(?P<dur>\d+)\s*min\s*tp(?P<tp>\d+)\.out$",
    re.IGNORECASE,
)


def parse_out(path: Path) -> dict:
    """Extract peak discharge from the outlet hydrograph section of a
    RORB .out file. Returns {'peak', 'ttp', 'vol'}. Raises ValueError on
    parse failure."""
    try:
        text = path.read_text(encoding="cp1252", errors="replace")
    except OSError as e:
        raise ValueError(f"Cannot read: {e}")

    outlet_matches = [
        m.start() for m in
        re.finditer(r"\*\*\*\s+Calculated hydrograph,\s+outlet", text, re.IGNORECASE)
    ]
    if outlet_matches:
        idx = outlet_matches[-1]
    else:
        idx = text.rfind("*** Calculated hydrograph,")
        if idx == -1:
            raise ValueError("No hydrograph section found")

    section = text[idx: idx + 600]

    peak = ttp = vol = None
    for line in section.split("\n"):
        s = line.strip()
        if re.match(r"Peak discharge", s, re.IGNORECASE):
            m = re.search(r"[\d.Ee+\-]+$", s)
            if m:
                peak = float(m.group())
        elif re.match(r"Time to peak", s, re.IGNORECASE):
            m = re.search(r"[\d.Ee+\-]+$", s)
            if m:
                ttp = float(m.group())
        elif re.match(r"Volume", s, re.IGNORECASE):
            m = re.search(r"[\d.Ee+\-]+$", s)
            if m:
                vol = float(m.group())

    if peak is None:
        raise ValueError("Peak discharge not found in outlet section")
    return {"peak": peak, "ttp": ttp, "vol": vol}


def scan_folder(folder: Path) -> list[dict]:
    """Walk a folder for `*_aepN_duXmin_tpNN.out` files and parse each.
    Returns a list of {aep, aep_label, duration_min, tp, peak, path}.
    Files not matching the pattern are skipped silently."""
    folder = Path(folder)
    rows = []
    for f in folder.rglob("*.out"):
        m = _FILE_RE.search(f.name)
        if not m:
            continue
        aep_token = m.group("aep")
        try:
            info = parse_out(f)
        except ValueError:
            continue
        rows.append({
            "aep": aep_token,
            "aep_label": AEP_LABEL_FROM_TOKEN.get(aep_token, f"{aep_token}%"),
            "duration_min": int(m.group("dur")),
            "tp": int(m.group("tp")),
            "peak": info["peak"],
            "path": str(f),
        })
    return rows


def aggregate_mean_per_aep(rows: list[dict]) -> dict:
    """Group parsed rows by (aep, duration), average peak across TPs, then
    for each AEP pick the critical duration (highest mean) and return
    {aep_label: {'mean_peak', 'critical_duration_min', 'n_tp', 'per_tp'}}.

    Uses mean-of-TPs — not max-of-TPs — as the design flow, per the user's
    requirement to report the average across the 10 temporal patterns.
    """
    grouped: dict[tuple, list[dict]] = {}
    for r in rows:
        grouped.setdefault((r["aep_label"], r["duration_min"]), []).append(r)

    by_aep: dict[str, list[tuple]] = {}
    for (aep_label, dur), items in grouped.items():
        peaks = [it["peak"] for it in items]
        mean_peak = statistics.mean(peaks) if peaks else 0.0
        by_aep.setdefault(aep_label, []).append((dur, mean_peak, peaks))

    out = {}
    for aep_label, entries in by_aep.items():
        dur, mean_peak, peaks = max(entries, key=lambda e: e[1])
        out[aep_label] = {
            "mean_peak": mean_peak,
            "critical_duration_min": dur,
            "n_tp": len(peaks),
            "per_tp": peaks,
        }
    return out
