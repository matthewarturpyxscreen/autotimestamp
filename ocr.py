"""OCR screenshot timestamp memakai Gemini."""

from __future__ import annotations

import io
import re

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_EDGE_PX = 2000  # screenshot lebih besar dari ini tidak menambah akurasi, hanya memperlambat

PROMPT = """
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


def shrink_for_ocr(image):
    """Perkecil (kalau perlu) sebelum dikirim/di-hash. Return gambar baru atau yang sama."""
    if max(image.size) <= MAX_EDGE_PX:
        return image
    from PIL import Image

    copy = image.copy()
    copy.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
    return copy


def clean_ocr_text(raw_text: str) -> str:
    raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", (raw_text or "").strip())
    raw_text = re.sub(r"```$", "", raw_text.strip())
    return "\n".join(line.strip() for line in raw_text.splitlines() if line.strip())


def extract_text(pil_image, api_key: str) -> str:
    from google import genai  # import lambat -> baru dimuat saat OCR dipakai
    from google.genai import types as genai_types

    image = shrink_for_ocr(pil_image)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=[genai_types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png"), PROMPT],
    )
    return clean_ocr_text(response.text)
