"""Halaman batch bersama untuk Batch Manual dan Batch NPSN.

Kedua mode hanya berbeda pada SUMBER LOKASI (Langkah 2). Foto, tanggal/jam,
preview, generate, dan hasil identik, jadi ada di sini sekali saja.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import common
import ui
from ui import NO_RERUN, STRETCH

RESULT_TABLE_COLUMNS = [
    "Nama File", "Tanggal", "Jam", "Latitude", "Longitude", "Offset Koordinat (meter)", "Daerah",
]


@dataclass
class LocationSource:
    """Hasil Langkah 2 dari mode apa pun."""

    latitude: float | None = None
    longitude: float | None = None
    location_text: str = ""
    extra_lines: tuple = ()
    tz_candidates: list = field(default_factory=list)  # [(asal, info, dari_teks_sumber)]
    log_extra: dict = field(default_factory=dict)
    zip_name: str = "hasil_timestamp.zip"
    ready: bool = False
    blocker: str = "Lokasi belum diisi."


def _photo_step(scope: str, ver: int):
    ui.step_title(1, "Foto")
    files = st.file_uploader(
        "Foto (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"], accept_multiple_files=True,
        key=f"{scope}_photos_{ver}", label_visibility="collapsed",
        help="Upload langsung beberapa foto (tanpa ZIP). Nama file harus angka: 1.jpg, 2.jpg, 3.jpg, ...",
    )
    sorted_files = sorted(files or [], key=common.photo_sort_key)
    errors, warnings = common.validate_numeric_photo_names(sorted_files)

    for message in errors:
        st.error("❌ " + message)
    for message in warnings:
        st.warning("⚠️ " + message)

    sizes = []
    if sorted_files and not errors:
        sizes = ui.photo_sizes(sorted_files)
        st.caption(
            f"✅ **{len(sorted_files)} foto** siap · urutan {sorted_files[0].name} → {sorted_files[-1].name}"
        )
        with st.expander("Lihat daftar & resolusi"):
            st.dataframe(
                pd.DataFrame(
                    [{"Urutan": i, "Nama File": f.name, "Resolusi": f"{w} × {h}"}
                     for i, (f, (w, h)) in enumerate(zip(sorted_files, sizes), start=1)]
                ),
                hide_index=True, **STRETCH,
            )
    elif not sorted_files:
        st.caption("Belum ada foto. Beri nama 1, 2, 3, ... sesuai urutan yang diinginkan.")
    return sorted_files, errors, sizes


def render_batch_page(*, scope, ver, style, title, desc, location_title, location_panel):
    result_key = f"{scope}_result"
    st.session_state.setdefault(result_key, None)

    ui.hero(title, desc)
    st.warning(
        "Jam pada mode ini **dibuat dari rentang yang kamu pilih**, bukan waktu pengambilan asli. "
        "Hasil dan `timestamp_log.csv` menandai hal ini; foto hasil tidak membawa metadata EXIF asli."
    )

    left, right = st.columns([6, 5], gap="large")

    # ------------------------------------------------------------ KIRI: INPUT
    with left:
        with st.container(border=True):
            sorted_files, name_errors, sizes = _photo_step(scope, ver)

        with st.container(border=True):
            ui.step_title(2, location_title)
            location = location_panel(ver)

        with st.container(border=True):
            ui.step_title(3, "Tanggal & rentang jam")
            time_choice = ui.render_datetime_panel(
                scope, ver, len(sorted_files), location.tz_candidates if location else []
            )

    # --------------------------------------------------- KANAN: STATUS & HASIL
    photos_ok = bool(sorted_files) and not name_errors
    location_ok = bool(location and location.ready)
    time_ok = time_choice.error is None
    can_generate = photos_ok and location_ok and time_ok

    locked_px = common.locked_font_px(sizes, style) if (style.lock_uniform and sizes) else None

    signature = None
    if photos_ok and location_ok:
        signature = hashlib.md5(repr((
            tuple(ui.file_key(f) for f in sorted_files), dataclasses.astuple(style),
            location.latitude, location.longitude, location.location_text, tuple(location.extra_lines),
            time_choice.tz_text, time_choice.date, time_choice.start, time_choice.end,
            tuple(sorted(location.log_extra.items())),
        )).encode()).hexdigest()

    with right:
        with st.container(key="sticky_panel"):
            ui.status_checklist([
                (photos_ok, "Foto", f"{len(sorted_files)} file" if photos_ok else "belum siap"),
                (location_ok, "Lokasi", location.location_text if location_ok else (location.blocker if location else "belum diisi")),
                (time_ok, "Waktu", f"{time_choice.start:%H:%M}–{time_choice.end:%H:%M} {time_choice.tz_text}" if time_ok else "rentang tidak valid"),
            ])

            clicked = st.button(
                f"🚀 Generate {len(sorted_files)} foto" if photos_ok else "🚀 Generate semua foto",
                type="primary", disabled=not can_generate, key=f"{scope}_generate_{ver}", **STRETCH,
            )
            st.caption(ui.style_summary(style, batch=True))

            if clicked and can_generate:
                try:
                    datetimes = common.generate_ordered_random_datetimes(
                        time_choice.date, time_choice.start, time_choice.end, len(sorted_files)
                    )
                    bar = st.progress(0.0, text="Memulai...")
                    started = _time.perf_counter()
                    batch = common.process_batch(
                        sorted_files,
                        base_latitude=location.latitude, base_longitude=location.longitude,
                        location_text=location.location_text, extra_lines=location.extra_lines,
                        datetimes=datetimes, tz_text=time_choice.tz_text, style=style,
                        locked_px=locked_px, log_extra=location.log_extra,
                        progress=lambda done, total: bar.progress(done / total, text=f"Memproses foto {done}/{total}"),
                    )
                    bar.empty()
                    st.session_state[result_key] = {
                        "batch": batch, "zip_name": location.zip_name, "signature": signature,
                        "count": len(sorted_files), "seconds": _time.perf_counter() - started,
                    }
                except Exception as error:
                    st.error(f"❌ Gagal generate batch: {error}")

            result = st.session_state.get(result_key)
            if result:
                _render_result(result, signature, scope, ver)

            with st.expander("👁️ Preview live (foto pertama)", expanded=result is None):
                if photos_ok and location and location.latitude is not None and location.location_text:
                    start_dt = datetime.combine(time_choice.date, time_choice.start)
                    sample = start_dt + timedelta(seconds=max(time_choice.seconds, 0) // 2)
                    raw = "\n".join([
                        f"{location.latitude:.7f}, {location.longitude:.7f}",
                        location.location_text,
                        common.format_datetime_text(sample, time_choice.tz_text),
                        *location.extra_lines,
                    ])
                    ui.render_preview(sorted_files[0], raw, style, locked_px)
                else:
                    st.info("Preview muncul setelah foto dan lokasi siap.")


def _render_result(result, current_signature, scope, ver):
    batch = result["batch"]
    with st.container(border=True):
        st.success(f"✅ {result['count']} foto selesai dalam {result['seconds']:.1f} detik.")
        if current_signature != result["signature"]:
            st.warning("Input/pengaturan berubah sejak hasil ini dibuat. Klik Generate lagi untuk memperbarui.")

        col_zip, col_csv = st.columns([3, 2])
        with col_zip:
            st.download_button(
                "⬇️ Download ZIP", data=batch.zip_bytes, file_name=result["zip_name"],
                mime="application/zip", type="primary", key=f"{scope}_dl_zip_{ver}", **STRETCH, **NO_RERUN,
            )
        with col_csv:
            st.download_button(
                "📄 Log CSV", data=batch.csv_bytes, file_name=common.LOG_NAME,
                mime="text/csv", key=f"{scope}_dl_csv_{ver}", **STRETCH, **NO_RERUN,
            )
        st.caption(f"ZIP berisi foto hasil + `{common.LOG_NAME}`.")

        with st.expander("Tabel hasil"):
            st.dataframe(pd.DataFrame(batch.log_rows)[RESULT_TABLE_COLUMNS], hide_index=True, **STRETCH)
        if batch.preview_bytes:
            st.image(batch.preview_bytes, caption=f"Hasil: {batch.preview_name}", **STRETCH)
