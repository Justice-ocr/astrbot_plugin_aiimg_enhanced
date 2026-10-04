"""Persona layout assertions for the current React Studio, not the removed legacy UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web" / "src" / "app" / "StudioApp.tsx"
STYLE = ROOT / "web" / "src" / "styles" / "yukina-shell.css"


def test_persona_upload_toolbar_lives_in_reference_panel():
    source = APP.read_text(encoding="utf-8").split("function PersonasView", 1)[1].split("const providerSecretFields", 1)[0]
    assert source.index("基础提示词") < source.index("参考图与职责") < source.index("添加参考图") < source.index('className="persona-ref-grid"')
    assert 'accept="image/jpeg,image/png,image/webp,image/gif"' in source
    assert "removeRef(path)" in source


def test_persona_reference_panel_preserves_image_aspect_ratio():
    css = STYLE.read_text(encoding="utf-8")
    media = css.split(".persona-ref-media img {", 1)[1].split("}", 1)[0]
    assert "object-fit: contain" in media
    assert ".persona-editor-layout" in css
    assert ".persona-ref-grid" in css
