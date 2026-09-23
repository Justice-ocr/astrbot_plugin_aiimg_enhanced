from __future__ import annotations

import asyncio
import base64
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlsplit

import httpx

from astrbot.api import logger

from .image_format import guess_image_mime_and_ext, guess_image_mime_and_ext_strict
from .repeatable_file_tokens import (
    install_repeatable_file_token_support,
    mark_repeatable_file_token,
)
from .video_errors import VideoSubmissionUnknownError, VideoTaskAcceptedError


_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
_DONE_STATUSES = {"succeeded"}
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


class MiniMaxH3VideoService:
    """MiniMax H3 video generation V2 backend."""

    supports_multiple_images = True
    supports_selfie_reference_fallback = True

    def __init__(self, *, settings: dict, data_dir: Path | str | None = None):
        s = settings if isinstance(settings, dict) else {}
        self.data_dir = Path(data_dir or ".")
        self.base_url = str(s.get("base_url") or "https://api.minimax.io").rstrip("/")
        self.model = str(s.get("model") or "MiniMax-H3").strip()

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
        self.duration = _clamp_int(s.get("duration", 5), 5, 4, 15)
        self.resolution = str(s.get("resolution") or "2K").strip().upper()
        self.ratio = str(s.get("ratio") or "16:9").strip()
        self.image_handling_method = str(
            s.get("image_handling_method") or "data_uri"
        ).strip().lower()
        self.file_service_base_url = str(
            s.get("file_service_base_url") or ""
        ).strip().rstrip("/")
        self.enable_file_service_magic = bool(s.get("enable_file_service_magic", True))
        self.proxy_url = str(s.get("proxy_url") or "").strip() or None

    def _get_key(self) -> str:
        if not self.api_keys:
            raise RuntimeError("未配置 MiniMax API Key")
        return self.api_keys[0]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_key()}",
            "Content-Type": "application/json",
        }

    def _create_url(self) -> str:
        return f"{self.base_url}/v2/video_generation"

    def _poll_url(self, task_id: str) -> str:
        return f"{self.base_url}/v2/query/video_generation/{quote(task_id, safe='')}"

    def _client(self, *, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=timeout, write=30.0, pool=timeout + 15.0),
            follow_redirects=True,
            proxy=self.proxy_url,
        )

    def _install_file_service_magic(self, file_token_service: Any) -> None:
        if not self.enable_file_service_magic:
            return
        if not install_repeatable_file_token_support(file_token_service):
            logger.warning("[MiniMaxH3] 当前 AstrBot 文件服务不支持可重复访问补丁")

    def _resolve_file_service_base_url(self) -> str:
        if self.file_service_base_url:
            if not _is_http_url(self.file_service_base_url):
                raise RuntimeError("AstrBot 文件服务公网地址必须以 http:// 或 https:// 开头")
            return self.file_service_base_url
        try:
            from astrbot.core import astrbot_config

            base_url = str(astrbot_config.get("callback_api_base", "") or "").strip()
        except Exception:
            base_url = ""
        if not _is_http_url(base_url):
            raise RuntimeError(
                "未配置 AstrBot 文件服务公网地址，且 callback_api_base 不可用"
            )
        return base_url.rstrip("/")

    async def _to_astrbot_url(self, image_bytes: bytes) -> tuple[str, Path]:
        try:
            from astrbot.core import file_token_service
        except Exception as exc:
            raise RuntimeError("当前 AstrBot 不提供文件 token 服务") from exc

        base_url = self._resolve_file_service_base_url()
        self._install_file_service_magic(file_token_service)
        _, ext = guess_image_mime_and_ext(image_bytes)
        cache_dir = self.data_dir / "minimax_h3_refs"
        await asyncio.to_thread(cache_dir.mkdir, parents=True, exist_ok=True)
        file_path = cache_dir / f"minimax_h3_ref_{uuid.uuid4().hex}.{ext}"
        await asyncio.to_thread(file_path.write_bytes, image_bytes)
        try:
            token = str(await file_token_service.register_file(str(file_path)) or "").strip()
        except Exception:
            file_path.unlink(missing_ok=True)
            raise
        if not token:
            file_path.unlink(missing_ok=True)
            raise RuntimeError("AstrBot 文件服务未返回有效 token")
        if self.enable_file_service_magic:
            try:
                mark_repeatable_file_token(file_token_service, token, file_path)
            except Exception:
                file_path.unlink(missing_ok=True)
                raise
        return f"{base_url}/api/file/{token}", file_path

    @staticmethod
    def _to_data_uri(image_bytes: bytes) -> str:
        detected = guess_image_mime_and_ext_strict(image_bytes)
        if detected is None or detected[0] not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise RuntimeError("MiniMax H3 本地参考图仅支持 JPEG、PNG 或 WEBP")
        mime, _ = detected
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    async def _prepare_reference_urls(
        self,
        image_bytes_list: list[bytes],
        image_urls: list[str],
        *,
        temporary_paths: list[Path] | None = None,
    ) -> list[str]:
        refs: list[str] = []
        count = min(max(len(image_bytes_list), len(image_urls)), 9)
        for index in range(count):
            source_url = image_urls[index] if index < len(image_urls) else ""
            if _is_http_url(source_url):
                refs.append(source_url.strip())
                continue

            image_bytes = image_bytes_list[index] if index < len(image_bytes_list) else b""
            if not image_bytes:
                raise RuntimeError(f"MiniMax H3 第 {index + 1} 张参考图缺少可用数据")
            if self.image_handling_method in {"data_uri", "auto"}:
                refs.append(self._to_data_uri(image_bytes))
            elif self.image_handling_method == "astrbot":
                url, file_path = await self._to_astrbot_url(image_bytes)
                refs.append(url)
                if temporary_paths is not None:
                    temporary_paths.append(file_path)
            else:
                raise RuntimeError("MiniMax H3 本地参考图处理已禁用")
        return refs

    def _build_payload(
        self,
        prompt: str,
        refs: list[str],
        *,
        duration: str | int | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
    ) -> dict[str, Any]:
        if self.model != "MiniMax-H3":
            raise RuntimeError("当前 MiniMax H3 模板仅支持 MiniMax-H3")
        selected_duration = _clamp_int(duration, self.duration, 1, 15)
        selected_resolution = str(resolution or self.resolution).strip().upper()
        selected_ratio = str(ratio or self.ratio).strip()
        if selected_resolution not in {"768P", "2K", "480P", "1080P"}:
            raise RuntimeError("MiniMax-H3 分辨率仅支持 768P 或 2K")
        if selected_ratio not in _RATIOS:
            raise RuntimeError(f"MiniMax-H3 不支持画幅 {selected_ratio}")
        text = str(prompt or "").strip()
        if not text:
            raise RuntimeError("MiniMax H3 视频提示词不能为空")

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        ratio = selected_ratio
        if len(refs) == 1:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": refs[0]},
                    "role": "first_frame",
                }
            )
            ratio = "adaptive"
        elif refs:
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": url},
                    "role": "reference_image",
                }
                for url in refs[:9]
            )
        elif ratio == "adaptive":
            raise RuntimeError("MiniMax H3 文生视频不能使用 adaptive 画幅")

        return {
            "model": self.model,
            "content": content,
            "resolution": selected_resolution,
            "duration": selected_duration,
            "ratio": ratio,
        }

    async def _submit(self, payload: dict[str, Any]) -> str:
        url = self._create_url()
        try:
            async with self._client(timeout=float(self.timeout)) as client:
                response = await client.post(url, headers=self._headers(), json=payload)
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise VideoSubmissionUnknownError(
                f"MiniMax H3 提交连接中断，任务可能已被接收，不会自动重试: {exc}"
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"MiniMax H3 提交任务失败 HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except Exception as exc:
            raise VideoSubmissionUnknownError(
                "MiniMax H3 提交成功但响应无法解析，不会自动重试"
            ) from exc
        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            raise VideoSubmissionUnknownError(
                f"MiniMax H3 提交成功但没有 task_id，不会自动重试: {str(data)[:300]}"
            )
        return task_id

    @staticmethod
    def _parse_poll_result(data: Any) -> tuple[str, str, str]:
        task = data.get("task") if isinstance(data, dict) else None
        task = task if isinstance(task, dict) else {}
        status = str(task.get("status") or "").strip().lower()
        content = task.get("content")
        video_url = (
            str(content.get("url") or "").strip()
            if isinstance(content, dict)
            else ""
        )
        error = task.get("error")
        detail = (
            str(error.get("message") or "").strip()
            if isinstance(error, dict)
            else str(error or "").strip()
        )
        return status, video_url, detail

    async def _poll(self, task_id: str) -> str:
        url = self._poll_url(task_id)
        deadline = time.monotonic() + self.poll_timeout
        consecutive_errors = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            try:
                async with self._client(timeout=30.0) as client:
                    response = await client.get(url, headers=self._headers())
                if response.status_code != 200:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        raise RuntimeError(
                            f"MiniMax H3 轮询连续失败 HTTP {response.status_code}: {response.text[:200]}"
                        )
                    continue
                data = response.json()
                consecutive_errors = 0
                status, video_url, detail = self._parse_poll_result(data)
                if status in _FAIL_STATUSES:
                    raise RuntimeError(f"MiniMax H3 视频生成失败: {detail or status}")
                if _is_http_url(video_url):
                    return video_url
                if status in _DONE_STATUSES:
                    raise RuntimeError("MiniMax H3 任务已完成但未返回 task.content.url")
            except asyncio.CancelledError:
                raise
            except RuntimeError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("[MiniMaxH3] 轮询异常: %s", exc)
                if consecutive_errors >= 3:
                    raise RuntimeError(f"MiniMax H3 连续轮询异常: {exc}") from exc
        raise RuntimeError(f"MiniMax H3 视频轮询超时（{self.poll_timeout}s），task_id={task_id}")

    async def resume_video_url(self, upstream_task_id: str) -> str:
        task_id = str(upstream_task_id or "").strip()
        if not task_id:
            raise ValueError("缺少 MiniMax H3 上游任务 ID")
        return await self._poll(task_id)

    async def generate_video_url(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        *,
        image_bytes_list: list[bytes] | None = None,
        image_urls: list[str] | None = None,
        preset: str | None = None,
        duration: str | int | None = None,
        seconds: str | int | None = None,
        resolution: str | None = None,
        ratio: str | None = None,
        aspect_ratio: str | None = None,
        on_task_accepted: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        del preset
        byte_items = list(image_bytes_list or ([] if image_bytes is None else [image_bytes]))
        url_items = list(image_urls or [])
        temporary_paths: list[Path] = []
        try:
            refs = await self._prepare_reference_urls(
                byte_items, url_items, temporary_paths=temporary_paths
            )
            payload = self._build_payload(
                prompt,
                refs,
                duration=duration if duration is not None else seconds,
                resolution=resolution,
                ratio=ratio if ratio is not None else aspect_ratio,
            )
            task_id = await self._submit(payload)
            logger.info("[MiniMaxH3] 任务已提交: task_id=%s", task_id)
            if on_task_accepted is not None:
                await on_task_accepted(task_id)
            try:
                return await self._poll(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise VideoTaskAcceptedError(
                    "MiniMax H3", task_id, "轮询", exc
                ) from exc
        finally:
            for path in temporary_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("[MiniMaxH3] 清理临时参考图失败: %s", exc)
