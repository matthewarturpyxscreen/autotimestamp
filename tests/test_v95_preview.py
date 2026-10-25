"""V9.5 UI & engine-boundary regression checks without hosted Streamlit/Gemini."""
import ast
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import workspace_preview as wp


class Upload(io.BytesIO):
    def __init__(self, name, content):
        super().__init__(content)
        self.name = name


def _png(colour='red', size=(800, 600)):
    file = io.BytesIO()
    Image.new('RGB', size, colour).save(file, format='PNG')
    return file.getvalue()


def test_signature_changes_with_pixels_and_also_with_timestamps():
    a = Upload('1.png', _png('red'))
    b = Upload('1.png', _png('blue'))
    sig1 = wp.input_signature([a], {'text': 'A', 'bold': False})
    assert sig1 == wp.input_signature([a], {'bold': False, 'text': 'A'})
    assert sig1 != wp.input_signature([b], {'text': 'A', 'bold': False})
    assert sig1 != wp.input_signature([a], {'text': 'B', 'bold': False})
    assert sig1 != wp.input_signature([a], {'text': 'A', 'bold': True})
    assert wp.output_is_stale(sig1, wp.input_signature([a], {'text': 'B'}))
    assert not wp.output_is_stale(None, sig1)
    assert not wp.output_is_stale(sig1, sig1)


def test_hashing_upload_does_not_change_stream_cursor():
    photo = Upload('4.png', _png())
    photo.seek(42)
    wp.file_fingerprint(photo)
    wp.input_signature([photo], {'mode': 'batch_manual'})
    assert photo.tell() == 42


def test_live_calls_production_renderer_without_modifying_source():
    photo = Image.new('RGB', (750, 300), (25, 100, 200))
    before = photo.tobytes()
    calls = []

    def production_renderer(pixels, text, **params):
        calls.append((pixels.shape, text, params))
        out = Image.fromarray(pixels.copy())
        out.putpixel((0, 0), (255, 255, 255))
        return out, {'font_name': 'unchanged'}

    params = {'bold_enabled': True, 'font_size_percent': 5.0}
    result = wp.build_live_preview(photo, '1, 2\nAlamat\n24/10/2026 13:00 WIB',
                                   production_renderer, params)
    assert calls == [((300, 750, 3), '1, 2\nAlamat\n24/10/2026 13:00 WIB', params)]
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert photo.tobytes() == before


def test_live_skips_renderer_for_blank_timestamp():
    def renderer(*args, **kwargs):
        raise AssertionError('should not run')
    assert wp.build_live_preview(Image.new('RGB', (50, 50)), '', renderer, {}) is None


def test_zoom_changes_display_only_and_does_not_touch_photo():
    original = Image.new('RGB', (2800, 1800), (40, 50, 60))
    before = original.tobytes()
    fit = wp._small_image(original, wp.PREVIEW_SIZE)
    zoom = wp._small_image(original, (1120, 640))
    assert fit.size == (498, 320)
    assert zoom.size == (996, 640)
    assert original.size == (2800, 1800)
    assert original.tobytes() == before


def test_clickable_photo_tile_has_image_background_and_active_outline():
    src = Image.new('RGB', (400, 200), 'purple')
    css = wp._photo_button_css('v95_thumb_test_0', src, active=True)
    assert '.st-key-v95_thumb_test_0 button' in css
    assert 'data:image/jpeg;base64,' in css
    assert 'border:2px solid #BF408A' in css
    assert 'height:76px' in css
    assert 'onclick' not in css.lower()  # Real Streamlit buttons, no browser hacks.


def test_zip_preview_is_not_reencoded_or_modified():
    bytes_ = _png('green', (1100, 700))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        output.writestr('1.png', bytes_)
    output_bytes = stream.getvalue()
    assert wp._read_result(output_bytes, '1.png').size == (1100, 700)
    with zipfile.ZipFile(io.BytesIO(output_bytes)) as archive:
        assert archive.read('1.png') == bytes_


def test_all_three_modes_wired_and_engine_not_duplicated():
    root = Path(__file__).resolve().parents[1]
    app = (root / 'app.py').read_text()
    manual = (root / 'batch_manual.py').read_text()
    npsn = (root / 'batch_npsn.py').read_text()
    assert 'single_preview(' in app
    assert 'generate_fn=generate_timestamp_fn' in manual
    assert 'generate_fn=generate_timestamp_fn' in npsn
    assert 'v95_single_stale' in app
    assert 'v95_manual_stale' in manual
    assert 'v95_npsn_stale' in npsn
    assert 'download_button(' in app
    assert 'zip_file.writestr(uploaded_file.name, encoded_bytes)' in manual
    assert 'zip_file.writestr(uploaded_file.name, encoded_bytes)' in npsn


