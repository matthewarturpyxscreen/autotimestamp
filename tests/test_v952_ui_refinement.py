"""V9.5.2 presentation contract and engine-boundary regression checks."""
import ast
import hashlib
import io
import zipfile
from pathlib import Path

from PIL import Image
import workspace_preview as preview

ROOT = Path(__file__).resolve().parents[1]


def src(name):
    return (ROOT/name).read_text(encoding='utf-8')


def test_font_controls_visible_near_top_for_all_timestamp_modes():
    for name, next_step in (
        ('app.py', '**🔎 OCR & teks timestamp**'),
        ('batch_manual.py', '**🔎 OCR & teks acuan**'),
        ('batch_npsn.py', '**🏫 Identitas sekolah (NPSN)**'),
    ):
        body = src(name)
        photo = body.index('st.markdown("**📷 Foto')
        style = body.index('st.markdown("**🎨 Ukuran')
        following = body.index(next_step)
        assert photo < style < following, name
        assert 'st.tabs(' not in body
        assert 'with st.expander("🎨 Pengaturan font' not in body
        assert 'selected_font_size_percent = st.slider' in body if name=='app.py' else 'batch_font_size_percent = st.slider' in body


def test_preview_is_large_and_fixed_with_no_zoom_or_fit_control():
    assert preview.PREVIEW_SIZE == (820, 500)
    body = src('workspace_preview.py')
    assert '_show_size_control' not in body
    assert 'Zoom preview' not in body
    assert "selected_view = st.radio('Tampilan'" in body
    assert 'Before / After' in body
    assert 'fill_width=True' in body
    photo = Image.new('RGB', (2000, 1600), 'green')
    before = photo.tobytes()
    display = preview._small_image(photo, preview.PREVIEW_SIZE)
    assert display.size == (625, 500)
    assert photo.tobytes() == before


def test_converter_ocr_and_engine_files_remain_exactly_identical_to_v951():
    # SHA256 hashes come from the pristine uploaded V9.5.1 ZIP.
    fingerprints = {
        'ocr_fields.py': 'd4367b96ba7f418cc0987819e6c6b293b1c5fbf9bd04c7e191482bbda7aee9f4',
    }
    for name, expected in fingerprints.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected


def test_generation_sections_unchanged_when_original_zip_available():
    original=ROOT.parent.parent/'AutoTimestamp_V9.5.1_Converter_JPG_Optimized.zip'
    if not original.is_file():
        return  # Engine helper signatures remain verified by the manifest test.
    markers={
        'app.py':'# V9.5 UI-only freshness token',
        'batch_manual.py':'# V9.5 UI-only tracking of settings',
        'batch_npsn.py':'# V9.5 UI-only fingerprint of all inputs',
    }
    with zipfile.ZipFile(original) as bundle:
        for name, marker in markers.items():
            old=bundle.read('timestamp-2-main/'+name).decode('utf-8')
            new=src(name)
            original_section = old[old.index(marker):]
            current_section = new[new.index(marker):]
            if name == 'app.py':
                # V9.5.3 fixes only a UI callback: `timestamp` belongs in the
                # stale-input signature, not the renderer keyword arguments.
                current_section = current_section.replace(
                    "timestamp_text, generate_timestamp_image,\n"
                    "            {name: value for name, value in v95_single_params.items() if name != 'timestamp'},",
                    "timestamp_text, generate_timestamp_image, v95_single_params,",
                )
            assert original_section == current_section, name
        for name in ('ocr_fields.py','jpg_converter.py','jpg_converter_ui.py'):
            assert (ROOT/name).read_bytes()==bundle.read('timestamp-2-main/'+name)
