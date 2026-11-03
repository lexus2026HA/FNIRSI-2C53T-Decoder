"""Analysis of FNIRSI screenshots (2C53T 320x240, 2C53P 480x272; 16 bit RGB565 BMP).

The screenshot is used only to *check* the decoding and to *suggest* the
scale settings that the BIN file does not contain:

* trace match  - every decoded sample is looked up at its screen pixel
                 (column 9+i, row 248-code); the share of hits proves that
                 BIN and BMP belong together and that the decoding is right;
* zero markers - coloured triangles at the left edge mark 0 V of each
                 channel: zero code = 248 - marker centre row;
* status text  - "H=200uS", "500mV", "X10", "DC" are read with fixed glyph
                 templates learned from real screenshots (glyph_templates.py).
                 A glyph that does not match a template makes the whole
                 field "not recognised" - nothing is guessed.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fnirsi_2c53t import find_bmp_for
from .glyph_templates import TEMPLATES
from .model import Measurement, SRC_BMP, SRC_UNKNOWN
from .profiles import P2C53P, P2C53T, PROFILES, Profile, profile_for_screen

W, H = P2C53T.screen_w, P2C53T.screen_h
TRACE_COLORS = dict(P2C53T.trace_colors)
MIN_TRACE_MATCH = 0.90          # share of samples that must hit the trace

# text fields: (font, mask, rows, x-range)
FIELD_ROWS_TOP = (3, 18)
FIELD_ROWS_BOTTOM = (224, 238)


class BmpError(Exception):
    pass


@dataclass
class Screen:
    path: Path
    codes: np.ndarray       # (H, W) uint16 RGB565, top row first
    profile: Profile = P2C53T

    def rgb(self) -> np.ndarray:
        c = self.codes.astype(np.uint32)
        r = ((c >> 11) & 0x1F) << 3
        g = ((c >> 5) & 0x3F) << 2
        b = (c & 0x1F) << 3
        return np.dstack([r, g, b]).astype(np.uint8)


def load_screen(path: str | Path, prefer: Profile | None = None) -> Screen:
    p = Path(path)
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError as e:
        raise BmpError(f"Не удалось прочитать BMP: {e.strerror or e}")
    if len(data) < 54 or data[:2] != b"BM":
        raise BmpError("Не BMP-файл.")
    off, = struct.unpack_from("<I", data, 10)
    hdr, w, h, planes, bpp, comp = struct.unpack_from("<IiiHHI", data, 14)
    prof = profile_for_screen(w, abs(h), prefer)
    if prof is None or bpp != 16:
        known = ", ".join(f"{q.screen_w}x{q.screen_h} ({q.model})" for q in PROFILES)
        raise BmpError(f"Неожиданный формат BMP: {w}x{abs(h)}, {bpp} бит (ожидается {known}, 16 бит).")
    if comp not in (0, 3):
        raise BmpError(f"Сжатие BMP {comp} не поддерживается.")
    ww, hh = prof.screen_w, prof.screen_h
    need = off + ww * hh * 2
    if len(data) < need:
        raise BmpError("BMP обрезан.")
    px = np.frombuffer(data, dtype="<u2", count=ww * hh, offset=off).reshape(hh, ww)
    if h > 0:                     # bottom-up storage
        px = px[::-1]
    return Screen(p, px.copy(), prof)


# ----------------------------------------------------------------- masks
def _rgb5(c: np.ndarray):
    c = c.astype(np.int32)
    return (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F


def mask_yellow(c):
    r, g, b = _rgb5(c)
    return (r >= 10) & (g >= 20) & (b <= 8)


def mask_blue(c):
    r, g, b = _rgb5(c)
    return (r <= 3) & (b >= 20)


def mask_light(c):
    r, g, b = _rgb5(c)
    return (r >= 9) & (b >= 16)


# ------------------------------------------------------------ glyph OCR
def segment(mask: np.ndarray, space_gap: int = 3) -> list[tuple[int, int] | None]:
    """Split a text mask into glyph column ranges; ``None`` marks a word gap."""
    cols = mask.any(axis=0)
    out: list[tuple[int, int] | None] = []
    x, n = 0, len(cols)
    last_end = None
    while x < n:
        if cols[x]:
            s = x
            while x < n and cols[x]:
                x += 1
            if last_end is not None and s - last_end >= space_gap:
                out.append(None)
            out.append((s, x))
            last_end = x
        else:
            x += 1
    return out


def glyph_key(mask: np.ndarray) -> str:
    return "|".join("".join("#" if v else "." for v in row) for row in mask)


def _key_to_array(key: str) -> np.ndarray:
    return np.array([[ch == "#" for ch in row] for row in key.split("|")], dtype=bool)


def _templates(font: str) -> list[tuple[np.ndarray, str]]:
    src = TEMPLATES.get(font, {})
    cache = _TPL_CACHE.get(font)
    if cache is None or cache[0] is not src:
        cache = (src, [(_key_to_array(k), ch) for k, ch in src.items()])
        _TPL_CACHE[font] = cache
    return cache[1]


_TPL_CACHE: dict = {}
TOLERANCE = 0.22      # max share of differing pixels (relative to glyph ink)
MARGIN = 0.08         # a different character must score at least this much worse


def _window_cost(mask: np.ndarray, p: int, t: np.ndarray) -> float:
    """Normalised pixel difference of template t at column p, best of +-1 row shift."""
    h, w = t.shape
    win = mask[:, p:p + w]
    if win.shape[1] != w:
        return 9.0
    best = 9.0
    area = max(int(t.sum()), 1)
    for dy in (0, -1, 1):
        tt = np.roll(t, dy, axis=0)
        if dy == -1 and t[0].any() or dy == 1 and t[-1].any():
            continue
        d = int(np.count_nonzero(win ^ tt)) / area
        best = min(best, d)
    return best


def read_text(mask: np.ndarray, font: str, space_gap: int = 3) -> tuple[str, bool]:
    """Recognise the text in a binary mask by sliding glyph templates.

    Dynamic programming over columns: blank columns may be skipped, every ink
    column must be covered by one template window.  Per window the cost is
    the share of differing pixels (best of +-1 row shift).  A window is
    accepted only below TOLERANCE, and only if no *other* character fits
    almost as well (MARGIN).  Returns (text, recognised).
    """
    tpls = _templates(font)
    h, n = mask.shape
    ink = mask.any(axis=0)
    if not ink.any():
        return "", False
    best: list = [None] * (n + 1)
    best[n] = (0.0, [])
    ambiguous = False
    for p in range(n - 1, -1, -1):
        cands = []
        if not ink[p] and best[p + 1] is not None:
            cands.append(best[p + 1])
        if ink[p] and (p == 0 or True):
            per_char: dict[str, tuple[float, int]] = {}
            for t, ch in tpls:
                if t.shape[0] != h:
                    continue
                w = t.shape[1]
                if p + w > n or best[p + w] is None:
                    continue
                c = _window_cost(mask, p, t)
                if c <= TOLERANCE:
                    tot = c + best[p + w][0]
                    if ch not in per_char or tot < per_char[ch][0]:
                        per_char[ch] = (tot, w)
            for ch, (tot, w) in per_char.items():
                cands.append((tot, [(p, ch, w)] + best[p + w][1]))
        if cands:
            best[p] = min(cands, key=lambda c: c[0])
    if best[0] is None:
        return "?", False
    # ambiguity check on each chosen glyph: another char fitting the same window
    for start, ch, w in best[0][1]:
        own = None
        rivals = []
        for t, c2 in tpls:
            if t.shape[0] != h or abs(t.shape[1] - w) > 1:
                continue
            cost = _window_cost(mask, start, t)
            if c2 == ch:
                own = cost if own is None else min(own, cost)
            else:
                rivals.append(cost)
        if own is not None and rivals and min(rivals) < own + MARGIN:
            ambiguous = True
    out, last_end = [], None
    for start, ch, w in best[0][1]:
        if last_end is not None and start - last_end >= space_gap:
            out.append(" ")
        out.append(ch)
        last_end = start + w
    return "".join(out), not ambiguous


def _field_mask(screen: Screen, rows, xs, maskfn) -> np.ndarray:
    sub = screen.codes[rows[0]:rows[1], xs[0]:xs[1]]
    return maskfn(sub)


def _text_extent(mask: np.ndarray) -> tuple[int, int] | None:
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size == 0:
        return None
    return int(cols[0]), int(cols[-1]) + 1


def read_status_fields(screen: Screen) -> dict:
    """Raw OCR of the scale labels. Values are strings, unparsed."""
    if screen.profile is P2C53P:
        return read_status_fields_p(screen)
    if screen.profile.bmp_only:
        return read_status_fields_23(screen)
    res: dict[str, dict] = {}

    def put(name, mask, font):
        text, ok = read_text(mask, font)
        res[name] = {"text": text.strip(), "ok": ok and bool(text.strip()) and "?" not in text}

    put("timebase", _field_mask(screen, FIELD_ROWS_TOP, (45, 140), mask_light), "top")

    m1 = _field_mask(screen, FIELD_ROWS_BOTTOM, (0, 62), mask_yellow)
    put("ch1_vdiv", m1, "bottom")
    e1 = _text_extent(m1)
    x1 = (e1[1] + 1) if e1 else 30
    put("ch1_probe_coupling", _field_mask(screen, FIELD_ROWS_BOTTOM, (x1, 104), mask_light), "bottom")

    m2 = _field_mask(screen, FIELD_ROWS_BOTTOM, (222, 292), mask_blue)
    put("ch2_vdiv", m2, "bottom")
    e2 = _text_extent(m2)
    x2 = 222 + ((e2[1] + 1) if e2 else 40)
    put("ch2_probe_coupling", _field_mask(screen, FIELD_ROWS_BOTTOM, (x2, 320), mask_light), "bottom")
    return res


def mask_bright(c):
    r, g, b = _rgb5(c)
    return (r * 8 * 0.3 + g * 4 * 0.59 + b * 8 * 0.11) > 80


P_FIELDS = {          # 2C53P status bar: name -> (rows, x-range)
    "ch1": ((3, 27), (36, 125)),
    "ch2": ((3, 27), (150, 236)),
    "timebase": ((3, 17), (252, 285)),
}
P_BAND = 10           # glyph height band above (and including) the baseline row


def p_field_mask(screen: Screen, name: str) -> np.ndarray:
    """Text of one 2C53P field, cut to a fixed band ending at the baseline."""
    rows, xs = P_FIELDS[name]
    m = mask_bright(screen.codes[rows[0]:rows[1], xs[0]:xs[1]])
    ink = np.flatnonzero(m.any(axis=1))
    if ink.size == 0:
        return np.zeros((P_BAND, xs[1] - xs[0]), bool)
    b = int(ink[-1])
    top = max(0, b - P_BAND + 1)
    band = m[top:b + 1]
    if band.shape[0] < P_BAND:
        band = np.vstack([np.zeros((P_BAND - band.shape[0], band.shape[1]), bool), band])
    return band


def read_status_fields_p(screen: Screen) -> dict:
    """2C53P: 'CH1 1V X1 AC', 'CH2 100mV X1 AC', 'H 1mS' (crisp pixel font)."""
    res: dict[str, dict] = {}
    for ch in ("ch1", "ch2"):
        text, ok = read_text(p_field_mask(screen, ch), "p")
        words = text.split()
        ok = ok and "?" not in text and len(words) >= 1
        res[f"{ch}_vdiv"] = {"text": words[0] if words else text, "ok": ok}
        res[f"{ch}_probe_coupling"] = {"text": " ".join(words[1:]), "ok": ok and len(words) > 1}
    text, ok = read_text(p_field_mask(screen, "timebase"), "p")
    res["timebase"] = {"text": text.strip(), "ok": ok and "?" not in text and bool(text.strip())}
    return res


T23_FIELDS = {        # 2C23T: white italic pixel font
    "timebase": ((2, 16), (52, 100)),
    "ch1": ((221, 236), (14, 112)),
    "ch2": ((221, 236), (210, 320)),
}


def t23_field_mask(screen: Screen, name: str) -> np.ndarray:
    rows, xs = T23_FIELDS[name]
    r, g, b = _rgb5(screen.codes[rows[0]:rows[1], xs[0]:xs[1]])
    lum = r * 8 * 0.3 + g * 4 * 0.59 + b * 8 * 0.11
    m = lum > 170
    ink = np.flatnonzero(m.any(axis=1))
    if ink.size == 0:
        return np.zeros((P_BAND + 1, xs[1] - xs[0]), bool)
    bot = int(ink[-1])
    top = max(0, bot - P_BAND)
    band = m[top:bot + 1]
    if band.shape[0] < P_BAND + 1:
        band = np.vstack([np.zeros((P_BAND + 1 - band.shape[0], band.shape[1]), bool), band])
    return band


def read_status_fields_23(screen: Screen) -> dict:
    res: dict[str, dict] = {}
    for ch in ("ch1", "ch2"):
        text, ok = read_text(t23_field_mask(screen, ch), "t23")
        words = text.split()
        ok = ok and "?" not in text and len(words) >= 1
        res[f"{ch}_vdiv"] = {"text": words[0] if words else text, "ok": ok}
        res[f"{ch}_probe_coupling"] = {"text": " ".join(words[1:]), "ok": ok and len(words) > 1}
    text, ok = read_text(t23_field_mask(screen, "timebase"), "t23")
    res["timebase"] = {"text": text.strip(), "ok": ok and "?" not in text and bool(text.strip())}
    return res


# ----------------------------------------------------------- parsing
_SI = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3}


def _is_125(v: float) -> bool:
    if v <= 0:
        return False
    e = np.floor(np.log10(v))
    mant = v / 10 ** e
    return any(abs(mant - k) < 1e-6 for k in (1, 2, 5))


def parse_timebase(text: str) -> float | None:
    m = re.fullmatch(r"(?:H=)?(\d+(?:\.\d+)?)([num]?)[Ss]", text.replace(" ", ""))
    if not m:
        return None
    v = float(f"{float(m.group(1)) * _SI[m.group(2)]:.6g}")
    return v if _is_125(v) else None


def parse_vdiv(text: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([m]?)V", text.replace(" ", ""))
    if not m:
        return None
    v = float(f"{float(m.group(1)) * _SI[m.group(2)]:.6g}")
    return v if _is_125(v) else None


def parse_probe_coupling(text: str) -> tuple[int | None, str | None]:
    t = text.replace(" ", "")
    m = re.fullmatch(r"X(\d+)(AC|DC)?", t)
    if not m:
        return None, None
    return int(m.group(1)), m.group(2)


# ------------------------------------------------------- zero markers
def find_zero_markers(screen: Screen, colors: dict | None = None) -> dict:
    pr = screen.profile
    mrows, mx = pr.marker_rows, pr.marker_x
    out = {}
    cols = dict(colors or pr.trace_colors)
    if pr.marker_colors:
        cols.update(pr.marker_colors)
    for name, col in cols.items():
        if col is None:
            out[name] = {"found": False, "reason": "цвет канала на этой модели ещё не известен"}
            continue
        region = screen.codes[mrows[0]:mrows[1], mx[0]:mx[1]]
        rows = np.flatnonzero((region == col).any(axis=1)) + mrows[0]
        if rows.size == 0:
            out[name] = {"found": False, "reason": "метка не найдена"}
            continue
        # largest contiguous run of rows
        runs, s = [], rows[0]
        for a, b in zip(rows[:-1], rows[1:]):
            if b != a + 1:
                runs.append((s, a))
                s = b
        runs.append((s, rows[-1]))
        s, e = max(runs, key=lambda r: r[1] - r[0])
        height = e - s + 1
        if not pr.marker_height[0] <= height <= pr.marker_height[1]:
            out[name] = {"found": False, "reason": f"метка неожиданной высоты ({height} px)"}
            continue
        centre = (s + e) / 2.0
        code = pr.y_of_code0 - centre
        note = ""
        if s <= mrows[0] + 1 or e >= mrows[1] - 2:
            note = "метка у края экрана — ноль может быть за пределами экрана"
        out[name] = {"found": True, "row": centre, "zero_code": code, "note": note}
    return out


# ----------------------------------------------------------- trace match
OVERLAY_ROWS = P2C53T.overlay_rows   # 2C53T prints "Freq: Duty+: Vp-p:" over the grid here


def _expected_xy(pr: Profile, raw: np.ndarray):
    xs = pr.x0 + np.arange(raw.size)
    ys = pr.y_of_code0 - raw.astype(int)
    ok = (xs >= 0) & (xs < pr.screen_w) & (ys >= 0) & (ys < pr.screen_h)
    return xs, ys, ok


def trace_color(screen: Screen, ch) -> tuple[int | None, bool]:
    """Known colour of the channel's trace, or the colour found under the
    decoded samples (for channels whose colour is not known yet)."""
    col = screen.profile.trace_colors.get(ch.name)
    if col is not None:
        return col, False
    xs, ys, ok = _expected_xy(screen.profile, ch.raw)
    vals = screen.codes[ys[ok], xs[ok]]
    vals = vals[vals != 0]
    if vals.size == 0:
        return None, True
    v, c = np.unique(vals, return_counts=True)
    return int(v[np.argmax(c)]), True


def trace_match_window(screen: Screen, m: Measurement) -> dict:
    """1013D: only the 750-point window that was on screen can be compared."""
    pr = screen.profile
    out = {}
    right = pr.grid_right or (pr.x0 + m.n_samples - 1)
    for ch in m.channels:
        if not ch.enabled:
            continue
        col = pr.trace_colors.get(ch.name)
        off = m.header.get(f"{ch.name.lower()}_screen_offset")
        hit = near = considered = 0
        if off is not None and col is not None:
            for i in range(off, min(off + right - pr.x0 + 1, m.n_samples)):
                x = pr.x0 + i - off
                y = int(pr.y_of_code0 - int(ch.raw[i]))
                if not (0 <= y < pr.screen_h):
                    continue
                considered += 1
                if screen.codes[y, x] == col:
                    hit += 1
                elif (screen.codes[max(0, y - 1):y + 2, x] == col).any():
                    near += 1
        considered = max(considered, 1)
        out[ch.name] = {"hits": hit, "near": near, "n": m.n_samples, "considered": considered,
                        "ratio": hit / considered, "ratio_near": (hit + near) / considered,
                        "color": col, "color_learned": False, "drawn_until": None, "window": off}
    return out


def trace_match(screen: Screen, m: Measurement) -> dict:
    """Check every decoded sample against the screenshot.

    Samples whose pixel falls into the measurement-text overlay band are
    not counted (the text may hide the trace there); neither are samples
    to the right of where the scope stopped drawing (slow-timebase roll).
    """
    pr = screen.profile
    if pr.grid_right and pr.n_samples > pr.grid_right:
        return trace_match_window(screen, m)
    out = {}
    for ch in m.channels:
        if not ch.enabled:
            continue
        col, learned = trace_color(screen, ch)
        n = m.n_samples
        if col is None:
            out[ch.name] = {"hits": 0, "near": 0, "n": n, "considered": 1, "ratio": 0.0, "ratio_near": 0.0,
                            "color": None, "color_learned": learned, "drawn_until": None}
            continue
        grid = screen.codes[max(0, pr.y_of_code0 - pr.code_max):pr.y_of_code0 - pr.code_min + 1,
                            pr.x0:pr.x0 + n]
        cols = np.flatnonzero((grid == col).any(axis=0))
        drawn_until = int(cols[-1]) if cols.size else -1
        hit = near = considered = 0
        for i, code in enumerate(ch.raw.astype(int)):
            if i > drawn_until:
                break
            x = pr.x0 + i
            y = pr.y_of_code0 - code
            if not (0 <= x < pr.screen_w and 0 <= y < pr.screen_h):
                continue
            if screen.codes[y, x] == col:
                hit += 1
                considered += 1
            elif pr.overlay_rows and pr.overlay_rows[0] <= y <= pr.overlay_rows[1]:
                continue
            else:
                considered += 1
                if (screen.codes[max(0, y - 1):y + 2, x] == col).any():
                    near += 1
        considered = max(considered, 1)
        out[ch.name] = {"hits": hit, "near": near, "n": n, "considered": considered,
                        "ratio": hit / considered, "ratio_near": (hit + near) / considered,
                        "color": col, "color_learned": learned, "drawn_until": drawn_until}
    return out


def trace_matches(info: dict) -> bool:
    tm = info.get("trace_match") or {}
    if not tm:
        return False
    # overlapping traces hide each other, so accept +-1 row hits as well;
    # at least half of the samples must be checkable
    return all(v["ratio_near"] >= MIN_TRACE_MATCH
               and v["considered"] >= min(v["n"] // 2, 300)
               for v in tm.values())


# ----------------------------------------------------------- top level
def analyse_screen(screen: Screen, m: Measurement | None = None) -> dict:
    info: dict = {"path": str(screen.path), "ok": True}
    fields = read_status_fields(screen)
    info["ocr"] = fields
    info["timebase_s"] = parse_timebase(fields["timebase"]["text"]) if fields["timebase"]["ok"] else None
    for ch in ("ch1", "ch2"):
        f = fields[f"{ch}_vdiv"]
        info[f"{ch}_vdiv"] = parse_vdiv(f["text"]) if f["ok"] else None
        pc = fields[f"{ch}_probe_coupling"]
        probe, coupling = parse_probe_coupling(pc["text"]) if pc["ok"] else (None, None)
        info[f"{ch}_probe"] = probe
        info[f"{ch}_coupling"] = coupling
    info["model"] = screen.profile.model
    colors = dict(screen.profile.trace_colors)
    if screen.profile.data_ext == ".wav":
        # 1013D: settings come from the WAV header; nothing to read from the picture
        info["ocr"] = {k: {"text": "", "ok": False} for k in
                       ("timebase", "ch1_vdiv", "ch1_probe_coupling", "ch2_vdiv", "ch2_probe_coupling")}
        info["note"] = ("Снимок и данные 1013D сохраняются разными кнопками (SAVE PIC / SAVE WAVE): кадры могут "
                        "отличаться. Шкалы берутся из файла WAV.")
    if m is not None:
        if m.prof is not screen.profile:
            info["trace_match"] = {}
            info["matches_bin"] = False
            info["error"] = f"Снимок от {screen.profile.model}, а BIN от {m.prof.model}."
        else:
            info["trace_match"] = trace_match(screen, m)
            info["matches_bin"] = trace_matches(info)
            for k, v in info["trace_match"].items():
                if colors.get(k) is None and v.get("color") is not None and info["matches_bin"]:
                    colors[k] = v["color"]
    info["markers"] = find_zero_markers(screen, colors)
    return info


def attach_bmp(m: Measurement, apply_scales: bool = True, bmp_path: str | Path | None = None) -> None:
    """Find the screenshot for ``m``, analyse it and (optionally) fill unknown scales."""
    p = Path(bmp_path) if bmp_path else find_bmp_for(m.path)
    if p is None:
        m.bmp_path = None
        m.bmp_info = {"ok": False, "error": "BMP с тем же именем не найден."}
        return
    m.bmp_path = p
    try:
        screen = load_screen(p)
    except BmpError as e:
        m.bmp_info = {"ok": False, "path": str(p), "error": str(e)}
        return
    if screen_profile_mismatch(screen, m):
        m.bmp_info = {"ok": False, "path": str(p), "matches_bin": False, "trace_match": {},
                      "error": f"Снимок от {screen.profile.model}, а данные от {m.prof.model}."}
        return
    info = analyse_screen(screen, m)
    m.bmp_info = info
    if info.get("matches_bin"):
        for k, v in info["trace_match"].items():
            du = v.get("drawn_until")
            if du is not None and 0 <= du < m.n_samples - 4:
                msg = (f"{k}: отсчёты {du + 1}–{m.n_samples - 1} не были показаны на экране прибора "
                       "(развёртка не дорисована) — вероятно, это старые данные.")
                if msg not in m.warnings:
                    m.warnings.append(msg)
                info.setdefault("undrawn_from", {})[k] = du + 1
    if apply_scales:
        apply_bmp_scales(m)


def screen_profile_mismatch(screen: Screen, m: Measurement) -> bool:
    return screen.profile.screen_w != m.prof.screen_w or screen.profile.screen_h != m.prof.screen_h


def apply_bmp_scales(m: Measurement, overwrite: bool = False) -> list[str]:
    """Copy recognised settings into the measurement (only unknown ones unless overwrite)."""
    info = m.bmp_info
    applied: list[str] = []
    if not info or not info.get("ok"):
        return applied
    if m.prof.data_ext == ".wav":
        return applied            # 1013D: all scales are in the file itself
    if not info.get("matches_bin"):
        msg = "BMP не совпадает с отсчётами BIN — шкалы из снимка не применены."
        if msg not in m.warnings:
            m.warnings.append(msg)
        return applied
    note = "распознано по снимку экрана, проверьте"

    def put(param, value, unit_note=""):
        if value is None:
            return False
        if param.known and not overwrite:
            return False
        param.set(value, SRC_BMP, note + unit_note)
        return True

    if put(m.time_per_div, info.get("timebase_s")):
        applied.append("время/дел")
    for ch in m.channels:
        k = ch.name.lower()
        if put(ch.volts_per_div, info.get(f"{k}_vdiv")):
            applied.append(f"{ch.name} В/дел")
        mk = info.get("markers", {}).get(ch.name, {})
        if mk.get("found"):
            if put(ch.zero_code, float(mk["zero_code"]), " (точность ±1 код)"):
                applied.append(f"{ch.name} ноль")
        put(ch.probe, info.get(f"{k}_probe"))
        put(ch.coupling, info.get(f"{k}_coupling"))
    return applied


def clear_bmp_scales(m: Measurement) -> None:
    for p in [m.time_per_div] + [x for ch in m.channels
                                 for x in (ch.volts_per_div, ch.zero_code, ch.probe, ch.coupling)]:
        if p.source == SRC_BMP:
            p.clear()
