"""Mode Smart Replication: referensi screenshot → OCR → preview → export.

Uses the existing timestamp renderer unchanged. The resulting overlay is digitally
added, and is not a substitute for original capture time/location evidence.
"""
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from PIL import Image, ImageOps
import numpy as np
import streamlit as st
from streamlit_paste_button import paste_image_button


def _image_from_upload(file):
    return ImageOps.exif_transpose(Image.open(io.BytesIO(file.getvalue()))).convert('RGB')


def _render_preview(image, text, size_mode, size_pct, fixed_px, bold, bold_strength, generate):
    # Preview at full resolution logically, downsample only the displayed result.
    return generate(np.asarray(image)[:, :, ::-1].copy(), text, font_size_mode=size_mode,
                    font_size_percent=size_pct, fixed_font_size_px=fixed_px,
                    bold_enabled=bold, bold_strength_percent=bold_strength)


def _jpeg_bytes(image):
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=95, optimize=True)
    return output.getvalue()


def render(generate, ocr):
    st.markdown('<div class="hero-badge">✨ V9.3 • Smart Replication</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-title">Reference Timestamp Studio</div>', unsafe_allow_html=True)
    st.caption('Paste screenshot geotag → baca dengan Gemini → cocokkan tampilan → preview → simpan hasil.')

    left, center, right = st.columns([1.05, 1.05, 1.35], gap='medium')
    with left:
        st.markdown('##### ① Referensi geotag')
        paste = paste_image_button(label='📋 Paste screenshot (Ctrl+V)', key='smart_paste')
        uploaded_ref = st.file_uploader('Atau upload screenshot', type=['jpg','jpeg','png'], key='smart_reference')
        source = None
        if paste.image_data is not None:
            source = ImageOps.exif_transpose(paste.image_data).convert('RGB')
        elif uploaded_ref is not None:
            source = _image_from_upload(uploaded_ref)
        if source is not None:
            st.image(source, caption='Referensi', use_container_width=True)
            buffer = io.BytesIO(); source.save(buffer, format='PNG')
            digest = hashlib.sha256(buffer.getvalue()).hexdigest()
            st.session_state.smart_source_digest = digest
            st.session_state.smart_source_image = source
        else:
            source = st.session_state.get('smart_source_image')
            if source is not None:
                st.image(source, caption='Referensi terakhir', use_container_width=True)
        api_key = st.secrets.get('GEMINI_API_KEY','')
        if st.button('✨ Baca screenshot dengan Gemini', disabled=not (source is not None and api_key), use_container_width=True):
            try:
                with st.spinner('Membaca teks referensi...'):
                    extracted = ocr(source, api_key)
                if not extracted.strip():
                    st.warning('OCR tidak menemukan teks. Gunakan input manual.')
                else:
                    st.session_state.smart_text = extracted.strip()
                    st.session_state.smart_ocr_source_digest = st.session_state.get('smart_source_digest')
                    st.rerun()
            except Exception as exc:
                st.error(f'OCR gagal: {exc}')
        if not api_key:
            st.caption('OCR memerlukan GEMINI_API_KEY di Streamlit Secrets; input manual tetap tersedia.')
        if st.session_state.get('smart_ocr_source_digest') and st.session_state.get('smart_ocr_source_digest') != st.session_state.get('smart_source_digest'):
            st.warning('Referensi berubah. Jalankan OCR lagi agar teks sesuai.')

    with center:
        st.markdown('##### ② Foto pengganti & teks')
        photos = st.file_uploader('Upload foto pengganti', type=['jpg','jpeg','png'], accept_multiple_files=True, key='smart_photos')
        if photos:
            selected = st.selectbox('Foto untuk preview', range(len(photos)), format_func=lambda i:photos[i].name, key='smart_selected')
            selected_photo = _image_from_upload(photos[selected])
            st.caption(f'{len(photos)} foto dipilih · Preview: {selected_photo.width} × {selected_photo.height}px')
        else:
            selected_photo = None
        st.text_area('Teks timestamp (dapat dikoreksi)', key='smart_text', height=122, placeholder='-6.1234567, 106.1234567\nKelurahan, Kabupaten, Provinsi\n23/10/2026 10:30:00 WIB')
        with st.expander('⚙️ Ukuran & bold', expanded=True):
            mode_name = st.selectbox('Metode ukuran', ['Smart Uniform (sisi pendek)','Persentase lebar','Fixed Pixel'], key='smart_sizing')
            mode = {'Smart Uniform (sisi pendek)':'short_edge','Persentase lebar':'width','Fixed Pixel':'fixed_px'}[mode_name]
            if mode == 'fixed_px':
                fixed_px = st.slider('Font (piksel)', 20, 250, 100, 5, key='smart_fixed')
                pct = 6.5
            else:
                pct = st.slider('Ukuran font (%)',2.0,12.0,6.5,0.5,key='smart_percent')
                fixed_px = 100
            bold = st.toggle('Bold halus',value=False,key='smart_bold')
            bold_strength = st.slider('Ketebalan bold',1,100,15,1,key='smart_bold_amount') if bold else 15
            st.caption('Font asli AVHershey tetap dipakai. Auto-fit dapat mengecilkan huruf bila teks terlalu panjang.')
        st.caption('Periksa tanggal, waktu, dan koordinat. Informasi dari screenshot tidak otomatis membuktikan data foto pengganti.')

    with right:
        st.markdown('##### ③ Live Preview & Export')
        text = st.session_state.get('smart_text','').strip()
        ready = bool(selected_photo is not None and text)
        if ready:
            try:
                # Full-resolution render, no recompression before preview.
                preview, detail = _render_preview(selected_photo, text, mode, pct, fixed_px, bold, bold_strength, generate)
                st.image(preview, caption='Preview hasil · overlay digital', use_container_width=True)
                st.caption(f'Font aktual: {detail["font_size"]}px · Auto-fit: {"Ya" if detail.get("auto_fit_applied") else "Tidak"}')
            except Exception as exc:
                ready=False
                st.error(f'Preview gagal: {exc}')
        else:
            st.info('Masukkan foto pengganti dan teks referensi untuk melihat preview.')

        # Jangan tampilkan hasil ZIP lama bila input/pengaturan telah berubah.
        current_signature = hashlib.sha256(repr((
            [(f.name, len(f.getvalue()), hashlib.sha256(f.getvalue()).hexdigest()) for f in (photos or [])],
            text, mode, pct, fixed_px, bold, bold_strength,
        )).encode('utf-8')).hexdigest()
        if st.session_state.get('smart_export_signature') != current_signature:
            st.session_state.pop('smart_export', None)
        st.checkbox('Saya telah memeriksa teks, waktu, dan lokasi; output adalah foto yang diedit', key='smart_verified')
        can_export = ready and st.session_state.get('smart_verified',False)
        if st.button('📦 Siapkan hasil ZIP', type='primary', use_container_width=True, disabled=not can_export):
            if len(photos)>100:
                st.error('Maksimal 100 foto per ZIP agar memori server tetap aman.')
            else:
                try:
                    stream = io.BytesIO(); log=[]
                    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=5) as bundle:
                        prog = st.progress(0)
                        for i, photo in enumerate(photos):
                            src = _image_from_upload(photo)
                            rendered, details = _render_preview(src,text,mode,pct,fixed_px,bold,bold_strength,generate)
                            new_name=f'{i+1:03d}_{photo.name.rsplit(".",1)[0]}_overlay.jpg'
                            bundle.writestr(new_name, _jpeg_bytes(rendered))
                            log.append({'original':photo.name,'result':new_name,'font_size_px':details['font_size'],'auto_fit':bool(details.get('auto_fit_applied'))})
                            prog.progress((i+1)/len(photos))
                        manifest={'type':'digitally_added_timestamp_overlay', 'timestamp_source':'reference screenshot or manual text, reviewed by operator',
                                  'created_at_utc':datetime.now(timezone.utc).isoformat(), 'referenced_text':text,
                                  'reference_sha256':st.session_state.get('smart_source_digest'), 'photos':log}
                        bundle.writestr('overlay_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
                    st.session_state.smart_export=stream.getvalue()
                    st.session_state.smart_export_signature=current_signature
                    st.success(f'{len(photos)} foto berhasil disiapkan.')
                except Exception as exc:
                    st.error(f'Export gagal: {exc}')
        if st.session_state.get('smart_export'):
            st.download_button('⬇️ Download ZIP hasil + manifest',st.session_state.smart_export,
                               file_name='timestamp_replication_results.zip',mime='application/zip',use_container_width=True)
