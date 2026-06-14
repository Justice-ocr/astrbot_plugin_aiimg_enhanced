import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MONITOR_SIZES = {
    "1920x1080",
    "2560x1440",
    "3840x2160",
    "1080x1920",
    "1440x2560",
}


def _extract_output_size_options() -> set[str]:
    app_js = (ROOT / "pages" / "Settings" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"const OUTPUT_SIZE_OPTIONS = \[(.*?)\];", app_js, re.S)
    assert match, "OUTPUT_SIZE_OPTIONS is missing"
    return set(re.findall(r"'([^']*)'", match.group(1)))


def _schema_option_lists(node):
    if isinstance(node, dict):
        if isinstance(node.get("options"), list):
            yield node["options"]
        for value in node.values():
            yield from _schema_option_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_option_lists(item)


def test_common_monitor_sizes_are_available_in_settings_dropdowns():
    options = _extract_output_size_options()

    assert REQUIRED_MONITOR_SIZES <= options


def test_common_monitor_sizes_are_available_in_static_feature_selects():
    index_html = (ROOT / "pages" / "Settings" / "index.html").read_text(encoding="utf-8")

    for size in REQUIRED_MONITOR_SIZES:
        assert f'<option value="{size}">{size}</option>' in index_html


def test_common_monitor_sizes_are_available_in_schema_options():
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    size_option_lists = [
        set(options)
        for options in _schema_option_lists(schema)
        if "1024x1024" in options and "4096x4096" in options
    ]

    assert size_option_lists, "No output-size option lists found in schema"
    for options in size_option_lists:
        assert REQUIRED_MONITOR_SIZES <= options
