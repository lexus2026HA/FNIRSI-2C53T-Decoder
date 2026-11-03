"""Checks 1-3, 9, 12: reading, sample count, channel split, damaged files, unknown scales."""
import numpy as np
import pytest

from conftest import SAMPLES
from fnirsi2c53t.decoders.fnirsi_2c53t import FILE_SIZE, N_SAMPLES, DecodeError, decode_bytes, decode_file
from fnirsi2c53t.decoders.model import SRC_UNKNOWN


def test_reads_all_samples(sample):
    _, path, t = sample
    m = decode_file(path, with_bmp=False)
    assert m.n_samples == N_SAMPLES == 301
    assert tuple(c.name for c in m.enabled_channels) == t["on"]
    for ch in m.channels:
        assert ch.raw.dtype == np.uint8 and ch.raw.size == 301


def test_channel_split_matches_bytes(sample):
    _, path, _ = sample
    data = path.read_bytes()
    m = decode_file(path, with_bmp=False)
    assert bytes(m.channel("CH1").raw) == data[0:301]
    assert bytes(m.channel("CH2").raw) == data[301:602]
    assert data[603:607] == bytes([0, 0, 1, 0x2D])


def test_without_bmp_nothing_is_invented(sample):
    _, path, _ = sample
    m = decode_file(path, with_bmp=False)
    assert m.time_per_div.value is None and m.time_per_div.source == SRC_UNKNOWN
    assert m.time_axis() is None
    for ch in m.channels:
        assert ch.volts() is None
        assert ch.divisions() is not None
    assert any("неизвестна" in w for w in m.reliability_warnings())


def _blob(n, fill=0x80):
    return bytes([fill]) * n


@pytest.mark.parametrize("data,msg", [
    (b"", "Пустой"),
    (_blob(100), "короткий"),
    (_blob(602) + bytes([1, 0, 0, 0, 0x10]), "длины"),
])
def test_damaged_files(data, msg):
    with pytest.raises(DecodeError, match=msg):
        decode_bytes(data)


def test_missing_file(tmp_path):
    with pytest.raises(DecodeError, match="не найден"):
        decode_file(tmp_path / "gone.bin")


def test_extra_bytes_and_flags_warn():
    m = decode_bytes(_blob(602) + bytes([7, 0, 0, 1, 0x2D]) + b"xx")
    assert len(m.warnings) == 2
    assert m.file_size == FILE_SIZE + 2


def test_clipping_warning():
    m = decode_file(SAMPLES / "9.bin", with_bmp=False)
    assert any("край экрана" in w for w in m.warnings)


def test_file_not_modified(sample):
    _, path, _ = sample
    before = (path.read_bytes(), path.stat().st_mtime)
    decode_file(path)
    assert (path.read_bytes(), path.stat().st_mtime) == before
