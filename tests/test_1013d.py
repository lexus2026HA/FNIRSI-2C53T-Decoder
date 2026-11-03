"""FNIRSI 1013D .wav files (original firmware), checked against the scope's own screenshots."""
import numpy as np
import pytest

from conftest import SAMPLES
from fnirsi2c53t.analysis.measurements import channel_measurements
from fnirsi2c53t.decoders.fnirsi_1013d import screen_window
from fnirsi2c53t.decoders.fnirsi_2c53t import DecodeError, decode_bytes
from fnirsi2c53t.decoders.model import SRC_FILE
from fnirsi2c53t.decoders.profiles import P1013D
from fnirsi2c53t.decoders.screen_digitizer import open_capture

D = SAMPLES / "1013d"
# by eye from the screenshots of the same settings: timebase, CH1 V/div, CH1 coupling, CH2 on, CH2 V/div
TRUTH = {
    1: (500e-6, 1.0, "DC", True, 0.05),
    2: (100e-6, 0.5, "DC", True, 0.05),
    3: (2e-3, 0.05, "AC", False, 5.0),
    12: (2.0, 1.0, "AC", False, 5.0),      # wav 12 = 2 s/div (bmp 15)
    19: (5e-6, 0.5, "AC", False, 50.0),     # CH2 x10 probe -> 50 V/div
    20: (5e-6, 0.5, "AC", False, 50.0),
    21: (5e-6, 0.5, "AC", False, 50.0),
}


@pytest.mark.parametrize("n", sorted(TRUTH))
def test_header_settings(n):
    tb, v1, c1, ch2_on, v2 = TRUTH[n]
    m = open_capture(D / f"{n}.wav")
    assert m.prof is P1013D and m.n_samples == 1500
    assert m.time_per_div.value == pytest.approx(tb) and m.time_per_div.source == SRC_FILE
    ch1, ch2 = m.channels
    assert ch1.volts_per_div.value == pytest.approx(v1) and ch1.coupling.value == c1
    assert ch2.enabled == ch2_on and ch2.volts_per_div.value == pytest.approx(v2)
    assert ch1.zero_code.source == SRC_FILE
    assert not any("не откалибровано" in w for w in m.reliability_warnings())


def test_screen_is_window_of_buffer():
    data = (D / "1.wav").read_bytes()
    buf = np.frombuffer(data, "<u2", 1500, 1000)
    scr = np.frombuffer(data, "<u2", 750, 7000)
    off = screen_window(buf, scr)
    assert off == 387
    assert np.array_equal(449 - scr.astype(int), buf[off:off + 750].astype(int))


def test_values_match_scope_readout():
    m = open_capture(D / "1.wav")             # screen: VPP 3.17 V, Freq 1.00 kHz (1 V/div DC)
    r = channel_measurements(m, m.channel("CH1"))
    assert r.get("pp").value == pytest.approx(3.17, abs=0.1)
    assert r.get("freq").value == pytest.approx(1000, rel=0.005)
    assert m.sample_interval() == pytest.approx(500e-6 / 50)
    # zero level from the header sits where the screen marker is: CH1 237 -> row 212
    assert 449 - m.channel("CH1").zero_code.value == 212


def test_screenshot_pairs_match_when_frame_identical():
    m = open_capture(D / "1.wav")
    assert m.bmp_info["matches_bin"]
    assert m.bmp_info["trace_match"]["CH2"]["hits"] >= 700


def test_bad_header_rejected():
    data = bytearray((D / "1.wav").read_bytes())
    data[22] = 77
    with pytest.raises(DecodeError, match="прошивка"):
        decode_bytes(bytes(data), "x.wav")


def test_model_forcing():
    with pytest.raises(DecodeError, match="1013D"):
        open_capture(D / "1.wav", "2c53t")
    assert open_capture(D / "19.wav", "1013d").prof is P1013D
