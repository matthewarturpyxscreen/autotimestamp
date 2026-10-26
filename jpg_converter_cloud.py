"""Disk-backed Cloud output adapter for the existing JPG encoder.

Only the *storage strategy* differs from jpg_converter.convert_files:
- original JPEG encoding, frame decoding, names, limits and failure policy are reused;
- completed JPEGs live in a temporary ZIP, not in Streamlit session-state bytes;
- .data provides backward-compatible, on-demand bytes for the selected preview/download.

This module deliberately does not import OCR, timestamp, or batch engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import zipfile
from typing import Callable, Iterable

from jpg_converter import (
    JPGSettings, ConversionError, MAX_FILES, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
    MAX_PAGES, _iter_frames, image_to_jpeg, safe_basename, _unique_name,
)


@dataclass
class CloudJPGItem:
    name: str
    width: int
    height: int
    source: str
    page: int
    byte_size: int
    _zip_file: object = field(repr=False, compare=False)

    @property
    def data(self) -> bytes:
        """One JPEG on demand, never all 250 images at once."""
        if getattr(self._zip_file, "closed", True):
            raise OSError("File ZIP sementara sudah ditutup. Konversi ulang untuk mengunduh.")
        with zipfile.ZipFile(self._zip_file, "r") as archive:
            return archive.read(self.name)


@dataclass
class CloudConversionReport:
    items: list[CloudJPGItem] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    zip_bytes: bytes = b""  # compatibility with the existing UI
    zip_file: object | None = field(default=None, repr=False)
    input_count: int = 0
    input_bytes: int = 0
    _jpg_total: int = 0

    @property
    def jpg_bytes(self) -> int:
        # IMPORTANT: never load every JPG to calculate this sum.
        return self._jpg_total

    def close(self) -> None:
        if self.zip_file is not None and not self.zip_file.closed:
            self.zip_file.close()


def _source_bytes(payload: object) -> bytes:
    """Read one uploaded file at a time, not the whole selection."""
    if isinstance(payload, bytes):
        return payload
    if hasattr(payload, 'getvalue'):
        data = payload.getvalue()
    elif hasattr(payload, 'read'):
        if hasattr(payload, 'seek'):
            payload.seek(0)
        data = payload.read()
    else:
        raise ConversionError("Sumber file tidak bisa dibaca.")
    if not isinstance(data, bytes):
        raise ConversionError("Format data file tidak didukung.")
    return data


def convert_files_cloud(
    uploads: Iterable[tuple[str, object]],
    settings: JPGSettings,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> CloudConversionReport:
    """Cloud-safe storage of IDENTICAL JPEGs; no changes to encoding/render engines.

    Per-document frames are staged on local disk to retain the existing
    all-or-nothing behavior on a bad/corrupted page. The aggregate ZIP is
    SpooledTemporaryFile(max_size=8 MiB), and metadata stays in RAM.
    """
    settings.validate()
    uploads = list(uploads)  # Only filenames and UploadedFile references, not byte payload copies.
    if len(uploads) > MAX_FILES:
        raise ConversionError(f"Maksimum {MAX_FILES} file per batch.")
    report = CloudConversionReport(input_count=len(uploads))
    report.zip_file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    used_names: set[str] = set()
    try:
        with zipfile.ZipFile(report.zip_file, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for index, (name, uploaded) in enumerate(uploads):
                if on_progress:
                    on_progress(index, len(uploads), name)
                try:
                    payload = _source_bytes(uploaded)
                except (ValueError, OSError, ConversionError) as exc:
                    report.errors.append((name, str(exc)))
                    continue
                report.input_bytes += len(payload)
                if not payload:
                    report.errors.append((name, "File kosong."))
                    continue
                if len(payload) > MAX_INPUT_BYTES:
                    report.errors.append((name, "Ukuran file melebihi 100 MB."))
                    continue
                # Failed pages must not produce partly successful documents.
                try:
                    with tempfile.TemporaryDirectory(prefix='pyx-jpg-stage-') as temp_dir:
                        staged = []
                        total_local_bytes = 0
                        for n, frame in _iter_frames(payload, name, settings):
                            if len(report.items) + len(staged) >= MAX_PAGES:
                                raise ConversionError(f"Total hasil melebihi {MAX_PAGES} JPG per batch.")
                            try:
                                jpg, (width, height) = image_to_jpeg(frame, settings)
                                if report._jpg_total + total_local_bytes + len(jpg) > MAX_OUTPUT_BYTES:
                                    raise ConversionError("Total hasil melebihi batas 400 MB. Gunakan kualitas/resolusi lebih rendah.")
                                temp_path = Path(temp_dir) / f"{len(staged):04d}.jpg"
                                temp_path.write_bytes(jpg)
                                staged.append((n, width, height, len(jpg), temp_path))
                                total_local_bytes += len(jpg)
                            finally:
                                frame.close()
                        if not staged:
                            raise ConversionError("Tidak ada halaman atau foto yang dapat dikonversi.")
                        is_pdf = Path(name).suffix.lower() == '.pdf'
                        basename = safe_basename(name)
                        for n, width, height, byte_count, temp_path in staged:
                            if is_pdf:
                                proposed = f"{basename}_page_{n:03d}.jpg"
                            elif len(staged) > 1:
                                proposed = f"{basename}_frame_{n:03d}.jpg"
                            else:
                                proposed = f"{basename}.jpg"
                            output_name = _unique_name(proposed, used_names)
                            # At most one full JPG in memory at any time.
                            archive.writestr(output_name, temp_path.read_bytes())
                            report.items.append(CloudJPGItem(
                                output_name, width, height, name, n, byte_count, report.zip_file
                            ))
                            report._jpg_total += byte_count
                except (ConversionError, OSError, ValueError) as exc:
                    report.errors.append((name, str(exc)))
                finally:
                    del payload
        if on_progress:
            on_progress(len(uploads), len(uploads), "Selesai")
        report.zip_file.seek(0)
        return report
    except Exception:
        report.close()
        raise
