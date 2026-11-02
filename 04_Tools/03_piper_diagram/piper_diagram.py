"""
Piper (trilinear) diagram generator - Molyhil Project (C260813).

Reads major-ion chemistry from the 'Script Input' tab of the workbook, plots a
Piper diagram, and writes a register of everything plotted (raw mg/L, meq/L,
ionic %, plot coordinates and charge-balance QA) to CSV and XLSX.

Axis directions and labels follow the reference figure 'PiperPlot_img1.png':
- Cation triangle: Ca along the bottom (100 at bottom-LEFT vertex, reading
  right->left), Mg up the left edge, Na+K up the right edge (apex = Na+K).
- Anion triangle:  Cl along the bottom (100 at bottom-RIGHT vertex, reading
  left->right), HCO3+CO3 up the left edge, SO4 up the right edge (apex = SO4).
- Diamond:         Ca+Mg on the upper-right axes, SO4+Cl on the upper-left axes.

Add more sample columns to the 'Script Input' tab and they are picked up
automatically (colours/markers cycle).

Requires: pandas, numpy, matplotlib, openpyxl
"""

import os
from itertools import cycle

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines

# ---------------------------------------------------------------------------
# Paths - resolve to the folder this script lives in (fallback to cwd for
# interactive sessions where __file__ is undefined).
# ---------------------------------------------------------------------------
try:
    OUT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    OUT_DIR = os.getcwd()

WORKBOOK = os.path.join(OUT_DIR, "Molyhil_Piper_Diagram_Data_Script_Input.xlsx")
INPUT_SHEET = "Script Input"

H = 86.602540378  # sqrt(3)/2 * 100, height of an equilateral triangle, side 100

# Equivalent weights (g/eq). HCO3/CO3 are reported as mg CaCO3/L -> use CaCO3 eq wt.
EQ_WT = {"Ca": 20.04, "Mg": 12.153, "Na": 22.99, "K": 39.098,
         "Cl": 35.45, "SO4": 48.03}
CACO3_EQ_WT = 50.04

DEFAULT_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
DEFAULT_COLOURS = ["#c0392b", "#2980b9", "#27ae60", "#8e44ad",
                   "#e67e22", "#16a085", "#2c3e50", "#d35400"]


# ---------------------------------------------------------------------------
# 1. Read samples from the 'Script Input' tab
# ---------------------------------------------------------------------------
def read_samples(workbook=WORKBOOK, sheet=INPUT_SHEET):
    """Read the clean input tab into {sample_name: {ion: mg/L}}.

    Expected layout:  col A = Ion, col B = Unit, cols C.. = one column per sample.
    Rows: Ca, Mg, Na, K, Cl, SO4, HCO3, CO3.
    """
    df = pd.read_excel(workbook, sheet_name=sheet)
    df = df.set_index(df.columns[0])          # 'Ion' as index
    sample_cols = [c for c in df.columns if c != "Unit"]
    samples = {}
    for col in sample_cols:
        samples[str(col)] = {ion: float(df.loc[ion, col])
                             for ion in ["Ca", "Mg", "Na", "K",
                                         "Cl", "SO4", "HCO3", "CO3"]}
    return samples


# ---------------------------------------------------------------------------
# 2. Chemistry -> meq/L, percentages, plot coordinates
# ---------------------------------------------------------------------------
def to_meq(sample):
    meq = {ion: sample[ion] / EQ_WT[ion] for ion in
           ["Ca", "Mg", "Na", "K", "Cl", "SO4"]}
    meq["HCO3"] = sample["HCO3"] / CACO3_EQ_WT
    meq["CO3"] = sample["CO3"] / CACO3_EQ_WT
    return meq


def cation_pct(meq):
    tot = meq["Ca"] + meq["Mg"] + meq["Na"] + meq["K"]
    return {"Ca": 100 * meq["Ca"] / tot,
            "Mg": 100 * meq["Mg"] / tot,
            "NaK": 100 * (meq["Na"] + meq["K"]) / tot}, tot


def anion_pct(meq):
    tot = meq["Cl"] + meq["SO4"] + meq["HCO3"] + meq["CO3"]
    return {"Cl": 100 * meq["Cl"] / tot,
            "SO4": 100 * meq["SO4"] / tot,
            "HCO3": 100 * (meq["HCO3"] + meq["CO3"]) / tot}, tot


