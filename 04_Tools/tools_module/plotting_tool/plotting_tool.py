"""
Plotting Tool -- paste-and-plot desktop GUI (PyQt5)
===================================================

A general-purpose PyQt5 plotting tool. Ported from tkinter so it runs on
QGIS's bundled Python (which does not ship _tkinter), matching the pattern
used by the sibling Drain Design Toolbox.

The window is a set of CASES. A case is one self-contained plot: its own
data table, its own series, its own plot type, its own axis settings, its
own title/labels and its own exports.

Projects (all cases, data and styling) save to / load from a .json file
(legacy .plotproj files are also accepted).
"""

import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
# Only pick the pyplot backend when running standalone. Inside QGIS the tool
# is docked in-process, and switching backends there would close any open
# pyplot figures of other tools. (This module draws via FigureCanvasQTAgg
# directly, so it does not need pyplot's backend either way.)
if "qgis.core" not in sys.modules:
    matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import (
    AutoLocator, AutoMinorLocator, FuncFormatter, LogLocator, MultipleLocator, NullFormatter,
)

try:
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QColor, QIcon, QImage, QKeySequence
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QDialog, QMessageBox,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton, QButtonGroup,
        QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
        QTabWidget, QSplitter, QFrame, QScrollArea, QFileDialog, QColorDialog,
        QInputDialog, QListWidget, QAbstractItemView, QSizePolicy,
    )
except ImportError:
    from qgis.PyQt.QtCore import QEvent, Qt
    from qgis.PyQt.QtGui import QColor, QIcon, QImage, QKeySequence
    from qgis.PyQt.QtWidgets import (
        QApplication, QMainWindow, QWidget, QDialog, QMessageBox,
        QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QRadioButton, QButtonGroup,
        QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
        QTabWidget, QSplitter, QFrame, QScrollArea, QFileDialog, QColorDialog,
        QInputDialog, QListWidget, QAbstractItemView, QSizePolicy,
    )

APP_TITLE = "Plotting Tool"
PROJECT_EXT = ".json"

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

COLOR_CYCLE = [
    "#2564A6", "#C1521C", "#2F8F6B", "#8A3FA6", "#B0862A",
    "#3D6E8C", "#A6425A", "#5C7A29", "#6A4FA0", "#2E958F",
    "#8C4B2F", "#4A6FA5",
]

LINESTYLE_OPTIONS = ["solid", "dashed", "dotted", "dash-dot", "none"]
LINESTYLE_MAP = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-.", "none": "None"}

MARKER_OPTIONS = ["none", "circle", "square", "tri-up", "tri-down", "diamond",
                  "thin diamond", "star", "plus", "cross", "pentagon", "point"]
MARKER_MAP = {
    "none": "None", "circle": "o", "square": "s", "tri-up": "^", "tri-down": "v",
    "diamond": "D", "thin diamond": "d", "star": "*", "plus": "P", "cross": "X",
    "pentagon": "p", "point": ".",
}

FILL_OPTIONS = ["Filled", "Hollow", "Hollow (white)"]

PLOT_TYPES = [
    "Line + markers", "Line only", "Scatter only",
    "Bar (grouped)", "Bar (horizontal)", "Bar (stacked)",
    "Step", "Area (filled)",
]
BAR_TYPES = {"Bar (grouped)", "Bar (horizontal)", "Bar (stacked)"}

LEGEND_LOCS = ["best", "upper left", "upper right", "lower left", "lower right",
               "upper center", "lower center", "center left", "center right", "off"]

DEFAULT_ROWS = 25
DEFAULT_SERIES = 2


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def to_float(value):
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
    if v is None:
        return ""
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:.4g}"


def tick_fmt(v):
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


