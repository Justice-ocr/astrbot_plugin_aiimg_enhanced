from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps


def slice_image(path: Path, rows: int, columns: int) -> list[tuple[bytes, dict]]:
    """Split every source pixel exactly once, including uneven edge tiles."""
    if not 1 <= rows <= 8 or not 1 <= columns <= 8 or rows * columns > 32:
        raise ValueError("Grid must contain at most 32 tiles, with 1-8 rows/columns")
    with Image.open(path) as source:
        if source.width * source.height > 32_000_000:
            raise ValueError("Image exceeds the 32 megapixel slicing limit")
        image = ImageOps.exif_transpose(source).convert("RGBA")
    try:
        width, height = image.size
        if width < columns or height < rows:
            raise ValueError("Grid exceeds source image dimensions")
        tiles = []
        for row in range(rows):
            for column in range(columns):
                box = (
                    column * width // columns, row * height // rows,
                    (column + 1) * width // columns, (row + 1) * height // rows,
                )
                with image.crop(box) as tile:
                    output = io.BytesIO()
                    tile.save(output, format="PNG")
                tiles.append((output.getvalue(), {"row": row, "column": column, "box": box}))
        return tiles
    finally:
        image.close()


def slice_regions(path: Path, regions: list[dict]) -> tuple[tuple[int, int], list[tuple[bytes, dict]]]:
    """Crop normalized floating-point rectangles against the oriented source."""
    if not isinstance(regions, list) or not 1 <= len(regions) <= 32:
        raise ValueError("Free slicing requires 1-32 regions")
    with Image.open(path) as source:
        if source.width * source.height > 32_000_000:
            raise ValueError("Image exceeds the 32 megapixel slicing limit")
        image = ImageOps.exif_transpose(source).convert("RGBA")
    try:
        width, height = image.size
        tiles = []
        for index, region in enumerate(regions):
            if not isinstance(region, dict):
                raise ValueError("Invalid slice region")
            values = [region.get(key) for key in ("x", "y", "width", "height")]
            if any(type(value) not in (int, float) for value in values):
                raise ValueError("Slice coordinates must be numbers")
            x, y, w, h = values
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.000001 and y + h <= 1.000001):
                raise ValueError("Slice region exceeds the source")
            box = (round(x * width), round(y * height), round((x + w) * width), round((y + h) * height))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Slice region has no pixels")
            with image.crop(box) as tile:
                output = io.BytesIO()
                tile.save(output, format="PNG")
            tiles.append((output.getvalue(), {"index": index, "box": box, "region": dict(zip(("x", "y", "width", "height"), values))}))
        return (width, height), tiles
    finally:
        image.close()
