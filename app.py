# ============================================================
# TIMESTAMP GENERATOR V7.4 - STREAMLIT UI
# ============================================================
#
# FONT:
# AVHershey Simplex Medium
#
# SOURCE:
# https://github.com/yangcht/Hershey_font_TTF
#
# Port dari versi Google Colab (V7.4 New Input freetext +
# Gemini OCR). Fungsi inti (normalisasi teks, parsing
# timestamp, render font, OCR Gemini) TIDAK diubah logikanya
# -- hanya lapisan UI/IO yang diganti ke Streamlit karena
# ipywidgets & google.colab.files tidak jalan di luar Colab.
#
# Credit:
# Matthew Artur Panahatan Sitorus
# Nikita Adriella Virginia Jacob
# ============================================================


# ============================================================
# IMPORT
# ============================================================

import os
import re
import io
import glob
import hashlib
import secrets
import subprocess

import cv2
import numpy as np
import streamlit as st

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps
)

from google import genai
from google.genai import types as genai_types

from streamlit_paste_button import paste_image_button as pbutton


# ============================================================
# ============================================================
# CONFIGURATION (SAMA PERSIS DENGAN VERSI COLAB)
# ============================================================
# ============================================================


# ============================================================
# MASTER WIDTH
# ============================================================

REFERENCE_WIDTH = 2048


# ============================================================
# FONT SIZE
# ============================================================

REFERENCE_FONT_SIZE = 70

# Ukuran timestamp dinyatakan sebagai % dari lebar foto, supaya
# otomatis mengikuti resolusi/rasio foto apapun yang diupload.
# Diatur langsung di sini oleh program (bukan lewat UI) --
# tinggal ganti angka ini kalau mau lebih besar/kecil lagi.
DEFAULT_FONT_SIZE_PERCENT = 5.0


# ============================================================
# TEXT COLOR
# ============================================================

TEXT_COLOR = (
    255,
    255,
    255
)


# ============================================================
# OUTLINE
# ============================================================

REFERENCE_OUTLINE_WIDTH = 2


OUTLINE_COLOR = (
    0,
    0,
    0
)


# ============================================================
# OUTLINE OFFSET
# ============================================================

REFERENCE_OUTLINE_OFFSET_X = 0

REFERENCE_OUTLINE_OFFSET_Y = 0


# ============================================================
# LETTER SPACING
# ============================================================

REFERENCE_LETTER_SPACING = -1


# ============================================================
# SPACE SCALE
# ============================================================

SPACE_SCALE = 0.75


# ============================================================
# POSISI
# ============================================================

REFERENCE_LEFT_MARGIN = 32

REFERENCE_BOTTOM_MARGIN = 88

REFERENCE_LINE_SPACING = 78


# ============================================================
# TEXT ANCHOR
# ============================================================

TEXT_ANCHOR = "ls"


# ============================================================
# ============================================================
# FONT SETUP (DENGAN CACHE STREAMLIT)
# ============================================================
# ============================================================

REPO_DIR = "Hershey_font_TTF"


# ============================================================
# DAFTAR KATA UNTUK NAMA FILE RANDOM
# ============================================================
#
# Dipakai buat bikin nama file download unik & gampang dibaca,
# contoh: FOTO_hangatpelangi.jpg
# ============================================================

RANDOM_WORD_LIST_A = [
    "hangat", "cerah", "biru", "senja", "kilat", "lembut",
    "gemilang", "rindang", "damai", "megah", "riang", "sejuk",
    "terang", "elok", "anggun", "cepat", "tenang", "ceria",
]

RANDOM_WORD_LIST_B = [
    "pelangi", "senja", "camar", "kabut", "elang", "bintang",
    "ombak", "awan", "bukit", "kilau", "embun", "cakrawala",
    "merpati", "fajar", "angin", "karang", "hutan", "samudra",
]


