# ============================================================
# TIMESTAMP GENERATOR V10 — GPS Map Camera style
# ============================================================
#
# Struktur:
#   app.py          entry point + mode "Satu Foto"
#   batch_manual.py mode Batch Manual (sumber lokasi: ketik / OCR)
#   batch_npsn.py   mode Batch NPSN   (sumber lokasi: Referensi Data Kemendikdasmen)
#   batch_page.py   halaman batch bersama (foto, jam, preview, generate, hasil)
#   ui.py           komponen UI bersama (CSS, sidebar gaya, OCR, tanggal/zona waktu)
#   common.py       logika bersama tanpa UI (nama foto, jam acak, zona waktu, ZIP)
#   engine.py       mesin render overlay (tanpa Streamlit/OpenCV)
#   ocr.py          OCR Gemini
#   npsn_lookup.py  data layer NPSN (scrape + validasi + fallback geocoding)
#
# Font: AVHershey Simplex Medium — https://github.com/yangcht/Hershey_font_TTF
#
# Credit:
# Matthew Artur Panahatan Sitorus
# Nikita Adriella Virginia Jacob
# ============================================================

import html
import hashlib
import dataclasses
import os
import secrets

import streamlit as st

st.set_page_config(
    page_title="Timestamp Generator | GPS Camera Style",
    page_icon="🕒",
    layout="wide",
    initial_sidebar_state="expanded",
)

import batch_manual  # noqa: E402
import batch_npsn  # noqa: E402
import engine  # noqa: E402
import ui  # noqa: E402
from ui import NO_RERUN, STRETCH  # noqa: E402

WORDS_A = ["hangat", "cerah", "biru", "senja", "kilat", "lembut", "gemilang", "rindang", "damai",
           "megah", "riang", "sejuk", "terang", "elok", "anggun", "cepat", "tenang", "ceria"]
WORDS_B = ["pelangi", "senja", "camar", "kabut", "elang", "bintang", "ombak", "awan", "bukit",
           "kilau", "embun", "cakrawala", "merpati", "fajar", "angin", "karang", "hutan", "samudra"]

MODE_SINGLE, MODE_MANUAL, MODE_NPSN = "📷 Satu Foto", "🗂️ Batch Manual", "🏫 Batch NPSN"
STATE_PREFIXES = ("single_", "manual_", "npsn_")


def reset_all():
    """Mulai baru: naikkan versi widget (mengosongkan uploader) dan hapus hasil lama."""
    version = st.session_state.get("uploader_version", 0) + 1
    for key in [k for k in st.session_state if k.startswith(STATE_PREFIXES)]:
        del st.session_state[key]
    st.session_state["uploader_version"] = version


# ============================================================
# MODE: SATU FOTO
# ============================================================