def cation_xy(cat):
    """Ca at bottom-left (0,0), Na+K at bottom-right (100,0), Mg apex (50,H)."""
    x = cat["NaK"] + 0.5 * cat["Mg"]
    y = H * cat["Mg"] / 100
    return x, y


def anion_xy(an):
    """HCO3+CO3 bottom-left (100,0), Cl bottom-right (200,0), SO4 apex (150,H)."""
    x = 100 + an["Cl"] + 0.5 * an["SO4"]
    y = H * an["SO4"] / 100
    return x, y


def diamond_xy(cat_xy, an_xy):
    xc, yc = cat_xy
    xa, ya = an_xy
    t = 0.5 * ((xa - xc) / 50 + (ya - yc) / H)
    return xc + 50 * t, yc + H * t


# ---------------------------------------------------------------------------
# 3. Compute results + charge-balance QA for every sample
# ---------------------------------------------------------------------------
def compute(samples):
    results = {}
    for name, raw in samples.items():
        meq = to_meq(raw)
        cat, cat_tot = cation_pct(meq)
        an, an_tot = anion_pct(meq)
        balance_err = 100 * (cat_tot - an_tot) / ((cat_tot + an_tot) / 2)
        cxy = cation_xy(cat)
        axy = anion_xy(an)
        dxy = diamond_xy(cxy, axy)
        results[name] = dict(raw=raw, meq=meq, cat=cat, an=an,
                             cat_tot=cat_tot, an_tot=an_tot,
                             balance_err=balance_err,
                             cxy=cxy, axy=axy, dxy=dxy)
        print(f"{name}: cations {cat_tot:6.2f} meq/L, anions {an_tot:6.2f} meq/L, "
              f"charge balance {balance_err:+5.1f}%"
              f"{'  <-- exceeds +/-5%' if abs(balance_err) > 5 else ''}")
    return results


# ---------------------------------------------------------------------------
# 4. Export a register of everything plotted (CSV + XLSX)
# ---------------------------------------------------------------------------
def export_register(results, csv_path=None, xlsx_path=None, out_dir=None):
    rows = []
    for name, r in results.items():
        rows.append({
            "Sample": name,
            "Ca (mg/L)": r["raw"]["Ca"], "Mg (mg/L)": r["raw"]["Mg"],
            "Na (mg/L)": r["raw"]["Na"], "K (mg/L)": r["raw"]["K"],
            "Cl (mg/L)": r["raw"]["Cl"], "SO4 (mg/L)": r["raw"]["SO4"],
            "HCO3 (mg CaCO3/L)": r["raw"]["HCO3"],
            "CO3 (mg CaCO3/L)": r["raw"]["CO3"],
            "Ca (meq/L)": r["meq"]["Ca"], "Mg (meq/L)": r["meq"]["Mg"],
            "Na (meq/L)": r["meq"]["Na"], "K (meq/L)": r["meq"]["K"],
            "Cl (meq/L)": r["meq"]["Cl"], "SO4 (meq/L)": r["meq"]["SO4"],
            "HCO3 (meq/L)": r["meq"]["HCO3"], "CO3 (meq/L)": r["meq"]["CO3"],
            "Ca (%cat)": r["cat"]["Ca"], "Mg (%cat)": r["cat"]["Mg"],
            "Na+K (%cat)": r["cat"]["NaK"],
            "Cl (%an)": r["an"]["Cl"], "SO4 (%an)": r["an"]["SO4"],
            "HCO3+CO3 (%an)": r["an"]["HCO3"],
            "Total cations (meq/L)": r["cat_tot"],
            "Total anions (meq/L)": r["an_tot"],
            "Charge balance error (%)": r["balance_err"],
            "Charge balance OK (+/-5%)": "Yes" if abs(r["balance_err"]) <= 5 else "No",
            "Cation X": r["cxy"][0], "Cation Y": r["cxy"][1],
            "Anion X": r["axy"][0], "Anion Y": r["axy"][1],
            "Diamond X": r["dxy"][0], "Diamond Y": r["dxy"][1],
        })
    reg = pd.DataFrame(rows).set_index("Sample").T
    reg.index.name = "Parameter"
    if out_dir is None:
        out_dir = OUT_DIR
    if csv_path is None:
        csv_path = os.path.join(out_dir, "Molyhil_Piper_Register.csv")
    if xlsx_path is None:
        xlsx_path = os.path.join(out_dir, "Molyhil_Piper_Register.xlsx")
    reg.to_csv(csv_path, index=True)
    reg.to_excel(xlsx_path, index=True, sheet_name="Piper Register")
    print(f"\nRegister saved: {csv_path}\n                {xlsx_path}")
    return reg


