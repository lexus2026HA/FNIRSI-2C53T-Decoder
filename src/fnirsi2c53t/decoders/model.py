"""Measurement data model.

Every scale parameter carries its origin (``source``) so the UI and the
exporters can tell confirmed values from values typed by the user or read
from the screen image.  Unknown values stay ``None`` - nothing is silently
replaced by a default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Where a parameter value came from.
SRC_UNKNOWN = "unknown"   # not present in the file, not provided
SRC_FILE = "file"         # read from the BIN file itself
SRC_BMP = "bmp"           # recognised on the matching BMP screenshot
SRC_USER = "user"         # typed in by the user

SOURCE_LABELS = {
    SRC_UNKNOWN: "неизвестно",
    SRC_FILE: "из файла данных",
    SRC_BMP: "распознано по BMP",
    SRC_USER: "введено вручную",
}


@dataclass
class Param:
    """A scale/setting value with its provenance."""

    value: Any = None
    unit: str = ""
    source: str = SRC_UNKNOWN
    note: str = ""

    @property
    def known(self) -> bool:
        return self.value is not None

    def set(self, value: Any, source: str, note: str = "") -> None:
        self.value = value
        self.source = source if value is not None else SRC_UNKNOWN
        self.note = note

    def clear(self) -> None:
        self.set(None, SRC_UNKNOWN)

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit, "source": self.source, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "Param":
        return cls(d.get("value"), d.get("unit", ""), d.get("source", SRC_UNKNOWN), d.get("note", ""))


@dataclass
class Channel:
    name: str                       # "CH1" / "CH2"
    enabled: bool                   # channel-enabled flag from the file
    raw: np.ndarray                 # uint8 screen codes, exactly as stored
    volts_per_div: Param = field(default_factory=lambda: Param(unit="V/div"))
    zero_code: Param = field(default_factory=lambda: Param(unit="code"))   # raw code of 0 V
    probe: Param = field(default_factory=lambda: Param(unit="x"))          # informational
    coupling: Param = field(default_factory=lambda: Param(unit=""))        # informational
    profile: Any = None                                                    # decoders.profiles.Profile

    @property
    def prof(self):
        if self.profile is None:
            from .profiles import P2C53T
            return P2C53T
        return self.profile

    # --- derived values -------------------------------------------------
    @property
    def has_volts(self) -> bool:
        return self.volts_per_div.known and self.zero_code.known

    def divisions(self) -> np.ndarray:
        """Vertical position in screen divisions relative to the screen centre."""
        p = self.prof
        return (self.raw.astype(np.float64) - p.code_center) / p.codes_per_div

    def volts(self) -> np.ndarray | None:
        """Voltage at the probe tip, or ``None`` if the scale is not known."""
        if not self.has_volts:
            return None
        return (self.raw.astype(np.float64) - float(self.zero_code.value)) / self.prof.codes_per_div * float(
            self.volts_per_div.value)

    def code_to_volts(self, code: float) -> float | None:
        if not self.has_volts:
            return None
        return (code - float(self.zero_code.value)) / self.prof.codes_per_div * float(self.volts_per_div.value)

    def volts_per_code(self) -> float | None:
        if not self.volts_per_div.known:
            return None
        return float(self.volts_per_div.value) / self.prof.codes_per_div


@dataclass
class Measurement:
    path: Path
    format_name: str
    decoder_version: str
    n_samples: int
    channels: list[Channel]
    time_per_div: Param = field(default_factory=lambda: Param(unit="s/div"))
    file_size: int = 0
    file_mtime: float = 0.0
    header: dict = field(default_factory=dict)        # raw metadata bytes, flags etc.
    warnings: list[str] = field(default_factory=list)  # decode-time warnings
    bmp_path: Path | None = None
    bmp_info: dict = field(default_factory=dict)       # results of the BMP analysis
    fft_result: dict | None = None                     # last FFT computed in the UI
    profile: Any = None                                # decoders.profiles.Profile

    @property
    def prof(self):
        if self.profile is None:
            from .profiles import P2C53T
            return P2C53T
        return self.profile

    # --- convenience -----------------------------------------------------
    @property
    def name(self) -> str:
        return self.path.name

    def channel(self, name: str) -> Channel | None:
        for ch in self.channels:
            if ch.name == name:
                return ch
        return None

    @property
    def enabled_channels(self) -> list[Channel]:
        return [c for c in self.channels if c.enabled]

    @property
    def has_time(self) -> bool:
        return self.time_per_div.known

    def sample_interval(self) -> float | None:
        """Seconds between neighbouring screen samples, if the timebase is known."""
        if not self.has_time:
            return None
        return float(self.time_per_div.value) / self.prof.samples_per_div

    def time_axis(self) -> np.ndarray | None:
        dt = self.sample_interval()
        if dt is None:
            return None
        t = np.arange(self.n_samples, dtype=np.float64) * dt
        # drop binary rounding noise (3.0000000000000004e-05 -> 3e-05): 12 significant digits of dt
        decimals = int(-np.floor(np.log10(dt))) + 11
        return np.round(t, decimals)

    def index_axis(self) -> np.ndarray:
        return np.arange(self.n_samples, dtype=np.int64)

    def reliability_warnings(self) -> list[str]:
        """All warnings about data trustworthiness: decode + scale status."""
        out = list(self.warnings)
        if not self.has_time:
            out.append("Временная шкала неизвестна: ось X — номер отсчёта.")
        elif self.time_per_div.source != SRC_FILE:
            out.append(f"Шкала времени {SOURCE_LABELS[self.time_per_div.source]} — не хранится в файле данных.")
        for ch in self.enabled_channels:
            if not ch.has_volts:
                missing = []
                if not ch.volts_per_div.known:
                    missing.append("В/дел")
                if not ch.zero_code.known:
                    missing.append("положение нуля")
                out.append(f"{ch.name}: напряжение не откалибровано (нет: {', '.join(missing)}).")
            else:
                srcs = {ch.volts_per_div.source, ch.zero_code.source}
                if srcs != {SRC_FILE}:
                    out.append(f"{ch.name}: шкала напряжения "
                               + ", ".join(sorted(SOURCE_LABELS[s] for s in srcs))
                               + " — не хранится в файле данных.")
        return out
