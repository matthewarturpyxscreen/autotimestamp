"""Komponen UI Streamlit yang dipakai semua mode."""

from __future__ import annotations

import dataclasses
import hashlib
import html
import os
from dataclasses import dataclass
from datetime import datetime, time

import streamlit as st
from PIL import ImageOps

import common
import engine
import ocr

APP_VERSION = "V10"


def _st_version():
    try:
        return tuple(int(x) for x in st.__version__.split(".")[:2])
    except Exception:
        return (0, 0)


# Streamlit >= 1.50 memakai width="stretch"; versi lama use_container_width.
STRETCH = {"width": "stretch"} if _st_version() >= (1, 50) else {"use_container_width": True}

# Klik download tidak perlu memicu rerun seluruh aplikasi (Streamlit >= 1.43).
NO_RERUN = {"on_click": "ignore"} if _st_version() >= (1, 43) else {}


def get_secret(name: str, default: str = "") -> str:
    """st.secrets bisa melempar error bila secrets.toml tidak ada; juga dukung env var."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return value or os.environ.get(name, default)


# ============================================================
# CSS
# ============================================================

_CSS = """
<style>
.block-container { padding-top: 2.2rem; max-width: 1480px; }

/* Card */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px;
    border: 1px solid rgba(140,140,140,.18);
}

