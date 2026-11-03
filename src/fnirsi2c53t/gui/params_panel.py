"""Right panel: file info, scales, display options, cursors, measurements."""
from __future__ import annotations

import datetime as _dt
import html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..analysis.measurements import ChannelMeasurements, format_si
from ..decoders.profiles import P2C53T
from ..decoders.model import SOURCE_LABELS, SRC_BMP, SRC_FILE, SRC_UNKNOWN, SRC_USER, Measurement
from .plot_area import fmt_value

SRC_COLORS = {SRC_UNKNOWN: "#d03030", SRC_BMP: "#c98a00", SRC_USER: "#2f7bff", SRC_FILE: "#2e9d4a"}

TIMEBASES = [m * 10 ** e for e in range(-9, 2) for m in (1, 2, 5)]
VDIVS = [m * 10 ** e for e in range(-3, 3) for m in (1, 2, 5)]

_PREF = {"n": 1e-9, "н": 1e-9, "u": 1e-6, "µ": 1e-6, "мк": 1e-6, "m": 1e-3, "м": 1e-3, "": 1.0, "k": 1e3, "к": 1e3}


def parse_quantity(text: str, base_units: tuple[str, ...]) -> float | None:
    """'200 мкс', '0.2ms', '500mV', '0,5' -> float in base units. None if unknown/empty."""
    t = text.strip().replace(",", ".").replace(" ", "")
    if not t or t.lower().startswith("неизв"):
        return None
    for u in sorted(base_units, key=len, reverse=True):
        if t.lower().endswith(u.lower()):
            t = t[: -len(u)]
            break
    m = re.fullmatch(r"([0-9]*\.?[0-9]+(?:e-?\d+)?)(n|н|u|µ|мк|m|м|k|к)?", t, flags=re.I)
    if not m:
        raise ValueError(text)
    return float(m.group(1)) * _PREF.get((m.group(2) or "").lower(), 1.0)


def human_time(v: float) -> str:
    return format_si(v, "s", 3).replace("µs", "мкс").replace("ms", "мс").replace("ns", "нс").replace(" s", " с")


def human_volt(v: float) -> str:
    return format_si(v, "V", 3).replace("mV", "мВ").replace("µV", "мкВ").replace(" V", " В")


