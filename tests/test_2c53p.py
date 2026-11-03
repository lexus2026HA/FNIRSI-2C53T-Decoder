"""FNIRSI 2C53P: 927-byte BIN in 'Screenshot simple file', 480x272 BMP in 'Screenshot file'.

Ground truth read by eye from the device's own screenshots (CH1 only enabled).
"""
import csv

import numpy as np
import pytest

from conftest import SAMPLES
from fnirsi2c53t.analysis.measurements import channel_measurements
from fnirsi2c53t.decoders import bmp_screen as bs
from fnirsi2c53t.decoders.fnirsi_2c53t import decode_bytes, decode_file, find_bin_for, find_bmp_for
from fnirsi2c53t.decoders.model import SRC_BMP
from fnirsi2c53t.decoders.profiles import P2C53P
from fnirsi2c53t.exporters import data_export
from fnirsi2c53t.io.drives import guess_capture_folder

P_ROOT = SAMPLES / "2c53p"
BIN_DIR = P_ROOT / "Screenshot simple file"
BMP_DIR = P_ROOT / "Screenshot file"
TRUTH_P = {
    "1": dict(tb=0.2, v1=1.0, v2=1.0, undrawn_from=392),
    "2": dict(tb=1e-3, v1=1.0, v2=0.1, undrawn_from=None, vpp=3.41),
    "3": dict(tb=1e-3, v1=1.0, v2=0.1, undrawn_from=None, vpp=3.53),
}


@pytest.fixture(params=sorted(TRUTH_P))
def psample(request):
    return request.param, BIN_DIR / f"{request.param}.bin", TRUTH_P[request.param]


def test_layout(psample):
    _, path, _ = psample
    data = path.read_bytes()
    m = decode_file(path, with_bmp=False)
    assert m.prof is P2C53P and m.n_samples == 461
    assert bytes(m.channel("CH1").raw) == data[0:461]
    assert bytes(m.channel("CH2").raw) == data[463:924]
    assert [c.name for c in m.enabled_channels] == ["CH1"]
    ch1 = m.channel("CH1").raw
    assert (data[461], data[462]) == (ch1.max(), ch1.min())     # stored max/min
    assert not any("макс/мин" in w for w in m.warnings)


def test_corrupted_maxmin_warns():
    data = bytearray((BIN_DIR / "2.bin").read_bytes())
    data[461] = 7
    m = decode_bytes(bytes(data))
    assert any("макс/мин" in w for w in m.warnings)


def test_bmp_in_sibling_folder(psample):
    n, path, _ = psample
    assert find_bmp_for(path) == BMP_DIR / f"{n}.bmp"
    assert find_bin_for(BMP_DIR / f"{n}.bmp") == path


def test_trace_matches_screenshot(psample):
    _, path, t = psample
    m = decode_file(path)
    assert m.bmp_info["matches_bin"]
    v = m.bmp_info["trace_match"]["CH1"]
    assert v["hits"] / v["considered"] >= 0.98


def test_scales_recognised(psample):
    _, path, t = psample
    m = decode_file(path)
    assert m.time_per_div.value == pytest.approx(t["tb"]) and m.time_per_div.source == SRC_BMP
    assert m.channel("CH1").volts_per_div.value == pytest.approx(t["v1"])
    assert m.channel("CH2").volts_per_div.value == pytest.approx(t["v2"])
    ch1 = m.channel("CH1")
    assert (ch1.probe.value, ch1.coupling.value) == (1, "AC")
    assert ch1.zero_code.known
    assert m.sample_interval() == pytest.approx(t["tb"] / 50)


def test_undrawn_tail_reported(psample):
    _, path, t = psample
    m = decode_file(path)
    got = (m.bmp_info.get("undrawn_from") or {}).get("CH1")
    assert got == t["undrawn_from"]
    assert any("не были показаны" in w for w in m.warnings) == (t["undrawn_from"] is not None)


@pytest.mark.parametrize("n", ["2", "3"])
def test_measurements(n):
    m = decode_file(BIN_DIR / f"{n}.bin")
    r = channel_measurements(m, m.channel("CH1"))
    assert r.get("pp").value == pytest.approx(TRUTH_P[n]["vpp"], abs=0.02)
    assert r.get("freq").value == pytest.approx(1000, rel=0.01)   # ~1 kHz on screen: 1 period per division
    assert r.get("duty").value == pytest.approx(50, abs=2)
    # AC coupling: the zero marker sits near the signal mean
    assert abs(r.get("mean").value) < 0.15


def test_profile_mismatch_rejected():
    m = decode_file(BIN_DIR / "2.bin", with_bmp=False)
    bs.attach_bmp(m, bmp_path=SAMPLES / "10.bmp")         # a 2C53T screenshot
    assert not m.bmp_info["matches_bin"]
    assert m.time_per_div.value is None


def test_csv_lossless(tmp_path):
    m = decode_file(BIN_DIR / "3.bin")
    out = data_export.write_csv(m, tmp_path / "p.csv")
    with open(out[0], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 461
    assert [int(r["ch1_raw"]) for r in rows] == m.channel("CH1").raw.tolist()
    assert np.array_equal(np.array([float(r["ch1_V"]) for r in rows]), m.channel("CH1").volts())


def test_capture_folder_on_drive_layout():
    assert guess_capture_folder(P_ROOT) == BIN_DIR


def test_unknown_glyph_fails_p():
    mask = np.zeros((10, 8), bool)
    mask[1:9, 1:7] = True
    _, ok = bs.read_text(mask, "p")
    assert not ok
