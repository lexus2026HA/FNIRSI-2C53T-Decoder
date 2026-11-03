"""Build glyph templates from labelled 2C53T screenshots.

Labels were read by eye from the sample screenshots in samples/.
Run:  python tools/build_glyphs.py [--loo]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fnirsi2c53t.decoders import bmp_screen as bs  # noqa: E402
from fnirsi2c53t.decoders.profiles import P2C23T  # noqa: E402

LABELS = {
    "1": ("H=2mS", "20V", "X10 DC", "100mV", "X10 AC"),
    "2": ("H=20mS", "20V", "X10 DC", "100mV", "X10 AC"),
    "3": ("H=200uS", "500mV", "X10 DC", "100mV", "X10 AC"),
    "4": ("H=200uS", "1V", "X10 DC", "100mV", "X10 AC"),
    "5": ("H=200uS", "200mV", "X10 DC", "500mV", "X10 AC"),
    "6": ("H=200uS", "200mV", "X10 DC", "500mV", "X10 AC"),
    "8": ("H=200uS", "200mV", "X10 DC", "500mV", "X10 AC"),
    "9": ("H=200uS", "200mV", "X10 DC", "100mV", "X10 AC"),
    "10": ("H=1mS", "200mV", "X10 DC", "500mV", "X10 AC"),
}
FIELDS = ["timebase", "ch1_vdiv", "ch1_probe_coupling", "ch2_vdiv", "ch2_probe_coupling"]

# 2C53P screenshots (samples/2c53p/Screenshot file/N.bmp): ch1 label, ch2 label, timebase
P_DIR = ROOT / "samples" / "2c53p" / "Screenshot file"
LABELS_P = {
    "1": ("1V X1 AC", "1V X1 AC", "200mS"),
    "2": ("1V X1 AC", "100mV X1 AC", "1mS"),
    "3": ("1V X1 AC", "100mV X1 AC", "1mS"),
}
P_FIELDS = ["ch1", "ch2", "timebase"]

# 2C23T screenshots (samples/2c23t/img_NN.bmp): ch1 label, ch2 label, timebase
T23_DIR = ROOT / "samples" / "2c23t"
LABELS_23 = {
    "img_01": ("20mV X1 AC", "50mV X1 AC", "500ns"),
    "img_02": ("1V X1 AC", "200mV X1 AC", "500us"),
    "img_03": ("500mV X1 AC", "50mV X1 AC", "50us"),
    "img_04": ("1V X1 AC", "50mV X1 AC", "5us"),
    "img_05": ("1V X1 AC", "50mV X1 AC", "10us"),
    "img_06": ("1V X1 AC", "50mV X1 AC", "10us"),
}


def collect_23(names, verbose=False):
    """Italic font: neighbouring glyphs may touch; split wide segments by known widths."""
    tpl, pending, widths = {}, [], {}
    for n in names:
        scr = bs.load_screen(T23_DIR / f"{n}.bmp", prefer=P2C23T)
        for fname, label in zip(P_FIELDS, LABELS_23[n]):
            mask = bs.t23_field_mask(scr, fname)
            segs = [s for s in bs.segment(mask, space_gap=4) if s is not None]
            chars = label.replace(" ", "")
            counts = ([1] * len(segs) if len(segs) == len(chars)
                      else [max(1, round((b - a + 1) / 6.5)) for a, b in segs])
            if verbose:
                print(n, fname, label, [(b - a) for a, b in segs], counts)
            if sum(counts) != len(chars):
                raise SystemExit(f"2c23t {n}/{fname}: cannot split {[(b - a) for a, b in segs]} into {label!r}")
            i = 0
            for (a0, b0), k in zip(segs, counts):
                g = chars[i:i + k]
                if k == 1:
                    widths.setdefault(g, set()).add(b0 - a0)
                pending.append((mask[:, a0:b0], g, f"{n}/{fname}"))
                i += k
    for sub, group, src in pending:
        for part, ch in zip(_split(sub, group, widths), group):
            key = bs.glyph_key(part)
            old = tpl.get(key)
            if old and old != ch:
                raise SystemExit(f"conflict t23 {old}/{ch} in {src}")
            tpl[key] = ch
    return tpl


def collect_p(names):
    """2C53P font is crisp and glyphs never touch: one segment = one character."""
    tpl = {}
    for n in names:
        scr = bs.load_screen(P_DIR / f"{n}.bmp")
        for fname, label in zip(P_FIELDS, LABELS_P[n]):
            mask = bs.p_field_mask(scr, fname)
            segs = []
            for seg in bs.segment(mask):
                if seg is None:
                    continue
                a0, b0 = seg
                if b0 - a0 >= 10:          # touching glyphs: monospace cells of 6 px
                    for x in range(a0, b0, 6):
                        segs.append((x, min(x + 6, b0)))
                else:
                    segs.append(seg)
            chars = label.replace(" ", "")
            if len(segs) != len(chars):
                raise SystemExit(f"2c53p {n}/{fname}: {len(segs)} glyphs vs label {label!r}")
            for (a, b), ch in zip(segs, chars):
                key = bs.glyph_key(mask[:, a:b])
                old = tpl.get(key)
                if old and old != ch:
                    raise SystemExit(f"conflict p {old}/{ch} in {n}/{fname}")
                tpl[key] = ch
    return tpl


def field_masks(screen):
    R_T, R_B = bs.FIELD_ROWS_TOP, bs.FIELD_ROWS_BOTTOM
    m1 = bs._field_mask(screen, R_B, (0, 62), bs.mask_yellow)
    e1 = bs._text_extent(m1)
    m2 = bs._field_mask(screen, R_B, (222, 292), bs.mask_blue)
    e2 = bs._text_extent(m2)
    return {
        "timebase": (bs._field_mask(screen, R_T, (45, 140), bs.mask_light), "top"),
        "ch1_vdiv": (m1, "bottom"),
        "ch1_probe_coupling": (bs._field_mask(screen, R_B, ((e1[1] + 1) if e1 else 30, 104), bs.mask_light), "bottom"),
        "ch2_vdiv": (m2, "bottom"),
        "ch2_probe_coupling": (bs._field_mask(screen, R_B, (222 + ((e2[1] + 1) if e2 else 40), 320), bs.mask_light), "bottom"),
    }


PITCH = 8.5


def _trim(sub):
    cols = sub.any(axis=0).nonzero()[0]
    return sub[:, cols[0]:cols[-1] + 1] if cols.size else sub[:, :0]


def _split(sub, chars, widths):
    """Split a segment of touching glyphs.

    Cut positions come from the widths of the same characters seen
    standing alone (``widths``); without that, the column with least ink
    near the expected position is used.
    """
    k = len(chars)
    if k == 1:
        return [sub]
    ink = sub.sum(axis=0)
    w = sub.shape[1]
    cuts = []
    prev = 0
    for j in range(1, k):
        left_c, right_rest = chars[j - 1], chars[j:]
        cands = []
        for wl in widths.get(left_c, ()):            # from the left
            cands.append(prev + wl)
        if all(c in widths for c in right_rest):      # from the right
            for combo in [min(widths[c]) for c in right_rest], [max(widths[c]) for c in right_rest]:
                cands.append(w - sum(combo))
        cands = [c for c in cands if prev < c < w]
        if cands:
            cut = min(cands, key=lambda x: (ink[x - 1] + ink[min(x, w - 1)], x))
        else:
            c = prev + (w - prev) / (k - j + 1)
            lo, hi = max(prev + 1, int(c - 2)), min(w - 1, int(c + 3))
            cut = min(range(lo, hi), key=lambda x: (ink[x], abs(x - c)))
        cuts.append(cut)
        prev = cut
    parts, prev = [], 0
    for cut in cuts + [w]:
        parts.append(_trim(sub[:, prev:cut]))
        prev = cut
    return parts


def collect(names):
    tpl = {"top": {}, "bottom": {}}
    pending = []
    widths = {"top": {}, "bottom": {}}
    for n in names:
        scr = bs.load_screen(ROOT / "samples" / f"{n}.bmp")
        fm = field_masks(scr)
        for fname, label in zip(FIELDS, LABELS[n]):
            mask, font = fm[fname]
            segs = [s for s in bs.segment(mask) if s is not None]
            chars = label.replace(" ", "")
            counts = [max(1, round((b - a + 1) / PITCH)) for a, b in segs]
            if sum(counts) != len(chars):
                raise SystemExit(f"{n}/{fname}: cannot split {counts} into {label!r}")
            i = 0
            for (a, b), k in zip(segs, counts):
                group = chars[i:i + k]
                if k == 1:
                    widths[font].setdefault(group, set()).add(b - a)
                pending.append((font, mask[:, a:b], group, f"{n}/{fname}"))
                i += k
    for font, sub, group, src in pending:
        for part, ch in zip(_split(sub, group, widths[font]), group):
            key = bs.glyph_key(part)
            old = tpl[font].get(key)
            if old and old != ch:
                raise SystemExit(f"conflict {font} {old}/{ch} in {src}")
            tpl[font][key] = ch
    return tpl


def write(tpl):
    out = ['"""Glyph templates for the 2C53T status-bar font.', "",
           "Generated by tools/build_glyphs.py from labelled screenshots in samples/.",
           "Each key is the glyph bitmap, rows joined with '|'.", '"""', "",
           "TEMPLATES: dict = {"]
    for font in tpl:
        out.append(f"    {font!r}: {{")
        for k, ch in sorted(tpl[font].items(), key=lambda kv: (kv[1], kv[0])):
            out.append(f"        {k!r}: {ch!r},")
        out.append("    },")
    out.append("}")
    p = ROOT / "src" / "fnirsi2c53t" / "decoders" / "glyph_templates.py"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    chars = {f: "".join(sorted(set(v.values()))) for f, v in tpl.items()}
    print("templates:", {f: len(v) for f, v in tpl.items()}, chars)


def loo():
    bad = 0
    for n in LABELS:
        tpl = collect([k for k in LABELS if k != n])
        bs.TEMPLATES.clear(); bs.TEMPLATES.update(tpl)
        scr = bs.load_screen(ROOT / "samples" / f"{n}.bmp")
        res = bs.read_status_fields(scr)
        for fname, label in zip(FIELDS, LABELS[n]):
            r = res[fname]
            good = r["ok"] and r["text"] == label
            if not good:
                bad += 1
            print(f"{n:>3} {fname:20} {label:10} -> {r['text']!r:14} ok={r['ok']} {'' if good else '<-- MISS'}")
    print("leave-one-out misses:", bad)


if __name__ == "__main__":
    if "--loo" in sys.argv:
        loo()
    else:
        t = collect(list(LABELS))
        t["p"] = collect_p(list(LABELS_P))
        t["t23"] = collect_23(list(LABELS_23), verbose="-v" in sys.argv)
        write(t)