def render_single(ver, style):
    result_key = "single_result"
    text_key = f"single_text_{ver}"

    ui.hero(
        "🕒 Timestamp Generator",
        "Watermark timestamp gaya <b>GPS Map Camera</b> dengan normalisasi orientasi EXIF, "
        "auto-fit font, dan OCR <b>Gemini</b>.",
    )

    left, right = st.columns([6, 5], gap="large")

    with left:
        with st.container(border=True):
            ui.step_title(1, "Foto")
            photo = st.file_uploader(
                "Foto (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"],
                key=f"single_photo_{ver}", label_visibility="collapsed",
                help="Orientasi EXIF dinormalisasi otomatis agar teks selalu tegak.",
            )
            photo_ok = False
            if photo is None:
                st.caption("Belum ada foto.")
            else:
                try:
                    width, height = ui.cached_oriented_size(ui.file_key(photo), photo.getvalue())
                    ratio = width / height if height else 1.0
                    shape = "Landscape" if ratio > 1.1 else ("Portrait" if ratio < 0.9 else "Persegi")
                    st.caption(f"📄 **{photo.name}** · {width} × {height} px · {shape}")
                    photo_ok = True
                except Exception as error:
                    st.error(f"❌ Foto tidak dapat dibaca: {error}")

        with st.container(border=True):
            ui.step_title(2, "Teks timestamp")
            # OCR harus dijalankan SEBELUM text_area dibuat agar boleh mengisi nilainya.
            with st.expander("🔍 Isi otomatis dari screenshot (OCR Gemini)"):
                ui.render_ocr_panel(
                    "single", ver, text_key,
                    hint="Screenshot area timestamp (Win+Shift+S / Cmd+Shift+4), lalu paste atau upload.",
                )
            text = st.text_area(
                "Isi timestamp (bebas jumlah baris)", height=140, key=text_key,
                placeholder="-5.7297568, 105.6231008\nSukaratu, Lampung Selatan, Lampung\n18/8/2026 10:12:35 WIB",
                help="Baris 1–3 dinormalisasi (koordinat, lokasi, tanggal/jam); baris 4+ dipakai apa adanya. "
                     "Baris terlalu panjang otomatis mengecilkan font agar tidak terpotong.",
            )
            line_count = len([line for line in text.splitlines() if line.strip()])
            if line_count:
                st.caption(f"🟢 {line_count} baris terdeteksi.")

    text_ok = bool(text.strip())
    signature = None
    if photo_ok and text_ok:
        signature = hashlib.md5(
            repr((ui.file_key(photo), text, dataclasses.astuple(style))).encode()
        ).hexdigest()

    with right:
        with st.container(key="sticky_panel"):
            ui.status_checklist([
                (photo_ok, "Foto", photo.name if photo_ok else "belum ada"),
                (text_ok, "Teks", f"{line_count} baris" if text_ok else "kosong"),
            ])
            clicked = st.button(
                "🚀 Generate timestamp", type="primary", disabled=not (photo_ok and text_ok),
                key=f"single_generate_{ver}", **STRETCH,
            )
            st.caption(ui.style_summary(style, batch=False))

            if clicked:
                try:
                    with st.spinner("Merender timestamp pada resolusi asli..."):
                        image = engine.load_image(photo.getvalue())
                        rendered, info = engine.render_timestamp(image, text, inplace=True, **style.render_kwargs())
                        name, ext = os.path.splitext(photo.name)
                        output_name = f"{name}_{secrets.choice(WORDS_A)}{secrets.choice(WORDS_B)}{ext or '.jpg'}"
                        data, mime = engine.encode_image(rendered, output_name)
                    st.session_state[result_key] = {
                        "data": data, "mime": mime, "name": output_name, "info": info,
                        "size": rendered.size, "signature": signature,
                    }
                except Exception as error:
                    st.error(f"❌ Terjadi kesalahan: {error}")

            result = st.session_state.get(result_key)
            if result:
                with st.container(border=True):
                    st.success(f"✅ Selesai: {result['size'][0]} × {result['size'][1]} px")
                    if signature != result["signature"]:
                        st.warning("Input/pengaturan berubah sejak hasil ini dibuat. Klik Generate lagi untuk memperbarui.")
                    st.download_button(
                        f"⬇️ Download {result['name']}", data=result["data"], file_name=result["name"],
                        mime=result["mime"], type="primary", key=f"single_download_{ver}",
                        **STRETCH, **NO_RERUN,
                    )
                    _render_single_details(result["info"])

            with st.expander("👁️ Preview live", expanded=result is None):
                if photo_ok and text_ok:
                    ui.render_preview(photo, text, style)
                else:
                    st.info("Preview muncul setelah foto dan teks timestamp terisi.")


def _render_single_details(info):
    with st.expander("Detail teks & parameter"):
        rows = "<br>".join(
            f"{i}. <code>{html.escape(line)}</code>" for i, line in enumerate(info["lines"], start=1)
        )
        st.markdown(
            f'<div class="info-card">📝 <b>Isi timestamp ({info["line_count"]} baris):</b><br>{rows}</div>',
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Ukuran font", f"{info['font_size']} px")
        col2.metric("Ukuran awal", f"{info['initial_font_size']} px")
        col3.metric("Margin bawah", f"{info['bottom_margin']} px")
        st.caption(
            f"Font {info['font_name']} · Bold: {'ya (' + str(info['bold_strength_px']) + ' px)' if info['bold_enabled'] else 'tidak'} · "
            f"Outline {info['outline_width']} px · Jarak baris {info['line_spacing']} px · "
            f"Auto-fit: {'ya' if info['auto_fit_applied'] else 'tidak perlu'}"
        )
        if info["vertical_overflow_warning"]:
            st.warning("Baris cukup banyak untuk ukuran ini; bagian atas teks berpotensi terpotong.")


# ============================================================
# ROUTER
# ============================================================

ui.inject_css()
st.session_state.setdefault("uploader_version", 0)
uploader_version = st.session_state["uploader_version"]

mode = st.radio(
    "Mode", [MODE_SINGLE, MODE_MANUAL, MODE_NPSN],
    horizontal=True, label_visibility="collapsed", key="app_mode",
)

app_style = ui.render_style_sidebar(batch=mode != MODE_SINGLE)
with st.sidebar:
    st.divider()
    st.button("🔄 Mulai baru (kosongkan semua)", on_click=reset_all, **STRETCH)

if mode == MODE_MANUAL:
    batch_manual.render(uploader_version, app_style)
elif mode == MODE_NPSN:
    batch_npsn.render(uploader_version, app_style)
else:
    render_single(uploader_version, app_style)

ui.footer()
