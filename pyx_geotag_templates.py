"""Optional geotag camera layout for AutoTimestamp Studio.

A wholly separate renderer: importing this module does not change the
existing Gemini OCR, AVHershey generator, batch logic, or converter.
"""
from functools import lru_cache
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TEMPLATE_CLASSIC = "classic"
TEMPLATE_CAMERA_GPS = "camera_gps"
TEMPLATE_OPTIONS = {
    "Original · Koordinat → Alamat → Waktu (bawah kiri)": TEMPLATE_CLASSIC,
    "Baru · Kamera GPS · Alamat → Waktu → Koordinat (atas kiri)": TEMPLATE_CAMERA_GPS,
}

_COORD_PATTERN = re.compile(
    r"^\s*([−-]?\d{1,2}(?:\.\d+)?)\s*[,;]\s*([−-]?\d{1,3}(?:\.\d+)?)\s*$"
)
_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)")


def camera_gps_lines(raw_text):
    """Address lines first, timestamp second, coordinates last.

    OCR/input order is deliberately flexible. User-entered address newlines
    remain separate, and coordinate digit precision remains unchanged.
    """
    raw_lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    address_lines, datetime_lines, coordinate_lines = [], [], []
    for line in raw_lines:
        simplified = line.replace('−', '-')
        if _COORD_PATTERN.fullmatch(simplified):
            coordinate_lines.append(line)
        elif _DATE_PATTERN.search(line):
            datetime_lines.append(_DATE_PATTERN.sub(
                lambda match: f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{match.group(3)}", line,
                count=1,
            ))
        else:
            address_lines.append(line)
    if not address_lines or not datetime_lines or not coordinate_lines:
        raise ValueError(
            "Template Kamera GPS membutuhkan alamat, tanggal/jam, dan koordinat. "
            "Periksa hasil OCR dan lengkapi teks sebelum Generate."
        )
    if len(datetime_lines) != 1 or len(coordinate_lines) != 1:
        raise ValueError("Gunakan tepat 1 baris tanggal/jam dan 1 baris koordinat.")
    return [*address_lines, datetime_lines[0], coordinate_lines[0]]


@lru_cache(maxsize=48)
def _font(size, bold):
    face = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(face, int(size))
    except OSError:
        # Pillow's bundled fallback avoids any additional network fetch.
        try:
            return ImageFont.load_default(size=int(size))
        except TypeError:
            return ImageFont.load_default()


def _line_width(draw, line, font, stroke_width=0):
    bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
    return bbox[2] - bbox[0]


def _wrap_address_lines(draw, lines, font, available_width, outline_px):
    """Wrap each original address line independently and preserve hard breaks."""
    result = []
    for line in lines:
        if _DATE_PATTERN.search(line) or _COORD_PATTERN.fullmatch(line.replace('−', '-')):
            result.append(line)
            continue
        words = line.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _line_width(draw, candidate, font, outline_px) <= available_width:
                current = candidate
            else:
                result.append(current)
                current = word
        result.append(current)
    return result


