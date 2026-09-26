from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "web" / "src" / "app" / "provider_catalog.js"
STUDIO = ROOT / "web" / "src" / "app" / "StudioApp.tsx"


def test_provider_templates_are_owned_by_studio():
    source = CATALOG.read_text(encoding="utf-8")
    app = STUDIO.read_text(encoding="utf-8")
    assert "PROVIDER_TEMPLATES" in source
    assert "VIDEO_PROVIDER_TYPES" in source
    assert 'from "./provider_catalog.js"' in app
    for template in ("agnes_video", "minimax_h3_video", "openai_video", "xai_video"):
        assert template in source
