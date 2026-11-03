"""CSV, XLSX and JSON export."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import numpy as np

from ..analysis.measurements import ChannelMeasurements, measure_all
from ..decoders.model import Measurement
from .tables import COLUMN_DOC, metadata, metadata_rows, waveform_columns


# ------------------------------------------------------------------ CSV
def _fmt(v, decimal: str) -> str:
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    s = repr(float(v))          # shortest exact round-trip representation
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(".", decimal) if decimal != "." else s


def write_csv(m: Measurement, path: str | Path, sep: str = ",", decimal: str = ".",
              include_disabled: bool = False, json_sidecar: bool = True) -> list[Path]:
    """Machine-readable CSV: one header row, decimal point by default.

    ``decimal=','`` (with ``sep=';'``) produces the localised variant that
    Russian Excel opens directly.
    """
    if decimal == sep:
        raise ValueError("Разделитель полей и десятичный разделитель совпадают.")
    cols = waveform_columns(m, include_disabled)
    return _write_columns(cols, path, sep, decimal,
                          sidecar=metadata(m) if json_sidecar else None)


def _write_columns(cols, path, sep, decimal, sidecar=None) -> list[Path]:
    path = Path(path)
    names = list(cols)
    n = max(len(v) for v in cols.values())
    lines = [sep.join(names)]
    for i in range(n):
        row = []
        for k in names:
            arr = cols[k]
            row.append(_fmt(arr[i], decimal) if i < len(arr) else "")
        lines.append(sep.join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    out = [path]
    if sidecar is not None:
        sp = path.with_suffix(".meta.json")
        sp.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        out.append(sp)
    return out


def write_csv_combined(ms: list[Measurement], path: str | Path, sep: str = ",", decimal: str = ".") -> list[Path]:
    """Several measurements side by side, columns prefixed with the file name."""
    cols = {}
    for m in ms:
        for k, v in waveform_columns(m).items():
            cols[f"{m.path.stem}:{k}"] = v
    side = {"schema": "fnirsi2c53t-combined/1", "files": [metadata(m) for m in ms]}
    return _write_columns(cols, path, sep, decimal, sidecar=side)


# ----------------------------------------------------------------- JSON
def _json_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


def measurement_json(m: Measurement, meas=None) -> dict:
    d = metadata(m, meas)
    t = m.time_axis()
    d["data"] = {
        "time_s": t.tolist() if t is not None else None,
        "sample_index": m.index_axis().tolist(),
        "channels": {ch.name: {
            "enabled": ch.enabled,
            "raw": ch.raw.astype(int).tolist(),
            "div": ch.divisions().tolist(),
            "volts": ch.volts().tolist() if ch.has_volts else None,
        } for ch in m.channels},
    }
    d["fft"] = m.fft_result
    return d


def write_json(m: Measurement, path: str | Path, meas=None) -> list[Path]:
    path = Path(path)
    path.write_text(json.dumps(measurement_json(m, meas), ensure_ascii=False, indent=1,
                               default=_json_default), encoding="utf-8")
    return [path]


# ----------------------------------------------------------------- XLSX
def write_xlsx(m: Measurement, path: str | Path, meas: dict[str, ChannelMeasurements] | None = None,
               fft: dict | None = None) -> list[Path]:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    meas = meas if meas is not None else measure_all(m)
    fft = fft if fft is not None else m.fft_result
    wb = Workbook()
    bold = Font(bold=True)

    ws = wb.active
    ws.title = "Waveform"
    cols = waveform_columns(m)
    names = list(cols)
    ws.append(names)
    for c in ws[1]:
        c.font = bold
    for i in range(m.n_samples):
        ws.append([int(cols[k][i]) if cols[k].dtype.kind in "iu" else float(cols[k][i]) for k in names])
    ws.freeze_panes = "A2"
    for j in range(1, len(names) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 14

    ws = wb.create_sheet("Measurements")
    ws.append(["Канал", "Параметр", "Значение", "Ед.", "Метод", "Примечание"])
    for c in ws[1]:
        c.font = bold
    for name, cm in meas.items():
        for r in cm.results:
            ws.append([name, r.label, r.value, r.unit, r.method, r.reason])
    for col, w in zip("ABCDEF", (8, 28, 16, 10, 60, 50)):
        ws.column_dimensions[col].width = w

    ws = wb.create_sheet("Metadata")
    ws.append(["Параметр", "Значение", "Ед.", "Источник"])
    for c in ws[1]:
        c.font = bold
    ws.append(["Дата экспорта", _dt.datetime.now().isoformat(timespec="seconds"), "", ""])
    for row in metadata_rows(m):
        ws.append(list(row))
    ws.append([])
    ws.append(["Предупреждения"])
    ws.cell(ws.max_row, 1).font = bold
    for w in m.reliability_warnings() or ["нет"]:
        ws.append([w])
    ws.append([])
    ws.append(["Столбцы листа Waveform"])
    ws.cell(ws.max_row, 1).font = bold
    for k, v in COLUMN_DOC.items():
        ws.append([k, v])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["D"].width = 22

    if fft:
        ws = wb.create_sheet("FFT")
        fu, au = fft.get("freq_unit", ""), fft.get("amp_unit", "")
        ws.append([f"freq_{fu}", f"amplitude_{au}"])
        for c in ws[1]:
            c.font = bold
        for f, a in zip(fft["freq"], fft["amp"]):
            ws.append([float(f), float(a)])
        ws["D1"] = "Канал"; ws["E1"] = fft.get("channel")
        ws["D2"] = "Окно"; ws["E2"] = fft.get("window")
        ws["D3"] = "Отсчётов"; ws["E3"] = fft.get("n_samples")
        ws["D4"] = "NFFT"; ws["E4"] = fft.get("nfft")
        ws["D5"] = "Разрешение"; ws["E5"] = fft.get("resolution")
        ws["D6"] = "Участок"; ws["E6"] = fft.get("segment")
        for i, note in enumerate(fft.get("notes", [])):
            ws.cell(8 + i, 4, note)
    path = Path(path)
    wb.save(path)
    return [path]


def write_spectrum_csv(fft: dict, path: str | Path, sep=",", decimal=".") -> list[Path]:
    cols = {f"freq_{fft['freq_unit']}": np.asarray(fft["freq"]),
            f"amplitude_{fft['amp_unit'] or 'units'}": np.asarray(fft["amp"])}
    return _write_columns(cols, path, sep, decimal)


def write_spectrum_xlsx(fft: dict, path: str | Path) -> list[Path]:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "FFT"
    ws.append([f"freq_{fft['freq_unit']}", f"amplitude_{fft['amp_unit']}"])
    for f, a in zip(fft["freq"], fft["amp"]):
        ws.append([float(f), float(a)])
    ws2 = wb.create_sheet("Info")
    for k in ("source", "channel", "segment", "window", "n_samples", "nfft", "resolution", "dc_removed"):
        ws2.append([k, str(fft.get(k))])
    for p in fft.get("peaks", []):
        ws2.append(["peak", p["freq"], p["amp"]])
    for n in fft.get("notes", []):
        ws2.append(["note", n])
    wb.save(path)
    return [Path(path)]