# ---------------------------------------------------------------------------
# 5. Draw the Piper diagram
# ---------------------------------------------------------------------------
GRID_COLOR = "#d5d5d5"
EDGE_COLOR = "#333333"
LABEL_COLOR = "#222222"
TICK_COLOR = "#777777"


def tri_vertices(x0):
    return np.array([[x0, 0], [x0 + 100, 0], [x0 + 50, H]])


GRID_BLUE = "#2e86de"    # bottom axis
GRID_GREEN = "#27ae60"   # left axis
GRID_RED = "#e74c3c"     # right axis


def gridlines_triangle(x0):
    if x0 == 0:
        c_horizontal, c_rising_right, c_rising_left = GRID_GREEN, GRID_RED, GRID_BLUE
    else:
        c_horizontal, c_rising_right, c_rising_left = GRID_RED, GRID_BLUE, GRID_GREEN

    segs = []
    for k in (20, 40, 60, 80):
        f = k / 100
        segs.append((((x0 + 50 * f, H * f), (x0 + 100 - 50 * f, H * f)), c_horizontal))
        segs.append((((x0 + 100 * f, 0), (x0 + 100 * f + 50 * (1 - f), H * (1 - f))), c_rising_right))
        segs.append((((x0 + 100 * (1 - f), 0), (x0 + 50 * (1 - f), H * (1 - f))), c_rising_left))
    return segs


def label_edge(ax, p_start, p_end, ticks, title, title_offset,
               rotation, tick_offset, tick_color=TICK_COLOR,
               title_fontsize=8.5, tick_fontsize=7):
    p_start = np.array(p_start, float)
    p_end = np.array(p_end, float)
    for i, val in enumerate(ticks):
        f = i / (len(ticks) - 1)
        pos = p_start + f * (p_end - p_start) + np.array(tick_offset)
        ax.text(pos[0], pos[1], str(val), fontsize=tick_fontsize, color=tick_color,
                ha="center", va="center", rotation=rotation)
    mid = 0.5 * (p_start + p_end) + np.array(title_offset)
    ax.text(mid[0], mid[1], title, fontsize=title_fontsize, color=LABEL_COLOR,
            ha="center", va="center", rotation=rotation, fontweight="bold")


DEFAULT_TITLE = ("Piper Diagram - Molyhil Project (C260813)\n"
                 "Major Ion Composition, 23 June 2026")


FACIES_TINT_CAT = "#f0ead6"      # cation triangle corner sub-triangles
FACIES_TINT_AN = "#f3dfdf"       # anion triangle corner sub-triangles
FACIES_TINT_DIA = "#dfdff0"      # diamond corner sub-diamonds
FACIES_ALPHA = 0.55


FACIES_LABEL_COLOR = "#5a5a5a"    # soft grey for facies-zone labels


def diamond_vertices(g):
    """Equilateral rhombus whose LEFT vertex sits on the cation apex (50, H)
    and RIGHT vertex sits on the anion apex (150+g, H). Preserves 60deg angles
    so the interior gridlines/projection formula still work."""
    L = (50.0, H)
    R = (150.0 + g, H)
    Cx = 100.0 + g / 2.0
    h = (50.0 + g / 2.0) * (H / 50.0)   # h/w = tan60deg = H/50
    T = (Cx, H + h)
    B = (Cx, H - h)
    return L, T, R, B


