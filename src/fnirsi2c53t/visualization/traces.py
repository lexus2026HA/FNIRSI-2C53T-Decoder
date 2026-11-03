"""Turns measurements into plottable traces (shared by the GUI and exporters)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..decoders.model import Measurement

DEFAULT_COLORS = {"CH1": "#d9b300", "CH2": "#2f7bff"}
EXTRA_PALETTE = ["#e4572e", "#29a35a", "#a347d1", "#e08b00", "#17becf", "#d62790", "#8c564b", "#7f7f7f"]

X_LABELS = {"time": ("Время", "s"), "index": ("Номер отсчёта", "")}
Y_LABELS = {"volts": ("Напряжение", "V"), "div": ("Деления от центра экрана", "дел"),
            "raw": ("Код отсчёта", "код")}
X_MODE_NAMES = {"time": "Время", "index": "Номер отсчёта"}
Y_MODE_NAMES = {"volts": "Напряжение", "div": "Деления (отн.)", "raw": "Исходный код"}


@dataclass
class DisplayItem:
    """A measurement in the workspace plus how it is drawn."""
    m: Measurement
    visible: dict = field(default_factory=lambda: {"CH1": True, "CH2": True})
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))
    x_shift_samples: float = 0.0     # explicit, user-set alignment (display only)
    y_shift_div: float = 0.0
    shown: bool = True

    @property
    def label(self) -> str:
        return self.m.path.stem


@dataclass
class Trace:
    item: DisplayItem
    channel: str
    x: np.ndarray
    y: np.ndarray
    raw: np.ndarray
    color: str
    label: str


@dataclass
class TraceSet:
    traces: list[Trace]
    xmode: str
    ymode: str
    xlabel: str
    ylabel: str
    xunit: str
    yunit: str
    notes: list[str]


def effective_modes(items: list[DisplayItem], xmode: str, ymode: str) -> tuple[str, str, list[str]]:
    notes = []
    shown = [it for it in items if it.shown]
    chans = [(it, ch) for it in shown for ch in it.m.enabled_channels if it.visible.get(ch.name, True)]
    if xmode == "time" and any(not it.m.has_time for it in shown):
        xmode = "index"
        notes.append("Время/дел неизвестно — ось X показана в номерах отсчётов.")
    if ymode == "volts" and any(not ch.has_volts for _, ch in chans):
        ymode = "div"
        notes.append("Шкала напряжения неизвестна — ось Y в делениях от центра экрана.")
    return xmode, ymode, notes


def build_traces(items: list[DisplayItem], xmode: str = "time", ymode: str = "volts",
                 multi: bool | None = None) -> TraceSet:
    xmode, ymode, notes = effective_modes(items, xmode, ymode)
    shown = [it for it in items if it.shown]
    multi = len(shown) > 1 if multi is None else multi
    traces = []
    for it in shown:
        m = it.m
        for ch in m.enabled_channels:
            if not it.visible.get(ch.name, True):
                continue
            if xmode == "time":
                dt = m.sample_interval()
                x = m.time_axis() + it.x_shift_samples * dt
            else:
                x = m.index_axis().astype(np.float64) + it.x_shift_samples
            if ymode == "volts":
                y = ch.volts() + it.y_shift_div * float(ch.volts_per_div.value)
            elif ymode == "div":
                y = ch.divisions() + it.y_shift_div
            else:
                y = ch.raw.astype(np.float64) + it.y_shift_div * ch.prof.codes_per_div
            label = f"{it.label} {ch.name}" if multi else ch.name
            traces.append(Trace(it, ch.name, x, y, ch.raw, it.colors.get(ch.name, "#888888"), label))
        if it.x_shift_samples or it.y_shift_div:
            notes.append(f"{it.label}: смещение для отображения X={it.x_shift_samples:g} отсч., "
                         f"Y={it.y_shift_div:g} дел (данные в экспорте без смещения).")
    xl, xu = X_LABELS[xmode]
    yl, yu = Y_LABELS[ymode]
    return TraceSet(traces, xmode, ymode, xl, yl, xu, yu, notes)
