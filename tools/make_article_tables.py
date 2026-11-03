"""Export examples + table pictures for the article.  python tools/make_article_tables.py <demo_folder> <articles_folder>"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from PIL import Image  # noqa: E402

from fnirsi2c53t.decoders.screen_digitizer import open_capture  # noqa: E402
from fnirsi2c53t.exporters import data_export, image_export  # noqa: E402

DEMO, A = Path(sys.argv[1]), Path(sys.argv[2])
I, EX = A / "illustrations", A / "export_examples"
I.mkdir(parents=True, exist_ok=True)
EX.mkdir(parents=True, exist_ok=True)

m = open_capture(DEMO / "1013D" / "1.wav")
data_export.write_csv(m, EX / "1013D_1.csv")
data_export.write_csv(m, EX / "1013D_1_excel_ru.csv", sep=";", decimal=",", json_sidecar=False)
data_export.write_xlsx(m, EX / "1013D_1.xlsx")
data_export.write_json(m, EX / "1013D_1.json")
image_export.render_measurement(m, EX / "1013D_1.png")
image_export.render_measurement(m, EX / "1013D_1.svg")
image_export.render_measurement(m, I / "23_report_png_1013d.png")
m2 = open_capture(DEMO / "2C53P" / "Screenshot simple file" / "2.bin")
data_export.write_csv(m2, EX / "2C53P_2.csv")
data_export.write_xlsx(m2, EX / "2C53P_2.xlsx")
image_export.render_measurement(m2, EX / "2C53P_2.png")


def table_png(rows, header, path, title, colw=None):
    fig, ax = plt.subplots(figsize=(11, 0.33 * (len(rows) + 2)), dpi=150)
    ax.axis("off")
    t = ax.table(cellText=rows, colLabels=header, loc="upper center", cellLoc="center", colWidths=colw)
    t.auto_set_font_size(False)
    t.set_fontsize(9)
    t.scale(1, 1.3)
    for (r, c), cell in t.get_celld().items():
        if r == 0:
            cell.set_facecolor("#dde6ef")
            cell.set_text_props(weight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f6f8fa")
    ax.set_title(title, fontsize=11, loc="left")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


lines = (EX / "1013D_1.csv").read_text(encoding="utf-8").splitlines()
hdr = lines[0].split(",")
rows = [ln.split(",") for ln in lines[1:13]] + [["…"] * len(hdr)]
table_png(rows, hdr, I / "20_csv_table.png",
          "CSV (1013D, 1.wav): первые 12 строк из 1500 — время, номер, исходный отсчёт, деления, вольты")
lines = (EX / "1013D_1_excel_ru.csv").read_text(encoding="utf-8").splitlines()
rows = [ln.split(";") for ln in lines[1:7]] + [["…"] * len(hdr)]
table_png(rows, lines[0].split(";"), I / "20b_csv_excel_ru.png",
          "Вариант «для русского Excel»: разделитель «;», десятичная запятая")
wb = load_workbook(EX / "1013D_1.xlsx")
r = [[str(c.value if c.value is not None else "") for c in row][:4] for row in wb["Measurements"].iter_rows(min_row=2)]
r = [[a, b, (f"{float(c):.5g}" if c not in ("", "None") else "—"), d] for a, b, c, d in r if a == "CH1"][:15]
table_png(r, ["Канал", "Параметр", "Значение", "Ед."], I / "21_xlsx_measurements.png",
          "XLSX, лист Measurements: автоматические измерения (1013D, 1.wav)", [0.1, 0.4, 0.25, 0.15])
r = [[str(c.value if c.value is not None else "") for c in row][:4] for row in wb["Metadata"].iter_rows(min_row=2, max_row=23)]
r = [[a, (b if len(b) < 50 else b[:48] + "…"), c, d] for a, b, c, d in r]
table_png(r, ["Параметр", "Значение", "Ед.", "Источник"], I / "22_xlsx_metadata.png",
          "XLSX, лист Metadata: у каждого параметра указан источник", [0.26, 0.44, 0.1, 0.2])


def bmp(p):
    d = open(p, "rb").read()
    off, = struct.unpack_from("<I", d, 10)
    w, h = struct.unpack_from("<ii", d, 18)
    px = np.frombuffer(d[off:off + w * abs(h) * 2], "<u2").reshape(abs(h), w)
    if h > 0:
        px = px[::-1]
    r, g, b = ((px >> 11) & 31) << 3, ((px >> 5) & 63) << 2, (px & 31) << 3
    return Image.fromarray(np.dstack([r, g, b]).astype(np.uint8))


for name, p, scale in (("30_screen_2c23t.png", DEMO / "2C23T" / "img_02.bmp", 3),
                       ("31_screen_2c53p.png", DEMO / "2C53P" / "Screenshot file" / "2.bmp", 2),
                       ("32_screen_1013d.png", DEMO / "1013D" / "1.bmp", 1.2)):
    im = bmp(p)
    im.resize((int(im.width * scale), int(im.height * scale)), Image.NEAREST).save(I / name)
print("ok")
