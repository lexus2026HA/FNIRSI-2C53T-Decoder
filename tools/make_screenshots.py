"""Render the screenshots used in README and in the article.

Usage:  python tools/make_screenshots.py <demo_folder> <out_folder>

<demo_folder> must contain 2C53P/, 2C23T/, 1013D/ with the scope files.
Keep it in a neutral location (e.g. C:\\FNIRSI_demo) so no personal path appears on the pictures.
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QCoreApplication, QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DEMO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
from fnirsi2c53t.gui.dialogs import ExportDialog, settings  # noqa: E402
from fnirsi2c53t.gui.main_window import MainWindow  # noqa: E402

settings().setValue("model", "auto")
settings().setValue("last_folder", "")
errs = []
w = MainWindow()
w.resize(1600, 900)
w.show()


def pump(n=3):
    for _ in range(n):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def shot(name, widget=None):
    pump()
    (widget or w).grab().save(str(OUT / f"{name}.png"))
    print("saved", name)


def show_folder(folder: Path):
    fp = w.files
    fp.fs_model.setRootPath(str(DEMO))
    fp.tree.setRootIndex(fp.fs_model.index(str(DEMO)))
    fp.set_folder(folder)
    pump(5)
    for _ in range(30):            # let the background status decoding finish
        fp._decode_step()
    pump()


def fresh(paths, add=False):
    w.items = []
    w.workspace.set_items([], 0)
    w.reset_cursors()
    w.open_paths([str(p) for p in paths], add=add)
    pump()


def cursors(a, b, y1=None, y2=None):
    w.params.set_cursor_state(dict(vertical=True, horizontal=y1 is not None))
    w.on_cursor_options(w.params.cursor_state())
    w.plot.set_cursor("A", a)
    w.plot.set_cursor("B", b)
    if y1 is not None:
        w.plot.set_cursor("Y1", y1)
        w.plot.set_cursor("Y2", y2)
    w.update_cursor_readout()
    pump()


def view(**kw):
    vs = w.params.view_state()
    vs.update(kw)
    w.params.set_view_state(vs)
    w.on_view_options(w.params.view_state())
    pump()


def step():
    try:
        p53 = DEMO / "2C53P" / "Screenshot simple file"
        d13 = DEMO / "1013D"
        t23 = DEMO / "2C23T"

        # 1. overview: 1013D, both channels, cursors on one period
        show_folder(d13)
        fresh([d13 / "1.wav"])
        view(xmode="time", ymode="volts", split=False)
        cursors(0.00387, 0.00487, -1.3, 1.9)
        w.params.tabs.setCurrentIndex(4)
        shot("01_overview_1013d")

        # 2. 2C53P sine, cursors on neighbouring peaks
        show_folder(p53)
        fresh([p53 / "2.bin"])
        m = w.m
        raw = m.channel("CH1").raw.astype(float)
        dt = m.sample_interval()
        i0 = int(raw[:60].argmax())
        i1 = i0 + 50 + int(raw[i0 + 40:i0 + 60].argmax()) - 10
        cursors(i0 * dt, i1 * dt, -1.6, 1.75)
        w.params.tabs.setCurrentIndex(3)
        shot("02_cursors_2c53p")

        # 3. measurements of the same file
        w.params.tabs.setCurrentIndex(4)
        shot("03_measurements_2c53p")

        # 4. screenshot check for 2C53P
        w.center.setCurrentIndex(1)
        w.params.tabs.setCurrentIndex(0)
        shot("04_bmp_check_2c53p")
        w.center.setCurrentIndex(0)

        # 5. scales and their source
        w.params.tabs.setCurrentIndex(1)
        shot("05_scales_sources")

        # 6. 2C23T: curve digitised from the picture
        show_folder(t23)
        fresh([t23 / "img_03.bmp"])
        w.center.setCurrentIndex(1)
        w.params.tabs.setCurrentIndex(4)
        shot("06_2c23t_digitized")
        w.center.setCurrentIndex(0)
        shot("07_2c23t_plot")

        # 8. two different scopes on one plot: 1013D and 2C53P, both 1 kHz square
        fresh([d13 / "1.wav", p53 / "3.bin"], add=True)
        w.items[0].visible["CH2"] = False
        w.workspace.set_items(w.items, 0)
        w.refresh(keep_view=False)
        w.plot.set_view((0, 0.009, -2.2, 2.4))
        w.params.tabs.setCurrentIndex(4)
        shot("08_compare_two_scopes")

        # 9. split channels
        fresh([d13 / "1.wav"])
        view(split=True)
        cursors(0.00387, 0.00487)
        shot("09_split_channels")
        view(split=False)

        # 10. FFT
        fresh([d13 / "1.wav"])
        w.show_fft()
        w.fft_win.resize(1100, 640)
        w.fft_win.win.setCurrentIndex(w.fft_win.win.findData("flattop"))
        w.fft_win.compute()
        shot("10_fft_1013d", w.fft_win)
        w.fft_win.close()

        # 11. unknown scales: 2C53P without its screenshot information
        fresh([p53 / "2.bin"])
        w.clear_scales()
        w.params.tabs.setCurrentIndex(0)
        shot("11_unknown_scales")

        # 12. export dialog
        fresh([d13 / "1.wav"])
        dlg = ExportDialog(w, len(w.items), "C:\\FNIRSI_export")
        dlg.dir.setText("C:\\FNIRSI_export")
        for k, cb in dlg.fmt.items():
            cb.setChecked(k in ("csv", "xlsx", "png"))
        dlg.show()
        pump(5)
        shot("12_export_dialog", dlg)
        dlg.close()
    except Exception:
        errs.append(traceback.format_exc())
    QTimer.singleShot(300, app.quit)


QTimer.singleShot(600, step)
app.exec()
settings().setValue("model", "auto")
print("ERRORS:", errs if errs else "none")
