from __future__ import annotations

import asyncio
import base64
import mimetypes
import pathlib
import re
import time
from collections.abc import Callable

from .image_format import decode_base64_image_payload


class PersonaRefService:
    """Stores and serves persona reference images for the Settings page."""

    max_bytes = 20 * 1024 * 1024

    def __init__(self, data_dir: str | pathlib.Path, now_ns: Callable[[], int] | None = None):
        self.data_dir = pathlib.Path(data_dir)
        self.ref_dir = self.data_dir / "persona_refs"
        self._now_ns = now_ns or time.time_ns

    @staticmethod
    def detect_ref_image(data: bytes) -> tuple[str, str] | None:
        if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
            return "image/jpeg", "jpg"
        if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png", "png"
        if len(data) >= 6 and data[:6] in {b"GIF87a", b"GIF89a"}:
            return "image/gif", "gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", "webp"
        return None

    @staticmethod
    def build_ref_filename(filename: str, ext: str, now_ns: int | None = None) -> str:
        stem = pathlib.Path(filename or "upload").stem.strip() or "upload"
        stem = re.sub(r"[^\w.-]+", "_", stem).strip("._") or "upload"
        stamp = time.time_ns() if now_ns is None else now_ns
        return f"{stamp}_{stem[:80]}.{ext}"

    def _safe_path(self, path: str) -> pathlib.Path:
        candidate = pathlib.Path(path)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self.data_dir.resolve())
        except (OSError, ValueError) as exc:
            raise ValueError("forbidden path") from exc
        if not resolved.is_file():
            raise FileNotFoundError("file not found")
        return resolved

    async def save_image_bytes(self, filename: str, data: bytes) -> tuple[str, str]:
        if len(data) > self.max_bytes:
            raise ValueError("file too large")
        detected = self.detect_ref_image(data)
        if detected is None:
            raise ValueError("unsupported image format")

        _mime, ext = detected
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self.build_ref_filename(filename, ext, self._now_ns())
        save_path = self.ref_dir / safe_name
        await asyncio.to_thread(save_path.write_bytes, data)
        return str(save_path), safe_name

    async def save_data_url(self, filename: str, data_url: str) -> tuple[str, str]:
        if not re.match(r"data:(image/[^;]+);base64,", data_url, re.DOTALL):
            raise ValueError("invalid image data")
        raw = decode_base64_image_payload(data_url)
        return await self.save_image_bytes(filename, raw)

    async def save_base64_refs(self, refs: list) -> list[str]:
        result: list[str] = []
        for ref in refs:
            value = str(ref or "").strip()
            if not value:
                continue
            if value.startswith("data:image"):
                path, _filename = await self.save_data_url("reference", value)
                result.append(path)
            else:
                result.append(value)
        return result

    async def preview_data_url(self, path: str) -> str:
        safe_path = self._safe_path(path)
        raw = await asyncio.to_thread(safe_path.read_bytes)
        detected = self.detect_ref_image(raw)
        mime = detected[0] if detected else (mimetypes.guess_type(str(safe_path))[0] or "image/png")
        b64 = base64.b64encode(raw).decode()
        return f"data:{mime};base64,{b64}"
