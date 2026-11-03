"""Per-model file layout and screen geometry.

Both models store *screen* samples: one byte = the vertical pixel position
of the trace.  Geometry was measured on real screenshots (docs/FORMAT.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    model: str
    file_size: int
    n_samples: int
    off_ch1: int
    off_ch2: int
    off_flags: int
    # extra byte fields: name -> offset (e.g. stored max/min per channel)
    extra: dict = field(default_factory=dict)
    count_field: tuple | None = None        # (offset, expected) uint32 big-endian
    # vertical: screen row = y_of_code0 - code
    code_min: int = 0                       # bottom edge of the grid
    code_max: int = 255                     # top edge of the grid
    code_center: float = 128
    codes_per_div: float = 25
    # horizontal: sample i is drawn in column x0 + i
    samples_per_div: float = 25
    divs_x: float = 12
    divs_y: float = 8
    screen_w: int = 320
    screen_h: int = 240
    x0: int = 9
    y_of_code0: int = 248
    trace_colors: dict = field(default_factory=dict)   # channel -> RGB565 (None = unknown yet)
    marker_x: tuple = (0, 8)
    marker_rows: tuple = (12, 229)
    marker_height: tuple = (7, 11)
    overlay_rows: tuple | None = None        # rows where measurement text may hide the trace
    bmp_sibling_dirs: tuple = ()            # other folders holding the screenshot
    verified: str = ""
    marker_colors: dict | None = None        # zero-marker colours if they differ from the trace
    bmp_only: bool = False                   # model saves only screenshots: waveform is digitised
    supported: bool = True                   # False = no samples studied yet
    data_ext: str = ".bin"                   # extension of the waveform data file
    grid_right: int = 0                      # last screen column of the grid (0 = x0 + n - 1)

    @property
    def format_name(self) -> str:
        if self.bmp_only:
            return (f"FNIRSI {self.model}: снимок экрана {self.screen_w}x{self.screen_h}, кривая оцифрована "
                    f"({self.n_samples} столбцов)")
        if self.data_ext == ".wav":
            return (f"FNIRSI {self.model} WAV ({self.file_size} байт, 2×{self.n_samples} отсчётов буфера uint16 "
                    "+ экранные точки + настройки)")
        return (f"FNIRSI {self.model} BIN ({self.file_size} байт, 2×{self.n_samples} экранных отсчётов uint8)")


P2C53T = Profile(
    key="2c53t", model="2C53T", file_size=607, n_samples=301,
    off_ch1=0, off_ch2=301, off_flags=602, count_field=(603, 301),
    code_min=28, code_max=228, code_center=128, codes_per_div=25,
    samples_per_div=25, divs_x=12, divs_y=8, screen_w=320, screen_h=240, x0=9, y_of_code0=248,
    trace_colors={"CH1": 0x7F40, "CH2": 0x02BF},
    marker_x=(0, 8), marker_rows=(12, 229), marker_height=(7, 11), overlay_rows=(186, 219),
    verified="9 пар BIN+BMP из репозитория RafaelDiasCampos",
)

# 2C53P: 461 samples + stored max/min byte per channel, flags at the end.
# Screen 480x272, grid 460x240 px, 50 px per horizontal division, 32 px per
# vertical division -> 9.2 x 7.5 divisions; centre line = code 120.
P2C53P = Profile(
    key="2c53p", model="2C53P", file_size=927, n_samples=461,
    off_ch1=0, off_ch2=463, off_flags=926,
    extra={"ch1_max": 461, "ch1_min": 462, "ch2_max": 924, "ch2_min": 925},
    code_min=0, code_max=240, code_center=120, codes_per_div=32,
    samples_per_div=50, divs_x=9.2, divs_y=7.5, screen_w=480, screen_h=272, x0=9, y_of_code0=270,
    trace_colors={"CH1": 0x9FBF, "CH2": None},
    marker_x=(0, 9), marker_rows=(31, 270), marker_height=(5, 9), overlay_rows=None,
    bmp_sibling_dirs=("Screenshot file",),
    verified="3 пары BIN+BMP с прибора пользователя (только CH1)",
)

# 2C23T saves no waveform data, only img_NN.bmp screenshots (320x240, top-down).
# Grid 300x200 px from column 10 / row 18, 25 px per division, centre row 118.
# The waveform is digitised from the trace pixels: one value per screen column.
P2C23T = Profile(
    key="2c23t", model="2C23T", file_size=0, n_samples=301,
    off_ch1=0, off_ch2=0, off_flags=0,
    code_min=28, code_max=228, code_center=128, codes_per_div=25,
    samples_per_div=25, divs_x=12, divs_y=8, screen_w=320, screen_h=240, x0=10, y_of_code0=246,
    trace_colors={"CH1": 0x0296, "CH2": 0x7DC0},
    marker_colors={"CH1": 0x039F, "CH2": 0x6D80},
    marker_x=(0, 9), marker_rows=(16, 221), marker_height=(5, 9), overlay_rows=(178, 214),
    bmp_only=True,
    verified="6 снимков с прибора пользователя (BIN прибор не сохраняет)",
)

# 1013D: N.wav (15000 bytes) with settings in the header + N.bmp 800x480 saved by a separate button.
# Buffer: 1500 uint16 per channel, 50 units per division (vertical and horizontal), 0 V = header value.
# Screen: 750 of the buffer points drawn from column 3, row = 448 - value.
P1013D = Profile(
    key="1013d", model="1013D", file_size=15000, n_samples=1500,
    off_ch1=1000, off_ch2=4000, off_flags=2,
    code_min=0, code_max=399, code_center=200, codes_per_div=50,
    samples_per_div=50, divs_x=30, divs_y=8, screen_w=800, screen_h=480, x0=3, y_of_code0=448,
    trace_colors={"CH1": 0xFFE0, "CH2": 0x07FF}, overlay_rows=None,
    data_ext=".wav", grid_right=725,
    verified="21 WAV + 23 BMP с прибора пользователя; формат по работам R. Tidey и W. Voigt",
)

PROFILES = (P2C53T, P2C53P, P2C23T, P1013D)
MODEL_CHOICES = {"auto": "Авто (по файлу)", "2c23t": "FNIRSI 2C23T", "2c53t": "FNIRSI 2C53T",
                 "2c53p": "FNIRSI 2C53P", "1013d": "FNIRSI 1013D"}


def profile_by_key(key: str) -> Profile | None:
    for p in PROFILES:
        if p.key == key:
            return p
    return None


def profile_for_size(size: int) -> Profile | None:
    for p in PROFILES:
        if p.file_size > 0 and size == p.file_size and not p.bmp_only and p.data_ext == ".bin":
            return p
    return None


def profile_for_screen(w: int, h: int, prefer: Profile | None = None) -> Profile | None:
    """Screen size alone is ambiguous for 320x240 (2C53T and 2C23T): ``prefer`` decides."""
    if prefer is not None and prefer.supported and (prefer.screen_w, prefer.screen_h) == (w, h):
        return prefer
    for p in PROFILES:
        if p.supported and (p.screen_w, p.screen_h) == (w, h):
            return p
    return None
