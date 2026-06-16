from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIZE_SOURCE = ROOT / "pages" / "Settings" / "output_sizes.json"
SCHEMA_PATH = ROOT / "_conf_schema.json"
HINT_EXAMPLES = ["1024x1024", "2048x2048", "4096x4096", "2560x1440", "1440x2560"]


def normalize_size(size: str | None) -> str:
    return str(size or "").strip().lower().replace("×", "x").replace("脳", "x")


def is_16_aligned_size(size: str) -> bool:
    match = re.fullmatch(r"(\d+)x(\d+)", normalize_size(size))
    if not match:
        return False
    width = int(match.group(1))
    height = int(match.group(2))
    return width % 16 == 0 and height % 16 == 0


def source_sizes() -> list[str]:
    data = json.loads(SIZE_SOURCE.read_text(encoding="utf-8"))
    out: list[str] = []
    for group in data.get("groups", []):
        for item in group.get("sizes", []):
            size = normalize_size(item.get("value"))
            if size and is_16_aligned_size(size) and size not in out:
                out.append(size)
    return out


def update_options(node, sizes: list[str]) -> None:
    if isinstance(node, dict):
        options = node.get("options")
        if (
            isinstance(options, list)
            and "1024x1024" in options
            and "4096x4096" in options
        ):
            node["options"] = sizes.copy()
        hint = node.get("hint")
        if (
            isinstance(hint, str)
            and "1024x1024" in hint
            and "4096x4096" in hint
        ):
            suffix = "。"
            if "。留空则由服务商默认决定。" in hint:
                suffix = "。留空则由服务商默认决定。"
            examples = [size for size in HINT_EXAMPLES if size in sizes]
            node["hint"] = f"例：{' / '.join(examples)}{suffix}"
        for value in node.values():
            update_options(value, sizes)
    elif isinstance(node, list):
        for item in node:
            update_options(item, sizes)


def main() -> None:
    sizes = source_sizes()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    update_options(schema, sizes)
    SCHEMA_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
