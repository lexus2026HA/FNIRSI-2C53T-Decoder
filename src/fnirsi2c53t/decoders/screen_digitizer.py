"""Waveform from a screenshot, for models that save no waveform data (2C23T).

One value per screen column: the centre of the trace pixels in that column.
Accuracy is +-1 pixel (1 code); steep edges become the middle of the
vertical stroke.  Columns where the trace is hidden (measurement text) are
filled by linear interpolation and reported.  Everything is marked as
"digitised from the screenshot" so it is never mistaken for scope data.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from . import bmp_screen as bs
from .fnirsi_2c53t import DecodeError, decode_file, find_bin_for
from .model import Channel, Measurement
from .profiles import P2C23T, Profile, profile_by_key

DIGITIZER_VERSION = "screen-digitizer/1.0"
MIN_COVERAGE = 0.6          # share of columns with trace pixels for a channel to count as shown


def digitize_screen(path: str | os.PathLike, profile: Profile | None = None,
                    apply_scales: bool = True) -> Measurement:
    p = Path(path)
    try:
        screen = bs.load_screen(p, prefer=profile or P2C23T)
    except bs.BmpError as e:
        raise DecodeError(str(e))
    pr = screen.profile
    n = pr.n_samples
    top = pr.y_of_code0 - pr.code_max
    bottom = pr.y_of_code0 - pr.code_min
    warnings = [f"Данные оцифрованы со снимка экрана ({pr.model} не сохраняет отсчёты): точность ±1 пиксель "
                f"(±{1 / pr.codes_per_div:.2f} дел), крутые фронты усреднены по вертикали."]
    channels = []
    for name in ("CH1", "CH2"):
        col = pr.trace_colors.get(name)
        raw = np.full(n, np.nan)
        if col is not None:
            for i in range(n):
                x = pr.x0 + i
                if x >= pr.screen_w:
                    break
                rows = np.flatnonzero(screen.codes[top:bottom + 1, x] == col) + top
                if pr.overlay_rows:
                    rows = rows[(rows < pr.overlay_rows[0]) | (rows > pr.overlay_rows[1])]
                if rows.size:
                    raw[i] = pr.y_of_code0 - (rows.min() + rows.max()) / 2.0
        found = ~np.isnan(raw)
        enabled = found.mean() >= MIN_COVERAGE
        if enabled and not found.all():
            idx = np.arange(n)
            raw = np.interp(idx, idx[found], raw[found])
            warnings.append(f"{name}: {int((~found).sum())} столбцов без луча (скрыт надписями) "
                            "заполнены линейной интерполяцией.")
        if not enabled:
            raw = np.where(found, raw, pr.code_center)
        channels.append(Channel(name, bool(enabled), raw.astype(np.float64), profile=pr))
    if not any(c.enabled for c in channels):
        warnings.append("На снимке не найден луч ни одного канала.")
    st = None
    try:
        st = os.stat(p)
    except OSError:
        pass
    m = Measurement(path=p, format_name=pr.format_name, decoder_version=DIGITIZER_VERSION, n_samples=n,
                    channels=channels, file_size=st.st_size if st else 0, file_mtime=st.st_mtime if st else 0.0,
                    header={"model": pr.model, "source": "screenshot", "ch1_enabled": channels[0].enabled,
                            "ch2_enabled": channels[1].enabled, "flags_byte": int(channels[0].enabled)
                            | (int(channels[1].enabled) << 1)},
                    warnings=warnings, profile=pr, bmp_path=p)
    info = bs.analyse_screen(screen, None)
    info["matches_bin"] = True            # the data *is* the screenshot
    info["digitized"] = True
    m.bmp_info = info
    if apply_scales:
        bs.apply_bmp_scales(m)
    return m


def open_capture(path: str | os.PathLike, model: str = "auto", apply_bmp_scales: bool = True) -> Measurement:
    """Open a BIN or a screenshot, honouring the model chosen by the user."""
    p = Path(path)
    forced = None if model in ("auto", "", None) else profile_by_key(model)
    if forced is not None and not forced.supported:
        raise DecodeError(f"Формат FNIRSI {forced.model} ещё не исследован — нужны файлы с прибора.")
    ext = p.suffix.lower()
    if ext == ".bmp":
        if forced is None or not forced.bmp_only:
            b = find_bin_for(p)
            if b is not None:
                m = open_capture(b, model, apply_bmp_scales)
                if m.prof.data_ext == ".wav":
                    m.warnings.append("Открыт WAV с тем же номером, что и снимок. У 1013D снимки и данные "
                                      "нумеруются независимо — убедитесь, что это одна запись.")
                return m
        if forced is not None and forced.data_ext == ".wav":
            raise DecodeError("У 1013D данные хранятся в .wav; снимок .bmp без пары не оцифровывается.")
        if forced is not None and not forced.bmp_only:
            # 2C53T/2C53P screenshot without BIN: digitise with that geometry
            return digitize_screen(p, forced, apply_bmp_scales)
        return digitize_screen(p, forced or None, apply_bmp_scales)
    if ext in (".bin", ".wav"):
        if forced is not None and forced.bmp_only:
            raise DecodeError(f"{forced.model} не сохраняет файлы данных; выбрана не та модель.")
        m = decode_file(p, apply_bmp_scales=apply_bmp_scales)
        if forced is not None and m.prof is not forced:
            raise DecodeError(f"Файл от {m.prof.model} ({m.file_size} байт), а выбрана модель {forced.model}.")
        return m
    raise DecodeError("Поддерживаются файлы .bin, .wav (1013D) и .bmp.")