def looks_like_header(cells):
    if len(cells) < 2:
        return False
    non_numeric = sum(1 for c in cells[1:] if c.strip() and to_float(c) is None)
    return non_numeric >= max(1, (len(cells) - 1) // 2)


def make_scrollable(parent_layout=None):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    scroll.setWidget(inner)
    if parent_layout is not None:
        parent_layout.addWidget(scroll)
    return scroll, inner, layout


def _bold_label(text):
    lbl = QLabel(text)
    font = lbl.font()
    font.setBold(True)
    lbl.setFont(font)
    return lbl


def _set_swatch_color(swatch, hex_color):
    swatch.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #999999;")


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                _clear_layout(child)


# --------------------------------------------------------------------------
# Data grid
# --------------------------------------------------------------------------

class DataGridTable(QTableWidget):
    def __init__(self, owner):
        super().__init__(0, 0)
        self._owner = owner
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                             | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.verticalHeader().setDefaultSectionSize(20)

    def event(self, event):
        # When docked in QGIS, the main window's Copy/Paste Features
        # shortcuts would otherwise take Ctrl+C / Ctrl+V before the table
        # sees them. Claim the keys the table handles while it has focus.
        if event.type() == QEvent.Type.ShortcutOverride and (
                event.matches(QKeySequence.StandardKey.Paste)
                or event.matches(QKeySequence.StandardKey.Copy)
                or event.key() == Qt.Key.Key_Delete):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self._owner.paste_clipboard()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self._owner.copy_selection()
            return
        if event.key() == Qt.Key.Key_Delete:
            self._owner.clear_selection()
            return
        super().keyPressEvent(event)


class DataGrid(QWidget):
    def __init__(self, headers, nrows=DEFAULT_ROWS,
                 on_data_change=None, on_headers_change=None):
        super().__init__()
        self.headers = list(headers)
        self.data = [["" for _ in self.headers] for _ in range(nrows)]
        self.on_data_change = on_data_change
        self.on_headers_change = on_headers_change
        self._suspend = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = DataGridTable(self)
        layout.addWidget(self.table)

        self.table.itemChanged.connect(self._on_item_changed)
        self._sync_columns()
        self.refresh()

    def _sync_columns(self):
        self._suspend = True
        try:
            self.table.setColumnCount(len(self.headers))
            self.table.setHorizontalHeaderLabels(self.headers)
            header = self.table.horizontalHeader()
            for i in range(len(self.headers)):
                self.table.setColumnWidth(i, 95 if i == 0 else 115)
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        finally:
            self._suspend = False

    def _normalize(self):
        width = len(self.headers)
        for row in self.data:
            while len(row) < width:
                row.append("")
            del row[width:]

    def refresh(self):
        self._suspend = True
        try:
            self._normalize()
            self.table.setRowCount(len(self.data))
            for r, row in enumerate(self.data):
                for c, val in enumerate(row):
                    item = self.table.item(r, c)
                    if item is None:
                        item = QTableWidgetItem("")
                        item.setTextAlignment(
                            (Qt.AlignmentFlag.AlignLeft if c == 0 else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter)
                        self.table.setItem(r, c, item)
                    item.setText(str(val))
        finally:
            self._suspend = False

    def set_header(self, index, text):
        if 0 <= index < len(self.headers):
            self.headers[index] = text
            self.table.setHorizontalHeaderItem(index, QTableWidgetItem(text))

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

    def _selected_rows(self):
        return sorted({idx.row() for idx in self.table.selectedIndexes()})

    def delete_selected_rows(self):
        sel = list(reversed(self._selected_rows()))
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
        for idx in self.table.selectedIndexes():
            r, c = idx.row(), idx.column()
            if 0 <= r < len(self.data) and 0 <= c < len(self.headers):
                self.data[r][c] = ""
        self.refresh()
        self._changed()

    def clear_all(self):
        self.data = [["" for _ in self.headers] for _ in range(DEFAULT_ROWS)]
        self.refresh()
        self._changed()

    def column(self, index):
        self._normalize()
        return [row[index] if index < len(row) else "" for row in self.data]

    def used_row_count(self):
        last = 0
        for i, row in enumerate(self.data):
            if any(str(c).strip() for c in row):
                last = i + 1
        return last

    def paste_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            QMessageBox.information(self, "Nothing to paste", "The clipboard is empty.")
            return
        self.paste_text(text)

    def _anchor(self):
        idx = self.table.currentIndex()
        if idx.isValid():
            return idx.row(), idx.column()
        return 0, 0

    def paste_text(self, text):
        raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while raw and not raw[-1].strip():
            raw.pop()
        if not raw:
            return
        sep = "\t" if any("\t" in line for line in raw) else None
        rows = [line.split(sep) if sep else [line] for line in raw]

        r0, c0 = self._anchor()
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
        rows = self._selected_rows() or list(range(self.used_row_count()))
        lines = ["\t".join(self.headers)]
        lines += ["\t".join(str(c) for c in self.data[i]) for i in rows if i < len(self.data)]
        QApplication.clipboard().setText("\n".join(lines))

    def _on_item_changed(self, item):
        if self._suspend:
            return
        r, c = item.row(), item.column()
        while len(self.data) <= r:
            self.data.append(["" for _ in self.headers])
        while len(self.data[r]) <= c:
            self.data[r].append("")
        text = item.text().strip()
        if self.data[r][c] != text:
            self.data[r][c] = text
            self._changed()

    def _changed(self):
        if self.on_data_change:
            self.on_data_change()

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
# Axis panel
# --------------------------------------------------------------------------

class AxisPanel(QWidget):
    def __init__(self, auto_xlim_fn, auto_ylim_fn, on_change):
        super().__init__()
        self._auto_xlim_fn = auto_xlim_fn
        self._auto_ylim_fn = auto_ylim_fn
        self._on_change = on_change
        self._suspend = False

        self.x_scale = "linear"
        self.y_scale = "linear"
        self.x_auto = True
        self.y_auto = True
        self.custom_xlim = None
        self.custom_ylim = None
        # Tick spacing overrides — None means "auto" (matplotlib picks).
        self.custom_x_major = None
        self.custom_x_minor = None
        self.custom_y_major = None
        self.custom_y_minor = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame()
        container.setFrameShape(QFrame.Shape.StyledPanel)
        outer.addWidget(container)

        grid = QGridLayout(container)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)

        grid.addWidget(_bold_label("X scale"), 0, 0, 1, 3)
        x_row = QHBoxLayout()
        self.x_linear = QRadioButton("Linear")
        self.x_log = QRadioButton("Log")
        self.x_linear.setChecked(True)
        g1 = QButtonGroup(self); g1.addButton(self.x_linear); g1.addButton(self.x_log)
        x_row.addWidget(self.x_linear); x_row.addWidget(self.x_log); x_row.addStretch()
        grid.addLayout(x_row, 1, 0, 1, 3)
        self.x_linear.toggled.connect(self._on_x_scale_change)
        self.x_log.toggled.connect(self._on_x_scale_change)

        self.x_auto_cb = QCheckBox("Auto X limits"); self.x_auto_cb.setChecked(True)
        self.x_auto_cb.toggled.connect(self._on_x_auto_toggle)
        grid.addWidget(self.x_auto_cb, 2, 0, 1, 3)
        grid.addWidget(QLabel("min"), 3, 0)
        self.x_min_edit = QLineEdit(); self.x_min_edit.setFixedWidth(90); self.x_min_edit.setEnabled(False)
        self.x_min_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.x_min_edit, 3, 1)
        grid.addWidget(QLabel("max"), 4, 0)
        self.x_max_edit = QLineEdit(); self.x_max_edit.setFixedWidth(90); self.x_max_edit.setEnabled(False)
        self.x_max_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.x_max_edit, 4, 1)
        grid.addWidget(QLabel("major every"), 5, 0)
        self.x_major_edit = QLineEdit(); self.x_major_edit.setFixedWidth(90)
        self.x_major_edit.setPlaceholderText("auto")
        self.x_major_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.x_major_edit, 5, 1)
        grid.addWidget(QLabel("minor every"), 6, 0)
        self.x_minor_edit = QLineEdit(); self.x_minor_edit.setFixedWidth(90)
        self.x_minor_edit.setPlaceholderText("auto")
        self.x_minor_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.x_minor_edit, 6, 1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(sep, 7, 0, 1, 3)

        grid.addWidget(_bold_label("Y scale"), 8, 0, 1, 3)
        y_row = QHBoxLayout()
        self.y_linear = QRadioButton("Linear"); self.y_log = QRadioButton("Log")
        self.y_linear.setChecked(True)
        g2 = QButtonGroup(self); g2.addButton(self.y_linear); g2.addButton(self.y_log)
        y_row.addWidget(self.y_linear); y_row.addWidget(self.y_log); y_row.addStretch()
        grid.addLayout(y_row, 9, 0, 1, 3)
        self.y_linear.toggled.connect(self._on_y_scale_change)
        self.y_log.toggled.connect(self._on_y_scale_change)

        self.y_auto_cb = QCheckBox("Auto Y limits"); self.y_auto_cb.setChecked(True)
        self.y_auto_cb.toggled.connect(self._on_y_auto_toggle)
        grid.addWidget(self.y_auto_cb, 10, 0, 1, 3)
        grid.addWidget(QLabel("min"), 11, 0)
        self.y_min_edit = QLineEdit(); self.y_min_edit.setFixedWidth(90); self.y_min_edit.setEnabled(False)
        self.y_min_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.y_min_edit, 11, 1)
        grid.addWidget(QLabel("max"), 12, 0)
        self.y_max_edit = QLineEdit(); self.y_max_edit.setFixedWidth(90); self.y_max_edit.setEnabled(False)
        self.y_max_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.y_max_edit, 12, 1)
        grid.addWidget(QLabel("major every"), 13, 0)
        self.y_major_edit = QLineEdit(); self.y_major_edit.setFixedWidth(90)
        self.y_major_edit.setPlaceholderText("auto")
        self.y_major_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.y_major_edit, 13, 1)
        grid.addWidget(QLabel("minor every"), 14, 0)
        self.y_minor_edit = QLineEdit(); self.y_minor_edit.setFixedWidth(90)
        self.y_minor_edit.setPlaceholderText("auto")
        self.y_minor_edit.returnPressed.connect(self.on_apply)
        grid.addWidget(self.y_minor_edit, 14, 1)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply"); apply_btn.clicked.connect(self.on_apply)
        auto_btn = QPushButton("Auto"); auto_btn.clicked.connect(self.on_reset)
        btn_row.addWidget(apply_btn); btn_row.addWidget(auto_btn)
        grid.addLayout(btn_row, 15, 0, 1, 3)

    def _on_x_scale_change(self, *_):
        if self._suspend:
            return
        self.x_scale = "log" if self.x_log.isChecked() else "linear"
        self.custom_xlim = None
        self._suspend = True; self.x_auto_cb.setChecked(True); self._suspend = False
        self.x_auto = True
        self.x_min_edit.setEnabled(False); self.x_max_edit.setEnabled(False)
        self._on_change()

    def _on_y_scale_change(self, *_):
        if self._suspend:
            return
        self.y_scale = "log" if self.y_log.isChecked() else "linear"
        self.custom_ylim = None
        self._suspend = True; self.y_auto_cb.setChecked(True); self._suspend = False
        self.y_auto = True
        self.y_min_edit.setEnabled(False); self.y_max_edit.setEnabled(False)
        self._on_change()

    def _on_x_auto_toggle(self, checked):
        if self._suspend:
            return
        self.x_auto = bool(checked)
        self.x_min_edit.setEnabled(not self.x_auto); self.x_max_edit.setEnabled(not self.x_auto)
        if self.x_auto:
            self.custom_xlim = None
        else:
            lo, hi = self.custom_xlim if self.custom_xlim else self._auto_xlim_fn()
            if lo is not None: self.x_min_edit.setText(fmt_num(lo))
            if hi is not None: self.x_max_edit.setText(fmt_num(hi))
            if lo is not None and hi is not None:
                self.custom_xlim = (lo, hi)
        self._on_change()

    def _on_y_auto_toggle(self, checked):
        if self._suspend:
            return
        self.y_auto = bool(checked)
        self.y_min_edit.setEnabled(not self.y_auto); self.y_max_edit.setEnabled(not self.y_auto)
        if self.y_auto:
            self.custom_ylim = None
        else:
            lo, hi = self.custom_ylim if self.custom_ylim else self._auto_ylim_fn()
            if lo is not None: self.y_min_edit.setText(fmt_num(lo))
            if hi is not None: self.y_max_edit.setText(fmt_num(hi))
            if lo is not None and hi is not None:
                self.custom_ylim = (lo, hi)
        self._on_change()

    def on_apply(self):
        errors = []
        if not self.x_auto:
            try:
                xlo = float(self.x_min_edit.text()); xhi = float(self.x_max_edit.text())
                if self.x_scale == "log" and (xlo <= 0 or xhi <= 0):
                    raise ValueError("limits must be positive on a log scale.")
                if xlo >= xhi:
                    raise ValueError("min must be less than max.")
                self.custom_xlim = (xlo, xhi)
            except ValueError as exc:
                errors.append(f"X axis: {exc or 'must be valid numbers'}")
        if not self.y_auto:
            try:
                ylo = float(self.y_min_edit.text()); yhi = float(self.y_max_edit.text())
                if self.y_scale == "log" and (ylo <= 0 or yhi <= 0):
                    raise ValueError("limits must be positive on a log scale.")
                if ylo >= yhi:
                    raise ValueError("min must be less than max.")
                self.custom_ylim = (ylo, yhi)
            except ValueError as exc:
                errors.append(f"Y axis: {exc or 'must be valid numbers'}")
        if errors:
            QMessageBox.critical(self, "Invalid axis limits", "\n".join(errors))
            return
        # Tick spacings: blank / non-numeric / non-positive → auto.
        self.custom_x_major = self._positive_or_none(self.x_major_edit.text())
        self.custom_x_minor = self._positive_or_none(self.x_minor_edit.text())
        self.custom_y_major = self._positive_or_none(self.y_major_edit.text())
        self.custom_y_minor = self._positive_or_none(self.y_minor_edit.text())
        self._on_change()

    @staticmethod
    def _positive_or_none(text):
        v = to_float(text)
        return v if (v is not None and v > 0) else None

    def on_reset(self):
        self._suspend = True
        self.x_auto_cb.setChecked(True); self.y_auto_cb.setChecked(True)
        self._suspend = False
        self.x_auto = True; self.y_auto = True
        self.custom_xlim = None; self.custom_ylim = None
        self.custom_x_major = None; self.custom_x_minor = None
        self.custom_y_major = None; self.custom_y_minor = None
        self.x_min_edit.setEnabled(False); self.x_max_edit.setEnabled(False)
        self.y_min_edit.setEnabled(False); self.y_max_edit.setEnabled(False)
        for e in (self.x_major_edit, self.x_minor_edit,
                  self.y_major_edit, self.y_minor_edit):
            e.blockSignals(True); e.clear(); e.blockSignals(False)
        self._on_change()

    @staticmethod
    def _apply_locator(axis_obj, scale, major, minor):
        """Apply major+minor locators. On log scale, custom spacings are
        ignored (a MultipleLocator on a log axis rarely matches intent)."""
        axis_obj.set_major_formatter(FuncFormatter(lambda v, _: tick_fmt(v)))
        axis_obj.set_minor_formatter(NullFormatter())
        if scale == "log":
            axis_obj.set_major_locator(LogLocator(base=10.0))
            axis_obj.set_minor_locator(LogLocator(base=10.0, subs=range(2, 10)))
            return
        axis_obj.set_major_locator(MultipleLocator(major) if major else AutoLocator())
        axis_obj.set_minor_locator(MultipleLocator(minor) if minor else AutoMinorLocator())

    def apply_to_axes(self, ax, categorical_x=False, horizontal=False):
        x_scale = "linear" if categorical_x else self.x_scale
        ax.set_xscale(x_scale)
        if not categorical_x:
            if self.x_auto:
                xlo, xhi = self._auto_xlim_fn()
                if xlo is not None: self.x_min_edit.setText(fmt_num(xlo))
                if xhi is not None: self.x_max_edit.setText(fmt_num(xhi))
            else:
                xlo, xhi = self.custom_xlim if self.custom_xlim else self._auto_xlim_fn()
            if xlo is not None and xhi is not None and xlo < xhi:
                ax.set_xlim(xlo, xhi)
            self._apply_locator(ax.xaxis, x_scale,
                                self.custom_x_major, self.custom_x_minor)

        y_scale = self.y_scale
        ax.set_yscale(y_scale)
        if self.y_auto:
            ylo, yhi = self._auto_ylim_fn()
            if ylo is not None: self.y_min_edit.setText(fmt_num(ylo))
            if yhi is not None: self.y_max_edit.setText(fmt_num(yhi))
        else:
            ylo, yhi = self.custom_ylim if self.custom_ylim else self._auto_ylim_fn()
        if ylo is not None and yhi is not None and ylo < yhi:
            ax.set_ylim(ylo, yhi)
        self._apply_locator(ax.yaxis, y_scale,
                            self.custom_y_major, self.custom_y_minor)

    def dump(self):
        return {"x_scale": self.x_scale, "y_scale": self.y_scale,
                "x_auto": self.x_auto, "y_auto": self.y_auto,
                "xlim": list(self.custom_xlim) if self.custom_xlim else None,
                "ylim": list(self.custom_ylim) if self.custom_ylim else None,
                "x_major": self.custom_x_major, "x_minor": self.custom_x_minor,
                "y_major": self.custom_y_major, "y_minor": self.custom_y_minor}

    def load(self, blob):
        self._suspend = True
        try:
            self.x_scale = blob.get("x_scale", "linear")
            self.y_scale = blob.get("y_scale", "linear")
            (self.x_log if self.x_scale == "log" else self.x_linear).setChecked(True)
            (self.y_log if self.y_scale == "log" else self.y_linear).setChecked(True)
            self.x_auto = bool(blob.get("x_auto", True))
            self.y_auto = bool(blob.get("y_auto", True))
            self.x_auto_cb.setChecked(self.x_auto); self.y_auto_cb.setChecked(self.y_auto)
            self.custom_xlim = tuple(blob["xlim"]) if blob.get("xlim") else None
            self.custom_ylim = tuple(blob["ylim"]) if blob.get("ylim") else None
            self.x_min_edit.setEnabled(not self.x_auto); self.x_max_edit.setEnabled(not self.x_auto)
            self.y_min_edit.setEnabled(not self.y_auto); self.y_max_edit.setEnabled(not self.y_auto)
            if self.custom_xlim:
                self.x_min_edit.setText(fmt_num(self.custom_xlim[0]))
                self.x_max_edit.setText(fmt_num(self.custom_xlim[1]))
            if self.custom_ylim:
                self.y_min_edit.setText(fmt_num(self.custom_ylim[0]))
                self.y_max_edit.setText(fmt_num(self.custom_ylim[1]))
            self.custom_x_major = self._positive_or_none(blob.get("x_major"))
            self.custom_x_minor = self._positive_or_none(blob.get("x_minor"))
            self.custom_y_major = self._positive_or_none(blob.get("y_major"))
            self.custom_y_minor = self._positive_or_none(blob.get("y_minor"))
            for edit, val in ((self.x_major_edit, self.custom_x_major),
                              (self.x_minor_edit, self.custom_x_minor),
                              (self.y_major_edit, self.custom_y_major),
                              (self.y_minor_edit, self.custom_y_minor)):
                edit.setText("" if val is None else fmt_num(val))
        finally:
            self._suspend = False


