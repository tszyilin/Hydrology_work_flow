"""
Plotting Tool -- paste-and-plot desktop GUI
===========================================

A general-purpose Tkinter plotting tool, built on the same shape as
flow_comparison_gui.py but with no workbook required: you just start it
and paste data in.

The window is a set of CASES. A case is one self-contained plot: its own
data table, its own series, its own plot type, its own axis settings, its
own title/labels and its own exports. Add as many cases as you like --
each one draws a different plot, and they don't interfere with each other.

Inside every case:
  * A DATA table you can paste straight into from Excel / Google Sheets
    (Ctrl+V). Column 1 is the X values; every column after it is one
    series of Y values. If the first pasted row looks like text headers,
    it is used to name the series automatically.
  * A SERIES panel where each series gets a name, colour, line style,
    marker style, line width and marker size -- all editable, all live.
  * A PLOT panel: plot type (line, scatter, bar, step, area...), axis
    scales and limits, grid, legend, title and axis labels.
  * Export to PNG/PDF/SVG, or the plotted data back out as CSV.

Fonts default to Arial throughout (chart title, labels, ticks, legend) and
can be changed for every chart at once from the top toolbar.

Projects (all cases, data and styling) save to / load from a .plotproj
JSON file.

Usage:
    python plotting_tool.py
    python plotting_tool.py path\\to\\project.plotproj
"""

import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, colorchooser

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator, AutoMinorLocator, FuncFormatter, LogLocator, NullFormatter

APP_TITLE = "Plotting Tool"
PROJECT_EXT = ".plotproj"

# ---- fonts -----------------------------------------------------------------
DEFAULT_FONT = "Arial"
DEFAULT_FONT_SIZE = 11
FONT_CHOICES = [
    "Arial", "Calibri", "Segoe UI", "Helvetica", "Times New Roman",
    "Cambria", "Georgia", "Verdana", "Tahoma", "Courier New", "DejaVu Sans",
]

matplotlib.rcParams["font.family"] = "sans-serif"
matplotlib.rcParams["font.sans-serif"] = [DEFAULT_FONT, "Helvetica", "DejaVu Sans"]
matplotlib.rcParams["font.size"] = DEFAULT_FONT_SIZE
matplotlib.rcParams["axes.unicode_minus"] = False

# ---- styling options -------------------------------------------------------
COLOR_CYCLE = [
    "#2564A6", "#C1521C", "#2F8F6B", "#8A3FA6", "#B0862A",
    "#3D6E8C", "#A6425A", "#5C7A29", "#6A4FA0", "#2E958F",
    "#8C4B2F", "#4A6FA5",
]

LINESTYLE_OPTIONS = ["solid", "dashed", "dotted", "dash-dot", "none"]
LINESTYLE_MAP = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-.", "none": "None"}
LINESTYLE_RMAP = {v: k for k, v in LINESTYLE_MAP.items()}

MARKER_OPTIONS = ["none", "circle", "square", "tri-up", "tri-down", "diamond",
                  "thin diamond", "star", "plus", "cross", "pentagon", "point"]
MARKER_MAP = {
    "none": "None", "circle": "o", "square": "s", "tri-up": "^", "tri-down": "v",
    "diamond": "D", "thin diamond": "d", "star": "*", "plus": "P", "cross": "X",
    "pentagon": "p", "point": ".",
}
MARKER_RMAP = {v: k for k, v in MARKER_MAP.items()}

FILL_OPTIONS = ["Filled", "Hollow", "Hollow (white)"]

PLOT_TYPES = [
    "Line + markers",
    "Line only",
    "Scatter only",
    "Bar (grouped)",
    "Bar (horizontal)",
    "Bar (stacked)",
    "Step",
    "Area (filled)",
]
BAR_TYPES = {"Bar (grouped)", "Bar (horizontal)", "Bar (stacked)"}

LEGEND_LOCS = ["best", "upper left", "upper right", "lower left", "lower right",
               "upper center", "lower center", "center left", "center right", "off"]

DEFAULT_ROWS = 25
DEFAULT_SERIES = 2


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def to_float(value):
    """Lenient text -> float. Handles thousands separators, %, unicode minus,
    parenthesised negatives and blanks. Returns None when not a number."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("%", "").replace("−", "-").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def mathify(text):
    """Turn shorthand like `m^3` / `CO_2` into matplotlib mathtext so it
    renders as superscript / subscript. If the string already contains a
    `$`, it is assumed to be hand-written mathtext and returned unchanged."""
    if not text or "$" in text:
        return text
    expanded = re.sub(r"([\^_])([A-Za-z0-9])", r"\1{\2}", text)
    if "^{" not in expanded and "_{" not in expanded:
        return text
    parts = re.split(r"([\^_]\{[^}]*\})", expanded)
    out = []
    for part in parts:
        if not part:
            continue
        if part[0] in "^_" and len(part) > 1 and part[1] == "{":
            out.append(part)
        else:
            out.append(r"\mathrm{" + part.replace(" ", r"\ ") + "}")
    return "$" + "".join(out) + "$"


def fmt_num(v):
    """Compact numeric formatting for the axis-limit entry boxes."""
    if v is None:
        return ""
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:.4g}"


def tick_fmt(v):
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


def looks_like_header(cells):
    """A pasted first row counts as headers when its series columns hold
    text that isn't numeric."""
    if len(cells) < 2:
        return False
    non_numeric = sum(1 for c in cells[1:] if c.strip() and to_float(c) is None)
    return non_numeric >= max(1, (len(cells) - 1) // 2)


def make_scrollable(parent):
    """Returns (outer, inner): a vertically scrollable region. Put widgets
    into `inner`, pack/grid `outer`."""
    outer = ttk.Frame(parent)
    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
    scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    inner = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=inner, anchor="nw")

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

    def _wheel(event):
        step = 1
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        elif getattr(event, "delta", 0):
            step = -1 if event.delta > 0 else 1
        canvas.yview_scroll(step, "units")

    def _bind(_e):
        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel)
        canvas.bind_all("<Button-5>", _wheel)

    def _unbind(_e):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind)
    canvas.bind("<Leave>", _unbind)
    return outer, inner


# --------------------------------------------------------------------------
# Editable, paste-aware data grid
# --------------------------------------------------------------------------