class ScaleCombo(QComboBox):
    """Editable combo of standard values + 'неизвестно'."""

    edited = Signal(object)          # float | None

    def __init__(self, values, humanize, units, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.units = units
        self.addItem("неизвестно", None)
        for v in values:
            self.addItem(humanize(v), v)
        self.humanize = humanize
        self.activated.connect(self._activated)
        self.lineEdit().editingFinished.connect(self._typed)
        self._block = False

    def set_value(self, v):
        self._block = True
        if v is None:
            self.setCurrentIndex(0)
        else:
            i = next((k for k in range(1, self.count()) if abs(self.itemData(k) - v) < 1e-12 * max(1, abs(v))), -1)
            if i >= 0:
                self.setCurrentIndex(i)
            else:
                self.setEditText(self.humanize(v))
        self._block = False

    def _activated(self, i):
        if not self._block:
            self.edited.emit(self.itemData(i))

    def _typed(self):
        if self._block:
            return
        try:
            v = parse_quantity(self.currentText(), self.units)
        except ValueError:
            self.setStyleSheet("background:#ffdddd;")
            return
        self.setStyleSheet("")
        self.edited.emit(v)


class ParamsPanel(QWidget):
    scalesEdited = Signal(str, str, object)      # target ("time" / "CH1"...), field, value
    applyBmpRequested = Signal()
    clearScalesRequested = Signal()
    viewOptions = Signal(dict)
    autoRangeRequested = Signal()
    manualRangeRequested = Signal()
    cursorOptions = Signal(dict)
    resetCursorsRequested = Signal()
    measureOptions = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self._build_info()
        self._build_scales()
        self._build_view()
        self._build_cursors()
        self._build_measure()

    # ------------------------------------------------------------- info
    def _build_info(self):
        self.info = QTextBrowser()
        self.info.setOpenExternalLinks(False)
        self.tabs.addTab(self.info, "Файл")

    def show_info(self, m: Measurement | None):
        if m is None:
            self.info.setHtml("<i>Нет открытого измерения.</i>")
            return
        e = html.escape
        rows = [
            ("Файл", e(str(m.path))),
            ("Размер", f"{m.file_size} байт"),
            ("Изменён", _dt.datetime.fromtimestamp(m.file_mtime).strftime("%Y-%m-%d %H:%M:%S") if m.file_mtime else "—"),
            ("Модель", e(m.prof.model)),
            ("Формат", e(m.format_name)),
            ("Декодер", e(m.decoder_version)),
            ("Отсчётов", f"{m.n_samples} на канал"),
            ("Флаги каналов", f"0x{m.header.get('flags_byte', 0):02X} — "
                              + ", ".join(f"{c.name} {'вкл' if c.enabled else 'выкл'}" for c in m.channels)),
            ("Хвост файла", e(m.header.get("trailer_hex", ""))),
        ]
        bi = m.bmp_info or {}
        if bi.get("path"):
            rows.append(("Снимок BMP", e(bi["path"])))
        if bi.get("error"):
            rows.append(("BMP", e(bi["error"])))
        if bi.get("trace_match"):
            for k, v in bi["trace_match"].items():
                rows.append((f"Сверка {k} с BMP", f"{v['hits']} из {v['considered']} отсчётов совпали с лучом"
                             + (f" (+{v['near']} в ±1 px)" if v.get("near") else "")))
            rows.append(("BMP соответствует BIN", "да" if bi.get("matches_bin") else "<b style='color:#d03030'>нет</b>"))
        if bi.get("ocr"):
            o = bi["ocr"]
            rows.append(("Надписи на экране", "; ".join(
                f"{k}: «{e(v['text'])}»{'' if v['ok'] else ' (не распознано)'}" for k, v in o.items())))
        h = "<table cellspacing=3>" + "".join(
            f"<tr><td valign=top><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        warns = m.reliability_warnings()
        if warns:
            h += "<p><b style='color:#c98a00'>Предупреждения о достоверности:</b><ul>" + "".join(
                f"<li>{e(w)}</li>" for w in warns) + "</ul>"
        pr = m.prof
        h += (f"<p style='color:#888'>Модель: {pr.model}. Файл открыт только для чтения. BIN хранит лишь "
              f"экранные отсчёты ({pr.n_samples} на канал, 8 бит, {pr.codes_per_div:g} кодов на деление); "
              "В/дел, время/дел и положение нуля в нём не хранятся.</p>")
        self.info.setHtml(h)

    # ----------------------------------------------------------- scales
    def _src_label(self):
        lab = QLabel()
        lab.setMinimumWidth(120)
        return lab

    @staticmethod
    def _set_src(label: QLabel, p):
        label.setText(SOURCE_LABELS.get(p.source, p.source))
        label.setStyleSheet(f"color:{SRC_COLORS.get(p.source, '#888')};")
        label.setToolTip(p.note or "")

    def _build_scales(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Время")
        f = QFormLayout(g)
        self.tb_combo = ScaleCombo(TIMEBASES, human_time, ("s", "с"))
        self.tb_combo.edited.connect(lambda val: self.scalesEdited.emit("time", "time_per_div", val))
        self.tb_src = self._src_label()
        hl = QHBoxLayout()
        hl.addWidget(self.tb_combo, 1)
        hl.addWidget(self.tb_src)
        f.addRow("Время/дел:", hl)
        self.dt_label = QLabel("—")
        f.addRow("Шаг отсчётов:", self.dt_label)
        v.addWidget(g)
        self.ch_widgets = {}
        for chn in ("CH1", "CH2"):
            g = QGroupBox(chn)
            f = QFormLayout(g)
            vd = ScaleCombo(VDIVS, human_volt, ("V", "В"))
            vd.edited.connect(lambda val, c=chn: self.scalesEdited.emit(c, "volts_per_div", val))
            vs = self._src_label()
            hl = QHBoxLayout()
            hl.addWidget(vd, 1)
            hl.addWidget(vs)
            f.addRow("В/дел:", hl)
            zk = QCheckBox("известен")
            zs = QDoubleSpinBox()
            zs.setRange(-20, 20)
            zs.setDecimals(2)
            zs.setSingleStep(0.04)
            zs.setSuffix(" дел")
            zs.setToolTip("Положение 0 В в делениях от центра экрана (вверх +). "
                          "1 код = 0.04 дел. На экране прибора — цветная метка у левого края.")
            zsrc = self._src_label()
            zk.toggled.connect(lambda on, c=chn, s=zs: self.scalesEdited.emit(
                c, "zero_code", self._div_to_code(s.value()) if on else None))
            zs.editingFinished.connect(lambda c=chn, s=zs, k=zk: k.isChecked() and self.scalesEdited.emit(
                c, "zero_code", self._div_to_code(s.value())))
            hl = QHBoxLayout()
            hl.addWidget(zk)
            hl.addWidget(zs, 1)
            hl.addWidget(zsrc)
            f.addRow("Ноль:", hl)
            pr = QLabel("—")
            f.addRow("Щуп / вход:", pr)
            v.addWidget(g)
            self.ch_widgets[chn] = dict(group=g, vdiv=vd, vsrc=vs, zero_on=zk, zero=zs, zsrc=zsrc, probe=pr)
        note = QLabel("В/дел вводится так, как показано на экране прибора (с учётом множителя щупа). "
                      "Значения «распознано по BMP» прочитаны с экранного снимка — сверьте их со снимком "
                      "(вкладка «Снимок BMP»).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        v.addWidget(note)
        hl = QHBoxLayout()
        b = QPushButton("Взять из BMP")
        b.setToolTip("Заменить шкалы значениями, распознанными на снимке экрана")
        b.clicked.connect(self.applyBmpRequested)
        hl.addWidget(b)
        b = QPushButton("Сбросить шкалы")
        b.setToolTip("Пометить все шкалы как неизвестные")
        b.clicked.connect(self.clearScalesRequested)
        hl.addWidget(b)
        v.addLayout(hl)
        v.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        self.tabs.addTab(sa, "Шкалы")

    def _div_to_code(self, div: float) -> float:
        p = getattr(self, "_prof", P2C53T)
        return p.code_center + div * p.codes_per_div

    def show_scales(self, m: Measurement | None):
        if m is None:
            return
        self._prof = m.prof
        self.tb_combo.set_value(m.time_per_div.value)
        self._set_src(self.tb_src, m.time_per_div)
        dt = m.sample_interval()
        self.dt_label.setText(f"{human_time(dt)} (экранные отсчёты, {m.prof.samples_per_div:g} на деление)"
                              if dt else "неизвестен")
        for ch in m.channels:
            w = self.ch_widgets[ch.name]
            w["group"].setTitle(f"{ch.name} — {'включён' if ch.enabled else 'выключен в файле'}")
            w["vdiv"].set_value(ch.volts_per_div.value)
            self._set_src(w["vsrc"], ch.volts_per_div)
            w["zero_on"].blockSignals(True)
            w["zero_on"].setChecked(ch.zero_code.known)
            w["zero_on"].blockSignals(False)
            w["zero"].blockSignals(True)
            pr = ch.prof
            w["zero"].setValue(((ch.zero_code.value if ch.zero_code.known else pr.code_center)
                                - pr.code_center) / pr.codes_per_div)
            w["zero"].blockSignals(False)
            self._set_src(w["zsrc"], ch.zero_code)
            pr = f"X{ch.probe.value}" if ch.probe.known else "щуп ?"
            cp = ch.coupling.value or "вход ?"
            w["probe"].setText(f"{pr}, {cp}  ({SOURCE_LABELS[ch.probe.source]}, справочно)")

    # ------------------------------------------------------------- view
    def _build_view(self):
        w = QWidget()
        f = QFormLayout(w)
        self.xmode = QComboBox()
        self.xmode.addItem("Время", "time")
        self.xmode.addItem("Номер отсчёта", "index")
        self.ymode = QComboBox()
        self.ymode.addItem("Напряжение, В", "volts")
        self.ymode.addItem("Деления от центра экрана", "div")
        self.ymode.addItem("Исходный код (0–255)", "raw")
        self.split = QComboBox()
        self.split.addItem("На одном графике", False)
        self.split.addItem("Каждый канал отдельно", True)
        self.lines = QCheckBox("Соединять отсчёты линией")
        self.lines.setChecked(True)
        self.points = QCheckBox("Показывать точки отсчётов")
        self.width = QDoubleSpinBox()
        self.width.setRange(0.5, 6)
        self.width.setSingleStep(0.5)
        self.width.setValue(1.5)
        self.grid = QCheckBox("Сетка")
        self.grid.setChecked(True)
        self.dark = QCheckBox("Тёмный фон")
        self.dark.setChecked(True)
        f.addRow("Ось X:", self.xmode)
        f.addRow("Ось Y:", self.ymode)
        f.addRow("Каналы:", self.split)
        f.addRow(self.lines)
        f.addRow(self.points)
        f.addRow("Толщина линии:", self.width)
        f.addRow(self.grid)
        f.addRow(self.dark)
        hl = QHBoxLayout()
        b = QPushButton("Сброс масштаба")
        b.setToolTip("Автомасштаб по данным (Ctrl+0)")
        b.clicked.connect(self.autoRangeRequested)
        hl.addWidget(b)
        b = QPushButton("Диапазон осей…")
        b.clicked.connect(self.manualRangeRequested)
        hl.addWidget(b)
        f.addRow(hl)
        self.view_note = QLabel("")
        self.view_note.setWordWrap(True)
        self.view_note.setStyleSheet("color:#c98a00;")
        f.addRow(self.view_note)
        hint = QLabel("Колесо мыши — масштаб, левая кнопка — перемещение, правая — масштаб по осям, "
                      "двойной щелчок по курсору не нужен: тяните линию. Интерполяция не применяется: "
                      "линия лишь соединяет соседние отсчёты.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;")
        f.addRow(hint)
        for wdg in (self.xmode, self.ymode, self.split):
            wdg.currentIndexChanged.connect(self._emit_view)
        for wdg in (self.lines, self.points, self.grid, self.dark):
            wdg.toggled.connect(self._emit_view)
        self.width.valueChanged.connect(self._emit_view)
        self.tabs.addTab(w, "Вид")

    def view_state(self) -> dict:
        return dict(xmode=self.xmode.currentData(), ymode=self.ymode.currentData(),
                    split=self.split.currentData(), lines=self.lines.isChecked(),
                    points=self.points.isChecked(), width=self.width.value(), grid=self.grid.isChecked(),
                    dark=self.dark.isChecked())

    def set_view_state(self, d: dict):
        for wdg, key in ((self.xmode, "xmode"), (self.ymode, "ymode"), (self.split, "split")):
            if key in d:
                i = wdg.findData(d[key])
                if i >= 0:
                    wdg.setCurrentIndex(i)
        for wdg, key in ((self.lines, "lines"), (self.points, "points"), (self.grid, "grid"), (self.dark, "dark")):
            if key in d:
                wdg.setChecked(bool(d[key]))
        if "width" in d:
            self.width.setValue(float(d["width"]))

    def _emit_view(self, *_):
        self.viewOptions.emit(self.view_state())

    # ---------------------------------------------------------- cursors
    def _build_cursors(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.cv = QCheckBox("Вертикальные курсоры A / B  (V)")
        self.ch = QCheckBox("Горизонтальные курсоры Y1 / Y2  (H)")
        self.csnap = QCheckBox("Привязка к ближайшему отсчёту  (S)")
        self.csnap.setChecked(True)
        self.cplot = QComboBox()
        self.cplot.addItem("Y-курсоры на графике 1", 0)
        self.cplot.addItem("Y-курсоры на графике 2", 1)
        self.cplot.setToolTip("Для режима «каждый канал отдельно»")
        for wdg in (self.cv, self.ch, self.csnap):
            v.addWidget(wdg)
            wdg.toggled.connect(self._emit_cursor)
        v.addWidget(self.cplot)
        self.cplot.currentIndexChanged.connect(self._emit_cursor)
        hl = QHBoxLayout()
        b = QPushButton("Сбросить курсоры (Esc)")
        b.clicked.connect(self.resetCursorsRequested)
        hl.addWidget(b)
        b = QPushButton("Копировать")
        b.clicked.connect(self._copy_cursor_table)
        hl.addWidget(b)
        v.addLayout(hl)
        self.ctable = QTableWidget(0, 2)
        self.ctable.setHorizontalHeaderLabels(["Величина", "Значение"])
        self.ctable.verticalHeader().hide()
        self.ctable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ctable.horizontalHeader().setStretchLastSection(True)
        self.ctable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        v.addWidget(self.ctable, 1)
        note = QLabel("1/|Δt| — величина, обратная интервалу между курсорами. Это частота сигнала только "
                      "если A и B стоят на соседних одинаковых фазах (например, на двух соседних фронтах).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        v.addWidget(note)
        self.tabs.addTab(w, "Курсоры")

    def cursor_state(self) -> dict:
        return dict(vertical=self.cv.isChecked(), horizontal=self.ch.isChecked(), snap=self.csnap.isChecked(),
                    hplot=self.cplot.currentData())

    def set_cursor_state(self, d: dict):
        for wdg, k in ((self.cv, "vertical"), (self.ch, "horizontal"), (self.csnap, "snap")):
            if k in d:
                wdg.blockSignals(True)
                wdg.setChecked(bool(d[k]))
                wdg.blockSignals(False)

    def _emit_cursor(self, *_):
        self.cursorOptions.emit(self.cursor_state())

    def show_cursor_readout(self, r: dict):
        rows = []
        xu, yu = r.get("xunit", ""), r.get("yunit", "")
        for row in r.get("rows", []):
            k = row["cursor"]
            rows.append((f"{k}: X", fmt_value(row["x"], xu)))
            rows.append((f"{k}: № отсчёта", str(row.get("index"))))
            for val in row["values"]:
                rows.append((f"{k}: {val['trace']}", f"{fmt_value(val['y'], yu)}   (код {val['raw']})"))
        if r.get("dx") is not None:
            rows.append(("Δt = B − A" if xu == "s" else "ΔX = B − A", fmt_value(r["dx"], xu)))
            if r.get("di") is not None:
                rows.append(("Δ отсчётов", str(r["di"])))
            inv = r.get("inv_dx")
            rows.append(("1/|Δt|" if xu == "s" else "1/|ΔX|",
                         fmt_value(inv, "Hz") if (inv and xu == "s") else (f"{inv:.6g} 1/отсч." if inv else "—")))
        if r.get("dy") is not None:
            rows.append(("Y1", fmt_value(r["y1"], yu)))
            rows.append(("Y2", fmt_value(r["y2"], yu)))
            rows.append(("ΔY = Y2 − Y1" if yu != "V" else "ΔV = Y2 − Y1", fmt_value(r["dy"], yu)))
        if not rows:
            rows.append(("", "Включите курсоры (клавиши V и H)"))
        self.ctable.setRowCount(len(rows))
        for i, (a, b) in enumerate(rows):
            self.ctable.setItem(i, 0, QTableWidgetItem(a))
            self.ctable.setItem(i, 1, QTableWidgetItem(b))
        self._cursor_rows = rows

    def _copy_cursor_table(self):
        rows = getattr(self, "_cursor_rows", [])
        QGuiApplication.clipboard().setText("\n".join(f"{a}\t{b}" for a, b in rows))

    # ------------------------------------------------------ measurements
    def _build_measure(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.level_mode = QComboBox()
        self.level_mode.addItem("середина размаха", "mid")
        self.level_mode.addItem("среднее значение", "mean")
        self.level_mode.addItem("вручную (дел от центра)", "manual")
        self.level_div = QDoubleSpinBox()
        self.level_div.setRange(-4, 4)
        self.level_div.setDecimals(2)
        self.level_div.setSingleStep(0.04)
        self.level_div.setSuffix(" дел")
        self.hyst = QDoubleSpinBox()
        self.hyst.setRange(0, 50)
        self.hyst.setValue(10)
        self.hyst.setSuffix(" % размаха")
        f.addRow("Уровень фронтов:", self.level_mode)
        f.addRow("Уровень вручную:", self.level_div)
        f.addRow("Гистерезис:", self.hyst)
        v.addLayout(f)
        self.level_mode.currentIndexChanged.connect(self._emit_measure)
        self.level_div.valueChanged.connect(self._emit_measure)
        self.hyst.valueChanged.connect(self._emit_measure)
        self.mtable = QTableWidget(0, 3)
        self.mtable.setHorizontalHeaderLabels(["Параметр", "CH1", "CH2"])
        self.mtable.verticalHeader().hide()
        self.mtable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.mtable.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.mtable.setWordWrap(True)
        v.addWidget(self.mtable, 1)
        b = QPushButton("Копировать таблицу")
        b.clicked.connect(self._copy_measure)
        v.addWidget(b)
        note = QLabel("Наведите на значение, чтобы увидеть метод расчёта. Все измерения — по экранным "
                      "отсчётам (2C53T: 301 точка, 1/25 дел; 2C53P: 461, 1/32 дел; 1013D: буфер 1500, 1/50 дел).")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        v.addWidget(note)
        self.tabs.addTab(w, "Измерения")

    def measure_state(self) -> dict:
        return dict(level_mode=self.level_mode.currentData(), level_div=self.level_div.value(),
                    hyst=self.hyst.value())

    def _emit_measure(self, *_):
        self.measureOptions.emit(self.measure_state())

    def show_measurements(self, res: dict[str, ChannelMeasurements], title: str = ""):
        keys, labels = [], {}
        for cm in res.values():
            for r in cm.results:
                if r.key not in labels:
                    keys.append(r.key)
                    labels[r.key] = r.label
        self.mtable.setRowCount(len(keys))
        for i, k in enumerate(keys):
            self.mtable.setItem(i, 0, QTableWidgetItem(labels[k]))
            for c, chn in ((1, "CH1"), (2, "CH2")):
                cm = res.get(chn)
                r = cm.get(k) if cm else None
                if r is None:
                    it = QTableWidgetItem("—" if cm is None else "")
                    it.setToolTip("канал выключен" if cm is None else "")
                else:
                    it = QTableWidgetItem(r.text())
                    it.setToolTip((r.method or "") + (("\n" + r.reason) if r.reason else ""))
                    if r.value is None:
                        it.setForeground(QBrush(QColor("#c98a00")))
                self.mtable.setItem(i, c, it)
        self.mtable.setHorizontalHeaderLabels(["Параметр", "CH1", "CH2"])

    def _copy_measure(self):
        out = []
        for i in range(self.mtable.rowCount()):
            out.append("\t".join((self.mtable.item(i, c).text() if self.mtable.item(i, c) else "")
                                 for c in range(3)))
        QGuiApplication.clipboard().setText("Параметр\tCH1\tCH2\n" + "\n".join(out))
