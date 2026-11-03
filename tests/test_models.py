"""2C23T (screenshots only, digitised) and model selection."""
import pytest

from conftest import SAMPLES
from fnirsi2c53t.analysis.measurements import channel_measurements
from fnirsi2c53t.decoders.fnirsi_2c53t import DecodeError
from fnirsi2c53t.decoders.profiles import P2C23T, P2C53P, P2C53T
from fnirsi2c53t.decoders.screen_digitizer import open_capture
from fnirsi2c53t.exporters import batch

T23 = SAMPLES / "2c23t"
# by eye from the scope screens: timebase, CH1 V/div, CH2 V/div, on-screen CH1 Freq, Vpp
TRUTH_23 = {
    "img_01": (500e-9, 0.02, 0.05, None, None),
    "img_02": (500e-6, 1.0, 0.2, 1000.0, 2.87),
    "img_03": (50e-6, 0.5, 0.05, 11110.0, 1.96),
    "img_04": (5e-6, 1.0, 0.05, None, 1.89),
    "img_05": (10e-6, 1.0, 0.05, 90110.0, 1.88),
    "img_06": (10e-6, 1.0, 0.05, None, 0.04),
}


@pytest.mark.parametrize("name", sorted(TRUTH_23))
def test_2c23t_scales_and_values(name):
    tb, v1, v2, freq, vpp = TRUTH_23[name]
    m = open_capture(T23 / f"{name}.bmp")
    assert m.prof is P2C23T
    assert any("оцифрованы" in w for w in m.warnings)
    assert m.time_per_div.value == pytest.approx(tb)
    assert m.channel("CH1").volts_per_div.value == pytest.approx(v1)
    assert m.channel("CH2").volts_per_div.value == pytest.approx(v2)
    if name == "img_01":                      # Single mode, nothing captured yet
        assert not m.enabled_channels
        return
    ch1 = m.channel("CH1")
    assert ch1.enabled and ch1.zero_code.value == pytest.approx(178)
    r = channel_measurements(m, ch1)
    if freq:
        assert r.get("freq").value == pytest.approx(freq, rel=0.015)
    # digitising the stroke centre loses thin peaks: within 12 % of the scope's Vpp
    assert r.get("pp").value == pytest.approx(vpp, rel=0.12, abs=0.05)


def test_model_selection():
    with pytest.raises(DecodeError, match="1013D"):
        open_capture(SAMPLES / "1.bin", "1013d")
    with pytest.raises(DecodeError, match="2C53P"):
        open_capture(SAMPLES / "1.bin", "2c53p")
    with pytest.raises(DecodeError, match="не сохраняет файлы данных"):
        open_capture(SAMPLES / "1.bin", "2c23t")
    assert open_capture(SAMPLES / "1.bin", "2c53t").prof is P2C53T
    # a BMP opens its BIN when one exists
    m = open_capture(SAMPLES / "2c53p" / "Screenshot file" / "2.bmp")
    assert m.prof is P2C53P and m.path.suffix == ".bin"
    # forcing 2C23T on a 2C53T screenshot digitises it instead
    m = open_capture(SAMPLES / "10.bmp", "2c23t")
    assert m.prof is P2C23T


def test_batch_screenshots(tmp_path):
    rep = batch.export_many([T23 / "img_02.bmp", T23 / "img_03.bmp"], tmp_path,
                            batch.BatchOptions(("csv", "png"), model="2c23t"))
    assert [r[1] for r in rep] == ["OK", "OK"]
