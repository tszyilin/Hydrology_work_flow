"""
Regime Flow Check GUI

Displays the original reference figure (main_plot.png) and overlays a red
horizontal line on each of the three panels at the user-supplied B_R, h_R
and S_R values. No digitisation of the envelopes is used.

The mapping from data value -> pixel row is a per-panel log10 interpolation
between the top and bottom pixel of the plot frame. Calibration constants
(PIXEL_* below) are the axis-frame pixel positions in main_plot.png; adjust
them if the red line does not visually land where you expect.
"""

import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PIL import Image

IMAGE_PATH = r"G:/My Drive/02_Coding/Coding/29_Regime_Flow_Check/01_Main_Plot/main_plot.png"

# Pixel positions of the plot frames in the reference image (644 x 1092).
# Values are (y_top, y_bottom, x_left, x_right, y_top_value, y_bot_value).
# x_left / x_right are shared as the Q axis spans 10^-3 to 10^5 in all panels.
PIXEL_X_LEFT  = 98      # x pixel where Q = 1e-3 (left axis line)
PIXEL_X_RIGHT = 601     # x pixel where Q = 1e5  (right axis line)

PANELS = {
    "B": dict(y_top=27,  y_bot=301,  y_top_val=1e4, y_bot_val=1e-1),
    "H": dict(y_top=386, y_bot=661,  y_top_val=1e2, y_bot_val=1e-2),
    "S": dict(y_top=747, y_bot=1022, y_top_val=1e0, y_bot_val=1e-5),
}


def value_to_pixel(panel, value):
    p = PANELS[panel]
    log_top = np.log10(p["y_top_val"])
    log_bot = np.log10(p["y_bot_val"])
    log_val = np.log10(value)
    frac = (log_top - log_val) / (log_top - log_bot)   # 0 at top, 1 at bottom
    return p["y_top"] + frac * (p["y_bot"] - p["y_top"])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Regime Flow Check — Q estimator")
        self.geometry("1000x900")

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=8, pady=8)
        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        pad = {"padx": 6, "pady": 4}
        frm = ttk.LabelFrame(left, text="Inputs (leave blank to skip)")
        frm.pack(fill="x")

        self.width_var = tk.StringVar()
        self.depth_var = tk.StringVar()
        self.slope_var = tk.StringVar()

        ttk.Label(frm, text="Width  B_R  (m):").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.width_var, width=14).grid(row=0, column=1, **pad)
        ttk.Label(frm, text="Depth  h_R  (m):").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.depth_var, width=14).grid(row=1, column=1, **pad)
        ttk.Label(frm, text="Slope  S_R  (-):").grid(row=2, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.slope_var, width=14).grid(row=2, column=1, **pad)

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 6))
        ttk.Button(btns, text="Show on plot", command=self.compute).pack(side="left", padx=4)
        ttk.Button(btns, text="Clear",         command=self.clear).pack(side="left")

        hint = ttk.Label(left, text="Left-click on the plot to drop a vertical\nQ marker; right-click to clear markers.",
                         foreground="gray30", justify="left")
        hint.pack(anchor="w", pady=(4, 4))

        readout = ttk.LabelFrame(left, text="Vertical Q markers")
        readout.pack(fill="both", expand=True)
        self.marker_list = tk.Text(readout, height=12, width=32, font=("Consolas", 9))
        self.marker_list.pack(fill="both", expand=True, padx=4, pady=4)

        # image + overlay
        self.img = np.array(Image.open(IMAGE_PATH))
        self.img_h, self.img_w = self.img.shape[:2]
        self.fig = Figure(figsize=(6.4, 8.5), dpi=100)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.v_markers = []  # list of Q values the user has clicked
        self.canvas.mpl_connect("button_press_event", self._on_click)

        self._draw_base()
        self.canvas.draw()

    def _draw_base(self):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.imshow(self.img)
        self.ax.set_xlim(0, self.img_w)
        self.ax.set_ylim(self.img_h, 0)  # image coords: y grows downward
        for q in self.v_markers:
            self._vline_q(q)

    def _hline(self, panel, value):
        y = value_to_pixel(panel, value)
        self.ax.plot([PIXEL_X_LEFT, PIXEL_X_RIGHT], [y, y],
                     color="red", ls="--", lw=1.2)

    def _pixel_to_q(self, x_pixel):
        frac = (x_pixel - PIXEL_X_LEFT) / (PIXEL_X_RIGHT - PIXEL_X_LEFT)
        log_q = np.log10(1e-3) + frac * (np.log10(1e5) - np.log10(1e-3))
        return 10 ** log_q

    def _q_to_pixel(self, q):
        log_q = np.log10(q)
        frac = (log_q - np.log10(1e-3)) / (np.log10(1e5) - np.log10(1e-3))
        return PIXEL_X_LEFT + frac * (PIXEL_X_RIGHT - PIXEL_X_LEFT)

    def _vline_q(self, q):
        """Draw a blue dashed vertical line at Q across all three panels."""
        x = self._q_to_pixel(q)
        for p in PANELS.values():
            self.ax.plot([x, x], [p["y_top"], p["y_bot"]],
                         color="blue", ls="--", lw=1.0)

    def _on_click(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            return
        x = event.xdata
        if x < PIXEL_X_LEFT or x > PIXEL_X_RIGHT:
            return
        if event.button == 3:   # right-click clears all
            self.v_markers.clear()
        elif event.button == 1: # left-click adds
            q = self._pixel_to_q(x)
            self.v_markers.append(q)
        else:
            return
        self._refresh_marker_list()
        self._redraw()

    def _refresh_marker_list(self):
        self.marker_list.delete("1.0", "end")
        for q in self.v_markers:
            self.marker_list.insert("end", f"Q = {q:.3g} m^3/s\n")

    def _redraw(self):
        """Re-render current state (base image + any input h-lines + v-markers)."""
        self._draw_base()
        # re-apply horizontal input lines if fields have values
        try:
            b = self._parse(self.width_var.get())
            h = self._parse(self.depth_var.get())
            s = self._parse(self.slope_var.get())
        except ValueError:
            b = h = s = None
        if b is not None: self._hline("B", b)
        if h is not None: self._hline("H", h)
        if s is not None: self._hline("S", s)
        self.canvas.draw()

    def _parse(self, s):
        s = s.strip()
        return float(s) if s else None

    def compute(self):
        try:
            b = self._parse(self.width_var.get())
            h = self._parse(self.depth_var.get())
            s = self._parse(self.slope_var.get())
        except ValueError:
            messagebox.showerror("Input error", "Values must be numeric.")
            return

        if b is None and h is None and s is None:
            messagebox.showwarning("Input error", "Enter at least one value.")
            return

        self._redraw()

    def clear(self):
        self.width_var.set("")
        self.depth_var.set("")
        self.slope_var.set("")
        self.v_markers.clear()
        self._refresh_marker_list()
        self._redraw()


if __name__ == "__main__":
    App().mainloop()