@st.cache_resource(show_spinner="Menyiapkan font Hershey...")
def get_font_path():

    if not os.path.exists(REPO_DIR):

        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "https://github.com/yangcht/Hershey_font_TTF.git",
                REPO_DIR
            ],
            check=True
        )


    font_candidates = glob.glob(
        REPO_DIR + "/**/*Simplex*Medium*.ttf",
        recursive=True
    )


    if len(font_candidates) == 0:

        raise Exception(
            "Font AVHershey Simplex Medium tidak ditemukan."
        )


    return font_candidates[0]


# ------------------------------------------------------------
# Cache objek font per (path, size) supaya file .ttf tidak
# di-parse ulang dari disk setiap kali generate dipanggil --
# ImageFont.truetype() lumayan mahal kalau dipanggil berulang.
# ------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_font(font_path, font_size):

    return ImageFont.truetype(
        font_path,
        font_size
    )


# ============================================================
# ============================================================
# OCR PAKAI GEMINI AI (LOGIKA SAMA DENGAN VERSI COLAB)
# ============================================================
# ============================================================

GEMINI_MODEL_NAME = "gemini-3.6-flash"


# ============================================================
# LOAD FOTO DENGAN FIX ORIENTASI EXIF
# ============================================================
#
# cv2.imread() TIDAK membaca tag EXIF Orientation, jadi foto
# dari HP yang disimpan dengan tag "rotate 90/180/270" akan
# terbaca apa adanya (raw sensor orientation) oleh OpenCV.
#
# Akibatnya timestamp yang kita gambar (selalu lurus/horizontal
# di array mentah) jadi ikut miring begitu foto ditampilkan di
# viewer lain yang MENGHORMATI tag EXIF tersebut.
#
# Fix: normalisasi orientasi dulu pakai PIL (ImageOps.exif_transpose)
# SEBELUM digambar, supaya pixel-nya benar2 sudah tegak sesuai
# tampilan aslinya, dan text yang kita gambar horizontal akan
# selalu terlihat lurus di manapun foto ini dibuka.
# ============================================================

def load_pil_image_fixed_orientation(uploaded_file):

    pil_image = Image.open(
        uploaded_file
    )

    pil_image = ImageOps.exif_transpose(
        pil_image
    )

    pil_image = pil_image.convert(
        "RGB"
    )

    return pil_image


GEMINI_OCR_PROMPT = """
Gambar ini adalah screenshot yang berisi overlay timestamp
GPS kamera (koordinat, lokasi, tanggal & jam).

Baca teks overlay timestamp tersebut PERSIS seperti yang
tertulis di gambar, tanpa mengubah, membetulkan, atau
menerka-nerka isinya.

Keluarkan HANYA 3 baris berikut, tanpa penjelasan tambahan,
tanpa markdown, tanpa tanda kutip:

Baris 1: koordinat (lintang, bujur)
Baris 2: nama lokasi
Baris 3: tanggal dan jam (dan WIB/zona waktu jika ada)
""".strip()


def ocr_extract_text_gemini(
    pil_image,
    api_key
):

    client = genai.Client(
        api_key=api_key
    )


    # --------------------------------------------------------
    # Convert PIL image ke bytes PNG
    # --------------------------------------------------------

    image_buffer = io.BytesIO()

    pil_image.save(
        image_buffer,
        format="PNG"
    )

    image_bytes = image_buffer.getvalue()


    # --------------------------------------------------------
    # Kirim ke Gemini
    # --------------------------------------------------------

    response = client.models.generate_content(

        model=GEMINI_MODEL_NAME,

        contents=[

            genai_types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/png"
            ),

            GEMINI_OCR_PROMPT
        ]
    )


    raw_text = response.text or ""


    # --------------------------------------------------------
    # Bersihkan kemungkinan markdown code fence
    # kalau Gemini iseng bungkus jawabannya
    # --------------------------------------------------------

    raw_text = re.sub(
        r"^```[a-zA-Z]*\n?",
        "",
        raw_text.strip()
    )

    raw_text = re.sub(
        r"```$",
        "",
        raw_text.strip()
    )


    lines = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip()
    ]


    return "\n".join(lines)