def render_camera_gps(
    image_cv,
    raw_timestamp_text,
    font_size_percent=5.0,
    font_size_mode="short_edge",
    fixed_font_size_px=80,
    font_size_px_override=None,
    preserve_locked_font_size=False,
    bold_enabled=False,
    bold_strength_percent=25,
):
    """Render the new top-left camera GPS style without calling old renderer.

    Returns the same `(PIL.Image, info)` interface as the classic renderer.
    Text is white with a charcoal stroke and a small shadow; source pixels
    elsewhere are untouched. Preview and export use this same function.
    """
    image = Image.fromarray(np.asarray(image_cv)).convert("RGB")
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError("Ukuran foto tidak valid.")
    source_lines = camera_gps_lines(raw_timestamp_text)
    percent = max(1.0, min(20.0, float(font_size_percent)))
    if font_size_px_override is not None:
        initial_size = max(1, int(round(float(font_size_px_override))))
        sizing_basis = "batch_lock_px"
    elif font_size_mode == "fixed_px":
        initial_size = max(1, int(round(float(fixed_font_size_px))))
        sizing_basis = "fixed_px"
    elif font_size_mode == "width":
        initial_size = max(1, round(width * percent / 100))
        sizing_basis = "width_percent"
    else:
        initial_size = max(1, round(min(width, height) * percent / 100))
        sizing_basis = "short_edge_percent"

    # Local calculations only: no persistent image buffers or OCR requests.
    x = max(8, round(width * 0.035))
    y = max(6, round(height * 0.055))
    right_margin = x
    max_width = max(20, width - x - right_margin)
    max_height = max(20, height - y - max(6, round(height * 0.04)))
    bold = bool(bold_enabled)
    font_size = initial_size
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    line_spacing = 0
    lines = source_lines
    auto_fit = False
    wrapped = False

    # A few predictable iterations; font cache bounds memory usage.
    for _ in range(32):
        font = _font(font_size, bold)
        stroke = max(1, round(font_size * 0.045))
        lines = _wrap_address_lines(measure, source_lines, font, max_width, stroke)
        wrapped = len(lines) != len(source_lines)
        line_spacing = max(1, round(font_size * 1.43))
        max_line = max(_line_width(measure, s, font, stroke) for s in lines)
        bbox0 = measure.textbbox((0, 0), "Ag", font=font, stroke_width=stroke)
        line_height = bbox0[3] - bbox0[1]
        required_height = line_height + (len(lines) - 1) * line_spacing + 3
        if max_line <= max_width and required_height <= max_height:
            break
        if font_size <= 8:
            break
        auto_fit = True
        ratio = min(max_width / max(1, max_line), max_height / max(1, required_height), 0.92)
        font_size = max(8, min(font_size - 1, int(font_size * ratio)))
    font = _font(font_size, bold)
    stroke = max(1, round(font_size * 0.045))
    draw = ImageDraw.Draw(image)
    for idx, line in enumerate(lines):
        yy = y + idx * line_spacing
        # Shadow first, subtle border and white fill afterward.
        draw.text((x + 1, yy + 2), line, font=font, fill=(38, 38, 38),
                  stroke_width=stroke + 1, stroke_fill=(38, 38, 38), anchor="lt")
        draw.text((x, yy), line, font=font, fill=(255, 255, 255),
                  stroke_width=stroke, stroke_fill=(75, 75, 75), anchor="lt")

    info = {
        "lines": lines,
        "line_count": len(lines),
        "font_size": font_size,
        "scale_ratio": font_size / 70,
        "outline_width": stroke,
        "letter_spacing": 0,
        "left_margin": x,
        "bottom_margin": max(0, height - y - len(lines) * line_spacing),
        "line_spacing": line_spacing,
        "auto_fit_applied": auto_fit,
        "font_size_percent": font_size_percent,
        "font_size_mode": font_size_mode,
        "fixed_font_size_px": fixed_font_size_px,
        "font_size_px_override": font_size_px_override,
        "preserve_locked_font_size": preserve_locked_font_size,
        "true_uniform_lock": bool(preserve_locked_font_size and font_size_px_override is not None),
        "wrap_applied": wrapped,
        "original_line_count": len(source_lines),
        "initial_font_size": initial_size,
        "sizing_basis": sizing_basis,
        "bold_enabled": bold_enabled,
        "font_name": "DejaVu Sans (Kamera GPS)",
        "bold_mode": "Bold" if bold else "Normal",
        "bold_strength_px": 0,
        "bold_strength_percent": bold_strength_percent if bold else 0,
        "first_baseline": y,
        "vertical_overflow_warning": False,
        "vertical_auto_fit_applied": auto_fit,
        "locked_size_adjusted_for_height": bool(auto_fit and preserve_locked_font_size),
        "template": TEMPLATE_CAMERA_GPS,
    }
    return image, info
