"""The rainfall colour ramp, kept free of QGIS imports.

``styling`` renders the output layers and ``preview`` paints the live search
view; both must agree, and the preview must stay importable with nothing but Qt.
Holding the ramp here lets each import it without dragging in the other.
"""

from __future__ import annotations

#: Wet to dry, colour-blind safe and legible in both light and dark canvases.
#: Index 0 is ellipse A, the innermost and wettest.
RAMP = [
    "#08306b", "#0b4a8f", "#1864ab", "#2b7bba", "#4292c6",
    "#6baed6", "#9ecae1", "#c6dbef", "#deebf7", "#f7fbff",
]

#: The template outline colour, shared by the output layer renderer and the
#: preview's highlight of the enclosing ellipse.
OUTLINE = "#c92a2a"


def ramp_colour(index: int) -> str:
    return RAMP[min(max(index, 0), len(RAMP) - 1)]
