"""Small, dependency-free helpers for syncing editable OCR coordinates.

These functions work only on form text. They do not alter the timestamp renderer,
font selection, image data, or the OCR model's response.
"""

import re

_COORD_PATTERN = re.compile(
    r"\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*,\s*"
    r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
)
_LABEL_PATTERN = re.compile(
    r"^(?:(?:baris\s*1|line\s*1)\s*[:.\-]\s*)?"
    r"(?:(?:koordinat|coordinates?)\s*[:：]\s*)?",
    flags=re.IGNORECASE,
)


def first_nonempty_line(text):
    """Get the coordinate-line candidate, without reformatting OCR's numbers."""
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def coordinate_from_ocr(text):
    """Return recognized coordinates exactly as read, or '' if not valid.

    Only decimal latitude, longitude are accepted; never silently guess a
    location from dates, addresses, or an OCR hallucination.
    """
    candidate = first_nonempty_line(text)
    if not candidate:
        return ""
    candidate = _LABEL_PATTERN.sub("", candidate).strip()
    match = _COORD_PATTERN.fullmatch(candidate)
    if not match:
        return ""
    lat, lon = map(float, match.groups())
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return ""
    return candidate


def normalize_ocr_lines(text):
    """Remove only accidental 'Baris 1:' / 'Koordinat:' labels from OCR.

    Numeric formatting, significant digits, and spacing remain unchanged.
    """
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if lines and coordinate_from_ocr(lines[0]):
        lines[0] = coordinate_from_ocr(lines[0])
    return "\n".join(lines)


def replace_first_line(text, new_coordinate):
    """Replace only the coordinate row; preserve location, time, extra rows."""
    lines = str(text or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        lines[0] = str(new_coordinate or "").strip()
    else:
        lines = [str(new_coordinate or "").strip()]
    return "\n".join(lines)
