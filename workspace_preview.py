"""AutoTimestamp V9.5 UI-only previews and signature utilities.

No OCR, batch scheduling, font or output-encoding behavior lives here.
The live view calls the existing generate_timestamp_image callback, and the
finished view reads original rendered bytes without modifying them.
"""

import base64
import hashlib
import html
import io
import json
import zipfile
from collections import OrderedDict
from types import SimpleNamespace
from pyx_image_job_guard import image_job_slot, ImageServerBusy

import numpy as np
from PIL import Image, ImageOps

try:
    import streamlit as st
except ImportError:  # Pure utility tests can run without Streamlit.
    st = None

PREVIEW_SIZE = (820, 500)
THUMBNAIL_SIZE = (140, 90)
VISIBLE_THUMBS = 5
CLOUD_PREVIEW_MAX_EDGE = 1600  # Only the on-screen rendering; never final exports.
CLOUD_THUMB_CACHE_SIZE = 20
FILE_HASH_CACHE_SIZE = 256


def _small_image(image, bounds):
    """Return a reduced display image; never mutate the caller's pixels."""
    if not isinstance(image, Image.Image):
        image = Image.fromarray(image)
    reduced = ImageOps.exif_transpose(image)
    reduced.thumbnail(bounds, Image.Resampling.LANCZOS)
    return reduced.convert('RGB')


def compact_preview(image, caption='', bounds=PREVIEW_SIZE, *, fill_width=False):
    """Only resize display pixels, not source or exported image bytes."""
    st.image(_small_image(image, bounds), caption=caption, use_container_width=fill_width)


