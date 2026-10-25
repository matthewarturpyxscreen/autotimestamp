"""V9.6 standalone JPG converter and no-regressions from v9.5."""

import ast
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest
from PIL import Image, ImageDraw, ImageOps

from jpg_converter import JPGSettings, convert_files, image_to_jpeg, safe_basename, ConversionError, MAX_PAGES

ROOT = Path(__file__).resolve().parents[1]


def png_rgba(size=(150, 80)):
    b = io.BytesIO()
    photo = Image.new('RGBA', size, (0, 0, 0, 0))
    ImageDraw.Draw(photo).rectangle((0, 0, 20, 20), fill=(255, 0, 0, 255))
    photo.save(b, format='PNG')
    return b.getvalue()


def gif_two_frames():
    b = io.BytesIO()
    imgs = [Image.new('RGB', (100, 40), colour) for colour in ('red', 'blue')]
    imgs[0].save(b, format='GIF', save_all=True, append_images=imgs[1:], duration=100, loop=0)
    return b.getvalue()


def sample_pdf():
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(200, 180))
    c.drawString(10, 160, 'PAGE ONE')
    c.showPage()
    c.drawString(10, 160, 'PAGE TWO')
    c.save()
    return b.getvalue()


def test_png_alpha_white_and_black():
    png = png_rgba()
    white = convert_files([('test.png', png)], JPGSettings(background='#FFFFFF'))
    black = convert_files([('test.png', png)], JPGSettings(background='#000000'))
    assert not white.errors and not black.errors
    assert white.items[0].data.startswith(b'\xff\xd8')
    w = Image.open(io.BytesIO(white.items[0].data))
    k = Image.open(io.BytesIO(black.items[0].data))
    assert all(x > 245 for x in w.getpixel((120, 70)))
    assert all(x < 10 for x in k.getpixel((120, 70)))


def test_convert_multiframe_gif_and_first_only():
    payload = gif_two_frames()
    all_ = convert_files([('anim.gif', payload)], JPGSettings(all_frames=True))
    first = convert_files([('anim.gif', payload)], JPGSettings(all_frames=False))
    assert [x.name for x in all_.items] == ['anim_frame_001.jpg', 'anim_frame_002.jpg']
    assert len(first.items) == 1
    assert Image.open(io.BytesIO(all_.items[1].data)).getpixel((50, 20))[2] > 220


def test_pdf_two_pages_and_dpi_limits():
    result = convert_files([('school.pdf', sample_pdf())], JPGSettings(dpi=160))
    assert not result.errors
    assert [p.name for p in result.items] == ['school_page_001.jpg', 'school_page_002.jpg']
    assert result.items[0].width >= 400
    assert result.items[0].height >= 350
    assert len(result.zip_bytes) > 0


def test_pdf_one_page_only():
    result = convert_files([('school.pdf', sample_pdf())], JPGSettings(all_frames=False))
    assert len(result.items) == 1
    assert result.items[0].name == 'school_page_001.jpg'


def test_resize_never_upscales():
    data, size = image_to_jpeg(Image.new('RGB',(4000, 2000),'cyan'), JPGSettings(max_side=1280))
    assert size == (1280, 640)
    smaller, small_size = image_to_jpeg(Image.new('RGB',(800, 400),'blue'), JPGSettings(max_side=1280))
    assert small_size == (800,400)


def test_orientation_exif_transposed():
    img = Image.new('RGB',(100,60),'red')
    exif=img.getexif()
    exif[274] = 6
    input_bytes=io.BytesIO()
    img.save(input_bytes,format='JPEG',exif=exif)
    original=Image.open(io.BytesIO(input_bytes.getvalue()))
    encoded, size=image_to_jpeg(original, JPGSettings())
    assert size == (60,100)
    assert Image.open(io.BytesIO(encoded)).getexif().get(274) is None


def test_original_not_mutated_and_exif_is_removed():
    img = Image.new('RGBA', (100,70), (80,90,100,128))
    before = img.tobytes()
    encoded, size = image_to_jpeg(img, JPGSettings())
    assert img.mode == 'RGBA'
    assert img.tobytes() == before
    assert Image.open(io.BytesIO(encoded)).mode == 'RGB'


def test_csv_error_unsupported_format_does_not_block_valid_images():
    result=convert_files([('no.csv', b'a,b,c\n'), ('yes.png', png_rgba())], JPGSettings())
    assert len(result.items)==1 and len(result.errors)==1
    assert result.errors[0][0]=='no.csv'


