"""Presentation-only OCR layout bridge for AutoTimestamp (no renderer changes).

The legacy OCR model, timestamp parser, AVHershey font and image generators stay
byte-for-byte unchanged. New and old OCR text layouts are routed at the UI edge.
This module is dependency-free and does not call Gemini or decode images.
"""
import hashlib
import re
from ocr_fields import coordinate_from_ocr as _legacy_coordinate

_DATE_PATTERN = re.compile(r"(?<!\d)\d{1,2}[/-]\d{1,2}[/-]\d{4}(?!\d)")


def coordinate_line_index(text):
    """Locate the sole valid GPS line anywhere; reject ambiguous duplicates."""
    valid = [index for index, row in enumerate(str(text or "").splitlines())
             if _legacy_coordinate(row)]
    return valid[0] if len(valid) == 1 else None


def coordinate_anywhere(text):
    """Return the literal GPS digits from any row, with no rounding or guessing."""
    rows = str(text or "").splitlines()
    index = coordinate_line_index(text)
    return _legacy_coordinate(rows[index]) if index is not None else ""


def normalize_layout_ocr(text):
    """Populate textbox with each OCR-visible line unchanged and in order.

    Like the legacy helper, trim surrounding whitespace and blank OCR rows.
    Unlike the legacy helper, an optional Gemini 'Koordinat:' label on the
    LAST line is also handled without moving any line or merging addresses.
    """
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    index = coordinate_line_index("\n".join(lines))
    if index is not None:
        lines[index] = _legacy_coordinate(lines[index])
    return "\n".join(lines)


def replace_coordinate_line(text, new_coordinate):
    """Replace only the GPS row, preserving the remaining line breaks exactly."""
    source = str(text or "")
    index = coordinate_line_index(source)
    if index is not None:
        rows = source.splitlines(keepends=True)
        old = rows[index]
        if old.endswith("\r\n"):
            ending = "\r\n"
        elif old.endswith(("\n", "\r")):
            ending = old[-1]
        else:
            ending = ""
        rows[index] = str(new_coordinate or "").strip() + ending
        return "".join(rows)
    coordinate = str(new_coordinate or "").strip()
    if not coordinate:
        return source
    if not source.strip():
        return coordinate
    # A new-layout OCR missing GPS must not lose its first address line.
    if _DATE_PATTERN.search(source.splitlines()[-1]):
        return source.rstrip("\r\n") + "\n" + coordinate
    return coordinate + "\n" + source


def parse_reference_auto(raw_text, legacy_parser):
    """Make the legacy batch parser understand last-row GPS without editing it.

    Original parser still processes classic coordinate-first text verbatim.
    For address-first text, only a *temporary parser copy* is reordered; the
    textbox and generated timestamp retain the exact original row sequence.
    """
    rows = [row.strip() for row in str(raw_text or "").splitlines() if row.strip()]
    if len(rows) < 2:
        return legacy_parser(raw_text)
    index = coordinate_line_index("\n".join(rows))
    if index is None:
        raise ValueError("Tidak ditemukan tepat satu koordinat latitude, longitude yang valid.")
    if index == 0:
        return legacy_parser(raw_text)
    parser_copy = "\n".join([rows[index], *[row for i,row in enumerate(rows) if i != index]])
    return legacy_parser(parser_copy)


def build_batch_timestamp(reference_text, new_coordinate, new_datetime):
    """Replace generated GPS/date at their source positions for preview & ZIP.

    N address rows are allowed; output remains old- or new-layout as entered.
    If the reference lacks date, insert near the coordinate in the same order.
    """
    rows = [row.strip() for row in str(reference_text or "").splitlines() if row.strip()]
    index = coordinate_line_index("\n".join(rows))
    if index is None:
        raise ValueError("Tidak ditemukan tepat satu koordinat latitude, longitude yang valid.")
    dates = [i for i, row in enumerate(rows) if _DATE_PATTERN.search(row)]
    if len(dates) > 1:
        raise ValueError("Ditemukan lebih dari satu baris tanggal/jam. Sisakan satu saja.")
    rows[index] = str(new_coordinate)
    if dates:
        rows[dates[0]] = str(new_datetime)
    elif index == len(rows) - 1 and index > 0:
        rows.insert(index, str(new_datetime))
    else:
        rows.append(str(new_datetime))
    return "\n".join(rows)


def screenshot_fingerprint(image, upload_bytes=None):
    """Fast OCR source identity without PNG re-encoding on Streamlit reruns.

    Identity only: OCR upload still uses the existing untouched Gemini path.
    An uploaded file is hashed as original bytes; pasted images use raw RGB
    bytes and dimensions to avoid an expensive PNG compression per rerun.
    """
    digest = hashlib.md5(usedforsecurity=False)
    if upload_bytes is not None:
        digest.update(upload_bytes)
    else:
        digest.update(str(image.size).encode("ascii"))
        digest.update(str(image.mode).encode("ascii"))
        digest.update(image.tobytes())
    return digest.hexdigest()