def _read_photo(uploaded_file, load_image_fn):
    """Decode a display-only image at bounded size (JPEG draft if available).

    Batch Generate continues to use load_image_fn on the ORIGINAL upload.
    Unsupported formats fall back to the existing image loader.
    """
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as source:
            source.draft('RGB', (CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE))
            # Resize BEFORE EXIF transpose. Otherwise a rotated 12MP PNG
            # can allocate two full-resolution images just for a small UI view.
            source.thumbnail((CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
            photo = ImageOps.exif_transpose(source)
            return photo.convert('RGB')
    except (OSError, ValueError):
        uploaded_file.seek(0)
        photo = load_image_fn(uploaded_file)
        return _small_image(photo, (CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE))


def read_image_dimensions(uploaded_file):
    """Exact EXIF-oriented size without decoding the source pixels.

    Both original batch font-lock calculators only inspect `image.size`;
    using this *metadata-only* loader produces identical font calculations.
    The original full-resolution loader is still used to Generate every file.
    """
    position = uploaded_file.tell()
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            width, height = image.size
            if image.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
        return SimpleNamespace(size=(width, height))
    finally:
        uploaded_file.seek(position)


def cached_single_photo(uploaded_file, load_image_fn):
    """Keep ONE bounded preview image and its original EXIF dimensions.

    The cache is per Streamlit browser session, never process-wide, and only
    uses a stable immutable Streamlit UploadedFile id. Generic mutable file
    objects are always re-read so changes cannot be hidden by a cache key.
    """
    file_id = getattr(uploaded_file, 'file_id', None)
    stable = isinstance(file_id, str) and getattr(uploaded_file, 'size', None) is not None and st is not None
    identity = (file_id, uploaded_file.name, uploaded_file.size) if stable else None
    if stable:
        previous = st.session_state.get('v952422_single_photo')
        if previous and previous['identity'] == identity:
            return previous['image'], previous['dimensions']
    preview = _read_photo(uploaded_file, load_image_fn)
    dimensions = read_image_dimensions(uploaded_file).size
    if stable:
        st.session_state['v952422_single_photo'] = {
            'identity': identity, 'image': preview, 'dimensions': dimensions,
        }
    return preview, dimensions


def _gallery_thumbnail(uploaded_file, load_image_fn, fingerprint):
    """Bound per-session gallery thumbnail cache; no photo-sized cache entries."""
    if st is None:
        return _small_image(_read_photo(uploaded_file, load_image_fn), THUMBNAIL_SIZE)
    cache = st.session_state.setdefault('v9524_small_thumb_cache', OrderedDict())
    if fingerprint in cache:
        cache.move_to_end(fingerprint)
        return cache[fingerprint]
    thumb = _small_image(_read_photo(uploaded_file, load_image_fn), THUMBNAIL_SIZE)
    cache[fingerprint] = thumb
    if len(cache) > CLOUD_THUMB_CACHE_SIZE:
        cache.popitem(last=False)
    return thumb


def _read_result(zip_source, filename):
    source = io.BytesIO(zip_source) if isinstance(zip_source, (bytes, bytearray)) else zip_source
    with zipfile.ZipFile(source, 'r') as archive:
        with Image.open(io.BytesIO(archive.read(filename))) as photo:
            photo.draft('RGB', (CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE))
            photo.thumbnail((CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
            return photo.convert('RGB')


def cached_batch_result_preview(result, filename, cache_key):
    """Avoid reopening the ZIP and JPEG-decompressing a full result each rerun.

    Only the active output photo is cached; the ZIP and encoded export image
    remain unchanged and never enter this preview cache as large byte strings.
    """
    key = cache_key + '_active_finished'
    previous = st.session_state.get(key)
    identity = (id(result), filename)
    if previous and previous['identity'] == identity:
        return previous['image']
    zip_source = result.get('zip_file')
    if zip_source is None:
        zip_source = result['zip_bytes']
    preview = _read_result(zip_source, filename)
    st.session_state[key] = {'identity': identity, 'image': preview}
    return preview


def file_fingerprint(file):
    """Hash uploads once per immutable Streamlit file id within a session.

    Generic/mutable BytesIO input is ALWAYS rehashed. This preserves the
    original change detection on tests/scripts that modify buffer contents.
    Only Streamlit UploadedFile's stable immutable file_id is memoized.
    """
    name = getattr(file, 'name', '')
    file_id = getattr(file, 'file_id', None)
    size = getattr(file, 'size', None)
    use_cache = file_id is not None and isinstance(file_id, str) and size is not None and st is not None
    cache_key = (file_id, name, size) if use_cache else None
    cache = st.session_state.setdefault('v9524_upload_sha_cache', OrderedDict()) if use_cache else None
    if cache is not None and cache_key in cache:
        cache.move_to_end(cache_key)
        return name, size, cache[cache_key]
    if hasattr(file, 'getvalue'):
        payload = file.getvalue()
    else:
        pos = file.tell()
        try:
            file.seek(0)
            payload = file.read()
        finally:
            file.seek(pos)
    digest = hashlib.sha256(payload).hexdigest()
    if cache is not None:
        cache[cache_key] = digest
        if len(cache) > FILE_HASH_CACHE_SIZE:
            cache.popitem(last=False)
    return (name, len(payload), digest)


def input_signature(files, params):
    """Deterministic signature of inputs that affect output bytes, not UI state."""
    payload = {
        'files': [file_fingerprint(f) for f in files],
        'params': params,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def output_is_stale(last_signature, current_signature):
    return bool(last_signature and last_signature != current_signature)


def preview_locked_size(files, load_fn, existing_calculator, font_mode,
                        font_percent, fixed_px, cache_key):
    """Memoize only the preview's font-lock measurement, not Generate logic."""
    signature = input_signature(files, {
        'font_mode': font_mode, 'font_percent': font_percent,
        'fixed_px': fixed_px,
    })
    state_key = f'v95_preview_font_lock_{cache_key}'
    previous = st.session_state.get(state_key)
    if previous and previous['signature'] == signature:
        return previous['size']
    # Preserve the original calculation EXACTLY; just avoid decoding RGB
    # image buffers when its sole input requirement is photo dimensions.
    dimensions_only = (getattr(existing_calculator, '__name__', '') == '_calculate_locked_font_size_px'
                       and getattr(existing_calculator, '__module__', '') in ('batch_manual', 'batch_npsn'))
    calculator_loader = read_image_dimensions if dimensions_only else load_fn
    size, _info = existing_calculator(files, calculator_loader, font_mode, font_percent, fixed_px)
    st.session_state[state_key] = {'signature': signature, 'size': size}
    return size


def build_live_preview(photo_pil, raw_timestamp, generate_fn, render_options):
    """Call the unchanged production renderer; return preview pixels ONLY."""
    if not raw_timestamp or not raw_timestamp.strip():
        return None
    photo_cv = np.array(ImageOps.exif_transpose(photo_pil).convert('RGB'))
    pil_image, _info = generate_fn(photo_cv, raw_timestamp, **render_options)
    return pil_image


def build_cloud_live_preview(photo_pil, raw_timestamp, generate_fn, render_options):
    """Use the ORIGINAL renderer on a bounded preview canvas.

    This function never changes Generate/export pixels. For fixed-pixel and
    locked font settings, pixels are scaled down with the canvas so the
    apparent proportions remain consistent. Small images use original sizes.
    """
    longest = max(photo_pil.size)
    if longest <= CLOUD_PREVIEW_MAX_EDGE:
        return build_live_preview(photo_pil, raw_timestamp, generate_fn, render_options)
    scale = CLOUD_PREVIEW_MAX_EDGE / longest
    small = photo_pil.copy()
    small.thumbnail((CLOUD_PREVIEW_MAX_EDGE, CLOUD_PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
    scaled_opts = dict(render_options)
    for name in ('fixed_font_size_px', 'font_size_px_override'):
        value = scaled_opts.get(name)
        if value is not None:
            scaled_opts[name] = max(1, round(float(value) * scale))
    return build_live_preview(small, raw_timestamp, generate_fn, scaled_opts)


def _cached_live_preview(photo_pil, raw_timestamp, generate_fn, render_options, cache_key, source_fingerprint=None):
    """Cache one small live image per active mode; never cache export bytes."""
    key = 'v95_live_' + cache_key
    signature = hashlib.sha256(
        (raw_timestamp + json.dumps(render_options, sort_keys=True, default=str)).encode('utf-8')
        + (repr(source_fingerprint).encode('utf-8') if source_fingerprint is not None
           else np.asarray(photo_pil).tobytes())
    ).hexdigest()
    previous = st.session_state.get(key)
    if previous and previous['signature'] == signature:
        return previous['preview']
    # Live preview is lower priority than Generate. Do not start additional
    # costly PIL/NumPy renderers when another user is already generating.
    try:
        with image_job_slot():
            rendered = build_cloud_live_preview(photo_pil, raw_timestamp, generate_fn, render_options)
    except ImageServerBusy:
        return None  # User can preview again after the active job completes.
    if rendered is None:
        return None
    preview = _small_image(rendered, (1120, 720))
    st.session_state[key] = {'signature': signature, 'preview': preview}
    return preview


def _photo_button_css(container_key, thumb, active):
    """Clickable thumbnail: real Streamlit button with an image background.

    No JS, third-party component or query-param navigation. The button keeps
    its accessible text while the image is rendered on its face.
    """
    buffer = io.BytesIO()
    _small_image(thumb, THUMBNAIL_SIZE).save(buffer, format='JPEG', quality=75)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    border = '#BF408A' if active else '#CBD5E1'
    return (
        '<style>'
        f'.st-key-{container_key} button {{'
        f'background-image:url("data:image/jpeg;base64,{encoded}");'
        'background-position:center;background-size:contain;background-repeat:no-repeat;'
        'height:76px; width:100%;padding:3px;'
        f'border:2px solid {border}; border-radius:9px;'
        'font-size:0px;color:transparent;'
        '}'
        f'.st-key-{container_key} button:hover {{border-color:#BF408A;}}'
        '</style>'
    )


def _display_active(source, after, selected_view, filename, finished):
    """Fixed-size responsive preview. No zoom or fit controls."""
    bounds = PREVIEW_SIZE
    if selected_view == 'Before / After' and after is not None:
        left, right = st.columns(2)
        with left:
            compact_preview(source, caption='Before · foto asli', bounds=(bounds[0] // 2, bounds[1]), fill_width=True)
        with right:
            compact_preview(after, caption=('After · hasil generate' if finished else 'After · live preview'),
                            bounds=(bounds[0] // 2, bounds[1]), fill_width=True)
    elif selected_view == 'Foto asli' or after is None:
        compact_preview(source, caption=f'Foto asli · {filename}', bounds=bounds, fill_width=True)
    else:
        compact_preview(after, caption=f'{selected_view} · {filename}', bounds=bounds, fill_width=True)


def _gallery_identity(files):
    # Include bytes, not just filename, so a replacement with the same name resets selection.
    return tuple(file_fingerprint(f) for f in files)


def batch_gallery(sorted_files, result, load_image_fn, mode, uploader_version,
                  *, generate_fn=None, live_timestamp=None, live_options=None,
                  stale=False, live_caption=None):
    """Clickable photo tiles, real-engine live view and before/after.

    `live_timestamp` is the current reference overlay for the ACTIVE image.
    The production batch engine still independently chooses final random
    timestamps and any enabled coordinate jitter at Generate time.
    """
    if not sorted_files:
        st.info('Upload foto dari panel kiri untuk menampilkan preview.')
        return

    names = [f.name for f in sorted_files]
    gallery_key = f'v95_gallery_{mode}_{uploader_version}'
    gallery_sig_key = gallery_key + '_source_signature'
    identity = _gallery_identity(sorted_files)
    if st.session_state.get(gallery_sig_key) != identity:
        st.session_state[gallery_sig_key] = identity
        st.session_state[gallery_key] = 0
        st.session_state.pop(gallery_key + '_view', None)

    active_index = max(0, min(st.session_state.get(gallery_key, 0), len(names) - 1))
    st.session_state[gallery_key] = active_index
    active_name = names[active_index]
    finished = bool(result and (result.get('zip_file') or result.get('zip_bytes')) and not stale)

    st.markdown(f'**Foto {active_index + 1} / {len(names)} · {html.escape(active_name)}**')
    source = None
    finished_after = None
    live_after = None
    try:
        # Keep only one currently viewed reduced source image per session.
        # Typing text/adjusting controls no longer decodes the 12MP upload.
        display_cache_key = gallery_key + '_active_source'
        cache_entry = st.session_state.get(display_cache_key)
        if cache_entry and cache_entry['fingerprint'] == identity[active_index]:
            source = cache_entry['photo']
        else:
            source = _read_photo(sorted_files[active_index], load_image_fn)
            st.session_state[display_cache_key] = {
                'fingerprint': identity[active_index], 'photo': source,
            }
        if finished:
            finished_after = cached_batch_result_preview(result, active_name, gallery_key)
        if generate_fn and live_timestamp and live_options is not None:
            live_after = _cached_live_preview(source, live_timestamp, generate_fn, live_options,
                                              gallery_key, identity[active_index])
    except Exception as error:
        st.warning(f'Preview tidak dapat ditampilkan: {error}')
        return

    choices = ['Live Preview', 'Foto asli', 'Before / After'] if live_after is not None else ['Foto asli']
    if finished:
        choices.insert(1 if live_after is not None else 0, 'Hasil Generate')
    view_key = gallery_key + '_view'
    result_marker_key = gallery_key + '_result_object'
    if finished and st.session_state.get(result_marker_key) != id(result):
        st.session_state[result_marker_key] = id(result)
        st.session_state[view_key] = 'Hasil Generate'
    if st.session_state.get(view_key) not in choices:
        st.session_state[view_key] = 'Hasil Generate' if finished else choices[0]
    selected_view = st.radio('Tampilan', choices, key=view_key, horizontal=True)
    after = finished_after if selected_view == 'Hasil Generate' else live_after
    if selected_view == 'Before / After' and finished:
        after = finished_after
    _display_active(source, after, selected_view, active_name,
                    finished=(selected_view == 'Hasil Generate' or
                              (selected_view == 'Before / After' and finished)))
    if live_after is not None and selected_view in ('Live Preview', 'Before / After') and not finished:
        st.caption(live_caption or 'Live preview adalah contoh visual. Jam/koordinat acak final ditetapkan saat Generate.')

    back, previous, next_, forward = st.columns(4)
    for column, label, target, suffix in (
        (back, '⏮ 5 Foto', max(0, active_index - VISIBLE_THUMBS), 'back'),
        (previous, '◀', active_index - 1, 'prev'),
        (next_, '▶', active_index + 1, 'next'),
        (forward, '5 Foto ⏭', min(len(names) - 1, active_index + VISIBLE_THUMBS), 'forward'),
    ):
        with column:
            if st.button(label, key=f'{gallery_key}_{suffix}',
                         disabled=target < 0 or target >= len(names) or target == active_index,
                         use_container_width=True):
                st.session_state[gallery_key] = target
                st.rerun()

    start = (active_index // VISIBLE_THUMBS) * VISIBLE_THUMBS
    cells = st.columns(VISIBLE_THUMBS, gap='small')
    for index in range(start, min(start + VISIBLE_THUMBS, len(names))):
        with cells[index - start]:
            name = names[index]
            container_key = f'v95_thumb_{mode}_{uploader_version}_{index}'
            try:
                thumbnail = _gallery_thumbnail(sorted_files[index], load_image_fn, identity[index])
                style = _photo_button_css(container_key, thumbnail, active_index == index)
            except Exception:
                style = ''
            with st.container(key=container_key):
                if style:
                    st.markdown(style, unsafe_allow_html=True)
                if st.button(f'Foto {index + 1}', key=f'{gallery_key}_pick_{index}',
                             help=f'Pilih foto {index + 1}: {name}', use_container_width=True):
                    st.session_state[gallery_key] = index
                    st.rerun()
            st.caption(f'{index + 1}. {name[:12] + "…" if len(name) > 13 else name}')
    if len(names) > VISIBLE_THUMBS:
        st.caption(f'Thumbnail {start + 1}–{min(start + VISIBLE_THUMBS, len(names))} dari {len(names)} foto.')


def single_preview(image_cv, result, text, render_fn, options, signature, last_signature,
                   uploader_version, source_scale=1.0):
    """Single-photo workspace. Output download/UI remain handled by app.py."""
    if image_cv is None:
        st.info('Upload foto dari panel kiri untuk menampilkan preview.')
        return
    key = f'v95_single_{uploader_version}'
    original = image_cv if isinstance(image_cv, Image.Image) else Image.fromarray(image_cv)
    finished = bool(result and not output_is_stale(last_signature, signature))
    finished_after = result['pil_image'] if finished else None
    live_after = None
    if text.strip():
        try:
            preview_options = dict(options)
            if source_scale < 1.0:
                for name in ('fixed_font_size_px', 'font_size_px_override'):
                    if preview_options.get(name) is not None:
                        preview_options[name] = max(1, round(float(preview_options[name]) * source_scale))
            live_after = _cached_live_preview(original, text, render_fn, preview_options, key, signature)
        except Exception as error:
            st.warning(f'Live preview gagal: {error}')
    choices = ['Live Preview', 'Foto asli', 'Before / After'] if live_after is not None else ['Foto asli']
    if finished:
        choices.insert(1, 'Hasil Generate')
    view_key = key + '_view'
    result_marker_key = key + '_result_object'
    if finished and st.session_state.get(result_marker_key) != id(result):
        st.session_state[result_marker_key] = id(result)
        st.session_state[view_key] = 'Hasil Generate'
    if st.session_state.get(view_key) not in choices:
        st.session_state[view_key] = 'Hasil Generate' if finished else choices[0]
    selected_view = st.radio('Tampilan', choices, key=view_key, horizontal=True)
    after = finished_after if selected_view == 'Hasil Generate' else live_after
    if selected_view == 'Before / After' and finished:
        after = finished_after
    _display_active(original, after, selected_view, 'Foto utama',
                    finished=(selected_view == 'Hasil Generate' or
                              (selected_view == 'Before / After' and finished)))
    if live_after is not None and not finished:
        st.caption('Live preview memakai renderer yang sama dengan Generate; download tetap memerlukan Generate.')
