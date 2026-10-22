"""Batch Manual: lokasi dari teks yang diketik / hasil OCR screenshot."""

from __future__ import annotations

import streamlit as st

import common
import ui
from batch_page import LocationSource, render_batch_page

SCOPE = "manual"


def location_panel(ver: int):
    key = f"manual_ref_{ver}"

    # OCR harus dijalankan SEBELUM text_area dibuat agar boleh mengisi nilainya.
    with st.expander("🔍 Isi otomatis dari screenshot (OCR Gemini)"):
        ui.render_ocr_panel(
            SCOPE, ver, key,
            hint="Screenshot area timestamp (Win+Shift+S / Cmd+Shift+4), lalu paste atau upload.",
        )

    text = st.text_area(
        "Timestamp acuan", height=120, key=key,
        placeholder="-6.5500687, 107.4378152\nCipaisan, Purwakarta, Jawa Barat\n7/10/2026 13:12:08 WIB",
        help="Baris 1: koordinat · Baris 2: lokasi · Baris 3 (opsional): waktu acuan, hanya dipakai "
             "untuk mendeteksi zona waktu · Baris 4+: baris tambahan yang ikut tampil di semua foto.",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    if len(lines) < 2:
        st.error("❌ Minimal 2 baris: koordinat (baris 1) dan lokasi (baris 2).")
        return LocationSource(blocker="butuh 2 baris")

    try:
        latitude, longitude = common.parse_coordinate_pair(lines[0])
        location_text = common.collapse_spaces(lines[1])
        if not location_text:
            raise ValueError("Daerah/lokasi belum diisi.")
    except ValueError as error:
        st.error(f"❌ {error}")
        return LocationSource(blocker="koordinat/lokasi tidak valid")

    reference_time = lines[2] if len(lines) >= 3 else ""
    extra_lines = tuple(lines[3:])

    candidates = []
    from_text = common.timezone_info(common.extract_timezone_label(text))
    if from_text:
        candidates.append(("Timestamp/OCR", from_text, True))
    from_place = common.infer_timezone_from_place(location_text)
    if from_place:
        candidates.append(("Lokasi", from_place, False))

    col_lat, col_lon = st.columns(2)
    col_lat.metric("Latitude", f"{latitude:.7f}")
    col_lon.metric("Longitude", f"{longitude:.7f}")
    st.caption(f"📍 {location_text}")
    if reference_time:
        st.caption(f"🕒 Waktu acuan `{reference_time}` tidak dipakai — tanggal & jam diatur di Langkah 3.")
    if extra_lines:
        st.caption("➕ Baris tambahan di semua foto: " + " | ".join(extra_lines))

    return LocationSource(
        latitude=latitude, longitude=longitude, location_text=location_text,
        extra_lines=extra_lines, tz_candidates=candidates,
        log_extra={"Sumber Lokasi": "Input manual user"},
        zip_name="hasil_timestamp_batch_manual.zip", ready=True,
    )


def render(uploader_version: int, style: common.StyleSettings):
    render_batch_page(
        scope=SCOPE, ver=uploader_version, style=style,
        title="🗂️ Batch Manual",
        desc="Upload foto bernama <b>1, 2, 3, …</b>, isi koordinat & lokasi (ketik atau OCR), "
             "atur tanggal dan rentang jam, lalu generate semuanya sekaligus.",
        location_title="Koordinat & lokasi",
        location_panel=location_panel,
    )
