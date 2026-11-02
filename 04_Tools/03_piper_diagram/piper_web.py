"""
Streamlit web-app front end for the Piper diagram generator.

Run locally:
    pip install streamlit openpyxl pandas matplotlib numpy
    streamlit run piper_web.py

It will open a browser tab at http://localhost:8501 automatically.

Reuses the pure-python plotting core in `piper_diagram.py` (same maths and
styling used by the desktop Tk GUI in `piper_gui.py`).
"""

import io
import json
from tempfile import NamedTemporaryFile

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import piper_diagram as pd_mod


st.set_page_config(page_title="Piper Diagram Generator", layout="wide")
st.title("Piper Diagram Generator")

# ---------------------------------------------------------------------------
# 1. Input: file upload OR path to a bundled example
# ---------------------------------------------------------------------------
left, right = st.columns([1, 2], gap="large")

with left:
    st.header("Input")
    uploaded = st.file_uploader(
        "Input workbook (.xlsx)",
        type=["xlsx", "xlsm"],
        help="Must contain a 'Script Input' sheet with rows Ca, Mg, Na, K, Cl, "
             "SO4, HCO3, CO3 and one column per sample.",
    )

    # A convenient way to persist samples across reruns without re-uploading.
    if "raw_bytes" not in st.session_state:
        st.session_state.raw_bytes = None
    if uploaded is not None:
        st.session_state.raw_bytes = uploaded.getvalue()

    if st.session_state.raw_bytes is None:
        st.info("Upload a Script Input workbook to begin.")
        st.stop()

    # Persist the upload to a temp file so read_samples() (which uses pandas
    # read_excel with a path) can access it.
    with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(st.session_state.raw_bytes)
        wb_path = tmp.name

    try:
        samples = pd_mod.read_samples(workbook=wb_path)
    except Exception as e:
        st.error(f"Could not read the workbook: {e}")
        st.stop()

    results = pd_mod.compute(samples)
    st.success(f"Loaded {len(samples)} sample(s).")

# ---------------------------------------------------------------------------
# 2. Sample styling table (name / marker / colour / size / filled / order)
# ---------------------------------------------------------------------------
with left:
    st.header("Samples")

    # Build a default table, or reuse the session-persisted one if the sample
    # set hasn't changed.
    def _fresh_table():
        return pd.DataFrame([
            {
                "orig": name,
                "name": name,
                "marker": pd_mod.DEFAULT_MARKERS[i % len(pd_mod.DEFAULT_MARKERS)],
                "colour": pd_mod.DEFAULT_COLOURS[i % len(pd_mod.DEFAULT_COLOURS)],
                "size": 110.0,
                "filled": True,
            }
            for i, name in enumerate(samples)
        ])

    if ("sample_table" not in st.session_state
            or set(st.session_state.sample_table["orig"]) != set(samples)):
        st.session_state.sample_table = _fresh_table()

    edited = st.data_editor(
        st.session_state.sample_table,
        num_rows="fixed",
        use_container_width=True,
        hide_index=False,
        column_config={
            "orig": st.column_config.TextColumn("orig (locked)", disabled=True),
            "name": st.column_config.TextColumn("Display name"),
            "marker": st.column_config.SelectboxColumn(
                "Marker",
                options=["o", "s", "^", "D", "v", "P", "X", "*", "<", ">", "h", "p"],
                required=True,
            ),
            "colour": st.column_config.TextColumn(
                "Colour",
                help="Hex like #c0392b, or a matplotlib named colour.",
            ),
            "size": st.column_config.NumberColumn("Size", min_value=10, max_value=600, step=10),
            "filled": st.column_config.CheckboxColumn("Filled"),
        },
        key="sample_editor",
    )
    # Persist edits so a rerun doesn't lose them.
    st.session_state.sample_table = edited

    st.caption("Tip: click the row-number to drag samples up/down; the plot's "
               "legend and z-order follow the table order.")

# ---------------------------------------------------------------------------
# 3. Plot options
# ---------------------------------------------------------------------------
with left:
    st.header("Plot options")
    title = st.text_area(
        "Plot title", value=pd_mod.DEFAULT_TITLE, height=70,
        help="Real line breaks are honoured.",
    )
    gap = st.slider("Triangle gap (units)", 0, 80, 30, step=1)
    rot_mode = st.selectbox("Axis label rotation", ["along", "horizontal"], index=0)
    rot_off = st.slider("Fine rotation offset (deg)", -45, 45, 0, step=1)
    show_facies = st.checkbox("Show facies zones (background tint)", value=True)

# ---------------------------------------------------------------------------
# 4. Build styles + renamed results in the user's chosen order
# ---------------------------------------------------------------------------
styles = {}
renamed_results = {}
for _, row in edited.iterrows():
    orig = row["orig"]
    display = (row.get("name") or "").strip() or orig
    styles[display] = dict(
        marker=row["marker"],
        color=row["colour"],
        size=float(row["size"]),
        filled=bool(row["filled"]),
    )
    if orig in results:
        renamed_results[display] = results[orig]

# ---------------------------------------------------------------------------
# 5. Render the plot into a matplotlib figure and show it
# ---------------------------------------------------------------------------
with right:
    st.header("Preview")
    fig, ax = plt.subplots(figsize=(11, 9.5))
    pd_mod.render_axes(
        ax, renamed_results,
        styles=styles,
        axis_label_rotation_offset=float(rot_off),
        rotation_mode=rot_mode,
        gap=float(gap),
        show_facies=bool(show_facies),
        title=title,
    )
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)

    # ---- Download buttons for plot + register --------------------------------
    st.subheader("Downloads")
    png_buf = io.BytesIO()
    fig.savefig(png_buf, format="png", dpi=200, bbox_inches="tight")
    png_buf.seek(0)
    st.download_button("Download plot (PNG)", data=png_buf,
                       file_name="piper_diagram.png", mime="image/png")

    # Build the register in-memory (same content as export_register writes).
    rows = []
    for name, r in renamed_results.items():
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

    csv_bytes = reg.to_csv(index=True).encode("utf-8")
    st.download_button("Download register (CSV)", data=csv_bytes,
                       file_name="piper_register.csv", mime="text/csv")

    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        reg.to_excel(writer, index=True, sheet_name="Piper Register")
    xlsx_buf.seek(0)
    st.download_button("Download register (XLSX)", data=xlsx_buf,
                       file_name="piper_register.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------------------------------------------------------------------
# 6. Project save / load (JSON round-trip of all settings + the sample table)
# ---------------------------------------------------------------------------
with left:
    st.header("Project")
    proj_state = {
        "title": title,
        "gap": gap,
        "rotation_mode": rot_mode,
        "rotation_offset": rot_off,
        "facies": show_facies,
        "samples": edited.to_dict(orient="records"),
    }
    st.download_button(
        "Save project (JSON)",
        data=json.dumps(proj_state, indent=2).encode("utf-8"),
        file_name="piper_project.json", mime="application/json",
    )
    proj_upload = st.file_uploader("Load project (JSON)", type=["json"], key="proj_upload")
    if proj_upload is not None:
        try:
            loaded = json.loads(proj_upload.getvalue())
            # Apply immediately - the widgets will pick up the new state on rerun.
            st.session_state.sample_table = pd.DataFrame(loaded.get("samples", []))
            # Note: title/gap/rotation widgets read from their own keys on next run;
            # for simplicity we ask the user to re-enter those or use session_state.
            st.success("Project loaded - the sample table has been restored. "
                       "Re-adjust title/gap/rotation if they differ.")
            st.rerun()
        except Exception as e:
            st.error(f"Load failed: {e}")
