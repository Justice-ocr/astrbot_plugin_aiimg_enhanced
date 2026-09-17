from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import aiofiles
import httpx

from astrbot.api import logger

from .image_format import guess_image_mime_and_ext


_DONE_STATUSES = {"completed", "succeeded"}
_FAIL_STATUSES = {"failed", "cancelled", "canceled"}


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _is_http_url(value: Any) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_url(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("url", "video_url", "download_url"):
        value = str(data.get(key) or "").strip()
        if _is_http_url(value):
            return value
    items = data.get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return _extract_url(items[0])
    return ""


class OpenAIVideoService:
    """OpenAI-compatible Videos API backend."""

    def __init__(self, *, settings: dict, data_dir: Path | str | None = None):
        s = settings if isinstance(settings, dict) else {}
        self.data_dir = Path(data_dir or ".")
        self.base_url = str(s.get("base_url") or "https://api.openai.com").rstrip("/")
        self.model = str(s.get("model") or "sora-2").strip()

        api_keys = s.get("api_keys") or []
        if isinstance(api_keys, str):
            api_keys = [line.strip() for line in api_keys.splitlines() if line.strip()]
        if not api_keys and s.get("api_key"):
            api_keys = [str(s.get("api_key") or "").strip()]
        self.api_keys = [str(key).strip() for key in api_keys if str(key).strip()]

        self.timeout = _clamp_int(s.get("timeout", 120), 120, 10, 3600)
        self.max_retries = _clamp_int(s.get("max_retries", 1), 1, 0, 10)
        self.poll_interval = _clamp_int(s.get("poll_interval", 10), 10, 1, 60)
        self.poll_timeout = _clamp_int(s.get("poll_timeout", 1200), 1200, 30, 7200)
        self.seconds = str(s.get("seconds") or "4").strip()
        self.size = str(s.get("size") or "").strip()
        self.input_reference_field = str(
            s.get("input_reference_field") or "input_reference"
        ).strip() or "input_reference"
        self.max_download_bytes = _clamp_int(
            s.get("max_download_mb", 500), 500, 10, 2048
        ) * 1024 * 1024
        self.max_cached_videos = _clamp_int(
            s.get("max_cached_videos", 20), 20, 1, 500
        )
        self.proxy_url = str(s.get("proxy_url") or "").strip() or None

        extra = s.get("extra_form")
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        self.extra_form = extra if isinstance(extra, dict) else {}

    def _get_key(self) -> str:
        if not self.api_keys:
            raise RuntimeError("未配置 OpenAI Videos API Key")
        return self.api_keys[0]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_key()}"}

    def _api_root(self) -> str:
        if self.base_url.lower().endswith("/v1"):
            return self.base_url
        return f"{self.base_url}/v1"

    def _create_url(self) -> str:
        return f"{self._api_root()}/videos"

    def _retrieve_url(self, video_id: str) -> str:
        return f"{self._api_root()}/videos/{quote(video_id, safe='')}"

    def _content_url(self, video_id: str) -> str:
        return f"{self._retrieve_url(video_id)}/content"

    def _client(self, *, timeout: float, follow_redirects: bool = True) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=15.0,
                read=timeout,
                write=max(30.0, timeout),
                pool=timeout + 15.0,
            ),
            follow_redirects=follow_redirects,
            proxy=self.proxy_url,
        )

    @staticmethod
    def _error_detail(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "").strip()
        return str(error or "").strip()

    def _multipart_fields(
        self, prompt: str, image_bytes: bytes | None
    ) -> list[tuple[str, Any]]:
        text = str(prompt or "").strip()
        if not text:
            raise RuntimeError("OpenAI Videos 提示词不能为空")
        if not self.model:
            raise RuntimeError("未配置 OpenAI Videos 模型")

        fields: list[tuple[str, Any]] = [
            ("model", (None, self.model)),
            ("prompt", (None, text)),
        ]
        if self.seconds:
            fields.append(("seconds", (None, self.seconds)))
        if self.size:
            fields.append(("size", (None, self.size)))
        for key, value in self.extra_form.items():
            name = str(key or "").strip()
            if not name or value is None:
                continue
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            fields.append((name, (None, rendered)))
        if image_bytes:
            mime, ext = guess_image_mime_and_ext(image_bytes)
            fields.append(
                (
                    self.input_reference_field,
                    (f"reference.{ext}", image_bytes, mime),
                )
            )
        return fields

    async def _submit(self, prompt: str, image_bytes: bytes | None) -> str:
        last_error: Exception | None = None
        fields = self._multipart_fields(prompt, image_bytes)
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2**attempt, 10))
            try:
                async with self._client(timeout=float(self.timeout)) as client:
                    response = await client.post(
                        self._create_url(), headers=self._headers(), files=fields
                    )
                if response.status_code not in {200, 201, 202}:
                    raise RuntimeError(
                        f"OpenAI Videos 提交失败 HTTP {response.status_code}: "
                        f"{response.text[:300]}"
                    )
                data = response.json()
                video_id = str(data.get("id") or data.get("task_id") or "").strip()
                if not video_id:
                    raise RuntimeError(f"OpenAI Videos 未返回任务 ID: {str(data)[:300]}")
                return video_id
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        raise last_error or RuntimeError("OpenAI Videos 任务提交失败")

    async def _cleanup_cached_videos(self) -> None:
        video_dir = self.data_dir / "videos"
        try:
            files = [path for path in video_dir.iterdir() if path.is_file()]
            if len(files) <= self.max_cached_videos:
                return
            files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            for path in files[self.max_cached_videos :]:
                await asyncio.to_thread(path.unlink, missing_ok=True)
        except Exception as exc:
            logger.warning("[OpenAIVideo] 清理旧视频失败: %s", exc)

    async def _download_content(self, video_id: str) -> str:
        video_dir = self.data_dir / "videos"
        await asyncio.to_thread(video_dir.mkdir, parents=True, exist_ok=True)
        final_path = video_dir / f"openai_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"
        temp_path = final_path.with_suffix(".mp4.part")
        try:
            async with self._client(timeout=float(self.timeout)) as client:
                async with client.stream(
                    "GET", self._content_url(video_id), headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise RuntimeError(
                            f"OpenAI Videos 下载失败 HTTP {response.status_code}: {body[:300]}"
                        )

                    content_type = str(response.headers.get("content-type") or "").lower()
                    if "application/json" in content_type:
                        body = await response.aread()
                        try:
                            data = json.loads(body.decode("utf-8"))
                        except Exception as exc:
                            raise RuntimeError("OpenAI Videos 内容响应 JSON 解析失败") from exc
                        url = _extract_url(data)
                        if url:
                            return url
                        raise RuntimeError(
                            f"OpenAI Videos 内容响应未包含视频 URL: {str(data)[:300]}"
                        )

                    total = 0
                    async with aiofiles.open(temp_path, "wb") as file:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > self.max_download_bytes:
                                raise RuntimeError("OpenAI Videos 下载结果超过大小限制")
                            await file.write(chunk)
            if not temp_path.exists() or temp_path.stat().st_size <= 0:
                raise RuntimeError("OpenAI Videos 下载结果为空")
            await asyncio.to_thread(temp_path.replace, final_path)
            await self._cleanup_cached_videos()
            return str(final_path)
        except asyncio.CancelledError:
            temp_path.unlink(missing_ok=True)
            raise
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    async def _poll(self, video_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout
        consecutive_errors = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            try:
                async with self._client(timeout=30.0) as client:
                    response = await client.get(
                        self._retrieve_url(video_id), headers=self._headers()
                    )
                if response.status_code != 200:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        raise RuntimeError(
                            f"OpenAI Videos 轮询连续失败 HTTP {response.status_code}: "
                            f"{response.text[:200]}"
                        )
                    continue
                data = response.json()
                consecutive_errors = 0
                status = str(data.get("status") or "").strip().lower()
                if status in _FAIL_STATUSES:
                    raise RuntimeError(
                        f"OpenAI Videos 生成失败: {self._error_detail(data) or status}"
                    )
                direct_url = _extract_url(data)
                if direct_url:
                    return direct_url
                if status in _DONE_STATUSES:
                    return await self._download_content(video_id)
            except asyncio.CancelledError:
                raise
            except RuntimeError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("[OpenAIVideo] 轮询异常: %s", exc)
                if consecutive_errors >= 3:
                    raise RuntimeError(f"OpenAI Videos 连续轮询异常: {exc}") from exc
        raise RuntimeError(
            f"OpenAI Videos 轮询超时（{self.poll_timeout}s），video_id={video_id}"
        )

    async def generate_video_url(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        *,
        preset: str | None = None,
    ) -> str:
        del preset
        video_id = await self._submit(prompt, image_bytes)
        logger.info("[OpenAIVideo] 任务已提交: video_id=%s", video_id)
        return await self._poll(video_id)
