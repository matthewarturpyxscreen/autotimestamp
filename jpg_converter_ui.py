"""Isolated Streamlit UI for the JPG Converter. No AutoTimestamp engine imports."""

from __future__ import annotations
import hashlib
import os
from io import BytesIO
from pathlib import Path
import zipfile

import streamlit as st
from PIL import Image

from workspace_preview import input_signature

from jpg_converter_cloud import convert_files_cloud
from jpg_converter_resource_guard import converter_slot, ConverterBusyError

from jpg_converter import (
    JPGSettings, ConversionError, SUPPORTED_EXT, MAX_FILES,
    available_backends, convert_files,
)


def _signature(files: list[tuple[str, bytes]], options: JPGSettings) -> str:
    h = hashlib.sha256(repr(options).encode('utf-8'))
    for name, data in files:
        h.update(name.encode('utf-8', errors='replace'))
        h.update(len(data).to_bytes(8, 'little'))
        h.update(data)
    return h.hexdigest()


def _choose_thumbnail(index: int) -> None:
    # Streamlit callbacks run before widgets are instantiated on the next rerun.
    st.session_state['jpgconv_active'] = index
    st.session_state['jpgconv_picker'] = index


def render_jpg_converter() -> None:
    st.markdown('#### 🖼️ Konverter ke JPG')
    st.caption('Mode terpisah — tidak memakai atau mengubah OCR, renderer timestamp, maupun Batch Manual/NPSN.')
    backends = available_backends()
    with st.expander('ℹ️ Format yang didukung & persyaratan', expanded=False):
        st.markdown(
            '**Gambar:** JPG/JPEG, PNG, WebP, GIF, BMP, TIFF, ICO, PPM/PGM; '
            '**PDF:** semua halaman; **SVG:** gambar vektor; **HEIC/HEIF/AVIF:** foto ponsel; '
            ''
            'Format lain seperti EXE, ZIP, MP4, dan file yang tidak mengandung gambar/halaman tidak dapat otomatis diubah menjadi JPG.'
        )
        for label, enabled in (
            ('PDFium (PDF)', backends['pdf']),
            ('CairoSVG (SVG)', backends['svg']),
            ('pillow-heif (HEIC/AVIF)', backends['heic']),
        ):
            st.caption(f"{'✅' if enabled else '⚠️'} {label}: {'tersedia' if enabled else 'tidak tersedia di server'}")

    control, preview = st.columns([1.1, 1.4], gap='large')
    with control:
        with st.container(border=True):
            st.markdown('**1. Pilih file**')
            uploads = st.file_uploader(
                'Pilih beberapa file gambar, PDF atau SVG',
                accept_multiple_files=True,
                type=sorted(ext.lstrip('.') for ext in SUPPORTED_EXT),
                key='jpgconv_uploads',
                help=f'Maksimal {MAX_FILES} file per batch dan 100 MB per file.',
            )
            if uploads:
                st.caption(f'{len(uploads)} file dipilih — output JPG/ZIP dibuat setelah proses konversi.')
            st.markdown('**2. Kualitas & optimasi**')
            preset = st.selectbox(
                'Preset kualitas',
                options=['Seimbang • 88', 'Ukuran lebih kecil • 75', 'Detail tinggi • 95'],
                index=0, key='jpgconv_preset',
            )
            quality = {'Seimbang • 88': 88, 'Ukuran lebih kecil • 75': 75, 'Detail tinggi • 95': 95}[preset]
            size_choice = st.selectbox(
                'Resolusi JPG (sisi terpanjang)',
                ['Asli', '1280 px', '1920 px', '2560 px', '4096 px'],
                key='jpgconv_size',
                help='Asli mempertahankan resolusi sepanjang aman; pilihan lainnya mengecilkan, tidak membesarkan.',
            )
            max_side = {'Asli': 0, '1280 px':1280, '1920 px':1920,'2560 px':2560,'4096 px':4096}[size_choice]
            c1, c2 = st.columns(2)
            with c1:
                dpi = st.selectbox('Resolusi PDF', [120, 160, 200, 300], index=1, key='jpgconv_dpi', help='Hanya berlaku untuk PDF.')
            with c2:
                background = st.selectbox('Background transparan', ['Putih', 'Hitam'], key='jpgconv_bg')
            all_frames = st.checkbox('Konversi semua halaman / frame', value=True, key='jpgconv_frames', help='PDF multipage, GIF/TIFF animasi, dan dokumen. Bila mati, hanya halaman pertama.')
            settings = JPGSettings(quality=quality, dpi=dpi, max_side=max_side,
                                   background='#FFFFFF' if background=='Putih' else '#000000',
                                   all_frames=all_frames)
            st.caption('Optimasi: JPEG progressive, encoding optimize, koreksi orientasi EXIF, downsampling Lanczos, RGB dan flatten transparansi. Metadata EXIF/GPS tidak dibawa ke JPG baru.')

            # Metadata + per-upload memoized hashes: no 80-file read every rerun.
            signature = input_signature(uploads or [], {'jpg_converter_settings': repr(settings)})
            outdated = (st.session_state.get('jpgconv_signature') != signature and st.session_state.get('jpgconv_result') is not None)
            if outdated:
                st.warning('⚠️ File atau pengaturan berubah. Hasil sebelumnya tidak berlaku; klik Konversi lagi.')
            pressed = st.button('🔄 KONVERSI KE JPG', type='primary', use_container_width=True, disabled=not bool(uploads))
            st.caption('Proteksi multi-user: konversi JPG berat dijalankan bergantian agar RAM server lebih stabil.')
            if pressed:
                try:
                    # A process-wide permit limits concurrent heavy JPG jobs;
                    # each user's files and report remain strictly session-local.
                    with converter_slot():
                        progress = st.progress(0, text='Menyiapkan...')
                        try:
                            def on_progress(index: int, total: int, filename: str):
                                progress.progress(min(1.0, index / max(1,total)), text=f'Konversi {index}/{total}: {filename[:42]}')
                            report = convert_files_cloud([(f.name, f) for f in uploads], settings, on_progress)
                        finally:
                            progress.empty()
                    previous_report = st.session_state.get('jpgconv_result')
                    st.session_state['jpgconv_result'] = report
                    # Release the old ZIP only after a successful conversion.
                    if previous_report is not None and previous_report is not report:
                        previous_report.close()
                    st.session_state['jpgconv_signature'] = signature
                    st.session_state['jpgconv_active'] = 0
                    try:
                        from pyx_monitor_activity import record_event
                        record_event("konversi_jpg")
                    except Exception:
                        pass
                    st.rerun()
                except ConverterBusyError as exc:
                    st.warning(f'⏳ {exc}')
                except (ConversionError, ValueError, OSError) as exc:
                    st.error(f'❌ Konversi gagal: {exc}')

    with preview:
        report = st.session_state.get('jpgconv_result')
        if not report or outdated:
            with st.container(border=True):
                st.markdown('**Preview JPG**')
                st.info('Upload file dan klik **KONVERSI KE JPG**. Hasil dipilih dari galeri, lalu unduh satu JPG atau ZIP semuanya.')
        else:
            with st.container(border=True):
                st.markdown('**3. Hasil konversi & preview**')
                if report.items:
                    st.success(f'{len(report.items)} JPG berhasil dibuat dari {report.input_count} file input.')
                    if report.input_bytes:
                        before_mb = report.input_bytes / 1048576
                        after_mb = report.jpg_bytes / 1048576
                        st.caption(f'Ukuran input: {before_mb:.2f} MB • total JPG: {after_mb:.2f} MB. PDF/animasi dapat menghasilkan banyak JPG sehingga ukuran total bisa lebih besar.')
                    idx = min(st.session_state.get('jpgconv_active', 0), len(report.items)-1)
                    selected_name = st.selectbox('Foto untuk preview',
                                                 list(range(len(report.items))), index=idx,
                                                 format_func=lambda i: report.items[i].name,
                                                 key='jpgconv_picker')
                    st.session_state['jpgconv_active'] = selected_name
                    chosen = report.items[selected_name]
                    with Image.open(BytesIO(chosen.data)) as display_img:
                        display_img.thumbnail((760, 420), Image.Resampling.LANCZOS)
                        st.image(display_img.copy(), caption=f'{chosen.name} • {chosen.width} × {chosen.height} px', use_container_width=True)
                    # Up to five quick-select buttons, no permanent full-height gallery.
                    if len(report.items) > 1:
                        start = (selected_name // 5) * 5
                        st.caption(f'Galeri {start+1}–{min(start+5,len(report.items))} dari {len(report.items)} hasil')
                        cells = st.columns(min(5, len(report.items)-start))
                        for col, i in zip(cells, range(start, min(start+5,len(report.items)))):
                            with col:
                                with Image.open(BytesIO(report.items[i].data)) as thumb_img:
                                    thumb_img.thumbnail((170,100), Image.Resampling.LANCZOS)
                                    st.image(thumb_img.copy(), use_container_width=True)
                                st.button(f'{i+1}', key=f'jpgconv_thumb_{i}', use_container_width=True,
                                          type='primary' if i==selected_name else 'secondary',
                                          on_click=_choose_thumbnail, args=(i,))
                    d1, d2 = st.columns(2)
                    with d1:
                        st.download_button('⬇️ Download JPG ini', chosen.data, file_name=chosen.name,
                                           mime='image/jpeg', use_container_width=True)
                    with d2:
                        # Streamlit still materializes download data internally;
                        # this avoids permanently retaining another ZIP in session state.
                        if report.zip_file is not None:
                            # Streamlit supports io.BufferedReader; SpooledTemporaryFile
                            # itself is not a supported runtime type in some versions.
                            # dup() retains the session's original temporary ZIP handle.
                            with os.fdopen(os.dup(report.zip_file.fileno()), 'rb') as stream:
                                stream.seek(0)
                                st.download_button('📦 Download Semua (ZIP)', stream,
                                                   file_name='AutoTimestamp_JPG_Converted.zip', mime='application/zip',
                                                   type='primary', use_container_width=True)
                        else:
                            st.download_button('📦 Download Semua (ZIP)', report.zip_bytes,
                                               file_name='AutoTimestamp_JPG_Converted.zip', mime='application/zip',
                                               type='primary', use_container_width=True)
                if report.errors:
                    with st.expander(f'⚠️ {len(report.errors)} file gagal diproses', expanded=True):
                        for name, message in report.errors:
                            st.error(f'**{name}**: {message}')
                if not report.items:
                    st.warning('Belum ada JPG yang berhasil dibuat. Periksa pesan error tiap file.')
                # An explicit release helps on shared Cloud hosts: results are
                # not otherwise closed until the user converts again or disconnects.
                if st.button('🧹 Bersihkan hasil konversi', use_container_width=True):
                    report.close()
                    st.session_state.pop('jpgconv_result', None)
                    st.session_state.pop('jpgconv_signature', None)
                    st.session_state['jpgconv_active'] = 0
                    st.rerun()
    st.caption('Batas aman: maksimum 80 file, 250 JPG hasil, 100 MB/file, 40 MP/foto, total output 400 MB. Konversi hanya bekerja pada salinan; file asli tetap utuh.')
