"""PNG / SVG / PDF plots rendered with matplotlib (no GUI needed)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..visualization.traces import DisplayItem, TraceSet, build_traces  # noqa: E402

IMAGE_FORMATS = {"png": "PNG", "svg": "SVG", "pdf": "PDF"}


@dataclass
class CursorState:
    a: float | None = None
    b: float | None = None
    y1: float | None = None
    y2: float | None = None
    labels: dict = field(default_factory=dict)   # name -> text


@dataclass
class PlotStyle:
    line_width: float = 1.2
    show_points: bool = False
    show_lines: bool = True
    grid: bool = True
    width_in: float = 11.0
    height_in: float = 5.0
    dpi: int = 150


def _unit_label(name: str, unit: str) -> str:
    return f"{name}, {unit}" if unit else name


def render(ts: TraceSet, path: str | Path, title: str = "", view: tuple | None = None,
           cursors: CursorState | None = None, style: PlotStyle | None = None,
           footer: list[str] | None = None) -> Path:
    style = style or PlotStyle()
    path = Path(path)
    fig, ax = plt.subplots(figsize=(style.width_in, style.height_in), dpi=style.dpi)
    for t in ts.traces:
        kw = dict(color=t.color, label=t.label, linewidth=style.line_width if style.show_lines else 0)
        if style.show_points:
            kw.update(marker="o", markersize=2.5)
        if not style.show_lines:
            kw["linestyle"] = "none"
        ax.plot(t.x, t.y, **kw)
    ax.set_xlabel(_unit_label(ts.xlabel, ts.xunit))
    ax.set_ylabel(_unit_label(ts.ylabel, ts.yunit))
    if style.grid:
        ax.grid(True, alpha=0.35)
        ax.minorticks_on()
        ax.grid(True, which="minor", alpha=0.12)
    if view:
        ax.set_xlim(view[0], view[1])
        ax.set_ylim(view[2], view[3])
    if cursors:
        for name, v, kw in (("A", cursors.a, dict(color="#d62728", ls="--")),
                            ("B", cursors.b, dict(color="#1f77b4", ls="--"))):
            if v is not None:
                ax.axvline(v, lw=1, **kw)
                ax.annotate(name, (v, 1.0), xycoords=("data", "axes fraction"), color=kw["color"],
                            ha="center", va="bottom", fontsize=9, annotation_clip=False)
        for name, v, kw in (("Y1", cursors.y1, dict(color="#9467bd", ls=":")),
                            ("Y2", cursors.y2, dict(color="#2ca02c", ls=":"))):
            if v is not None:
                ax.axhline(v, lw=1, **kw)
                ax.annotate(name, (1.0, v), xycoords=("axes fraction", "data"), color=kw["color"],
                            ha="left", va="center", fontsize=9, annotation_clip=False)
        if cursors.labels:
            txt = "\n".join(f"{k}: {v}" for k, v in cursors.labels.items())
            ax.text(0.01, 0.99, txt, transform=ax.transAxes, va="top", ha="left", fontsize=8,
                    family="monospace", bbox=dict(boxstyle="round", fc="white", ec="#999", alpha=0.85))
    if ts.traces:
        ax.legend(loc="upper right", fontsize=8)
    if title:
        ax.set_title(title, fontsize=10)
    notes = list(ts.notes) + list(footer or [])
    if notes:
        fig.text(0.01, 0.005, "\n".join(notes), fontsize=7, color="#a33", va="bottom", ha="left")
        fig.tight_layout(rect=(0, 0.03 * min(len(notes), 6), 1, 1))
    else:
        fig.tight_layout()
    fmt = path.suffix.lower().lstrip(".")
    fig.savefig(path, format=fmt)
    plt.close(fig)
    return path


def render_measurement(m, path, xmode="time", ymode="volts", style=None) -> Path:
    """Default plot of one measurement (used by batch export)."""
    ts = build_traces([DisplayItem(m)], xmode, ymode)
    warn = [w for w in m.reliability_warnings() if w not in ts.notes]
    return render(ts, path, title=m.path.name, style=style, footer=warn[:4])