def _facies_polys(g, an_x0, dy=0.0):
    """Return (fills, labels) where fills is a list of (vertices, tint) polygons
    to draw as background patches, and labels is a list of (text, (x, y))
    positions for the water-type names. `dy` shifts the diamond zones up."""
    fills = []
    labels = []

    # ---- Cation triangle corner sub-triangles (Ca / Na+K / Mg) ----
    Ca, NaK, Mg = (0, 0), (100, 0), (50, H)
    M_bot = (50, 0)
    M_left = (25, H / 2)
    M_right = (75, H / 2)
    fills.append((np.array([Ca, M_bot, M_left]), FACIES_TINT_CAT))
    fills.append((np.array([NaK, M_bot, M_right]), FACIES_TINT_CAT))
    fills.append((np.array([Mg, M_left, M_right]), FACIES_TINT_CAT))
    labels.append(("Calcium\nType", (25, H / 6)))
    labels.append(("Sodium & Potassium\nType", (75, H / 6)))
    labels.append(("Magnesium\nType", (50, 2 * H / 3)))

    # ---- Anion triangle corner sub-triangles (HCO3 / Cl / SO4) ----
    HCO, Cl, SO4 = (an_x0, 0), (an_x0 + 100, 0), (an_x0 + 50, H)
    aM_bot = (an_x0 + 50, 0)
    aM_left = (an_x0 + 25, H / 2)
    aM_right = (an_x0 + 75, H / 2)
    fills.append((np.array([HCO, aM_bot, aM_left]), FACIES_TINT_AN))
    fills.append((np.array([Cl, aM_bot, aM_right]), FACIES_TINT_AN))
    fills.append((np.array([SO4, aM_left, aM_right]), FACIES_TINT_AN))
    labels.append(("Bicarbonate\nType", (an_x0 + 25, H / 6)))
    labels.append(("Chloride\nType", (an_x0 + 75, H / 6)))
    labels.append(("Sulphate\nType", (an_x0 + 50, 2 * H / 3)))

    # ---- Diamond (translated by dx=g/2 in x and dy in y): triangles at
    # top/bottom, sub-rhombi at left/right, unshaded bowtie in the middle.
    dx = g / 2.0
    L = (50 + dx, H + dy)
    R = (150 + dx, H + dy)
    T = (100 + dx, 2 * H + dy)
    B = (100 + dx, 0 + dy)
    C = (100 + dx, H + dy)
    tl = (75 + dx, 1.5 * H + dy)
    tr = (125 + dx, 1.5 * H + dy)
    br = (125 + dx, 0.5 * H + dy)
    bl = (75 + dx, 0.5 * H + dy)
    fills.append((np.array([T, tl, tr]), FACIES_TINT_DIA))
    fills.append((np.array([B, bl, br]), FACIES_TINT_DIA))
    fills.append((np.array([L, tl, C, bl]), FACIES_TINT_DIA))
    fills.append((np.array([R, tr, C, br]), FACIES_TINT_DIA))
    labels.append(("Calcium chloride\nType", (117.2, 162.1)))
    labels.append(("Sodium bicarbonate\nType", (114.9, 55.1)))
    labels.append(("Magnesium\nbicarbonate Type", (72 + dx, H + dy)))
    labels.append(("Sodium chloride\nType", (128 + dx, H + dy)))

    return fills, labels


DIAMOND_DY = 23.0   # y-shift of the diamond (and its projected sample points)


