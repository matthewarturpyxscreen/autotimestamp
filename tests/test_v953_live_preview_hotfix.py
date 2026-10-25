"""V9.5.3: renderer signature mismatch regression, no changes to engine."""
import ast
from pathlib import Path

import numpy as np
from PIL import Image

import workspace_preview as preview

ROOT = Path(__file__).resolve().parents[1]


def test_single_mode_forwards_only_renderer_keyword_parameters():
    module = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
    renderer = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'generate_timestamp_image')
    permitted = {a.arg for a in renderer.args.args[2:]}
    single = next(n for n in ast.walk(module) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == 'single_preview')
    options_expr = single.args[4]
    # Evaluate ONLY the adapter argument expression, not the app or Streamlit.
    original = {
        'timestamp': '3.2060390, 99.2981530\nDesa Panombean Baru\n24/10/2026 14:36:41 WIB',
        'font_size_percent': 5.0,
        'font_size_mode': 'short_edge',
        'fixed_font_size_px': 80,
        'bold_enabled': True,
        'bold_strength_percent': 25,
    }
    options = eval(compile(ast.Expression(options_expr), '<preview_callback>', 'eval'),
                   {'v95_single_params': original})
    assert 'timestamp' in original  # Must remain in the stale-result signature.
    assert 'timestamp' not in options
    assert set(options) <= permitted
    assert options['bold_enabled'] is True
    assert len(options) == len(original) - 1

    # Strict production-like renderer; the original buggy adapter fails here.
    def strict_renderer(image_cv, raw_timestamp_text, font_size_percent=5.0,
                        font_size_mode='short_edge', fixed_font_size_px=80,
                        font_size_px_override=None, preserve_locked_font_size=False,
                        bold_enabled=False, bold_strength_percent=25):
        assert raw_timestamp_text == original['timestamp']
        assert bold_enabled is True
        return Image.fromarray(image_cv), {'rendered': True}

    photo = Image.new('RGB', (90, 90), 'white')
    rendered = preview.build_live_preview(photo, original['timestamp'], strict_renderer, options)
    assert isinstance(rendered, Image.Image)
    assert rendered.size == photo.size


def test_engine_and_converter_source_untouched_by_hotfix():
    # Ensures the converter, OCR logic, and batch flows remain unedited.
    import hashlib
    import zipfile
    original = ROOT.parent.parent / 'AutoTimestamp_V9.5.2_Separate_Controls_Large_Preview.zip'
    if not original.exists():
        return
    with zipfile.ZipFile(original) as archive:
        for name in ['workspace_preview.py', 'jpg_converter.py', 'jpg_converter_ui.py',
                     'batch_manual.py', 'batch_npsn.py', 'ocr_fields.py', 'requirements.txt']:
            assert (ROOT / name).read_bytes() == archive.read('timestamp-2-main/' + name), name
        old_app = archive.read('timestamp-2-main/app.py').decode('utf-8')
        new_app = (ROOT / 'app.py').read_text(encoding='utf-8')
        assert new_app.replace(
            "timestamp_text, generate_timestamp_image,\n"
            "            {name: value for name, value in v95_single_params.items() if name != 'timestamp'},",
            "timestamp_text, generate_timestamp_image, v95_single_params,",
        ) == old_app
