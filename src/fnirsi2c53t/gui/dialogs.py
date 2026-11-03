"""Export, batch export, settings and axis-range dialogs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QVBoxLayout)

CSV_STYLES = {
    "machine_comma": ("Машинный: запятая, десятичная точка", ",", "."),
    "machine_semicolon": ("Машинный: точка с запятой, десятичная точка", ";", "."),
    "excel_ru": ("Для русского Excel: «;» и десятичная запятая", ";", ","),
}


def settings() -> QSettings:
    return QSettings("FNIRSI-2C53T-Decoder", "FNIRSI-2C53T-Decoder")


class ExportDialog(QDialog):
    """Choose formats for the current measurement(s)."""

    def __init__(self, parent, n_items: int, default_dir: str):
        super().__init__(parent)
        self.setWindowTitle("Экспорт")
        s = settings()
        lay = QVBoxLayout(self)
        g = QGroupBox("Что экспортировать")
        gl = QVBoxLayout(g)
        self.scope_active = QRadioButton("Активное измерение")
        self.scope_all = QRadioButton(f"Все измерения рабочей области ({n_items}) — каждое отдельно")
        self.scope_joint = QRadioButton(f"Все измерения рабочей области — один общий CSV")
        self.scope_active.setChecked(True)
        for w in (self.scope_active, self.scope_all, self.scope_joint):
            gl.addWidget(w)
            w.setEnabled(n_items > 1 or w is self.scope_active)
        lay.addWidget(g)
        g = QGroupBox("Форматы")
        f = QFormLayout(g)
        self.fmt = {}
        row = QHBoxLayout()
        for k, t in (("csv", "CSV"), ("xlsx", "XLSX"), ("json", "JSON"), ("png", "PNG"), ("svg", "SVG"),
                     ("pdf", "PDF")):
            cb = QCheckBox(t)
            cb.setChecked(s.value(f"export/{k}", k == "csv", type=bool))
            self.fmt[k] = cb
            row.addWidget(cb)
        f.addRow(row)
        self.csv_style = QComboBox()
        for k, (t, _, _) in CSV_STYLES.items():
            self.csv_style.addItem(t, k)
        i = self.csv_style.findData(s.value("export/csv_style", "machine_comma"))
        self.csv_style.setCurrentIndex(max(i, 0))
        f.addRow("CSV:", self.csv_style)
        self.sidecar = QCheckBox("Метаданные CSV в отдельном .meta.json")
        self.sidecar.setChecked(s.value("export/sidecar", True, type=bool))
        f.addRow(self.sidecar)
        self.img_view = QComboBox()
        self.img_view.addItem("Отчётный график (белый фон, текущий масштаб и курсоры)", "report")
        self.img_view.addItem("Как на экране (снимок области графика)", "screen")
        f.addRow("Изображения:", self.img_view)
        lay.addWidget(g)
        row = QHBoxLayout()
        self.dir = QLineEdit(s.value("export/dir", default_dir))
        b = QPushButton("…")
        b.clicked.connect(self._pick_dir)
        row.addWidget(self.dir, 1)
        row.addWidget(b)
        lay.addWidget(QLabel("Папка (не на осциллографе — исходные файлы не изменяются):"))
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для экспорта", self.dir.text())
        if d:
            self.dir.setText(d)

    def accept(self):
        s = settings()
        for k, cb in self.fmt.items():
            s.setValue(f"export/{k}", cb.isChecked())
        s.setValue("export/csv_style", self.csv_style.currentData())
        s.setValue("export/sidecar", self.sidecar.isChecked())
        s.setValue("export/dir", self.dir.text())
        super().accept()

    def options(self) -> dict:
        _, sep, dec = CSV_STYLES[self.csv_style.currentData()]
        scope = "active" if self.scope_active.isChecked() else "all" if self.scope_all.isChecked() else "joint"
        return dict(formats=[k for k, cb in self.fmt.items() if cb.isChecked()], sep=sep, decimal=dec,
                    sidecar=self.sidecar.isChecked(), dir=Path(self.dir.text()), scope=scope,
                    image_view=self.img_view.currentData())


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        s = settings()
        f = QFormLayout(self)
        self.auto_bmp = QCheckBox("Автоматически применять шкалы, распознанные по BMP-снимку")
        self.auto_bmp.setChecked(s.value("auto_bmp", True, type=bool))
        self.auto_bmp.setToolTip("Применяются только если декодированные отсчёты совпали с лучом на снимке. "
                                 "Такие значения помечаются как «распознано по BMP».")
        f.addRow(self.auto_bmp)
        self.removable_only = QCheckBox("Показывать в списке дисков только съёмные")
        self.removable_only.setChecked(s.value("removable_only", True, type=bool))
        f.addRow(self.removable_only)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def accept(self):
        s = settings()
        s.setValue("auto_bmp", self.auto_bmp.isChecked())
        s.setValue("removable_only", self.removable_only.isChecked())
        super().accept()


class RangeDialog(QDialog):
    def __init__(self, parent, view, xunit, yunit):
        super().__init__(parent)
        self.setWindowTitle("Диапазон осей")
        f = QFormLayout(self)
        self.sp = []
        for lab, v in zip((f"X мин ({xunit})", f"X макс ({xunit})", f"Y мин ({yunit})", f"Y макс ({yunit})"), view):
            s = QDoubleSpinBox()
            s.setDecimals(9)
            s.setRange(-1e12, 1e12)
            s.setValue(v)
            f.addRow(lab, s)
            self.sp.append(s)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        x0, x1, y0, y1 = (s.value() for s in self.sp)
        return (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1))