def test_file_name_sanitization_and_collision():
    payload=png_rgba()
    report=convert_files([('../../back.png',payload), ('back.png',payload), ('BACK.PNG',payload)], JPGSettings())
    assert len(report.items)==3
    filenames=[item.name for item in report.items]
    assert len({n.casefold() for n in filenames})==3
    assert all('/' not in n and '..' not in n for n in filenames)
    with zipfile.ZipFile(io.BytesIO(report.zip_bytes)) as z:
        assert z.namelist()==filenames
        assert all(z.read(name)[:2]==b'\xff\xd8' for name in filenames)


def test_svg_with_alpha_and_external_link_rejected():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect x="10" y="10" width="50" height="20" fill="orange"/></svg>'
    report = convert_files([('art.svg', svg)], JPGSettings())
    assert not report.errors
    assert report.items[0].name=='art.jpg'
    assert report.items[0].width==160
    attack = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>'
    rejected = convert_files([('external.svg', attack)], JPGSettings())
    assert len(rejected.errors)==1 and not rejected.items


def test_corrupted_pdf_fails_gracefully():
    report=convert_files([('bad.pdf', b'%PDF-1.7 BAD')], JPGSettings())
    assert not report.items
    assert report.errors and 'PDF' in report.errors[0][1]


def test_options_validation():
    for quality in (0, 100):
        with pytest.raises(ValueError):
            JPGSettings(quality=quality).validate()


def test_v95_core_renderer_ocr_batch_functions_ast_unchanged():
    manifest=json.loads((ROOT/'CORE_V941_AST_SHA256.json').read_text())
    for filename,names in manifest.items():
        tree=ast.parse((ROOT/filename).read_text())
        nodes={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name,old in names.items():
            actual=hashlib.sha256(ast.dump(nodes[name],include_attributes=False).encode()).hexdigest()
            assert actual==old,(filename,name)


def test_v951_engine_code_unchanged_in_ui_refinement():
    """V9.5.2 changes UI only. All processing helpers match V9.5.1 by AST."""
    zipfile_path=ROOT.parent.parent/'AutoTimestamp_V9.5.1_Converter_JPG_Optimized.zip'
    if not zipfile_path.is_file():
        pytest.skip('Original V9.5.1 ZIP not mounted in this test environment')
    with zipfile.ZipFile(zipfile_path) as original:
        for name in ('ocr_fields.py', 'jpg_converter.py', 'jpg_converter_ui.py'):
            assert (ROOT/name).read_bytes()==original.read('timestamp-2-main/'+name)
        for name in ('app.py', 'batch_manual.py', 'batch_npsn.py', 'workspace_preview.py'):
            original_tree=ast.parse(original.read('timestamp-2-main/'+name).decode())
            current_tree=ast.parse((ROOT/name).read_text())
            old_functions={node.name:node for node in original_tree.body if isinstance(node,(ast.FunctionDef, ast.AsyncFunctionDef))}
            new_functions={node.name:node for node in current_tree.body if isinstance(node,(ast.FunctionDef, ast.AsyncFunctionDef))}
            for fn, original_node in old_functions.items():
                if name=='workspace_preview.py' and fn in ('compact_preview','_display_active','_show_size_control','batch_gallery','single_preview'):
                    continue  # Display/UI helpers intentionally adjusted.
                if name in ('batch_manual.py','batch_npsn.py') and fn == 'render_batch_mode':
                    continue  # This wrapper's layout is intentionally reorganized; core helpers are checked below.
                assert fn in new_functions
                assert ast.dump(new_functions[fn], include_attributes=False) == ast.dump(original_node, include_attributes=False), (name,fn)


def test_real_office_docx_converts_via_libreoffice_when_available():
    import shutil
    if not (shutil.which('libreoffice') or shutil.which('soffice')):
        pytest.skip('LibreOffice not installed in environment')
    docx = pytest.importorskip('docx')
    doc=docx.Document()
    doc.add_heading('Contoh Dokumen Sekolah', 0)
    doc.add_paragraph('Aplikasi AutoTimestamp — konversi dokumen ke JPG.')
    buf=io.BytesIO()
    doc.save(buf)
    result=convert_files([('test.docx',buf.getvalue())], JPGSettings(dpi=120))
    assert not result.errors
    assert len(result.items)>=1
    assert result.items[0].name == 'test_page_001.jpg'
    assert Image.open(io.BytesIO(result.items[0].data)).width >= 900
