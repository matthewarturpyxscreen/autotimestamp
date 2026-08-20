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

    for char in text:

        if char == " ":

            space_width = draw.textlength(
                " ",
                font=font
            )

            space_width *= space_scale

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
    raw_timestamp_text
):

    lines = parse_timestamp(
        raw_timestamp_text
    )

    line1 = lines[0]

    line2 = lines[1]

    line3 = lines[2]


    height, width = image_cv.shape[:2]


    scale_ratio = (
        width /
        REFERENCE_WIDTH
    )


    font_size = max(
        1,
        round(
            REFERENCE_FONT_SIZE *
            scale_ratio
        )
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

    font = ImageFont.truetype(
        font_path,
        font_size
    )


    image_rgb = cv2.cvtColor(
        image_cv,
        cv2.COLOR_BGR2RGB
    )


    pil_image = Image.fromarray(
        image_rgb
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


st.title("🕒 Timestamp Generator")

st.caption(
    "AVHershey Simplex Medium — watermark timestamp gaya GPS Map Camera"
)


if "timestamp_box" not in st.session_state:

    st.session_state.timestamp_box = ""


# ------------------------------------------------------------
# 1. UPLOAD FOTO UTAMA
# ------------------------------------------------------------

st.header("1. Upload Foto")

photo_file = st.file_uploader(
    "Pilih foto utama",
    type=["jpg", "jpeg", "png"],
    key="photo_uploader"
)


image_cv = None

if photo_file is not None:

    try:

        photo_pil = load_pil_image_fixed_orientation(
            photo_file
        )

        image_cv = cv2.cvtColor(
            np.array(photo_pil),
            cv2.COLOR_RGB2BGR
        )

    except Exception as error:

        st.error(
            f"❌ Foto tidak dapat dibaca: {error}"
        )

        image_cv = None


    if image_cv is not None:

        height, width = image_cv.shape[:2]

        st.success(
            f"File: {photo_file.name}  |  Resolusi: {width} x {height}"
        )

        st.image(
            cv2.cvtColor(
                image_cv,
                cv2.COLOR_BGR2RGB
            ),
            caption="Preview foto asli (orientasi sudah dinormalisasi)",
            use_container_width=True
        )


# ------------------------------------------------------------
# 2. MASUKKAN TIMESTAMP
# ------------------------------------------------------------

st.header("2. Masukkan Timestamp")

st.markdown(
    """
Ada 2 cara:

1. Ketik / paste manual 3 baris di kotak teks di bawah.
2. Upload screenshot timestamp, isi API key Gemini, klik
   **OCR (GEMINI AI)** — hasilnya otomatis masuk ke kotak teks.
   Cek dulu hasilnya sebelum klik **GENERATE**.

Baris 1 = Koordinat
Baris 2 = Lokasi
Baris 3 = Tanggal & Waktu
"""
)


with st.expander("🔍 OCR dari Screenshot (Gemini AI)"):

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

    screenshot_file = st.file_uploader(
        "Upload screenshot timestamp",
        type=["jpg", "jpeg", "png"],
        key="screenshot_uploader"
    )

    screenshot_image = None

    if screenshot_file is not None:

        try:

            screenshot_image = load_pil_image_fixed_orientation(
                screenshot_file
            )

            st.image(
                screenshot_image,
                caption="Preview screenshot yang akan di-OCR",
                use_container_width=True
            )

        except Exception as error:

            st.error(
                f"❌ Screenshot tidak dapat dibaca: {error}"
            )

            screenshot_image = None

    if st.button(
        "OCR (GEMINI AI)",
        type="secondary"
    ):

        if screenshot_image is None:

            st.error(
                "❌ Belum ada screenshot yang diupload."
            )

        elif not gemini_api_key:

            st.error(
                "❌ API key Gemini belum dikonfigurasi di server "
                "(Streamlit Secrets)."
            )

        else:

            try:

                with st.spinner(
                    "⏳ Meminta Gemini membaca timestamp..."
                ):

                    ocr_result = ocr_extract_text_gemini(
                        screenshot_image,
                        gemini_api_key
                    )


                if ocr_result:

                    st.session_state.timestamp_box = ocr_result

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


timestamp_text = st.text_area(
    "Timestamp (3 baris)",
    height=130,
    placeholder=(
        "-5.7297568, 105.6231008\n"
        "Sukaratu, Lampung Selatan, Lampung\n"
        "18/8/2026 10:12:35 WIB"
    ),
    key="timestamp_box"
)


# ------------------------------------------------------------
# 3. GENERATE
# ------------------------------------------------------------

st.header("3. Generate")

if st.button(
    "GENERATE TIMESTAMP",
    type="primary"
):

    if image_cv is None:

        st.error(
            "❌ Upload foto dulu di langkah 1."
        )

    elif not timestamp_text.strip():

        st.error(
            "❌ Timestamp belum diisi."
        )

    else:

        try:

            with st.spinner(
                "Menggambar timestamp..."
            ):

                pil_image, info = generate_timestamp_image(
                    image_cv,
                    timestamp_text
                )


            st.success(
                "✅ TIMESTAMP BERHASIL DIBUAT"
            )

            with st.expander(
                "Detail timestamp & rendering",
                expanded=True
            ):

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
- Font Size: {info['font_size']}px
- Scale Ratio: {info['scale_ratio']:.4f}
- Outline Width: {info['outline_width']}px
- Letter Spacing: {info['letter_spacing']:.2f}px
- Left Margin: {info['left_margin']}px
- Bottom Margin: {info['bottom_margin']}px
- Line Spacing: {info['line_spacing']}px
"""
                )


            st.image(
                pil_image,
                caption="Preview hasil",
                use_container_width=True
            )


            # ------------------------------------------------
            # SIAPKAN FILE UNTUK DOWNLOAD
            # ------------------------------------------------

            name, ext = os.path.splitext(
                photo_file.name
            )

            if not ext:

                ext = ".jpg"

            output_file_name = (
                name +
                "_TIMESTAMP_V7_4" +
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

                st.download_button(
                    label="⬇️ DOWNLOAD HASIL",
                    data=encoded_bytes.tobytes(),
                    file_name=output_file_name,
                    mime=mime_type,
                    type="primary"
                )

            else:

                st.error(
                    "❌ Gagal encode gambar hasil."
                )


        except Exception as error:

            st.error(
                f"❌ ERROR: {error}"
            )


# ------------------------------------------------------------
# CREDIT
# ------------------------------------------------------------

st.divider()

st.caption(
    "Dibuat oleh: **Matthew Artur Panahatan Sitorus** & "
    "**Nikita Adriella Virginia Jacob**"
)
