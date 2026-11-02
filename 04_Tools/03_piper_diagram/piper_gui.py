"""
Tkinter GUI for the Piper diagram generator with a live-updating preview.

- Pick the input .xlsx (Script Input sheet), the output plot file, and the
  output register (CSV + XLSX) locations.
- Load samples and edit per-sample marker, colour and size.
- Set an extra rotation offset applied to every axis label.
- The embedded matplotlib canvas re-renders whenever any option changes.
- Generate: writes the plot + register to the chosen paths.
"""

import json
import os
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

import piper_diagram as pd_mod


MARKER_CHOICES = ["o", "s", "^", "D", "v", "P", "X", "*", "<", ">", "h", "p"]


class PiperGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Piper Diagram Generator")
        self.geometry("1400x820")

        base_dir = pd_mod.OUT_DIR
        default_wb = pd_mod.WORKBOOK if os.path.exists(pd_mod.WORKBOOK) else ""

        self.input_var = tk.StringVar(value=default_wb)
        self.plot_var = tk.StringVar(value=os.path.join(base_dir, "Molyhil_Piper_Diagram.png"))
        self.csv_var = tk.StringVar(value=os.path.join(base_dir, "Molyhil_Piper_Register.csv"))
        self.xlsx_var = tk.StringVar(value=os.path.join(base_dir, "Molyhil_Piper_Register.xlsx"))
        self.rotation_var = tk.DoubleVar(value=0.0)
        self.rotation_mode_var = tk.StringVar(value="along")
        self.gap_var = tk.DoubleVar(value=30.0)
        self.facies_var = tk.BooleanVar(value=True)
        self.title_var = tk.StringVar(value=pd_mod.DEFAULT_TITLE)

        self.sample_rows = {}   # name -> dict(marker_var, color_var, size_var, swatch)
        self.results = None
        self._pending_redraw = None

        # Layout: left = controls, right = live preview.
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(10, 4), pady=10)
        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=(4, 10), pady=10)

        self._build_paths_frame(left)
        self._build_options_frame(left)
        self._build_samples_frame(left)
        self._build_actions_frame(left)
        self._build_preview_frame(right)

    # ---- layout ----
    def _build_paths_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Files")
        f.pack(fill="x", pady=(0, 6))
        self._path_row(f, "Input .xlsx:", self.input_var, self._pick_input, 0)
        self._path_row(f, "Plot output:", self.plot_var, self._pick_plot, 1)
        self._path_row(f, "Register CSV:", self.csv_var, self._pick_csv, 2)
        self._path_row(f, "Register XLSX:", self.xlsx_var, self._pick_xlsx, 3)
        f.columnconfigure(1, weight=1)

    def _path_row(self, parent, label, var, cmd, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=3)
        e = ttk.Entry(parent, textvariable=var, width=42)
        e.grid(row=row, column=1, sticky="ew", padx=6, pady=3)
        ttk.Button(parent, text="Browse...", command=cmd).grid(row=row, column=2, padx=6, pady=3)

    def _build_options_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Plot options")
        f.pack(fill="x", pady=6)
        ttk.Label(f, text="Axis label rotation:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        mode_cb = ttk.Combobox(f, textvariable=self.rotation_mode_var,
                               values=["along", "horizontal"], width=12, state="readonly")
        mode_cb.grid(row=0, column=1, sticky="w", padx=6)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_redraw())
        ttk.Label(f, text="Fine offset (deg):").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Scale(f, from_=-45, to=45, orient="horizontal", variable=self.rotation_var,
                  length=220, command=self._on_rotation).grid(row=1, column=1, sticky="w")
        self.rot_lbl = ttk.Label(f, text="+0")
        self.rot_lbl.grid(row=1, column=2, sticky="w", padx=6)
        ttk.Label(f, text="Triangle gap (units):").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Scale(f, from_=0, to=80, orient="horizontal", variable=self.gap_var,
                  length=220, command=self._on_gap).grid(row=2, column=1, sticky="w")
        self.gap_lbl = ttk.Label(f, text="30")
        self.gap_lbl.grid(row=2, column=2, sticky="w", padx=6)
        ttk.Checkbutton(f, text="Show facies zones (background tint)",
                        variable=self.facies_var,
                        command=self._schedule_redraw).grid(row=3, column=0,
                                                            columnspan=3, sticky="w",
                                                            padx=6, pady=(4, 2))
        ttk.Label(f, text="Plot title (use \\n for a line break):").grid(
            row=4, column=0, sticky="w", padx=6, pady=(4, 2))
        te = ttk.Entry(f, textvariable=self.title_var, width=52)
        te.grid(row=4, column=1, columnspan=2, sticky="ew", padx=6, pady=(4, 2))
        self.title_var.trace_add("write", lambda *_: self._schedule_redraw())

    def _build_samples_frame(self, parent):
        outer = ttk.LabelFrame(parent, text="Samples (Load to populate)")
        outer.pack(fill="both", expand=True, pady=6)

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(4, 4))
        ttk.Button(top, text="Load samples from input", command=self._load_samples).pack(side="left", padx=6)

        header = ttk.Frame(outer)
        header.pack(fill="x", padx=6)
        for i, (t, w) in enumerate([("Sample (rename)", 22), ("Marker", 8),
                                    ("Colour", 10), ("Size", 7), ("Fill", 4),
                                    ("Order", 6)]):
            ttk.Label(header, text=t, width=w, anchor="w").grid(row=0, column=i, padx=4, sticky="w")

        canvas = tk.Canvas(outer, highlightthickness=0, width=470)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        scroll.pack(side="right", fill="y")
        self.rows_frame = ttk.Frame(canvas)
        self.rows_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")

    def _build_actions_frame(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=(4, 0))
        ttk.Button(f, text="Save plot + register", command=self._generate).pack(side="right")
        ttk.Button(f, text="Plot", command=self._plot_only).pack(side="right", padx=(0, 6))
        self.status = ttk.Label(f, text="", foreground="#155")
        self.status.pack(side="left")

        f2 = ttk.Frame(parent)
        f2.pack(fill="x", pady=(4, 0))
        ttk.Button(f2, text="Save project...", command=self._save_project).pack(side="left")
        ttk.Button(f2, text="Load project...", command=self._load_project).pack(side="left", padx=(6, 0))
        ttk.Button(f2, text="Apply renames to input .xlsx",
                   command=self._apply_renames_to_xlsx).pack(side="right")

    def _build_preview_frame(self, parent):
        f = ttk.LabelFrame(parent, text="Live preview")
        f.pack(fill="both", expand=True)
        self.fig = Figure(figsize=(8.5, 7.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_axis_off()
        self.ax.text(0.5, 0.5, "Load samples to preview", ha="center", va="center",
                     transform=self.ax.transAxes, color="#888")
        self.canvas = FigureCanvasTkAgg(self.fig, master=f)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(self.canvas, f)

    # ---- file pickers ----
    def _pick_input(self):
        p = filedialog.askopenfilename(title="Select input workbook",
                                       filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*.*")])
        if p:
            self.input_var.set(p)

    def _pick_plot(self):
        p = filedialog.asksaveasfilename(title="Save plot as", defaultextension=".png",
                                         filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"),
                                                    ("SVG", "*.svg"), ("All", "*.*")])
        if p:
            self.plot_var.set(p)

    def _pick_csv(self):
        p = filedialog.asksaveasfilename(title="Save register CSV as", defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if p:
            self.csv_var.set(p)

    def _pick_xlsx(self):
        p = filedialog.asksaveasfilename(title="Save register XLSX as", defaultextension=".xlsx",
                                         filetypes=[("Excel", "*.xlsx"), ("All", "*.*")])
        if p:
            self.xlsx_var.set(p)

    # ---- samples ----
    def _load_samples(self):
        path = self.input_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("Missing input", "Pick a valid input .xlsx first.")
            return
        try:
            samples = pd_mod.read_samples(workbook=path)
            self.results = pd_mod.compute(samples)
        except Exception as e:
            messagebox.showerror("Read failed", f"{e}")
            return

        # Preserve any existing per-sample state for samples that reappear.
        old = self.sample_rows
        self.sample_rows = {}
        for i, name in enumerate(samples):
            prev = old.get(name)
            if prev:
                state = {k: prev[k].get() for k in ("name", "marker", "color", "size", "filled")}
            else:
                state = dict(name=name,
                             marker=pd_mod.DEFAULT_MARKERS[i % len(pd_mod.DEFAULT_MARKERS)],
                             color=pd_mod.DEFAULT_COLOURS[i % len(pd_mod.DEFAULT_COLOURS)],
                             size=110.0, filled=True)
            self.sample_rows[name] = self._make_row_vars(state)

        self._rebuild_rows()
        self.status.config(text=f"Loaded {len(samples)} samples.")
        self._redraw_preview()

    def _make_row_vars(self, state):
        """Create Tk vars for a sample row from a plain-dict state snapshot."""
        n_var = tk.StringVar(value=state["name"])
        m_var = tk.StringVar(value=state["marker"])
        c_var = tk.StringVar(value=state["color"])
        s_var = tk.DoubleVar(value=state["size"])
        f_var = tk.BooleanVar(value=state["filled"])
        n_var.trace_add("write", lambda *_: self._schedule_redraw())
        s_var.trace_add("write", lambda *_: self._schedule_redraw())
        return dict(name=n_var, marker=m_var, color=c_var, size=s_var,
                    filled=f_var, swatch=None)

    def _rebuild_rows(self):
        """Redraw all sample rows in current dict order (reorder-safe)."""
        for child in self.rows_frame.winfo_children():
            child.destroy()
        keys = list(self.sample_rows.keys())
        n = len(keys)
        for i, orig in enumerate(keys):
            r = self.sample_rows[orig]
            row = ttk.Frame(self.rows_frame)
            row.grid(row=i, column=0, sticky="ew", pady=2)

            ttk.Entry(row, textvariable=r["name"], width=22).grid(row=0, column=0, padx=4, sticky="w")

            cb = ttk.Combobox(row, textvariable=r["marker"], values=MARKER_CHOICES,
                              width=5, state="readonly")
            cb.grid(row=0, column=1, padx=4)
            cb.bind("<<ComboboxSelected>>", lambda e: self._schedule_redraw())

            swatch = tk.Label(row, text="   ", background=r["color"].get(),
                              relief="ridge", width=4)
            swatch.grid(row=0, column=2, padx=(4, 2))
            r["swatch"] = swatch
            ttk.Button(row, text="Pick", width=5,
                       command=lambda k=orig: self._pick_colour(k)).grid(row=0, column=3, padx=(0, 4))

            ttk.Spinbox(row, from_=10, to=600, increment=10, textvariable=r["size"],
                        width=7, command=self._schedule_redraw).grid(row=0, column=4, padx=4)

            ttk.Checkbutton(row, variable=r["filled"],
                            command=self._schedule_redraw).grid(row=0, column=5, padx=4)

            up = ttk.Button(row, text="↑", width=2,
                            command=lambda k=orig: self._move_sample(k, -1))
            up.grid(row=0, column=6, padx=(4, 1))
            if i == 0:
                up.state(["disabled"])
            dn = ttk.Button(row, text="↓", width=2,
                            command=lambda k=orig: self._move_sample(k, +1))
            dn.grid(row=0, column=7, padx=(1, 4))
            if i == n - 1:
                dn.state(["disabled"])

    def _move_sample(self, orig, delta):
        keys = list(self.sample_rows.keys())
        if orig not in keys:
            return
        i = keys.index(orig)
        j = i + delta
        if not (0 <= j < len(keys)):
            return
        keys[i], keys[j] = keys[j], keys[i]
        self.sample_rows = {k: self.sample_rows[k] for k in keys}
        self._rebuild_rows()
        self._schedule_redraw()

    def _pick_colour(self, name):
        row = self.sample_rows[name]
        current = row["color"].get()
        rgb, hexval = colorchooser.askcolor(color=current, title=f"Colour for {name}")
        if hexval:
            row["color"].set(hexval)
            row["swatch"].configure(background=hexval)
            self._schedule_redraw()

    # ---- live preview ----
    def _on_rotation(self, v):
        self.rot_lbl.config(text=f"{float(v):+.0f}")
        self._schedule_redraw()

    def _on_gap(self, v):
        self.gap_lbl.config(text=f"{float(v):.0f}")
        self._schedule_redraw()

    def _schedule_redraw(self):
        # debounce so scale drags don't fire re-renders per pixel.
        if self._pending_redraw is not None:
            self.after_cancel(self._pending_redraw)
        self._pending_redraw = self.after(80, self._redraw_preview)

    def _current_styles(self):
        """Styles keyed by the CURRENT display name (user-editable)."""
        styles = {}
        for orig, r in self.sample_rows.items():
            try:
                size = float(r["size"].get())
            except (tk.TclError, ValueError):
                size = 110.0
            display = r["name"].get().strip() or orig
            styles[display] = dict(marker=r["marker"].get(),
                                   color=r["color"].get(), size=size,
                                   filled=bool(r["filled"].get()))
        return styles

    def _renamed_results(self):
        """results dict remapped so keys are the user's display names, in the
        user's chosen sample order (from the reordered sample_rows dict)."""
        if not self.results:
            return {}
        out = {}
        for orig in self.sample_rows:
            if orig not in self.results:
                continue
            display = self.sample_rows[orig]["name"].get().strip() or orig
            out[display] = self.results[orig]
        # Include any results whose row hasn't been built (safety fallback).
        for orig in self.results:
            if orig not in self.sample_rows:
                out[orig] = self.results[orig]
        return out

    def _redraw_preview(self):
        self._pending_redraw = None
        if not self.results:
            return
        try:
            pd_mod.render_axes(self.ax, self._renamed_results(),
                               styles=self._current_styles(),
                               axis_label_rotation_offset=float(self.rotation_var.get()),
                        rotation_mode=self.rotation_mode_var.get(),
                        gap=float(self.gap_var.get()),
                        show_facies=bool(self.facies_var.get()),
                        title=self.title_var.get().replace("\\n", "\n"))
            self.fig.tight_layout()
            self.canvas.draw_idle()
        except Exception as e:
            traceback.print_exc()
            self.status.config(text=f"Preview error: {e}")

    def _plot_only(self):
        """Refresh the live preview from the current input + settings without
        writing any output files."""
        if not self.results:
            path = self.input_var.get().strip()
            if not path or not os.path.exists(path):
                messagebox.showerror("Missing input", "Pick a valid input .xlsx first.")
                return
            try:
                samples = pd_mod.read_samples(workbook=path)
                self.results = pd_mod.compute(samples)
                if not self.sample_rows:
                    self._load_samples()
            except Exception as e:
                messagebox.showerror("Read failed", f"{e}")
                return
        self._redraw_preview()
        self.status.config(text="Preview refreshed (not saved).")

    # ---- generate ----
    def _generate(self):
        in_path = self.input_var.get().strip()
        plot_path = self.plot_var.get().strip()
        csv_path = self.csv_var.get().strip()
        xlsx_path = self.xlsx_var.get().strip()
        if not (in_path and plot_path and csv_path and xlsx_path):
            messagebox.showerror("Missing paths", "Fill in all file paths.")
            return
        if not os.path.exists(in_path):
            messagebox.showerror("Input not found", in_path)
            return

        try:
            if not self.results:
                self._load_samples()
            for p in (plot_path, csv_path, xlsx_path):
                d = os.path.dirname(p)
                if d and not os.path.exists(d):
                    os.makedirs(d, exist_ok=True)
            renamed = self._renamed_results()
            pd_mod.export_register(renamed, csv_path=csv_path, xlsx_path=xlsx_path)
            pd_mod.draw(renamed, plot_path, styles=self._current_styles(),
                        axis_label_rotation_offset=float(self.rotation_var.get()),
                        rotation_mode=self.rotation_mode_var.get(),
                        gap=float(self.gap_var.get()),
                        show_facies=bool(self.facies_var.get()),
                        title=self.title_var.get().replace("\\n", "\n"))
            self.status.config(text=f"Saved: {plot_path}")
            messagebox.showinfo("Done", f"Plot: {plot_path}\nCSV: {csv_path}\nXLSX: {xlsx_path}")
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Generation failed", f"{e}")


    # ---- project save/load + xlsx rename ----
    def _apply_renames_to_xlsx(self):
        """Rewrite the header row of the input .xlsx so that user-entered names
        replace the original sample column headers."""
        path = self.input_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("No input", "Pick a valid input .xlsx first.")
            return
        rename_map = {}
        for orig, r in self.sample_rows.items():
            new = r["name"].get().strip()
            if new and new != orig:
                rename_map[orig] = new
        if not rename_map:
            messagebox.showinfo("Nothing to rename", "No sample names were changed.")
            return
        if not messagebox.askyesno("Confirm rewrite",
                                   f"Rewrite {len(rename_map)} column header(s) in\n{path}\n\n"
                                   "The original file will be modified in place."):
            return
        try:
            from openpyxl import load_workbook
            wb = load_workbook(path)
            ws = wb[pd_mod.INPUT_SHEET]
            renamed_orig = set()
            for cell in ws[1]:
                if cell.value in rename_map:
                    orig = cell.value
                    cell.value = rename_map[orig]
                    renamed_orig.add(orig)
            wb.save(path)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Rewrite failed", f"{e}")
            return
        # Re-key sample_rows so subsequent edits use the new keys.
        new_rows = {}
        for orig, r in self.sample_rows.items():
            new_key = rename_map.get(orig, orig)
            new_rows[new_key] = r
        self.sample_rows = new_rows
        # results dict is keyed by orig too - re-key.
        if self.results:
            self.results = {rename_map.get(k, k): v for k, v in self.results.items()}
        self._rebuild_rows()
        self._redraw_preview()
        self.status.config(text=f"Renamed {len(renamed_orig)} column(s) in xlsx.")

    def _project_state(self):
        return {
            "input": self.input_var.get(),
            "plot": self.plot_var.get(),
            "csv": self.csv_var.get(),
            "xlsx": self.xlsx_var.get(),
            "gap": float(self.gap_var.get()),
            "rotation_mode": self.rotation_mode_var.get(),
            "rotation_offset": float(self.rotation_var.get()),
            "facies": bool(self.facies_var.get()),
            "title": self.title_var.get(),
            "samples": [
                {
                    "orig": orig,
                    "name": r["name"].get(),
                    "marker": r["marker"].get(),
                    "color": r["color"].get(),
                    "size": float(r["size"].get()),
                    "filled": bool(r["filled"].get()),
                }
                for orig, r in self.sample_rows.items()
            ],
        }

    def _save_project(self):
        p = filedialog.asksaveasfilename(title="Save project as",
                                         defaultextension=".piper.json",
                                         filetypes=[("Piper project", "*.piper.json"),
                                                    ("JSON", "*.json"), ("All", "*.*")])
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._project_state(), f, indent=2)
            self.status.config(text=f"Project saved: {p}")
        except Exception as e:
            messagebox.showerror("Save failed", f"{e}")

    def _load_project(self):
        p = filedialog.askopenfilename(title="Load project",
                                       filetypes=[("Piper project", "*.piper.json"),
                                                  ("JSON", "*.json"), ("All", "*.*")])
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            messagebox.showerror("Load failed", f"{e}")
            return
        # Apply file paths + options.
        self.input_var.set(state.get("input", ""))
        self.plot_var.set(state.get("plot", ""))
        self.csv_var.set(state.get("csv", ""))
        self.xlsx_var.set(state.get("xlsx", ""))
        self.gap_var.set(state.get("gap", 30.0))
        self.gap_lbl.config(text=f"{self.gap_var.get():.0f}")
        self.rotation_mode_var.set(state.get("rotation_mode", "along"))
        self.rotation_var.set(state.get("rotation_offset", 0.0))
        self.rot_lbl.config(text=f"{self.rotation_var.get():+.0f}")
        self.facies_var.set(state.get("facies", True))
        self.title_var.set(state.get("title", pd_mod.DEFAULT_TITLE))
        # Reload samples from the (possibly new) input path, then overlay saved
        # per-sample state in the saved order.
        if self.input_var.get() and os.path.exists(self.input_var.get()):
            try:
                samples = pd_mod.read_samples(workbook=self.input_var.get())
                self.results = pd_mod.compute(samples)
            except Exception as e:
                messagebox.showerror("Sample read failed", f"{e}")
                return
        saved = {s["orig"]: s for s in state.get("samples", [])}
        # Build sample_rows in saved order (fall back to XLSX order for extras).
        ordered = [s["orig"] for s in state.get("samples", []) if s["orig"] in (self.results or {})]
        for orig in (self.results or {}):
            if orig not in ordered:
                ordered.append(orig)
        self.sample_rows = {}
        for i, orig in enumerate(ordered):
            s = saved.get(orig, {})
            self.sample_rows[orig] = self._make_row_vars(dict(
                name=s.get("name", orig),
                marker=s.get("marker", pd_mod.DEFAULT_MARKERS[i % len(pd_mod.DEFAULT_MARKERS)]),
                color=s.get("color", pd_mod.DEFAULT_COLOURS[i % len(pd_mod.DEFAULT_COLOURS)]),
                size=s.get("size", 110.0),
                filled=s.get("filled", True),
            ))
        self._rebuild_rows()
        self._redraw_preview()
        self.status.config(text=f"Project loaded: {p}")


if __name__ == "__main__":
    PiperGUI().mainloop()
