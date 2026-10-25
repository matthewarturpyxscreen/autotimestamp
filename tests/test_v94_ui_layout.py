"""V9.4.1 UI-only checks. Tests intentionally do not need Streamlit runtime."""
from pathlib import Path
from io import BytesIO
import zipfile

from PIL import Image
from workspace_preview import _small_image, _read_result, PREVIEW_SIZE, THUMBNAIL_SIZE

ROOT = Path(__file__).resolve().parents[1]


def _source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_wide_workspace_and_three_modes_preserved():
    src = _source("app.py")
    assert 'layout="wide"' in src
    for mode in ["📷 Satu Foto", "🗂️ Batch Manual", "🗂️ Batch NPSN Online"]:
        assert mode in src
    assert "with controls_col:" in src
    assert "with preview_col:" in src


def test_all_modes_have_compact_tabs_instead_of_fixed_scroll():
    for name in ["app.py", "batch_manual.py", "batch_npsn.py"]:
        src = _source(name)
        assert 'with st.container(height=610, border=True):' not in src
        assert 'with st.container(border=True):' in src
        assert 'tab_foto' in src and 'tab_style_input' in src
        assert 'compact_preview' in src or 'batch_gallery' in src
    for name in ["batch_manual.py", "batch_npsn.py"]:
        src = _source(name)
        assert 'st.columns([1.05, 1.35], gap="large")' in src
        assert 'with st.expander("🎨 Pengaturan font' in src
        assert 'st.download_button(' in src
        assert 'batch_gallery(sorted_files, result,' in src
        assert 'batch_gallery(sorted_files, None,' in src


def test_ocr_and_existing_batch_generation_calls_preserved():
    app = _source("app.py")
    manual = _source("batch_manual.py")
    npsn = _source("batch_npsn.py")
    assert "ocr_extract_text_gemini(" in app
    assert "ocr_extract_text_fn(" in manual
    assert "parse_batch_timestamp_reference(timestamp_reference_text)" in manual
    assert "lookup_npsn_online_cached(current_npsn)" in npsn
    assert "generate_timestamp_fn(" in manual
    assert "generate_timestamp_fn(" in npsn


def test_preview_images_only_downscale_for_display():
    original = Image.new("RGB", (1800, 1200), color="white")
    compact = _small_image(original, PREVIEW_SIZE)
    mini = _small_image(original, THUMBNAIL_SIZE)
    assert compact.width <= 560 and compact.height <= 320
    assert mini.width <= 160 and mini.height <= 90
    assert original.size == (1800, 1200)  # full-resolution original untouched


def test_can_preview_any_output_photo_from_existing_zip():
    image_a = Image.new("RGB", (950, 700), color="red")
    image_b = Image.new("RGB", (950, 700), color="blue")
    buffers = []
    for image in (image_a, image_b):
        b = BytesIO()
        image.save(b, format="PNG")
        buffers.append(b.getvalue())
    zip_output = BytesIO()
    with zipfile.ZipFile(zip_output, "w") as z:
        z.writestr("1.png", buffers[0])
        z.writestr("2.png", buffers[1])
    assert _read_result(zip_output.getvalue(), "2.png").getpixel((0, 0)) == (0, 0, 255)
    with zipfile.ZipFile(BytesIO(zip_output.getvalue()), "r") as z:
        assert z.read("1.png") == buffers[0]
        assert z.read("2.png") == buffers[1]
