"""Left panel: drives, folder tree, file table with decode status."""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFileSystemModel, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTreeView, QVBoxLayout, QWidget)

from ..decoders.fnirsi_2c53t import DecodeError, decode_bytes, find_bin_for, find_bmp_for, read_file_readonly
from ..decoders.profiles import MODEL_CHOICES, profile_by_key
from ..io.drives import FILTERS, guess_capture_folder, list_drives, list_files

COL_NAME, COL_SIZE, COL_DATE, COL_STATUS, COL_RESULT = range(5)
STATUS_COLORS = {"OK": "#2e9d4a", "предупр.": "#c98a00", "ошибка": "#d03030", "—": "#888888"}


class FilePanel(QWidget):
    openRequested = Signal(list, bool)       # paths, add_to_workspace
    message = Signal(str)
    folderChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder: Path | None = None
        self.cache: dict[str, tuple[float, str, str]] = {}
        self._queue: list[Path] = []
        self._drives_sig = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.drive_combo = QComboBox()
        self.drive_combo.setToolTip("Съёмные диски (осциллограф FNIRSI 2C53T определяется как съёмный диск)")
        self.drive_combo.activated.connect(self._drive_chosen)
        row.addWidget(self.drive_combo, 1)
        b = QPushButton("Папка…")
        b.setToolTip("Выбрать произвольную папку")
        b.clicked.connect(self.choose_folder)
        row.addWidget(b)
        lay.addLayout(row)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Модель:"))
        self.model_combo = QComboBox()
        for k, t in MODEL_CHOICES.items():
            self.model_combo.addItem(t, k)
        self.model_combo.setToolTip(
            "Авто: 2C53T/2C53P определяются по размеру BIN, снимок без BIN оцифровывается как 2C23T.\n"
            "2C23T сохраняет только снимки экрана — кривая оцифровывается по пикселям (±1 px).\n"
            "1013D: формат ещё не исследован (нужны файлы с прибора).")
        from .dialogs import settings
        i = self.model_combo.findData(settings().value("model", "auto"))
        self.model_combo.setCurrentIndex(max(0, i))
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        mrow.addWidget(self.model_combo, 1)
        lay.addLayout(mrow)

        split = QSplitter(Qt.Vertical)
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.fs_model.setReadOnly(True)
        self.fs_model.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self._tree_clicked)
        split.addWidget(self.tree)

        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        frow = QHBoxLayout()
        self.filter_combo = QComboBox()
        for k, (title, _) in FILTERS.items():
            self.filter_combo.addItem(title, k)
        self.filter_combo.currentIndexChanged.connect(lambda *_: self.refresh())
        frow.addWidget(QLabel("Фильтр:"))
        frow.addWidget(self.filter_combo, 1)
        wl.addLayout(frow)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Имя", "Размер", "Изменён", "Статус", "Результат"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setSortingEnabled(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        self.table.setColumnWidth(COL_NAME, 80)
        self.table.setColumnWidth(COL_SIZE, 64)
        self.table.setColumnWidth(COL_DATE, 112)
        self.table.setColumnWidth(COL_STATUS, 70)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        wl.addWidget(self.table, 1)
        brow = QHBoxLayout()
        b1 = QPushButton("Открыть")
        b1.setToolTip("Открыть выбранный файл (заменяет текущее измерение)")
        b1.clicked.connect(lambda: self._emit_selected(False))
        b2 = QPushButton("Добавить")
        b2.setToolTip("Добавить выбранные файлы в рабочую область (сравнение)")
        b2.clicked.connect(lambda: self._emit_selected(True))
        b3 = QPushButton("Обновить")
        b3.setToolTip("Обновить список дисков и файлов (F5)")
        b3.clicked.connect(self.refresh_all)
        for bb in (b1, b2, b3):
            brow.addWidget(bb)
        wl.addLayout(brow)
        split.addWidget(w)
        split.setSizes([160, 400])
        lay.addWidget(split, 1)

        self._decode_timer = QTimer(self)
        self._decode_timer.setInterval(15)
        self._decode_timer.timeout.connect(self._decode_step)
        self._drive_timer = QTimer(self)
        self._drive_timer.setInterval(2000)
        self._drive_timer.timeout.connect(self._poll_drives)
        self._drive_timer.start()
        self.update_drives(initial=True)

    def model(self) -> str:
        return self.model_combo.currentData() or "auto"

    def _model_changed(self, *_):
        from .dialogs import settings
        settings().setValue("model", self.model())
        p = profile_by_key(self.model())
        if p is not None and not p.supported:
            self.message.emit(f"FNIRSI {p.model}: формат ещё не исследован — подключите прибор и пришлите файлы.")
        self.refresh()

    # ------------------------------------------------------------ drives
    def update_drives(self, initial=False):
        drives = list_drives(getattr(self, "removable_only", True))
        sig = tuple(d.root for d in drives)
        if not initial and sig == self._drives_sig:
            return
        added = set(sig) - set(self._drives_sig or ())
        removed = set(self._drives_sig or ()) - set(sig)
        self._drives_sig = sig
        cur = self.drive_combo.currentData()
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        self.drive_combo.addItem("— выберите съёмный диск —" if drives else "Съёмные диски не найдены", None)
        for d in drives:
            self.drive_combo.addItem(d.title, d.root)
        i = self.drive_combo.findData(cur)
        self.drive_combo.setCurrentIndex(max(i, 0))
        self.drive_combo.blockSignals(False)
        if not initial:
            if added:
                self.message.emit("Подключён съёмный диск: " + ", ".join(sorted(added)))
            if removed:
                self.message.emit("Отключён съёмный диск: " + ", ".join(sorted(removed)))
                if self.folder and any(str(self.folder).upper().startswith(r.upper()) for r in removed):
                    self._folder_lost()

    def _poll_drives(self):
        try:
            self.update_drives()
        except Exception:
            pass
        if self.folder is not None and not self._exists(self.folder):
            self._folder_lost()

    @staticmethod
    def _exists(p: Path) -> bool:
        try:
            return p.is_dir()
        except OSError:
            return False

    def _folder_lost(self):
        self.message.emit(f"Папка {self.folder} больше недоступна (диск отключён?). "
                          "Уже открытые измерения остаются в памяти.")
        self.table.setRowCount(0)
        self.folder = None
        self._queue.clear()

    def _drive_chosen(self, idx):
        root = self.drive_combo.itemData(idx)
        if root:
            self.set_folder(guess_capture_folder(root))

    def choose_folder(self):
        start = str(self.folder) if self.folder else ""
        d = QFileDialog.getExistingDirectory(self, "Папка с измерениями", start)
        if d:
            self.set_folder(Path(d))

    # ------------------------------------------------------------ listing
    def set_folder(self, folder: Path):
        self.folder = Path(folder)
        idx = self.fs_model.index(str(self.folder))
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
            self.tree.scrollTo(idx)
            self.tree.expand(idx)
        self.refresh()
        self.folderChanged.emit(str(self.folder))

    def _tree_clicked(self, idx: QModelIndex):
        self.folder = Path(self.fs_model.filePath(idx))
        self.refresh()
        self.folderChanged.emit(str(self.folder))

    def refresh_all(self):
        self.update_drives(initial=True)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        self._queue.clear()
        if self.folder is None:
            return
        key = self.filter_combo.currentData() or "supported"
        try:
            files = list_files(self.folder, key)
        except OSError as e:
            self.message.emit(f"Не удалось прочитать папку {self.folder}: {e.strerror or e}")
            return
        self.table.setRowCount(len(files))
        for r, f in enumerate(files):
            it = QTableWidgetItem(f.path.name)
            it.setData(Qt.UserRole, str(f.path))
            it.setToolTip(str(f.path))
            self.table.setItem(r, COL_NAME, it)
            si = QTableWidgetItem(f"{f.size:,}".replace(",", " "))
            si.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, COL_SIZE, si)
            self.table.setItem(r, COL_DATE, QTableWidgetItem(
                _dt.datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")))
            if f.ext in (".bin", ".wav"):
                c = self.cache.get(str(f.path))
                if c and c[0] == f.mtime:
                    self._set_status(r, c[1], c[2])
                else:
                    self._set_status(r, "—", "ожидает")
                    self._queue.append(f.path)
            elif f.ext == ".bmp" and f.size == 800000:
                self._set_status(r, "", "снимок 1013D (данные — в .wav)")
            elif f.ext == ".bmp":
                if find_bin_for(f.path) is not None and self.model() != "2c23t":
                    self._set_status(r, "", "снимок экрана к BIN")
                else:
                    self._set_status(r, "снимок", "без BIN: кривая будет оцифрована со снимка (±1 px)")
            else:
                self._set_status(r, "", "не осциллограмма")
        self.message.emit(f"{self.folder}: {len(files)} файл(ов)")
        if self._queue:
            self._decode_timer.start()

    def _row_of(self, path: Path) -> int:
        for r in range(self.table.rowCount()):
            if self.table.item(r, COL_NAME).data(Qt.UserRole) == str(path):
                return r
        return -1

    def _set_status(self, row: int, status: str, result: str):
        it = QTableWidgetItem(status)
        col = STATUS_COLORS.get(status)
        if col:
            it.setForeground(QBrush(QColor(col)))
        self.table.setItem(row, COL_STATUS, it)
        ri = QTableWidgetItem(result)
        ri.setToolTip(result)
        self.table.setItem(row, COL_RESULT, ri)

    def _decode_step(self):
        for _ in range(8):
            if not self._queue:
                self._decode_timer.stop()
                return
            p = self._queue.pop(0)
            status, result = self.quick_status(p)
            try:
                mt = os.stat(p).st_mtime
            except OSError:
                mt = 0
            self.cache[str(p)] = (mt, status, result)
            r = self._row_of(p)
            if r >= 0:
                self._set_status(r, status, result)

    @staticmethod
    def quick_status(p: Path) -> tuple[str, str]:
        try:
            m = decode_bytes(read_file_readonly(p), p)
        except DecodeError as e:
            return "ошибка", str(e)
        except Exception as e:
            return "ошибка", f"непредвиденная ошибка: {e}"
        chans = "+".join(c.name for c in m.enabled_channels) or "каналы выкл."
        bmp = " · есть BMP" if find_bmp_for(p) else ""
        if m.warnings:
            return "предупр.", f"{chans}{bmp} · {m.warnings[0]}"
        return "OK", f"{m.prof.model}: {chans}, {m.n_samples} отсч.{bmp}"

    def update_status(self, path: Path, status: str, result: str):
        r = self._row_of(path)
        if r >= 0:
            self._set_status(r, status, result)

    # ------------------------------------------------------------ actions
    def selected_paths(self) -> list[Path]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [Path(self.table.item(r, COL_NAME).data(Qt.UserRole)) for r in rows]

    def _is_capture(self, p: Path) -> bool:
        """A BIN, or a screenshot that has no BIN (2C23T: the curve is digitised)."""
        ext = p.suffix.lower()
        if ext in (".bin", ".wav"):
            return self.model() != "2c23t"
        if ext == ".bmp":
            return self.model() == "2c23t" or find_bin_for(p) is None
        return False

    def selected_bins(self) -> list[Path]:
        return [p for p in self.selected_paths() if self._is_capture(p)]

    def all_bins(self) -> list[Path]:
        out = []
        for r in range(self.table.rowCount()):
            p = Path(self.table.item(r, COL_NAME).data(Qt.UserRole))
            if self._is_capture(p):
                out.append(p)
        return out

    def _emit_selected(self, add: bool):
        paths = self.selected_paths()
        if not paths:
            self.message.emit("Выберите файл(ы) в списке.")
            return
        self.openRequested.emit(paths, add)

    def _double_clicked(self, row, col):
        p = Path(self.table.item(row, COL_NAME).data(Qt.UserRole))
        self.openRequested.emit([p], False)

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Открыть", lambda: self._emit_selected(False))
        menu.addAction("Добавить в рабочую область", lambda: self._emit_selected(True))
        menu.addSeparator()
        menu.addAction("Показать в проводнике", self._reveal)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reveal(self):
        ps = self.selected_paths()
        if ps:
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(ps[0])])
