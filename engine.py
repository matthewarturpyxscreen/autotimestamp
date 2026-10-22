"""Mesin render timestamp gaya GPS Map Camera.

Modul ini TIDAK bergantung pada Streamlit maupun OpenCV, jadi bisa dites
terpisah. Logika tampilan (font AVHershey Simplex Medium, outline, spasi,
auto-fit, uniform-lock, bold) sama dengan versi sebelumnya; yang berubah
hanya performanya:

* lebar glyph di-cache (dulu dihitung ulang tiap karakter, tiap iterasi),
* tidak ada konversi RGB<->BGR/numpy; semua langsung di PIL,
* font di-cache per thread sehingga aman dipakai batch paralel,
* font diunduh sebagai 1 file (bukan clone repo penuh).
"""

from __future__ import annotations

import glob
import io
import os
import re
import subprocess
import threading
import urllib.request
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps

# ============================================================
# KONFIGURASI (identik dengan versi sebelumnya)
# ============================================================

REFERENCE_FONT_SIZE = 70
DEFAULT_FONT_SIZE_PERCENT = 5.0
MIN_FONT_SIZE_PX = 14

TEXT_COLOR = (255, 255, 255)
OUTLINE_COLOR = (0, 0, 0)

REFERENCE_OUTLINE_WIDTH = 2
REFERENCE_LETTER_SPACING = -1
SPACE_SCALE = 0.75

REFERENCE_LEFT_MARGIN = 32
REFERENCE_BOTTOM_MARGIN = 88
REFERENCE_LINE_SPACING = 78

TEXT_ANCHOR = "ls"
FONT_NAME = "AVHershey Simplex Medium"

SIZE_MODES = ("short_edge", "width", "fixed_px")

# ============================================================
# FONT
# ============================================================

FONT_DIR = "Hershey_font_TTF"
FONT_FILE = "AVHersheySimplexMedium.ttf"
FONT_RAW_URL = (
    "https://raw.githubusercontent.com/yangcht/Hershey_font_TTF/main/ttf/" + FONT_FILE
)
FONT_REPO_URL = "https://github.com/yangcht/Hershey_font_TTF.git"


def _find_font_file() -> str | None:
    candidates = glob.glob(os.path.join(FONT_DIR, "**", "*Simplex*Medium*.ttf"), recursive=True)
    # Hindari varian Italic yang namanya juga mengandung "Simplex...Medium".
    candidates = [p for p in candidates if "italic" not in os.path.basename(p).lower()]
    return sorted(candidates)[0] if candidates else None