class DataGrid(ttk.Frame):
    """Spreadsheet-style grid backed by a Treeview.

    Column 0 holds X values; every later column is one series of Y values.
    Cells edit in place (double-click, Enter, or just start typing), and
    clipboard data pasted from Excel / Sheets lands in the grid as-is --
    tab separated, one line per row.
    """

    def __init__(self, master, headers, nrows=DEFAULT_ROWS,
                 on_data_change=None, on_headers_change=None):
        super().__init__(master)
        self.headers = list(headers)
        self.data = [["" for _ in self.headers] for _ in range(nrows)]
        self.on_data_change = on_data_change
        self.on_headers_change = on_headers_change
        self._editor = None
        self._editing = None
        self.anchor = (0, 0)

        wrap = ttk.Frame(self)
        wrap.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(wrap, show="headings", selectmode="extended", height=12)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="we")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._on_click, add="+")
        self.tree.bind("<Return>", self._on_return)
        self.tree.bind("<Control-v>", self._paste_event)
        self.tree.bind("<Control-V>", self._paste_event)
        self.tree.bind("<Control-c>", self._copy_event)
        self.tree.bind("<Control-C>", self._copy_event)
        self.tree.bind("<Delete>", self._delete_event)
        self.tree.bind("<Key>", self._on_keypress)

        self._sync_columns()
        self.refresh()

    # ---------- event shims ----------
    def _paste_event(self, _event):
        self.paste_clipboard()
        return "break"

    def _copy_event(self, _event):
        self.copy_selection()
        return "break"

    def _delete_event(self, _event):
        self.clear_selection()
        return "break"

    # ---------- structure ----------
    def _sync_columns(self):
        ids = [f"c{i}" for i in range(len(self.headers))]
        self.tree.configure(columns=ids)
        for i, cid in enumerate(ids):
            self.tree.heading(cid, text=self.headers[i])
            self.tree.column(cid, width=95 if i == 0 else 115,
                             anchor="w" if i == 0 else "e", stretch=False)

    def _normalize(self):
        width = len(self.headers)
        for row in self.data:
            while len(row) < width:
                row.append("")
            del row[width:]

    def refresh(self):
        self._normalize()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.data):
            self.tree.insert("", "end", iid=str(i), values=row)

    def set_header(self, index, text):
        if 0 <= index < len(self.headers):
            self.headers[index] = text
            self.tree.heading(f"c{index}", text=text)

    def add_series_column(self, name=None):
        self.headers.append(name or f"Series {len(self.headers)}")
        for row in self.data:
            row.append("")
        self._sync_columns()
        self.refresh()
        if self.on_headers_change:
            self.on_headers_change()

    def remove_last_series_column(self):
        if len(self.headers) <= 2:
            return False
        self.headers.pop()
        for row in self.data:
            row.pop()
        self._sync_columns()
        self.refresh()
        if self.on_headers_change:
            self.on_headers_change()
        return True

    def add_rows(self, n=10):
        for _ in range(n):
            self.data.append(["" for _ in self.headers])
        self.refresh()

    def delete_selected_rows(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        if not sel:
            return
        for i in sel:
            if 0 <= i < len(self.data):
                del self.data[i]
        if not self.data:
            self.data = [["" for _ in self.headers] for _ in range(DEFAULT_ROWS)]
        self.refresh()
        self._changed()

    def clear_selection(self):
        for i in (int(i) for i in self.tree.selection()):
            if 0 <= i < len(self.data):
                self.data[i] = ["" for _ in self.headers]
        self.refresh()
        self._changed()

    def clear_all(self):
        self.data = [["" for _ in self.headers] for _ in range(DEFAULT_ROWS)]
        self.anchor = (0, 0)
        self.refresh()
        self._changed()

    # ---------- values out ----------
    def column(self, index):
        self._normalize()
        return [row[index] if index < len(row) else "" for row in self.data]

    def used_row_count(self):
        last = 0
        for i, row in enumerate(self.data):
            if any(str(c).strip() for c in row):
                last = i + 1
        return last

    # ---------- clipboard ----------
    def paste_clipboard(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("Nothing to paste", "The clipboard is empty.")
            return
        self.paste_text(text)

    def paste_text(self, text):
        raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while raw and not raw[-1].strip():
            raw.pop()
        if not raw:
            return
        sep = "\t" if any("\t" in line for line in raw) else None
        rows = [line.split(sep) if sep else [line] for line in raw]

        r0, c0 = self.anchor
        structure_changed = False

        if r0 == 0 and c0 == 0 and looks_like_header(rows[0]):
            names = [c.strip() or f"Series {i}" for i, c in enumerate(rows[0])]
            while len(names) < 2:
                names.append(f"Series {len(names)}")
            self.headers = names
            rows = rows[1:]
            structure_changed = True
            if not rows:
                self._sync_columns()
                self.refresh()
                if self.on_headers_change:
                    self.on_headers_change()
                return

        need_cols = c0 + max((len(r) for r in rows), default=0)
        while len(self.headers) < need_cols:
            self.headers.append(f"Series {len(self.headers)}")
            structure_changed = True

        need_rows = r0 + len(rows)
        while len(self.data) < need_rows:
            self.data.append(["" for _ in self.headers])
        self._normalize()

        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                r, c = r0 + ri, c0 + ci
                if c < len(self.headers):
                    self.data[r][c] = cell.strip()

        if structure_changed:
            self._sync_columns()
        self.refresh()
        if structure_changed and self.on_headers_change:
            self.on_headers_change()
        self._changed()

    def copy_selection(self):
        sel = sorted(int(i) for i in self.tree.selection())
        rows = sel or list(range(self.used_row_count()))
        lines = ["\t".join(self.headers)]
        lines += ["\t".join(str(c) for c in self.data[i]) for i in rows if i < len(self.data)]
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))

    # ---------- editing ----------
    def _col_from_x(self, x):
        colid = self.tree.identify_column(x)
        if not colid or not colid.startswith("#"):
            return None
        idx = int(colid[1:]) - 1
        return idx if 0 <= idx < len(self.headers) else None

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        rowid = self.tree.identify_row(event.y)
        col = self._col_from_x(event.x)
        if rowid and col is not None:
            self.anchor = (int(rowid), col)

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "heading":
            return None
        rowid = self.tree.identify_row(event.y)
        col = self._col_from_x(event.x)
        if rowid and col is not None:
            self._begin_edit(int(rowid), col)
        return "break"

    def _on_return(self, _event):
        r, c = self.anchor
        self._begin_edit(r, c)
        return "break"

    def _on_keypress(self, event):
        if event.state & 0x0004:                     # Ctrl held: leave to other bindings
            return None
        if len(event.char) == 1 and event.char.isprintable():
            r, c = self.anchor
            self._begin_edit(r, c, initial=event.char)
            return "break"
        return None

    def _begin_edit(self, r, c, initial=None):
        self._end_edit(commit=True)
        if not (0 <= r < len(self.data)) or not (0 <= c < len(self.headers)):
            return
        self.tree.see(str(r))
        self.tree.selection_set(str(r))
        bbox = self.tree.bbox(str(r), f"c{c}")
        if not bbox:
            return
        x, y, w, h = bbox
        self.anchor = (r, c)
        self._editing = (r, c)
        self._editor = tk.Entry(self.tree, justify="left" if c == 0 else "right",
                                relief="solid", borderwidth=1)
        self._editor.place(x=x, y=y, width=w, height=h)
        self._editor.insert(0, initial if initial is not None else self.data[r][c])
        if initial is None:
            self._editor.select_range(0, "end")
        else:
            self._editor.icursor("end")
        self._editor.focus_set()
        self._editor.bind("<Return>", lambda e: self._end_edit(commit=True, move=(1, 0)))
        self._editor.bind("<Tab>", self._edit_tab)
        self._editor.bind("<Escape>", lambda e: self._end_edit(commit=False))
        self._editor.bind("<FocusOut>", lambda e: self._end_edit(commit=True))

    def _edit_tab(self, _event):
        self._end_edit(commit=True, move=(0, 1))
        return "break"

    def _end_edit(self, commit=True, move=None):
        if self._editor is None or self._editing is None:
            return
        r, c = self._editing
        value = self._editor.get().strip() if commit else None
        editor, self._editor, self._editing = self._editor, None, None
        editor.destroy()
        if commit and value is not None:
            if 0 <= r < len(self.data) and 0 <= c < len(self.data[r]):
                self.data[r][c] = value
                self.tree.item(str(r), values=self.data[r])
                self._changed()
        self.tree.focus_set()
        if move:
            dr, dc = move
            nr, nc = r + dr, c + dc
            if nc >= len(self.headers):
                nr, nc = nr + 1, 0
            if nr >= len(self.data):
                self.add_rows(5)
            self._begin_edit(min(nr, len(self.data) - 1), nc)

    def _changed(self):
        if self.on_data_change:
            self.on_data_change()

    # ---------- persistence ----------
    def dump(self):
        used = max(self.used_row_count(), 1)
        return {"headers": list(self.headers),
                "rows": [list(r) for r in self.data[:used]]}

    def load(self, blob):
        self.headers = list(blob.get("headers") or ["X", "Series 1"])
        rows = [list(r) for r in (blob.get("rows") or [])]
        while len(rows) < DEFAULT_ROWS:
            rows.append(["" for _ in self.headers])
        self.data = rows
        self._sync_columns()
        self.refresh()
        if self.on_headers_change:
            self.on_headers_change()


# --------------------------------------------------------------------------
# Axis scale / limits panel -- one instance per case
# --------------------------------------------------------------------------