# ============================================================
# ============================================================
# NORMALISASI TEXT (LOGIKA SAMA DENGAN VERSI COLAB)
# ============================================================
# ============================================================


def normalize_coordinate(text):

    text = re.sub(
        r"\s+",
        " ",
        text.strip()
    )

    text = re.sub(
        r"\s*,",
        ",",
        text
    )

    text = re.sub(
        r",\s*",
        ",  ",
        text
    )

    return text


def normalize_location(text):

    text = re.sub(
        r"\s+",
        " ",
        text.strip()
    )

    text = re.sub(
        r"\s*,",
        ",",
        text
    )

    text = re.sub(
        r",\s*",
        ",  ",
        text
    )

    return text


def normalize_datetime(text):

    text = re.sub(
        r"\s+",
        " ",
        text.strip()
    )


    time_match = re.search(
        r"\b(\d{1,2}:\d{2}:\d{2})\b",
        text
    )


    if time_match:

        time_value = time_match.group(1)

        before = text[
            :time_match.start()
        ].strip()

        after = text[
            time_match.end():
        ].strip()

        after = re.sub(
            r"^\s*WIB\s*$",
            "WIB",
            after,
            flags=re.IGNORECASE
        )

        if after:

            return (
                before
                + " "
                + time_value
                + "  "
                + after
            )

        else:

            return (
                before
                + " "
                + time_value
            )


    return text


# ============================================================
# PARSE TIMESTAMP
# ============================================================

def parse_timestamp(raw_text):

    lines = raw_text.splitlines()

    lines = [
        line.strip()
        for line in lines
        if line.strip()
    ]

    if len(lines) != 3:

        raise ValueError(
            "Input harus terdiri dari tepat 3 baris."
        )

    line1 = normalize_coordinate(
        lines[0]
    )

    line2 = normalize_location(
        lines[1]
    )

    line3 = normalize_datetime(
        lines[2]
    )

    return [
        line1,
        line2,
        line3
    ]


# ============================================================
# ============================================================
# DRAW TIMESTAMP (LOGIKA SAMA DENGAN VERSI COLAB)
# ============================================================
# ============================================================


def draw_timestamp(
    draw,
    text,
    x,
    baseline,
    font,
    outline_width,
    letter_spacing,
    space_scale,
    outline_offset_x,
    outline_offset_y
):

    current_x = float(x)

    # Lebar spasi sama untuk semua karakter " " di baris yang
    # sama, jadi dihitung sekali saja sebelum loop (sebelumnya
    # dihitung ulang tiap kali ketemu spasi).
    space_width = draw.textlength(
        " ",
        font=font
    ) * space_scale

    for char in text:

        if char == " ":

            current_x += (
                space_width +
                letter_spacing
            )

            continue

        draw.text(

            (
                round(
                    current_x +
                    outline_offset_x
                ),

                round(
                    baseline +
                    outline_offset_y
                )
            ),

            char,

            font=font,

            fill=TEXT_COLOR,

            stroke_width=outline_width,

            stroke_fill=OUTLINE_COLOR,

            anchor=TEXT_ANCHOR
        )

        char_width = draw.textlength(
            char,
            font=font
        )

        current_x += (
            char_width +
            letter_spacing
        )


# ============================================================
# ============================================================
# GENERATE TIMESTAMP (LOGIKA SAMA, INPUT/OUTPUT PAKAI BYTES)
# ============================================================
# ============================================================

