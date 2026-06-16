from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "pages" / "Settings" / "app.js"
PERSONA_JS = ROOT / "pages" / "Settings" / "persona_refs.js"


def test_persona_reference_logic_is_split_into_its_own_module():
    app_js = APP_JS.read_text(encoding="utf-8")
    persona_js = PERSONA_JS.read_text(encoding="utf-8")

    assert "persona_refs.js" in app_js
    assert "uploadRefImages" not in app_js
    assert "renderRefPreviews" not in app_js
    assert "getLocalRefPreview" not in app_js
    assert "uploadRefImages" in persona_js
    assert "renderRefPreviews" in persona_js
    assert "getLocalRefPreview" in persona_js
