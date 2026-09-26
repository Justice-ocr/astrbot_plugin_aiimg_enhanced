from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_FILES = [
    ROOT / "web" / "src" / "app" / "StudioApp.tsx",
    ROOT / "web" / "src" / "app" / "provider_catalog.js",
    ROOT / "web" / "src" / "styles" / "yukina-shell.css",
    ROOT / "scripts" / "output_sizes.json",
]


def test_studio_ui_sources_are_clean_utf8():
    for path in UI_FILES:
        text = path.read_text(encoding="utf-8")
        assert "\ufffd" not in text, path


def test_output_size_labels_are_literal_chinese():
    text = (ROOT / "scripts" / "output_sizes.json").read_text(encoding="utf-8")
    for label in ("方图", "横屏", "竖屏"):
        assert label in text
