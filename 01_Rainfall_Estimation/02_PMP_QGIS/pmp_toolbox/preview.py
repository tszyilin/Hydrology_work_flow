"""A live view of the placement search.

GSDM Step 1 asks an analyst to overlay the Figure 6 template on a catchment map
and shuffle it about by hand.  ``optimiser`` does that numerically, but silently
-- the user sees a progress bar and then two finished layers.  This window shows
the shuffling: the catchment outline holds still while the ten-ellipse template
sweeps and rotates through candidate placements, the best so far ghosted behind
the current one.  When the run ends it switches to the final placement with the
rainfall rings shaded, and the recorded trials can be replayed.

Only Qt is imported here, never ``qgis.core``: the geometry arrives as plain
``(n, 2)`` coordinate arrays from :func:`qgis_bridge.geometry_polygons`.

The search runs on the GUI thread, so this class is also the observer.  It
throttles repainting to a frame rate -- the coarse sweep alone is thousands of
candidates -- and pumps the event loop itself so Pause and Cancel stay live.
"""

from __future__ import annotations

import math
import time
import traceback

import numpy as np
from qgis.PyQt.QtCore import QPointF, Qt, QThread, QTimer
from qgis.PyQt.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .core import ellipses
from .core.optimiser import SearchCancelled
from .palette import OUTLINE, ramp_colour

#: Vertices per ellipse.  The output geometry uses 180; at screen scale 72 is
#: indistinguishable and a fifth of the work, which matters at 20 frames a
#: second with ten ellipses redrawn each frame.
SEGMENTS = 72

#: Widget margin in pixels around the mapped area.
MARGIN = 14

#: Pump the event loop at least this often even when not repainting, so Cancel
#: still responds while the search runs at full speed.
PUMP_EVERY = 250

#: Darkest ramp entry used for ellipse *outlines*; beyond it the ramp is too
#: pale to read as a line.
_LINE_RAMP_FLOOR = 5

_BACKGROUND = QColor("#f4f7fa")
_CATCHMENT_FILL = QColor("#c9d6e2")
_CATCHMENT_LINE = QColor("#2f4858")
_GHOST = QColor(40, 40, 40, 70)
_HUD_BACKGROUND = QColor(255, 255, 255, 215)


