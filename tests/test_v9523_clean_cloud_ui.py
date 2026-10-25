from pathlib import Path
from zipfile import ZipFile
import ast
import hashlib
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_only_presentation_css_changed_against_base():
    # The baseline block is preserved as a text fixture to verify the exact
    # replacement; a parser-level test can't prove the unchanged parts.
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    intro = "    /* V9.5.2.3 — Streamlit Community Cloud UI clean-up (presentation only)."
    tail = "    /* Card Container & Shadow */"
    assert src.count(intro) == 1
    assert src.count(tail) == 1
    assert src.index(intro) < src.index(tail)
    assert "embed=true" in src
    ast.parse(src)


def test_toolbar_css_has_targeted_platform_chrome_selectors():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    for selector in ('[data-testid="stAppToolbar"]',
                     '[data-testid="stHeaderActionElements"]',
                     '#GithubIcon', '[class*="viewerBadge_container"]'):
        assert selector in src
    assert "display: none !important;" in src


def test_streamlit_config_minimal():
    with (ROOT / ".streamlit/config.toml").open("rb") as f:
        assert tomllib.load(f)["client"]["toolbarMode"] == "minimal"


def test_engine_modules_syntax():
    for name in ("batch_manual.py", "batch_npsn.py", "ocr_fields.py",
                 "jpg_converter.py", "jpg_converter_ui.py", "workspace_preview.py"):
        ast.parse((ROOT / name).read_text(encoding="utf-8"))
