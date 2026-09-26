from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .asset_store import StudioAssetStore


class StudioAppearanceStore:
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    DEFAULT_MASK_OPACITY = 0.82
    IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

    def __init__(self, data_dir: str | Path):
        self.folder = Path(data_dir).resolve() / "studio_appearance"
        self.background = self.folder / "background"
        self.settings = self.folder / "settings.json"
        self._lock = asyncio.Lock()

    def _settings(self) -> dict:
        try:
            data = json.loads(self.settings.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        try:
            opacity = float(data.get("mask_opacity", self.DEFAULT_MASK_OPACITY))
        except (TypeError, ValueError):
            opacity = self.DEFAULT_MASK_OPACITY
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            opacity = self.DEFAULT_MASK_OPACITY
        mime = data.get("mime")
        return {
            "mask_opacity": opacity,
            "mime": mime if mime in self.IMAGE_TYPES.values() else "",
        }

    def _read(self) -> dict:
        settings = self._settings()
        image_data = ""
        if settings["mime"] and self.background.is_file():
            raw = self.background.read_bytes()
            if len(raw) <= self.MAX_IMAGE_BYTES:
                image_data = f"data:{settings['mime']};base64,{base64.b64encode(raw).decode('ascii')}"
        return {"mask_opacity": settings["mask_opacity"], "image_data": image_data}

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _validate_image(cls, image_data: str) -> tuple[str, bytes]:
        if len(image_data) > (cls.MAX_IMAGE_BYTES * 4 // 3) + 128:
            raise ValueError("背景图片不能超过 8 MB")
        declared_mime, raw = StudioAssetStore.decode_data_url(image_data)
        if len(raw) > cls.MAX_IMAGE_BYTES:
            raise ValueError("背景图片不能超过 8 MB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                mime = cls.IMAGE_TYPES.get(image.format or "")
                if mime is None or mime != declared_mime:
                    raise ValueError("背景图片仅支持 JPEG、PNG 或 WebP")
                if image.width * image.height > 40_000_000:
                    raise ValueError("背景图片像素过大")
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("背景图片内容无效") from exc
        return mime, raw

    async def get(self) -> dict:
        async with self._lock:
            return await asyncio.to_thread(self._read)

    async def save(self, *, mask_opacity: object, image_data: object = None, remove_image: bool = False) -> dict:
        if isinstance(mask_opacity, bool):
            raise ValueError("遮罩不透明度必须在 0 到 1 之间")
        try:
            opacity = float(mask_opacity)
        except (TypeError, ValueError) as exc:
            raise ValueError("遮罩不透明度必须在 0 到 1 之间") from exc
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("遮罩不透明度必须在 0 到 1 之间")
        if remove_image and image_data is not None:
            raise ValueError("不能同时上传和移除背景")
        image = None
        if image_data is not None:
            if not isinstance(image_data, str):
                raise ValueError("背景图片格式无效")
            image = self._validate_image(image_data)

        async with self._lock:
            def write() -> dict:
                self.folder.mkdir(parents=True, exist_ok=True)
                mime = self._settings()["mime"]
                if image is not None:
                    mime, raw = image
                    self._atomic_write(self.background, raw)
                elif remove_image:
                    mime = ""
                    self.background.unlink(missing_ok=True)
                self._atomic_write(
                    self.settings,
                    json.dumps({"mask_opacity": opacity, "mime": mime}).encode("utf-8"),
                )
                return self._read()

            return await asyncio.to_thread(write)
