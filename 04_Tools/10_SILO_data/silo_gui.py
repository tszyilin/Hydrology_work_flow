"""SILO weather station downloader.

Search a SILO Patched Point Dataset station by number or name, download its
daily data and split every value into "Actual" (observed at the station) or
"Synthetic" (interpolated / estimated by SILO) using the per-value source code.

Run:  python silo_gui.py
"""

import datetime as dt
import json
import os
import queue
import re
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from silo_core import EMAIL_RE, FIRST_DATE, VARIABLES, download_to_excel, search_stations

SETTINGS_FILE = Path(__file__).with_name("silo_settings.json")


# ---------------------------------------------------------------- UI

class SiloApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SILO weather station downloader")
        self.minsize(720, 640)
        self.settings = self._load_settings()
        self.stations = []
        self.selected = None
        self._jobs = queue.Queue()

        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        # Station search
        ttk.Label(frm, text="Station number or name:").grid(row=0, column=0, sticky="w", **pad)
        self.search_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.search_var)
        entry.grid(row=0, column=1, sticky="ew", **pad)
        entry.bind("<Return>", lambda e: self.on_search())
        entry.focus()
        self.search_btn = ttk.Button(frm, text="Search", command=self.on_search)
        self.search_btn.grid(row=0, column=2, **pad)

        cols = ("number", "name", "state", "lat", "lon", "elevation")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=7, selectmode="browse")
        for col, text, width in zip(cols, ("No.", "Name", "State", "Lat", "Lon", "Elev (m)"),
                                    (70, 280, 60, 80, 80, 80)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w" if col == "name" else "center")
        self.tree.grid(row=1, column=0, columnspan=3, sticky="nsew", **pad)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        frm.rowconfigure(1, weight=1)

        self.selected_var = tk.StringVar(value="No station selected")
        ttk.Label(frm, textvariable=self.selected_var, font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, columnspan=3, sticky="w", **pad)

        # Dates
        dates = ttk.Frame(frm)
        dates.grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        self.start_var = tk.StringVar(value=FIRST_DATE.isoformat())
        self.end_var = tk.StringVar(value=(dt.date.today() - dt.timedelta(days=1)).isoformat())
        ttk.Label(dates, text="Start (YYYY-MM-DD):").pack(side="left")
        ttk.Entry(dates, textvariable=self.start_var, width=12).pack(side="left", padx=(4, 16))
        ttk.Label(dates, text="End:").pack(side="left")
        ttk.Entry(dates, textvariable=self.end_var, width=12).pack(side="left", padx=4)

        # Variables
        var_box = ttk.LabelFrame(frm, text="Variables", padding=6)
        var_box.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        saved_vars = self.settings.get("variables")
        self.var_checks = {}
        for i, (_, col, label, default) in enumerate(VARIABLES):
            v = tk.BooleanVar(value=(col in saved_vars) if saved_vars else default)
            ttk.Checkbutton(var_box, text=label, variable=v).grid(row=i // 3, column=i % 3, sticky="w", padx=6)
            self.var_checks[col] = v
        self.code15_var = tk.BooleanVar(value=self.settings.get("code15_actual", True))
        ttk.Checkbutton(
            var_box, variable=self.code15_var,
            text="Count code 15 (accumulated rain redistributed by SILO) as Actual",
        ).grid(row=len(VARIABLES) // 3 + 1, column=0, columnspan=3, sticky="w", padx=6, pady=(6, 0))
        self.spread15_var = tk.BooleanVar(value=self.settings.get("spread_code15", True))
        ttk.Checkbutton(
            var_box, variable=self.spread15_var,
            text="Spread code 15 rain evenly over its days (instead of SILO's split)",
        ).grid(row=len(VARIABLES) // 3 + 2, column=0, columnspan=3, sticky="w", padx=6)

        # Email + output
        ttk.Label(frm, text="Email (SILO API username):").grid(row=5, column=0, sticky="w", **pad)
        self.email_var = tk.StringVar(value=self.settings.get("email", ""))
        ttk.Entry(frm, textvariable=self.email_var).grid(row=5, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frm, text="Save to folder:").grid(row=6, column=0, sticky="w", **pad)
        self.out_var = tk.StringVar(value=self.settings.get("output_dir", str(Path(__file__).parent)))
        ttk.Entry(frm, textvariable=self.out_var).grid(row=6, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…", command=self.on_browse).grid(row=6, column=2, **pad)

        # Download
        bottom = ttk.Frame(frm)
        bottom.grid(row=7, column=0, columnspan=3, sticky="ew", **pad)
        bottom.columnconfigure(1, weight=1)
        self.dl_btn = ttk.Button(bottom, text="Download", command=self.on_download)
        self.dl_btn.grid(row=0, column=0)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=8)
        self.status_var = tk.StringVar(value="Type a station number (e.g. 13017) or part of a name, then Search.")
        ttk.Label(frm, textvariable=self.status_var, wraplength=680).grid(
            row=8, column=0, columnspan=3, sticky="w", **pad)

        self.after(100, self._poll_jobs)

    # -- background work: network calls run off the UI thread
    def _run_bg(self, work, on_done, busy_text):
        self.status_var.set(busy_text)
        self.progress.start(12)
        self.search_btn.state(["disabled"])
        self.dl_btn.state(["disabled"])

        def runner():
            try:
                self._jobs.put((on_done, work(), None))
            except Exception as exc:  # shown to the user in the UI thread
                self._jobs.put((on_done, None, exc))

        threading.Thread(target=runner, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                on_done, result, exc = self._jobs.get_nowait()
                self.progress.stop()
                self.search_btn.state(["!disabled"])
                self.dl_btn.state(["!disabled"])
                if exc:
                    self.status_var.set("Error: " + str(exc).splitlines()[0])
                    messagebox.showerror("SILO", str(exc))
                else:
                    on_done(result)
        except queue.Empty:
            pass
        self.after(100, self._poll_jobs)

    # -- handlers
    def on_search(self):
        text = self.search_var.get()
        if not text.strip():
            return
        self._run_bg(lambda: search_stations(text), self._show_results, f"Searching SILO for '{text.strip()}'…")

    def _show_results(self, stations):
        self.stations = stations
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(stations):
            self.tree.insert("", "end", iid=str(i), values=(
                s["number"], s["name"], s["state"], s["lat"], s["lon"], s["elevation"]))
        if not stations:
            self.status_var.set("No stations found. Try a shorter part of the name.")
            return
        self.status_var.set(f"{len(stations)} station(s) found. Select one, then Download.")
        if len(stations) == 1:
            self.tree.selection_set("0")

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected = self.stations[int(sel[0])]
        s = self.selected
        self.selected_var.set(f"Selected: {s['number']} – {s['name']} ({s['state']}, {s['lat']}, {s['lon']})")

    def on_browse(self):
        folder = filedialog.askdirectory(initialdir=self.out_var.get() or None)
        if folder:
            self.out_var.set(folder)

    def on_download(self):
        if not self.selected:
            messagebox.showwarning("SILO", "Search for and select a station first.")
            return
        try:
            start = dt.date.fromisoformat(self.start_var.get().strip())
            end = dt.date.fromisoformat(self.end_var.get().strip())
        except ValueError:
            messagebox.showwarning("SILO", "Dates must be YYYY-MM-DD.")
            return
        if start > end:
            messagebox.showwarning("SILO", "Start date is after end date.")
            return
        if start < FIRST_DATE:
            start = FIRST_DATE
            self.start_var.set(start.isoformat())
        email = self.email_var.get().strip()
        if not re.fullmatch(EMAIL_RE, email):
            messagebox.showwarning("SILO", "Enter a valid email address — SILO uses it as the API username.")
            return
        columns = [col for col, v in self.var_checks.items() if v.get()]
        if not columns:
            messagebox.showwarning("SILO", "Tick at least one variable.")
            return
        out_dir = Path(self.out_var.get().strip() or Path(__file__).parent)
        actual_codes = {0, 15} if self.code15_var.get() else {0}
        station = self.selected
        spread15 = self.spread15_var.get()

        self.settings.update(email=email, output_dir=str(out_dir), variables=columns,
                             code15_actual=self.code15_var.get(), spread_code15=spread15)
        self._save_settings()

        def work():
            return download_to_excel(station, start, end, columns, email,
                                     actual_codes, spread15, out_dir)

        self._run_bg(work, self._download_done,
                     f"Downloading {station['number']} {station['name']} {start} to {end}…")

    def _download_done(self, result):
        path, summary = result
        lines = [f"{r['Variable']}: {r['Actual %']}% actual" for _, r in summary.iterrows()]
        self.status_var.set(f"Saved {path}")
        if messagebox.askyesno("SILO", f"Saved:\n{path}\n\n" + "\n".join(lines) + "\n\nOpen the file now?"):
            os.startfile(path)

    # -- settings
    def _load_settings(self):
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))
        except OSError:
            pass


if __name__ == "__main__":
    SiloApp().mainloop()
