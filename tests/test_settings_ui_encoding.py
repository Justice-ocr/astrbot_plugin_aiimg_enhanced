from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_FILES = [
    ROOT / "pages" / "Settings" / "index.html",
    ROOT / "pages" / "Settings" / "app.js",
    ROOT / "pages" / "Settings" / "output_sizes.js",
    ROOT / "pages" / "Settings" / "provider_catalog.js",
    ROOT / "pages" / "Settings" / "provider_form.js",
    ROOT / "pages" / "Settings" / "style.css",
    ROOT / "pages" / "Settings" / "output_sizes.json",
]
MOJIBAKE_FRAGMENTS = [
    "\ufffd",
    "鈹",
    "馃",
    "鍔",
    "鏈",
    "榛",
    "鏂",
    "閰",
    "缁",
    "涓",
    "浣",
    "Â",
    "Ã",
]


def test_settings_ui_sources_are_clean_utf8():
    for path in UI_FILES:
        text = path.read_text(encoding="utf-8")
        for fragment in MOJIBAKE_FRAGMENTS:
            assert fragment not in text, f"{path} contains mojibake fragment {fragment!r}"


def test_output_size_labels_are_literal_chinese():
    output_sizes = (ROOT / "pages" / "Settings" / "output_sizes.json").read_text(encoding="utf-8")
    output_sizes_js = (ROOT / "pages" / "Settings" / "output_sizes.js").read_text(encoding="utf-8")

    for label in ("方图", "横屏", "竖屏"):
        assert label in output_sizes
        assert label in output_sizes_js

    for escaped_label in (r"\u65b9\u56fe", r"\u6a2a\u5c4f", r"\u7ad6\u5c4f"):
        assert escaped_label not in output_sizes_js
