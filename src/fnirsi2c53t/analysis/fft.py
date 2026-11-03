"""Spectrum (FFT) of a waveform segment."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps

WINDOWS = {
    "rect": "Прямоугольное",
    "hann": "Ханна",
    "hamming": "Хэмминга",
    "blackman": "Блэкмана",
    "flattop": "Flat-top (точная амплитуда)",
}


@dataclass
class Spectrum:
    freq: np.ndarray            # Hz, or cycles/sample when dt is None
    amp: np.ndarray             # single-sided amplitude (peak), in input units
    freq_unit: str              # "Hz" or "цикл/отсч."
    amp_unit: str
    n_samples: int              # real samples used
    nfft: int
    window: str
    dc_removed: bool
    resolution: float           # real resolution = 1/(N*dt), not affected by zero padding
    peaks: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"freq": self.freq.tolist(), "amp": self.amp.tolist(), "freq_unit": self.freq_unit,
                "amp_unit": self.amp_unit, "n_samples": self.n_samples, "nfft": self.nfft,
                "window": self.window, "dc_removed": self.dc_removed, "resolution": self.resolution,
                "peaks": self.peaks, "notes": self.notes}


def compute_spectrum(y: np.ndarray, dt: float | None, window: str = "hann", remove_dc: bool = True,
                     nfft: int | None = None, amp_unit: str = "", n_peaks: int = 5) -> Spectrum:
    y = np.asarray(y, dtype=np.float64)
    n = y.size
    notes = []
    if n < 8:
        raise ValueError("Недостаточно данных для FFT: нужно хотя бы 8 отсчётов.")
    if remove_dc:
        y = y - y.mean()
    w = np.ones(n) if window == "rect" else sps.get_window(window, n, fftbins=True)
    nfft = int(nfft or n)
    if nfft < n:
        nfft = n
    if nfft > n:
        notes.append(f"Дополнение нулями до {nfft} точек лишь интерполирует спектр; "
                     f"реальное разрешение определяется {n} отсчётами.")
    X = np.fft.rfft(y * w, nfft)
    amp = np.abs(X) * 2.0 / w.sum()       # coherent-gain corrected peak amplitude
    amp[0] /= 2.0
    if nfft % 2 == 0:
        amp[-1] /= 2.0
    if dt:
        freq = np.fft.rfftfreq(nfft, d=dt)
        funit = "Hz"
        res = 1.0 / (n * dt)
    else:
        freq = np.fft.rfftfreq(nfft, d=1.0)
        funit = "цикл/отсч."
        res = 1.0 / n
        notes.append("Временная шкала неизвестна: частота в циклах на отсчёт (0…0.5).")
    sp = Spectrum(freq, amp, funit, amp_unit, n, nfft, window, remove_dc, res, notes=notes)
    start = 1 if remove_dc else 0
    if amp.size > start + 2:
        pk, props = sps.find_peaks(amp[start:], height=amp[start:].max() * 0.02)
        pk = pk + start
        order = pk[np.argsort(amp[pk])[::-1]][:n_peaks]
        sp.peaks = [{"freq": float(freq[i]), "amp": float(amp[i]), "bin": int(i)} for i in order]
    return sp