# --------------------------------------------------------------------------
# Reference lines
# --------------------------------------------------------------------------

REFLINE_ORIENTATIONS = ["Horizontal", "Vertical"]
REFLINE_ORI_MAP = {"Horizontal": "h", "Vertical": "v"}
REFLINE_ORI_RMAP = {v: k for k, v in REFLINE_ORI_MAP.items()}


class SwatchLabel(QLabel):
    def __init__(self, hex_color, on_click):
        super().__init__()
        self.setFixedSize(18, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        _set_swatch_color(self, hex_color)
        self._on_click = on_click

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
        super().mousePressEvent(event)


class RefLinesPanel(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self._on_change = on_change
        self.lines = []
        self._suspend = False

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        container = QFrame(); container.setFrameShape(QFrame.Shape.StyledPanel)
        outer.addWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6); layout.setSpacing(4)

        btns = QHBoxLayout()
        add_btn = QPushButton("+ line"); add_btn.clicked.connect(lambda: self.add_line())
        clear_btn = QPushButton("Clear"); clear_btn.clicked.connect(self.clear)
        btns.addWidget(add_btn); btns.addWidget(clear_btn); btns.addStretch()
        layout.addLayout(btns)

        self.rows_holder = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_holder)
        self.rows_layout.setContentsMargins(0, 0, 0, 0); self.rows_layout.setSpacing(2)
        layout.addWidget(self.rows_holder)

    def _new_state(self, blob=None):
        blob = blob or {}
        return {
            "orientation": REFLINE_ORI_RMAP.get(blob.get("orientation", "h"), "Horizontal"),
            "value": str(blob.get("value", "0")),
            "color": blob.get("color", "#666666"),
            "linestyle": blob.get("linestyle", "dashed"),
            "width": str(blob.get("width", "1.2")),
            "label": blob.get("label", ""),
        }

    def add_line(self, blob=None):
        self.lines.append(self._new_state(blob))
        self._rebuild()
        if not self._suspend:
            self._on_change()

    def remove_line(self, index):
        if 0 <= index < len(self.lines):
            del self.lines[index]
            self._rebuild()
            self._on_change()

    def clear(self):
        if not self.lines:
            return
        self.lines.clear(); self._rebuild(); self._on_change()

    def pick_color(self, index):
        current = self.lines[index]["color"]
        col = QColorDialog.getColor(QColor(current), self, "Reference line colour")
        if not col.isValid():
            return
        self.lines[index]["color"] = col.name()
        self._rebuild(); self._on_change()

    def _rebuild(self):
        _clear_layout(self.rows_layout)
        for i, state in enumerate(self.lines):
            row = QWidget()
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(2)
            ori = QComboBox(); ori.addItems(REFLINE_ORIENTATIONS); ori.setCurrentText(state["orientation"])
            ori.currentTextChanged.connect(lambda text, idx=i: self._update_field(idx, "orientation", text))
            rl.addWidget(ori)
            val = QLineEdit(state["value"]); val.setFixedWidth(60)
            val.textChanged.connect(lambda text, idx=i: self._update_field(idx, "value", text))
            rl.addWidget(val)
            swatch = SwatchLabel(state["color"], lambda idx=i: self.pick_color(idx))
            rl.addWidget(swatch)
            ls = QComboBox(); ls.addItems(LINESTYLE_OPTIONS); ls.setCurrentText(state["linestyle"])
            ls.currentTextChanged.connect(lambda text, idx=i: self._update_field(idx, "linestyle", text))
            rl.addWidget(ls)
            width = QLineEdit(state["width"]); width.setFixedWidth(45)
            width.textChanged.connect(lambda text, idx=i: self._update_field(idx, "width", text))
            rl.addWidget(width)
            label = QLineEdit(state["label"]); label.setFixedWidth(80)
            label.textChanged.connect(lambda text, idx=i: self._update_field(idx, "label", text))
            rl.addWidget(label)
            rm = QPushButton("−"); rm.setFixedWidth(28)
            rm.clicked.connect(lambda _c=False, idx=i: self.remove_line(idx))
            rl.addWidget(rm); rl.addStretch()
            self.rows_layout.addWidget(row)

    def _update_field(self, index, key, value):
        if 0 <= index < len(self.lines):
            self.lines[index][key] = value
            if not self._suspend:
                self._on_change()

    def apply_to_axes(self, ax):
        for state in self.lines:
            value = to_float(state["value"])
            if value is None:
                continue
            orientation = REFLINE_ORI_MAP.get(state["orientation"], "h")
            linestyle = LINESTYLE_MAP.get(state["linestyle"], "--")
            if linestyle == "None":
                linestyle = "--"
            width = to_float(state["width"]) or 1.2
            label = state["label"].strip() or None
            if orientation == "h":
                ax.axhline(value, color=state["color"], linestyle=linestyle,
                           linewidth=width, label=label)
            else:
                ax.axvline(value, color=state["color"], linestyle=linestyle,
                           linewidth=width, label=label)

    def dump(self):
        return [{"orientation": REFLINE_ORI_MAP.get(s["orientation"], "h"),
                 "value": s["value"], "color": s["color"],
                 "linestyle": s["linestyle"], "width": s["width"],
                 "label": s["label"]} for s in self.lines]

    def load(self, blob_list):
        self._suspend = True
        self.lines.clear()
        for blob in blob_list or []:
            self.lines.append(self._new_state(blob))
        self._rebuild()
        self._suspend = False


