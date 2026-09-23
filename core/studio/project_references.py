from __future__ import annotations

from typing import Any


def asset_references(document: Any) -> set[str]:
    """Collect explicit asset fields, including GIF frame lists."""
    result: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"asset_id", "result_asset_id", "output_asset_id"} and isinstance(item, str) and item:
                    result.add(item)
                elif key in {"asset_ids", "reference_asset_ids", "slice_asset_ids", "frames"} and isinstance(item, list):
                    result.update(entry for entry in item if isinstance(entry, str) and entry)
                    for entry in item:
                        if isinstance(entry, (dict, list)):
                            visit(entry)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)
    return result
