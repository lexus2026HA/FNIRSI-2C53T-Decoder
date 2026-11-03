"""Analysis sessions saved as documented JSON (schema fnirsi2c53t-session/1).

Only paths are stored, never copies of the measurements.  User-entered
calibration is stored per file; values that came from the BMP are
re-derived when the session is opened.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from . import __version__
from .decoders.fnirsi_2c53t import DecodeError
from .decoders.screen_digitizer import open_capture
from .decoders.model import Param, SRC_USER
from .visualization.traces import DisplayItem

SCHEMA = "fnirsi2c53t-session/1"


def _params_of(m):
    d = {"time_per_div": m.time_per_div.to_dict()}
    for ch in m.channels:
        for k in ("volts_per_div", "zero_code", "probe", "coupling"):
            d[f"{ch.name}.{k}"] = getattr(ch, k).to_dict()
    return d


def save_session(path: str | Path, items: list[DisplayItem], view: dict, cursors: dict,
                 settings: dict, measurements: dict | None = None, active: int = 0) -> Path:
    data = {
        "schema": SCHEMA,
        "app_version": __version__,
        "saved_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "active": active,
        "files": [{
            "path": str(it.m.path),
            "model": it.m.prof.key,
            "shown": it.shown,
            "visible": it.visible,
            "colors": it.colors,
            "x_shift_samples": it.x_shift_samples,
            "y_shift_div": it.y_shift_div,
            "params": _params_of(it.m),
            "warnings": it.m.reliability_warnings(),
        } for it in items],
        "view": view,
        "cursors": cursors,
        "settings": settings,
        "measurements": measurements or {},
    }
    path = Path(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_session(path: str | Path, apply_bmp: bool = True) -> tuple[list[DisplayItem], dict, list[str]]:
    """Returns (items, raw session dict, problems)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("Это не файл сессии FNIRSI-2C53T-Decoder.")
    items, problems = [], []
    for f in data.get("files", []):
        p = Path(f["path"])
        try:
            m = open_capture(p, f.get("model", "auto"), apply_bmp_scales=apply_bmp)
        except DecodeError as e:
            problems.append(f"{p}: {e}")
            continue
        # restore user-entered values (they win over BMP)
        for key, pd in f.get("params", {}).items():
            if pd.get("source") != SRC_USER:
                continue
            if key == "time_per_div":
                m.time_per_div = Param.from_dict(pd)
            else:
                chn, attr = key.split(".", 1)
                ch = m.channel(chn)
                if ch is not None:
                    setattr(ch, attr, Param.from_dict(pd))
        it = DisplayItem(m, visible=f.get("visible", {"CH1": True, "CH2": True}),
                         colors=f.get("colors") or DisplayItem(m).colors,
                         x_shift_samples=f.get("x_shift_samples", 0.0),
                         y_shift_div=f.get("y_shift_div", 0.0), shown=f.get("shown", True))
        items.append(it)
    return items, data, problems