# --------------------------------------------------------------------------
# Sets / cases
# --------------------------------------------------------------------------

SET_MODE_LABELS = {"shared": "Shared X", "pair": "Pair (X,Y per series)"}
SET_MODE_FROM_LABEL = {v: k for k, v in SET_MODE_LABELS.items()}


def _default_set(name="Set 1", mode="shared"):
    if mode == "pair":
        headers = ["Series 1 - X", "Series 1 - Y"]
    else:
        headers = ["X"] + [f"Series {i}" for i in range(1, DEFAULT_SERIES + 1)]
    return {"name": name, "mode": mode, "enabled": True, "headers": headers,
            "rows": [["" for _ in headers] for _ in range(DEFAULT_ROWS)]}


def _set_series_count(s):
    if s.get("mode") == "pair":
        return len(s["headers"]) // 2
    return max(len(s["headers"]) - 1, 0)


def _set_xy_cols(s, j):
    if s.get("mode") == "pair":
        return 2 * j, 2 * j + 1
    return 0, j + 1


class DataWindow(QDialog):
    def __init__(self, case, parent=None):
        super().__init__(parent)
        self.case = case
        self.setWindowTitle(f"Data - {case.name}")
        self.resize(880, 580)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        outer = QHBoxLayout(self); outer.setContentsMargins(8, 8, 8, 8)

        left = QWidget(); left_l = QVBoxLayout(left); left_l.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(_bold_label("SERIES SETS"))
        self.listbox = QListWidget(); self.listbox.setFixedWidth(200)
        self.listbox.currentRowChanged.connect(self._on_select)
        left_l.addWidget(self.listbox, 1)
        lb_btns = QHBoxLayout()
        for text, slot in (("+ Set", self._on_add), ("Rename", self._on_rename), ("Remove", self._on_remove)):
            b = QPushButton(text); b.clicked.connect(slot); lb_btns.addWidget(b)
        left_l.addLayout(lb_btns)
        outer.addWidget(left)

        right = QWidget(); right_l = QVBoxLayout(right); right_l.setContentsMargins(10, 0, 0, 0)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Set mode:"))
        self.mode_combo = QComboBox(); self.mode_combo.addItems(list(SET_MODE_LABELS.values()))
        self.mode_combo.currentTextChanged.connect(self._on_mode_change)
        mode_row.addWidget(self.mode_combo)
        self.mode_hint = QLabel(""); self.mode_hint.setStyleSheet("color: #666666;")
        mode_row.addWidget(self.mode_hint); mode_row.addStretch()
        right_l.addLayout(mode_row)

        self.grid_holder = QWidget()
        self.grid_holder_layout = QVBoxLayout(self.grid_holder)
        self.grid_holder_layout.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(self.grid_holder, 1)
        self.action_bar = QWidget()
        self.action_bar_layout = QHBoxLayout(self.action_bar)
        self.action_bar_layout.setContentsMargins(0, 6, 0, 0)
        right_l.addWidget(self.action_bar)
        outer.addWidget(right, 1)

        self._grid = None
        self._current_index = None
        self._suspend = False
        self.refresh_list()
        if self.case.sets:
            self.select(0)

    def closeEvent(self, event):
        event.ignore(); self.hide()

    def show(self):
        self.setVisible(True); self.raise_(); self.activateWindow()

    def refresh_list(self):
        self._suspend = True
        self.listbox.clear()
        for s in self.case.sets:
            self.listbox.addItem(s["name"])
        if self._current_index is not None and 0 <= self._current_index < len(self.case.sets):
            self.listbox.setCurrentRow(self._current_index)
        self._suspend = False

    def select(self, index):
        if not self.case.sets:
            self._teardown_grid(); self._current_index = None; return
        index = max(0, min(index, len(self.case.sets) - 1))
        self._suspend = True; self.listbox.setCurrentRow(index); self._suspend = False
        self._current_index = index
        self._show_grid(index)

    def _teardown_grid(self):
        if self._grid is not None:
            self._grid.setParent(None); self._grid.deleteLater(); self._grid = None
        _clear_layout(self.action_bar_layout)

    def _show_grid(self, index):
        self._teardown_grid()
        model = self.case.sets[index]
        mode = model.get("mode", "shared")
        self._suspend = True; self.mode_combo.setCurrentText(SET_MODE_LABELS[mode]); self._suspend = False
        self.mode_hint.setText(
            "Column 1 = X; other columns = Y series." if mode == "shared"
            else "Columns are pairs: Series 1-X, Series 1-Y, Series 2-X, ...")
        grid = DataGrid(model["headers"],
                        on_data_change=lambda: self._sync_from_grid(index, structure=False),
                        on_headers_change=lambda: self._sync_from_grid(index, structure=True))
        grid.load({"headers": model["headers"], "rows": model["rows"]})
        self.grid_holder_layout.addWidget(grid)
        self._grid = grid

        ab = self.action_bar_layout
        for text, slot in (("Paste", grid.paste_clipboard),
                           ("Copy", grid.copy_selection),
                           ("+20 rows", lambda: grid.add_rows(20)),
                           ("Del rows", grid.delete_selected_rows),
                           ("+ series", self._on_add_series),
                           ("- series", self._on_remove_series),
                           ("Clear", grid.clear_all)):
            b = QPushButton(text); b.clicked.connect(slot); ab.addWidget(b)
        ab.addStretch()

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
                QMessageBox.information(self, "Keep one series", "A set needs at least one X,Y pair.")
                return
            self._grid.remove_last_series_column()
            self._grid.remove_last_series_column()
        else:
            if not self._grid.remove_last_series_column():
                QMessageBox.information(self, "Keep one series", "A set needs at least one series column.")

    def _on_mode_change(self, _text=None):
        if self._suspend or self._current_index is None:
            return
        new_mode = SET_MODE_FROM_LABEL.get(self.mode_combo.currentText(), "shared")
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
        else:
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

    def _on_select(self, idx):
        if self._suspend or idx < 0:
            return
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
            QMessageBox.information(self, "Keep one set", "A case needs at least one series set.")
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
        text, ok = QInputDialog.getText(self, "Rename set", "New set name:",
                                        QLineEdit.EchoMode.Normal, current)
        if ok and text.strip():
            self.case.sets[idx]["name"] = text.strip()
            self.case.on_set_structure_changed()
            self.refresh_list()
            self._suspend = True; self.listbox.setCurrentRow(idx); self._suspend = False


