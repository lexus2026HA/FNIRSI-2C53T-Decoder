"""Screenshot tab: original BMP next to the waveform rebuilt on the same screen grid."""
from __future__ import annotations

import html

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QSizePolicy, QCheckBox, QHBoxLayout, QLabel, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from ..decoders import bmp_screen
from ..decoders.model import Measurement

OVERLAY = {"CH1": (255, 40, 40), "CH2": (255, 60, 255)}


class ScaledImage(QLabel):
    """Shows a pixmap scaled to the label size with crisp (nearest) pixels."""

    def __init__(self, text=""):
        super().__init__(text)
        self._pm = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_image(self, pm):
        self._pm = pm
        self._update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update()

    def _update(self):
        if self._pm is not None:
            self.setPixmap(self._pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.FastTransformation))

    def setText(self, t):
        self._pm = None
        super().setText(t)


class BmpView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.m: Measurement | None = None
        self.screen = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.diag = QCheckBox("Диагностика: нанести декодированные отсчёты на снимок")
        self.diag.setChecked(True)
        self.diag.toggled.connect(self._render)
        top.addWidget(self.diag)
        top.addStretch(1)
        lay.addLayout(top)
        sp = QSplitter(Qt.Horizontal)
        self.img = ScaledImage("Нет снимка")
        sp.addWidget(self.img)
        self.plot = pg.PlotWidget(background="#050505")
        self.plot.setTitle("Восстановлено из BIN (сетка экрана 12×8 дел)", color="#ccc", size="9pt")
        sp.addWidget(self.plot)
        sp.setSizes([660, 600])
        lay.addWidget(sp, 3)
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)

    def set_measurement(self, m: Measurement | None):
        self.m = m
        self.screen = None
        if m is not None and m.bmp_path is not None:
            try:
                self.screen = bmp_screen.load_screen(m.bmp_path)
            except bmp_screen.BmpError as e:
                self.screen = None
                self.text.setHtml(f"<b>BMP:</b> {html.escape(str(e))}")
        self._render()

    def _render(self, *_):
        m = self.m
        self.plot.clear()
        if m is None:
            self.img.setText("Нет измерения")
            return
        # rebuilt waveform in screen geometry
        p = self.plot.getPlotItem()
        pr = m.prof
        last = m.n_samples - 1
        cx = last / 2.0
        k = 0
        while cx + k * pr.samples_per_div <= last + 0.5:       # vertical grid from the centre outwards
            for x in {cx + k * pr.samples_per_div, cx - k * pr.samples_per_div}:
                p.addLine(x=x, pen=pg.mkPen("#1e5a2c", width=1.5 if k == 0 else 1))
            k += 1
        k = 0
        while pr.code_center + k * pr.codes_per_div <= pr.code_max + 0.5:
            for y in {pr.code_center + k * pr.codes_per_div, pr.code_center - k * pr.codes_per_div}:
                p.addLine(y=y, pen=pg.mkPen("#1e5a2c", width=1.5 if k == 0 else 1))
            k += 1
        what = "Оцифровано со снимка" if (m.bmp_info or {}).get("digitized") else "Из файла данных"
        self.plot.setTitle(f"{what} ({pr.model}: сетка экрана {pr.divs_x:g}×{pr.divs_y:g} дел)",
                           color="#ccc", size="9pt")
        colors = {"CH1": "#e6e600", "CH2": "#2f7bff"}
        for ch in m.enabled_channels:
            p.plot(np.arange(m.n_samples), ch.raw.astype(float), pen=pg.mkPen(colors[ch.name], width=1.2),
                   name=ch.name)
            if ch.zero_code.known:
                p.addLine(y=float(ch.zero_code.value), pen=pg.mkPen(colors[ch.name], style=Qt.DotLine))
        p.setXRange(0, last, padding=0.01)
        p.setYRange(pr.code_min, pr.code_max, padding=0.01)
        p.setLabel("bottom", f"номер отсчёта (= столбец экрана − {pr.x0})")
        p.setLabel("left", f"код (= {pr.y_of_code0} − строка экрана)")
        und = (m.bmp_info or {}).get("undrawn_from") or {}
        for chn, i0 in und.items():
            p.addItem(pg.LinearRegionItem((i0, last), movable=False, brush=pg.mkBrush(200, 60, 60, 40)))
        if self.screen is None:
            self.img.setText("BMP-снимок с тем же именем не найден" if m.bmp_path is None else "BMP не прочитан")
            self.text.setHtml(self._report(m))
            return
        rgb = self.screen.rgb().copy()
        if self.diag.isChecked():
            for ch in m.enabled_channels:
                col = OVERLAY[ch.name]
                xs = m.prof.x0 + np.arange(m.n_samples)
                ys = m.prof.y_of_code0 - ch.raw.astype(int)
                ok = (ys >= 0) & (ys < rgb.shape[0]) & (xs < rgb.shape[1])
                rgb[ys[ok], xs[ok]] = col
        h, w, _ = rgb.shape
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.img.set_image(QPixmap.fromImage(qimg))
        self.text.setHtml(self._report(m))

    @staticmethod
    def _report(m: Measurement) -> str:
        e = html.escape
        bi = m.bmp_info or {}
        if not bi.get("path"):
            return ("<p>Снимок экрана не найден. Шкалы можно ввести вручную на вкладке «Шкалы».</p>")
        out = [f"<b>Снимок:</b> {e(bi.get('path', ''))}"]
        if bi.get("note"):
            out.append(f"<span style='color:#c98a00'>{e(bi['note'])}</span>")
        if bi.get("trace_match"):
            for k, v in bi["trace_match"].items():
                out.append(f"<b>{k}</b>: {v['hits']} из {v['considered']} отсчётов лежат точно на пикселях луча"
                           + (f", ещё {v['near']} — в ±1 пикселе" if v.get("near") else "")
                           + (lambda hidden: f"; {hidden} скрыты надписями измерений"
                              if hidden > 0 and "window" not in v else "")(
                               min(v['n'], (v.get('drawn_until') if v.get('drawn_until') is not None else v['n'] - 1) + 1)
                               - v['considered']))
            out.append("BMP соответствует BIN: <b>" + ("да" if bi.get("matches_bin") else "НЕТ") + "</b>")
            for k, i0 in (bi.get("undrawn_from") or {}).items():
                out.append(f"<span style='color:#c98a00'>{k}: отсчёты с {i0} не были нарисованы прибором "
                           "(развёртка не завершена) — область отмечена красным справа.</span>")
        o = bi.get("ocr") or {}
        names = {"timebase": "время/дел", "ch1_vdiv": "CH1 В/дел", "ch1_probe_coupling": "CH1 щуп/вход",
                 "ch2_vdiv": "CH2 В/дел", "ch2_probe_coupling": "CH2 щуп/вход"}
        if o and any(v.get("text") for v in o.values()):
            out.append("<b>Распознанные надписи:</b> " + "; ".join(
                f"{names.get(k, k)} «{e(v['text'])}»" + ("" if v["ok"] else " — <span style='color:#d03030'>не распознано</span>")
                for k, v in o.items()))
        mk = bi.get("markers") or {}
        enabled = {c.name for c in m.enabled_channels}
        if m.prof.data_ext == ".wav":
            enabled = set()              # 1013D: zero level comes from the WAV header
            out.append("Шкалы и положение нуля взяты из заголовка WAV.")
        for k, v in mk.items():
            if k not in enabled:
                continue
            if v.get("found"):
                pr = m.prof
                out.append(f"Метка нуля {k}: строка {v['row']:.1f} → код {v['zero_code']:.1f} "
                           f"({(v['zero_code'] - pr.code_center) / pr.codes_per_div:+.2f} дел от центра) "
                           f"{e(v.get('note', ''))}")
            else:
                out.append(f"Метка нуля {k}: {e(v.get('reason', 'не найдена'))}")
        out.append("<span style='color:#888'>Красные/пурпурные точки — декодированные отсчёты CH1/CH2, "
                   "нанесённые на снимок. Распознавание надписей проверено на 9 снимках 2C53T и 3 снимках 2C53P; при незнакомом "
                   "символе поле считается нераспознанным и шкалу нужно ввести вручную.</span>")
        return "<br>".join(out)
