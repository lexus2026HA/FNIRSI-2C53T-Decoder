"""Decoder for FNIRSI 2C53T and 2C53P ``.bin`` waveform files.

2C53T (607 bytes, verified on 9 sample captures):

    0x000  301  CH1 screen samples, uint8
    0x12D  301  CH2 screen samples, uint8
    0x25A  1    channel-enabled flags: bit0 = CH1, bit1 = CH2
    0x25B  4    uint32 big-endian, always 301

2C53P (927 bytes, verified on 3 captures from a real device):

    0x000  461  CH1 screen samples, uint8
    0x1CD  1    CH1 maximum of the samples
    0x1CE  1    CH1 minimum
    0x1CF  461  CH2 screen samples
    0x39C  1    CH2 maximum
    0x39D  1    CH2 minimum
    0x39E  1    channel-enabled flags: bit0 = CH1, bit1 = CH2

Each sample is the vertical pixel position of the trace on the screen
(see profiles.py for the geometry of each model).  Volts/div, timebase,
channel offset, probe and coupling are NOT stored; they come from the BMP
screenshot or from the user.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np

from .model import Channel, Measurement
from .profiles import P1013D, P2C53P, P2C53T, PROFILES, Profile, profile_for_size

DECODER_VERSION = "fnirsi-bin/1.1"

# 2C53T constants kept for compatibility (tests, docs)
N_SAMPLES = P2C53T.n_samples
FILE_SIZE = P2C53T.file_size
CODE_MIN = P2C53T.code_min
CODE_MAX = P2C53T.code_max
CODE_CENTER = P2C53T.code_center
CODES_PER_DIV = P2C53T.codes_per_div
SAMPLES_PER_DIV = P2C53T.samples_per_div
DIVS_X = P2C53T.divs_x
DIVS_Y = P2C53T.divs_y
SCREEN_X0 = P2C53T.x0
SCREEN_Y_OF_CODE0 = P2C53T.y_of_code0
FORMAT_NAME = P2C53T.format_name


class DecodeError(Exception):
    """File is not a readable waveform. Message is user-facing (Russian)."""


def read_file_readonly(path: str | os.PathLike) -> bytes:
    """Read a file without ever opening it for writing."""
    p = Path(path)
    try:
        with open(p, "rb") as f:       # read-only
            return f.read()
    except FileNotFoundError:
        raise DecodeError("Файл не найден (диск отключён или файл удалён).")
    except PermissionError:
        raise DecodeError("Нет доступа к файлу.")
    except OSError as e:
        raise DecodeError(f"Ошибка чтения: {e.strerror or e}")


def _choose_profile(size: int) -> tuple[Profile, list[str]]:
    if size == 0:
        raise DecodeError("Пустой файл (0 байт).")
    p = profile_for_size(size)
    if p is not None:
        return p, []
    if size < P2C53T.file_size:
        sizes = ", ".join(f"{q.file_size} ({q.model})" for q in PROFILES)
        raise DecodeError(f"Файл слишком короткий: {size} байт, ожидается {sizes}. "
                          "Это не осциллограмма FNIRSI или файл повреждён.")
    # unknown size: only accept the 2C53T layout when its length field confirms it
    return P2C53T, [f"Размер файла {size} байт больше ожидаемого ({P2C53T.file_size}); "
                    f"лишние {size - P2C53T.file_size} байт не разобраны."]


def decode_bytes(data: bytes, path: str | os.PathLike = "<memory>") -> Measurement:
    path = Path(path)
    if path.suffix.lower() == ".wav" or (len(data) == P1013D.file_size and path.suffix.lower() != ".bin"):
        from .fnirsi_1013d import decode_1013d
        return decode_1013d(data, path, P1013D, DecodeError)
    prof, warnings = _choose_profile(len(data))
    n = prof.n_samples
    if prof.count_field:
        off, expected = prof.count_field
        count = struct.unpack(">I", data[off:off + 4])[0]
        if count != expected:
            raise DecodeError(f"Неподдерживаемый вариант формата: поле длины = {count}, ожидается {expected}.")
    flags = data[prof.off_flags]
    if flags & ~0x03:
        warnings.append(f"Неизвестные биты в байте флагов каналов: 0x{flags:02X}.")
    ch1_on, ch2_on = bool(flags & 0x01), bool(flags & 0x02)
    if not (ch1_on or ch2_on):
        warnings.append("Оба канала помечены как выключенные.")

    raw1 = np.frombuffer(data, dtype=np.uint8, count=n, offset=prof.off_ch1).copy()
    raw2 = np.frombuffer(data, dtype=np.uint8, count=n, offset=prof.off_ch2).copy()
    channels = [Channel("CH1", ch1_on, raw1, profile=prof), Channel("CH2", ch2_on, raw2, profile=prof)]

    header = {"model": prof.model, "flags_byte": flags, "ch1_enabled": ch1_on, "ch2_enabled": ch2_on,
              "trailer_hex": data[prof.off_flags:prof.file_size].hex()}
    if prof.count_field:
        header["count_field"] = struct.unpack(">I", data[prof.count_field[0]:prof.count_field[0] + 4])[0]
    for k, off in prof.extra.items():
        header[k] = data[off]

    for ch in channels:
        if not ch.enabled:
            continue
        k = ch.name.lower()
        if f"{k}_max" in header:
            smax, smin = header[f"{k}_max"], header[f"{k}_min"]
            if (smax, smin) != (int(ch.raw.max()), int(ch.raw.min())):
                warnings.append(f"{ch.name}: записанные в файле макс/мин ({smax}/{smin}) не совпадают с "
                                f"отсчётами ({int(ch.raw.max())}/{int(ch.raw.min())}) — файл мог быть повреждён.")
        out = int(np.count_nonzero((ch.raw < prof.code_min) | (ch.raw > prof.code_max)))
        if out:
            warnings.append(f"{ch.name}: {out} отсчётов вне диапазона экрана {prof.code_min}..{prof.code_max} — "
                            "неожиданно для этого формата.")
        lo = int(np.count_nonzero(ch.raw <= prof.code_min))
        hi = int(np.count_nonzero(ch.raw >= prof.code_max))
        if lo or hi:
            warnings.append(f"{ch.name}: сигнал упирается в край экрана ({hi} отсч. сверху, {lo} снизу) — "
                            "размах, среднее и RMS занижены/искажены.")

    st = None
    try:
        st = os.stat(path)
    except OSError:
        pass
    return Measurement(
        path=path,
        format_name=prof.format_name,
        decoder_version=DECODER_VERSION,
        n_samples=n,
        channels=channels,
        file_size=len(data),
        file_mtime=st.st_mtime if st else 0.0,
        header=header,
        warnings=warnings,
        profile=prof,
    )


def decode_file(path: str | os.PathLike, with_bmp: bool = True, apply_bmp_scales: bool = True) -> Measurement:
    """Decode a BIN file; optionally look for and analyse the matching BMP."""
    data = read_file_readonly(path)
    m = decode_bytes(data, path)
    if with_bmp:
        from .bmp_screen import attach_bmp
        attach_bmp(m, apply_scales=apply_bmp_scales)
    return m


def _same_stem(folder: Path, stem: str, exts) -> Path | None:
    for ext in exts:
        c = folder / (stem + ext)
        try:
            if c.is_file():
                return c
        except OSError:
            return None
    return None


def _sibling_dirs(folder: Path) -> list[Path]:
    """Neighbouring folders of a scope drive ('Screenshot file', 'Screenshot simple file')."""
    try:
        return sorted((d for d in folder.parent.iterdir()
                       if d.is_dir() and d != folder and "screenshot" in d.name.lower()),
                      key=lambda d: d.name.lower())
    except OSError:
        return []


def find_bmp_for(path: str | os.PathLike) -> Path | None:
    """Matching screenshot: same stem in the same folder, otherwise in a
    neighbouring 'Screenshot …' folder (2C53P keeps BIN and BMP apart)."""
    p = Path(path)
    exts = (".bmp", ".BMP", ".Bmp")
    hit = _same_stem(p.parent, p.stem, exts)
    if hit:
        return hit
    for d in _sibling_dirs(p.parent):
        hit = _same_stem(d, p.stem, exts)
        if hit:
            return hit
    return None


def find_bin_for(path: str | os.PathLike) -> Path | None:
    """Matching BIN for a screenshot (same folder or neighbouring 'Screenshot …' folder)."""
    p = Path(path)
    exts = (".bin", ".BIN", ".Bin", ".wav", ".WAV")
    hit = _same_stem(p.parent, p.stem, exts)
    if hit:
        return hit
    for d in _sibling_dirs(p.parent):
        hit = _same_stem(d, p.stem, exts)
        if hit:
            return hit
    return None


__all__ = [
    "DecodeError", "decode_bytes", "decode_file", "find_bmp_for", "find_bin_for", "read_file_readonly",
    "N_SAMPLES", "FILE_SIZE", "CODE_MIN", "CODE_MAX", "CODE_CENTER", "CODES_PER_DIV",
    "SAMPLES_PER_DIV", "DIVS_X", "DIVS_Y", "SCREEN_X0", "SCREEN_Y_OF_CODE0",
    "DECODER_VERSION", "FORMAT_NAME", "P2C53T", "P2C53P",
]
