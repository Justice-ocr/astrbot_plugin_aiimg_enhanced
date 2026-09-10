from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path

from .image_format import guess_image_mime_and_ext


class HistoryPageService:
    def __init__(self, history, data_dir):
        self.history = history
        self.image_dir = (Path(data_dir) / "history_images").resolve()

    def safe_path(self, path: str) -> Path:
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.image_dir):
            raise ValueError("图片路径无效")
        return resolved

    async def browse(self, *, page: int = 1, query: str = "") -> dict:
        result = await self.history.browse(page=page, query=query[:200])

        def project():
            items = []
            for row in result["items"]:
                meta = row["metadata"]
                try:
                    available = self.safe_path(row["path"]).is_file()
                except (ValueError, OSError):
                    available = False
                try:
                    scope = json.loads(row["scope"])
                    origin, bot, sender, conversation = scope
                except (ValueError, TypeError):
                    origin = bot = sender = conversation = ""
                tries = meta.get("provider_tries") or []
                provider = next((
                    str(item.get("pid", "")) for item in reversed(tries)
                    if isinstance(item, dict) and item.get("ok")
                ), str(meta.get("backend") or ""))
                items.append({
                    "id": row["id"], "sequence": row["sequence"], "created_at": row["created_at"],
                    "prompt": str(meta.get("user_prompt") or ""),
                    "effective_prompt": str(meta.get("effective_prompt") or ""),
                    "mode": str(meta.get("mode") or ""),
                    "provider": provider, "output": str(meta.get("size") or meta.get("resolution") or ""),
                    "parent_image_id": meta.get("parent_image_id"),
                    "origin": origin, "bot": bot, "sender": sender,
                    "conversation": conversation, "available": available,
                    "conversation_title": str(meta.get("conversation_title") or ""),
                })
            return {**result, "items": items}
        return await asyncio.to_thread(project)

    async def image(self, image_id: int, *, original: bool = False) -> dict:
        row = await self.history.get_for_admin(image_id)
        if row is None:
            raise FileNotFoundError("图片记录不存在")
        path = self.safe_path(row["path"])

        def encode():
            if not path.is_file():
                raise FileNotFoundError("图片缓存已过期")
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("图片超过 50 MB，无法通过页面传输")
            data = path.read_bytes()
            if original:
                mime, ext = guess_image_mime_and_ext(data)
            else:
                from PIL import Image, ImageOps
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height > 40_000_000:
                        raise ValueError("图片像素过大，无法预览")
                    image.thumbnail((640, 640))
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    output = io.BytesIO()
                    image.save(output, format="JPEG", quality=82)
                    data = output.getvalue()
                mime, ext = "image/jpeg", "jpg"
            return {
                "image_data": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
                "filename": f"aiimg-{image_id}.{ext.lstrip('.')}",
            }
        return await asyncio.to_thread(encode)
