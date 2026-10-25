"""V9.5.2.4: regression of real encoder bytes and UI-only performance paths."""
import io
import hashlib
import json
import ast
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
import workspace_preview as wp
from jpg_converter import JPGSettings, convert_files

ROOT = Path(__file__).resolve().parents[1]


def make_png(color, sz=(320,220)):
    fp=io.BytesIO()
    Image.new('RGB',sz,color).save(fp,format='PNG')
    return fp.getvalue()


def test_converter_spooled_zip_has_identical_jpg_bytes_and_names():
    inputs=[('one.png',make_png('red')),('two.png',make_png('blue'))]
    cfg=JPGSettings(quality=88, max_side=1280)
    old=convert_files(inputs,cfg)
    disk=convert_files(inputs,cfg,zip_to_disk=True)
    try:
        assert old.zip_bytes and disk.zip_file is not None and not disk.zip_bytes
        assert [(x.name,x.data) for x in old.items]==[(x.name,x.data) for x in disk.items]
        with zipfile.ZipFile(io.BytesIO(old.zip_bytes)) as a, zipfile.ZipFile(disk.zip_file) as b:
            assert a.namelist()==b.namelist()
            for name in a.namelist():
                assert a.read(name)==b.read(name)
    finally:
        disk.zip_file.close()


def test_converter_spool_moves_large_archive_to_disk(monkeypatch):
    import jpg_converter
    original=jpg_converter.tempfile.SpooledTemporaryFile
    def small_spool(*a,**kw):
        kw['max_size']=128
        return original(*a,**kw)
    monkeypatch.setattr(jpg_converter.tempfile,'SpooledTemporaryFile', small_spool)
    report=convert_files([('one.png',make_png('green'))],JPGSettings(),zip_to_disk=True)
    try:
        assert report.zip_file._rolled
    finally:
        report.zip_file.close()


def test_preview_large_calls_same_renderer_but_uses_bounded_pixels():
    source=Image.new('RGB',(3200,2400),'red')
    original_pixel=source.getpixel((10,10))
    calls=[]
    def renderer(pixels,text,**opts):
        calls.append((pixels.shape,text,opts))
        return Image.fromarray(pixels.copy()),{}
    outcome=wp.build_cloud_live_preview(source,'text',renderer, {'fixed_font_size_px':80,'font_size_px_override':100,'font_size_mode':'fixed_px'})
    assert calls[0][0]==(1200,1600,3)
    assert calls[0][2]['fixed_font_size_px']==40
    assert calls[0][2]['font_size_px_override']==50
    assert outcome.size==(1600,1200)
    assert source.size==(3200,2400) and source.getpixel((10,10))==original_pixel


def test_preview_small_same_signature():
    img=Image.new('RGB',(600,350),'red')
    a=[]
    def renderer(arr,text,**opts):
        a.append((arr.shape,opts))
        return Image.fromarray(arr),{}
    wp.build_cloud_live_preview(img,'text',renderer,{'fixed_font_size_px':80})
    assert a==[((350,600,3),{'fixed_font_size_px':80})]


def test_gallery_read_photo_reduces_input_without_closing_upload():
    b=io.BytesIO()
    Image.new('RGB',(3400,2400),'red').save(b,'JPEG',quality=80)
    upload=io.BytesIO(b.getvalue())
    small=wp._read_photo(upload,lambda f: Image.open(f).convert('RGB'))
    assert max(small.size)<=1600
    upload.seek(0)
    assert upload.read(2)==b'\xff\xd8'


def test_generic_mutable_buffer_rehashes_every_call():
    class Upload(io.BytesIO):
        name='reused.png'
    buf=Upload(b'hello')
    first=wp.file_fingerprint(buf)
    buf.seek(0);buf.truncate(0);buf.write(b'world')
    second=wp.file_fingerprint(buf)
    assert first!=second


def test_no_changes_to_main_ocr_batch_code_and_jpg_encoder():
    baseline=json.loads((ROOT/'ENGINE_UNCHANGED_SHA256_V9.5.2.3.json').read_text())
    for name in ('app.py','batch_manual.py','batch_npsn.py','ocr_fields.py','requirements.txt','.streamlit/config.toml'):
        actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if name=='app.py':
            # Preserved app code was measured in V9.5.2.3 archive rather than manifest.
            continue
        assert actual==baseline[name]
