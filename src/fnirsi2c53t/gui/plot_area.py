"""Interactive waveform plot: overlay/split view, A/B and Y1/Y2 cursors, hover readout."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..analysis.cursors import nearest_index
from ..visualization.traces import TraceSet

pg.setConfigOptions(antialias=True)

CURSOR_PENS = {
    "A": pg.mkPen("#ff5555", width=1.5, style=Qt.DashLine),
    "B": pg.mkPen("#55aaff", width=1.5, style=Qt.DashLine),
    "Y1": pg.mkPen("#d68cff", width=1.5, style=Qt.DotLine),
    "Y2": pg.mkPen("#66dd77", width=1.5, style=Qt.DotLine),
}
SI_UNITS = {"s", "V", "Hz"}


def fmt_value(v: float | None, unit: str) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    if unit in SI_UNITS:
        return pg.siFormat(v, precision=5, suffix=unit, space=True)
    if unit == "":
        return f"{v:.6g}"
    return f"{v:.5g} {unit}"


class PlotArea(QWidget):
    hoverText = Signal(str)          # for the status bar
    cursorsChanged = Signal()
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.glw = pg.GraphicsLayoutWidget()
        lay.addWidget(self.glw)
        self.ts: TraceSet | None = None
        self.plots: list[pg.PlotItem] = []
        self.plot_traces: list[list] = []        # traces per plot
        self.curves = []
        self.split = False
        self.line_width = 1.4
        self.show_points = False
        self.show_lines = True
        self.grid = True
        self.dark = True
        self.snap = True
        self.vcursors_on = False
        self.hcursors_on = False
        self.hcursor_plot = 0
        self.cur = {"A": None, "B": None, "Y1": None, "Y2": None}
        self._lines: dict[str, list[pg.InfiniteLine]] = {}
        self._sync = False
        self.last_point: dict | None = None
        self._hover_items = []
        self._mouse_proxy = pg.SignalProxy(self.glw.scene().sigMouseMoved, rateLimit=40, slot=self._on_mouse)
        self._apply_bg()

    # ------------------------------------------------------------ building
    def _apply_bg(self):
        self.glw.setBackground("#101418" if self.dark else "w")

    def set_dark(self, dark: bool):
        self.dark = dark
        self._apply_bg()
        self.rebuild(keep_view=True)

    def set_traces(self, ts: TraceSet | None, keep_view: bool = True):
        old = self.ts
        view = self.get_view() if (keep_view and old is not None and self.plots) else None
        if view and old and (old.xmode != (ts.xmode if ts else None) or old.ymode != (ts.ymode if ts else None)):
            view = None
            self._remap_cursors(old, ts)
        self.ts = ts
        self.rebuild(view=view)

    def rebuild(self, keep_view: bool = False, view=None):
        if keep_view and view is None and self.plots:
            view = self.get_view()
        self.glw.clear()
        self.plots, self.plot_traces, self.curves = [], [], []
        self._lines = {}
        self._hover_items = []
        ts = self.ts
        if ts is None or not ts.traces:
            p = self.glw.addPlot()
            p.hideAxis("left")
            p.hideAxis("bottom")
            t = pg.TextItem("Нет данных: откройте BIN-файл (двойной щелчок в списке слева)",
                            color="#888", anchor=(0.5, 0.5))
            p.addItem(t)
            t.setPos(0, 0)
            p.setRange(QRectF(-1, -1, 2, 2))
            self.plots.append(p)
            self.plot_traces.append([])
            return
        if self.split:
            groups: dict[str, list] = {}
            for t in ts.traces:
                groups.setdefault(t.channel, []).append(t)
            group_list = list(groups.values())
        else:
            group_list = [ts.traces]
        fg = "#cfd6dd" if self.dark else "#222"
        for gi, traces in enumerate(group_list):
            p = self.glw.addPlot(row=gi, col=0)
            p.showGrid(x=self.grid, y=self.grid, alpha=0.3)
            p.addLegend(offset=(-10, 10), labelTextColor=fg)
            for ax in ("left", "bottom"):
                p.getAxis(ax).setTextPen(fg)
                p.getAxis(ax).setPen(fg)
            if ts.xunit in SI_UNITS:
                p.setLabel("bottom", ts.xlabel, units=ts.xunit)
            else:
                p.setLabel("bottom", ts.xlabel + (f", {ts.xunit}" if ts.xunit else ""))
            ylab = ts.ylabel + (f" — {traces[0].channel}" if self.split else "")
            if ts.yunit in SI_UNITS:
                p.setLabel("left", ylab, units=ts.yunit)
            else:
                p.setLabel("left", ylab + (f", {ts.yunit}" if ts.yunit else ""))
            for t in traces:
                pen = pg.mkPen(t.color, width=self.line_width) if self.show_lines else None
                kw = {}
                if self.show_points or not self.show_lines:
                    kw = dict(symbol="o", symbolSize=4, symbolBrush=t.color, symbolPen=None)
                c = p.plot(t.x, t.y, pen=pen, name=t.label, **kw)
                self.curves.append(c)
            if gi > 0:
                p.setXLink(self.plots[0])
            p.sigRangeChanged.connect(lambda *_: self.viewChanged.emit())
            # hover marker + text
            mk = pg.ScatterPlotItem(size=9, pen=pg.mkPen("w" if self.dark else "k"), brush=None)
            tx = pg.TextItem("", color=fg, fill=pg.mkBrush(0, 0, 0, 170) if self.dark else pg.mkBrush(255, 255, 255, 220),
                             anchor=(0, 1))
            tx.setFont(QFont("Consolas", 9))
            mk.setZValue(50)
            tx.setZValue(51)
            p.addItem(mk, ignoreBounds=True)
            p.addItem(tx, ignoreBounds=True)
            mk.hide()
            tx.hide()
            self._hover_items.append((mk, tx))
            self.plots.append(p)
            self.plot_traces.append(traces)
        if view:
            self.set_view(view)
        else:
            self.auto_range()
        self._build_cursors()

    # ------------------------------------------------------------- view
    def get_view(self):
        if not self.plots:
            return None
        (x0, x1), (y0, y1) = self.plots[0].viewRange()
        return (x0, x1, y0, y1)

    def set_view(self, v):
        if not self.plots or not v:
            return
        x0, x1, y0, y1 = v
        for i, p in enumerate(self.plots):
            p.setXRange(x0, x1, padding=0)
            if i == 0 or not self.split:
                p.setYRange(y0, y1, padding=0)

    def auto_range(self):
        for p in self.plots:
            p.enableAutoRange()
            p.autoRange(padding=0.04)

    def set_grid(self, on: bool):
        self.grid = on
        for p in self.plots:
            p.showGrid(x=on, y=on, alpha=0.3)

    # ---------------------------------------------------------- cursors
    def _xaxis(self) -> np.ndarray | None:
        if self.ts and self.ts.traces:
            return self.ts.traces[0].x
        return None

    def _remap_cursors(self, old: TraceSet, new: TraceSet | None):
        if new is None or not old.traces or not new.traces:
            return
        if old.xmode != new.xmode:
            ox, nx = old.traces[0].x, new.traces[0].x
            for k in ("A", "B"):
                v = self.cur[k]
                if v is not None:
                    i = nearest_index(v, ox)
                    self.cur[k] = float(nx[i])
        if old.ymode != new.ymode:
            self.cur["Y1"] = self.cur["Y2"] = None

    def _default_cursor_positions(self):
        v = self.get_view()
        if not v:
            return
        x0, x1, y0, y1 = v
        xa = self._xaxis()
        if self.cur["A"] is None or not (x0 <= self.cur["A"] <= x1):
            self.cur["A"] = x0 + 0.25 * (x1 - x0)
        if self.cur["B"] is None or not (x0 <= self.cur["B"] <= x1):
            self.cur["B"] = x0 + 0.75 * (x1 - x0)
        if self.snap and xa is not None:
            for k in ("A", "B"):
                self.cur[k] = float(xa[nearest_index(self.cur[k], xa)])
        p = self.plots[min(self.hcursor_plot, len(self.plots) - 1)]
        (_, _), (py0, py1) = p.viewRange()
        if self.cur["Y1"] is None or not (py0 <= self.cur["Y1"] <= py1):
            self.cur["Y1"] = py0 + 0.25 * (py1 - py0)
        if self.cur["Y2"] is None or not (py0 <= self.cur["Y2"] <= py1):
            self.cur["Y2"] = py0 + 0.75 * (py1 - py0)

    def _build_cursors(self):
        for lines in self._lines.values():
            for ln in lines:
                try:
                    ln.getViewBox() and ln.getViewBox().removeItem(ln)
                except Exception:
                    pass
        self._lines = {}
        if not self.ts or not self.ts.traces:
            return
        if self.vcursors_on or self.hcursors_on:
            self._default_cursor_positions()
        lab_opts = dict(position=0.96, color="#eee" if self.dark else "#111",
                        fill=(0, 0, 0, 140) if self.dark else (255, 255, 255, 200), movable=True)
        if self.vcursors_on:
            for k in ("A", "B"):
                self._lines[k] = []
                for p in self.plots:
                    ln = pg.InfiniteLine(pos=self.cur[k], angle=90, movable=True, pen=CURSOR_PENS[k],
                                         hoverPen=pg.mkPen(CURSOR_PENS[k].color(), width=3),
                                         label=k, labelOpts=lab_opts)
                    ln.setZValue(40)
                    ln.sigPositionChanged.connect(lambda line, key=k: self._on_cursor_moved(key, line))
                    p.addItem(ln, ignoreBounds=True)
                    self._lines[k].append(ln)
        if self.hcursors_on:
            p = self.plots[min(self.hcursor_plot, len(self.plots) - 1)]
            for k in ("Y1", "Y2"):
                ln = pg.InfiniteLine(pos=self.cur[k], angle=0, movable=True, pen=CURSOR_PENS[k],
                                     hoverPen=pg.mkPen(CURSOR_PENS[k].color(), width=3),
                                     label=k, labelOpts=dict(lab_opts, position=0.03))
                ln.setZValue(40)
                ln.sigPositionChanged.connect(lambda line, key=k: self._on_cursor_moved(key, line))
                p.addItem(ln, ignoreBounds=True)
                self._lines[k] = [ln]
        self.cursorsChanged.emit()

    def _on_cursor_moved(self, key: str, line: pg.InfiniteLine):
        if self._sync:
            return
        v = float(line.value())
        if key in ("A", "B") and self.snap:
            xa = self._xaxis()
            if xa is not None:
                v = float(xa[nearest_index(v, xa)])
        self.cur[key] = v
        self._sync = True
        try:
            for ln in self._lines.get(key, []):
                if float(ln.value()) != v:
                    ln.setValue(v)
        finally:
            self._sync = False
        self.cursorsChanged.emit()

    def set_cursor_modes(self, vertical: bool | None = None, horizontal: bool | None = None):
        if vertical is not None:
            self.vcursors_on = vertical
        if horizontal is not None:
            self.hcursors_on = horizontal
        self._build_cursors()

    def reset_cursors(self):
        for k in self.cur:
            self.cur[k] = None
        self._build_cursors()

    def set_cursor(self, key: str, value: float):
        self.cur[key] = value
        for ln in self._lines.get(key, []):
            ln.setValue(value)

    def set_snap(self, on: bool):
        self.snap = on
        if on:
            for k in ("A", "B"):
                for ln in self._lines.get(k, [])[:1]:
                    self._on_cursor_moved(k, ln)

    def cursor_readout(self) -> dict:
        """Values under the cursors for every visible trace."""
        out = {"rows": [], "dx": None, "dy": None, "inv_dx": None, "di": None}
        ts = self.ts
        if not ts or not ts.traces:
            return out
        if self.vcursors_on and self.cur["A"] is not None:
            idx = {}
            for k in ("A", "B"):
                x = self.cur[k]
                row = {"cursor": k, "x": x, "xunit": ts.xunit, "values": []}
                for t in ts.traces:
                    i = nearest_index(x, t.x)
                    idx.setdefault(k, i)
                    row["values"].append({"trace": t.label, "index": i, "x": float(t.x[i]),
                                          "y": float(t.y[i]), "raw": int(t.raw[i]), "unit": ts.yunit})
                row["index"] = row["values"][0]["index"] if row["values"] else None
                out["rows"].append(row)
            dx = self.cur["B"] - self.cur["A"]
            out["dx"] = dx
            out["inv_dx"] = (1.0 / abs(dx)) if dx else None
            if idx.get("A") is not None and idx.get("B") is not None:
                out["di"] = idx["B"] - idx["A"]
        if self.hcursors_on and self.cur["Y1"] is not None:
            out["y1"], out["y2"] = self.cur["Y1"], self.cur["Y2"]
            out["dy"] = self.cur["Y2"] - self.cur["Y1"]
        out["xunit"], out["yunit"] = ts.xunit, ts.yunit
        return out

    # ------------------------------------------------------------ hover
    def _on_mouse(self, evt):
        pos = evt[0]
        if not self.ts or not self.ts.traces:
            return
        for pi, p in enumerate(self.plots):
            mk, tx = self._hover_items[pi] if pi < len(self._hover_items) else (None, None)
            if mk is None:
                continue
            vb = p.vb
            if not p.sceneBoundingRect().contains(pos) or not vb.sceneBoundingRect().contains(pos):
                mk.hide()
                tx.hide()
                continue
            mp = vb.mapSceneToView(pos)
            x, y = mp.x(), mp.y()
            ts = self.ts
            # nearest trace point in screen pixels
            best = None
            for t in self.plot_traces[pi]:
                i = nearest_index(x, t.x)
                sp = vb.mapViewToScene(pg.Point(t.x[i], t.y[i]))
                d = (sp.x() - pos.x()) ** 2 + (sp.y() - pos.y()) ** 2
                if best is None or d < best[0]:
                    best = (d, t, i)
            status = f"X = {fmt_value(x, ts.xunit)}   Y = {fmt_value(y, ts.yunit)}"
            if best is None:
                self.hoverText.emit(status)
                continue
            d, t, i = best
            lines = [f"#{i}  {fmt_value(float(t.x[i]), ts.xunit)}"]
            # values of every channel of the same measurement at this index
            for t2 in self.ts.traces:
                if t2.item is t.item:
                    j = nearest_index(float(t.x[i]), t2.x)
                    lines.append(f"{t2.label}: {fmt_value(float(t2.y[j]), ts.yunit)}  (код {int(t2.raw[j])})")
            self.last_point = {"index": i, "x": float(t.x[i]), "y": float(t.y[i]), "trace": t.label,
                               "raw": int(t.raw[i]), "xunit": ts.xunit, "yunit": ts.yunit,
                               "text": "\t".join(lines)}
            status += "   |   ближайший отсчёт: " + "; ".join(lines)
            self.hoverText.emit(status)
            if d <= 30 ** 2:
                mk.setData([t.x[i]], [t.y[i]])
                mk.show()
                tx.setText("\n".join(lines))
                tx.setPos(t.x[i], t.y[i])
                tx.show()
            else:
                mk.hide()
                tx.hide()

    # ---------------------------------------------------------- export
    def render_to(self, path: str, fmt: str):
        """Save exactly what is on screen (PNG/SVG/PDF)."""
        from PySide6.QtCore import QMarginsF, QSize, QSizeF
        from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter
        src = QRectF(self.glw.rect())
        if fmt == "png":
            scale = 2
            img = QImage(int(src.width() * scale), int(src.height() * scale), QImage.Format_ARGB32)
            img.fill(QColor("#101418" if self.dark else "white"))
            pt = QPainter(img)
            pt.setRenderHint(QPainter.Antialiasing)
            self.glw.render(pt)
            pt.end()
            img.save(path)
        elif fmt == "svg":
            from PySide6.QtSvg import QSvgGenerator
            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(int(src.width()), int(src.height())))
            gen.setViewBox(src)
            pt = QPainter(gen)
            self.glw.render(pt)
            pt.end()
        elif fmt == "pdf":
            w = QPdfWriter(path)
            w.setPageSize(QPageSize(QSizeF(src.width(), src.height()), QPageSize.Unit.Point))
            w.setPageMargins(QMarginsF(0, 0, 0, 0))
            w.setResolution(72)
            pt = QPainter(w)
            self.glw.render(pt)
            pt.end()