class _Canvas(QWidget):
    """Paints the catchment, the current template, and the final rings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(440, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.catchment: list[list[np.ndarray]] = []
        self.current: tuple[float, float, float, int] | None = None
        self.best: tuple[float, float, float, int] | None = None
        self.final: list[tuple[str, float | None, list[list[np.ndarray]]]] = []
        self.show_final = False
        self.hud: list[str] = []
        #: Set by paintEvent if drawing ever raised; the tests assert it stays None.
        self._failure: str | None = None
        self._bounds: tuple[float, float, float, float] | None = None
        self._draw_to = len(ellipses.LABELS) - 1
        self._path = None
        self._path_key = None

    # ------------------------------------------------------------------ setup

    def set_catchment(self, polygons: list[list[np.ndarray]]) -> None:
        """Frame the view once, from the catchment and the template it needs."""
        self.catchment = polygons
        points = np.vstack([ring for polygon in polygons for ring in polygon])
        xmin, ymin = points.min(axis=0)
        xmax, ymax = points.max(axis=0)
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        radius = math.hypot(xmax - xmin, ymax - ymin) / 2.0

        # Show one ellipse more than the catchment needs: enough context to see
        # the fit, without ellipse J's 23 km semi-major axis shrinking a 12 km
        # catchment to a dot.  A search that reaches further expands the view.
        self._fits = min(
            int(np.searchsorted(ellipses.SEMI_MINOR_M, radius)),
            len(ellipses.LABELS) - 1,
        )
        self._frame(cx, cy, min(self._fits + 1, len(ellipses.LABELS) - 1), radius)

    def _frame(self, cx: float, cy: float, draw_to: int, radius: float) -> None:
        self._draw_to = draw_to
        pad = max(ellipses.SEMI_MAJOR_M[draw_to] * 1.08, radius * 1.15)
        self._bounds = (cx - pad, cy - pad, cx + pad, cy + pad)
        self._centre = (cx, cy)
        self._radius = radius
        # Both halves of the cache, or paintEvent finds a matching key and a
        # path of None -- and an exception raised in a Qt virtual method takes
        # the whole process down rather than surfacing as a traceback.
        self._path = None
        self._path_key = None

    def frame_for(self, k: int) -> None:
        """Fit the view to the enclosing ellipse ``k``, never tighter than the
        catchment itself needs.

        Called only for the best placement so far.  Because the objective
        minimises ``k`` before anything else, the best ``k`` never grows, so the
        view tightens a handful of times as the search improves and then holds
        still -- rather than following every wild early candidate.

        ``k == OUTSIDE`` means the catchment escapes the template altogether;
        those would zoom out to ellipse J and stay there, so they are ignored.
        """
        if self._bounds is None or k >= len(ellipses.LABELS):
            return
        draw_to = min(max(k, self._fits), len(ellipses.LABELS) - 1)
        if draw_to != self._draw_to:
            self._frame(*self._centre, draw_to, self._radius)

    # ------------------------------------------------------------- projection

    def _transform(self):
        """``(scale, ox, oy)`` mapping map metres to widget pixels, y flipped."""
        xmin, ymin, xmax, ymax = self._bounds
        width = max(self.width() - 2 * MARGIN, 1)
        height = max(self.height() - 2 * MARGIN, 1)
        scale = min(width / max(xmax - xmin, 1e-9), height / max(ymax - ymin, 1e-9))
        ox = MARGIN + (width - (xmax - xmin) * scale) / 2.0
        oy = MARGIN + (height - (ymax - ymin) * scale) / 2.0 + (ymax - ymin) * scale
        return scale, ox, oy

    def _polygon(self, points: np.ndarray, transform) -> QPolygonF:
        scale, ox, oy = transform
        xmin, ymin, _xmax, _ymax = self._bounds
        sx = ox + (points[:, 0] - xmin) * scale
        sy = oy - (points[:, 1] - ymin) * scale
        return QPolygonF([QPointF(x, y) for x, y in zip(sx, sy)])

    def _path_for(self, polygons, transform) -> QPainterPath:
        """One path per feature, odd-even filled so holes stay holes."""
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        for polygon in polygons:
            for ring in polygon:
                path.addPolygon(self._polygon(ring, transform))
                path.closeSubpath()
        return path

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event):  # noqa: N802 -- Qt API
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception as exc:  # noqa: BLE0001 -- see below
            # PyQt turns an escaped exception in a virtual method into a hard
            # abort, which would take QGIS down with it.  A preview that cannot
            # draw is a nuisance; a QGIS that dies mid-run loses the user's work.
            self._failure = f"{type(exc).__name__}: {exc}"
            painter.setPen(QPen(_CATCHMENT_LINE, 1.0))
            painter.drawText(MARGIN, MARGIN + 12, f"Preview failed: {self._failure}")
            traceback.print_exc()
        finally:
            painter.end()

    def _paint(self, painter):
        painter.fillRect(self.rect(), _BACKGROUND)
        if self._bounds is None or not self.catchment:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        transform = self._transform()

        key = (transform, self.width(), self.height())
        if self._path is None or self._path_key != key:
            self._path = self._path_for(self.catchment, transform)
            self._path_key = key

        painter.fillPath(self._path, _CATCHMENT_FILL)
        if self.show_final and self.final:
            self._paint_final(painter, transform)
        painter.strokePath(self._path, QPen(_CATCHMENT_LINE, 1.6))

        if self.best is not None and self.best != self.current:
            self._paint_template(painter, transform, self.best, ghost=True)
        if self.current is not None:
            self._paint_template(painter, transform, self.current, ghost=False)

        self._paint_scale_bar(painter, transform)
        self._paint_hud(painter)

    def _paint_final(self, painter, transform):
        for index, (_label, _mrd, polygons) in enumerate(self.final):
            if not polygons:
                continue
            painter.fillPath(
                self._path_for(polygons, transform), QColor(ramp_colour(index))
            )

    def _paint_template(self, painter, transform, placement, ghost: bool):
        cx, cy, theta, k = placement
        # The ghost is context, not the subject: its innermost and enclosing
        # ellipses say where the best fit sat without ten more dashed rings.
        upto = min(self._draw_to, len(ellipses.LABELS) - 1)
        indices = sorted({0, min(k, upto)}) if ghost else range(upto + 1)
        for index in indices:
            points = ellipses.polygon(
                cx, cy, theta, ellipses.AREAS_KM2[index], SEGMENTS
            )
            if ghost:
                pen = QPen(_GHOST, 1.0, Qt.PenStyle.DashLine)
            elif index == k:
                pen = QPen(QColor(OUTLINE), 2.6)
            elif self.show_final:
                # Over the shaded rings the ramp colour is the fill colour, so
                # an outline drawn in it disappears.
                pen = QPen(QColor(255, 255, 255, 190), 1.2)
            else:
                # The dry end of the ramp is near white -- fine as a fill over
                # the catchment, invisible as a line on the background.
                pen = QPen(QColor(ramp_colour(min(index, _LINE_RAMP_FLOOR))), 1.3)
            painter.setPen(pen)
            polygon = self._polygon(points, transform)
            painter.drawPolyline(polygon)
            if self.show_final and not ghost:
                self._label_ellipse(painter, polygon, index)

        if not ghost:
            scale, ox, oy = transform
            xmin, ymin, _x, _y = self._bounds
            px, py = ox + (cx - xmin) * scale, oy - (cy - ymin) * scale
            painter.setPen(QPen(QColor(OUTLINE), 1.4))
            painter.drawLine(QPointF(px - 6, py), QPointF(px + 6, py))
            painter.drawLine(QPointF(px, py - 6), QPointF(px, py + 6))

    def _label_ellipse(self, painter, polygon, index):
        """The ellipse letter and its mapped depth, at the top of the ring.

        The same two numbers the output layer is labelled with, so the preview
        and the map agree at a glance.
        """
        top = min((polygon.at(i) for i in range(polygon.count())), key=lambda p: p.y())
        text = ellipses.LABELS[index]
        if index < len(self.final) and self.final[index][1] is not None:
            text += f"  {self.final[index][1]:.0f} mm"
        painter.setFont(QFont(painter.font().family(), 8))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text)
        x, y = top.x() - width / 2.0, top.y() + metrics.ascent() + 1
        painter.fillRect(
            int(x) - 3, int(y) - metrics.ascent() - 1,
            width + 6, metrics.height(), _HUD_BACKGROUND,
        )
        painter.setPen(QPen(_CATCHMENT_LINE, 1.0))
        painter.drawText(int(x), int(y), text)

    def _paint_scale_bar(self, painter, transform):
        scale, _ox, _oy = transform
        span_km = (self._bounds[2] - self._bounds[0]) / 1000.0
        # The largest 1/2/5 x 10^n kilometres that fits in a quarter of the view.
        target = span_km / 4.0
        exponent = 10.0 ** math.floor(math.log10(max(target, 1e-6)))
        length_km = max(
            (n * exponent for n in (1, 2, 5) if n * exponent <= target),
            default=exponent,
        )
        pixels = length_km * 1000.0 * scale
        y = self.height() - MARGIN
        x = self.width() - MARGIN - pixels
        painter.setPen(QPen(_CATCHMENT_LINE, 2.0))
        painter.drawLine(QPointF(x, y), QPointF(x + pixels, y))
        painter.drawLine(QPointF(x, y - 4), QPointF(x, y + 2))
        painter.drawLine(QPointF(x + pixels, y - 4), QPointF(x + pixels, y + 2))
        painter.setFont(QFont(painter.font().family(), 8))
        painter.drawText(QPointF(x, y - 6), f"{length_km:g} km")

    def _paint_hud(self, painter):
        if not self.hud:
            return
        font = QFont(painter.font().family(), 9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        line_height = metrics.height() + 2
        width = max(metrics.horizontalAdvance(line) for line in self.hud) + 14
        height = line_height * len(self.hud) + 8
        painter.fillRect(MARGIN, MARGIN, width, height, _HUD_BACKGROUND)
        painter.setPen(QPen(_CATCHMENT_LINE, 1.0))
        painter.drawRect(MARGIN, MARGIN, width, height)
        for row, line in enumerate(self.hud):
            painter.drawText(
                MARGIN + 7, MARGIN + 6 + metrics.ascent() + row * line_height, line
            )


class SearchPreviewDialog(QDialog):
    """The preview window, and the observer the optimiser reports trials to."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GSDM search preview")
        self.setModal(False)
        self.resize(660, 640)

        self.history = []
        self._best = None
        self._best_index = 0
        self._coarse_best_index = 0
        self._paused = False
        self._cancelled = False
        self._running = False
        self._pumping = False
        self._last_paint = 0.0
        self._summary = ""

        self.canvas = _Canvas(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas, stretch=1)
        layout.addLayout(self._live_controls())
        layout.addLayout(self._replay_controls())
        layout.addLayout(self._replay_settings())

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        self._set_replay_enabled(False)

    # --------------------------------------------------------------- controls

    def _live_controls(self):
        row = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("Cancel search")
        self.cancel_button.clicked.connect(self._cancel)
        self.fps = QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(20)
        self.fps.setSuffix(" fps")
        self.fps.setToolTip(
            "Frames per second while the search runs. The search itself is "
            "unaffected -- only how often the view is redrawn."
        )
        self.full_speed = QCheckBox("Run at full speed")
        self.full_speed.setToolTip(
            "Stop redrawing during the search. Every trial is still recorded, "
            "so the whole run can be replayed afterwards."
        )
        row.addWidget(self.pause_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        row.addWidget(self.full_speed)
        row.addWidget(self.fps)
        self._live_widgets = (
            self.pause_button, self.cancel_button, self.fps, self.full_speed
        )
        return row

    def _replay_controls(self):
        row = QHBoxLayout()
        self.play_button = QPushButton("Replay")
        self.play_button.clicked.connect(self._toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._replay_to)
        # After finish() the slider already sits at the end, so grabbing it there
        # would emit nothing and leave the final view up, looking broken.
        self.slider.sliderPressed.connect(lambda: self._replay_to(self.slider.value()))
        self.final_button = QPushButton("Final result")
        self.final_button.clicked.connect(self.show_final)
        self.trial_label = QLabel("")
        row.addWidget(self.play_button)
        row.addWidget(self.slider, stretch=1)
        row.addWidget(self.trial_label)
        row.addWidget(self.final_button)
        self._replay_widgets = (
            self.play_button, self.slider, self.final_button, self.trial_label
        )
        return row

    def _replay_settings(self):
        """Kept out of ``_replay_widgets`` so they stay editable mid-search."""
        row = QHBoxLayout()
        self.auto_replay = QCheckBox("Replay the whole search when it finishes")
        self.auto_replay.setChecked(True)
        self.auto_replay.setToolTip(
            "When the search ends, play the recorded trials back from the "
            "start, then settle on the final result. Untick to jump straight "
            "to the result."
        )
        self.replay_seconds = QSpinBox()
        self.replay_seconds.setRange(2, 120)
        self.replay_seconds.setValue(10)
        self.replay_seconds.setSuffix(" s")
        self.replay_seconds.setToolTip(
            "Roughly how long a replay takes, whatever the trial count: a long "
            "search simply skips more trials per frame."
        )
        row.addWidget(self.auto_replay)
        row.addWidget(self.replay_seconds)
        row.addStretch(1)
        return row

    def _set_live_enabled(self, enabled: bool):
        for widget in self._live_widgets:
            widget.setEnabled(enabled)

    def _set_replay_enabled(self, enabled: bool):
        for widget in self._replay_widgets:
            widget.setEnabled(enabled)

    # ------------------------------------------------------------- run cycle

    def begin(self):
        """Reset for a new run and show the window."""
        self.history = []
        self._best = None
        self._best_index = 0
        self._coarse_best_index = 0
        self._paused = False
        self._cancelled = False
        self._running = True
        self._last_paint = 0.0
        self._timer.stop()
        self.canvas.current = None
        self.canvas.best = None
        self.canvas.final = []
        self.canvas.show_final = False
        self.canvas.hud = ["Preparing…"]
        self.pause_button.setText("Pause")
        self._set_live_enabled(True)
        self._set_replay_enabled(False)
        self.show()
        self.raise_()
        self._pump()

    def on_catchment(self, polygons):
        """Called by ``qgis_bridge.run`` once the catchment is dissolved."""
        self.canvas.set_catchment(polygons)
        self.canvas.hud = ["Searching…"]
        self.canvas.update()
        self._pump()

    def __call__(self, trial):
        """The optimiser's observer hook."""
        if self._cancelled:
            raise SearchCancelled("search cancelled from the preview window")
        self.history.append(trial)
        if trial.is_best:
            self._best = trial
            self._best_index = len(self.history) - 1
            if trial.phase == "coarse":
                self._coarse_best_index = self._best_index

        now = time.monotonic()
        live = not self.full_speed.isChecked()
        if trial.is_best:
            # Only the best-so-far reframes.  Early candidates are flung well
            # off the catchment and enclosed by huge ellipses; letting those
            # widen the view would zoom out once and never come back.
            self.canvas.frame_for(trial.k)

        if live and (trial.is_best or now - self._last_paint >= 1.0 / self.fps.value()):
            self.canvas.current = (trial.cx, trial.cy, trial.theta, trial.k)
            self.canvas.best = self._placement(self._best)
            self.canvas.hud = self._hud(trial)
            self.canvas.update()
            self._last_paint = now
            self._pump()
        elif trial.index % PUMP_EVERY == 0:
            self._pump()

        while self._paused and not self._cancelled:
            self._pump()
            QThread.msleep(20)
        if self._cancelled:
            raise SearchCancelled("search cancelled from the preview window")

    def end_run(self):
        """The search is over, however it ended: stop treating Close as Cancel."""
        self._running = False
        self._paused = False
        self._set_live_enabled(False)

    def finish(self, result, placement, ring_polygons, summary: str = ""):
        """Show the chosen placement with its rainfall rings, and open replay."""
        self.end_run()
        self._timer.stop()
        self.canvas.frame_for(
            ellipses.LABELS.index(result.outermost) if result else placement.k
        )
        self.canvas.final = [
            (ring.label, ring.mrd, ring_polygons.get(ring.label, []))
            for ring in result.rings
        ]
        self._summary = summary
        self.slider.blockSignals(True)
        self.slider.setMaximum(max(len(self.history) - 1, 0))
        self.slider.setValue(max(len(self.history) - 1, 0))
        self.slider.blockSignals(False)
        self._set_replay_enabled(bool(self.history))
        self._final_placement = (placement.cx, placement.cy, placement.theta, placement.k)
        self.show()
        self.raise_()

        # The result is already in the dialog's table and on the map by now, so
        # the window is free to spend a few seconds retracing how it got there.
        if self.auto_replay.isChecked() and self.history:
            self.start_replay()
        else:
            self.show_final()

    def show_final(self):
        """Draw the final answer: placement, shaded rings, summary."""
        self._timer.stop()
        self.play_button.setText("Replay")
        self.canvas.show_final = True
        self.canvas.best = None
        self.canvas.current = getattr(self, "_final_placement", self.canvas.current)
        self.canvas.hud = [line for line in self._summary.split("\n") if line]
        self.canvas.update()
        self._pump()

    # ---------------------------------------------------------------- replay

    def start_replay(self):
        """Play the recorded trials from the first, ending on the final result."""
        if not self.history:
            return
        self._timer.stop()
        self.slider.setValue(0)
        self._replay_to(0)  # setValue(0) emits nothing if it was already 0
        self._timer.start()
        self.play_button.setText("Pause replay")

    def _toggle_play(self):
        if self._timer.isActive():
            self._timer.stop()
            self.play_button.setText("Replay")
        elif self.slider.value() >= self.slider.maximum():
            self.start_replay()
        else:
            self._timer.start()
            self.play_button.setText("Pause replay")

    def _advance(self):
        if self.slider.value() >= self.slider.maximum():
            self._timer.stop()
            self.play_button.setText("Replay")
            self.show_final()
            return
        self.slider.setValue(
            min(self.slider.value() + self._replay_step(), self.slider.maximum())
        )

    def _replay_step(self) -> int:
        """Trials per frame, so a replay lasts about as long as asked.

        The coarse sweep can be ten thousand trials; stepping through them one
        at a time would take minutes and show nothing a skipping replay does not.
        """
        frames = max(self.replay_seconds.value() * 1000 // self._timer.interval(), 1)
        return max(1, math.ceil(len(self.history) / frames))

    def _replay_to(self, index: int):
        if not self.history:
            return
        index = min(max(index, 0), len(self.history) - 1)
        trial = self.history[index]
        best = None
        for candidate in self.history[: index + 1]:
            if candidate.is_best:
                best = candidate
        self.canvas.show_final = False
        self.canvas.current = self._placement(trial)
        self.canvas.best = self._placement(best)
        self.canvas.hud = self._hud(trial, best=best, replaying=True)
        self.canvas.update()
        self.trial_label.setText(f"{index + 1} / {len(self.history)}")

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _placement(trial):
        return None if trial is None else (trial.cx, trial.cy, trial.theta, trial.k)

    @staticmethod
    def _ellipse_label(k: int) -> str:
        return ellipses.LABELS[k] if k < len(ellipses.LABELS) else "outside"

    def _hud(self, trial, best=None, replaying: bool = False):
        """The running caption.

        ``best`` is passed explicitly during a replay: the best *at that point*
        in the history, not the one the search eventually settled on.
        """
        best = best if best is not None or replaying else self._best
        where = (
            f"trial {trial.index:,} / {trial.total:,}"
            if trial.phase == "coarse"
            else f"refining, trial {trial.index:,}"
        )
        # The view is framed on the best fit, so a poor candidate's enclosing
        # ellipse is often larger than anything drawn -- say so rather than
        # naming an ellipse the user cannot see.
        beyond = "  (larger than the view)" if trial.k > self.canvas._draw_to else ""
        lines = [
            f"{'replay — ' if replaying else ''}{where}   ({trial.phase})",
            f"enclosing ellipse {self._ellipse_label(trial.k)}{beyond}   "
            f"score {trial.score:,.0f} mm·km²",
        ]
        if best is not None:
            lines.append(
                f"best so far: {self._ellipse_label(best.k)}   "
                f"{best.score:,.0f} mm·km²   "
                f"bearing {(90.0 - math.degrees(best.theta)) % 180.0:.0f}°"
            )
        return lines

    def _toggle_pause(self):
        self._paused = not self._paused
        self.pause_button.setText("Resume" if self._paused else "Pause")

    def _cancel(self):
        self._cancelled = True
        self._paused = False

    def _pump(self):
        """Let Qt paint and deliver clicks without recursing into ourselves."""
        if self._pumping:
            return
        self._pumping = True
        try:
            QApplication.processEvents()
        finally:
            self._pumping = False

    def closeEvent(self, event):  # noqa: N802 -- Qt API
        # Closing mid-run is the same intent as pressing Cancel; leaving the
        # search running against a hidden window would just look like a hang.
        if self._running:
            self._cancel()
        self._timer.stop()
        super().closeEvent(event)