# --------------------------------------------------------------------------
# CaseTab
# --------------------------------------------------------------------------

class CaseTab(QWidget):
    def __init__(self, app, name):
        super().__init__()
        self.app = app
        self.name = name
        self.sets = [_default_set()]
        self.series_states = []
        self._data_window = None
        self._suspend = False

        self.plot_type = PLOT_TYPES[0]
        self.title_text = name
        self.xlabel_text = "X"
        self.ylabel_text = "Y"
        self.grid_on = True
        self.legend_loc = "best"

        self._build_ui()
        self._sync_series_states()
        self._rebuild_series_rows()
        self._update_summary()
        self.redraw()

    def _build_ui(self):
        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal); root.addWidget(splitter)

        left = QWidget(); left.setMinimumWidth(280); left.setMaximumWidth(320)
        left_layout = QVBoxLayout(left); left_layout.setContentsMargins(0, 0, 6, 0)
        _, _, opts = make_scrollable(left_layout)

        opts.addWidget(_bold_label("PLOT TYPE"))
        self.plot_type_combo = QComboBox(); self.plot_type_combo.addItems(PLOT_TYPES)
        self.plot_type_combo.setCurrentText(self.plot_type)
        self.plot_type_combo.currentTextChanged.connect(self._on_plot_type_change)
        opts.addWidget(self.plot_type_combo); opts.addSpacing(6)

        opts.addWidget(_bold_label("LABELS"))
        lbl_frame = QFrame(); lbl_frame.setFrameShape(QFrame.Shape.StyledPanel)
        lbl_grid = QGridLayout(lbl_frame)
        lbl_grid.setContentsMargins(6, 6, 6, 6); lbl_grid.setHorizontalSpacing(6); lbl_grid.setVerticalSpacing(2)
        lbl_grid.addWidget(QLabel("Title"), 0, 0)
        self.title_edit = QLineEdit(self.title_text)
        self.title_edit.textChanged.connect(self._on_title_change)
        lbl_grid.addWidget(self.title_edit, 0, 1)
        lbl_grid.addWidget(QLabel("X label"), 1, 0)
        self.xlabel_edit = QLineEdit(self.xlabel_text)
        self.xlabel_edit.textChanged.connect(self._on_xlabel_change)
        lbl_grid.addWidget(self.xlabel_edit, 1, 1)
        lbl_grid.addWidget(QLabel("Y label"), 2, 0)
        self.ylabel_edit = QLineEdit(self.ylabel_text)
        self.ylabel_edit.textChanged.connect(self._on_ylabel_change)
        lbl_grid.addWidget(self.ylabel_edit, 2, 1)
        self.grid_cb = QCheckBox("Show grid"); self.grid_cb.setChecked(True)
        self.grid_cb.toggled.connect(self._on_grid_toggle)
        lbl_grid.addWidget(self.grid_cb, 3, 0, 1, 2)
        lbl_grid.addWidget(QLabel("Legend"), 4, 0)
        self.legend_combo = QComboBox(); self.legend_combo.addItems(LEGEND_LOCS)
        self.legend_combo.setCurrentText(self.legend_loc)
        self.legend_combo.currentTextChanged.connect(self._on_legend_change)
        lbl_grid.addWidget(self.legend_combo, 4, 1)
        lbl_grid.setColumnStretch(1, 1)
        opts.addWidget(lbl_frame); opts.addSpacing(6)

        opts.addWidget(_bold_label("AXES"))
        self.axis = AxisPanel(self._auto_xlim, self._auto_ylim, self.redraw)
        opts.addWidget(self.axis); opts.addSpacing(6)

        opts.addWidget(_bold_label("REFERENCE LINES"))
        self.reflines = RefLinesPanel(self.redraw)
        opts.addWidget(self.reflines); opts.addSpacing(6)

        opts.addWidget(_bold_label("EXPORT"))
        exp_frame = QFrame(); exp_frame.setFrameShape(QFrame.Shape.StyledPanel)
        exp_layout = QVBoxLayout(exp_frame); exp_layout.setContentsMargins(6, 6, 6, 6)
        for text, slot in (("Chart as image...", self.on_export_image),
                           ("Copy chart to clipboard", self.on_copy_image),
                           ("Data as CSV...", self.on_export_csv)):
            b = QPushButton(text); b.clicked.connect(slot); exp_layout.addWidget(b)
        opts.addWidget(exp_frame); opts.addStretch()
        splitter.addWidget(left)

        center = QWidget(); center_layout = QVBoxLayout(center); center_layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(7.5, 5.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_layout.addWidget(self.canvas, 1)
        self.toolbar = NavigationToolbar(self.canvas, center)
        center_layout.addWidget(self.toolbar)
        splitter.addWidget(center)

        right = QWidget(); right.setMinimumWidth(320); right.setMaximumWidth(400)
        right_layout = QVBoxLayout(right); right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(_bold_label("DATA"))
        blurb = QLabel("Each series set has its own X column. Open the data window to add sets and paste values.")
        blurb.setWordWrap(True); blurb.setStyleSheet("color: #666666;")
        right_layout.addWidget(blurb)
        data_row = QHBoxLayout()
        open_data_btn = QPushButton("Open data window...")
        open_data_btn.clicked.connect(self.open_data_window)
        data_row.addWidget(open_data_btn); data_row.addStretch()
        right_layout.addLayout(data_row)
        self.data_summary = QLabel(""); self.data_summary.setStyleSheet("color: #444444;")
        right_layout.addWidget(self.data_summary)

        right_layout.addWidget(_bold_label("SERIES"))
        series_frame = QFrame(); series_frame.setFrameShape(QFrame.Shape.StyledPanel)
        sf_layout = QVBoxLayout(series_frame); sf_layout.setContentsMargins(2, 2, 2, 2)
        _, _, self.series_layout = make_scrollable(sf_layout)
        right_layout.addWidget(series_frame, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 900, 340])

    def _on_plot_type_change(self, text): self.plot_type = text; self.redraw()
    def _on_title_change(self, text): self.title_text = text; self.redraw()
    def _on_xlabel_change(self, text): self.xlabel_text = text; self.redraw()
    def _on_ylabel_change(self, text): self.ylabel_text = text; self.redraw()
    def _on_grid_toggle(self, checked): self.grid_on = bool(checked); self.redraw()
    def _on_legend_change(self, text): self.legend_loc = text; self.redraw()

    def open_data_window(self):
        if self._data_window is None:
            self._data_window = DataWindow(self, parent=self.app)
        self._data_window.show()

    def on_set_data_changed(self):
        self._update_summary(); self.redraw()

    def on_set_structure_changed(self):
        self._sync_series_states(); self._rebuild_series_rows()
        self._update_summary(); self.redraw()

    def _update_summary(self):
        n_sets = len(self.sets)
        n_series = sum(max(len(s["headers"]) - 1, 0) for s in self.sets)
        self.data_summary.setText(f"{n_sets} set(s), {n_series} series")

    def _default_series_state(self, index, name):
        color = COLOR_CYCLE[index % len(COLOR_CYCLE)]
        return {"enabled": True, "name": name, "color": color,
                "linestyle": "solid", "marker": MARKER_OPTIONS[(index % 6) + 1],
                "width": "1.6", "size": "5", "fill": "Filled"}

    def _sync_series_states(self):
        self._suspend = True
        try:
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
                    header = (s["headers"][y_col] if y_col < len(s["headers"])
                              else f"Series {global_idx + j + 1}")
                    row.append(self._default_series_state(global_idx + j, header))
                del row[n_y:]
                for j, state in enumerate(row):
                    _, y_col = _set_xy_cols(s, j)
                    if y_col < len(s["headers"]):
                        hdr = s["headers"][y_col]
                        if hdr and hdr != state["name"]:
                            state["name"] = hdr
                global_idx += n_y
        finally:
            self._suspend = False

    def _rebuild_series_rows(self):
        _clear_layout(self.series_layout)
        total = sum(len(row) for row in self.series_states)
        if total == 0:
            lbl = QLabel("No series."); lbl.setStyleSheet("color: #888888; padding: 6px;")
            self.series_layout.addWidget(lbl); self.series_layout.addStretch()
            return

        for si, row in enumerate(self.series_states):
            if not row:
                continue
            set_model = self.sets[si]
            header_widget = QWidget()
            hl = QHBoxLayout(header_widget); hl.setContentsMargins(4, 4, 4, 0)
            enabled_cb = QCheckBox(); enabled_cb.setChecked(bool(set_model.get("enabled", True)))
            enabled_cb.toggled.connect(lambda checked, sm=set_model: self._on_set_enabled(sm, checked))
            hl.addWidget(enabled_cb)
            title_lbl = QLabel(set_model["name"])
            f = title_lbl.font(); f.setBold(True); title_lbl.setFont(f)
            title_lbl.setStyleSheet("color: #2A4F80;")
            hl.addWidget(title_lbl); hl.addStretch()
            self.series_layout.addWidget(header_widget)

            for j, state in enumerate(row):
                self.series_layout.addWidget(self._build_series_row(si, j, state))

            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFrameShadow(QFrame.Shadow.Sunken)
            self.series_layout.addWidget(sep)
        self.series_layout.addStretch()

    def _on_set_enabled(self, set_model, checked):
        if self._suspend:
            return
        set_model["enabled"] = bool(checked); self.redraw()

    def _build_series_row(self, si, j, state):
        box = QWidget()
        box_layout = QVBoxLayout(box); box_layout.setContentsMargins(4, 2, 4, 2); box_layout.setSpacing(2)

        top = QHBoxLayout(); top.setSpacing(4)
        enabled_cb = QCheckBox(); enabled_cb.setChecked(bool(state["enabled"]))
        enabled_cb.toggled.connect(lambda checked, ss=si, jj=j: self._update_state(ss, jj, "enabled", bool(checked)))
        top.addWidget(enabled_cb)
        swatch = SwatchLabel(state["color"], lambda ss=si, jj=j: self.on_pick_color(ss, jj))
        state["_swatch"] = swatch
        top.addWidget(swatch)
        hex_edit = QLineEdit(state["color"]); hex_edit.setFixedWidth(70)
        state["_hex_edit"] = hex_edit
        hex_edit.editingFinished.connect(lambda ss=si, jj=j: self._apply_hex_color(ss, jj))
        top.addWidget(hex_edit)
        name_edit = QLineEdit(state["name"])
        name_edit.textChanged.connect(lambda text, ss=si, jj=j: self._on_name_change(ss, jj, text))
        top.addWidget(name_edit, 1)
        box_layout.addLayout(top)

        bottom = QHBoxLayout(); bottom.setContentsMargins(24, 0, 0, 0); bottom.setSpacing(4)
        bottom.addWidget(QLabel("Line"))
        line_combo = QComboBox(); line_combo.addItems(LINESTYLE_OPTIONS); line_combo.setCurrentText(state["linestyle"])
        line_combo.currentTextChanged.connect(lambda text, ss=si, jj=j: self._update_state(ss, jj, "linestyle", text))
        bottom.addWidget(line_combo)
        bottom.addWidget(QLabel("Marker"))
        marker_combo = QComboBox(); marker_combo.addItems(MARKER_OPTIONS); marker_combo.setCurrentText(state["marker"])
        marker_combo.currentTextChanged.connect(lambda text, ss=si, jj=j: self._update_state(ss, jj, "marker", text))
        bottom.addWidget(marker_combo); bottom.addStretch()
        box_layout.addLayout(bottom)

        sizes = QHBoxLayout(); sizes.setContentsMargins(24, 0, 0, 0); sizes.setSpacing(4)
        sizes.addWidget(QLabel("Width"))
        width_edit = QLineEdit(str(state["width"])); width_edit.setFixedWidth(50)
        width_edit.textChanged.connect(lambda text, ss=si, jj=j: self._update_state(ss, jj, "width", text))
        sizes.addWidget(width_edit)
        sizes.addWidget(QLabel("Mkr size"))
        size_edit = QLineEdit(str(state["size"])); size_edit.setFixedWidth(50)
        size_edit.textChanged.connect(lambda text, ss=si, jj=j: self._update_state(ss, jj, "size", text))
        sizes.addWidget(size_edit)
        sizes.addWidget(QLabel("Fill"))
        fill_combo = QComboBox(); fill_combo.addItems(FILL_OPTIONS); fill_combo.setCurrentText(state["fill"])
        fill_combo.currentTextChanged.connect(lambda text, ss=si, jj=j: self._update_state(ss, jj, "fill", text))
        sizes.addWidget(fill_combo); sizes.addStretch()
        box_layout.addLayout(sizes)
        return box

    def _update_state(self, si, j, key, value):
        if self._suspend or si >= len(self.series_states) or j >= len(self.series_states[si]):
            return
        self.series_states[si][j][key] = value
        self.redraw()

    def _on_name_change(self, si, j, text):
        if self._suspend or si >= len(self.series_states) or j >= len(self.series_states[si]):
            return
        self.series_states[si][j]["name"] = text
        if si >= len(self.sets):
            return
        _, header_idx = _set_xy_cols(self.sets[si], j)
        if header_idx < len(self.sets[si]["headers"]):
            self.sets[si]["headers"][header_idx] = text
            if (self._data_window is not None and self._data_window.isVisible()
                    and self._data_window._current_index == si
                    and self._data_window._grid is not None):
                self._data_window._grid.set_header(header_idx, text)
        self.redraw()

    def on_pick_color(self, si, j):
        state = self.series_states[si][j]
        col = QColorDialog.getColor(QColor(state["color"]), self, "Series colour")
        if not col.isValid():
            return
        state["color"] = col.name()
        if "_swatch" in state:
            _set_swatch_color(state["_swatch"], state["color"])
        if "_hex_edit" in state:
            state["_hex_edit"].blockSignals(True)
            state["_hex_edit"].setText(state["color"])
            state["_hex_edit"].blockSignals(False)
        self.redraw()

    def _apply_hex_color(self, si, j):
        state = self.series_states[si][j]
        if "_hex_edit" not in state:
            return
        raw = state["_hex_edit"].text().strip()
        val = raw if raw.startswith("#") else f"#{raw}"
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", val):
            state["_hex_edit"].blockSignals(True); state["_hex_edit"].setText(state["color"]); state["_hex_edit"].blockSignals(False)
            return
        val = val.lower()
        state["color"] = val
        if "_swatch" in state:
            _set_swatch_color(state["_swatch"], val)
        state["_hex_edit"].blockSignals(True); state["_hex_edit"].setText(val); state["_hex_edit"].blockSignals(False)
        self.redraw()

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
                if not state["enabled"]:
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
                    out.append((state["name"] or f"Series {j + 1}", xs, ys, state))

            labels = ([str(v).strip() if str(v).strip() else str(i + 1)
                       for i, v in enumerate(x_raw)]
                      if (categorical or not has_x) else [])
            return labels, (categorical or not has_x), out

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
                if not state["enabled"]:
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
                    xs.append(x); ys.append(y)
                if ys:
                    out.append((state["name"] or f"Series {j + 1}", xs, ys, state))
        return [], False, out

    def _auto_xlim(self):
        _, categorical, series = self.plotted_series()
        if categorical or not series:
            return (None, None)
        values = [v for _, xs, _, _ in series for v in xs]
        if not values:
            return (None, None)
        lo, hi = min(values), max(values)
        if self.axis.x_scale == "log":
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
        if self.axis.y_scale == "log":
            positive = [v for v in values if v > 0]
            if not positive:
                return (None, None)
            return (10 ** math.floor(math.log10(min(positive))),
                    10 ** math.ceil(math.log10(max(positive))))
        if self.plot_type in BAR_TYPES or self.plot_type == "Area (filled)":
            lo = min(0.0, lo)
        if lo == hi:
            pad = abs(lo) * 0.1 or 1.0
            return (lo - pad, hi + pad)
        pad = (hi - lo) * 0.08
        return (lo - pad if lo != 0 else 0.0, hi + pad)

    def redraw(self, *_):
        if self._suspend:
            return
        family = self.app.font_family_value() or DEFAULT_FONT
        base = self.app.font_size_value()
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = [family, "Helvetica", "DejaVu Sans"]
        matplotlib.rcParams["font.size"] = base

        self.ax.clear()
        labels, categorical, series = self.plotted_series()
        ptype = self.plot_type
        horizontal = ptype == "Bar (horizontal)"

        if not series:
            self.ax.text(0.5, 0.5, "Paste data into the table to draw a plot",
                         transform=self.ax.transAxes, ha="center", va="center",
                         fontsize=base, color="gray", fontname=family)
            self.ax.set_xticks([]); self.ax.set_yticks([])
        elif ptype in BAR_TYPES:
            self._draw_bars(series, labels, categorical, ptype)
        else:
            self._draw_lines(series, ptype)

        if series:
            if ptype in BAR_TYPES:
                self._apply_bar_axes(horizontal)
            else:
                self.axis.apply_to_axes(self.ax, categorical_x=categorical)
                if categorical and labels:
                    positions = sorted({int(v) for _, xs, _, _ in series for v in xs})
                    self.ax.set_xticks(positions)
                    self.ax.set_xticklabels([labels[p] if p < len(labels) else "" for p in positions])

        title = self.title_text.strip()
        if title:
            self.ax.set_title(mathify(title), fontname=family, fontsize=base + 2, fontweight="bold")
        xl, yl = self.xlabel_text.strip(), self.ylabel_text.strip()
        if horizontal:
            xl, yl = yl, xl
        self.ax.set_xlabel(mathify(xl), fontname=family, fontsize=base)
        self.ax.set_ylabel(mathify(yl), fontname=family, fontsize=base)
        for lab in self.ax.get_xticklabels() + self.ax.get_yticklabels():
            lab.set_fontname(family); lab.set_fontsize(base - 1)

        if self.grid_on:
            self.ax.grid(True, which="both", linestyle=":", linewidth=0.6, alpha=0.7)
        else:
            self.ax.grid(False)

        self.reflines.apply_to_axes(self.ax)

        loc = self.legend_loc
        if loc != "off" and self.ax.get_legend_handles_labels()[0]:
            self.ax.legend(loc=loc, fontsize=base - 1, framealpha=0.9,
                           prop={"family": family, "size": base - 1})

        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw_idle()

    def _style_of(self, state):
        linestyle = LINESTYLE_MAP.get(state["linestyle"], "-")
        marker = MARKER_MAP.get(state["marker"], "None")
        width = to_float(state["width"]) or 1.6
        size = to_float(state["size"]) or 5.0
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

    def _draw_lines(self, series, ptype):
        for name, xs, ys, state in series:
            linestyle, marker, width, size = self._style_of(state)
            if ptype == "Line only":
                marker = "None"
            elif ptype == "Scatter only":
                linestyle = "None"
                if marker == "None":
                    marker = "o"
            color = state["color"]
            fill_kw = self._marker_fill_kwargs(state["fill"], color, width)

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

    def _draw_bars(self, series, labels, categorical, ptype):
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
            hollow = state["fill"] != "Filled"
            face = "none" if hollow else state["color"]
            edge = state["color"] if hollow else "white"
            edge_w = 1.2 if hollow else 0.6
            if ptype == "Bar (stacked)":
                self.ax.bar(base_pos, heights, width=span, bottom=bottoms,
                            label=name, color=face, edgecolor=edge, linewidth=edge_w)
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
            self.ax.set_yticks(ticks); self.ax.set_yticklabels(tick_labels)
        else:
            self.ax.set_xticks(ticks); self.ax.set_xticklabels(tick_labels)

    def _apply_bar_axes(self, horizontal):
        lo, hi = self._auto_ylim()
        if not self.axis.y_auto and self.axis.custom_ylim:
            lo, hi = self.axis.custom_ylim
        else:
            if lo is not None: self.axis.y_min_edit.setText(fmt_num(lo))
            if hi is not None: self.axis.y_max_edit.setText(fmt_num(hi))
        scale = self.axis.y_scale
        if horizontal:
            self.ax.set_xscale(scale)
            if lo is not None and hi is not None and lo < hi:
                self.ax.set_xlim(lo, hi)
        else:
            self.ax.set_yscale(scale)
            if lo is not None and hi is not None and lo < hi:
                self.ax.set_ylim(lo, hi)

    def on_export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export chart as image", f"{self.name}.png",
            "PNG image (*.png);;PDF document (*.pdf);;SVG image (*.svg);;"
            "JPEG image (*.jpg);;TIFF image (*.tif);;All files (*.*)")
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=300, bbox_inches="tight")
            QMessageBox.information(self, "Export complete", f"Chart saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def on_copy_image(self):
        """Render the chart to PNG and place it on the system clipboard via
        QApplication.clipboard() — pure Qt, no external process."""
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            self.fig.savefig(tmp, dpi=300, bbox_inches="tight")
            image = QImage(tmp)
            if image.isNull():
                raise RuntimeError(f"Could not read rendered PNG at {tmp}")
            QApplication.clipboard().setImage(image)
            self.app.set_status("Chart copied to clipboard.")
        except Exception as exc:
            QMessageBox.critical(self, "Copy failed", str(exc))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def on_export_csv(self):
        if not any(self._set_used_rows(s) for s in self.sets):
            QMessageBox.warning(self, "Nothing to export", "All sets are empty.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export data as CSV", f"{self.name}.csv",
            "CSV file (*.csv);;All files (*.*)")
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
                            headers[y_col] = state["name"]
                    writer.writerow(headers)
                    n = self._set_used_rows(s)
                    for row in s["rows"][:n]:
                        writer.writerow(row)
            QMessageBox.information(self, "Export complete", f"Data saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def dump(self):
        return {
            "name": self.name, "plot_type": self.plot_type,
            "title": self.title_text, "xlabel": self.xlabel_text, "ylabel": self.ylabel_text,
            "grid": self.grid_on, "legend": self.legend_loc,
            "axis": self.axis.dump(), "reflines": self.reflines.dump(),
            "sets": [{"name": s["name"], "mode": s.get("mode", "shared"),
                      "enabled": bool(s.get("enabled", True)),
                      "headers": list(s["headers"]),
                      "rows": [list(r) for r in s["rows"][:max(self._set_used_rows(s), 1)]]}
                     for s in self.sets],
            "series": [[{"enabled": st["enabled"], "name": st["name"],
                         "color": st["color"], "linestyle": st["linestyle"],
                         "marker": st["marker"], "width": st["width"],
                         "size": st["size"], "fill": st["fill"]}
                        for st in row] for row in self.series_states],
        }

    def load(self, blob):
        self._suspend = True
        try:
            self.name = blob.get("name", self.name)

            self.plot_type = blob.get("plot_type", PLOT_TYPES[0])
            self.plot_type_combo.blockSignals(True); self.plot_type_combo.setCurrentText(self.plot_type); self.plot_type_combo.blockSignals(False)

            self.title_text = blob.get("title", self.name)
            self.title_edit.blockSignals(True); self.title_edit.setText(self.title_text); self.title_edit.blockSignals(False)

            self.xlabel_text = blob.get("xlabel", "X")
            self.xlabel_edit.blockSignals(True); self.xlabel_edit.setText(self.xlabel_text); self.xlabel_edit.blockSignals(False)

            self.ylabel_text = blob.get("ylabel", "Y")
            self.ylabel_edit.blockSignals(True); self.ylabel_edit.setText(self.ylabel_text); self.ylabel_edit.blockSignals(False)

            self.grid_on = bool(blob.get("grid", True))
            self.grid_cb.blockSignals(True); self.grid_cb.setChecked(self.grid_on); self.grid_cb.blockSignals(False)

            self.legend_loc = blob.get("legend", "best")
            self.legend_combo.blockSignals(True); self.legend_combo.setCurrentText(self.legend_loc); self.legend_combo.blockSignals(False)

            if "sets" in blob:
                raw_sets = blob["sets"]
            elif "table" in blob:
                t = blob["table"] or {}
                raw_sets = [{"name": "Set 1", "headers": t.get("headers", ["X", "Series 1"]),
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
                saved_series = [saved_series]
            for si, row in enumerate(self.series_states):
                saved_row = saved_series[si] if si < len(saved_series) else []
                for j, state in enumerate(row):
                    if j >= len(saved_row):
                        continue
                    saved = saved_row[j]
                    state["enabled"] = bool(saved.get("enabled", True))
                    state["name"] = saved.get("name", state["name"])
                    state["color"] = saved.get("color", state["color"])
                    state["linestyle"] = saved.get("linestyle", "solid")
                    state["marker"] = saved.get("marker", "circle")
                    state["width"] = str(saved.get("width", "1.6"))
                    state["size"] = str(saved.get("size", "5"))
                    state["fill"] = saved.get("fill", "Filled")

            self.axis.load(blob.get("axis", {}))
            self.reflines.load(blob.get("reflines", []))
        finally:
            self._suspend = False
        self._rebuild_series_rows()
        self._update_summary()
        self.redraw()


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------

class PlottingToolApp(QMainWindow):
    """Accepts an optional positional arg for backwards compatibility with
    the old ``PlottingToolApp(root)`` signature; ignored under Qt.

    ``embedded=True`` is for hosting the window inside a QGIS dock: it does
    not size or maximise itself and allows a smaller minimum size so the
    dock can sit against the side of QGIS.
    """

    def __init__(self, _ignored=None, parent=None, embedded=False):
        super().__init__(parent)
        self.cases = []
        self._case_counter = 0
        self.project_path = None

        self.setWindowTitle(APP_TITLE)
        if embedded:
            self.setMinimumSize(640, 420)
        else:
            self.resize(1900, 1080)
            self.setMinimumSize(1150, 680)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(10, 8, 10, 10)

        self._status_text = "Paste data from Excel with Ctrl+V into the table."
        self._build_toolbar(root)

        self.notebook = QTabWidget()
        self.notebook.tabBarDoubleClicked.connect(self._on_tab_double_click)
        root.addWidget(self.notebook, 1)

        self.add_case()
        if not embedded:
            try:
                self.showMaximized()
            except Exception:
                pass

    def _build_toolbar(self, parent_layout):
        bar = QWidget()
        bl = QHBoxLayout(bar); bl.setContentsMargins(0, 0, 0, 4); bl.setSpacing(4)

        bl.addWidget(_bold_label("CASES"))
        for text, slot in (("New case", self.add_case), ("Duplicate", self.duplicate_case),
                           ("Rename", self.rename_case), ("Delete", self.delete_case)):
            btn = QPushButton(text); btn.clicked.connect(slot); bl.addWidget(btn)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.VLine); sep.setFrameShadow(QFrame.Shadow.Sunken); bl.addWidget(sep)

        bl.addWidget(_bold_label("FONT"))
        self.font_family_combo = QComboBox(); self.font_family_combo.setEditable(True)
        self.font_family_combo.addItems(FONT_CHOICES); self.font_family_combo.setCurrentText(DEFAULT_FONT)
        self.font_family_combo.currentTextChanged.connect(lambda _t: self.redraw_all())
        bl.addWidget(self.font_family_combo)
        bl.addWidget(QLabel("size"))
        self.font_size_spin = QSpinBox(); self.font_size_spin.setRange(6, 28)
        self.font_size_spin.setValue(DEFAULT_FONT_SIZE)
        self.font_size_spin.valueChanged.connect(lambda _v: self.redraw_all())
        bl.addWidget(self.font_size_spin)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.VLine); sep2.setFrameShadow(QFrame.Shadow.Sunken); bl.addWidget(sep2)

        bl.addWidget(_bold_label("PROJECT"))
        for text, slot in (("Open...", self.open_project),
                           ("Save", self.save_project_current),
                           ("Save as...", self.save_project)):
            btn = QPushButton(text); btn.clicked.connect(slot); bl.addWidget(btn)

        bl.addStretch()
        self.status_label = QLabel(self._status_text)
        self.status_label.setStyleSheet("color: #666666;")
        bl.addWidget(self.status_label)
        parent_layout.addWidget(bar)

    def font_family_value(self):
        return self.font_family_combo.currentText().strip() or DEFAULT_FONT

    def font_size_value(self):
        return int(self.font_size_spin.value())

    def set_status(self, text):
        self._status_text = text
        self.status_label.setText(text)

    def redraw_all(self):
        for case in self.cases:
            case.redraw()

    def add_case(self, name=None):
        self._case_counter += 1
        if not isinstance(name, str):
            name = None
        name = name or f"Case {self._case_counter}"
        case = CaseTab(self, name)
        self.cases.append(case)
        self.notebook.addTab(case, name)
        self.notebook.setCurrentWidget(case)
        return case

    def current_case(self):
        w = self.notebook.currentWidget()
        for case in self.cases:
            if case is w:
                return case
        return None

    def duplicate_case(self):
        case = self.current_case()
        if not case:
            return
        blob = case.dump()
        new_case = self.add_case(f"{case.name} copy")
        blob["name"] = new_case.name
        new_case.load(blob)
        self.notebook.setTabText(self.notebook.indexOf(new_case), new_case.name)

    def rename_case(self):
        case = self.current_case()
        if not case:
            return
        text, ok = QInputDialog.getText(self, "Rename case", "Case name:",
                                        QLineEdit.EchoMode.Normal, case.name)
        if not ok or not text.strip():
            return
        case.name = text.strip()
        self.notebook.setTabText(self.notebook.indexOf(case), case.name)
        if not case.title_text.strip() or case.title_text.startswith("Case "):
            case.title_text = case.name
            case.title_edit.blockSignals(True); case.title_edit.setText(case.name); case.title_edit.blockSignals(False)
            case.redraw()

    def delete_case(self):
        case = self.current_case()
        if not case:
            return
        if len(self.cases) == 1:
            QMessageBox.information(self, "Keep one case", "At least one case has to stay open.")
            return
        if QMessageBox.question(self, "Delete case",
                                f"Delete '{case.name}' and its data?") != QMessageBox.StandardButton.Yes:
            return
        idx = self.notebook.indexOf(case)
        self.notebook.removeTab(idx)
        self.cases.remove(case)
        case.deleteLater()

    def _on_tab_double_click(self, _index):
        self.rename_case()

    def save_project_current(self):
        if self.project_path:
            self._write_project(str(self.project_path))
        else:
            self.save_project()

    def save_project(self):
        initial = self.project_path.name if self.project_path else f"plots{PROJECT_EXT}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", initial,
            "JSON project (*.json);;Legacy .plotproj (*.plotproj);;All files (*.*)")
        if not path:
            return
        self._write_project(path)

    def _write_project(self, path):
        blob = {"version": 1,
                "font": {"family": self.font_family_value(),
                         "size": str(self.font_size_value())},
                "cases": [case.dump() for case in self.cases]}
        try:
            Path(path).write_text(json.dumps(blob, indent=2), encoding="utf-8")
            self.project_path = Path(path)
            self.setWindowTitle(f"{APP_TITLE} - {self.project_path.name}")
            self.set_status(f"Saved to {Path(path).name}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def open_project(self, path=None):
        if not isinstance(path, str):
            path = None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open project", "",
                "JSON project (*.json);;Legacy .plotproj (*.plotproj);;All files (*.*)")
        if not path:
            return
        try:
            blob = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return

        while self.notebook.count():
            w = self.notebook.widget(0)
            self.notebook.removeTab(0)
            if w is not None:
                w.deleteLater()
        self.cases.clear()
        self._case_counter = 0

        font = blob.get("font", {})
        self.font_family_combo.blockSignals(True)
        self.font_family_combo.setCurrentText(font.get("family", DEFAULT_FONT))
        self.font_family_combo.blockSignals(False)
        self.font_size_spin.blockSignals(True)
        try:
            self.font_size_spin.setValue(int(font.get("size", DEFAULT_FONT_SIZE)))
        except (TypeError, ValueError):
            self.font_size_spin.setValue(DEFAULT_FONT_SIZE)
        self.font_size_spin.blockSignals(False)

        for case_blob in blob.get("cases", []) or [{}]:
            case = self.add_case(case_blob.get("name"))
            case.load(case_blob)
            self.notebook.setTabText(self.notebook.indexOf(case), case.name)

        if not self.cases:
            self.add_case()
        self.project_path = Path(path)
        self.setWindowTitle(f"{APP_TITLE} - {self.project_path.name}")
        self.set_status(f"Loaded {self.project_path.name}")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = PlottingToolApp()
    if len(sys.argv) > 1:
        win.open_project(sys.argv[1])
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
