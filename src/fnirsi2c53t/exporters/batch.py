"""Batch export of several files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..decoders.fnirsi_2c53t import DecodeError
from ..decoders.screen_digitizer import open_capture
from ..decoders.model import Measurement
from . import data_export, image_export

FORMATS = ["csv", "xlsx", "json", "png", "svg", "pdf"]


@dataclass
class BatchOptions:
    formats: tuple = ("csv",)
    sep: str = ","
    decimal: str = "."
    json_sidecar: bool = True
    xmode: str = "time"
    ymode: str = "volts"
    model: str = "auto"


def export_one(m: Measurement, out_dir: Path, opt: BatchOptions) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / m.path.stem
    files: list[Path] = []
    for fmt in opt.formats:
        if fmt == "csv":
            files += data_export.write_csv(m, stem.with_suffix(".csv"), opt.sep, opt.decimal,
                                           json_sidecar=opt.json_sidecar)
        elif fmt == "xlsx":
            files += data_export.write_xlsx(m, stem.with_suffix(".xlsx"))
        elif fmt == "json":
            files += data_export.write_json(m, stem.with_suffix(".json"))
        elif fmt in image_export.IMAGE_FORMATS:
            files.append(image_export.render_measurement(m, stem.with_suffix("." + fmt), opt.xmode, opt.ymode))
    return files


def export_many(items: list[Measurement | Path], out_dir: str | Path, opt: BatchOptions,
                progress: Callable[[int, int, str], bool] | None = None) -> list[tuple[str, str, list[Path]]]:
    """Returns (name, status, files) per input; never raises for a single bad file."""
    out_dir = Path(out_dir)
    report = []
    for i, it in enumerate(items):
        name = it.path.name if isinstance(it, Measurement) else Path(it).name
        if progress and progress(i, len(items), name) is False:
            report.append((name, "отменено", []))
            break
        try:
            m = it if isinstance(it, Measurement) else open_capture(it, opt.model)
            report.append((name, "OK", export_one(m, out_dir, opt)))
        except DecodeError as e:
            report.append((name, f"ошибка декодирования: {e}", []))
        except OSError as e:
            report.append((name, f"ошибка записи: {e.strerror or e}", []))
        except Exception as e:  # keep going on unexpected problems
            report.append((name, f"ошибка: {e}", []))
    return report