def generate_timestamp_image(
    image_cv,
    raw_timestamp_text,
    font_size_percent=DEFAULT_FONT_SIZE_PERCENT
):

    lines = parse_timestamp(
        raw_timestamp_text
    )

    line1 = lines[0]

    line2 = lines[1]

    line3 = lines[2]


    height, width = image_cv.shape[:2]


    # --------------------------------------------------------
    # Font size dihitung langsung dari % lebar foto, jadi
    # otomatis menyesuaikan resolusi/rasio foto apapun yang
    # diupload. Elemen lain (outline, margin, spacing) ikut
    # di-scale proporsional lewat scale_ratio, sama seperti
    # sebelumnya.
    # --------------------------------------------------------

    font_size = max(
        1,
        round(
            width *
            (font_size_percent / 100)
        )
    )

    scale_ratio = (
        font_size /
        REFERENCE_FONT_SIZE
    )


    outline_width = max(
        1,
        round(
            REFERENCE_OUTLINE_WIDTH *
            scale_ratio
        )
    )


    left_margin = round(
        REFERENCE_LEFT_MARGIN *
        scale_ratio
    )


    bottom_margin = round(
        REFERENCE_BOTTOM_MARGIN *
        scale_ratio
    )


    line_spacing = round(
        REFERENCE_LINE_SPACING *
        scale_ratio
    )


    outline_offset_x = round(
        REFERENCE_OUTLINE_OFFSET_X *
        scale_ratio
    )


    outline_offset_y = round(
        REFERENCE_OUTLINE_OFFSET_Y *
        scale_ratio
    )


    letter_spacing = (
        REFERENCE_LETTER_SPACING *
        scale_ratio
    )


    font_path = get_font_path()

    font = get_font(
        font_path,
        font_size
    )


    # Foto sudah dalam urutan channel RGB sejak diupload (lihat
    # bagian UI), jadi langsung dipakai tanpa konversi warna
    # bolak-balik yang sia-sia.
    pil_image = Image.fromarray(
        image_cv
    )


    draw = ImageDraw.Draw(
        pil_image
    )


    baseline3 = (
        height -
        bottom_margin
    )


    baseline2 = (
        baseline3 -
        line_spacing
    )


    baseline1 = (
        baseline2 -
        line_spacing
    )


    draw_timestamp(

        draw,

        line1,

        left_margin,

        baseline1,

        font,

        outline_width,

        letter_spacing,

        SPACE_SCALE,

        outline_offset_x,

        outline_offset_y
    )


    draw_timestamp(

        draw,

        line2,

        left_margin,

        baseline2,

        font,

        outline_width,

        letter_spacing,

        SPACE_SCALE,

        outline_offset_x,

        outline_offset_y
    )


    draw_timestamp(

        draw,

        line3,

        left_margin,

        baseline3,

        font,

        outline_width,

        letter_spacing,

        SPACE_SCALE,

        outline_offset_x,

        outline_offset_y
    )


    info = {
        "line1": line1,
        "line2": line2,
        "line3": line3,
        "font_size": font_size,
        "scale_ratio": scale_ratio,
        "outline_width": outline_width,
        "letter_spacing": letter_spacing,
        "left_margin": left_margin,
        "bottom_margin": bottom_margin,
        "line_spacing": line_spacing
    }


    return pil_image, info


# ============================================================
# ============================================================
# STREAMLIT UI
# ============================================================
# ============================================================

st.set_page_config(
    page_title="Timestamp Generator",
    page_icon="🕒",
    layout="centered"
)