class AxisPanel:
    """Independent log/linear toggles and Auto/Custom min-max limits for X
    and Y. Each case owns its own instance, so nothing leaks between cases."""

    def __init__(self, parent, auto_xlim_fn, auto_ylim_fn, on_change):
        self.x_scale_var = tk.StringVar(value="linear")
        self.y_scale_var = tk.StringVar(value="linear")
        self.x_auto_var = tk.BooleanVar(value=True)
        self.y_auto_var = tk.BooleanVar(value=True)
        self.x_min_var = tk.StringVar()
        self.x_max_var = tk.StringVar()
        self.y_min_var = tk.StringVar()
        self.y_max_var = tk.StringVar()
        self.custom_xlim = None
        self.custom_ylim = None

        self._auto_xlim_fn = auto_xlim_fn
        self._auto_ylim_fn = auto_ylim_fn
        self._on_change = on_change

        container = ttk.Frame(parent, relief="groove", borderwidth=1)
        container.pack(fill=tk.X, pady=(2, 0))
        frame = ttk.Frame(container, padding=6)
        frame.pack(fill=tk.X)

        ttk.Label(frame, text="X scale").grid(row=0, column=0, columnspan=3, sticky="w")
        x_row = ttk.Frame(frame)
        x_row.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Radiobutton(x_row, text="Linear", variable=self.x_scale_var, value="linear",
                        command=self._on_x_scale_change).pack(side=tk.LEFT)
        ttk.Radiobutton(x_row, text="Log", variable=self.x_scale_var, value="log",
                        command=self._on_x_scale_change).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Checkbutton(frame, text="Auto X limits", variable=self.x_auto_var,
                        command=self._on_x_auto_toggle).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="min").grid(row=3, column=0, sticky="w")
        self.x_min_entry = ttk.Entry(frame, textvariable=self.x_min_var, width=10, state="disabled")
        self.x_min_entry.grid(row=3, column=1, padx=(2, 4), pady=1)
        ttk.Label(frame, text="max").grid(row=4, column=0, sticky="w")
        self.x_max_entry = ttk.Entry(frame, textvariable=self.x_max_var, width=10, state="disabled")
        self.x_max_entry.grid(row=4, column=1, padx=(2, 4), pady=1)

        ttk.Separator(frame, orient="horizontal").grid(row=5, column=0, columnspan=3,
                                                       sticky="we", pady=8)

        ttk.Label(frame, text="Y scale").grid(row=6, column=0, columnspan=3, sticky="w")
        y_row = ttk.Frame(frame)
        y_row.grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Radiobutton(y_row, text="Linear", variable=self.y_scale_var, value="linear",
                        command=self._on_y_scale_change).pack(side=tk.LEFT)
        ttk.Radiobutton(y_row, text="Log", variable=self.y_scale_var, value="log",
                        command=self._on_y_scale_change).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Checkbutton(frame, text="Auto Y limits", variable=self.y_auto_var,
                        command=self._on_y_auto_toggle).grid(row=8, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="min").grid(row=9, column=0, sticky="w")
        self.y_min_entry = ttk.Entry(frame, textvariable=self.y_min_var, width=10, state="disabled")
        self.y_min_entry.grid(row=9, column=1, padx=(2, 4), pady=1)
        ttk.Label(frame, text="max").grid(row=10, column=0, sticky="w")
        self.y_max_entry = ttk.Entry(frame, textvariable=self.y_max_var, width=10, state="disabled")
        self.y_max_entry.grid(row=10, column=1, padx=(2, 4), pady=1)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=11, column=0, columnspan=3, sticky="we", pady=(8, 0))
        ttk.Button(btn_row, text="Apply", command=self.on_apply).pack(side=tk.LEFT, expand=True, fill=tk.X)
        ttk.Button(btn_row, text="Auto", command=self.on_reset).pack(side=tk.LEFT, expand=True,
                                                                    fill=tk.X, padx=(4, 0))

        for entry in (self.x_min_entry, self.x_max_entry, self.y_min_entry, self.y_max_entry):
            entry.bind("<Return>", lambda e: self.on_apply())

    # ---------- handlers ----------
    def _on_x_scale_change(self):
        self.custom_xlim = None
        self.x_auto_var.set(True)
        self.x_min_entry.configure(state="disabled")
        self.x_max_entry.configure(state="disabled")
        self._on_change()

    def _on_y_scale_change(self):
        self.custom_ylim = None
        self.y_auto_var.set(True)
        self.y_min_entry.configure(state="disabled")
        self.y_max_entry.configure(state="disabled")
        self._on_change()

    def _on_x_auto_toggle(self):
        is_auto = self.x_auto_var.get()
        self.x_min_entry.configure(state="disabled" if is_auto else "normal")
        self.x_max_entry.configure(state="disabled" if is_auto else "normal")
        if is_auto:
            self.custom_xlim = None
        else:
            lo, hi = self.custom_xlim if self.custom_xlim else self._auto_xlim_fn()
            self.x_min_var.set(fmt_num(lo))
            self.x_max_var.set(fmt_num(hi))
            self.custom_xlim = (lo, hi)
        self._on_change()

    def _on_y_auto_toggle(self):
        is_auto = self.y_auto_var.get()
        self.y_min_entry.configure(state="disabled" if is_auto else "normal")
        self.y_max_entry.configure(state="disabled" if is_auto else "normal")
        if is_auto:
            self.custom_ylim = None
        else:
            lo, hi = self.custom_ylim if self.custom_ylim else self._auto_ylim_fn()
            self.y_min_var.set(fmt_num(lo))
            self.y_max_var.set(fmt_num(hi))
            self.custom_ylim = (lo, hi)
        self._on_change()

    def on_apply(self):
        errors = []
        if not self.x_auto_var.get():
            try:
                xlo, xhi = float(self.x_min_var.get()), float(self.x_max_var.get())
                if self.x_scale_var.get() == "log" and (xlo <= 0 or xhi <= 0):
                    raise ValueError("limits must be positive on a log scale.")
                if xlo >= xhi:
                    raise ValueError("min must be less than max.")
                self.custom_xlim = (xlo, xhi)
            except ValueError as exc:
                errors.append(f"X axis: {exc or 'must be valid numbers'}")
        if not self.y_auto_var.get():
            try:
                ylo, yhi = float(self.y_min_var.get()), float(self.y_max_var.get())
                if self.y_scale_var.get() == "log" and (ylo <= 0 or yhi <= 0):
                    raise ValueError("limits must be positive on a log scale.")
                if ylo >= yhi:
                    raise ValueError("min must be less than max.")
                self.custom_ylim = (ylo, yhi)
            except ValueError as exc:
                errors.append(f"Y axis: {exc or 'must be valid numbers'}")
        if errors:
            messagebox.showerror("Invalid axis limits", "\n".join(errors))
            return
        self._on_change()

    def on_reset(self):
        self.x_auto_var.set(True)
        self.y_auto_var.set(True)
        self.custom_xlim = None
        self.custom_ylim = None
        for entry in (self.x_min_entry, self.x_max_entry, self.y_min_entry, self.y_max_entry):
            entry.configure(state="disabled")
        self._on_change()

    # ---------- redraw ----------
    def apply_to_axes(self, ax, categorical_x=False, horizontal=False):
        """categorical_x: the X values are labels, so the X scale/limit
        controls are ignored (matplotlib places the categories itself)."""
        x_scale = "linear" if categorical_x else self.x_scale_var.get()
        ax.set_xscale(x_scale)
        if not categorical_x:
            if self.x_auto_var.get():
                xlo, xhi = self._auto_xlim_fn()
                self.x_min_var.set(fmt_num(xlo))
                self.x_max_var.set(fmt_num(xhi))
            else:
                xlo, xhi = self.custom_xlim if self.custom_xlim else self._auto_xlim_fn()
            if xlo is not None and xhi is not None and xlo < xhi:
                ax.set_xlim(xlo, xhi)
            if x_scale == "log":
                ax.xaxis.set_major_locator(LogLocator(base=10.0))
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: tick_fmt(v)))
                ax.xaxis.set_minor_locator(LogLocator(base=10.0, subs=range(2, 10)))
                ax.xaxis.set_minor_formatter(NullFormatter())
            else:
                ax.xaxis.set_major_locator(AutoLocator())
                ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: tick_fmt(v)))
                ax.xaxis.set_minor_locator(AutoMinorLocator())
                ax.xaxis.set_minor_formatter(NullFormatter())

        y_scale = self.y_scale_var.get()
        ax.set_yscale(y_scale)
        if self.y_auto_var.get():
            ylo, yhi = self._auto_ylim_fn()
            self.y_min_var.set(fmt_num(ylo))
            self.y_max_var.set(fmt_num(yhi))
        else:
            ylo, yhi = self.custom_ylim if self.custom_ylim else self._auto_ylim_fn()
        if ylo is not None and yhi is not None and ylo < yhi:
            ax.set_ylim(ylo, yhi)
        if y_scale == "log":
            ax.yaxis.set_major_locator(LogLocator(base=10.0))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: tick_fmt(v)))
            ax.yaxis.set_minor_locator(LogLocator(base=10.0, subs=range(2, 10)))
            ax.yaxis.set_minor_formatter(NullFormatter())
        else:
            ax.yaxis.set_major_locator(AutoLocator())
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: tick_fmt(v)))
            ax.yaxis.set_minor_locator(AutoMinorLocator())
            ax.yaxis.set_minor_formatter(NullFormatter())

    # ---------- persistence ----------
    def dump(self):
        return {
            "x_scale": self.x_scale_var.get(), "y_scale": self.y_scale_var.get(),
            "x_auto": self.x_auto_var.get(), "y_auto": self.y_auto_var.get(),
            "xlim": list(self.custom_xlim) if self.custom_xlim else None,
            "ylim": list(self.custom_ylim) if self.custom_ylim else None,
        }

    def load(self, blob):
        self.x_scale_var.set(blob.get("x_scale", "linear"))
        self.y_scale_var.set(blob.get("y_scale", "linear"))
        self.x_auto_var.set(bool(blob.get("x_auto", True)))
        self.y_auto_var.set(bool(blob.get("y_auto", True)))
        self.custom_xlim = tuple(blob["xlim"]) if blob.get("xlim") else None
        self.custom_ylim = tuple(blob["ylim"]) if blob.get("ylim") else None
        for auto, lo_e, hi_e, lim, lo_v, hi_v in (
            (self.x_auto_var, self.x_min_entry, self.x_max_entry, self.custom_xlim,
             self.x_min_var, self.x_max_var),
            (self.y_auto_var, self.y_min_entry, self.y_max_entry, self.custom_ylim,
             self.y_min_var, self.y_max_var),
        ):
            state = "disabled" if auto.get() else "normal"
            lo_e.configure(state=state)
            hi_e.configure(state=state)
            if lim:
                lo_v.set(fmt_num(lim[0]))
                hi_v.set(fmt_num(lim[1]))


# --------------------------------------------------------------------------
# Reference-lines panel (horizontal / vertical guides on the chart)
# --------------------------------------------------------------------------

REFLINE_ORIENTATIONS = ["Horizontal", "Vertical"]
REFLINE_ORI_MAP = {"Horizontal": "h", "Vertical": "v"}
REFLINE_ORI_RMAP = {v: k for k, v in REFLINE_ORI_MAP.items()}


