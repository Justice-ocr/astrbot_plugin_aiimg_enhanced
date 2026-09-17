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


def test_agnes_video_provider_template_is_available():
    provider_js = PROVIDER_JS.read_text(encoding="utf-8")
    provider_form_js = PROVIDER_FORM_JS.read_text(encoding="utf-8")
    index_html = (ROOT / "pages" / "Settings" / "index.html").read_text(encoding="utf-8")

    assert "agnes_video" in provider_js
    assert "agnes-video-2.5-flash" in provider_js
    assert "image_handling_method" in provider_form_js
    assert "file_service_base_url" in provider_js
    assert "enable_file_service_magic" in provider_form_js
    assert "'astrbot'" in provider_form_js
    assert 'value="agnes_video"' in index_html


def test_minimax_h3_video_provider_template_is_available():
    provider_js = PROVIDER_JS.read_text(encoding="utf-8")
    provider_form_js = PROVIDER_FORM_JS.read_text(encoding="utf-8")
    index_html = (ROOT / "pages" / "Settings" / "index.html").read_text(encoding="utf-8")

    assert "minimax_h3_video" in provider_js
    assert "MiniMax-H3" in provider_js
    assert "data_uri" in provider_form_js
    assert "duration" in provider_form_js
    assert 'value="minimax_h3_video"' in index_html


def test_openai_video_provider_template_is_available():
    provider_js = PROVIDER_JS.read_text(encoding="utf-8")
    provider_form_js = PROVIDER_FORM_JS.read_text(encoding="utf-8")
    index_html = (ROOT / "pages" / "Settings" / "index.html").read_text(encoding="utf-8")

    assert "openai_video" in provider_js
    assert "https://api.openai.com" in provider_js
    assert "input_reference_field" in provider_form_js
    assert "extra_form" in provider_form_js
    assert 'value="openai_video"' in index_html