st.markdown(
    """
    <style>
    div[data-testid="stDownloadButton"] button,
    div[data-testid="stButton"] button {
        border-radius: 10px;
        font-weight: 600;
    }
    div[data-testid="stMetric"] {
        background-color: rgba(120, 120, 120, 0.08);
        border-radius: 10px;
        padding: 10px 14px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


st.title("🕒 Timestamp Generator")

st.caption(
    "AVHershey Simplex Medium — watermark timestamp gaya GPS Map Camera"
)


# ------------------------------------------------------------
# SESSION STATE AWAL
# ------------------------------------------------------------
#
# uploader_version dipakai untuk "mereset" SEMUA widget input
# (file_uploader, paste button, DAN text_area timestamp).
# Widget-widget itu tidak bisa dikosongkan langsung lewat
# session_state kalau sudah pernah dirender di run yang sama
# (Streamlit akan melempar StreamlitAPIException), jadi triknya
# bikin key baru per widget supaya Streamlit menganggapnya
# widget baru yang masih kosong.
# ------------------------------------------------------------

DEFAULTS = {
    "uploader_version": 0,
    "generated_result": None,
    "last_ocr_signature": None,
}

for state_key, default_value in DEFAULTS.items():

    if state_key not in st.session_state:

        st.session_state[state_key] = default_value


def reset_app():

    st.session_state.uploader_version += 1

    st.session_state.last_ocr_signature = None

    st.session_state.generated_result = None


uploader_version = st.session_state.uploader_version

timestamp_key = f"timestamp_box_{uploader_version}"


# ------------------------------------------------------------
# 1. UPLOAD FOTO UTAMA
# ------------------------------------------------------------

st.header("1️⃣ Upload Foto")

with st.container(border=True):

    photo_file = st.file_uploader(
        "Pilih foto utama",
        type=["jpg", "jpeg", "png"],
        key=f"photo_uploader_{uploader_version}"
    )


    image_cv = None

    if photo_file is not None:

        try:

            photo_pil = load_pil_image_fixed_orientation(
                photo_file
            )

            # Disimpan langsung dalam urutan channel RGB (bukan BGR)
            # supaya tidak perlu bolak-balik convert warna nanti pas
            # digambar timestamp-nya -- hanya dikonversi ke BGR sekali,
            # di akhir, saat proses encode file downloadnya (cv2.imencode
            # butuh BGR).
            image_cv = np.array(
                photo_pil
            )

        except Exception as error:

            st.error(
                f"❌ Foto tidak dapat dibaca: {error}"
            )

            image_cv = None


        if image_cv is not None:

            height, width = image_cv.shape[:2]

            col_name, col_res = st.columns(2)

            with col_name:

                st.metric(
                    "📄 Nama File",
                    photo_file.name
                )

            with col_res:

                st.metric(
                    "📐 Resolusi",
                    f"{width} × {height}"
                )

            st.image(
                image_cv,
                caption="Preview foto asli (orientasi sudah dinormalisasi)",
                use_container_width=True
            )

    else:

        st.info(
            "⬆️ Belum ada foto. Upload foto utama yang mau "
            "ditambahkan timestamp."
        )


# ------------------------------------------------------------
# 2. MASUKKAN TIMESTAMP
# ------------------------------------------------------------

st.header("2️⃣ Masukkan Timestamp")

tab_manual, tab_ocr = st.tabs(
    [
        "✍️ Ketik Manual",
        "🔍 OCR dari Screenshot (Gemini AI)"
    ]
)

with tab_manual:

    st.caption(
        "Ketik atau paste teks manual, 3 baris: "
        "koordinat, lokasi, lalu tanggal & waktu."
    )

with tab_ocr:

    gemini_api_key = st.secrets.get(
        "GEMINI_API_KEY",
        ""
    )

    if not gemini_api_key:

        st.warning(
            "⚠️ `GEMINI_API_KEY` belum diset di Secrets. "
            "Fitur OCR tidak akan jalan sampai API key dikonfigurasi "
            "di Streamlit Cloud (Settings → Secrets), bukan di kode."
        )

    st.caption(
        "Screenshot dulu area timestamp-nya (Win+Shift+S di Windows, "
        "Cmd+Shift+4 di Mac), lalu klik tombol paste di bawah dan "
        "tekan Ctrl+V (Cmd+V di Mac). Didukung di Chrome/Edge/Safari "
        "(belum jalan di Firefox) — kalau browser gak support, "
        "upload manual saja. Hasilnya otomatis masuk ke kotak teks "
        "di bawah, gak perlu klik apa-apa lagi."
    )

    paste_result = pbutton(
        label="📋 Klik lalu Ctrl+V untuk paste screenshot",
        key=f"screenshot_paste_{uploader_version}"
    )

    screenshot_file = st.file_uploader(
        "atau upload file screenshot",
        type=["jpg", "jpeg", "png"],
        key=f"screenshot_uploader_{uploader_version}"
    )


    screenshot_image = None

    if paste_result.image_data is not None:

        try:

            screenshot_image = ImageOps.exif_transpose(
                paste_result.image_data
            ).convert("RGB")

        except Exception as error:

            st.error(
                f"❌ Screenshot hasil paste tidak dapat dibaca: {error}"
            )

            screenshot_image = None

    elif screenshot_file is not None:

        try:

            screenshot_image = load_pil_image_fixed_orientation(
                screenshot_file
            )

        except Exception as error:

            st.error(
                f"❌ Screenshot tidak dapat dibaca: {error}"
            )

            screenshot_image = None


    if screenshot_image is not None:

        st.image(
            screenshot_image,
            caption="Preview screenshot yang akan di-OCR",
            use_container_width=True
        )


        # ----------------------------------------------------
        # Jalankan OCR OTOMATIS begitu ada screenshot baru
        # (paste ataupun upload), tanpa perlu klik tombol.
        # Dicek pakai hash gambar supaya tidak OCR ulang
        # berkali-kali untuk gambar yang sama di setiap rerun
        # Streamlit.
        # ----------------------------------------------------

        image_buffer_for_hash = io.BytesIO()

        screenshot_image.save(
            image_buffer_for_hash,
            format="PNG"
        )

        screenshot_signature = hashlib.md5(
            image_buffer_for_hash.getvalue()
        ).hexdigest()

        already_processed = (
            st.session_state.last_ocr_signature == screenshot_signature
        )

        col_ocr_status, col_ocr_button = st.columns(
            [3, 1]
        )

        with col_ocr_button:

            rerun_ocr_clicked = st.button(
                "🔁 OCR ulang",
                type="secondary",
                disabled=not gemini_api_key,
                use_container_width=True
            )

        should_run_ocr = (
            gemini_api_key
            and (not already_processed or rerun_ocr_clicked)
        )

        if should_run_ocr:

            try:

                with col_ocr_status:

                    with st.spinner(
                        "⏳ Meminta Gemini membaca timestamp..."
                    ):

                        ocr_result = ocr_extract_text_gemini(
                            screenshot_image,
                            gemini_api_key
                        )


                st.session_state.last_ocr_signature = screenshot_signature

                if ocr_result:

                    st.session_state[timestamp_key] = ocr_result

                    st.success(
                        "✅ Hasil OCR sudah dimasukkan ke kotak teks "
                        "di bawah. Silakan cek & edit dulu sebelum GENERATE."
                    )

                    st.rerun()

                else:

                    st.warning(
                        "⚠️ Gemini tidak mengembalikan teks apapun."
                    )


            except Exception as error:

                st.error(
                    f"❌ ERROR OCR GEMINI: {error}"
                )

        elif already_processed:

            st.caption(
                "✅ Screenshot ini sudah di-OCR. Klik **OCR ulang** "
                "kalau mau coba baca ulang."
            )


timestamp_text = st.text_area(
    "Timestamp (3 baris)",
    height=130,
    placeholder=(
        "-5.7297568, 105.6231008\n"
        "Sukaratu, Lampung Selatan, Lampung\n"
        "18/8/2026 10:12:35 WIB"
    ),
    key=timestamp_key
)


# ------------------------------------------------------------
# 3. GENERATE
# ------------------------------------------------------------

st.header("3️⃣ Generate")

photo_ready = image_cv is not None
timestamp_ready = bool(timestamp_text.strip())

if not photo_ready or not timestamp_ready:

    missing = []

    if not photo_ready:
        missing.append("foto (langkah 1)")

    if not timestamp_ready:
        missing.append("timestamp (langkah 2)")

    st.caption(
        "⏳ Lengkapi dulu: " + " & ".join(missing) + "."
    )

generate_clicked = st.button(
    "GENERATE TIMESTAMP",
    type="primary",
    disabled=not (photo_ready and timestamp_ready),
    use_container_width=True
)

if generate_clicked:

    try:

        with st.spinner(
            "Menggambar timestamp..."
        ):

            pil_image, info = generate_timestamp_image(
                image_cv,
                timestamp_text
            )


        # ----------------------------------------------------
        # SIAPKAN FILE UNTUK DOWNLOAD
        # ----------------------------------------------------

        name, ext = os.path.splitext(
            photo_file.name
        )

        if not ext:

            ext = ".jpg"

        random_word = (
            secrets.choice(RANDOM_WORD_LIST_A) +
            secrets.choice(RANDOM_WORD_LIST_B)
        )

        output_file_name = (
            name +
            "_" +
            random_word +
            ext
        )


        result_rgb = np.array(
            pil_image
        )

        result_cv = cv2.cvtColor(
            result_rgb,
            cv2.COLOR_RGB2BGR
        )


        if ext.lower() in [
            ".jpg",
            ".jpeg"
        ]:

            encode_success, encoded_bytes = cv2.imencode(
                ext,
                result_cv,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    95
                ]
            )

            mime_type = "image/jpeg"

        else:

            encode_success, encoded_bytes = cv2.imencode(
                ext,
                result_cv
            )

            mime_type = "image/png"


        if encode_success:

            st.session_state.generated_result = {
                "pil_image": pil_image,
                "info": info,
                "output_file_name": output_file_name,
                "encoded_bytes": encoded_bytes.tobytes(),
                "mime_type": mime_type,
            }

            st.rerun()

        else:

            st.error(
                "❌ Gagal encode gambar hasil."
            )


    except Exception as error:

        st.error(
            f"❌ ERROR: {error}"
        )


# ------------------------------------------------------------
# HASIL (persist di session_state supaya tetap tampil sampai
# di-reset, walaupun ada widget lain yang dipencet)
# ------------------------------------------------------------

result = st.session_state.generated_result

if result is not None:

    st.divider()

    st.success(
        "✅ TIMESTAMP BERHASIL DIBUAT"
    )

    with st.expander(
        "Detail timestamp & rendering",
        expanded=True
    ):

        info = result["info"]

        st.write(
            "**Baris 1 / KOORDINAT:**",
            info["line1"]
        )

        st.write(
            "**Baris 2 / LOKASI:**",
            info["line2"]
        )

        st.write(
            "**Baris 3 / TANGGAL & WAKTU:**",
            info["line3"]
        )

        st.markdown(
            f"""
- Font: AVHershey Simplex Medium
- Font Size: {info['font_size']}px ({DEFAULT_FONT_SIZE_PERCENT}% dari lebar foto)
- Scale Ratio: {info['scale_ratio']:.4f}
- Outline Width: {info['outline_width']}px
- Letter Spacing: {info['letter_spacing']:.2f}px
- Left Margin: {info['left_margin']}px
- Bottom Margin: {info['bottom_margin']}px
- Line Spacing: {info['line_spacing']}px
"""
        )


    st.image(
        result["pil_image"],
        caption="Preview hasil",
        use_container_width=True
    )


    col_download, col_reset = st.columns(2)

    with col_download:

        st.download_button(
            label="⬇️ DOWNLOAD HASIL",
            data=result["encoded_bytes"],
            file_name=result["output_file_name"],
            mime=result["mime_type"],
            type="primary",
            use_container_width=True
        )

    with col_reset:

        if st.button(
            "🔄 Reset & Mulai Lagi",
            type="secondary",
            use_container_width=True
        ):

            reset_app()

            st.rerun()


# ------------------------------------------------------------
# CREDIT
# ------------------------------------------------------------

st.divider()

st.caption(
    "Dibuat oleh: **Matthew Artur Panahatan Sitorus** & "
    "**Nikita Adriella Virginia Jacob**"
)