@lru_cache(maxsize=1)
def get_font_path() -> str:
    """Path font. Unduh 1 file TTF; kalau gagal, fallback ke git clone dangkal."""
    found = _find_font_file()
    if found:
        return found

    try:
        target_dir = os.path.join(FONT_DIR, "ttf")
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, FONT_FILE)
        request = urllib.request.Request(FONT_RAW_URL, headers={"User-Agent": "AutoTimestamp"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()
        if len(data) < 1000:
            raise ValueError("file font tidak valid")
        with open(target, "wb") as handle:
            handle.write(data)
    except Exception:
        try:
            subprocess.run(
                ["git", "clone", "-q", "--depth", "1", FONT_REPO_URL, FONT_DIR],
                check=True,
                timeout=90,
            )
        except Exception:
            pass

    found = _find_font_file()
    if not found:
        raise RuntimeError(
            f"Font {FONT_NAME} tidak ditemukan dan gagal diunduh. "
            f"Pastikan server bisa mengakses github.com, atau letakkan {FONT_FILE} di folder {FONT_DIR}/ttf/."
        )
    return found


_tls = threading.local()


def get_font(size: int) -> ImageFont.FreeTypeFont:
    """FreeType face tidak thread-safe, jadi cache-nya per thread."""
    fonts = getattr(_tls, "fonts", None)
    if fonts is None:
        fonts = _tls.fonts = {}
    font = fonts.get(size)
    if font is None:
        font = fonts[size] = ImageFont.truetype(get_font_path(), size)
    return font


@lru_cache(maxsize=8192)
def glyph_width(size: int, char: str) -> float:
    return get_font(size).getlength(char)


# ============================================================
# NORMALISASI & PARSING TEKS
# ============================================================

_WS = re.compile(r"\s+")


def _normalize_commas(text: str) -> str:
    text = _WS.sub(" ", text.strip())
    text = re.sub(r"\s*,", ",", text)
    return re.sub(r",\s*", ",  ", text)


def normalize_datetime(text: str) -> str:
    text = _WS.sub(" ", text.strip())
    match = re.search(r"\b(\d{1,2}:\d{2}:\d{2})\b", text)
    if not match:
        return text

    before = text[: match.start()].strip()
    after = text[match.end():].strip()
    after = re.sub(r"^\s*WIB\s*$", "WIB", after, flags=re.IGNORECASE)
    if after:
        return f"{before} {match.group(1)}  {after}"
    return f"{before} {match.group(1)}"


def parse_timestamp(raw_text: str) -> list[str]:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Input minimal harus terdiri dari 1 baris.")

    result = []
    for index, line in enumerate(lines):
        if index in (0, 1):
            result.append(_normalize_commas(line))
        elif index == 2:
            result.append(normalize_datetime(line))
        else:
            result.append(_WS.sub(" ", line).strip())
    return result


# ============================================================
# UKUR / WRAP / GAMBAR
# ============================================================


def line_advances(text: str, size: int, letter_spacing: float) -> list[float]:
    space = glyph_width(size, " ") * SPACE_SCALE + letter_spacing
    return [space if ch == " " else glyph_width(size, ch) + letter_spacing for ch in text]


def measure_line_width(text: str, size: int, letter_spacing: float) -> float:
    return sum(line_advances(text, size, letter_spacing))


def wrap_line_to_width(text: str, size: int, letter_spacing: float, max_width: float) -> list[str]:
    """Bungkus per kata tanpa mengubah ukuran font (dipakai uniform-lock)."""
    text = str(text or "").strip()
    if not text:
        return [""]
    if measure_line_width(text, size, letter_spacing) <= max_width:
        return [text]

    words = text.split()
    if len(words) <= 1:
        return [text]

    wrapped, current = [], words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if measure_line_width(candidate, size, letter_spacing) <= max_width:
            current = candidate
        else:
            wrapped.append(current)
            current = word
    wrapped.append(current)
    return wrapped


def _draw_line(draw, text, x, baseline, font, size, outline_width, letter_spacing, bold_px):
    current_x = float(x)
    for char, advance in zip(text, line_advances(text, size, letter_spacing)):
        if char != " ":
            position = (round(current_x), round(baseline))
            if bold_px:
                # Pass 1: outline hitam di luar glyph yang sudah ditebalkan.
                draw.text(position, char, font=font, fill=TEXT_COLOR,
                          stroke_width=outline_width + bold_px,
                          stroke_fill=OUTLINE_COLOR, anchor=TEXT_ANCHOR)
                # Pass 2: tebalkan badan huruf dengan stroke putih.
                draw.text(position, char, font=font, fill=TEXT_COLOR,
                          stroke_width=bold_px,
                          stroke_fill=TEXT_COLOR, anchor=TEXT_ANCHOR)
            else:
                draw.text(position, char, font=font, fill=TEXT_COLOR,
                          stroke_width=outline_width,
                          stroke_fill=OUTLINE_COLOR, anchor=TEXT_ANCHOR)
        current_x += advance


def render_timestamp(
    image: Image.Image,
    raw_text: str,
    *,
    size_mode: str = "short_edge",
    percent: float = DEFAULT_FONT_SIZE_PERCENT,
    fixed_px: int = 80,
    locked_px: int | None = None,
    bold: bool = False,
    bold_strength: int = 25,
    min_font_px: int = MIN_FONT_SIZE_PX,
    inplace: bool = False,
):
    """Gambar overlay timestamp. Return (PIL.Image, info dict).

    locked_px != None  -> mode True-Uniform: ukuran px dikunci, baris panjang
                          dibungkus (tidak dikecilkan).
    locked_px is None  -> auto-fit: font dikecilkan sampai semua baris muat.
    """
    lines = parse_timestamp(raw_text)
    canvas = image if inplace else image.copy()
    width, height = canvas.size

    if locked_px is not None:
        initial = max(1, int(round(locked_px)))
        basis = "batch_lock_px"
    elif size_mode == "fixed_px":
        initial = max(1, int(round(fixed_px)))
        basis = "fixed_px"
    elif size_mode == "width":
        initial = max(1, round(width * (percent / 100)))
        basis = "width_percent"
    else:
        initial = max(1, round(min(width, height) * (percent / 100)))
        basis = "short_edge_percent"

    font_size = initial
    original_line_count = len(lines)
    wrap_applied = False

    def metrics(size):
        ratio = size / REFERENCE_FONT_SIZE
        return ratio, round(REFERENCE_LEFT_MARGIN * ratio), REFERENCE_LETTER_SPACING * ratio

    if locked_px is not None:
        scale_ratio, left_margin, letter_spacing = metrics(font_size)
        available = max(1, width - 2 * left_margin)
        wrapped = []
        for line in lines:
            wrapped.extend(wrap_line_to_width(line, font_size, letter_spacing, available))
        lines = wrapped
        wrap_applied = len(lines) != original_line_count
        auto_fit_applied = False
    else:
        for _ in range(6):
            scale_ratio, left_margin, letter_spacing = metrics(font_size)
            widest = max(measure_line_width(line, font_size, letter_spacing) for line in lines)
            available = width - 2 * left_margin
            if widest <= available or font_size <= min_font_px:
                break
            font_size = max(min_font_px, int(font_size * (available / widest) * 0.97))
        auto_fit_applied = font_size < initial

    font = get_font(font_size)
    outline_width = max(1, round(REFERENCE_OUTLINE_WIDTH * scale_ratio))
    bottom_margin = round(REFERENCE_BOTTOM_MARGIN * scale_ratio)
    line_spacing = round(REFERENCE_LINE_SPACING * scale_ratio)

    bold_strength = max(1, min(100, int(bold_strength)))
    bold_ratio = 0.005 + (bold_strength / 100.0) * 0.020
    bold_px = max(1, round(font_size * bold_ratio)) if bold else 0

    last_baseline = height - bottom_margin
    first_baseline = last_baseline - line_spacing * (len(lines) - 1)

    draw = ImageDraw.Draw(canvas)
    for index, line in enumerate(lines):
        _draw_line(draw, line, left_margin, first_baseline + line_spacing * index,
                   font, font_size, outline_width, letter_spacing, bold_px)

    info = {
        "lines": lines,
        "line_count": len(lines),
        "original_line_count": original_line_count,
        "font_size": font_size,
        "initial_font_size": initial,
        "sizing_basis": basis,
        "scale_ratio": scale_ratio,
        "outline_width": outline_width,
        "letter_spacing": letter_spacing,
        "left_margin": left_margin,
        "bottom_margin": bottom_margin,
        "line_spacing": line_spacing,
        "auto_fit_applied": auto_fit_applied,
        "wrap_applied": wrap_applied,
        "true_uniform_lock": locked_px is not None,
        "bold_enabled": bool(bold),
        "bold_strength_percent": bold_strength if bold else 0,
        "bold_strength_px": bold_px,
        "font_name": FONT_NAME,
        "first_baseline": first_baseline,
        "vertical_overflow_warning": first_baseline < font_size,
    }
    return canvas, info


# ============================================================
# LOAD / ENCODE GAMBAR
# ============================================================

_ROTATED_ORIENTATIONS = {5, 6, 7, 8}


def load_image(data: bytes) -> Image.Image:
    """Buka foto, terapkan orientasi EXIF ke pixel, kembalikan RGB."""
    with Image.open(io.BytesIO(data)) as raw:
        return ImageOps.exif_transpose(raw).convert("RGB")


def oriented_size(data: bytes) -> tuple[int, int]:
    """Ukuran (w, h) setelah orientasi EXIF, TANPA decode piksel (cepat)."""
    with Image.open(io.BytesIO(data)) as raw:
        width, height = raw.size
        try:
            orientation = raw.getexif().get(0x0112, 1)
        except Exception:
            orientation = 1
    return (height, width) if orientation in _ROTATED_ORIENTATIONS else (width, height)


def load_preview_image(data: bytes, max_edge: int = 1280):
    """Versi kecil foto untuk preview. Return (image, scale terhadap aslinya)."""
    full_w, _ = oriented_size(data)
    with Image.open(io.BytesIO(data)) as raw:
        raw.draft("RGB", (max_edge, max_edge))  # decode JPEG langsung diperkecil
        image = ImageOps.exif_transpose(raw).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return image, image.width / max(1, full_w)


def encode_image(image: Image.Image, filename: str, jpeg_quality: int = 95):
    """Encode ke bytes sesuai ekstensi nama file. Return (bytes, mime)."""
    ext = os.path.splitext(filename)[1].lower()
    buffer = io.BytesIO()
    if ext == ".png":
        image.save(buffer, format="PNG", compress_level=4)
        return buffer.getvalue(), "image/png"
    image.save(buffer, format="JPEG", quality=jpeg_quality)
    return buffer.getvalue(), "image/jpeg"
