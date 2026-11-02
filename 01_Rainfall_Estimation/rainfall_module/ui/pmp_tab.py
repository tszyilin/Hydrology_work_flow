"""PMP tab — nests the vendored ``pmp_toolbox``'s three method tabs.

The pmp_toolbox package is vendored under ``rainfall_module/pmp_toolbox/``
verbatim. Its tabs already implement their own cases sidebar and inputs,
because pmp_toolbox is a full standalone plugin. We do NOT bind them to the
outer catchment yet — that's a bigger refactor. For now this tab just gives
you the three methods living in the same dock.
"""
from __future__ import annotations

from ....qt_compat import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class _PreviewOwner:
    """Minimal owner for ArealGsdmTab's preview dialog — lazy-created on demand."""

    def __init__(self, iface):
        self._iface = iface
        self._preview = None

    def preview_window(self):
        if self._preview is None:
            from ..pmp_toolbox.preview import SearchPreviewDialog
            parent = self._iface.mainWindow() if self._iface is not None else None
            self._preview = SearchPreviewDialog(parent)
        return self._preview

    def close(self):
        if self._preview is not None:
            try:
                self._preview.close()
            except Exception:
                pass
            self._preview = None


class PmpTab(QWidget):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._preview_owner = _PreviewOwner(iface)
        self._built = False
        self._pmp_tabs: list = []       # [(name, widget_with_picker), ...]
        self._pending_catchment = None  # applied on first show
        self._build_placeholder()

    def _build_placeholder(self):
        layout = QVBoxLayout(self)
        self._layout = layout
        self._info = QLabel(
            "PMP methods (vendored from pmp_toolbox). Loading on first view…"
        )
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._built:
            self._build_tabs()

    def _build_tabs(self):
        try:
            from ..pmp_toolbox.tabs.gsdm_tab import GsdmTab
            from ..pmp_toolbox.tabs.areal_gsdm_tab import ArealGsdmTab
            from ..pmp_toolbox.tabs.gtsmr_tab import GtsmrTab
        except Exception as exc:
            self._info.setText(
                "Could not load the vendored pmp_toolbox: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        # Replace the placeholder label with the real tabs.
        self._info.deleteLater()

        tabs = QTabWidget()
        for label, factory in [
            ("GSDM",         lambda: GsdmTab()),
            ("Areal GSDM",   lambda: ArealGsdmTab(self.iface, preview_owner=self._preview_owner)),
            ("GTSMR / GSAM", lambda: GtsmrTab()),
        ]:
            try:
                w = factory()
                tabs.addTab(w, label)
                # Each PMP tab exposes its picker as ``self.picker`` — that's
                # where our outer-catchment binding lands.
                if hasattr(w, "picker") and hasattr(w.picker, "set_external_location"):
                    self._pmp_tabs.append((label, w))
            except Exception as exc:
                tabs.addTab(_error_widget(label, exc), label)

        self._layout.addWidget(tabs, 1)
        self._built = True
        if self._pending_catchment is not None:
            self._apply_catchment(self._pending_catchment)
            self._pending_catchment = None

    # Called by the outer RainfallDialog whenever the selected catchment
    # changes. Delays the propagation until the tabs are built (first show).
    def set_catchment(self, cat):
        if not self._built:
            self._pending_catchment = cat
            return
        self._apply_catchment(cat)

    def _apply_catchment(self, cat):
        if cat is None or not cat.has_location():
            for _, w in self._pmp_tabs:
                try:
                    w.picker.set_external_location(None, None, None)
                except Exception:
                    pass
            return
        for _, w in self._pmp_tabs:
            try:
                w.picker.set_external_location(cat.name, cat.lat, cat.lon)
            except Exception:
                pass


def _error_widget(name, exc):
    w = QWidget()
    v = QVBoxLayout(w)
    lbl = QLabel(f"Could not build the {name} tab:\n{type(exc).__name__}: {exc}")
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    return w