def render_axes(ax, results, styles=None, axis_label_rotation_offset=0,
                rotation_mode="along", gap=30, show_facies=True,
                diamond_dy=DIAMOND_DY, title=DEFAULT_TITLE):
    """rotation_mode: "along" keeps each label parallel to its axis edge (the
    conventional Piper look); "horizontal" forces every axis title to 0deg.
    axis_label_rotation_offset is added on top for fine tweaking.
    gap: horizontal separation (plot units) between the cation and anion
    triangles. The diamond translates by gap/2 to sit centred above the pair.
    styles: {sample_name: {"marker": str, "color": str, "size": float}}
    """
    ax.clear()
    ax.set_aspect("equal")
    ax.axis("off")

    g = float(gap)
    an_x0 = 100 + g          # anion triangle left-bottom x
    dx = g / 2               # diamond translation
    dy = float(diamond_dy)   # diamond y-shift (moves diamond and its samples up)

    cat_v = tri_vertices(0)
    an_v = tri_vertices(an_x0)
    ax.add_patch(plt.Polygon(cat_v, closed=True, fill=False, edgecolor=EDGE_COLOR, lw=1.3))
    ax.add_patch(plt.Polygon(an_v, closed=True, fill=False, edgecolor=EDGE_COLOR, lw=1.3))
    diamond_v = np.array([[100 + dx, 0 + dy], [50 + dx, H + dy],
                          [100 + dx, 2 * H + dy], [150 + dx, H + dy]])
    ax.add_patch(plt.Polygon(diamond_v, closed=True, fill=False, edgecolor=EDGE_COLOR, lw=1.3))

    if show_facies:
        fills, labels = _facies_polys(g, an_x0, dy)
        for verts, tint in fills:
            ax.add_patch(plt.Polygon(verts, closed=True, facecolor=tint,
                                     edgecolor="none", alpha=FACIES_ALPHA, zorder=-1))
        for text, (lx, ly) in labels:
            ax.text(lx, ly, text, fontsize=6.2, color=FACIES_LABEL_COLOR,
                    ha="center", va="center", style="italic", zorder=1)

    for x0 in (0, an_x0):
        for (p1, p2), col in gridlines_triangle(x0):
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=col, lw=0.7,
                    alpha=0.55, zorder=0)
    for k in (20, 40, 60, 80):
        f = k / 100
        ax.plot([100 + dx - 50 * f, 150 + dx - 50 * f],
                [H * f + dy, H * f + H + dy],
                color=GRID_GREEN, lw=0.7, alpha=0.55, zorder=0)
        ax.plot([100 + dx + 50 * f, 50 + dx + 50 * f],
                [H * f + dy, H * f + H + dy],
                color=GRID_RED, lw=0.7, alpha=0.55, zorder=0)

    ticks_up = [0, 20, 40, 60, 80, 100]
    ticks_dn = [100, 80, 60, 40, 20, 0]

    horiz = rotation_mode != "along"

    def rot(base):
        return (base if not horiz else 0) + axis_label_rotation_offset

    # Perpendicular-outward unit normals for the slanted edges. Along-axis mode
    # puts titles OUTSIDE the shape along these normals; horizontal mode uses
    # a plain sideways offset (falls back to bigger clearance).
    #   (cos30, sin30) = (0.866, 0.5)
    NX, NY = 0.8660254, 0.5
    slant_d = 13
    diamond_d = 11
    horiz_slant = 18   # bigger sideways offset when labels are horizontal
    horiz_diamond = 16

    def tri_off(direction, d=slant_d):
        # direction: "left" (cation Mg / anion HCO3) or "right" (cation NaK / anion SO4)
        if horiz:
            return (-horiz_slant if direction == "left" else horiz_slant, 0)
        return (-NX * d, NY * d) if direction == "left" else (NX * d, NY * d)

    def diamond_off_vec(direction):
        if horiz:
            return (-horiz_diamond if direction == "left" else horiz_diamond, 3)
        return (-NX * diamond_d, NY * diamond_d) if direction == "left" else (NX * diamond_d, NY * diamond_d)

    # Cation triangle
    label_edge(ax, (0, 0), (100, 0), ticks_dn, "Calcium (Ca)",
               title_offset=(0, -11), rotation=rot(0), tick_offset=(0, -3.5),
               tick_color=GRID_BLUE)
    label_edge(ax, (0, 0), (50, H), ticks_up, "Magnesium (Mg)",
               title_offset=tri_off("left"), rotation=rot(60), tick_offset=(-3.5, 0),
               tick_color=GRID_GREEN)
    # Na+K: fixed centre at (80.4, 53.9). label_edge places at midpoint+offset.
    nak_mid = (75.0, H / 2.0)
    nak_off = (80.4 - nak_mid[0], 53.9 - nak_mid[1])
    label_edge(ax, (100, 0), (50, H), ticks_dn, "Sodium (Na) + Potassium (K)",
               title_offset=nak_off, rotation=rot(-60), tick_offset=(3.5, 0),
               tick_color=GRID_RED)

    # Anion triangle (shifted right by gap)
    label_edge(ax, (an_x0, 0), (an_x0 + 100, 0), ticks_up, "Chloride (Cl)",
               title_offset=(0, -11), rotation=rot(0), tick_offset=(0, -3.5),
               tick_color=GRID_BLUE)
    # HCO3+CO3: fixed centre at (146.2, 53.1). Offset computed from midpoint,
    # which depends on the current gap (adjust the target if you change gap).
    hco_mid = (an_x0 + 25.0, H / 2.0)
    hco_off = (146.2 - hco_mid[0], 53.1 - hco_mid[1])
    label_edge(ax, (an_x0, 0), (an_x0 + 50, H), ticks_dn,
               r"Carbonate (CO$_3^{2-}$) + Bicarbonate (HCO$_3^-$)",
               title_offset=hco_off, rotation=rot(60), tick_offset=(-3.5, 0),
               tick_color=GRID_GREEN)
    label_edge(ax, (an_x0 + 100, 0), (an_x0 + 50, H), ticks_up, "Sulfate (SO4)",
               title_offset=tri_off("right"), rotation=rot(-60), tick_offset=(3.5, 0),
               tick_color=GRID_RED)

    # Diamond upper edges. Ca+Mg tilt matches Sulfate (-60), SO4+Cl matches Mg (+60).
    label_edge(ax, (150 + dx, H + dy), (100 + dx, 2 * H + dy), ticks_up,
               "Calcium (Ca) + Magnesium (Mg)",
               title_offset=diamond_off_vec("right"), rotation=rot(-60),
               tick_offset=(3.2, 1.6), tick_color=GRID_GREEN)
    label_edge(ax, (50 + dx, H + dy), (100 + dx, 2 * H + dy), ticks_up,
               "Sulfate (SO4) + Chloride (Cl)",
               title_offset=diamond_off_vec("left"), rotation=rot(60),
               tick_offset=(-3.2, 1.6), tick_color=GRID_RED)

    # Styles - use provided or cycle through defaults.
    if styles is None:
        m_cycle = cycle(DEFAULT_MARKERS)
        c_cycle = cycle(DEFAULT_COLOURS)
        styles = {name: dict(marker=next(m_cycle), color=next(c_cycle), size=110)
                  for name in results}

    for name, r in results.items():
        s = styles.get(name, {"marker": "o", "color": "#333", "size": 110, "filled": True})
        filled = s.get("filled", True)
        cxy = r["cxy"]
        axy = (r["axy"][0] + g, r["axy"][1])          # shift anion pts by gap
        dxy = (r["dxy"][0] + dx, r["dxy"][1] + dy)    # shift diamond pts by gap/2 and dy
        for xy in (cxy, axy, dxy):
            if filled:
                ax.scatter(*xy, s=s.get("size", 110), marker=s["marker"],
                           color=s["color"], edgecolor="black", linewidth=0.6, zorder=5)
            else:
                ax.scatter(*xy, s=s.get("size", 110), marker=s["marker"],
                           facecolors="none", edgecolors=s["color"], linewidth=1.4,
                           zorder=5)

    handles = []
    for n in results:
        s = styles[n]
        ms = max(4, (s.get("size", 110) / 110) * 9)
        if s.get("filled", True):
            handles.append(mlines.Line2D([], [], marker=s["marker"], color=s["color"],
                                         linestyle="None", markersize=ms,
                                         markeredgecolor="black", markeredgewidth=0.6,
                                         label=n))
        else:
            handles.append(mlines.Line2D([], [], marker=s["marker"],
                                         markerfacecolor="none",
                                         markeredgecolor=s["color"], markeredgewidth=1.4,
                                         linestyle="None", markersize=ms, label=n))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.72, 1.0),
              frameon=False, fontsize=10, title="Sample", title_fontsize=11)

    ax.set_xlim(-30, 235 + g)
    ax.set_ylim(-25, 2 * H + dy + 25)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)


def draw(results, out_path, styles=None, axis_label_rotation_offset=0,
         rotation_mode="along", gap=30, show_facies=True,
         diamond_dy=DIAMOND_DY, title=DEFAULT_TITLE):
    fig, ax = plt.subplots(figsize=(11, 9.5))
    render_axes(ax, results, styles=styles,
                axis_label_rotation_offset=axis_label_rotation_offset,
                rotation_mode=rotation_mode, gap=gap,
                show_facies=show_facies, diamond_dy=diamond_dy, title=title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Plot saved:     {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = read_samples()
    results = compute(samples)
    export_register(results)
    draw(results, os.path.join(OUT_DIR, "Molyhil_Piper_Diagram.png"))
