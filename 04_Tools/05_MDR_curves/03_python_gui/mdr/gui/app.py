"""Tkinter MDR curves GUI.

Single window with a ttk.Notebook of seven tabs mirroring the pipeline stages.
State is held on the App instance so tabs share the loaded stations, fit
results, etc. Long-running work runs in a daemon thread and communicates back
via a queue polled by the Tk main loop.
"""

from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, Tk, StringVar, Toplevel, filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..curve_fit import FitResult, fit_mdr_curve  # noqa: E402
from ..design import critical_duration, design_p_pe_q, design_rainfall  # noqa: E402
from ..double_mass import DoubleMassResult, run_double_mass  # noqa: E402
from ..infill import InfillResult, infill  # noqa: E402
from ..io_bom import Station, coverage_summary, read_bom_csv  # noqa: E402
from ..mdr_build import MDRResult, build_mdr  # noqa: E402
from ..plotting import design_curves_figure, double_mass_figure, observed_vs_predicted_figure  # noqa: E402
from ..report import (  # noqa: E402
    write_stage1_ypp,
    write_stage2_double_mass,
    write_stage3_infill,
    write_stage4_mdr,
)

DEFAULT_DURATIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40,
                     45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150]
DEFAULT_ARIS = [2, 5, 10, 20, 50, 100, 200, 500, 1000]


@dataclass
class PipelineState:
    station_a: Station | None = None
    station_b: Station | None = None
    output_dir: Path | None = None
    dm_result: DoubleMassResult | None = None
    infill_result: InfillResult | None = None
    correction_override: float | None = None
    mdr_result: MDRResult | None = None
    fit_result: FitResult | None = None
    plot_aris: list[float] = field(default_factory=lambda: list(DEFAULT_ARIS))
    plot_max_duration: float = 150.0
    p1_on_p24: float = 0.4


