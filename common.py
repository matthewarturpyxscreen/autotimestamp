"""Logika bersama (tanpa UI) untuk mode Batch Manual & Batch NPSN.

Sebelumnya fungsi-fungsi ini disalin dobel di batch_manual.py dan
batch_npsn.py. Sekarang hanya ada satu versi.
"""

from __future__ import annotations

import csv
import io
import math
import os
import re
import secrets
import statistics
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import engine

_WIB = timezone(timedelta(hours=7))
LOG_NAME = "timestamp_log.csv"


def today_wib() -> date:
    """Server (mis. Streamlit Cloud) biasanya UTC; pakai WIB supaya tanggal default tidak mundur."""
    return datetime.now(_WIB).date()


def collapse_spaces(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


# ============================================================
# STYLE
# ============================================================


@dataclass(frozen=True)
class StyleSettings:
    size_mode: str = "short_edge"
    percent: float = 5.0
    fixed_px: int = 80
    bold: bool = False
    bold_strength: int = 25
    lock_uniform: bool = True
    jitter_enabled: bool = False
    jitter_radius_m: int = 8

    @property
    def size_label(self) -> str:
        return f"{self.fixed_px} px" if self.size_mode == "fixed_px" else f"{self.percent:.1f}%"

    def render_kwargs(self, locked_px=None, scale: float = 1.0) -> dict:
        """Argumen untuk engine.render_timestamp. `scale` dipakai preview yang diperkecil."""
        kwargs = dict(
            size_mode=self.size_mode,
            percent=self.percent,
            fixed_px=max(1, round(self.fixed_px * scale)),
            bold=self.bold,
            bold_strength=self.bold_strength,
            min_font_px=max(4, round(engine.MIN_FONT_SIZE_PX * scale)),
        )
        if locked_px is not None:
            kwargs["locked_px"] = max(1, round(locked_px * scale))
        return kwargs


def locked_font_px(sizes, style: StyleSettings):
    """Ukuran px terkunci untuk seluruh batch (median sisi acuan x persen)."""
    if style.size_mode == "fixed_px":
        return max(engine.MIN_FONT_SIZE_PX, int(round(style.fixed_px)))
    if not sizes:
        return None
    basis = [min(w, h) if style.size_mode == "short_edge" else w for w, h in sizes]
    return max(engine.MIN_FONT_SIZE_PX, int(round(statistics.median(basis) * style.percent / 100.0)))


# ============================================================
# NAMA FOTO
# ============================================================


def _stem(uploaded_file) -> str:
    return os.path.splitext(os.path.basename(uploaded_file.name))[0].strip()


def photo_sort_key(uploaded_file):
    stem = _stem(uploaded_file)
    if stem.isdigit():
        return (0, int(stem), uploaded_file.name.lower())
    parts = re.split(r"(\d+)", stem.lower())
    natural = tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)
    return (1, natural, uploaded_file.name.lower())


def validate_numeric_photo_names(uploaded_files):
    """Return (errors, warnings). Warning = nomor loncat (bukan error)."""
    invalid, duplicates, seen = [], [], set()
    for uploaded_file in uploaded_files or []:
        stem = _stem(uploaded_file)
        if not stem.isdigit():
            invalid.append(uploaded_file.name)
            continue
        number = int(stem)
        if number in seen:
            duplicates.append(number)
        seen.add(number)

    errors, warnings = [], []
    if invalid:
        errors.append("Nama file harus angka saja (1.jpg, 2.jpg, ...). Tidak valid: " + ", ".join(invalid[:8]))
    if duplicates:
        errors.append("Nomor foto duplikat: " + ", ".join(str(x) for x in sorted(set(duplicates))))
    if seen and not errors:
        missing = sorted(set(range(min(seen), max(seen) + 1)) - seen)
        if missing:
            shown = ", ".join(str(x) for x in missing[:10]) + (" ..." if len(missing) > 10 else "")
            warnings.append(f"Nomor yang loncat: {shown}. Tetap diproses sesuai urutan yang ada.")
    return errors, warnings


# ============================================================
# WAKTU
# ============================================================


def generate_ordered_random_datetimes(selected_date, start_time, end_time, count):
    if count <= 0:
        return []
    start_dt = datetime.combine(selected_date, start_time)
    end_dt = datetime.combine(selected_date, end_time)
    if end_dt <= start_dt:
        raise ValueError("Jam selesai harus lebih besar daripada jam mulai.")

    total_seconds = int((end_dt - start_dt).total_seconds())
    if total_seconds + 1 < count:
        raise ValueError("Rentang waktu terlalu pendek untuk membuat jam unik untuk semua foto.")

    offsets = sorted(secrets.SystemRandom().sample(range(total_seconds + 1), count))
    return [start_dt + timedelta(seconds=offset) for offset in offsets]


def format_datetime_text(moment: datetime, tz_text: str) -> str:
    return f"{moment.day}/{moment.month}/{moment.year} {moment:%H:%M:%S} {tz_text}"


