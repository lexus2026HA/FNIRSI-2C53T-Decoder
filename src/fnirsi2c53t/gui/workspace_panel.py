"""Workspace: loaded measurements, their visibility, colours and explicit display offsets."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QDoubleSpinBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..visualization.traces import DisplayItem


class WorkspacePanel(QWidget):
    changed = Signal()             # visibility / colours / offsets
    activeChanged = Signal(int)
    removeRequested = Signal(list)

    COLS = ["Пок.", "Файл", "CH1", "CH2", "Сдвиг X, отсч.", "Сдвиг Y, дел"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[DisplayItem] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        hl = QHBoxLayout()
        hl.addWidget(QLabel("<b>Рабочая область</b> (сравнение)"))
        hl.addStretch(1)
        b = QPushButton("Убрать")
        b.setToolTip("Убрать выбранные измерения из рабочей области (файлы не удаляются)")
        b.clicked.connect(self._remove)
        hl.addWidget(b)
        lay.addLayout(hl)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.currentCellChanged.connect(lambda r, *_: r >= 0 and self.activeChanged.emit(r))
        self.table.setToolTip("Смещения применяются только к отображению; экспорт содержит исходные координаты.")
        lay.addWidget(self.table)

    def set_items(self, items: list[DisplayItem], active: int = 0):
        self.items = items
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            cb = QCheckBox()
            cb.setChecked(it.shown)
            cb.toggled.connect(lambda v, it=it: self._set(it, "shown", v))
            self.table.setCellWidget(r, 0, self._center(cb))
            ni = QTableWidgetItem(it.label)
            ni.setToolTip(str(it.m.path))
            ni.setFlags(ni.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 1, ni)
            for c, chn in ((2, "CH1"), (3, "CH2")):
                ch = it.m.channel(chn)
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(2, 0, 2, 0)
                cb = QCheckBox()
                cb.setChecked(it.visible.get(chn, True))
                cb.setEnabled(bool(ch and ch.enabled))
                cb.setToolTip("показывать канал" if ch and ch.enabled else "канал выключен в файле")
                cb.toggled.connect(lambda v, it=it, chn=chn: self._set_vis(it, chn, v))
                btn = QPushButton()
                btn.setFixedSize(18, 18)
                btn.setStyleSheet(f"background:{it.colors.get(chn)}; border:1px solid #555;")
                btn.setToolTip("цвет кривой")
                btn.clicked.connect(lambda _=False, it=it, chn=chn, b=btn: self._pick_color(it, chn, b))
                hl.addWidget(cb)
                hl.addWidget(btn)
                self.table.setCellWidget(r, c, w)
            for c, attr, rng, step in ((4, "x_shift_samples", 300, 1.0), (5, "y_shift_div", 16, 0.04)):
                sp = QDoubleSpinBox()
                sp.setRange(-rng, rng)
                sp.setDecimals(2)
                sp.setSingleStep(step)
                sp.setValue(getattr(it, attr))
                sp.valueChanged.connect(lambda v, it=it, a=attr: self._set(it, a, v))
                self.table.setCellWidget(r, c, sp)
        if items:
            self.table.selectRow(max(0, min(active, len(items) - 1)))
        self.table.blockSignals(False)

    @staticmethod
    def _center(w):
        c = QWidget()
        hl = QHBoxLayout(c)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setAlignment(Qt.AlignCenter)
        hl.addWidget(w)
        return c

    def _set(self, it, attr, v):
        setattr(it, attr, v)
        self.changed.emit()

    def _set_vis(self, it, chn, v):
        it.visible[chn] = v
        self.changed.emit()

    def _pick_color(self, it, chn, btn):
        c = QColorDialog.getColor(QColor(it.colors.get(chn, "#888888")), self, f"Цвет {it.label} {chn}")
        if c.isValid():
            it.colors[chn] = c.name()
            btn.setStyleSheet(f"background:{c.name()}; border:1px solid #555;")
            self.changed.emit()

    def _remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if rows:
            self.removeRequested.emit(rows)

    def current_row(self) -> int:
        return self.table.currentRow()
