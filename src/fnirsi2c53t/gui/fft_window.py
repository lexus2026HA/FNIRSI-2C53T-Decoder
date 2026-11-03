"""Spectrum (FFT) window."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..analysis.fft import WINDOWS, compute_spectrum
from ..analysis.cursors import nearest_index
from ..exporters import data_export
from .plot_area import fmt_value


class FftWindow(QDialog):
    computed = Signal(dict)

    def __init__(self, parent, get_measurement, get_cursor_range):
        super().__init__(parent)
        self.setWindowTitle("Спектр (FFT)")
        self.resize(1000, 620)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.get_measurement = get_measurement
        self.get_cursor_range = get_cursor_range
        self.result = None
        lay = QHBoxLayout(self)
        side = QWidget()
        f = QFormLayout(side)
        self.ch = QComboBox()
        self.seg = QComboBox()
        self.seg.addItem("Весь сигнал", "all")
        self.seg.addItem("Между курсорами A и B", "cursors")
        self.win = QComboBox()
        for k, v in WINDOWS.items():
            self.win.addItem(v, k)
        self.win.setCurrentIndex(1)
        self.dc = QCheckBox("Удалить постоянную составляющую")
        self.dc.setChecked(True)
        self.nfft = QComboBox()
        self.nfft.addItem("N (без дополнения)", 1)
        self.nfft.addItem("2N (дополнение нулями)", 2)
        self.nfft.addItem("4N (дополнение нулями)", 4)
        self.nfft.addItem("8N (дополнение нулями)", 8)
        self.ylog = QCheckBox("Амплитуда в дБ")
        f.addRow("Канал:", self.ch)
        f.addRow("Участок:", self.seg)
        f.addRow("Окно:", self.win)
        f.addRow(self.dc)
        f.addRow("Размер FFT:", self.nfft)
        f.addRow(self.ylog)
        b = QPushButton("Рассчитать")
        b.clicked.connect(self.compute)
        f.addRow(b)
        self.peaks = QTableWidget(0, 2)
        self.peaks.setHorizontalHeaderLabels(["Частота", "Амплитуда"])
        self.peaks.verticalHeader().hide()
        self.peaks.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.peaks.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        f.addRow(QLabel("Наибольшие пики:"))
        f.addRow(self.peaks)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#c98a00;")
        f.addRow(self.note)
        hl = QHBoxLayout()
        b1 = QPushButton("CSV…")
        b1.clicked.connect(lambda: self.export("csv"))
        b2 = QPushButton("XLSX…")
        b2.clicked.connect(lambda: self.export("xlsx"))
        hl.addWidget(b1)
        hl.addWidget(b2)
        f.addRow("Экспорт спектра:", hl)
        side.setMaximumWidth(340)
        self.plot = pg.PlotWidget(background="#101418")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(side)
        sp.addWidget(self.plot)
        sp.setSizes([320, 680])
        lay.addWidget(sp)
        for w in (self.ch, self.seg, self.win, self.nfft):
            w.currentIndexChanged.connect(self.compute)
        for w in (self.dc, self.ylog):
            w.toggled.connect(self.compute)

    def refresh_channels(self):
        m = self.get_measurement()
        cur = self.ch.currentData()
        self.ch.blockSignals(True)
        self.ch.clear()
        if m:
            for c in m.enabled_channels:
                self.ch.addItem(c.name, c.name)
        i = self.ch.findData(cur)
        self.ch.setCurrentIndex(max(0, i))
        self.ch.blockSignals(False)

    def compute(self, *_):
        m = self.get_measurement()
        self.plot.clear()
        self.peaks.setRowCount(0)
        if m is None or self.ch.count() == 0:
            self.note.setText("Нет данных.")
            return
        ch = m.channel(self.ch.currentData())
        y = ch.volts() if ch.has_volts else ch.divisions()
        unit = "V" if ch.has_volts else "дел"
        lo, hi = 0, m.n_samples
        seg_txt = "весь сигнал"
        if self.seg.currentData() == "cursors":
            r = self.get_cursor_range()
            if r is None:
                self.note.setText("Курсоры A/B не включены — используется весь сигнал.")
            else:
                lo, hi = sorted(r)
                hi += 1
                seg_txt = f"отсчёты {lo}…{hi - 1}"
        try:
            sp = compute_spectrum(y[lo:hi], m.sample_interval(), self.win.currentData(), self.dc.isChecked(),
                                  (hi - lo) * self.nfft.currentData(), unit)
        except ValueError as e:
            self.note.setText(str(e))
            return
        amp = sp.amp
        if self.ylog.isChecked():
            ref = amp.max() if amp.max() > 0 else 1
            amp = 20 * np.log10(np.maximum(amp, ref * 1e-6) / ref)
            ylab, yunit = "Амплитуда, дБ от макс.", ""
        else:
            ylab, yunit = f"Амплитуда (пик), {unit}", ""
        self.plot.plot(sp.freq, amp, pen=pg.mkPen("#3fd0ff", width=1.2), stepMode=None)
        if sp.freq_unit == "Hz":
            self.plot.setLabel("bottom", "Частота", units="Hz")
        else:
            self.plot.setLabel("bottom", "Нормированная частота, циклов/отсчёт")
        self.plot.setLabel("left", ylab)
        self.peaks.setRowCount(len(sp.peaks))
        for i, pk in enumerate(sp.peaks):
            fu = sp.freq_unit
            self.peaks.setItem(i, 0, QTableWidgetItem(fmt_value(pk["freq"], "Hz") if fu == "Hz" else f"{pk['freq']:.4f}"))
            self.peaks.setItem(i, 1, QTableWidgetItem(fmt_value(pk["amp"], "V") if unit == "V" else f"{pk['amp']:.4g} дел"))
        res_txt = fmt_value(sp.resolution, "Hz") if sp.freq_unit == "Hz" else f"{sp.resolution:.4f} цикл/отсч."
        notes = [f"{sp.n_samples} отсчётов, разрешение {res_txt}."] + sp.notes
        if sp.freq_unit == "Hz":
            notes.append("Частоты выше половины частоты экранных отсчётов не видны; экранные данные "
                         "прибора могут содержать наложение спектров.")
        self.note.setText("\n".join(notes))
        d = sp.as_dict()
        d.update(channel=ch.name, segment=seg_txt, source=str(m.path))
        self.result = d
        m.fft_result = d
        self.computed.emit(d)

    def export(self, kind):
        if not self.result:
            QMessageBox.information(self, "Экспорт", "Сначала рассчитайте спектр.")
            return
        m = self.get_measurement()
        base = (m.path.stem + "_fft") if m else "spectrum"
        flt = "CSV (*.csv)" if kind == "csv" else "Excel (*.xlsx)"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить спектр", base + "." + kind, flt)
        if not path:
            return
        try:
            if kind == "csv":
                data_export.write_spectrum_csv(self.result, path)
            else:
                data_export.write_spectrum_xlsx(self.result, path)
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", f"Не удалось сохранить: {e.strerror or e}")
