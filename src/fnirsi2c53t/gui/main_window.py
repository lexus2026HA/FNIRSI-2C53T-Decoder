"""Main application window."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressDialog,
                               QSplitter, QTabWidget, QToolBar, QWidget)

from .. import APP_NAME, __version__
from ..analysis.measurements import EdgeSettings, measure_all
from ..decoders import bmp_screen
from ..decoders.fnirsi_2c53t import DecodeError, find_bin_for
from ..decoders.screen_digitizer import open_capture
from ..decoders.model import SRC_USER
from ..exporters import batch, data_export, image_export
from ..session import load_session, save_session
from ..visualization.traces import EXTRA_PALETTE, DisplayItem, build_traces
from .bmp_view import BmpView
from .dialogs import CSV_STYLES, ExportDialog, RangeDialog, SettingsDialog, settings
from .fft_window import FftWindow
from .file_panel import FilePanel
from .params_panel import ParamsPanel
from .plot_area import PlotArea, fmt_value
from .workspace_panel import WorkspacePanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        self.items: list[DisplayItem] = []
        self.active = 0
        self.edge = EdgeSettings()
        self.fft_win: FftWindow | None = None
        self.last_measurements = {}

        # --- panels
        self.files = FilePanel()
        self.files.removable_only = settings().value("removable_only", True, type=bool)
        self.workspace = WorkspacePanel()
        left = QSplitter(Qt.Vertical)
        left.addWidget(self.files)
        left.addWidget(self.workspace)
        left.setSizes([520, 200])
        self.plot = PlotArea()
        self.bmp = BmpView()
        self.center = QTabWidget()
        self.center.addTab(self.plot, "Осциллограмма")
        self.center.addTab(self.bmp, "Снимок BMP")
        self.params = ParamsPanel()
        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(left)
        self.split.addWidget(self.center)
        self.split.addWidget(self.params)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([400, 840, 380])
        self.left_panel = left
        self.setCentralWidget(self.split)

        # --- status bar
        sb = self.statusBar()
        self.st_coord = QLabel("")
        self.st_decode = QLabel("")
        self.st_samples = QLabel("")
        self.st_warn = QLabel("")
        self.st_warn.setStyleSheet("color:#c98a00;")
        sb.addWidget(self.st_coord, 1)
        sb.addPermanentWidget(self.st_decode)
        sb.addPermanentWidget(self.st_samples)
        sb.addPermanentWidget(self.st_warn)

        self._build_actions()
        self._connect()
        self.refresh()
        g = settings().value("geometry")
        if isinstance(g, QByteArray):
            self.restoreGeometry(g)
        else:
            self.resize(1500, 880)
        last = settings().value("last_folder", "")
        if last and os.path.isdir(last):
            QTimer.singleShot(0, lambda: self.files.set_folder(Path(last)))

    # ------------------------------------------------------------ actions
    def _act(self, text, slot, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        a.setCheckable(checkable)
        if checkable:
            a.toggled.connect(slot)
        else:
            a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self):
        A = self._act
        self.a_open_dir = A("Открыть диск/папку…", self.files.choose_folder, "Ctrl+O",
                            "Выбрать съёмный диск или папку с измерениями")
        self.a_refresh = A("Обновить", self.files.refresh_all, "F5", "Обновить список дисков и файлов")
        self.a_add = A("Добавить измерение…", self.add_files_dialog, "Ctrl+Shift+O",
                       "Добавить BIN-файлы в рабочую область")
        self.a_export = A("Экспорт…", self.export_dialog, "Ctrl+E", "Экспорт CSV / XLSX / JSON / PNG / SVG / PDF")
        self.a_batch = A("Пакетный экспорт…", self.batch_export, "Ctrl+Shift+E",
                         "Экспорт выбранных в списке файлов (или всех BIN папки)")
        self.a_fft = A("Спектр (FFT)…", self.show_fft, "F", "Частотный анализ")
        self.a_settings = A("Настройки…", self.settings_dialog, None, "Настройки программы")
        self.a_save_view = A("Сохранить вид графика…", self.save_view, "Ctrl+S", "PNG / SVG / PDF текущего вида")
        self.a_session_save = A("Сохранить сессию…", self.save_session, "Ctrl+Shift+S")
        self.a_session_open = A("Открыть сессию…", self.open_session, "Ctrl+Shift+L")
        self.a_max = A("Развернуть график", self.toggle_maximize, "F11", "Скрыть/показать боковые панели",
                       checkable=True)
        self.a_autorange = A("Сброс масштаба", self.plot.auto_range, "Ctrl+0")
        self.a_copy_pt = A("Копировать координаты точки", self.copy_point, "Ctrl+Shift+C",
                           "Копирует ближайший к мыши отсчёт")
        self.a_vc = A("Курсоры A/B", lambda: self.params.cv.toggle(), "V")
        self.a_hc = A("Курсоры Y1/Y2", lambda: self.params.ch.toggle(), "H")
        self.a_snap = A("Привязка курсоров", lambda: self.params.csnap.toggle(), "S")
        self.a_reset_c = A("Сбросить курсоры и измерения", self.reset_cursors, "Esc")

        tb = QToolBar("Главная")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in (self.a_open_dir, self.a_refresh, self.a_add, None, self.a_export, self.a_batch,
                  self.a_save_view, None, self.a_fft, None, self.a_max, None, self.a_settings):
            if a is None:
                tb.addSeparator()
            else:
                tb.addAction(a)
        self.addToolBar(tb)

        mb = self.menuBar()
        m = mb.addMenu("&Файл")
        for a in (self.a_open_dir, self.a_add, self.a_refresh, None, self.a_session_open, self.a_session_save,
                  None, self.a_export, self.a_batch, self.a_save_view, None):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction("Выход", self.close)
        m = mb.addMenu("&Вид")
        for a in (self.a_max, self.a_autorange, self.a_copy_pt):
            m.addAction(a)
        m = mb.addMenu("&Курсоры")
        for a in (self.a_vc, self.a_hc, self.a_snap, self.a_reset_c):
            m.addAction(a)
        m = mb.addMenu("&Анализ")
        m.addAction(self.a_fft)
        m = mb.addMenu("&Справка")
        m.addAction("Горячие клавиши", self.show_keys)
        m.addAction("О программе", self.about)
        self.addAction(self.a_settings)

    def _connect(self):
        self.files.openRequested.connect(self.open_paths)
        self.files.message.connect(lambda s: self.statusBar().showMessage(s, 8000))
        self.files.folderChanged.connect(lambda f: settings().setValue("last_folder", f))
        self.workspace.changed.connect(lambda: self.refresh(keep_view=True))
        self.workspace.activeChanged.connect(self.set_active)
        self.workspace.removeRequested.connect(self.remove_items)
        self.plot.hoverText.connect(self.st_coord.setText)
        self.plot.cursorsChanged.connect(self.update_cursor_readout)
        p = self.params
        p.scalesEdited.connect(self.on_scale_edit)
        p.applyBmpRequested.connect(self.apply_bmp)
        p.clearScalesRequested.connect(self.clear_scales)
        p.viewOptions.connect(self.on_view_options)
        p.autoRangeRequested.connect(self.plot.auto_range)
        p.manualRangeRequested.connect(self.manual_range)
        p.cursorOptions.connect(self.on_cursor_options)
        p.resetCursorsRequested.connect(self.reset_cursors)
        p.measureOptions.connect(self.on_measure_options)

    # ------------------------------------------------------------ opening
    @property
    def m(self):
        if 0 <= self.active < len(self.items):
            return self.items[self.active].m
        return None

    def _resolve(self, p: Path) -> Path | None:
        if p.suffix.lower() in (".bin", ".wav"):
            return p
        if p.suffix.lower() == ".bmp":
            c = find_bin_for(p)
            if c is not None and self.files.model() in ("auto", "2c53t", "2c53p"):
                return c
            return p          # no BIN: the curve is digitised from the screenshot
        self.statusBar().showMessage(f"{p.name}: не осциллограмма (поддерживаются .bin и .bmp).", 8000)
        return None

    def open_paths(self, paths, add=False):
        paths = [q for q in (self._resolve(Path(p)) for p in paths) if q]
        if not paths:
            return
        auto_bmp = settings().value("auto_bmp", True, type=bool)
        new, errors = [], []
        for p in paths:
            if add and any(it.m.path == p for it in self.items):
                continue
            try:
                m = open_capture(p, self.files.model(), apply_bmp_scales=auto_bmp)
            except DecodeError as e:
                errors.append(f"{p.name}: {e}")
                self.files.update_status(p, "ошибка", str(e))
                continue
            except Exception as e:
                errors.append(f"{p.name}: непредвиденная ошибка: {e}")
                continue
            new.append(DisplayItem(m))
            chans = "+".join(c.name for c in m.enabled_channels) or "луч не найден"
            src = "оцифровано со снимка" if m.prof.bmp_only or m.decoder_version.startswith("screen") else \
                f"{m.n_samples} отсч."
            self.files.update_status(p, "предупр." if m.warnings and not m.enabled_channels else "OK",
                                     f"{m.prof.model}: {chans}, {src}")
        if errors:
            QMessageBox.warning(self, "Не удалось открыть", "\n".join(errors))
        if not new:
            return
        replace = not add and len(paths) == 1
        if replace:
            self.items = new
            self.active = 0
        else:
            self.items.extend(new)
            self.active = len(self.items) - len(new)
        self._assign_colors()
        self.workspace.set_items(self.items, self.active)
        self.refresh(keep_view=False)
        self.statusBar().showMessage(f"Открыто: {', '.join(it.m.name for it in new)}", 6000)

    def _assign_colors(self):
        """First measurement keeps channel colours, the others get distinct ones."""
        if len(self.items) <= 1:
            return
        k = 0
        for i, it in enumerate(self.items):
            if i == 0:
                continue
            if it.colors == DisplayItem(it.m).colors:
                it.colors = {"CH1": EXTRA_PALETTE[k % len(EXTRA_PALETTE)],
                             "CH2": EXTRA_PALETTE[(k + 1) % len(EXTRA_PALETTE)]}
                k += 2

    def add_files_dialog(self):
        start = str(self.files.folder or "")
        paths, _ = QFileDialog.getOpenFileNames(self, "Добавить измерения", start,
                                                "Осциллограммы 2C53T (*.bin);;Все файлы (*)")
        if paths:
            self.open_paths(paths, add=True)

    def remove_items(self, rows):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(self.items):
                del self.items[r]
        self.active = min(self.active, max(0, len(self.items) - 1))
        self.workspace.set_items(self.items, self.active)
        self.refresh()

    def set_active(self, idx):
        if idx != self.active and 0 <= idx < len(self.items):
            self.active = idx
            self.refresh(keep_view=True, panels_only=True)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths, add=bool(self.items))

    # ------------------------------------------------------------ refresh
    def refresh(self, keep_view=True, panels_only=False):
        vs = self.params.view_state()
        if not panels_only:
            ts = build_traces(self.items, vs["xmode"], vs["ymode"]) if self.items else None
            self.ts = ts
            self.plot.set_traces(ts, keep_view=keep_view)
            self.params.view_note.setText("\n".join(ts.notes) if ts else "")
        m = self.m
        self.params.show_info(m)
        self.params.show_scales(m)
        self.bmp.set_measurement(m)
        self.update_measurements()
        self.update_cursor_readout()
        if m is None:
            self.st_decode.setText("Нет данных")
            self.st_samples.setText("")
            self.st_warn.setText("")
            self.st_warn.setToolTip("")
        else:
            bi = m.bmp_info or {}
            bmp = " · BMP ✓" if bi.get("matches_bin") else (" · BMP ✗" if bi.get("path") else "")
            self.st_decode.setText(f"{m.name}: декодировано ({m.decoder_version}){bmp}")
            self.st_samples.setText(f"{m.n_samples} отсч. × {len(m.enabled_channels)} кан.")
            warns = m.reliability_warnings()
            self.st_warn.setText(f"⚠ {len(warns)} предупр." if warns else "шкалы известны")
            self.st_warn.setToolTip("\n".join(warns))
        if self.fft_win and self.fft_win.isVisible():
            self.fft_win.refresh_channels()
            self.fft_win.compute()

    def update_measurements(self):
        m = self.m
        if m is None:
            self.params.show_measurements({})
            self.last_measurements = {}
            return
        self.last_measurements = measure_all(m, self.edge)
        self.params.show_measurements(self.last_measurements)

    def update_cursor_readout(self):
        self.params.show_cursor_readout(self.plot.cursor_readout())

    # ------------------------------------------------------------ edits
    def on_scale_edit(self, target, field, value):
        m = self.m
        if m is None:
            return
        if target == "time":
            m.time_per_div.set(value, SRC_USER, "введено пользователем")
        else:
            ch = m.channel(target)
            getattr(ch, field).set(value, SRC_USER, "введено пользователем")
        self.refresh(keep_view=False)

    def apply_bmp(self):
        m = self.m
        if m is None:
            return
        if not (m.bmp_info or {}).get("path"):
            QMessageBox.information(self, "BMP", "Для этого измерения нет снимка экрана.")
            return
        got = bmp_screen.apply_bmp_scales(m, overwrite=True)
        self.statusBar().showMessage("Из BMP применено: " + (", ".join(got) or "ничего (не распознано)"), 8000)
        self.refresh(keep_view=False)

    def clear_scales(self):
        m = self.m
        if m is None:
            return
        for p in [m.time_per_div] + [x for ch in m.channels for x in (ch.volts_per_div, ch.zero_code)]:
            p.clear()
        self.refresh(keep_view=False)

    def on_view_options(self, d):
        pl = self.plot
        pl.line_width = d["width"]
        pl.show_points = d["points"]
        pl.show_lines = d["lines"]
        pl.split = d["split"]
        pl.grid = d["grid"]
        pl.dark = d["dark"]
        pl._apply_bg()
        self.refresh(keep_view=True)

    def on_cursor_options(self, d):
        self.plot.snap = d["snap"]
        self.plot.hcursor_plot = d["hplot"] or 0
        self.plot.set_cursor_modes(d["vertical"], d["horizontal"])
        if d["snap"]:
            self.plot.set_snap(True)
        self.update_cursor_readout()

    def reset_cursors(self):
        self.params.set_cursor_state(dict(vertical=False, horizontal=False))
        self.plot.vcursors_on = self.plot.hcursors_on = False
        self.plot.reset_cursors()
        self.update_cursor_readout()

    def on_measure_options(self, d):
        self.edge.level_mode = d["level_mode"]
        self.edge.level_div = d["level_div"]
        self.edge.hysteresis_frac = d["hyst"] / 100.0
        self.update_measurements()

    def manual_range(self):
        v = self.plot.get_view()
        if not v or not getattr(self, "ts", None):
            return
        dlg = RangeDialog(self, v, self.ts.xunit, self.ts.yunit)
        if dlg.exec():
            self.plot.set_view(dlg.values())

    def toggle_maximize(self, on):
        self.left_panel.setVisible(not on)
        self.params.setVisible(not on)

    def copy_point(self):
        p = self.plot.last_point
        if not p:
            self.statusBar().showMessage("Наведите мышь на график.", 4000)
            return
        txt = (f"{p['trace']}\tотсчёт {p['index']}\tX={p['x']!r} {p['xunit']}\tY={p['y']!r} {p['yunit']}"
               f"\tкод {p['raw']}")
        QGuiApplication.clipboard().setText(txt)
        self.statusBar().showMessage("Скопировано: " + txt.replace("\t", "  "), 5000)

    # ------------------------------------------------------------ analysis
    def cursor_index_range(self):
        r = self.plot.cursor_readout()
        rows = r.get("rows") or []
        if len(rows) < 2 or rows[0].get("index") is None:
            return None
        return rows[0]["index"], rows[1]["index"]

    def show_fft(self):
        if self.m is None:
            QMessageBox.information(self, "FFT", "Сначала откройте измерение.")
            return
        if self.fft_win is None:
            self.fft_win = FftWindow(self, lambda: self.m, self.cursor_index_range)
        self.fft_win.refresh_channels()
        self.fft_win.show()
        self.fft_win.raise_()
        self.fft_win.compute()

    # ------------------------------------------------------------ export
    def _cursor_labels(self) -> dict:
        r = self.plot.cursor_readout()
        out = {}
        xu, yu = r.get("xunit", ""), r.get("yunit", "")
        if r.get("dx") is not None:
            out["Δt" if xu == "s" else "ΔX"] = fmt_value(r["dx"], xu)
            if r.get("inv_dx"):
                out["1/|Δt|" if xu == "s" else "1/|ΔX|"] = (fmt_value(r["inv_dx"], "Hz") if xu == "s"
                                                           else f"{r['inv_dx']:.5g}")
        if r.get("dy") is not None:
            out["ΔV" if yu == "V" else "ΔY"] = fmt_value(r["dy"], yu)
        return out

    def _cursor_state(self):
        pl = self.plot
        return image_export.CursorState(
            a=pl.cur["A"] if pl.vcursors_on else None, b=pl.cur["B"] if pl.vcursors_on else None,
            y1=pl.cur["Y1"] if pl.hcursors_on else None, y2=pl.cur["Y2"] if pl.hcursors_on else None,
            labels=self._cursor_labels())

    def _render_report(self, path: Path, items=None):
        vs = self.params.view_state()
        items = items if items is not None else self.items
        ts = build_traces(items, vs["xmode"], vs["ymode"])
        style = image_export.PlotStyle(line_width=vs["width"], show_points=vs["points"],
                                       show_lines=vs["lines"], grid=vs["grid"])
        same = items is self.items
        warns = []
        for it in items:
            warns += [f"{it.m.name}: {w}" for w in it.m.reliability_warnings() if w not in ts.notes]
        title = ", ".join(it.m.name for it in items if it.shown)
        image_export.render(ts, path, title=title, view=self.plot.get_view() if same else None,
                            cursors=self._cursor_state() if same else None, style=style, footer=warns[:5])

    def export_dialog(self):
        if not self.items:
            QMessageBox.information(self, "Экспорт", "Нет открытых измерений.")
            return
        default_dir = str(Path.home() / "Documents")
        dlg = ExportDialog(self, len(self.items), default_dir)
        if not dlg.exec():
            return
        o = dlg.options()
        if not o["formats"]:
            return
        out = o["dir"]
        if self._is_on_removable(out):
            if QMessageBox.question(self, "Экспорт", "Папка экспорта находится на съёмном диске (возможно, "
                                    "на осциллографе). Исходные файлы не изменятся, но запись на прибор "
                                    "не рекомендуется. Продолжить?") != QMessageBox.Yes:
                return
        try:
            out.mkdir(parents=True, exist_ok=True)
            written = []
            if o["scope"] == "joint":
                ms = [it.m for it in self.items]
                written += data_export.write_csv_combined(ms, out / "combined.csv", o["sep"], o["decimal"])
                for fmt in o["formats"]:
                    if fmt in image_export.IMAGE_FORMATS:
                        written.append(self._save_image(out / f"combined.{fmt}", fmt, o["image_view"], self.items))
            else:
                targets = [self.items[self.active]] if o["scope"] == "active" else self.items
                for it in targets:
                    m = it.m
                    stem = out / m.path.stem
                    meas = measure_all(m, self.edge)
                    for fmt in o["formats"]:
                        if fmt == "csv":
                            written += data_export.write_csv(m, stem.with_suffix(".csv"), o["sep"], o["decimal"],
                                                             json_sidecar=o["sidecar"])
                        elif fmt == "xlsx":
                            written += data_export.write_xlsx(m, stem.with_suffix(".xlsx"), meas)
                        elif fmt == "json":
                            written += data_export.write_json(m, stem.with_suffix(".json"), meas)
                        else:
                            only = [it] if (o["scope"] == "all" or len(self.items) > 1 and o["scope"] == "active"
                                            and False) else None
                            written.append(self._save_image(stem.with_suffix("." + fmt), fmt, o["image_view"],
                                                            only if o["scope"] == "all" else None))
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", f"Ошибка записи: {e.strerror or e}")
            return
        except Exception as e:
            QMessageBox.warning(self, "Экспорт", f"Ошибка экспорта: {e}")
            return
        self.statusBar().showMessage(f"Экспортировано файлов: {len(written)} в {out}", 10000)
        QMessageBox.information(self, "Экспорт", f"Сохранено {len(written)} файл(ов):\n"
                                + "\n".join(str(p) for p in written[:15]) + ("\n…" if len(written) > 15 else ""))

    def _save_image(self, path: Path, fmt: str, view_kind: str, items=None) -> Path:
        if view_kind == "screen" and items is None:
            self.plot.render_to(str(path), fmt)
        else:
            self._render_report(path, items)
        return path

    @staticmethod
    def _is_on_removable(p: Path) -> bool:
        from ..io.drives import list_drives
        roots = [d.root.upper() for d in list_drives()]
        return any(str(p).upper().startswith(r) for r in roots)

    def save_view(self):
        if not self.items:
            return
        base = str(Path(settings().value("export/dir", str(Path.home() / "Documents"))) / (self.m.path.stem + ".png"))
        path, flt = QFileDialog.getSaveFileName(self, "Сохранить вид графика", base,
                                                "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not path:
            return
        fmt = Path(path).suffix.lower().lstrip(".") or "png"
        if fmt not in image_export.IMAGE_FORMATS:
            fmt = "png"
            path += ".png"
        try:
            self._render_report(Path(path))
        except Exception as e:
            QMessageBox.warning(self, "Сохранение", f"Не удалось сохранить: {e}")
            return
        self.statusBar().showMessage(f"Сохранено: {path}", 6000)

    def batch_export(self):
        paths = self.files.selected_bins() or self.files.all_bins()
        if not paths:
            QMessageBox.information(self, "Пакетный экспорт", "Выберите папку с BIN-файлами в левой панели.")
            return
        dlg = ExportDialog(self, 1, str(Path.home() / "Documents"))
        dlg.setWindowTitle(f"Пакетный экспорт: {len(paths)} файл(ов)")
        dlg.scope_active.setText(f"Файлы, выбранные в списке (или все BIN папки): {len(paths)}")
        dlg.img_view.setCurrentIndex(0)
        dlg.img_view.setEnabled(False)
        if not dlg.exec():
            return
        o = dlg.options()
        vs = self.params.view_state()
        opt = batch.BatchOptions(tuple(o["formats"]), o["sep"], o["decimal"], o["sidecar"], vs["xmode"], vs["ymode"],
                                 self.files.model())
        prog = QProgressDialog("Экспорт…", "Отмена", 0, len(paths), self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(300)

        def cb(i, n, name):
            prog.setValue(i)
            prog.setLabelText(f"{name} ({i + 1}/{n})")
            QApplication.processEvents()
            return not prog.wasCanceled()

        rep = batch.export_many(paths, o["dir"], opt, cb)
        prog.setValue(len(paths))
        ok = sum(1 for r in rep if r[1] == "OK")
        bad = [f"{n}: {s}" for n, s, _ in rep if s != "OK"]
        QMessageBox.information(self, "Пакетный экспорт",
                                f"Готово: {ok} из {len(paths)} в {o['dir']}" + ("\n\nОшибки:\n" + "\n".join(bad[:20]) if bad else ""))

    # ------------------------------------------------------------ session
    def save_session(self):
        if not self.items:
            QMessageBox.information(self, "Сессия", "Нет открытых измерений.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить сессию", str(Path.home() / "Documents" / "session.f2c53t.json"),
                                              "Сессия FNIRSI (*.f2c53t.json *.json)")
        if not path:
            return
        meas = {it.m.name: {k: v.as_dict() for k, v in measure_all(it.m, self.edge).items()} for it in self.items}
        save_session(path, self.items, {"range": self.plot.get_view(), **self.params.view_state()},
                     {**self.params.cursor_state(), "positions": dict(self.plot.cur)},
                     {"measure": self.params.measure_state()}, meas, self.active)
        self.statusBar().showMessage(f"Сессия сохранена: {path}", 6000)

    def open_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть сессию", str(Path.home() / "Documents"),
                                              "Сессия FNIRSI (*.f2c53t.json *.json)")
        if not path:
            return
        try:
            items, data, problems = load_session(path, settings().value("auto_bmp", True, type=bool))
        except Exception as e:
            QMessageBox.warning(self, "Сессия", f"Не удалось открыть сессию: {e}")
            return
        if problems:
            QMessageBox.warning(self, "Сессия", "Часть файлов недоступна:\n" + "\n".join(problems))
        self.items = items
        self.active = min(int(data.get("active", 0)), max(0, len(items) - 1))
        view = data.get("view", {})
        self.params.blockSignals(True)
        self.params.set_view_state(view)
        self.params.blockSignals(False)
        self.on_view_options(self.params.view_state())
        self.workspace.set_items(self.items, self.active)
        self.refresh(keep_view=False)
        if view.get("range"):
            self.plot.set_view(view["range"])
        cur = data.get("cursors", {})
        self.plot.cur.update({k: v for k, v in (cur.get("positions") or {}).items()})
        self.params.set_cursor_state(cur)
        self.on_cursor_options(self.params.cursor_state())
        self.statusBar().showMessage(f"Сессия открыта: {path}", 6000)

    # ------------------------------------------------------------ misc
    def settings_dialog(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.files.removable_only = settings().value("removable_only", True, type=bool)
            self.files.update_drives(initial=True)

    def show_keys(self):
        QMessageBox.information(self, "Горячие клавиши", (
            "Ctrl+O — открыть диск/папку\nF5 — обновить\nCtrl+Shift+O — добавить измерение\n"
            "Ctrl+E — экспорт\nCtrl+Shift+E — пакетный экспорт\nCtrl+S — сохранить вид графика\n"
            "F — спектр (FFT)\nF11 — развернуть график\nCtrl+0 — сброс масштаба\n"
            "V — курсоры A/B\nH — курсоры Y1/Y2\nS — привязка к отсчётам\nEsc — сбросить курсоры\n"
            "Ctrl+Shift+C — копировать координаты точки под мышью\n\n"
            "Мышь: колесо — масштаб, левая кнопка — сдвиг, правая — масштаб по осям."))

    def about(self):
        QMessageBox.about(self, "О программе", (
            f"<b>{APP_NAME}</b> {__version__}<br>Декодирование, просмотр и экспорт осциллограмм "
            "FNIRSI 2C53T (BIN + BMP).<br><br>Формат BIN: 2×301 экранный отсчёт (uint8), байт флагов каналов, "
            "поле длины. Шкалы (В/дел, время/дел, ноль) в BIN не хранятся — берутся с BMP-снимка или "
            "вводятся вручную, источник каждого значения показывается.<br><br>"
            "Исходные файлы открываются только для чтения."))

    def closeEvent(self, e):
        settings().setValue("geometry", self.saveGeometry())
        super().closeEvent(e)
