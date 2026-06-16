from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "pages" / "Settings" / "app.js"
PROVIDER_JS = ROOT / "pages" / "Settings" / "provider_catalog.js"
PROVIDER_FORM_JS = ROOT / "pages" / "Settings" / "provider_form.js"


def test_provider_catalog_logic_is_split_into_its_own_module():
    app_js = APP_JS.read_text(encoding="utf-8")
    provider_js = PROVIDER_JS.read_text(encoding="utf-8")

    assert "from './provider_catalog.js'" in app_js
    assert "function inferProviderType" not in app_js
    assert "const P_TEMPLATES" not in app_js
    assert "const P_NAMES" not in app_js
    assert "const VIDEO_PROVIDER_TYPES" not in app_js
    assert "function inferProviderType" in provider_js
    assert "const PROVIDER_TEMPLATES" in provider_js
    assert "const PROVIDER_NAMES" in provider_js
    assert "const VIDEO_PROVIDER_TYPES" in provider_js
    assert "inferProviderType" in provider_js
    assert "PROVIDER_TEMPLATES" in provider_js
    assert "PROVIDER_NAMES" in provider_js
    assert "VIDEO_PROVIDER_TYPES" in provider_js


def test_provider_form_logic_is_split_into_its_own_module():
    app_js = APP_JS.read_text(encoding="utf-8")
    provider_form_js = PROVIDER_FORM_JS.read_text(encoding="utf-8")

    assert "from './provider_form.js'" in app_js
    assert "function buildProviderForm(" not in app_js
    assert "function readProviderForm(" not in app_js
    assert "export function buildProviderForm(" in provider_form_js
    assert "export function readProviderForm(" in provider_form_js
