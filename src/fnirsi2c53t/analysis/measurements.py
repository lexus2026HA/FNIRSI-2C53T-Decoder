"""Automatic waveform measurements.

All computations run on the raw screen codes (always available) and are
then converted to volts / seconds only when the scale is known.  Results
that cannot be determined are returned as ``None`` with a reason - no
number is produced from insufficient data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..decoders.model import Channel, Measurement

NOT_ENOUGH = "Недостаточно данных"
CANNOT = "Не удалось определить"


@dataclass
class EdgeSettings:
    level_mode: str = "mid"        # "mid" = (min+max)/2, "mean", "manual"
    level_div: float = 0.0         # used when level_mode == "manual" (divisions from screen centre)
    hysteresis_frac: float = 0.10  # of peak-to-peak
    min_hysteresis_codes: float = 2.0


@dataclass
class Result:
    key: str
    label: str
    value: float | None
    unit: str
    method: str = ""
    reason: str = ""             # why value is None

    def text(self, fmt=None) -> str:
        if self.value is None:
            return self.reason or CANNOT
        return (fmt or format_si)(self.value, self.unit)


@dataclass
class ChannelMeasurements:
    channel: str
    unit: str                        # "V" or "код" (raw)
    results: list[Result] = field(default_factory=list)
    edges_rising: list[float] = field(default_factory=list)   # fractional sample positions
    level_code: float | None = None
    hysteresis_codes: float | None = None

    def get(self, key: str) -> Result | None:
        for r in self.results:
            if r.key == key:
                return r
        return None

    def as_dict(self) -> dict:
        return {r.key: {"label": r.label, "value": r.value, "unit": r.unit, "method": r.method,
                        "reason": r.reason} for r in self.results}


_PREFIXES = [(1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")]


def format_si(v: float | None, unit: str, digits: int = 4) -> str:
    if v is None:
        return "—"
    if unit in ("", "%", "код", "отсч.", "дел", "цикл/отсч.", "1/отсч."):
        return f"{v:.{digits}g} {unit}".strip()
    if v == 0 or not np.isfinite(v):
        return f"{v:g} {unit}"
    a = abs(v)
    for f, p in _PREFIXES:
        if a >= f * 0.9999:
            return f"{v / f:.{digits}g} {p}{unit}"
    return f"{v:.{digits}g} {unit}"


def find_edges(raw: np.ndarray, level: float, hyst: float) -> tuple[list[float], list[float]]:
    """Rising/falling crossings of ``level`` with hysteresis (Schmitt trigger).

    Returns fractional sample positions where the signal crosses ``level``,
    found by linear interpolation inside the transition that crossed both
    thresholds.
    """
    x = raw.astype(np.float64)
    hi, lo = level + hyst / 2.0, level - hyst / 2.0
    state = None
    rising, falling = [], []
    last_cross = None
    for i in range(len(x)):
        v = x[i]
        if i > 0 and (x[i - 1] - level) * (v - level) <= 0 and x[i - 1] != v:
            last_cross = i - 1 + (level - x[i - 1]) / (v - x[i - 1])
        elif i > 0 and x[i - 1] == level == v and last_cross is None:
            last_cross = float(i)
        if state is None:
            state = "hi" if v >= hi else "lo" if v <= lo else None
            continue
        if state == "lo" and v >= hi:
            rising.append(last_cross if last_cross is not None else float(i))
            state = "hi"
            last_cross = None
        elif state == "hi" and v <= lo:
            falling.append(last_cross if last_cross is not None else float(i))
            state = "lo"
            last_cross = None
    return rising, falling


def channel_measurements(m: Measurement, ch: Channel, es: EdgeSettings | None = None) -> ChannelMeasurements:
    es = es or EdgeSettings()
    raw = ch.raw.astype(np.float64)
    vpc = ch.volts_per_code() if ch.has_volts else None
    unit = "V" if vpc else "код"
    dt = m.sample_interval()
    out = ChannelMeasurements(ch.name, unit)
    R = out.results

    def lvl(code):           # absolute level -> output unit
        return ch.code_to_volts(code) if vpc else code

    def delta(codes):        # difference -> output unit
        return codes * vpc if vpc else codes

    n = raw.size
    pr = ch.prof
    clipped = bool(np.any(raw <= pr.code_min) or np.any(raw >= pr.code_max))
    clip_note = " (сигнал обрезан краем экрана — значение недостоверно)" if clipped else ""
    cmin, cmax = raw.min(), raw.max()
    mean = raw.mean()
    R.append(Result("min", "Минимум", lvl(cmin), unit, "минимальный отсчёт" + clip_note))
    R.append(Result("max", "Максимум", lvl(cmax), unit, "максимальный отсчёт" + clip_note))
    R.append(Result("pp", "Размах (pk-pk)", delta(cmax - cmin), unit, "max − min" + clip_note))
    R.append(Result("mean", "Среднее", lvl(mean), unit, "среднее по всем отсчётам" + clip_note))
    if vpc:
        v = ch.volts()
        R.append(Result("rms", "RMS", float(np.sqrt(np.mean(v ** 2))), unit,
                        "√(mean(v²)), включая постоянную составляющую" + clip_note))
    else:
        R.append(Result("rms", "RMS", None, "V", reason="нужна шкала В/дел и ноль",
                        method="RMS относительно 0 В требует калибровки"))
    R.append(Result("ac_rms", "RMS переменной сост.", delta(float(np.std(raw))), unit,
                    "√(mean((v−mean)²))" + clip_note))
    R.append(Result("amp_pos", "Амплитуда +", delta(cmax - mean), unit, "max − среднее"))
    R.append(Result("amp_neg", "Амплитуда −", delta(mean - cmin), unit, "среднее − min"))
    R.append(Result("div_pp", "Размах, делений", (cmax - cmin) / pr.codes_per_div, "дел",
                    "по экранной сетке, не зависит от калибровки"))

    if dt:
        R.append(Result("fs", "Шаг отсчётов", dt, "s",
                        f"время/дел ÷ {pr.samples_per_div:g}; это экранные отсчёты, не частота АЦП"))
        R.append(Result("fs_hz", "Частота экранных отсчётов", 1.0 / dt, "Hz",
                        "1/шаг; реальная частота дискретизации АЦП прибора выше и в файле не хранится"))
    else:
        R.append(Result("fs", "Шаг отсчётов", None, "s", reason="временная шкала неизвестна"))

    # --- edges / period -------------------------------------------------
    pp = cmax - cmin
    hyst = max(es.hysteresis_frac * pp, es.min_hysteresis_codes)
    if es.level_mode == "manual":
        level = pr.code_center + float(es.level_div) * pr.codes_per_div
    elif es.level_mode == "mean":
        level = float(mean)
    else:
        level = (cmax + cmin) / 2.0
    out.level_code, out.hysteresis_codes = level, hyst
    method = (f"пересечения уровня {format_si(lvl(level), unit)} вверх, гистерезис "
              f"{format_si(delta(hyst), unit)}")
    tunit = "s" if dt else "отсч."
    funit = "Hz" if dt else "1/отсч."
    if pp < 2 * es.min_hysteresis_codes + 1:
        reason = f"{CANNOT}: размах {pp:.0f} кодов — сигнал не превышает шум"
        for k, lab, u in (("period", "Период", tunit), ("freq", "Частота", funit), ("duty", "Скважность (D+)", "%")):
            R.append(Result(k, lab, None, u, method, reason))
        return out
    rising, falling = find_edges(raw, level, hyst)
    out.edges_rising = rising
    if len(rising) >= 2:
        periods = np.diff(rising)
        per = float(np.mean(periods))
        jitter = float(np.std(periods)) if len(periods) > 1 else 0.0
        scale = dt if dt else 1.0
        note = f"; {len(periods)} периодов, разброс ±{jitter:.2f} отсч."
        R.append(Result("period", "Период", per * scale, tunit, method + note))
        R.append(Result("freq", "Частота", 1.0 / (per * scale), funit, "1/период по фронтам" + note))
        # duty over whole periods, first rising .. last rising
        a, b = rising[0], rising[-1]
        hi_time = 0.0
        f_iter = [f for f in falling if a < f < b]
        r_iter = [r for r in rising if a <= r <= b]
        for r in r_iter[:-1]:
            nxt_f = [f for f in f_iter if f > r]
            nxt_r = [x for x in r_iter if x > r]
            if nxt_f and nxt_r and nxt_f[0] < nxt_r[0]:
                hi_time += nxt_f[0] - r
            else:
                hi_time = None
                break
        if hi_time is not None and b > a:
            R.append(Result("duty", "Скважность (D+)", 100.0 * hi_time / (b - a), "%",
                            "доля времени выше уровня на целых периодах"))
        else:
            R.append(Result("duty", "Скважность (D+)", None, "%", reason=CANNOT))
    else:
        reason = (f"{NOT_ENOUGH}: найдено {len(rising)} фронт(ов) вверх, нужно ≥2 "
                  "(в окне меньше одного периода?)")
        R.append(Result("period", "Период", None, tunit, method, reason))
        R.append(Result("freq", "Частота", None, funit, method, reason))
        R.append(Result("duty", "Скважность (D+)", None, "%", method, reason))
    return out


def measure_all(m: Measurement, es: EdgeSettings | None = None) -> dict[str, ChannelMeasurements]:
    return {ch.name: channel_measurements(m, ch, es) for ch in m.enabled_channels}