class App:
    def __init__(self, root: Tk):
        self.root = root
        root.title("MDR Curves — Python")
        root.geometry("1100x760")

        self.state = PipelineState()
        self.log_queue: queue.Queue[str] = queue.Queue()

        nb = ttk.Notebook(root)
        nb.pack(fill=BOTH, expand=True)

        self.tab_inputs = ttk.Frame(nb)
        self.tab_dm = ttk.Frame(nb)
        self.tab_infill = ttk.Frame(nb)
        self.tab_mdr = ttk.Frame(nb)
        self.tab_fit = ttk.Frame(nb)
        self.tab_design = ttk.Frame(nb)
        self.tab_plot = ttk.Frame(nb)

        nb.add(self.tab_inputs, text="1. Inputs")
        nb.add(self.tab_dm, text="2. Double Mass")
        nb.add(self.tab_infill, text="3. Infill")
        nb.add(self.tab_mdr, text="4. MDR Extraction")
        nb.add(self.tab_fit, text="5. Curve Fit")
        nb.add(self.tab_design, text="6. Design Query")
        nb.add(self.tab_plot, text="7. Plot & Export")

        self._build_inputs_tab()
        self._build_dm_tab()
        self._build_infill_tab()
        self._build_mdr_tab()
        self._build_fit_tab()
        self._build_design_tab()
        self._build_plot_tab()

        self.status = StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x")

        self._poll_log()

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        self.log_queue.put(msg)

    def _poll_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.status.set(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _run_bg(self, func, on_done):
        """Run `func` in a daemon thread; call `on_done(result_or_exc)` in Tk thread."""

        def worker():
            try:
                result = func()
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                self.root.after(0, lambda: on_done((e, tb)))
            else:
                self.root.after(0, lambda: on_done(result))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ Tab 1: Inputs
    def _build_inputs_tab(self):
        f = self.tab_inputs
        self.path_a = StringVar()
        self.path_b = StringVar()
        self.label_a = StringVar(value="Station A")
        self.label_b = StringVar(value="Station B")
        self.year_start = StringVar()
        self.year_end = StringVar()
        self.out_dir = StringVar()

        grid = ttk.Frame(f, padding=12)
        grid.pack(fill=BOTH, expand=False)

        def _row(r, label, var, browse=None):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="e", padx=4, pady=3)
            ttk.Entry(grid, textvariable=var, width=70).grid(row=r, column=1, sticky="we", padx=4)
            if browse:
                ttk.Button(grid, text="Browse…", command=browse).grid(row=r, column=2, padx=4)

        _row(0, "Station A CSV:", self.path_a, lambda: self._pick_csv(self.path_a, self.label_a))
        _row(1, "Label A:", self.label_a)
        _row(2, "Station B CSV (optional):", self.path_b, lambda: self._pick_csv(self.path_b, self.label_b))
        _row(3, "Label B:", self.label_b)
        _row(4, "Start year:", self.year_start)
        _row(5, "End year:", self.year_end)
        _row(6, "Output directory:", self.out_dir, self._pick_out_dir)

        grid.columnconfigure(1, weight=1)

        ttk.Button(f, text="Load stations", command=self._load_stations).pack(pady=6)

        self.inputs_summary = ttk.Treeview(
            f,
            columns=("code", "years", "days_present", "days_total", "pct"),
            show="headings",
            height=6,
        )
        for c, w in zip(
            ("code", "years", "days_present", "days_total", "pct"),
            (140, 160, 120, 120, 120),
        ):
            self.inputs_summary.heading(c, text=c)
            self.inputs_summary.column(c, width=w, anchor="center")
        self.inputs_summary.pack(fill=BOTH, expand=True, padx=12, pady=6)

    def _pick_csv(self, target: StringVar, label_var: StringVar):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if p:
            target.set(p)
            stem = Path(p).stem
            if label_var.get() in ("Station A", "Station B"):
                label_var.set(stem)

    def _pick_out_dir(self):
        p = filedialog.askdirectory()
        if p:
            self.out_dir.set(p)

    def _load_stations(self):
        try:
            a = read_bom_csv(self.path_a.get(), label=self.label_a.get())
            b = read_bom_csv(self.path_b.get(), label=self.label_b.get()) if self.path_b.get() else None
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        if self.year_start.get() and self.year_end.get():
            ys, ye = int(self.year_start.get()), int(self.year_end.get())
            a = a.clip_years(ys, ye)
            if b is not None:
                b = b.clip_years(ys, ye)
        else:
            self.year_start.set(str(a.start_year))
            self.year_end.set(str(a.end_year))

        self.state.station_a = a
        self.state.station_b = b
        self.state.output_dir = Path(self.out_dir.get()) if self.out_dir.get() else None

        for row in self.inputs_summary.get_children():
            self.inputs_summary.delete(row)
        for st in filter(None, (a, b)):
            cov = coverage_summary(st)
            pct = 100 * cov["present"].sum() / max(cov["days"].sum(), 1)
            self.inputs_summary.insert(
                "",
                END,
                values=(
                    st.code,
                    f"{st.start_year}–{st.end_year}",
                    int(cov["present"].sum()),
                    int(cov["days"].sum()),
                    f"{pct:.1f} %",
                ),
            )
        self.log(f"Loaded station A ({a.code}); B = {b.code if b else 'none'}")

    # ------------------------------------------------------------------ Tab 2: Double Mass
    def _build_dm_tab(self):
        f = self.tab_dm
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="Run double-mass check", command=self._run_dm).pack(side=LEFT)
        self.dm_summary = StringVar(value="(load two stations first)")
        ttk.Label(top, textvariable=self.dm_summary).pack(side=LEFT, padx=12)

        self.dm_canvas_frame = ttk.Frame(f)
        self.dm_canvas_frame.pack(fill=BOTH, expand=True)
        self.dm_canvas = None

        override = ttk.Frame(f, padding=8)
        override.pack(fill="x")
        ttk.Label(override, text="Override correction factor:").pack(side=LEFT)
        self.dm_override = StringVar()
        ttk.Entry(override, textvariable=self.dm_override, width=12).pack(side=LEFT, padx=4)
        ttk.Button(override, text="Apply override", command=self._apply_dm_override).pack(side=LEFT, padx=4)

    def _run_dm(self):
        if not (self.state.station_a and self.state.station_b):
            messagebox.showwarning("Missing input", "Load both stations on tab 1 first.")
            return
        try:
            r = run_double_mass(self.state.station_a, self.state.station_b)
        except Exception as e:
            messagebox.showerror("Double-mass failed", str(e))
            return
        self.state.dm_result = r
        self.state.correction_override = None
        self.dm_summary.set(
            f"correction (B→A) = {r.correction_b_to_a:.4f}   r = {r.r:.5f}   N = {r.n_common_days} days"
        )
        self._show_dm_figure(r)
        self.log("Double-mass done.")

    def _apply_dm_override(self):
        try:
            v = float(self.dm_override.get())
        except ValueError:
            messagebox.showerror("Invalid", "Enter a numeric correction factor.")
            return
        self.state.correction_override = v
        self.dm_summary.set(f"override applied: correction = {v:.4f}")

    def _show_dm_figure(self, r: DoubleMassResult):
        for w in self.dm_canvas_frame.winfo_children():
            w.destroy()
        fig = double_mass_figure(
            r.common,
            r.correction_b_to_a,
            self.state.station_a.label if self.state.station_a else "A",
            self.state.station_b.label if self.state.station_b else "B",
        )
        canvas = FigureCanvasTkAgg(fig, master=self.dm_canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        self.dm_canvas = canvas

    # ------------------------------------------------------------------ Tab 3: Infill
    def _build_infill_tab(self):
        f = self.tab_infill
        ttk.Button(f, text="Build composite", command=self._run_infill).pack(anchor="w", padx=8, pady=6)
        self.infill_summary = StringVar(value="")
        ttk.Label(f, textvariable=self.infill_summary).pack(anchor="w", padx=8)
        self.infill_tree = ttk.Treeview(
            f,
            columns=("year", "present", "days", "pct"),
            show="headings",
            height=25,
        )
        for c, w in zip(("year", "present", "days", "pct"), (100, 120, 120, 120)):
            self.infill_tree.heading(c, text=c)
            self.infill_tree.column(c, width=w, anchor="center")
        self.infill_tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

    def _run_infill(self):
        if not self.state.station_a:
            messagebox.showwarning("Missing input", "Load station A first.")
            return
        if self.state.station_b is None:
            # No B — composite is just A.
            result = InfillResult(self.state.station_a, int(self.state.station_a.rain.notna().sum()), 0,
                                  int(self.state.station_a.rain.isna().sum()))
        else:
            corr = self.state.correction_override
            if corr is None and self.state.dm_result is not None:
                corr = self.state.dm_result.correction_b_to_a
            if corr is None:
                messagebox.showwarning("No correction factor", "Run tab 2 first or enter an override.")
                return
            result = infill(self.state.station_a, self.state.station_b, corr, label="Composite")
        self.state.infill_result = result
        self.infill_summary.set(
            f"days from A = {result.days_from_a}   from B = {result.days_from_b}   still missing = {result.days_still_missing}"
        )
        for row in self.infill_tree.get_children():
            self.infill_tree.delete(row)
        cov = coverage_summary(result.composite)
        for _, r in cov.iterrows():
            self.infill_tree.insert(
                "",
                END,
                values=(int(r["year"]), int(r["present"]), int(r["days"]), f"{r['pct_complete']:.1f} %"),
            )
        self.log("Infill / composite built.")

    # ------------------------------------------------------------------ Tab 4: MDR Extraction
    def _build_mdr_tab(self):
        f = self.tab_mdr
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Durations (space-separated days):").grid(row=0, column=0, sticky="e")
        self.dur_str = StringVar(value=" ".join(str(d) for d in DEFAULT_DURATIONS))
        ttk.Entry(top, textvariable=self.dur_str, width=80).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(top, text="Events per year:").grid(row=1, column=0, sticky="e")
        self.epy = StringVar(value="1.0")
        ttk.Entry(top, textvariable=self.epy, width=10).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(top, text="Depth adjustment:").grid(row=2, column=0, sticky="e")
        self.depth_adj = StringVar(value="1.0")
        ttk.Entry(top, textvariable=self.depth_adj, width=10).grid(row=2, column=1, sticky="w", padx=4)
        top.columnconfigure(1, weight=1)

        btns = ttk.Frame(f, padding=4)
        btns.pack(fill="x")
        self.mdr_run_btn = ttk.Button(btns, text="Run extraction", command=self._run_mdr)
        self.mdr_run_btn.pack(side=LEFT)
        self.mdr_status = StringVar(value="")
        ttk.Label(btns, textvariable=self.mdr_status).pack(side=LEFT, padx=12)

        self.mdr_stats_tree = ttk.Treeview(
            f,
            columns=("Duration", "Mean", "SDev", "Cv", "Median", "Skew", "N"),
            show="headings",
            height=15,
        )
        for c in ("Duration", "Mean", "SDev", "Cv", "Median", "Skew", "N"):
            self.mdr_stats_tree.heading(c, text=c)
            self.mdr_stats_tree.column(c, width=90, anchor="center")
        self.mdr_stats_tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

    def _run_mdr(self):
        source = None
        if self.state.infill_result is not None:
            source = self.state.infill_result.composite
        elif self.state.station_a is not None:
            source = self.state.station_a
        if source is None:
            messagebox.showwarning("Missing input", "Load a station or build a composite first.")
            return
        try:
            durs = [int(x) for x in self.dur_str.get().split()]
            epy = float(self.epy.get())
            adj = float(self.depth_adj.get())
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        self.mdr_run_btn.configure(state="disabled")
        self.mdr_status.set("Extracting… (this can take a minute)")
        self.log("MDR extraction started.")

        def work():
            return build_mdr(source.rain, durs, events_per_year=epy, depth_adj=adj)

        def done(result):
            self.mdr_run_btn.configure(state="normal")
            if isinstance(result, tuple):
                exc, tb = result
                messagebox.showerror("MDR extraction failed", f"{exc}\n\n{tb}")
                self.mdr_status.set("failed")
                return
            self.state.mdr_result = result
            self.mdr_status.set(f"done — {result.n_events} events × {len(result.stats)} durations")
            for row in self.mdr_stats_tree.get_children():
                self.mdr_stats_tree.delete(row)
            for _, r in result.stats.iterrows():
                self.mdr_stats_tree.insert(
                    "",
                    END,
                    values=(
                        int(r["Duration"]),
                        f"{r['Mean']:.2f}",
                        f"{r['SDev']:.2f}",
                        f"{r['Cv']:.3f}" if pd.notna(r["Cv"]) else "-",
                        f"{r['Median']:.2f}",
                        f"{r['Skew']:.3f}" if pd.notna(r["Skew"]) else "-",
                        int(r["N"]),
                    ),
                )
            self.log("MDR extraction done.")

        self._run_bg(work, done)

    # ------------------------------------------------------------------ Tab 5: Curve Fit
    def _build_fit_tab(self):
        f = self.tab_fit
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        self.ari_wgt = StringVar(value="0.5")
        self.d_wgt = StringVar(value="0.0")
        self.ari_min = StringVar(value="2.0")
        ttk.Label(top, text="ARI weight power:").grid(row=0, column=0, sticky="e")
        ttk.Entry(top, textvariable=self.ari_wgt, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(top, text="Duration weight power:").grid(row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Entry(top, textvariable=self.d_wgt, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(top, text="ARI min:").grid(row=0, column=4, sticky="e", padx=(12, 0))
        ttk.Entry(top, textvariable=self.ari_min, width=8).grid(row=0, column=5, sticky="w")
        self.fit_run_btn = ttk.Button(top, text="Fit curve", command=self._run_fit)
        self.fit_run_btn.grid(row=0, column=6, padx=(20, 0))

        self.fit_result_var = StringVar(value="")
        ttk.Label(f, textvariable=self.fit_result_var, font=("Courier", 10), justify="left").pack(
            anchor="w", padx=8, pady=8
        )

        self.fit_canvas_frame = ttk.Frame(f)
        self.fit_canvas_frame.pack(fill=BOTH, expand=True)

    def _run_fit(self):
        if not self.state.mdr_result:
            messagebox.showwarning("Missing MDR", "Run MDR extraction first.")
            return
        try:
            aw = float(self.ari_wgt.get())
            dw = float(self.d_wgt.get())
            amin = float(self.ari_min.get())
        except ValueError as e:
            messagebox.showerror("Invalid", str(e))
            return

        self.fit_run_btn.configure(state="disabled")
        self.log("Fitting design curve…")

        def work():
            return fit_mdr_curve(self.state.mdr_result.table, aw, dw, amin)

        def done(result):
            self.fit_run_btn.configure(state="normal")
            if isinstance(result, tuple):
                exc, tb = result
                messagebox.showerror("Fit failed", f"{exc}\n\n{tb}")
                return
            self.state.fit_result = result
            a = result.a
            self.fit_result_var.set(
                f"a1 = {a[0]:10.4f}    a4 = {a[3]:10.4f}\n"
                f"a2 = {a[1]:10.4f}    a5 = {a[4]:10.4f}\n"
                f"a3 = {a[2]:10.4f}    a6 = {a[5]:10.4f}\n\n"
                f"Nash-Sutcliffe = {result.nash:.5f}    R² = {result.r2:.5f}\n"
                f"RMSE           = {result.rmse:.3f} mm\n"
                f"Normalized bias= {result.nbias:.5f}\n"
                f"N points       = {result.n_points}"
            )
            for w in self.fit_canvas_frame.winfo_children():
                w.destroy()
            fig = observed_vs_predicted_figure(result.observed_vs_predicted)
            canvas = FigureCanvasTkAgg(fig, master=self.fit_canvas_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.log("Curve fit done.")

        self._run_bg(work, done)

    # ------------------------------------------------------------------ Tab 6: Design Query
    def _build_design_tab(self):
        f = self.tab_design
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        self.q_ari = StringVar(value="100")
        self.q_dur = StringVar(value="1")
        self.q_p1p24 = StringVar(value="0.4")
        self.q_ila = StringVar(value="0.5")
        self.q_fo = StringVar(value="20")
        self.q_emax = StringVar(value="3")
        self.q_lag = StringVar(value="0.5")
        self.q_qmax = StringVar(value="50")

        entries = [
            ("ARI (yr):", self.q_ari),
            ("Duration (days):", self.q_dur),
            ("P1hr/P24hr @ P24→0:", self.q_p1p24),
            ("Initial loss factor ILa:", self.q_ila),
            ("Initial deficit Fo (mm):", self.q_fo),
            ("Deficit growth Emax (mm/d):", self.q_emax),
            ("Catchment lag (days):", self.q_lag),
            ("Max outflow qmax (mm/d, for Dcrit):", self.q_qmax),
        ]
        for r, (label, var) in enumerate(entries):
            ttk.Label(top, text=label).grid(row=r, column=0, sticky="e", padx=4, pady=2)
            ttk.Entry(top, textvariable=var, width=14).grid(row=r, column=1, sticky="w", padx=4)

        ttk.Button(top, text="Compute", command=self._run_design).grid(row=0, column=2, rowspan=8, padx=20, sticky="ns")

        self.design_result = StringVar(value="")
        ttk.Label(f, textvariable=self.design_result, font=("Courier", 10), justify="left").pack(
            anchor="w", padx=8, pady=8
        )

    def _run_design(self):
        if not self.state.fit_result:
            messagebox.showwarning("Missing fit", "Fit the curve first.")
            return
        try:
            a = self.state.fit_result.a
            ari = float(self.q_ari.get())
            d = float(self.q_dur.get())
            p1p24 = float(self.q_p1p24.get())
            ila = float(self.q_ila.get())
            fo = float(self.q_fo.get())
            emax = float(self.q_emax.get())
            lag = float(self.q_lag.get())
            qmax = float(self.q_qmax.get())
        except ValueError as e:
            messagebox.showerror("Invalid", str(e))
            return

        p, p24, dpdd, z = design_rainfall(a, ari, d, p1p24)
        try:
            pt = design_p_pe_q(a, p1p24, ari, d, ila, fo, emax, lag)
            lines = [
                f"P     = {p:.2f} mm    (unrestricted 24 h = {p24:.2f} mm)",
                f"dP/dD = {dpdd:.3f} mm/day    Z = {z:.4f}",
                f"Pe    = {pt.Pe:.2f} mm    De = {pt.De:.3f} d",
                f"Q     = {pt.Q:.2f} mm    dQ/dD = {pt.dQdD:.3f}   d²Q/dD² = {pt.d2QdD2:.3f}",
            ]
        except Exception as e:  # noqa: BLE001
            lines = [f"P = {p:.2f} mm", f"Pe/Q calc failed: {e}"]

        try:
            dcrit, p_at_dcrit = critical_duration(a, ari, qmax)
            lines.append(f"Critical duration (dP/dD = qmax) = {dcrit:.2f} d, P = {p_at_dcrit:.2f} mm")
        except Exception as e:  # noqa: BLE001
            lines.append(f"Critical duration: {e}")

        self.design_result.set("\n".join(lines))

    # ------------------------------------------------------------------ Tab 7: Plot & Export
    def _build_plot_tab(self):
        f = self.tab_plot
        top = ttk.Frame(f, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="ARIs to plot (space-separated):").grid(row=0, column=0, sticky="e")
        self.plot_aris_str = StringVar(value=" ".join(str(a) for a in DEFAULT_ARIS))
        ttk.Entry(top, textvariable=self.plot_aris_str, width=60).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Label(top, text="Max duration (days):").grid(row=1, column=0, sticky="e")
        self.plot_maxd = StringVar(value="150")
        ttk.Entry(top, textvariable=self.plot_maxd, width=10).grid(row=1, column=1, sticky="w", padx=4)

        btns = ttk.Frame(f, padding=4)
        btns.pack(fill="x")
        ttk.Button(btns, text="Redraw curves", command=self._redraw_curves).pack(side=LEFT)
        ttk.Button(btns, text="Save all outputs to disk", command=self._save_all).pack(side=LEFT, padx=12)

        self.plot_canvas_frame = ttk.Frame(f)
        self.plot_canvas_frame.pack(fill=BOTH, expand=True)

    def _redraw_curves(self):
        if not self.state.fit_result:
            messagebox.showwarning("Missing fit", "Fit the curve first.")
            return
        try:
            aris = [float(x) for x in self.plot_aris_str.get().split()]
            maxd = float(self.plot_maxd.get())
        except ValueError as e:
            messagebox.showerror("Invalid", str(e))
            return
        self.state.plot_aris = aris
        self.state.plot_max_duration = maxd

        for w in self.plot_canvas_frame.winfo_children():
            w.destroy()
        fig = design_curves_figure(
            self.state.fit_result.a, aris, max_duration=maxd, p1_on_p24=self.state.p1_on_p24
        )
        canvas = FigureCanvasTkAgg(fig, master=self.plot_canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)

    def _save_all(self):
        if not self.state.output_dir:
            p = filedialog.askdirectory(title="Choose output directory")
            if not p:
                return
            self.state.output_dir = Path(p)
            self.out_dir.set(p)

        out = self.state.output_dir

        def work():
            stations = [s for s in (self.state.station_a, self.state.station_b) if s is not None]
            if stations:
                write_stage1_ypp(stations, out)
            if self.state.dm_result and self.state.station_b:
                write_stage2_double_mass(
                    self.state.dm_result,
                    self.state.station_a.label,
                    self.state.station_b.label,
                    out,
                )
            if self.state.infill_result:
                write_stage3_infill(self.state.infill_result, out)
            if self.state.fit_result and self.state.mdr_result:
                write_stage4_mdr(
                    self.state.mdr_result,
                    self.state.fit_result,
                    self.state.fit_result.a,
                    self.state.plot_aris,
                    self.state.plot_max_duration,
                    self.state.p1_on_p24,
                    out,
                )
            return "done"

        def done(result):
            if isinstance(result, tuple):
                exc, tb = result
                messagebox.showerror("Save failed", f"{exc}\n\n{tb}")
                return
            messagebox.showinfo("Saved", f"All outputs written to:\n{out}")
            self.log(f"Outputs saved to {out}")

        self.log("Saving outputs…")
        self._run_bg(work, done)


def main() -> None:
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
