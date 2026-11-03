"""Diagrams for the article: file layouts and workflow.  python tools/make_article_diagrams.py <out_folder>"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
C = {"hdr": "#8fa8c8", "ch1": "#e6c34a", "ch2": "#5aa0f0", "meta": "#b9b9b9", "scr": "#f0a35a",
     "zero": "#eeeeee", "mm": "#c48ad8"}


def layout():
    rows = [
        ("2C53T  ·  N.bin, 607 байт", 607, [(0, 301, "CH1: 301 × uint8", "ch1"), (301, 602, "CH2: 301 × uint8", "ch2"),
                                           (602, 607, "", "meta")]),
        ("2C53P  ·  N.bin, 927 байт", 927, [(0, 461, "CH1: 461 × uint8", "ch1"), (461, 463, "", "mm"),
                                           (463, 924, "CH2: 461 × uint8", "ch2"), (924, 926, "", "mm"),
                                           (926, 927, "", "meta")]),
        ("1013D  ·  N.wav, 15 000 байт", 15000, [(0, 1000, "заголов.", "hdr"), (1000, 4000, "CH1: 1500 × uint16", "ch1"),
                                                (4000, 7000, "CH2: 1500 × uint16", "ch2"), (7000, 8500, "экран CH1", "scr"),
                                                (8500, 10000, "экран CH2", "scr"), (10000, 15000, "нули", "zero")]),
    ]
    fig, ax = plt.subplots(figsize=(12, 4.6), dpi=150)
    for k, (title, size, parts) in enumerate(rows):
        y = 2.2 - k * 1.05
        ax.text(0, y + 0.42, title, fontsize=11, weight="bold", va="bottom")
        for a, b, lab, key in parts:
            x0, x1 = a / size, b / size
            ax.add_patch(FancyBboxPatch((x0, y), max(x1 - x0, 0.003), 0.36, boxstyle="square,pad=0",
                                        fc=C[key], ec="#333", lw=0.8))
            if lab:
                ax.text((x0 + x1) / 2, y + 0.18, lab, ha="center", va="center", fontsize=9 if x1 - x0 > 0.08 else 7.5)
    ax.text(0, -0.45, "узкие блоки: фиолетовые — записанные прибором макс./мин. канала, серые — флаги каналов (у 2C53T + поле длины)",
            ha="left", fontsize=9, color="#555")
    ax.text(0, -0.85, "2C23T: файлов данных нет — только снимок экрана img_NN.bmp (320×240); "
                      "программа оцифровывает луч по пикселям.", fontsize=10, color="#7a3b00")
    ax.set_xlim(-0.01, 1.01)
    ax.set_ylim(-1.0, 2.9)
    ax.axis("off")
    fig.savefig(OUT / "40_file_layouts.png", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def workflow():
    fig, ax = plt.subplots(figsize=(12, 3.4), dpi=150)
    boxes = [
        (0.0, "Осциллограф\nSAVE PIC / SAVE WAVE", "#e8eef6"),
        (0.205, "USB: прибор\nвиден как флешка", "#e8eef6"),
        (0.41, "Файлы\n.bin / .wav / .bmp", "#fff3d6"),
        (0.615, "FNIRSI-2C53T-Decoder\nграфик, курсоры,\nизмерения, FFT", "#dff3e3"),
        (0.82, "CSV · XLSX · JSON\nPNG · SVG · PDF", "#fde4e4"),
    ]
    for x, text, col in boxes:
        ax.add_patch(FancyBboxPatch((x, 0.25), 0.17, 0.5, boxstyle="round,pad=0.012", fc=col, ec="#445", lw=1))
        ax.text(x + 0.085, 0.5, text, ha="center", va="center", fontsize=10)
    for x, _, _ in boxes[:-1]:
        ax.add_patch(FancyArrowPatch((x + 0.178, 0.5), (x + 0.2, 0.5), arrowstyle="-|>", mutation_scale=14, lw=1.4))
    ax.text(0.5, 0.08, "Исходные файлы только читаются: программа ничего не пишет на прибор.",
            ha="center", fontsize=9.5, color="#555")
    ax.set_xlim(-0.01, 1.0)
    ax.set_ylim(0, 0.85)
    ax.axis("off")
    fig.savefig(OUT / "41_workflow.png", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)


layout()
workflow()
print("ok")