def test_core_ast_matches_v941_reference_hashes():
    # These hashes were captured from the V9.4.1 ZIP before modifications.
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'CORE_V941_AST_SHA256.json').read_text())
    import hashlib
    for filename, names in manifest.items():
        code = ast.parse((root / filename).read_text())
        functions = {n.name: n for n in code.body if isinstance(n, ast.FunctionDef)}
        for name, old_hash in names.items():
            current = hashlib.sha256(ast.dump(functions[name], include_attributes=False).encode()).hexdigest()
            assert current == old_hash, (filename, name)

class _FakeUI:
    """Minimal Streamlit double for click-navigation integration tests."""
    def __init__(self, clicked_key=None, view=None):
        self.clicked_key = clicked_key
        self.view = view
        self.session_state = {}
        self.images = []
        self.markdown_text = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def caption(self, *args, **kwargs): pass
    def markdown(self, text, **kwargs): self.markdown_text.append(text)
    def image(self, img, **kwargs): self.images.append(img.copy())
    def columns(self, n, **kwargs): return [self for _ in range(n if isinstance(n, int) else len(n))]
    def container(self, **kwargs): return self
    def radio(self, label, options, key=None, **kwargs):
        chosen = self.view if self.view in options else options[0]
        self.session_state[key] = chosen
        return chosen
    def slider(self, label, minimum, maximum, value=None, **kwargs): return value
    def button(self, label, key=None, **kwargs): return key == self.clicked_key
    def rerun(self): raise _ExpectedRerun()


class _ExpectedRerun(Exception):
    pass


def test_clicking_actual_thumbnail_button_selects_another_photo(monkeypatch):
    files = [Upload('1.png', _png('red')), Upload('2.png', _png('blue'))]
    fake = _FakeUI(clicked_key='v95_gallery_manual_0_pick_1')
    monkeypatch.setattr(wp, 'st', fake)
    with __import__('pytest').raises(_ExpectedRerun):
        wp.batch_gallery(files, None, lambda f: Image.open(f).copy(), 'manual', 0)
    assert fake.session_state['v95_gallery_manual_0'] == 1
    assert any('data:image/jpeg;base64,' in text for text in fake.markdown_text)
    fake.clicked_key = None
    fake.images.clear()
    wp.batch_gallery(files, None, lambda f: Image.open(f).copy(), 'manual', 0)
    assert fake.images[0].getpixel((5, 5)) == (0, 0, 255)


def test_before_after_uses_same_live_engine_and_two_images(monkeypatch):
    files = [Upload('1.png', _png('red'))]
    fake = _FakeUI(view='Before / After')
    monkeypatch.setattr(wp, 'st', fake)
    calls = []
    def renderer(pixels, text, **options):
        calls.append((text, options))
        changed = pixels.copy()
        changed[:, :, :] = (0, 200, 0)
        return Image.fromarray(changed), {}
    wp.batch_gallery(files, None, lambda f: Image.open(f).copy(),
                     'manual', 42, generate_fn=renderer, live_timestamp='alamat',
                     live_options={'bold_enabled': False})
    assert calls == [('alamat', {'bold_enabled': False})]
    assert fake.images[0].getpixel((5, 5)) == (255, 0, 0)
    assert fake.images[1].getpixel((5, 5)) == (0, 200, 0)
    # Thumbnail is also its own image-backed clickable button, not a text-only menu.
    assert any('.st-key-v95_thumb_manual_42_0 button' in t for t in fake.markdown_text)


def test_locked_preview_font_measurement_is_cached_without_changing_engine(monkeypatch):
    fake = _FakeUI()
    monkeypatch.setattr(wp, 'st', fake)
    photo = Upload('1.png', _png())
    count = []
    def calculate(*args):
        count.append(args[2:])
        return 48, {'unchanged': True}
    a = wp.preview_locked_size([photo], None, calculate, 'short_edge', 5.0, 80, 'manual_0')
    b = wp.preview_locked_size([photo], None, calculate, 'short_edge', 5.0, 80, 'manual_0')
    assert (a, b) == (48, 48)
    assert len(count) == 1
    c = wp.preview_locked_size([photo], None, calculate, 'short_edge', 6.0, 80, 'manual_0')
    assert c == 48
    assert len(count) == 2


def test_stale_outputs_are_disabled_in_all_modes():
    root = Path(__file__).resolve().parents[1]
    for name, signal in [('app.py', 'v95_single_stale'),
                         ('batch_manual.py', 'v95_manual_stale'),
                         ('batch_npsn.py', 'v95_npsn_stale')]:
        source = (root / name).read_text()
        assert f'disabled={signal}' in source