class RefLinesPanel:
    """Per-case list of horizontal/vertical reference lines. Each line has
    its own orientation, value, color, linestyle, width and optional label
    (labels appear in the plot legend)."""

    def __init__(self, parent, on_change):
        self._on_change = on_change
        self.lines = []   # list of dicts of tk vars + a "color" string

        container = ttk.Frame(parent, relief="groove", borderwidth=1)
        container.pack(fill=tk.X, pady=(2, 0))
        self.frame = ttk.Frame(container, padding=6)
        self.frame.pack(fill=tk.X)

        btns = ttk.Frame(self.frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="+ line", command=self.add_line).pack(side=tk.LEFT)
        ttk.Button(btns, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=(4, 0))

        self.rows_frame = ttk.Frame(self.frame)
        self.rows_frame.pack(fill=tk.X, pady=(4, 0))

    # ---------- state helpers ----------
    def _new_state(self, blob=None):
        blob = blob or {}
        state = {
            "orientation": tk.StringVar(value=REFLINE_ORI_RMAP.get(blob.get("orientation", "h"), "Horizontal")),
            "value": tk.StringVar(value=str(blob.get("value", "0"))),
            "color": blob.get("color", "#666666"),
            "linestyle": tk.StringVar(value=blob.get("linestyle", "dashed")),
            "width": tk.StringVar(value=str(blob.get("width", "1.2"))),
            "label": tk.StringVar(value=blob.get("label", "")),
        }
        for key in ("orientation", "value", "linestyle", "width", "label"):
            state[key].trace_add("write", lambda *_: self._on_change())
        return state

    def add_line(self, blob=None):
        self.lines.append(self._new_state(blob))
        self._rebuild()
        self._on_change()

    def remove_line(self, index):
        if 0 <= index < len(self.lines):
            del self.lines[index]
            self._rebuild()
            self._on_change()

    def clear(self):
        if not self.lines:
            return
        self.lines.clear()
        self._rebuild()
        self._on_change()

    def pick_color(self, index):
        current = self.lines[index]["color"]
        _rgb, hexval = colorchooser.askcolor(color=current, title="Reference line colour")
        if not hexval:
            return
        self.lines[index]["color"] = hexval
        self._rebuild()
        self._on_change()

    # ---------- ui ----------
    def _rebuild(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()
        for i, state in enumerate(self.lines):
            row = ttk.Frame(self.rows_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Combobox(row, textvariable=state["orientation"], values=REFLINE_ORIENTATIONS,
                         state="readonly", width=10).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=state["value"], width=7).pack(side=tk.LEFT, padx=(2, 2))
            swatch = tk.Canvas(row, width=16, height=14, highlightthickness=1,
                               highlightbackground="#999999", bg=state["color"], cursor="hand2")
            swatch.pack(side=tk.LEFT, padx=(0, 2))
            swatch.bind("<Button-1>", lambda e, idx=i: self.pick_color(idx))
            ttk.Combobox(row, textvariable=state["linestyle"], values=LINESTYLE_OPTIONS,
                         state="readonly", width=7).pack(side=tk.LEFT, padx=(0, 2))
            ttk.Spinbox(row, textvariable=state["width"], from_=0.2, to=6.0, increment=0.2,
                        width=4).pack(side=tk.LEFT, padx=(0, 2))
            ttk.Entry(row, textvariable=state["label"], width=8).pack(side=tk.LEFT, padx=(0, 2))
            ttk.Button(row, text="−", width=2,
                       command=lambda idx=i: self.remove_line(idx)).pack(side=tk.LEFT)

    # ---------- drawing ----------
    def apply_to_axes(self, ax):
        for state in self.lines:
            value = to_float(state["value"].get())
            if value is None:
                continue
            orientation = REFLINE_ORI_MAP.get(state["orientation"].get(), "h")
            linestyle = LINESTYLE_MAP.get(state["linestyle"].get(), "--")
            if linestyle == "None":
                linestyle = "--"
            width = to_float(state["width"].get()) or 1.2
            label = state["label"].get().strip() or None
            if orientation == "h":
                ax.axhline(value, color=state["color"], linestyle=linestyle,
                           linewidth=width, label=label)
            else:
                ax.axvline(value, color=state["color"], linestyle=linestyle,
                           linewidth=width, label=label)

    # ---------- persistence ----------
    def dump(self):
        out = []
        for state in self.lines:
            out.append({
                "orientation": REFLINE_ORI_MAP.get(state["orientation"].get(), "h"),
                "value": state["value"].get(),
                "color": state["color"],
                "linestyle": state["linestyle"].get(),
                "width": state["width"].get(),
                "label": state["label"].get(),
            })
        return out

    def load(self, blob_list):
        self.lines.clear()
        for blob in blob_list or []:
            self.lines.append(self._new_state(blob))
        self._rebuild()


# --------------------------------------------------------------------------
# One case = one plot
# --------------------------------------------------------------------------

SET_MODES = ("shared", "pair")
SET_MODE_LABELS = {"shared": "Shared X", "pair": "Pair (X,Y per series)"}
SET_MODE_FROM_LABEL = {v: k for k, v in SET_MODE_LABELS.items()}


def _default_set(name="Set 1", mode="shared"):
    if mode == "pair":
        headers = ["Series 1 - X", "Series 1 - Y"]
    else:
        headers = ["X"] + [f"Series {i}" for i in range(1, DEFAULT_SERIES + 1)]
    return {
        "name": name,
        "mode": mode,
        "enabled": True,
        "headers": headers,
        "rows": [["" for _ in headers] for _ in range(DEFAULT_ROWS)],
    }


def _set_series_count(s):
    if s.get("mode") == "pair":
        return len(s["headers"]) // 2
    return max(len(s["headers"]) - 1, 0)


def _set_xy_cols(s, j):
    """(x_col_index, y_col_index) for the j-th series in set s."""
    if s.get("mode") == "pair":
        return 2 * j, 2 * j + 1
    return 0, j + 1


class DataWindow(tk.Toplevel):
    """Popup editor for a case's series sets.

    Left pane: listbox of sets + add/rename/remove buttons.
    Right pane: DataGrid of the selected set + paste / rows / series buttons.
    """

    def __init__(self, case):
        super().__init__(case.app.root)
        self.case = case
        self.title(f"Data - {case.name}")
        self.geometry("880x580")
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        outer = ttk.Frame(self, padding=8)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        ttk.Label(left, text="SERIES SETS", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.listbox = tk.Listbox(left, height=20, width=22, exportselection=False)
        self.listbox.pack(fill=tk.Y, expand=True, pady=(2, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        lb_btns = ttk.Frame(left)
        lb_btns.pack(fill=tk.X)
        ttk.Button(lb_btns, text="+ Set", width=7, command=self._on_add).pack(side=tk.LEFT)
        ttk.Button(lb_btns, text="Rename", width=8, command=self._on_rename).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(lb_btns, text="Remove", width=8, command=self._on_remove).pack(side=tk.LEFT, padx=(4, 0))

        right = ttk.Frame(outer)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        mode_row = ttk.Frame(right)
        mode_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mode_row, text="Set mode:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value=SET_MODE_LABELS["shared"])
        self.mode_combo = ttk.Combobox(mode_row, textvariable=self.mode_var,
                                       values=list(SET_MODE_LABELS.values()),
                                       state="readonly", width=22)
        self.mode_combo.pack(side=tk.LEFT, padx=(4, 0))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)
        self.mode_hint = ttk.Label(mode_row, text="", foreground="#666666")
        self.mode_hint.pack(side=tk.LEFT, padx=(10, 0))

        self.grid_holder = ttk.Frame(right)
        self.grid_holder.pack(fill=tk.BOTH, expand=True)
        self.action_bar = ttk.Frame(right)
        self.action_bar.pack(fill=tk.X, pady=(6, 0))

        self._grid = None
        self._current_index = None
        self.refresh_list()
        if self.case.sets:
            self.select(0)

    def show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for s in self.case.sets:
            self.listbox.insert(tk.END, s["name"])
        if self._current_index is not None and 0 <= self._current_index < len(self.case.sets):
            self.listbox.selection_set(self._current_index)

    def select(self, index):
        if not self.case.sets:
            self._teardown_grid()
            self._current_index = None
            return
        index = max(0, min(index, len(self.case.sets) - 1))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self._current_index = index
        self._show_grid(index)

    def _teardown_grid(self):
        if self._grid is not None:
            self._grid.destroy()
            self._grid = None
        for w in self.action_bar.winfo_children():
            w.destroy()

    def _show_grid(self, index):
        self._teardown_grid()
        model = self.case.sets[index]
        mode = model.get("mode", "shared")
        self.mode_var.set(SET_MODE_LABELS[mode])
        self.mode_hint.configure(text=(
            "Column 1 = X; other columns = Y series." if mode == "shared"
            else "Columns are pairs: Series 1-X, Series 1-Y, Series 2-X, ..."
        ))
        grid = DataGrid(self.grid_holder, model["headers"],
                        on_data_change=lambda: self._sync_from_grid(index, structure=False),
                        on_headers_change=lambda: self._sync_from_grid(index, structure=True))
        grid.load({"headers": model["headers"], "rows": model["rows"]})
        grid.pack(fill=tk.BOTH, expand=True)
        self._grid = grid

        ab = self.action_bar
        ttk.Button(ab, text="Paste", width=8, command=grid.paste_clipboard).pack(side=tk.LEFT)
        ttk.Button(ab, text="Copy", width=7, command=grid.copy_selection).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ab, text="+20 rows", width=9,
                   command=lambda: grid.add_rows(20)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ab, text="Del rows", width=9,
                   command=grid.delete_selected_rows).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ab, text="+ series", width=9,
                   command=self._on_add_series).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ab, text="- series", width=9,
                   command=self._on_remove_series).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(ab, text="Clear", width=7,
                   command=grid.clear_all).pack(side=tk.LEFT, padx=(4, 0))

    def _on_add_series(self):
        if self._grid is None or self._current_index is None:
            return
        model = self.case.sets[self._current_index]
        if model.get("mode") == "pair":
            n = _set_series_count(model) + 1
            self._grid.add_series_column(name=f"Series {n} - X")
            self._grid.add_series_column(name=f"Series {n} - Y")
        else:
            self._grid.add_series_column()

    def _on_remove_series(self):
        if self._grid is None or self._current_index is None:
            return
        model = self.case.sets[self._current_index]
        if model.get("mode") == "pair":
            if len(self._grid.headers) <= 2:
                messagebox.showinfo("Keep one series", "A set needs at least one X,Y pair.")
                return
            self._grid.remove_last_series_column()
            self._grid.remove_last_series_column()
        else:
            if not self._grid.remove_last_series_column():
                messagebox.showinfo("Keep one series", "A set needs at least one series column.")

    def _on_mode_change(self, _event=None):
        if self._current_index is None:
            return
        new_mode = SET_MODE_FROM_LABEL.get(self.mode_var.get(), "shared")
        model = self.case.sets[self._current_index]
        if new_mode == model.get("mode"):
            return
        model["mode"] = new_mode
        if new_mode == "pair":
            if len(model["headers"]) < 2:
                model["headers"] = ["Series 1 - X", "Series 1 - Y"]
                for r in model["rows"]:
                    while len(r) < 2:
                        r.append("")
            n_pairs = len(model["headers"]) // 2
            new_headers = []
            for i in range(n_pairs):
                new_headers.append(f"Series {i + 1} - X")
                new_headers.append(f"Series {i + 1} - Y")
            model["headers"] = new_headers
        else:  # shared
            if len(model["headers"]) < 2:
                model["headers"] = ["X", "Series 1"]
                for r in model["rows"]:
                    while len(r) < 2:
                        r.append("")
            new_headers = ["X"] + [f"Series {i}" for i in range(1, len(model["headers"]))]
            model["headers"] = new_headers
        for r in model["rows"]:
            while len(r) < len(new_headers):
                r.append("")
            del r[len(new_headers):]
        self.case.on_set_structure_changed()
        self._show_grid(self._current_index)

    def _sync_from_grid(self, index, structure):
        if self._grid is None or index != self._current_index:
            return
        model = self.case.sets[index]
        model["headers"] = list(self._grid.headers)
        model["rows"] = [list(r) for r in self._grid.data]
        if structure:
            self.case.on_set_structure_changed()
        else:
            self.case.on_set_data_changed()

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx != self._current_index:
            self._current_index = idx
            self._show_grid(idx)

    def _on_add(self):
        n = len(self.case.sets) + 1
        self.case.sets.append(_default_set(f"Set {n}"))
        self.case.on_set_structure_changed()
        self.refresh_list()
        self.select(len(self.case.sets) - 1)

    def _on_remove(self):
        if len(self.case.sets) <= 1:
            messagebox.showinfo("Keep one set", "A case needs at least one series set.")
            return
        idx = self._current_index or 0
        del self.case.sets[idx]
        self.case.on_set_structure_changed()
        self.refresh_list()
        self.select(min(idx, len(self.case.sets) - 1))

    def _on_rename(self):
        if self._current_index is None:
            return
        idx = self._current_index
        current = self.case.sets[idx]["name"]
        dlg = TextPromptDialog(self, "Rename set", "New set name:", current)
        if dlg.result:
            self.case.sets[idx]["name"] = dlg.result
            self.case.on_set_structure_changed()
            self.refresh_list()
            self.listbox.selection_set(idx)
            self.title(f"Data - {self.case.name}")


