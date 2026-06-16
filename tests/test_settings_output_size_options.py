import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIZE_SOURCE = ROOT / "pages" / "Settings" / "output_sizes.json"
SYNC_SCRIPT = ROOT / "scripts" / "sync_output_size_schema.py"
REQUIRED_SIZES = {"2560x1440", "1440x2560"}
REMOVED_NON_16_SIZES = {"1920x1080", "3840x2160", "1080x1920"}


def _source() -> dict:
    return json.loads(SIZE_SOURCE.read_text(encoding="utf-8"))


def _source_sizes() -> set[str]:
    data = _source()
    sizes: set[str] = set()
    for group in data["groups"]:
        for item in group["sizes"]:
            sizes.add(item["value"])
    return sizes


def _source_group_labels() -> set[str]:
    return {group["label"] for group in _source()["groups"]}


def _schema_option_lists(node):
    if isinstance(node, dict):
        if isinstance(node.get("options"), list):
            yield node["options"]
        for value in node.values():
            yield from _schema_option_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_option_lists(item)


def test_output_size_source_has_grouped_common_sizes():
    assert SIZE_SOURCE.exists()
    data = _source()

    assert {"方图", "横屏", "竖屏"} <= _source_group_labels()
    assert REQUIRED_SIZES <= _source_sizes()
    assert REMOVED_NON_16_SIZES.isdisjoint(_source_sizes())


def test_output_size_source_only_contains_dimensions_divisible_by_16():
    for size in _source_sizes():
        width, height = [int(part) for part in size.split("x", 1)]
        assert width % 16 == 0, size
        assert height % 16 == 0, size


def test_static_feature_selects_are_populated_from_javascript_only():
    index_html = (ROOT / "pages" / "Settings" / "index.html").read_text(encoding="utf-8")

    for size in _source_sizes() | REMOVED_NON_16_SIZES:
        assert f'<option value="{size}">' not in index_html


def test_settings_javascript_loads_single_size_source_and_renders_groups():
    app_js = (ROOT / "pages" / "Settings" / "app.js").read_text(encoding="utf-8")

    assert "output_sizes.json" in app_js
    assert "OUTPUT_SIZE_OPTIONS = [" not in app_js
    assert "<optgroup" in app_js


def test_common_monitor_sizes_are_available_in_schema_options():
    schema_text = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
    schema = json.loads(schema_text)
    source_sizes = _source_sizes()
    size_option_lists = [
        set(options)
        for options in _schema_option_lists(schema)
        if "1024x1024" in options and "4096x4096" in options
    ]

    assert size_option_lists, "No output-size option lists found in schema"
    for options in size_option_lists:
        assert REQUIRED_SIZES <= options
        assert REMOVED_NON_16_SIZES.isdisjoint(options)
        assert options <= source_sizes
    for removed in REMOVED_NON_16_SIZES:
        assert removed not in schema_text


def test_schema_sync_script_is_idempotent():
    before = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")

    subprocess.run([sys.executable, str(SYNC_SCRIPT)], cwd=ROOT, check=True)

    after = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
    assert after == before
