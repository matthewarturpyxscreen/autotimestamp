from pathlib import Path
import ast
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_toolbar_config_minimal():
    with (ROOT / ".streamlit" / "config.toml").open("rb") as f:
        conf = tomllib.load(f)
    assert conf["client"]["toolbarMode"] == "minimal"


def test_toolbar_css_present_in_main_app():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for selector in ('[data-testid="stToolbar"]',
                     '[data-testid="stAppToolbar"]',
                     '[data-testid="stHeader"]', '#MainMenu'):
        assert selector in source
    assert "display: none !important" in source


def test_main_app_parses():
    ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))


def test_core_modules_parse():
    for file in ("batch_manual.py", "batch_npsn.py", "ocr_fields.py",
                 "jpg_converter.py", "jpg_converter_ui.py", "workspace_preview.py"):
        ast.parse((ROOT / file).read_text(encoding="utf-8"))