class CaseTab:
    """A single, self-contained plot: data table, series styling, plot
    options, chart canvas and exports."""

    def __init__(self, app, parent, name):
        self.app = app
        self.name = name
        self.frame = ttk.Frame(parent)
        self.sets = [_default_set()]
        self.series_states = []   # parallel to self.sets: one list per set
        self._data_window = None
        self._suspend = False     # set while rebuilding, to avoid redraw storms

        # ---- plot options vars ----
        self.plot_type_var = tk.StringVar(value=PLOT_TYPES[0])
        self.title_var = tk.StringVar(value=name)
        self.xlabel_var = tk.StringVar(value="X")
        self.ylabel_var = tk.StringVar(value="Y")
        self.grid_var = tk.BooleanVar(value=True)
        self.legend_var = tk.StringVar(value="best")

        for var in (self.plot_type_var, self.title_var, self.xlabel_var,
                    self.ylabel_var, self.legend_var):
            var.trace_add("write", lambda *_: self.redraw())
        self.grid_var.trace_add("write", lambda *_: self.redraw())

        # ---------------- layout: options | plot | data/series ----------------
        paned = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 6, 0))
        center = ttk.Frame(paned)
        right = ttk.Frame(paned, padding=(6, 0, 0, 0))
        paned.add(left, weight=0)
        paned.add(center, weight=1)
        paned.add(right, weight=0)

        # ---- OPTIONS column (leftmost) ----
        opt_container = ttk.Frame(left, width=260)
        opt_container.pack(fill=tk.BOTH, expand=True)
        opt_container.pack_propagate(False)
        opt_outer, opts = make_scrollable(opt_container)
        opt_outer.pack(fill=tk.BOTH, expand=True)

        # ---- DATA / SERIES column (rightmost) ----
        ttk.Label(right, text="DATA", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(right,
                  text="Each series set has its own X column. Open the data window "
                       "to add sets and paste values.",
                  foreground="#666666", wraplength=280, justify="left").pack(anchor="w", pady=(0, 4))

        data_row = ttk.Frame(right)
        data_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(data_row, text="Open data window...", width=22,
                   command=self.open_data_window).pack(side=tk.LEFT)
        self.data_summary = ttk.Label(right, text="", foreground="#444444")
        self.data_summary.pack(anchor="w", pady=(0, 8))

        ttk.Label(right, text="SERIES", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        series_container = ttk.Frame(right, relief="groove", borderwidth=1, width=340, height=360)
        series_container.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        series_container.pack_propagate(False)
        series_outer, self.series_frame = make_scrollable(series_container)
        series_outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(opts, text="PLOT TYPE", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Combobox(opts, textvariable=self.plot_type_var, values=PLOT_TYPES,
                     state="readonly").pack(fill=tk.X, pady=(2, 12))

        ttk.Label(opts, text="LABELS", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        lbl_container = ttk.Frame(opts, relief="groove", borderwidth=1)
        lbl_container.pack(fill=tk.X, pady=(2, 12))
        lbl = ttk.Frame(lbl_container, padding=6)
        lbl.pack(fill=tk.X)
        for row, (text, var) in enumerate((("Title", self.title_var),
                                           ("X label", self.xlabel_var),
                                           ("Y label", self.ylabel_var))):
            ttk.Label(lbl, text=text).grid(row=row, column=0, sticky="w", pady=1)
            ttk.Entry(lbl, textvariable=var, width=16).grid(row=row, column=1, sticky="we", pady=1)
        lbl.columnconfigure(1, weight=1)
        ttk.Checkbutton(lbl, text="Show grid", variable=self.grid_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(lbl, text="Legend").grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(lbl, textvariable=self.legend_var, values=LEGEND_LOCS,
                     state="readonly", width=14).grid(row=4, column=1, sticky="we", pady=(4, 0))

        ttk.Label(opts, text="AXES", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.axis = AxisPanel(opts, self._auto_xlim, self._auto_ylim, self.redraw)

        ttk.Label(opts, text="REFERENCE LINES", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        self.reflines = RefLinesPanel(opts, self.redraw)

        ttk.Label(opts, text="EXPORT", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(12, 0))
        exp_container = ttk.Frame(opts, relief="groove", borderwidth=1)
        exp_container.pack(fill=tk.X, pady=(2, 0))
        exp = ttk.Frame(exp_container, padding=6)
        exp.pack(fill=tk.X)
        ttk.Button(exp, text="Chart as image...", command=self.on_export_image).pack(fill=tk.X, pady=(0, 4))
        ttk.Button(exp, text="Copy chart to clipboard", command=self.on_copy_image).pack(fill=tk.X, pady=(0, 4))
        ttk.Button(exp, text="Data as CSV...", command=self.on_export_csv).pack(fill=tk.X)

        plot_frame = ttk.Frame(center)
        plot_frame.pack(fill=tk.BOTH, expand=True)
        self.fig = Figure(figsize=(7.5, 5.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, plot_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill=tk.X)

        self._sync_series_states()
        self._rebuild_series_rows()
        self._update_summary()
        self.redraw()

    # ---------------- data window plumbing ----------------
    def open_data_window(self):
        if self._data_window is None or not self._data_window.winfo_exists():
            self._data_window = DataWindow(self)
        else:
            self._data_window.show()

    def on_set_data_changed(self):
        self._update_summary()
        self.redraw()

    def on_set_structure_changed(self):
        self._sync_series_states()
        self._rebuild_series_rows()
        self._update_summary()
        self.redraw()

    def _update_summary(self):
        n_sets = len(self.sets)
        n_series = sum(max(len(s["headers"]) - 1, 0) for s in self.sets)
        self.data_summary.configure(text=f"{n_sets} set(s), {n_series} series")

    # ---------------- series styling ----------------
    def _default_series_state(self, index, name):
        color = COLOR_CYCLE[index % len(COLOR_CYCLE)]
        return {
            "enabled": tk.BooleanVar(value=True),
            "name": tk.StringVar(value=name),
            "color": color,
            "linestyle": tk.StringVar(value="solid"),
            "marker": tk.StringVar(value=MARKER_OPTIONS[(index % 6) + 1]),
            "width": tk.StringVar(value="1.6"),
            "size": tk.StringVar(value="5"),
            "fill": tk.StringVar(value="Filled"),
        }

    def _sync_series_states(self):
        """Ensure self.series_states matches self.sets shape (one row per set,
        one state per Y column). Preserves existing states where possible."""
        self._suspend = True
        while len(self.series_states) < len(self.sets):
            self.series_states.append([])
        del self.series_states[len(self.sets):]

        global_idx = 0
        for si, s in enumerate(self.sets):
            n_y = _set_series_count(s)
            row = self.series_states[si]
            while len(row) < n_y:
                j = len(row)
                _, y_col = _set_xy_cols(s, j)
                header = s["headers"][y_col] if y_col < len(s["headers"]) else f"Series {global_idx + j + 1}"
                state = self._default_series_state(global_idx + j, header)
                for key in ("enabled", "linestyle", "marker", "width", "size", "fill"):
                    state[key].trace_add("write", lambda *_: self.redraw())
                state["name"].trace_add(
                    "write", lambda *_, ss=si, jj=j: self._on_name_change(ss, jj))
                row.append(state)
            del row[n_y:]
            for j, state in enumerate(row):
                _, y_col = _set_xy_cols(s, j)
                if y_col < len(s["headers"]):
                    hdr = s["headers"][y_col]
                    if hdr and hdr != state["name"].get():
                        state["name"].set(hdr)
            global_idx += n_y
        self._suspend = False

    def _rebuild_series_rows(self):
        for w in self.series_frame.winfo_children():
            w.destroy()

        total = sum(len(row) for row in self.series_states)
        if total == 0:
            ttk.Label(self.series_frame, text="No series.",
                      foreground="#888888").pack(anchor="w", padx=6, pady=6)
            return

        for si, row in enumerate(self.series_states):
            if not row:
                continue
            header_row = ttk.Frame(self.series_frame)
            header_row.pack(fill=tk.X, padx=6, pady=(6, 0))
            set_model = self.sets[si]
            if "enabled_var" not in set_model:
                set_model["enabled_var"] = tk.BooleanVar(
                    value=bool(set_model.get("enabled", True)))
                set_model["enabled_var"].trace_add(
                    "write",
                    lambda *_, sm=set_model: (sm.__setitem__("enabled", sm["enabled_var"].get()),
                                              self.redraw()))
            ttk.Checkbutton(header_row, variable=set_model["enabled_var"]).pack(side=tk.LEFT)
            ttk.Label(header_row, text=set_model["name"],
                      font=("Segoe UI", 9, "bold"),
                      foreground="#2A4F80").pack(side=tk.LEFT, padx=(2, 0))
            for j, state in enumerate(row):
                box = ttk.Frame(self.series_frame, padding=(6, 4))
                box.pack(fill=tk.X)

                top = ttk.Frame(box)
                top.pack(fill=tk.X)
                ttk.Checkbutton(top, variable=state["enabled"]).pack(side=tk.LEFT)
                swatch = tk.Canvas(top, width=18, height=14, highlightthickness=1,
                                   highlightbackground="#999999", bg=state["color"], cursor="hand2")
                swatch.pack(side=tk.LEFT, padx=(2, 6))
                swatch.bind("<Button-1>", lambda e, ss=si, jj=j: self.on_pick_color(ss, jj))
                state["swatch"] = swatch
                hex_var = tk.StringVar(value=state["color"])
                state["hex_var"] = hex_var
                hex_entry = ttk.Entry(top, textvariable=hex_var, width=9)
                hex_entry.pack(side=tk.LEFT, padx=(0, 4))
                commit = lambda _e=None, ss=si, jj=j: self._apply_hex_color(ss, jj)
                hex_entry.bind("<Return>", commit)
                hex_entry.bind("<FocusOut>", commit)
                ttk.Entry(top, textvariable=state["name"]).pack(side=tk.LEFT, fill=tk.X, expand=True)

                bottom = ttk.Frame(box)
                bottom.pack(fill=tk.X, pady=(2, 0), padx=(24, 0))
                ttk.Label(bottom, text="Line").pack(side=tk.LEFT)
                ttk.Combobox(bottom, textvariable=state["linestyle"], values=LINESTYLE_OPTIONS,
                             state="readonly", width=9).pack(side=tk.LEFT, padx=(2, 6))
                ttk.Label(bottom, text="Marker").pack(side=tk.LEFT)
                ttk.Combobox(bottom, textvariable=state["marker"], values=MARKER_OPTIONS,
                             state="readonly", width=11).pack(side=tk.LEFT, padx=(2, 0))

                sizes = ttk.Frame(box)
                sizes.pack(fill=tk.X, pady=(2, 4), padx=(24, 0))
                ttk.Label(sizes, text="Width").pack(side=tk.LEFT)
                ttk.Spinbox(sizes, textvariable=state["width"], from_=0.2, to=8.0, increment=0.2,
                            width=5).pack(side=tk.LEFT, padx=(2, 8))
                ttk.Label(sizes, text="Mkr size").pack(side=tk.LEFT)
                ttk.Spinbox(sizes, textvariable=state["size"], from_=1, to=20, increment=1,
                            width=5).pack(side=tk.LEFT, padx=(2, 8))
                ttk.Label(sizes, text="Fill").pack(side=tk.LEFT)
                ttk.Combobox(sizes, textvariable=state["fill"], values=FILL_OPTIONS,
                             state="readonly", width=13).pack(side=tk.LEFT, padx=(2, 0))

            ttk.Separator(self.series_frame, orient="horizontal").pack(fill=tk.X, padx=4)

    def _on_name_change(self, si, j):
        if self._suspend:
            return
        if si >= len(self.sets):
            return
        _, header_idx = _set_xy_cols(self.sets[si], j)
        if header_idx >= len(self.sets[si]["headers"]):
            return
        new_name = self.series_states[si][j]["name"].get()
        self.sets[si]["headers"][header_idx] = new_name
        if (self._data_window and self._data_window.winfo_exists()
                and self._data_window._current_index == si
                and self._data_window._grid is not None):
            self._data_window._grid.set_header(header_idx, new_name)
        self.redraw()

    def on_pick_color(self, si, j):
        state = self.series_states[si][j]
        _, hexval = colorchooser.askcolor(color=state["color"], title="Series colour")
        if not hexval:
            return
        state["color"] = hexval
        state["swatch"].configure(bg=hexval)
        if "hex_var" in state:
            state["hex_var"].set(hexval)
        self.redraw()

    def _apply_hex_color(self, si, j):
        state = self.series_states[si][j]
        raw = state["hex_var"].get().strip()
        val = raw if raw.startswith("#") else f"#{raw}"
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", val):
            state["hex_var"].set(state["color"])
            return
        val = val.lower()
        if val == state["color"].lower():
            state["hex_var"].set(val)
            return
        state["color"] = val
        state["swatch"].configure(bg=val)
        state["hex_var"].set(val)
        self.redraw()

    def on_clear(self):
        if messagebox.askyesno("Clear data", f"Clear all data in '{self.name}'?"):
            for s in self.sets:
                s["rows"] = [["" for _ in s["headers"]] for _ in range(DEFAULT_ROWS)]
            if self._data_window and self._data_window.winfo_exists():
                self._data_window._show_grid(self._data_window._current_index or 0)
            self.redraw()

    # ---------------- data extraction ----------------
    @staticmethod
    def _set_column(s, index):
        return [row[index] if index < len(row) else "" for row in s["rows"]]

    @staticmethod
    def _set_used_rows(s):
        last = 0
        for i, row in enumerate(s["rows"]):
            if any(str(c).strip() for c in row):
                last = i + 1
        return last

    def plotted_series(self):
        """Returns (x_labels, categorical, [(name, xs, ys, state), ...]).

        Categorical X (text labels) is only allowed for a single shared-mode
        set; anything else uses numeric X per series."""
        active_sets = [s for s in self.sets if s.get("enabled", True)]
        single_shared = (len(active_sets) == 1
                         and active_sets[0].get("mode", "shared") == "shared")
        if single_shared:
            s = active_sets[0]
            active_si = self.sets.index(s)
            n_rows = self._set_used_rows(s)
            x_raw = self._set_column(s, 0)[:n_rows]
            x_num = [to_float(v) for v in x_raw]
            has_x = any(str(v).strip() for v in x_raw)
            categorical = has_x and any(
                str(raw).strip() and num is None for raw, num in zip(x_raw, x_num))

            out = []
            row_states = (self.series_states[active_si]
                          if active_si < len(self.series_states) else [])
            for j, state in enumerate(row_states):
                if not state["enabled"].get():
                    continue
                col = self._set_column(s, j + 1)[:n_rows]
                xs, ys = [], []
                for r, cell in enumerate(col):
                    y = to_float(cell)
                    if y is None:
                        continue
                    if categorical or not has_x:
                        xs.append(r)
                    else:
                        if x_num[r] is None:
                            continue
                        xs.append(x_num[r])
                    ys.append(y)
                if ys:
                    out.append((state["name"].get() or f"Series {j + 1}", xs, ys, state))

            labels = [str(v).strip() if str(v).strip() else str(i + 1)
                      for i, v in enumerate(x_raw)] if (categorical or not has_x) else []
            return labels, (categorical or not has_x), out

        # multi-set or pair-mode set(s): numeric X per series
        out = []
        for si, s in enumerate(self.sets):
            if not s.get("enabled", True):
                continue
            n_rows = self._set_used_rows(s)
            row_states = self.series_states[si] if si < len(self.series_states) else []
            pair_mode = s.get("mode") == "pair"
            shared_x_num = None
            if not pair_mode:
                shared_x_num = [to_float(v) for v in self._set_column(s, 0)[:n_rows]]
            for j, state in enumerate(row_states):
                if not state["enabled"].get():
                    continue
                x_col, y_col = _set_xy_cols(s, j)
                y_vals = self._set_column(s, y_col)[:n_rows]
                if pair_mode:
                    x_vals = [to_float(v) for v in self._set_column(s, x_col)[:n_rows]]
                else:
                    x_vals = shared_x_num
                xs, ys = [], []
                for r, cell in enumerate(y_vals):
                    y = to_float(cell)
                    x = x_vals[r] if r < len(x_vals) else None
                    if y is None or x is None:
                        continue
                    xs.append(x)
                    ys.append(y)
                if ys:
                    out.append((state["name"].get() or f"Series {j + 1}", xs, ys, state))
        return [], False, out

    # ---------------- auto limits ----------------
    def _auto_xlim(self):
        _, categorical, series = self.plotted_series()
        if categorical or not series:
            return (None, None)
        values = [v for _, xs, _, _ in series for v in xs]
        if not values:
            return (None, None)
        lo, hi = min(values), max(values)
        if self.axis.x_scale_var.get() == "log":
            positive = [v for v in values if v > 0]
            if not positive:
                return (None, None)
            return (10 ** math.floor(math.log10(min(positive))),
                    10 ** math.ceil(math.log10(max(positive))))
        if lo == hi:
            pad = abs(lo) * 0.1 or 1.0
            return (lo - pad, hi + pad)
        pad = (hi - lo) * 0.05
        return (lo - pad, hi + pad)

    def _auto_ylim(self):
        _, _, series = self.plotted_series()
        values = [v for _, _, ys, _ in series for v in ys]
        if not values:
            return (None, None)
        lo, hi = min(values), max(values)
        if self.axis.y_scale_var.get() == "log":
            positive = [v for v in values if v > 0]
            if not positive:
                return (None, None)
            return (10 ** math.floor(math.log10(min(positive))),
                    10 ** math.ceil(math.log10(max(positive))))
        if self.plot_type_var.get() in BAR_TYPES or self.plot_type_var.get() == "Area (filled)":
            lo = min(0.0, lo)
        if lo == hi:
            pad = abs(lo) * 0.1 or 1.0
            return (lo - pad, hi + pad)
        pad = (hi - lo) * 0.08
        return (lo - pad if lo != 0 else 0.0, hi + pad)

    # ---------------- drawing ----------------
    def redraw(self, *_):
        if self._suspend:
            return
        family = self.app.font_family.get() or DEFAULT_FONT
        base = self.app.font_size_value()
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = [family, "Helvetica", "DejaVu Sans"]
        matplotlib.rcParams["font.size"] = base

        self.ax.clear()
        labels, categorical, series = self.plotted_series()
        ptype = self.plot_type_var.get()
        horizontal = ptype == "Bar (horizontal)"

        if not series:
            self.ax.text(0.5, 0.5, "Paste data into the table to draw a plot",
                         transform=self.ax.transAxes, ha="center", va="center",
                         fontsize=base, color="gray", fontname=family)
            self.ax.set_xticks([])
            self.ax.set_yticks([])
        elif ptype in BAR_TYPES:
            self._draw_bars(series, labels, categorical, ptype, family)
        else:
            self._draw_lines(series, ptype, family)

        if series:
            if ptype in BAR_TYPES:
                self._apply_bar_axes(series, labels, categorical, horizontal)
            else:
                self.axis.apply_to_axes(self.ax, categorical_x=categorical)
                if categorical and labels:
                    positions = sorted({int(v) for _, xs, _, _ in series for v in xs})
                    self.ax.set_xticks(positions)
                    self.ax.set_xticklabels([labels[p] if p < len(labels) else ""
                                             for p in positions])

        title = self.title_var.get().strip()
        if title:
            self.ax.set_title(mathify(title), fontname=family, fontsize=base + 2, fontweight="bold")
        xl, yl = self.xlabel_var.get().strip(), self.ylabel_var.get().strip()
        if horizontal:
            xl, yl = yl, xl
        self.ax.set_xlabel(mathify(xl), fontname=family, fontsize=base)
        self.ax.set_ylabel(mathify(yl), fontname=family, fontsize=base)
        for lab in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            lab.set_fontname(family)
            lab.set_fontsize(base - 1)

        if self.grid_var.get():
            self.ax.grid(True, which="both", linestyle=":", linewidth=0.6, alpha=0.7)
        else:
            self.ax.grid(False)

        self.reflines.apply_to_axes(self.ax)

        loc = self.legend_var.get()
        if loc != "off" and self.ax.get_legend_handles_labels()[0]:
            self.ax.legend(loc=loc, fontsize=base - 1, framealpha=0.9,
                           prop={"family": family, "size": base - 1})

        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _style_of(self, state):
        linestyle = LINESTYLE_MAP.get(state["linestyle"].get(), "-")
        marker = MARKER_MAP.get(state["marker"].get(), "None")
        width = to_float(state["width"].get()) or 1.6
        size = to_float(state["size"].get()) or 5.0
        return linestyle, marker, width, size

    @staticmethod
    def _marker_fill_kwargs(fill, color, width):
        if fill == "Hollow":
            return {"markerfacecolor": "none", "markeredgecolor": color,
                    "markeredgewidth": max(1.0, width * 0.8)}
        if fill == "Hollow (white)":
            return {"markerfacecolor": "white", "markeredgecolor": color,
                    "markeredgewidth": max(1.0, width * 0.8)}
        return {}

    def _draw_lines(self, series, ptype, family):
        for name, xs, ys, state in series:
            linestyle, marker, width, size = self._style_of(state)
            if ptype == "Line only":
                marker = "None"
            elif ptype == "Scatter only":
                linestyle = "None"
                if marker == "None":
                    marker = "o"
            color = state["color"]
            fill_kw = self._marker_fill_kwargs(state["fill"].get(), color, width)

            if ptype == "Step":
                self.ax.step(xs, ys, where="post", label=name, color=color,
                             linestyle=linestyle if linestyle != "None" else "-",
                             marker=marker, markersize=size, linewidth=width, **fill_kw)
            elif ptype == "Area (filled)":
                self.ax.plot(xs, ys, label=name, color=color, linestyle=linestyle,
                             marker=marker, markersize=size, linewidth=width, **fill_kw)
                self.ax.fill_between(xs, ys, color=color, alpha=0.22)
            else:
                self.ax.plot(xs, ys, label=name, color=color, linestyle=linestyle,
                             marker=marker, markersize=size, linewidth=width, **fill_kw)

    def _draw_bars(self, series, labels, categorical, ptype, family):
        n = len(series)
        positions = sorted({v for _, xs, _, _ in series for v in xs})
        index = {p: i for i, p in enumerate(positions)}
        span = 0.8
        bw = span / max(n, 1)

        bottoms = [0.0] * len(positions)
        for si, (name, xs, ys, state) in enumerate(series):
            heights = [0.0] * len(positions)
            for x, y in zip(xs, ys):
                heights[index[x]] = y
            base_pos = list(range(len(positions)))
            hollow = state["fill"].get() != "Filled"
            face = "none" if hollow else state["color"]
            edge = state["color"] if hollow else "white"
            edge_w = 1.2 if hollow else 0.6
            if ptype == "Bar (stacked)":
                self.ax.bar(base_pos, heights, width=span, bottom=bottoms,
                            label=name, color=face,
                            edgecolor=edge, linewidth=edge_w)
                bottoms = [b + h for b, h in zip(bottoms, heights)]
            elif ptype == "Bar (horizontal)":
                offsets = [p - span / 2 + bw * (si + 0.5) for p in base_pos]
                self.ax.barh(offsets, heights, height=bw, label=name,
                             color=face, edgecolor=edge, linewidth=edge_w)
            else:
                offsets = [p - span / 2 + bw * (si + 0.5) for p in base_pos]
                self.ax.bar(offsets, heights, width=bw, label=name,
                            color=face, edgecolor=edge, linewidth=edge_w)

        ticks = list(range(len(positions)))
        tick_labels = []
        for p in positions:
            if categorical:
                tick_labels.append(labels[int(p)] if int(p) < len(labels) else "")
            else:
                tick_labels.append(fmt_num(p))
        if ptype == "Bar (horizontal)":
            self.ax.set_yticks(ticks)
            self.ax.set_yticklabels(tick_labels)
        else:
            self.ax.set_xticks(ticks)
            self.ax.set_xticklabels(tick_labels)

    def _apply_bar_axes(self, series, labels, categorical, horizontal):
        """Bars place their own category axis; only the value axis takes the
        scale/limit settings."""
        lo, hi = self._auto_ylim()
        if not self.axis.y_auto_var.get() and self.axis.custom_ylim:
            lo, hi = self.axis.custom_ylim
        else:
            self.axis.y_min_var.set(fmt_num(lo))
            self.axis.y_max_var.set(fmt_num(hi))
        scale = self.axis.y_scale_var.get()
        if horizontal:
            self.ax.set_xscale(scale)
            if lo is not None and hi is not None and lo < hi:
                self.ax.set_xlim(lo, hi)
        else:
            self.ax.set_yscale(scale)
            if lo is not None and hi is not None and lo < hi:
                self.ax.set_ylim(lo, hi)

    # ---------------- export ----------------
    def on_export_image(self):
        path = filedialog.asksaveasfilename(
            title="Export chart as image", defaultextension=".png",
            initialfile=f"{self.name}.png",
            filetypes=[("PNG image", "*.png"), ("PDF document", "*.pdf"),
                       ("SVG image", "*.svg"), ("JPEG image", "*.jpg"),
                       ("TIFF image", "*.tif"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=300, bbox_inches="tight")
            messagebox.showinfo("Export complete", f"Chart saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    def on_copy_image(self):
        """Render the chart to a PNG and place it on the Windows clipboard
        via PowerShell (no third-party dependencies required)."""
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            self.fig.savefig(tmp, dpi=300, bbox_inches="tight")
            if sys.platform.startswith("win"):
                ps = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "Add-Type -AssemblyName System.Drawing;"
                    f"$img = [System.Drawing.Image]::FromFile('{tmp}');"
                    "[System.Windows.Forms.Clipboard]::SetImage($img);"
                    "$img.Dispose();"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command", ps],
                    check=True, capture_output=True,
                )
                self.app.status_var.set("Chart copied to clipboard.")
            else:
                messagebox.showinfo(
                    "Copy to clipboard",
                    "Clipboard image copy is only implemented on Windows."
                )
        except subprocess.CalledProcessError as exc:
            messagebox.showerror(
                "Copy failed",
                (exc.stderr or b"").decode("utf-8", "replace") or str(exc)
            )
        except Exception as exc:
            messagebox.showerror("Copy failed", str(exc))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def on_export_csv(self):
        if not any(self._set_used_rows(s) for s in self.sets):
            messagebox.showwarning("Nothing to export", "All sets are empty.")
            return
        path = filedialog.asksaveasfilename(
            title="Export data as CSV", defaultextension=".csv",
            initialfile=f"{self.name}.csv",
            filetypes=[("CSV file", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                for si, s in enumerate(self.sets):
                    if si > 0:
                        writer.writerow([])
                    if len(self.sets) > 1:
                        writer.writerow([f"# {s['name']}"])
                    headers = list(s["headers"])
                    row_states = self.series_states[si] if si < len(self.series_states) else []
                    for j, state in enumerate(row_states):
                        _, y_col = _set_xy_cols(s, j)
                        if y_col < len(headers):
                            headers[y_col] = state["name"].get()
                    writer.writerow(headers)
                    n = self._set_used_rows(s)
                    for row in s["rows"][:n]:
                        writer.writerow(row)
            messagebox.showinfo("Export complete", f"Data saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))

    # ---------------- persistence ----------------
    def dump(self):
        return {
            "name": self.name,
            "plot_type": self.plot_type_var.get(),
            "title": self.title_var.get(),
            "xlabel": self.xlabel_var.get(),
            "ylabel": self.ylabel_var.get(),
            "grid": self.grid_var.get(),
            "legend": self.legend_var.get(),
            "axis": self.axis.dump(),
            "reflines": self.reflines.dump(),
            "sets": [{"name": s["name"],
                      "mode": s.get("mode", "shared"),
                      "enabled": bool(s.get("enabled", True)),
                      "headers": list(s["headers"]),
                      "rows": [list(r) for r in s["rows"][:max(self._set_used_rows(s), 1)]]}
                     for s in self.sets],
            "series": [
                [{"enabled": st["enabled"].get(), "name": st["name"].get(),
                  "color": st["color"], "linestyle": st["linestyle"].get(),
                  "marker": st["marker"].get(), "width": st["width"].get(),
                  "size": st["size"].get(), "fill": st["fill"].get()}
                 for st in row]
                for row in self.series_states
            ],
        }

    def load(self, blob):
        self._suspend = True
        try:
            self.name = blob.get("name", self.name)
            self.plot_type_var.set(blob.get("plot_type", PLOT_TYPES[0]))
            self.title_var.set(blob.get("title", self.name))
            self.xlabel_var.set(blob.get("xlabel", "X"))
            self.ylabel_var.set(blob.get("ylabel", "Y"))
            self.grid_var.set(bool(blob.get("grid", True)))
            self.legend_var.set(blob.get("legend", "best"))

            if "sets" in blob:
                raw_sets = blob["sets"]
            elif "table" in blob:
                t = blob["table"] or {}
                raw_sets = [{"name": "Set 1",
                             "headers": t.get("headers", ["X", "Series 1"]),
                             "rows": t.get("rows", [])}]
            else:
                raw_sets = [_default_set()]

            self.sets = []
            for s in raw_sets:
                headers = list(s.get("headers", ["X", "Series 1"]))
                rows = [list(r) for r in s.get("rows", [])]
                for r in rows:
                    while len(r) < len(headers):
                        r.append("")
                    del r[len(headers):]
                while len(rows) < DEFAULT_ROWS:
                    rows.append(["" for _ in headers])
                self.sets.append({"name": s.get("name", "Set"),
                                  "mode": s.get("mode", "shared"),
                                  "enabled": bool(s.get("enabled", True)),
                                  "headers": headers, "rows": rows})

            self.series_states = []
            self._sync_series_states()

            saved_series = blob.get("series", [])
            if saved_series and isinstance(saved_series[0], dict):
                saved_series = [saved_series]      # migrate old flat list
            for si, row in enumerate(self.series_states):
                saved_row = saved_series[si] if si < len(saved_series) else []
                for j, state in enumerate(row):
                    if j >= len(saved_row):
                        continue
                    saved = saved_row[j]
                    state["enabled"].set(bool(saved.get("enabled", True)))
                    state["name"].set(saved.get("name", state["name"].get()))
                    state["color"] = saved.get("color", state["color"])
                    state["linestyle"].set(saved.get("linestyle", "solid"))
                    state["marker"].set(saved.get("marker", "circle"))
                    state["width"].set(str(saved.get("width", "1.6")))
                    state["size"].set(str(saved.get("size", "5")))
                    state["fill"].set(saved.get("fill", "Filled"))

            self.axis.load(blob.get("axis", {}))
            self.reflines.load(blob.get("reflines", []))
        finally:
            self._suspend = False
        self._rebuild_series_rows()
        self._update_summary()
        self.redraw()


# --------------------------------------------------------------------------
# Application shell
# --------------------------------------------------------------------------

class PlottingToolApp:
    def __init__(self, root):
        self.root = root
        self.cases = []
        self._case_counter = 0
        self.project_path = None

        self.font_family = tk.StringVar(value=DEFAULT_FONT)
        self.font_size = tk.StringVar(value=str(DEFAULT_FONT_SIZE))
        self.font_family.trace_add("write", lambda *_: self.redraw_all())
        self.font_size.trace_add("write", lambda *_: self.redraw_all())

        root.title(APP_TITLE)
        root.geometry("1900x1080")
        root.minsize(1150, 680)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass

        self._build_toolbar()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.notebook.bind("<Double-1>", self._on_tab_double_click)

        self.add_case()

    # ---------------- toolbar ----------------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill=tk.X)

        ttk.Label(bar, text="CASES", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="New case", command=self.add_case).pack(side=tk.LEFT)
        ttk.Button(bar, text="Duplicate", command=self.duplicate_case).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bar, text="Rename", command=self.rename_case).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bar, text="Delete", command=self.delete_case).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=12)

        ttk.Label(bar, text="FONT", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Combobox(bar, textvariable=self.font_family, values=FONT_CHOICES,
                     width=16, state="normal").pack(side=tk.LEFT)
        ttk.Label(bar, text="size").pack(side=tk.LEFT, padx=(8, 2))
        ttk.Spinbox(bar, textvariable=self.font_size, from_=6, to=28, increment=1,
                    width=4).pack(side=tk.LEFT)

        ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=12)

        ttk.Label(bar, text="PROJECT", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="Open...", command=self.open_project).pack(side=tk.LEFT)
        ttk.Button(bar, text="Save", command=self.save_project_current).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bar, text="Save as...", command=self.save_project).pack(side=tk.LEFT, padx=(4, 0))

        self.status_var = tk.StringVar(value="Paste data from Excel with Ctrl+V into the table.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#666666").pack(side=tk.RIGHT)

    def font_size_value(self):
        return to_float(self.font_size.get()) or DEFAULT_FONT_SIZE

    def redraw_all(self):
        for case in self.cases:
            case.redraw()

    # ---------------- case management ----------------
    def add_case(self, name=None):
        self._case_counter += 1
        name = name or f"Case {self._case_counter}"
        case = CaseTab(self, self.notebook, name)
        self.cases.append(case)
        self.notebook.add(case.frame, text=name)
        self.notebook.select(case.frame)
        return case

    def current_case(self):
        current = self.notebook.select()
        for case in self.cases:
            if str(case.frame) == current:
                return case
        return None

    def duplicate_case(self):
        case = self.current_case()
        if not case:
            return
        blob = case.dump()
        new_case = self.add_case(f"{case.name} copy")
        blob["name"] = new_case.name
        blob["title"] = case.title_var.get()
        while len(new_case.grid.headers) < len(blob["table"]["headers"]):
            new_case.grid.add_series_column()
        new_case.load(blob)
        self.notebook.tab(new_case.frame, text=new_case.name)

    def rename_case(self):
        case = self.current_case()
        if not case:
            return
        dialog = TextPromptDialog(self.root, "Rename case", "Case name:", case.name)
        if not dialog.result:
            return
        case.name = dialog.result
        self.notebook.tab(case.frame, text=case.name)
        if not case.title_var.get().strip() or case.title_var.get().startswith("Case "):
            case.title_var.set(case.name)

    def delete_case(self):
        case = self.current_case()
        if not case:
            return
        if len(self.cases) == 1:
            messagebox.showinfo("Keep one case", "At least one case has to stay open.")
            return
        if not messagebox.askyesno("Delete case", f"Delete '{case.name}' and its data?"):
            return
        self.notebook.forget(case.frame)
        case.frame.destroy()
        self.cases.remove(case)

    def _on_tab_double_click(self, event):
        if self.notebook.identify(event.x, event.y) == "label":
            self.rename_case()

    # ---------------- project save / load ----------------
    def save_project_current(self):
        """Save to the current project file if there is one; otherwise fall
        back to the Save-As dialog."""
        if self.project_path:
            self._write_project(str(self.project_path))
        else:
            self.save_project()

    def save_project(self):
        path = filedialog.asksaveasfilename(
            title="Save project", defaultextension=PROJECT_EXT,
            initialfile=self.project_path.name if self.project_path else f"plots{PROJECT_EXT}",
            filetypes=[("Plotting Tool project", f"*{PROJECT_EXT}"),
                       ("JSON file", "*.json"), ("All files", "*.*")])
        if not path:
            return
        self._write_project(path)

    def _write_project(self, path):
        blob = {
            "version": 1,
            "font": {"family": self.font_family.get(), "size": self.font_size.get()},
            "cases": [case.dump() for case in self.cases],
        }
        try:
            Path(path).write_text(json.dumps(blob, indent=2), encoding="utf-8")
            self.project_path = Path(path)
            self.root.title(f"{APP_TITLE} - {self.project_path.name}")
            self.status_var.set(f"Saved to {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    def open_project(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open project",
                filetypes=[("Plotting Tool project", f"*{PROJECT_EXT}"),
                           ("JSON file", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            blob = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return

        for case in list(self.cases):
            self.notebook.forget(case.frame)
            case.frame.destroy()
        self.cases.clear()
        self._case_counter = 0

        font = blob.get("font", {})
        self.font_family.set(font.get("family", DEFAULT_FONT))
        self.font_size.set(str(font.get("size", DEFAULT_FONT_SIZE)))

        for case_blob in blob.get("cases", []) or [{}]:
            case = self.add_case(case_blob.get("name"))
            case.load(case_blob)
            self.notebook.tab(case.frame, text=case.name)

        if not self.cases:
            self.add_case()
        self.project_path = Path(path)
        self.root.title(f"{APP_TITLE} - {self.project_path.name}")
        self.status_var.set(f"Loaded {self.project_path.name}")


class TextPromptDialog(tk.Toplevel):
    """Tiny modal one-line text prompt (used for renaming cases)."""

    def __init__(self, parent, title, label, initial=""):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=label).pack(anchor="w")
        self.var = tk.StringVar(value=initial)
        entry = ttk.Entry(frame, textvariable=self.var, width=32)
        entry.pack(fill=tk.X, pady=(4, 10))
        entry.select_range(0, "end")

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="OK", command=self._ok).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 6))

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        entry.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        text = self.var.get().strip()
        if text:
            self.result = text
        self.destroy()


def main():
    root = tk.Tk()
    app = PlottingToolApp(root)
    if len(sys.argv) > 1:
        app.open_project(sys.argv[1])
    root.mainloop()


if __name__ == "__main__":
    main()
