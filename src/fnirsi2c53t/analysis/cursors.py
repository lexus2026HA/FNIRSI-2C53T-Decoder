"""Cursor arithmetic, independent from the GUI."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def nearest_index(x: float, xaxis: np.ndarray) -> int:
    """Index of the sample whose X coordinate is closest to ``x`` (clamped)."""
    if xaxis.size == 0:
        return 0
    if xaxis.size == 1:
        return 0
    step = (xaxis[-1] - xaxis[0]) / (xaxis.size - 1)
    if step > 0:
        i = int(round((x - xaxis[0]) / step))
    else:
        i = int(np.argmin(np.abs(xaxis - x)))
    return max(0, min(xaxis.size - 1, i))


def snap(x: float, xaxis: np.ndarray) -> float:
    return float(xaxis[nearest_index(x, xaxis)])


@dataclass
class VCursorResult:
    a: float
    b: float
    ia: int
    ib: int

    @property
    def dx(self) -> float:
        return self.b - self.a

    @property
    def di(self) -> int:
        return self.ib - self.ia

    def inv_dx(self) -> float | None:
        return None if self.dx == 0 else 1.0 / abs(self.dx)


def vcursors(a: float, b: float, xaxis: np.ndarray) -> VCursorResult:
    return VCursorResult(a, b, nearest_index(a, xaxis), nearest_index(b, xaxis))


def hdelta(y1: float, y2: float) -> float:
    return y2 - y1
