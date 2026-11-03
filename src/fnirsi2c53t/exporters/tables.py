"""Column tables and metadata shared by all exporters."""
from __future__ import annotations

import datetime as _dt
from collections import OrderedDict

import numpy as np

from .. import __version__
from ..analysis.measurements import ChannelMeasurements, measure_all
from ..decoders.model import Measurement, SOURCE_LABELS


def waveform_columns(m: Measurement, include_disabled: bool = False) -> "OrderedDict[str, np.ndarray]":
    """Only columns that are actually known; nothing is invented."""
    cols: OrderedDict[str, np.ndarray] = OrderedDict()
    t = m.time_axis()
    if t is not None:
        cols["time_s"] = t
    cols["sample_index"] = m.index_axis()
    for ch in m.channels:
        if not (ch.enabled or include_disabled):
            continue
        k = ch.name.lower()
        cols[f"{k}_raw"] = ch.raw.astype(np.int64)
        cols[f"{k}_div"] = ch.divisions()
        v = ch.volts()
        if v is not None:
            cols[f"{k}_V"] = v
    return cols


COLUMN_DOC = {
    "time_s": "время от первого отсчёта, с (шаг = время/дел ÷ отсчётов на деление: 2C53T 25, 2C53P и 1013D 50)",
    "sample_index": "номер отсчёта от 0",
    "raw": "исходное значение из файла (у 2C53T/2C53P — строка экрана, у 1013D — отсчёт буфера, у 2C23T — "
           "оцифрованная строка снимка)",
    "div": "деления от центра экрана = (raw − центр) / кодов на деление (2C53T 128/25, 2C53P 120/32, 1013D 200/50)",
    "V": "напряжение на входе щупа, В = (raw − ноль) / кодов на деление × В/дел",
}


def param_row(name: str, p) -> dict:
    return {"parameter": name, "value": p.value, "unit": p.unit, "source": p.source,
            "source_text": SOURCE_LABELS.get(p.source, p.source), "note": p.note}


def metadata(m: Measurement, meas: dict[str, ChannelMeasurements] | None = None) -> dict:
    meas = meas if meas is not None else measure_all(m)
    return {
        "schema": "fnirsi2c53t-measurement/1",
        "app": {"name": "FNIRSI-2C53T-Decoder", "version": __version__},
        "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": {"path": str(m.path), "name": m.path.name, "size_bytes": m.file_size,
                   "modified": _dt.datetime.fromtimestamp(m.file_mtime).isoformat(timespec="seconds")
                   if m.file_mtime else None},
        "decoder": {"format": m.format_name, "version": m.decoder_version, "header": m.header},
        "n_samples": m.n_samples,
        "timebase": m.time_per_div.to_dict(),
        "sample_interval_s": m.sample_interval(),
        "channels": [{
            "name": ch.name, "enabled": ch.enabled,
            "volts_per_div": ch.volts_per_div.to_dict(), "zero_code": ch.zero_code.to_dict(),
            "probe": ch.probe.to_dict(), "coupling": ch.coupling.to_dict(),
            "volts_calibrated": ch.has_volts,
        } for ch in m.channels],
        "measurements": {k: v.as_dict() for k, v in meas.items()},
        "bmp": _bmp_summary(m),
        "warnings": m.reliability_warnings(),
        "columns": COLUMN_DOC,
    }


def _bmp_summary(m: Measurement) -> dict | None:
    i = m.bmp_info or {}
    if not i:
        return None
    out = {"path": i.get("path"), "ok": i.get("ok"), "error": i.get("error"),
           "matches_bin": i.get("matches_bin"), "trace_match": i.get("trace_match"),
           "ocr": i.get("ocr"), "markers": i.get("markers")}
    return out


def metadata_rows(m: Measurement) -> list[tuple[str, object, str, str]]:
    """Flat (name, value, unit, source) rows for spreadsheets."""
    rows = [
        ("Исходный файл", str(m.path), "", ""),
        ("Размер файла", m.file_size, "байт", ""),
        ("Формат", m.format_name, "", ""),
        ("Версия декодера", m.decoder_version, "", ""),
        ("Модель", m.prof.model, "", ""),
        ("Байт флагов каналов", f"0x{m.header.get('flags_byte', 0):02X}", "", "из файла данных"),
        ("Отсчётов на канал", m.n_samples, "", "из файла данных"),
        ("Время/дел", m.time_per_div.value, "s/div", SOURCE_LABELS[m.time_per_div.source]),
        ("Шаг отсчётов", m.sample_interval(), "s", f"время/дел ÷ {m.prof.samples_per_div:g}" if m.has_time else "неизвестно"),
    ]
    for ch in m.channels:
        rows += [
            (f"{ch.name} включён", "да" if ch.enabled else "нет", "", "из файла данных"),
            (f"{ch.name} В/дел", ch.volts_per_div.value, "V/div", SOURCE_LABELS[ch.volts_per_div.source]),
            (f"{ch.name} ноль (код)", ch.zero_code.value, "code", SOURCE_LABELS[ch.zero_code.source]),
            (f"{ch.name} щуп", ch.probe.value, "x", SOURCE_LABELS[ch.probe.source]),
            (f"{ch.name} вход", ch.coupling.value, "", SOURCE_LABELS[ch.coupling.source]),
        ]
    bi = m.bmp_info or {}
    rows.append(("Снимок BMP", bi.get("path") or bi.get("error") or "нет", "", ""))
    if bi.get("trace_match"):
        for k, v in bi["trace_match"].items():
            rows.append((f"Сверка с BMP {k}", f"{v['hits']}/{v['considered']}", "отсч.", ""))
    return rows
