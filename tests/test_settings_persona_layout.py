from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "pages" / "Settings" / "index.html"
STYLE_CSS = ROOT / "pages" / "Settings" / "style.css"


def test_persona_upload_toolbar_lives_in_reference_panel():
    html = INDEX_HTML.read_text(encoding="utf-8")

    ref_panel_start = html.index('<div class="persona-ref-panel">')
    upload_button = html.index('id="modal-upload-btn"')
    left_form_end = html.index('</div>', html.index('<div class="persona-edit-fields">'))

    assert ref_panel_start < upload_button
    assert upload_button > left_form_end
    assert 'id="modal-clear-refs-btn"' in html


def test_persona_reference_panel_has_sticky_toolbar():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert ".persona-ref-toolbar" in css
    assert "position:sticky" in css
    assert "justify-content:space-between" in css
