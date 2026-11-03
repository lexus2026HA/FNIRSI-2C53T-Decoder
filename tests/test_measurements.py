"""Checks 5-7: vertical and time scale against the scope's own readings; cursors; FFT."""
import numpy as np
import pytest

from conftest import SAMPLES
from fnirsi2c53t.analysis.cursors import nearest_index, vcursors
from fnirsi2c53t.analysis.fft import compute_spectrum
from fnirsi2c53t.analysis.measurements import channel_measurements, find_edges
from fnirsi2c53t.decoders.fnirsi_2c53t import decode_bytes, decode_file


def test_vpp_matches_scope(sample):
    _, path, t = sample
    m = decode_file(path)
    ch = m.channel(t["ch"])
    vpp = channel_measurements(m, ch).get("pp").value
    # screen data has 1/25 div resolution: allow 1 code + 2 %
    assert vpp == pytest.approx(t["vpp"], abs=ch.volts_per_code() + 0.02 * t["vpp"])


def test_frequency_matches_scope(sample):
    _, path, t = sample
    m = decode_file(path)
    r = channel_measurements(m, m.channel(t["ch"])).get("freq")
    assert r.unit == "Hz"
    assert r.value == pytest.approx(t["freq"], rel=0.03)


def test_sample_interval_is_div_over_25():
    m = decode_file(SAMPLES / "10.bin")
    assert m.sample_interval() == pytest.approx(1e-3 / 25)
    # 12 periods of 1 kHz: div/25 gives 1000 Hz within 0.1 %; div*12/301 would give 1003 Hz
    f = channel_measurements(m, m.channel("CH2")).get("freq").value
    assert f == pytest.approx(1000, rel=1e-3)


def test_flat_signal_reports_cannot():
    m = decode_file(SAMPLES / "6.bin")
    r = channel_measurements(m, m.channel("CH1")).get("freq")
    assert r.value is None and "Не удалось" in r.reason


def test_frequency_without_timebase_is_per_sample():
    m = decode_file(SAMPLES / "10.bin", with_bmp=False)
    r = channel_measurements(m, m.channel("CH2"))
    assert r.get("freq").unit == "1/отсч."
    assert r.get("freq").value == pytest.approx(1 / 25, rel=1e-3)
    assert r.get("rms").value is None


def test_hysteresis_rejects_noise():
    rng = np.random.default_rng(1)
    x = 128 + 50 * np.sign(np.sin((np.arange(301) + 0.5) * 2 * np.pi / 50)) + rng.integers(-3, 4, 301)
    rising, _ = find_edges(x, 128, 20)
    assert len(rising) == 6
    assert np.diff(rising).mean() == pytest.approx(50, abs=0.5)


def test_duty_known_signal():
    raw = bytes(200 if (i % 40) < 10 else 60 for i in range(301))
    m = decode_bytes(raw + raw + bytes([1, 0, 0, 1, 0x2D]))
    r = channel_measurements(m, m.channel("CH1"))
    assert r.get("duty").value == pytest.approx(25, abs=1.0)
    assert r.get("period").value == pytest.approx(40, abs=0.01)


def test_cursors():
    x = np.arange(301) * 8e-6
    assert nearest_index(0.0010, x) == 125
    c = vcursors(x[25], x[150], x)
    assert c.dx == pytest.approx(1e-3)
    assert c.inv_dx() == pytest.approx(1000)
    assert c.di == 125


def test_fft_peak_and_resolution():
    dt = 1e-5
    t = np.arange(300) * dt
    y = 2.0 * np.sin(2 * np.pi * 2000 * t)       # exactly 6 cycles
    sp = compute_spectrum(y, dt, "flattop")
    assert sp.peaks[0]["freq"] == pytest.approx(2000)
    assert sp.peaks[0]["amp"] == pytest.approx(2.0, rel=0.01)
    sp2 = compute_spectrum(y, dt, "hann", nfft=1200)
    assert sp2.resolution == sp.resolution
    assert any("нулями" in n for n in sp2.notes)
    assert compute_spectrum(y, None).freq_unit != "Hz"
