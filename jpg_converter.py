"""Standalone JPG conversion pipeline for AutoTimestamp.

This module deliberately imports no AutoTimestamp OCR/render/batch code.
Original uploads are read-only. Output JPEGs always use .jpg and RGB pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Optional
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

RASTER_EXT = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".webp", ".bmp", ".dib", ".tif", ".tiff", ".gif", ".ico", ".ppm", ".pgm", ".pbm", ".psd", ".tga", ".pcx", ".jp2", ".j2k", ".avif", ".heic", ".heif"}
PDF_EXT = {".pdf"}
VECTOR_EXT = {".svg"}
OFFICE_EXT = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".ods", ".odp"}
SUPPORTED_EXT = RASTER_EXT | PDF_EXT | VECTOR_EXT | OFFICE_EXT
MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_FILES = 80
MAX_PAGES = 250
MAX_PIXELS = 40_000_000
MAX_OUTPUT_BYTES = 400 * 1024 * 1024


@dataclass(frozen=True)
class JPGSettings:
    quality: int = 88
    dpi: int = 160
    max_side: int = 0               # 0 = native size, within pixel-safety limit
    background: str = "#FFFFFF"
    all_frames: bool = True

    def validate(self) -> None:
        if not 50 <= self.quality <= 98:
            raise ValueError("Kualitas JPG harus antara 50–98.")
        if not 72 <= self.dpi <= 300:
            raise ValueError("DPI PDF harus antara 72–300.")
        if self.max_side not in (0, 1280, 1920, 2560, 4096):
            raise ValueError("Pilihan resolusi keluaran tidak dikenal.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background):
            raise ValueError("Warna latar tidak valid.")


@dataclass
class JPGItem:
    name: str
    data: bytes
    width: int
    height: int
    source: str
    page: int


@dataclass
class ConversionReport:
    items: list[JPGItem] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    zip_bytes: bytes = b""
    zip_file: Optional[object] = field(default=None, repr=False)  # UI-only disk-spooled ZIP option
    input_count: int = 0
    input_bytes: int = 0

    @property
    def jpg_bytes(self) -> int:
        return sum(len(x.data) for x in self.items)


class ConversionError(ValueError):
    pass


def _register_heif() -> bool:
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        return True
    except ImportError:
        return False


def available_backends() -> dict[str, bool]:
    try:
        import pypdfium2  # noqa: F401
        pdf = True
    except ImportError:
        pdf = False
    try:
        import cairosvg  # noqa: F401
        svg = True
    except (ImportError, OSError):
        svg = False
    return {
        "pdf": pdf,
        "svg": svg,
        "heic": _register_heif(),
        "office": bool(shutil.which("libreoffice") or shutil.which("soffice")),
    }


def safe_basename(filename: str) -> str:
    """Strip paths/control chars to avoid output ZIP path traversal."""
    name = str(filename).replace("\\", "/").split("/")[-1]
    stem = Path(name).stem
    stem = re.sub(r"[^\w.() -]", "_", stem, flags=re.UNICODE).strip(" ._")
    return (stem[:88] or "foto")


def safe_filename(filename: str) -> str:
    return (safe_basename(filename) + Path(filename).suffix.lower())[:110]


def _unique_name(proposed: str, used: set[str]) -> str:
    stem, ext = os.path.splitext(proposed)
    chosen = proposed
    n = 2
    while chosen.casefold() in used:
        chosen = f"{stem}_{n}{ext}"
        n += 1
    used.add(chosen.casefold())
    return chosen


def _color_rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))


def _fit_safe_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ConversionError("Ukuran gambar tidak valid.")
    factor = min(1.0, math.sqrt(MAX_PIXELS / (width * height)))
    if max_side:
        factor = min(factor, max_side / max(width, height))
    return (max(1, int(width * factor)), max(1, int(height * factor)))


def image_to_jpeg(image: Image.Image, settings: JPGSettings) -> tuple[bytes, tuple[int, int]]:
    """Orientation, ICC when possible, alpha compositing and optimized JPEG."""
    settings.validate()
    # Copy before touching image: the source remains unchanged.
    image = ImageOps.exif_transpose(image)
    target = _fit_safe_size(*image.size, settings.max_side)
    if target != image.size:
        image.thumbnail(target, Image.Resampling.LANCZOS, reducing_gap=2.0)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        rgb = Image.new("RGB", rgba.size, _color_rgb(settings.background))
        rgb.paste(rgba, mask=rgba.getchannel("A"))
    else:
        # Correct color rendering for CMYK input with an embedded ICC profile.
        rgb = None
        if image.mode == "CMYK" and image.info.get("icc_profile"):
            try:
                from PIL import ImageCms
                cmyk_profile = ImageCms.ImageCmsProfile(BytesIO(image.info["icc_profile"]))
                rgb_profile = ImageCms.createProfile("sRGB")
                rgb = ImageCms.profileToProfile(image, cmyk_profile, rgb_profile, outputMode="RGB")
            except (ValueError, OSError):
                pass
        if rgb is None:
            rgb = image.convert("RGB")
    buff = BytesIO()
    rgb.save(
        buff, format="JPEG", quality=settings.quality,
        optimize=True, progressive=True,
        subsampling=0 if settings.quality >= 93 else 2,
        # Deliberately strip EXIF / GPS to avoid copying stale metadata to output.
    )
    return buff.getvalue(), rgb.size


def _image_frames(payload: bytes, extension: str, settings: JPGSettings) -> Iterable[tuple[int, Image.Image]]:
    if extension in (".heic", ".heif") and not _register_heif():
        raise ConversionError("HEIC/HEIF memerlukan pillow-heif. Jalankan pip install -r requirements.txt.")
    if extension == ".avif":
        _register_heif()  # Built-in AVIF works as a fallback on newer Pillow versions.
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.width * image.height > 120_000_000:
                raise ConversionError("Gambar sumber terlalu besar (lebih dari 120 megapiksel).")
            nframes = getattr(image, "n_frames", 1)
            if nframes > MAX_PAGES and settings.all_frames:
                raise ConversionError(f"Terlalu banyak frame ({nframes}; maksimum {MAX_PAGES}).")
            count = nframes if settings.all_frames else 1
            for i in range(count):
                image.seek(i)
                yield i + 1, image.copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise ConversionError(f"Format gambar gagal dibuka: {str(exc)[:170]}") from exc


def _pdf_frames(payload: bytes, settings: JPGSettings) -> Iterable[tuple[int, Image.Image]]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ConversionError("PDF memerlukan pypdfium2 (pip install -r requirements.txt).") from exc
    try:
        doc = pdfium.PdfDocument(payload)
    except Exception as exc:
        raise ConversionError(f"PDF tidak bisa dibuka (mungkin terenkripsi/rusak): {str(exc)[:160]}") from exc
    try:
        num = len(doc)
        if num > MAX_PAGES and settings.all_frames:
            raise ConversionError(f"PDF berisi {num} halaman; maksimum {MAX_PAGES}.")
        for i in range(num if settings.all_frames else min(1, num)):
            page = doc[i]
            try:
                w, h = page.get_size()
                if w <= 0 or h <= 0:
                    raise ConversionError("Ukuran halaman PDF tidak valid.")
                scale = settings.dpi / 72.0
                px_w, px_h = w * scale, h * scale
                safety_scale = min(1.0, math.sqrt(MAX_PIXELS / max(1, px_w * px_h)))
                if settings.max_side:
                    safety_scale = min(safety_scale, settings.max_side / max(px_w, px_h))
                scale *= safety_scale
                bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
                try:
                    frame = bitmap.to_pil().copy()
                    yield i + 1, frame
                finally:
                    bitmap.close()
            finally:
                page.close()
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"Halaman PDF gagal dirender: {str(exc)[:160]}") from exc
    finally:
        doc.close()


def _svg_frames(payload: bytes, settings: JPGSettings) -> Iterable[tuple[int, Image.Image]]:
    try:
        import cairosvg
    except (ImportError, OSError) as exc:
        raise ConversionError("SVG memerlukan CairoSVG dan library cairo.") from exc
    # Reject references capable of fetching external resources or running scripts.
    text = payload.decode("utf-8-sig", errors="replace")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)|<\s*(?:script|foreignObject)\b", text, re.IGNORECASE):
        raise ConversionError("SVG mengandung elemen aktif atau deklarasi eksternal yang tidak didukung.")
    # Includes CSS url(), xlink:href, and @import; fail closed for security.
    if re.search(r"\b(?:href|src)\s*=\s*['\"](?!#)|@import\b|url\s*\(\s*['\"]?(?!#)", text, re.IGNORECASE):
        raise ConversionError("SVG dengan file/gambar eksternal tidak didukung demi keamanan.")
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(text)
        vbox = root.attrib.get("viewBox", "").replace(",", " ").split()
        if len(vbox) == 4:
            width, height = abs(float(vbox[2])), abs(float(vbox[3]))
        else:
            def number(v: str, default: float) -> float:
                match = re.match(r"\s*([0-9.]+)", v)
                return float(match.group(1)) if match else default
            width = number(root.attrib.get("width", ""), 1200)
            height = number(root.attrib.get("height", ""), 800)
        if not all(math.isfinite(x) and x > 0 for x in (width, height)):
            raise ConversionError("Dimensi SVG tidak valid.")
        # Unlike raster sources, vector graphics need a bounded raster target.
        bound = settings.max_side or 2560
        target_width, target_height = _fit_safe_size(round(width), round(height), bound)
        svg_bytes = cairosvg.svg2png(bytestring=payload, output_width=target_width, output_height=target_height, unsafe=False)
        with Image.open(BytesIO(svg_bytes)) as image:
            yield 1, image.copy()
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(f"SVG gagal dirender: {str(exc)[:170]}") from exc


def _office_frames(payload: bytes, original_name: str, settings: JPGSettings) -> Iterable[tuple[int, Image.Image]]:
    office = shutil.which("libreoffice") or shutil.which("soffice")
    if not office:
        raise ConversionError("Dokumen Office memerlukan LibreOffice di server. Format lain tetap bisa digunakan.")
    with tempfile.TemporaryDirectory(prefix="autotimestamp_jpg_") as tmp:
        root = Path(tmp)
        source = root / safe_filename(original_name)
        source.write_bytes(payload)
        output_dir = root / "out"
        output_dir.mkdir()
        # Isolated process profile avoids simultaneous conversion locking.
        profile = (root / "lo_profile").as_uri()
        command = [office, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(source)]
        try:
            proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=100, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ConversionError("Konversi dokumen terlalu lama (batas 100 detik).") from exc
        pdf_path = output_dir / (source.stem + ".pdf")
        if proc.returncode != 0 or not pdf_path.is_file():
            detail = proc.stderr.decode("utf-8", errors="replace").strip()[:170]
            raise ConversionError("LibreOffice tidak berhasil membuat PDF." + (" " + detail if detail else ""))
        yield from _pdf_frames(pdf_path.read_bytes(), settings)


def _iter_frames(payload: bytes, filename: str, settings: JPGSettings) -> Iterable[tuple[int, Image.Image]]:
    extension = Path(filename).suffix.lower()
    if extension in RASTER_EXT:
        yield from _image_frames(payload, extension, settings)
    elif extension in PDF_EXT:
        yield from _pdf_frames(payload, settings)
    elif extension in VECTOR_EXT:
        yield from _svg_frames(payload, settings)
    elif extension in OFFICE_EXT:
        yield from _office_frames(payload, filename, settings)
    else:
        raise ConversionError(f"Ekstensi {extension or '(tanpa ekstensi)'} belum didukung. Jangan mengubah ekstensi saja.")


def convert_files(
    uploads: Iterable[tuple[str, bytes]], settings: JPGSettings,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    *, zip_to_disk: bool = False,
) -> ConversionReport:
    """Convert independent inputs, keep successes if some fail, build memory ZIP.

    Inputs are immutable bytes. ZIP is exported only after all inputs are handled.
    Avoid huge documents and memory exhaustion via explicit page/size caps.
    """
    settings.validate()
    uploads = list(uploads)
    if len(uploads) > MAX_FILES:
        raise ConversionError(f"Maksimum {MAX_FILES} file per batch.")
    report = ConversionReport(input_count=len(uploads), input_bytes=sum(len(p) for _, p in uploads))
    used_names: set[str] = set()
    for index, (name, payload) in enumerate(uploads):
        if on_progress:
            on_progress(index, len(uploads), name)
        if not payload:
            report.errors.append((name, "File kosong."))
            continue
        if len(payload) > MAX_INPUT_BYTES:
            report.errors.append((name, "Ukuran file melebihi 100 MB."))
            continue
        try:
            local_bytes = 0
            # Each upload is all-or-nothing; an invalid frame should not
            # leave a misleading partially converted document.
            local: list[JPGItem] = []
            for n, frame in _iter_frames(payload, name, settings):
                if len(report.items) + len(local) >= MAX_PAGES:
                    raise ConversionError(f"Total hasil melebihi {MAX_PAGES} JPG per batch.")
                try:
                    jpg, (width, height) = image_to_jpeg(frame, settings)
                    if report.jpg_bytes + local_bytes + len(jpg) > MAX_OUTPUT_BYTES:
                        raise ConversionError("Total hasil melebihi batas 400 MB. Gunakan kualitas/resolusi lebih rendah.")
                    basename = safe_basename(name)
                    local.append(JPGItem(f"{basename}.jpg", jpg, width, height, name, n))
                    local_bytes += len(jpg)
                finally:
                    frame.close()
            if not local:
                raise ConversionError("Tidak ada halaman atau foto yang dapat dikonversi.")
            # Name frames consistently as _frame_001, _frame_002, etc.
            # PDF/Office always uses _page_001, including single-page docs.
            is_document = Path(name).suffix.lower() in (PDF_EXT | OFFICE_EXT)
            basename = safe_basename(name)
            for item in local:
                if is_document:
                    label = f"{basename}_page_{item.page:03d}.jpg"
                elif len(local) > 1:
                    label = f"{basename}_frame_{item.page:03d}.jpg"
                else:
                    label = f"{basename}.jpg"
                item.name = _unique_name(label, used_names)
            report.items.extend(local)
        except (ConversionError, OSError, ValueError) as exc:
            report.errors.append((name, str(exc)))
    if on_progress:
        on_progress(len(uploads), len(uploads), "Selesai")
    if report.items:
        # Cloud UI can opt into temporary disk spooling to avoid retaining
        # a second ~400MB in-memory copy of all output JPGs as a ZIP.
        # Default is unchanged for backward compatibility and tests.
        out = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") if zip_to_disk else BytesIO()
        try:
            with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for item in report.items:
                    archive.writestr(item.name, item.data)
            out.seek(0)
            if zip_to_disk:
                report.zip_file = out  # Closed automatically when report is released/reset.
            else:
                report.zip_bytes = out.getvalue()
                out.close()
        except Exception:
            out.close()
            raise
    return report
