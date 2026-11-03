"""Check 4: decoded samples match the screenshot; scale and zero-marker recovery."""
import numpy as np
import pytest

from conftest import SAMPLES
from fnirsi2c53t.decoders import bmp_screen as bs
from fnirsi2c53t.decoders.fnirsi_2c53t import decode_file
from fnirsi2c53t.decoders.model import SRC_BMP


def test_trace_matches_screenshot(sample):
    _, path, _ = sample
    m = decode_file(path)
    assert m.bmp_info["matches_bin"]
    for ch, v in m.bmp_info["trace_match"].items():
        assert v["hits"] / v["considered"] >= 0.98, (ch, v)


def test_scales_recognised(sample):
    _, path, t = sample
    m = decode_file(path)
    assert m.time_per_div.value == pytest.approx(t["tb"])
    assert m.time_per_div.source == SRC_BMP
    assert m.channel("CH1").volts_per_div.value == pytest.approx(t["v1"])
    assert m.channel("CH2").volts_per_div.value == pytest.approx(t["v2"])
    for ch in m.enabled_channels:
        assert ch.zero_code.known and ch.zero_code.source == SRC_BMP


def test_zero_marker_dc_signal():
    # sample 3: 0..3 V square, DC coupled -> low level must be about 0 V
    m = decode_file(SAMPLES / "3.bin")
    v = np.sort(m.channel("CH1").volts())
    assert abs(v[20]) < 0.05
    assert v[-20] == pytest.approx(3.0, abs=0.1)


def test_mismatched_bmp_is_rejected():
    m = decode_file(SAMPLES / "1.bin", with_bmp=False)
    bs.attach_bmp(m, bmp_path=SAMPLES / "10.bmp")
    assert not m.bmp_info["matches_bin"]
    assert m.time_per_div.value is None


def test_unknown_glyph_is_not_guessed():
    mask = np.zeros((14, 12), bool)
    mask[3:11, 2:9] = True          # a solid block is no character
    _, ok = bs.read_text(mask, "bottom")
    assert not ok


@pytest.mark.parametrize("text,val", [("H=200uS", 2e-4), ("H=1mS", 1e-3), ("H=20mS", 2e-2), ("H=3mS", None)])
def test_parse_timebase(text, val):
    assert bs.parse_timebase(text) == (pytest.approx(val) if val else None)


def test_bad_bmp(tmp_path):
    p = tmp_path / "x.bmp"
    p.write_bytes(b"BM" + bytes(60))
    with pytest.raises(bs.BmpError):
        bs.load_screen(p)
