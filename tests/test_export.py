"""Checks 8, 11: lossless CSV/XLSX/JSON, images, batch, sessions."""
import csv
import json

import numpy as np
import pytest
from openpyxl import load_workbook

from conftest import SAMPLES
from fnirsi2c53t.decoders.fnirsi_2c53t import decode_file
from fnirsi2c53t.exporters import batch, data_export, image_export
from fnirsi2c53t.session import load_session, save_session
from fnirsi2c53t.visualization.traces import DisplayItem


def test_csv_lossless(sample, tmp_path):
    _, path, _ = sample
    m = decode_file(path)
    out = data_export.write_csv(m, tmp_path / "a.csv")
    with open(out[0], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 301
    for ch in m.enabled_channels:
        k = ch.name.lower()
        assert [int(r[f"{k}_raw"]) for r in rows] == ch.raw.tolist()
        assert np.array_equal(np.array([float(r[f"{k}_V"]) for r in rows]), ch.volts())
    assert np.array_equal(np.array([float(r["time_s"]) for r in rows]), m.time_axis())
    assert json.loads(out[1].read_text(encoding="utf-8"))["schema"] == "fnirsi2c53t-measurement/1"


def test_csv_without_scales_has_no_fake_columns(tmp_path):
    m = decode_file(SAMPLES / "1.bin", with_bmp=False)
    out = data_export.write_csv(m, tmp_path / "a.csv", sep=";")
    head = out[0].read_text(encoding="utf-8").splitlines()[0].split(";")
    assert head == ["sample_index", "ch1_raw", "ch1_div"]


def test_csv_excel_ru(tmp_path):
    m = decode_file(SAMPLES / "3.bin")
    out = data_export.write_csv(m, tmp_path / "a.csv", sep=";", decimal=",")
    line = out[0].read_text(encoding="utf-8").splitlines()[2]
    assert "," in line and "." not in line
    with pytest.raises(ValueError):
        data_export.write_csv(m, tmp_path / "b.csv", sep=",", decimal=",")


def test_xlsx(tmp_path):
    m = decode_file(SAMPLES / "6.bin")
    data_export.write_xlsx(m, tmp_path / "a.xlsx")
    wb = load_workbook(tmp_path / "a.xlsx")
    assert wb.sheetnames[:3] == ["Waveform", "Measurements", "Metadata"]
    ws = wb["Waveform"]
    hdr = [c.value for c in ws[1]]
    col = hdr.index("ch2_raw")
    assert [r[col].value for r in ws.iter_rows(min_row=2)] == m.channel("CH2").raw.tolist()


def test_json(tmp_path):
    m = decode_file(SAMPLES / "5.bin")
    data_export.write_json(m, tmp_path / "a.json")
    d = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert d["data"]["channels"]["CH2"]["raw"] == m.channel("CH2").raw.tolist()
    assert d["timebase"]["source"] == "bmp"


@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_images(tmp_path, fmt):
    m = decode_file(SAMPLES / "10.bin")
    p = image_export.render_measurement(m, tmp_path / f"a.{fmt}")
    assert p.stat().st_size > 1000


def test_batch_with_bad_file(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"123")
    rep = batch.export_many([SAMPLES / "1.bin", bad, SAMPLES / "9.bin"], tmp_path / "out",
                            batch.BatchOptions(("csv", "png")))
    assert [r[1] == "OK" for r in rep] == [True, False, True]


def test_session_roundtrip(tmp_path):
    m = decode_file(SAMPLES / "3.bin")
    m.channel("CH1").volts_per_div.set(1.0, "user")
    items = [DisplayItem(m, x_shift_samples=5), DisplayItem(decode_file(SAMPLES / "4.bin"))]
    p = save_session(tmp_path / "s.json", items, {"range": [0, 1, 2, 3]}, {"vertical": True}, {})
    data = json.loads(p.read_text(encoding="utf-8"))
    data["files"][1]["path"] = str(tmp_path / "missing.bin")     # simulate unplugged drive
    p.write_text(json.dumps(data), encoding="utf-8")
    loaded, _, problems = load_session(p)
    assert len(loaded) == 1 and len(problems) == 1
    ch = loaded[0].m.channel("CH1")
    assert ch.volts_per_div.value == 1.0 and ch.volts_per_div.source == "user"
    assert loaded[0].x_shift_samples == 5
