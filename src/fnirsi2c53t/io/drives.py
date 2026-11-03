"""Removable drives and folder listing (read-only)."""
from __future__ import annotations

import ctypes
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path

DRIVE_REMOVABLE = 2

FILTERS = {
    "supported": ("Все поддерживаемые (*.bin, *.wav, *.bmp)", (".bin", ".wav", ".bmp")),
    "bin": ("Осциллограммы (*.bin, *.wav)", (".bin", ".wav")),
    "images": ("Изображения (*.bmp, *.png, *.jpg)", (".bmp", ".png", ".jpg", ".jpeg")),
    "all": ("Все файлы", None),
}


@dataclass
class Drive:
    root: str          # "E:\\"
    label: str
    removable: bool
    size: int | None = None

    @property
    def title(self) -> str:
        lab = self.label or "без метки"
        size = f", {self.size / 1e6:.0f} МБ" if self.size else ""
        kind = "съёмный" if self.removable else "диск"
        return f"{self.root} — {lab} ({kind}{size})"


def _volume_label(root: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261, None, None,
                                                          None, fs, 261)
    except Exception:
        return ""
    return buf.value if ok else ""


def list_drives(removable_only: bool = True) -> list[Drive]:
    if sys.platform != "win32":
        return []
    out = []
    k32 = ctypes.windll.kernel32
    # do not show "insert a disk" error boxes for empty card readers
    old = k32.SetErrorMode(0x0001 | 0x8000)
    try:
        mask = k32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << i):
                continue
            root = f"{letter}:\\"
            t = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
            rem = t == DRIVE_REMOVABLE
            if removable_only and not rem:
                continue
            free, total = ctypes.c_ulonglong(), ctypes.c_ulonglong()
            ready = k32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root), None, ctypes.byref(total),
                                            ctypes.byref(free))
            if not ready:
                continue   # card reader without media
            out.append(Drive(root, _volume_label(root), rem, total.value or None))
    finally:
        k32.SetErrorMode(old)
    return out


@dataclass
class FileEntry:
    path: Path
    size: int
    mtime: float

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()


def list_files(folder: str | Path, filter_key: str = "supported") -> list[FileEntry]:
    """Files of one folder. Raises OSError with a readable message on failure."""
    exts = FILTERS[filter_key][1]
    out = []
    with os.scandir(folder) as it:
        for e in it:
            try:
                if not e.is_file():
                    continue
                if exts and Path(e.name).suffix.lower() not in exts:
                    continue
                st = e.stat()
                out.append(FileEntry(Path(e.path), st.st_size, st.st_mtime))
            except OSError:
                continue
    out.sort(key=lambda f: _natural_key(f.path.name))
    return out


def _natural_key(name: str):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def folder_has_captures(folder: str | Path, limit: int = 2000) -> bool:
    try:
        with os.scandir(folder) as it:
            for i, e in enumerate(it):
                if i > limit:
                    break
                if e.name.lower().endswith((".bin", ".wav")):
                    return True
    except OSError:
        pass
    return False


def guess_capture_folder(root: str | Path) -> Path:
    """Folder on the scope drive that holds the captures (root or one level down)."""
    root = Path(root)
    if folder_has_captures(root):
        return root
    try:
        for e in sorted(os.scandir(root), key=lambda e: e.name.lower()):
            if e.is_dir() and folder_has_captures(e.path):
                return Path(e.path)
    except OSError:
        pass
    return root
