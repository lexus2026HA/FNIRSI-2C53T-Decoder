"""FNIRSI 1013D ``.wav`` waveform files (original FNIRSI firmware).

The file is not a RIFF/WAVE sound file.  15000 bytes:

    0..999        header (settings, measurements)
    1000..3999    CH1 buffer, 1500 x uint16 LE   (50 units per division)
    4000..6999    CH2 buffer, 1500 x uint16 LE
    7000..8499    CH1 screen points, 750 x uint16 = screen row (449 - buffer value)
    8500..9999    CH2 screen points
    10000..14999  zeros

Header bytes (channel 2 = channel 1 offset + 10):
    2 / 12   channel shown (0/1)                    - derived from 21 user files
    4 / 14   volts/div index: 5, 2.5, 1, 0.5, 0.2, 0.1, 0.05 V (x probe)
    8 / 18   coupling 0 DC, 1 AC
    10 / 20  probe 10**n (x1, x10, x100)
    22       timebase index 0..29: 50 s ... 10 ns (1-2-5)
    26 / 28 / 30  trigger mode / edge / channel
    84 / 86  uint16 LE: buffer value of 0 V (trace position) for CH1 / CH2

Format credits: Robert Tidey (github.com/roberttidey/FNISR1013DScope) and
W. Voigt (github.com/wavoigt/FNIRSI-1013D-WAV-Viewer-in-Excel-VBA); verified
here against 21 files and screenshots from a real 1013D.
Firmware variants by Peco (V0.0005) and Atlan (V0.26d) use other layouts and
are rejected rather than mis-read.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .model import Channel, Measurement, SRC_FILE

FILE_SIZE = 15000
N_BUF = 1500
N_SCREEN = 750
VDIV = [5.0, 2.5, 1.0, 0.5, 0.2, 0.1, 0.05]
TIMEBASE = [50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 5e-3, 2e-3, 1e-3, 5e-4, 2e-4, 1e-4,
            5e-5, 2e-5, 1e-5, 5e-6, 2e-6, 1e-6, 5e-7, 2e-7, 1e-7, 5e-8, 2e-8, 1e-8]
SCREEN_ROW_OF_ZERO = 449      # screen point = 449 - buffer value
TRIGGER_MODES = ["Auto", "Single", "Normal"]
TRIGGER_EDGES = ["rising", "falling"]
NOTE = "из заголовка WAV"


def screen_window(buf: np.ndarray, screen: np.ndarray) -> int | None:
    """Offset of the 750 displayed points inside the 1500-point buffer (exact match), or None."""
    target = SCREEN_ROW_OF_ZERO - screen.astype(np.int64)
    b = buf.astype(np.int64)
    for off in range(0, N_BUF - N_SCREEN + 1):
        if b[off] == target[0] and np.array_equal(b[off:off + N_SCREEN], target):
            return off
    return None


def decode_1013d(data: bytes, path: Path, prof, decode_error) -> Measurement:
    if len(data) != FILE_SIZE:
        raise decode_error(f"Файл 1013D должен иметь размер {FILE_SIZE} байт, а не {len(data)}.")

    def idx(off, n, what):
        v = data[off]
        if v >= n:
            raise decode_error(f"Неизвестное значение {what} ({v}) в заголовке 1013D — возможно, другая прошивка "
                               "(Peco V0.0005, Atlan V0.26d) или повреждённый файл.")
        return v

    tb = TIMEBASE[idx(22, len(TIMEBASE), "развёртки")]
    warnings: list[str] = []
    header = {"model": "1013D", "firmware": "оригинальная FNIRSI",
              "trigger_mode": TRIGGER_MODES[data[26]] if data[26] < 3 else data[26],
              "trigger_edge": TRIGGER_EDGES[data[28]] if data[28] < 2 else data[28],
              "trigger_channel": f"CH{data[30] + 1}" if data[30] < 2 else data[30],
              "timebase_index": data[22]}
    channels = []
    for c, name in enumerate(("CH1", "CH2")):
        base = c * 10
        vi = idx(4 + base, len(VDIV), f"В/дел {name}")
        ci = idx(8 + base, 2, f"входа {name}")
        pi = idx(10 + base, 3, f"щупа {name}")
        probe = 10 ** pi
        enabled = bool(data[2 + base])
        buf = np.frombuffer(data, dtype="<u2", count=N_BUF, offset=1000 + c * 3000).copy()
        screen = np.frombuffer(data, dtype="<u2", count=N_SCREEN, offset=7000 + c * 1500).copy()
        zero = data[84 + 2 * c] | (data[85 + 2 * c] << 8)
        ch = Channel(name, enabled, buf, profile=prof)
        ch.volts_per_div.set(VDIV[vi] * probe, SRC_FILE, NOTE + " (с учётом щупа)")
        ch.zero_code.set(float(zero), SRC_FILE, NOTE + " (положение луча)")
        ch.probe.set(probe, SRC_FILE, NOTE)
        ch.coupling.set(("DC", "AC")[ci], SRC_FILE, NOTE)
        channels.append(ch)
        k = name.lower()
        header[f"{k}_enabled"] = enabled
        header[f"{k}_zero"] = zero
        off = screen_window(buf, screen) if enabled else None
        header[f"{k}_screen_offset"] = off
        if enabled:
            if off is None:
                warnings.append(f"{name}: экранные точки не являются прямым окном буфера (растяжка, прокрутка "
                                "или остановленный кадр) — какой участок был на экране, неизвестно. "
                                "Данные буфера от этого не зависят.")
            hi = int(np.count_nonzero(buf >= 399))
            lo = int(np.count_nonzero(buf == 0))
            if hi or lo:
                warnings.append(f"{name}: сигнал упирается в границу диапазона АЦП ({hi} сверху, {lo} снизу) — "
                                "размах и среднее искажены.")
    header["flags_byte"] = int(channels[0].enabled) | (int(channels[1].enabled) << 1)
    if not any(c.enabled for c in channels):
        warnings.append("Оба канала помечены как выключенные.")
    st = None
    try:
        st = os.stat(path)
    except OSError:
        pass
    m = Measurement(path=Path(path), format_name=prof.format_name, decoder_version="fnirsi-1013d-wav/1.0",
                    n_samples=N_BUF, channels=channels, file_size=len(data),
                    file_mtime=st.st_mtime if st else 0.0, header=header, warnings=warnings, profile=prof)
    m.time_per_div.set(tb, SRC_FILE, NOTE)
    return m
