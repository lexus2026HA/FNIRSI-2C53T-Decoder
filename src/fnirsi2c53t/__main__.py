"""Entry point: GUI, or `--selftest [report.txt]` for checking a build without a display."""
from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def selftest(out: str | None) -> int:
    """Decode bundled samples, analyse BMP, export to a temp folder. Exit code 0 = OK."""
    import tempfile
    import traceback
    lines, ok = [], True
    try:
        from fnirsi2c53t.analysis.measurements import measure_all
        from fnirsi2c53t.decoders.screen_digitizer import open_capture as decode_file
        from fnirsi2c53t.exporters import batch
        samples = sorted((_base_dir() / "samples").rglob("*.bin")) + sorted(
            (_base_dir() / "samples" / "1013d").glob("*.wav"))[:3] + sorted(
            (_base_dir() / "samples" / "2c23t").glob("*.bmp"))
        if not samples:
            raise RuntimeError("samples/*.bin not found next to the program")
        tmp = Path(tempfile.mkdtemp(prefix="f2c53t_selftest_"))
        for p in samples:
            m = decode_file(p)
            meas = measure_all(m)
            f = {k: (v.get("freq").value if v.get("freq") else None) for k, v in meas.items()}
            match = m.bmp_info.get("matches_bin")
            lines.append(f"{p.parent.name}/{p.name} [{m.prof.model}]: ch={[c.name for c in m.enabled_channels]} tb={m.time_per_div.value} "
                         f"bmp_match={match} freq={f}")
            ok &= bool(match) or (m.prof.bmp_only and not m.enabled_channels) or (
                m.prof.data_ext == ".wav" and p.name != "1.wav")
        rep = batch.export_many(samples[:2], tmp, batch.BatchOptions(("csv", "xlsx", "json", "png", "svg", "pdf")))
        for name, status, files in rep:
            lines.append(f"export {name}: {status} ({len(files)} files)")
            ok &= status == "OK"
        from PySide6.QtWidgets import QApplication  # GUI libs importable
        import pyqtgraph  # noqa: F401
        lines.append(f"Qt OK, export dir {tmp}")
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("SELFTEST " + ("PASSED" if ok else "FAILED"))
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        return selftest(args[1] if len(args) > 1 else None)
    from PySide6.QtWidgets import QApplication
    from fnirsi2c53t import APP_NAME
    from fnirsi2c53t.gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    files = [a for a in args if a.lower().endswith((".bin", ".bmp"))]
    if files:
        w.open_paths(files, add=len(files) > 1)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