# ============================================================
# KOORDINAT
# ============================================================


def jitter_coordinate(latitude, longitude, max_radius_m):
    if max_radius_m <= 0:
        return latitude, longitude, 0.0
    rng = secrets.SystemRandom()
    angle = rng.uniform(0, 2 * math.pi)
    distance = rng.uniform(0, max_radius_m)
    lat_deg = 111_320.0
    lon_deg = max(111_320.0 * math.cos(math.radians(latitude)), 1e-9)
    return (
        latitude + distance * math.cos(angle) / lat_deg,
        longitude + distance * math.sin(angle) / lon_deg,
        distance,
    )


def parse_coordinate_pair(text):
    matches = re.findall(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", collapse_spaces(text))
    if len(matches) < 2:
        raise ValueError("Koordinat harus berisi latitude dan longitude. Contoh: -6.5500687, 107.4378152")
    latitude, longitude = float(matches[0]), float(matches[1])
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude di luar rentang yang valid.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude di luar rentang yang valid.")
    return latitude, longitude


# ============================================================
# ZONA WAKTU
# ============================================================

TIMEZONE_OPTIONS = (
    ["WIB", "WITA", "WIT", "GMT", "UTC"]
    + [f"GMT{h:+d}" for h in range(-12, 15)]
    + [f"UTC{h:+d}" for h in range(-12, 15)]
)

_ID_OFFSETS = {"WIB": 7, "WITA": 8, "WIT": 9}

_PROVINCE_TZ = {
    **{p: "WIB" for p in (
        "aceh", "sumatera utara", "sumatera barat", "riau", "kepulauan riau", "jambi",
        "bengkulu", "sumatera selatan", "kepulauan bangka belitung", "lampung", "banten",
        "dki jakarta", "jakarta", "jawa barat", "jawa tengah", "di yogyakarta", "yogyakarta",
        "jawa timur", "kalimantan barat", "kalimantan tengah")},
    **{p: "WITA" for p in (
        "bali", "nusa tenggara barat", "nusa tenggara timur", "kalimantan selatan",
        "kalimantan timur", "kalimantan utara", "sulawesi utara", "gorontalo",
        "sulawesi tengah", "sulawesi barat", "sulawesi selatan", "sulawesi tenggara")},
    **{p: "WIT" for p in (
        "maluku", "maluku utara", "papua", "papua barat", "papua barat daya",
        "papua tengah", "papua pegunungan", "papua selatan")},
}
_PROVINCES_LONGEST_FIRST = sorted(_PROVINCE_TZ, key=len, reverse=True)


def extract_timezone_label(text) -> str:
    raw = str(text or "")
    match = re.search(r"\b(WITA|WIB|WIT)\b", raw, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()

    match = re.search(
        r"\b(GMT|UTC)\s*([+-])\s*(1[0-4]|[0-9])(?:\s*:\s*(00|15|30|45))?\b", raw, flags=re.IGNORECASE
    )
    if match:
        prefix, sign, hour, minute = match.group(1).upper(), match.group(2), int(match.group(3)), match.group(4)
        return f"{prefix}{sign}{hour}:{minute}" if minute and minute != "00" else f"{prefix}{sign}{hour}"

    match = re.search(r"\b(GMT|UTC)\b", raw, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def timezone_info(label):
    """Label -> {source_label, offset, indonesia_label|None, gmt_label, utc_label}."""
    label = str(label or "").strip().upper()
    if not label:
        return None

    if label in _ID_OFFSETS:
        off = _ID_OFFSETS[label]
        return {"source_label": label, "offset": off, "indonesia_label": label,
                "gmt_label": f"GMT+{off}", "utc_label": f"UTC+{off}"}

    if label in {"GMT", "UTC"}:
        return {"source_label": label, "offset": 0, "indonesia_label": None,
                "gmt_label": "GMT+0", "utc_label": "UTC+0"}

    match = re.fullmatch(r"(GMT|UTC)([+-])(1[0-4]|[0-9])(?::(00|15|30|45))?", label)
    if not match:
        return None

    sign = 1 if match.group(2) == "+" else -1
    hour, minute = int(match.group(3)), int(match.group(4) or 0)
    offset = sign * (hour + minute / 60)
    indonesia = {7: "WIB", 8: "WITA", 9: "WIT"}.get(offset) if minute == 0 else None

    sign_text = "+" if offset >= 0 else "-"
    whole = int(abs(offset))
    suffix = f"{sign_text}{whole}:{minute:02d}" if minute else f"{sign_text}{whole}"
    return {"source_label": label, "offset": offset, "indonesia_label": indonesia,
            "gmt_label": f"GMT{suffix}", "utc_label": f"UTC{suffix}"}


def _normalize_place(value) -> str:
    value = collapse_spaces(value).lower().replace("d.k.i.", "dki").replace("d.i.", "di")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", value)).strip()


def infer_timezone_from_place(text):
    """Cari nama provinsi Indonesia di teks lokasi -> info zona waktu (atau None)."""
    normalized = _normalize_place(text)
    if not normalized:
        return None
    for province in _PROVINCES_LONGEST_FIRST:
        if re.search(rf"\b{re.escape(province)}\b", normalized):
            info = timezone_info(_PROVINCE_TZ[province])
            info["detected_province"] = province.title()
            return info
    return None


def timezone_label_choices(info, from_source_text: bool):
    """Daftar (nama format, teks label) yang bisa ditulis di foto; offset-nya sama."""
    choices = []
    if from_source_text and info["source_label"] != info.get("indonesia_label"):
        choices.append(("Sesuai sumber", info["source_label"]))
    if info.get("indonesia_label"):
        choices.append(("Indonesia", info["indonesia_label"]))
    choices.append(("GMT", info["gmt_label"]))
    choices.append(("UTC", info["utc_label"]))
    seen, unique = set(), []
    for name, text in choices:
        if text not in seen:
            seen.add(text)
            unique.append((name, text))
    return unique


# ============================================================
# PEMROSES BATCH
# ============================================================


@dataclass
class BatchResult:
    zip_bytes: bytes
    log_rows: list
    preview_bytes: bytes | None
    preview_name: str | None
    csv_bytes: bytes


def _log_to_csv(rows) -> bytes:
    if not rows:
        return b""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")  # BOM supaya Excel membaca UTF-8


def _render_job(job):
    image = engine.load_image(job["file"].getvalue())
    result, info = engine.render_timestamp(image, job["raw_text"], inplace=True, **job["render_kwargs"])
    encoded, _ = engine.encode_image(result, job["name"])
    return encoded, info["line_count"]


def process_batch(
    files,
    *,
    base_latitude,
    base_longitude,
    location_text,
    extra_lines,
    datetimes,
    tz_text,
    style: StyleSettings,
    locked_px,
    log_extra: dict | None = None,
    time_source_note="Generated/random dari rentang input; bukan EXIF asli",
    progress=None,
    workers: int | None = None,
):
    """Render semua foto -> ZIP (foto + timestamp_log.csv). `files` berurutan.

    Koordinat/jam dihitung di thread utama (urutan terjaga), render+encode
    berjalan paralel. `progress(done, total)` dipanggil dari thread utama.
    """
    log_extra = log_extra or {}
    render_kwargs = style.render_kwargs(locked_px=locked_px)
    location_text = collapse_spaces(location_text)

    jobs, rows = [], []
    for uploaded_file, moment in zip(files, datetimes):
        lat, lon, offset_m = jitter_coordinate(
            base_latitude, base_longitude, style.jitter_radius_m if style.jitter_enabled else 0
        )
        lines = [f"{lat:.7f}, {lon:.7f}", location_text, format_datetime_text(moment, tz_text)] + list(extra_lines)
        jobs.append({
            "name": uploaded_file.name,
            "file": uploaded_file,  # dibaca malas di worker agar memori tidak berlipat
            "raw_text": "\n".join(lines),
            "render_kwargs": render_kwargs,
        })
        rows.append({
            "Nama File": uploaded_file.name,
            "Latitude": f"{lat:.7f}",
            "Longitude": f"{lon:.7f}",
            "Latitude Dasar": f"{base_latitude:.7f}",
            "Longitude Dasar": f"{base_longitude:.7f}",
            "Offset Koordinat (meter)": round(offset_m, 2),
            "Daerah": location_text,
            "Tanggal": moment.strftime("%d/%m/%Y"),
            "Jam": moment.strftime("%H:%M:%S"),
            "Zona Waktu": tz_text,
            "Font": engine.FONT_NAME,
            "Bold": "Ya" if style.bold else "Tidak",
            "Ketebalan Bold (%)": style.bold_strength if style.bold else 0,
            "Ukuran Timestamp": style.size_label,
            "Ukuran Terkunci (px)": locked_px if locked_px is not None else "",
            "Baris Tambahan": " | ".join(extra_lines),
            **log_extra,
            "Sumber Waktu": time_source_note,
        })

    total = len(jobs)
    workers = max(1, min(workers or (os.cpu_count() or 1), 4, total or 1))
    zip_buffer = io.BytesIO()
    preview_bytes = preview_name = None

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            iterator = pool.map(_render_job, jobs)
            for index, (job, row, (encoded, line_count)) in enumerate(zip(jobs, rows, iterator), start=1):
                archive.writestr(job["name"], encoded)  # JPEG/PNG sudah terkompresi -> deflate ringan
                row["Jumlah Baris"] = line_count
                if preview_bytes is None:
                    preview_bytes, preview_name = encoded, job["name"]
                if progress:
                    progress(index, total)
        csv_bytes = _log_to_csv(rows)
        archive.writestr(LOG_NAME, csv_bytes)

    return BatchResult(zip_buffer.getvalue(), rows, preview_bytes, preview_name, csv_bytes)