/* Hero */
.hero { display:flex; align-items:center; gap:.7rem; flex-wrap:wrap; margin-bottom:.1rem; }
.hero-title { font-size:1.75rem; font-weight:800; letter-spacing:-.4px; line-height:1.2; }
.hero-badge { font-size:.68rem; font-weight:700; padding:3px 9px; border-radius:20px;
    background:linear-gradient(135deg,#2563eb,#3b82f6); color:#fff; letter-spacing:.4px; }
.hero-desc { opacity:.75; font-size:.92rem; margin:.15rem 0 .9rem; }

/* Judul langkah */
.step-title { font-weight:700; font-size:1.02rem; margin:0 0 .35rem; }
.step-title .n { display:inline-block; width:1.55rem; height:1.55rem; line-height:1.55rem;
    text-align:center; border-radius:50%; background:#3b82f6; color:#fff; font-size:.85rem; margin-right:.45rem; }

/* Checklist status */
.chk-wrap { display:flex; flex-direction:column; gap:6px; margin:.2rem 0 .6rem; }
.chk { display:flex; align-items:baseline; gap:.5rem; padding:7px 11px; border-radius:10px;
    border:1px solid rgba(140,140,140,.22); background:rgba(140,140,140,.06); font-size:.88rem; }
.chk.ok { border-color:rgba(16,185,129,.55); background:rgba(16,185,129,.09); }
.chk small { opacity:.75; margin-left:auto; text-align:right; }

/* Tombol */
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button,
div[data-testid="stFormSubmitButton"] button { border-radius:10px; font-weight:600; }

/* Metric lebih ringkas */
div[data-testid="stMetric"] { background:rgba(140,140,140,.07); border:1px solid rgba(140,140,140,.14);
    border-radius:12px; padding:8px 12px; }

.info-card { padding:10px 14px; border-radius:10px; background:rgba(140,140,140,.06);
    border-left:4px solid #3b82f6; margin:8px 0; font-size:.88rem; }
.footer-text { text-align:center; font-size:.8rem; opacity:.7; padding-top:.8rem; }

/* Panel kanan menempel saat scroll (layar lebar saja) */
@media (min-width: 992px) {
    div[data-testid="stColumn"]:has(.st-key-sticky_panel) {
        position: sticky; top: 3.6rem; align-self: flex-start;
        max-height: calc(100vh - 4.4rem); overflow-y: auto; padding-right: 4px;
    }
}
</style>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def hero(title: str, desc: str):
    st.markdown(
        f'<div class="hero"><span class="hero-title">{html.escape(title)}</span>'
        f'<span class="hero-badge">{APP_VERSION}</span></div>'
        f'<div class="hero-desc">{desc}</div>',
        unsafe_allow_html=True,
    )


def step_title(number: int, text: str):
    st.markdown(
        f'<div class="step-title"><span class="n">{number}</span>{html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


def status_checklist(items):
    """items: [(ok, label, detail)]"""
    rows = []
    for ok, label, detail in items:
        rows.append(
            f'<div class="chk {"ok" if ok else ""}"><span>{"✅" if ok else "⬜"}</span>'
            f"<b>{html.escape(label)}</b><small>{html.escape(str(detail))}</small></div>"
        )
    st.markdown(f'<div class="chk-wrap">{"".join(rows)}</div>', unsafe_allow_html=True)


# ============================================================
# SIDEBAR: GAYA TIMESTAMP
# ============================================================

SIZE_MODE_LABELS = {
    "short_edge": "Otomatis — % sisi terpendek ⭐",
    "width": "% lebar foto (lama)",
    "fixed_px": "Piksel tetap",
}

_STYLE_DEFAULTS = {
    "style_mode": "short_edge",
    "style_percent": 5.0,
    "style_px": 80,
    "style_bold": False,
    "style_bold_strength": 25,
    "style_lock": True,
    "style_jitter": False,
    "style_jitter_radius": 8,
}


def _reset_style():
    for key, value in _STYLE_DEFAULTS.items():
        st.session_state[key] = value


def render_style_sidebar(batch: bool) -> common.StyleSettings:
    for key, value in _STYLE_DEFAULTS.items():
        st.session_state.setdefault(key, value)

    with st.sidebar:
        st.markdown("### 🎨 Gaya Timestamp")
        st.caption(f"Font: {engine.FONT_NAME}")

        mode = st.selectbox(
            "Metode ukuran",
            list(SIZE_MODE_LABELS),
            format_func=SIZE_MODE_LABELS.get,
            key="style_mode",
            help="Otomatis memakai sisi terpendek foto, sehingga portrait & landscape tampil seimbang.",
        )
        if mode == "fixed_px":
            st.number_input("Ukuran (px)", min_value=14, max_value=400, step=1, key="style_px",
                            help="Ukuran piksel tetap, tidak mengikuti resolusi foto.")
        else:
            st.slider("Ukuran (%)", min_value=2.0, max_value=8.0, step=0.1, key="style_percent",
                      help="Persen dari sisi terpendek (Otomatis) atau dari lebar foto (lama).")

        bold = st.toggle("Bold", key="style_bold")
        if bold:
            st.slider("Ketebalan bold", 1, 100, key="style_bold_strength",
                      help="1 = sangat tipis, 100 = paling tebal.")

        if batch:
            st.divider()
            st.toggle(
                "Kunci ukuran huruf seluruh batch", key="style_lock",
                help="Direkomendasikan: semua foto memakai ukuran huruf (px) yang sama. "
                     "Baris panjang di foto sempit dibungkus ke baris berikutnya, bukan dikecilkan.",
            )
            jitter = st.toggle(
                "Acak sedikit koordinat per foto", key="style_jitter",
                help="Menambah offset kecil di sekitar titik dasar supaya koordinat antar foto tidak identik.",
            )
            if jitter:
                st.slider("Radius acak (meter)", 1, 30, key="style_jitter_radius")
        else:
            # Jaga state widget batch agar tidak hilang saat pindah ke mode Satu Foto.
            for key in ("style_lock", "style_jitter", "style_jitter_radius"):
                st.session_state[key] = st.session_state[key]

        st.button("↺ Kembalikan default", on_click=_reset_style, **STRETCH)

    ss = st.session_state
    return common.StyleSettings(
        size_mode=ss["style_mode"],
        percent=float(ss["style_percent"]),
        fixed_px=int(ss["style_px"]),
        bold=bool(ss["style_bold"]),
        bold_strength=int(ss["style_bold_strength"]),
        lock_uniform=bool(ss["style_lock"]) if batch else False,
        jitter_enabled=bool(ss["style_jitter"]) if batch else False,
        jitter_radius_m=int(ss["style_jitter_radius"]),
    )


def style_summary(style: common.StyleSettings, batch: bool) -> str:
    parts = [f"Ukuran **{style.size_label}**", f"Bold **{'ya' if style.bold else 'tidak'}**"]
    if batch:
        parts.append(f"Kunci ukuran **{'ya' if style.lock_uniform else 'tidak'}**")
        parts.append(f"Acak koordinat **{'ya' if style.jitter_enabled else 'tidak'}**")
    return "🎨 " + " · ".join(parts) + " — ubah di sidebar ‹"


# ============================================================
# FOTO: KEY, UKURAN, PREVIEW
# ============================================================


def file_key(uploaded_file) -> str:
    return f"{getattr(uploaded_file, 'file_id', '')}:{uploaded_file.name}:{uploaded_file.size}"


@st.cache_data(show_spinner=False, max_entries=1024)
def cached_oriented_size(key: str, _data: bytes):
    return engine.oriented_size(_data)


def photo_sizes(files):
    return [cached_oriented_size(file_key(f), f.getvalue()) for f in files]


@st.cache_data(show_spinner=False, max_entries=16)
def cached_preview(key: str, _data: bytes, raw_text: str, style_tuple: tuple, locked_px, max_edge: int = 1280):
    """Render overlay pada versi kecil foto (cepat). Hasil dikembalikan sebagai JPEG."""
    style = common.StyleSettings(*style_tuple)
    image, scale = engine.load_preview_image(_data, max_edge)
    rendered, info = engine.render_timestamp(
        image, raw_text, inplace=True, **style.render_kwargs(locked_px=locked_px, scale=scale)
    )
    encoded, _ = engine.encode_image(rendered, "preview.jpg", jpeg_quality=88)
    return encoded, info


def render_preview(uploaded_file, raw_text, style, locked_px=None):
    """Tampilkan preview live. Return info dict atau None bila gagal."""
    try:
        encoded, info = cached_preview(
            file_key(uploaded_file), uploaded_file.getvalue(), raw_text,
            dataclasses.astuple(style), locked_px,
        )
    except Exception as error:
        st.warning(f"Preview tidak dapat dibuat: {error}")
        return None
    st.image(encoded, caption="Preview (versi diperkecil; hasil akhir tetap resolusi asli)", **STRETCH)
    if info.get("auto_fit_applied"):
        st.caption("📏 Auto-fit aktif: font dikecilkan agar baris terpanjang muat.")
    if info.get("wrap_applied"):
        st.caption("↩️ Ada baris panjang yang dibungkus (ukuran huruf tetap seragam).")
    if info.get("vertical_overflow_warning"):
        st.warning("Baris terlalu banyak untuk ukuran ini; bagian atas teks bisa terpotong. Kecilkan ukuran.")
    return info


# ============================================================
# OCR PANEL
# ============================================================


def render_ocr_panel(scope: str, ver: int, target_key: str, hint: str):
    """Isi `st.session_state[target_key]` dari screenshot. Panggil SEBELUM text_area bertarget dibuat."""
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        st.warning("`GEMINI_API_KEY` belum diisi di Streamlit Secrets, jadi OCR tidak aktif. Ketik manual saja.")
    else:
        st.caption(hint)

    from streamlit_paste_button import paste_image_button as pbutton

    col_paste, col_upload = st.columns(2)
    with col_paste:
        pasted = pbutton(label="📋 Klik, lalu Ctrl+V", key=f"{scope}_paste_{ver}")
    with col_upload:
        uploaded = st.file_uploader(
            "Atau upload screenshot", type=["jpg", "jpeg", "png"],
            key=f"{scope}_shot_{ver}", label_visibility="collapsed",
        )

    image = None
    try:
        if pasted.image_data is not None:
            image = ImageOps.exif_transpose(pasted.image_data).convert("RGB")
        elif uploaded is not None:
            image = engine.load_image(uploaded.getvalue())
    except Exception as error:
        st.error(f"Screenshot tidak dapat dibaca: {error}")
    if image is None:
        return

    image = ocr.shrink_for_ocr(image)
    st.image(image, caption="Screenshot untuk OCR", width=420)
    signature = hashlib.md5(image.tobytes()).hexdigest()

    sig_key, err_key = f"{scope}_ocr_sig", f"{scope}_ocr_err"
    done = st.session_state.get(sig_key) == signature
    failed = st.session_state.get(err_key)
    failed_here = bool(failed and failed[0] == signature)

    col_status, col_button = st.columns([3, 1])
    with col_button:
        rerun = st.button("🔁 OCR ulang", disabled=not api_key, key=f"{scope}_ocr_again_{ver}", **STRETCH)

    # Otomatis jalan sekali per screenshot baru. Kalau gagal, TIDAK mengulang tiap rerun (hemat kuota).
    if api_key and (rerun or (not done and not failed_here)):
        try:
            with col_status:
                with st.spinner("Gemini sedang membaca timestamp..."):
                    text = ocr.extract_text(image, api_key)
            st.session_state[sig_key] = signature
            st.session_state.pop(err_key, None)
            if text:
                st.session_state[target_key] = text
                st.rerun()
            col_status.warning("Gemini tidak mengembalikan teks apa pun.")
        except Exception as error:
            st.session_state[err_key] = (signature, str(error))
            col_status.error(f"OCR gagal: {error}")
    elif failed_here:
        col_status.error(f"OCR gagal: {failed[1]} — klik 'OCR ulang' untuk mencoba lagi.")
    elif done:
        col_status.caption("✅ Screenshot ini sudah di-OCR; hasil ada di kotak teks.")


# ============================================================
# TANGGAL, JAM, ZONA WAKTU (BATCH)
# ============================================================


@dataclass
class TimeChoice:
    date: object
    start: time
    end: time
    tz_text: str
    error: str | None
    seconds: int


def _tz_display(info) -> str:
    return info.get("indonesia_label") or info["source_label"]


def render_datetime_panel(scope: str, ver: int, photo_count: int, tz_candidates) -> TimeChoice:
    """tz_candidates: [(asal, info, dari_teks_sumber)]"""
    c_date, c_start, c_end = st.columns(3)
    with c_date:
        picked_date = st.date_input("Tanggal", value=common.today_wib(), key=f"{scope}_date_{ver}", format="DD/MM/YYYY")
    with c_start:
        start = st.time_input("Jam mulai", value=time(13, 0), key=f"{scope}_start_{ver}", step=60)
    with c_end:
        end = st.time_input("Jam selesai", value=time(16, 0), key=f"{scope}_end_{ver}", step=60)

    # --- zona waktu ---
    manual_label = "Pilih manual"
    options = [f"Auto dari {origin} — {_tz_display(info)}" for origin, info, _ in tz_candidates] + [manual_label]
    # Key memuat hash daftar opsi: saat opsi auto muncul/berubah (mis. setelah OCR), pilihan
    # kembali ke "Auto" alih-alih menempel di "Pilih manual" dari saat teks masih kosong.
    options_sig = hashlib.md5("|".join(options).encode()).hexdigest()[:6]
    col_src, col_fmt = st.columns([3, 2])
    with col_src:
        source = st.selectbox("Zona waktu", options, key=f"{scope}_tz_source_{ver}_{options_sig}",
                              help="Otomatis dari timestamp/OCR atau provinsi lokasi. Bisa di-override manual.")

    tz_text, chosen = "WIB", None
    if source != manual_label:
        origin, chosen, from_text = tz_candidates[options.index(source)]
        choices = common.timezone_label_choices(chosen, from_text)
        shown = {f"{name} — {text}": text for name, text in choices}
        with col_fmt:
            fmt_sig = hashlib.md5("|".join(shown).encode()).hexdigest()[:6]
            picked = st.radio("Tulisan di foto", list(shown), key=f"{scope}_tz_fmt_{ver}_{fmt_sig}",
                              help="Offset sama; hanya mengubah tulisan (WITA / GMT+8 / UTC+8).")
        tz_text = shown[picked]
    else:
        default = next(
            (c[1].get("indonesia_label") or c[1]["source_label"] for c in tz_candidates), "WIB"
        )
        default = default if default in common.TIMEZONE_OPTIONS else "WIB"
        with col_fmt:
            tz_text = st.selectbox("Label zona waktu", common.TIMEZONE_OPTIONS,
                                   index=common.TIMEZONE_OPTIONS.index(default),
                                   key=f"{scope}_tz_manual_{ver}")
        if not tz_candidates:
            st.caption("ℹ️ Zona waktu belum terdeteksi otomatis; pilih manual.")

    # --- validasi rentang ---
    seconds = int((datetime.combine(picked_date, end) - datetime.combine(picked_date, start)).total_seconds())
    error = None
    if seconds <= 0:
        error = "Jam selesai harus lebih besar daripada jam mulai."
    elif photo_count and seconds + 1 < photo_count:
        error = f"Rentang {seconds} detik terlalu pendek untuk {photo_count} foto (jam harus unik)."

    if error:
        st.error("❌ " + error)
    elif photo_count:
        st.caption(
            f"🕒 {photo_count} foto dalam {seconds // 60} menit (≈ {seconds / max(photo_count, 1):.0f} detik/foto). "
            "Jam diacak lalu diurutkan naik mengikuti nomor foto."
        )
    return TimeChoice(picked_date, start, end, tz_text, error, seconds)


def footer():
    st.markdown(
        '<div class="footer-text">Dibuat oleh <b>Matthew Artur Panahatan Sitorus</b> & '
        "<b>Nikita Adriella Virginia Jacob</b><br>AVHershey Simplex Medium • Gemini OCR • Pillow</div>",
        unsafe_allow_html=True,
    )
