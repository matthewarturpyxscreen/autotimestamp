"""Static verification for V9.4 workspace layout (does not require Streamlit)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_wide_workspace_and_three_modes():
    src = _source("app.py")
    assert 'layout="wide"' in src
    for mode in ["📷 Satu Foto", "🗂️ Batch Manual", "🗂️ Batch NPSN Online"]:
        assert mode in src
    assert "with controls_col:" in src
    assert "with preview_col:" in src
    assert "with st.container(height=610, border=True):" in src


def test_all_modes_have_two_panel_layout_and_scrollable_settings():
    for name in ["batch_manual.py", "batch_npsn.py"]:
        src = _source(name)
        assert 'st.columns([1.05, 1.35], gap="large")' in src
        assert 'with st.container(height=610, border=True):' in src
        assert 'with st.expander("🎨 Pengaturan font' in src
        assert 'st.download_button(' in src


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
