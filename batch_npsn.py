"""Batch NPSN: koordinat & daerah diambil online dari Referensi Data Kemendikdasmen."""

from __future__ import annotations

import streamlit as st

import common
import npsn_lookup
import ui
from batch_page import LocationSource, render_batch_page
from ui import STRETCH

SCOPE = "npsn"
INFO_KEY = "npsn_info"

_STATUS_BADGE = {
    "verified": ("success", "🗺️ Validasi lokasi lolos"),
    "partial": ("warning", "🗺️ Validasi sebagian"),
    "unavailable": ("warning", "🗺️ Validator peta tidak tersedia"),
    "mismatch": ("error", "🛑 Lokasi tidak cocok"),
    "official_missing": ("warning", "🛑 Koordinat resmi kosong (0,0)"),
}


def _lookup(npsn_text: str, fallback_enabled: bool):
    npsn = npsn_lookup._validate_npsn_format(npsn_text)
    with st.spinner("Mengambil data resmi Kemendikdasmen dan memvalidasi koordinat..."):
        return npsn_lookup.resolve_npsn(npsn, fallback_enabled, ui.get_secret("GOOGLE_MAPS_API_KEY"))


def _render_details(info, validation):
    status = validation.get("status", "unavailable")
    kind, text = _STATUS_BADGE.get(status, ("warning", status))
    getattr(st, kind)(f"{text}. {validation.get('message', '')}")

    with st.expander("Detail sumber & validasi"):
        st.caption(f"Sumber identitas & wilayah: {info['source_url']}")
        st.caption(f"Sumber koordinat: {info.get('source_name', '-')}")
        if status in {"verified", "partial", "mismatch"}:
            st.caption(
                "Hasil reverse-validator → "
                f"Desa: {validation.get('reverse_desa') or '-'} | "
                f"Kecamatan: {validation.get('reverse_kecamatan') or '-'} | "
                f"Kab/Kota: {validation.get('reverse_kabupaten') or '-'} | "
                f"Provinsi: {validation.get('reverse_provinsi') or '-'}"
            )
        fallback = info.get("fallback")
        if fallback:
            st.caption(
                f"Fallback — confidence **{fallback.get('confidence', 'HIGH')}**, "
                f"metode **{fallback.get('provider_note', '-')}**, "
                f"konsensus query {fallback.get('consensus_count', 0)}, "
                f"kecocokan nama {fallback.get('name_similarity', 0.0) * 100:.1f}%"
            )


def location_panel(ver: int):
    st.session_state.setdefault(INFO_KEY, None)

    # Form: tekan Enter = cek NPSN.
    with st.form(f"npsn_form_{ver}", border=False):
        col_input, col_button = st.columns([3, 1], vertical_alignment="bottom")
        with col_input:
            npsn_text = st.text_input(
                "NPSN", placeholder="Contoh: 20212345", key=f"npsn_text_{ver}",
                help="Dipakai sebagai exact-match ke Referensi Data. Nama sekolah tidak ditampilkan di foto.",
            )
        with col_button:
            submitted = st.form_submit_button("🔎 Cek NPSN", type="primary", **STRETCH)
        with st.expander("Opsi lanjutan"):
            fallback_enabled = st.toggle(
                "Pakai fallback geocoding jika koordinat resmi 0,0", value=False, key=f"npsn_fb_{ver}",
                help="Koordinat resmi selalu diprioritaskan. Fallback hanya jika titik resmi 0,0 dan lolos validasi ketat.",
            )
            has_google = npsn_lookup._google_api_key_is_configured(ui.get_secret("GOOGLE_MAPS_API_KEY"))
            st.caption(
                "✅ GOOGLE_MAPS_API_KEY terdeteksi (Places/Geocoding aktif)." if has_google
                else "ℹ️ GOOGLE_MAPS_API_KEY belum diisi; fallback hanya memakai OpenStreetMap/Nominatim."
            )

    if submitted:
        st.session_state[INFO_KEY] = None
        try:
            st.session_state[INFO_KEY] = _lookup(npsn_text, fallback_enabled)
        except Exception as error:
            st.error(f"❌ Gagal mengambil NPSN: {error}")

    info = st.session_state.get(INFO_KEY)
    if not info:
        return None

    validation = info.get("validation", {})
    status = validation.get("status", "unavailable")
    source_type = info.get("coordinate_source_type", "official_missing")

    st.success(f"✅ NPSN **{info['npsn']}** ditemukan di Referensi Data Kemendikdasmen.")
    st.markdown(f"📍 **Daerah di timestamp:** `{info['location']}`")
    st.caption("Format: Desa/Kelurahan (fallback Kecamatan), Kabupaten/Kota, Provinsi. Nama sekolah tidak ikut.")

    if source_type != "official_missing":
        col_lat, col_lon = st.columns(2)
        col_lat.metric("Latitude", f"{info['latitude']:.7f}")
        col_lon.metric("Longitude", f"{info['longitude']:.7f}")
        if source_type == "fallback":
            st.warning("Titik resmi = 0,0. Memakai **fallback geocoding tervalidasi**, bukan koordinat resmi.")
        else:
            st.caption("🎯 Sumber koordinat: titik resmi NPSN.")

    _render_details(info, validation)

    override = False
    if status == "unavailable":
        override = st.checkbox(
            "Lanjutkan tanpa validator kedua (hanya data resmi Kemendikdasmen)",
            key=f"npsn_override_{ver}",
            help="Validator OpenStreetMap kadang menolak request dari server cloud. Klik 'Cek NPSN' lagi "
                 "untuk mencoba ulang; centang ini hanya jika kamu sudah yakin koordinat resmi benar.",
        )

    validation_ok = status == "verified" or (status == "unavailable" and override)
    if validation_ok:
        blocker = ""
    elif status == "official_missing":
        blocker = "koordinat resmi 0,0 (aktifkan fallback)"
    elif status == "mismatch":
        blocker = "koordinat tidak cocok dengan wilayah"
    else:
        blocker = "validasi lokasi belum lolos"

    status_note = status + (" (dilanjutkan manual tanpa validator)" if status == "unavailable" and override else "")
    return LocationSource(
        latitude=info["latitude"] if source_type != "official_missing" else None,
        longitude=info["longitude"] if source_type != "official_missing" else None,
        location_text=info["location"],
        tz_candidates=(
            [("NPSN", tz, False)] if (tz := common.infer_timezone_from_place(info.get("provinsi", ""))) else []
        ),
        log_extra={
            "NPSN": info["npsn"],
            "Sumber Koordinat/Daerah": info.get("source_name", ""),
            "URL Sumber": info.get("source_url", ""),
            "Status Validasi Lokasi": status_note,
        },
        zip_name=f"hasil_timestamp_npsn_{info['npsn']}.zip",
        ready=validation_ok,
        blocker=blocker,
    )


def render(uploader_version: int, style: common.StyleSettings):
    render_batch_page(
        scope=SCOPE, ver=uploader_version, style=style,
        title="🏫 Batch dari NPSN",
        desc="Upload foto bernama <b>1, 2, 3, …</b>, masukkan satu NPSN. Koordinat & daerah diambil online dari "
             "<b>Referensi Data Kemendikdasmen</b> lalu divalidasi, kemudian jam dibuat acak tapi tetap berurutan.",
        location_title="Lokasi dari NPSN",
        location_panel=location_panel,
    )
