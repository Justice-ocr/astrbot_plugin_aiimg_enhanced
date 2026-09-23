from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import httpx

from astrbot.api import logger

from .openai_video_service import OpenAIVideoService, _is_http_url
from .video_errors import VideoSubmissionUnknownError, VideoTaskAcceptedError


class XaiVideoService(OpenAIVideoService):
    """Native xAI JSON generation and request-id polling."""

    def __init__(self, *, settings: dict, data_dir=None):
        super().__init__(settings={
            **settings,
            "base_url": settings.get("base_url") or "https://api.x.ai",
            "model": settings.get("model") or "grok-imagine-video-1.5",
        }, data_dir=data_dir)
        self.reference_mode = settings.get("xai_reference_mode") or "reference"
        if self.reference_mode not in {"reference", "image", "text"}:
            raise ValueError("无效的 xAI 参考图模式")
        self.supports_selfie_reference_fallback = self.reference_mode != "text"
        self.duration = int(str(settings.get("duration") or "8"))
        if not 1 <= self.duration <= 15:
            raise ValueError("xAI 视频时长须为 1–15 秒")
        self.aspect_ratio = str(settings.get("aspect_ratio") or "16:9")
        if self.aspect_ratio not in {"auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("无效的 xAI 视频画幅")
        self.resolution = str(settings.get("xai_resolution") or "720p").lower()
        if self.resolution not in {"480p", "720p", "1080p"}:
            raise ValueError("xAI 分辨率支持 480p / 720p / 1080p")

    def _create_url(self):
        return f"{self._api_root()}/videos/generations"

    @staticmethod
    def _result_url(data):
        # Check moderation before considering alternative gateway URL fields.
        containers = [data]
        for name in ("video", "metadata"):
            value = data.get(name)
            if isinstance(value, dict):
                containers.append(value)
        if any(item.get("respect_moderation") is False for item in containers):
            raise RuntimeError("xAI 视频未通过内容审核")
        video = data.get("video")
        ordered = ([video] if isinstance(video, dict) else []) + containers
        for item in ordered:
            for name in ("url", "video_url"):
                value = item.get(name)
                if isinstance(value, str) and _is_http_url(value):
                    return value.strip()
        return ""

    async def generate_video_url(
        self, prompt, image_bytes=None, *, image_bytes_list=None,
        image_urls=None, preset=None, seconds=None, duration=None,
        aspect_ratio=None, resolution=None, reference_mode=None,
        on_task_accepted: Callable[[str], Awaitable[None]] | None = None,
    ):
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("xAI 视频提示词不能为空")
        images = list(image_bytes_list or ([image_bytes] if image_bytes else []))
        urls = list(image_urls or [])
        count = max(len(images), len(urls))
        selected_mode = str(reference_mode or self.reference_mode).strip().lower()
        if selected_mode not in {"reference", "image", "text"}:
            raise ValueError("无效的 xAI 参考图模式")
        selected_duration = int(str(duration or seconds or self.duration))
        if not 1 <= selected_duration <= 15:
            raise ValueError("xAI 视频时长须为 1–15 秒")
        selected_ratio = str(aspect_ratio or self.aspect_ratio)
        if selected_ratio not in {"auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("无效的 xAI 视频画幅")
        selected_resolution = str(resolution or self.resolution).lower()
        if selected_resolution not in {"480p", "720p", "1080p"}:
            raise ValueError("xAI 分辨率支持 480p / 720p / 1080p")
        if selected_mode == "text" and count:
            raise ValueError("纯文生视频模式不接受参考图")
        if count > 7 or (selected_mode == "image" and count > 1):
            raise ValueError("xAI 首帧模式最多 1 张图片，参考图模式最多 7 张")
        if selected_resolution == "1080p":
            if self.model != "grok-imagine-video-1.5":
                raise ValueError("1080p 仅对 grok-imagine-video-1.5 开放")
            if count and selected_mode == "reference":
                raise ValueError("xAI 多参考图模式最高支持 720p")
        refs = await self._prepare_reference_urls(images, urls)
        payload = {
            "model": self.model, "prompt": prompt, "duration": selected_duration,
            "resolution": selected_resolution,
        }
        if selected_ratio != "auto":
            payload["aspect_ratio"] = selected_ratio
        if refs:
            if selected_mode == "image":
                payload["image"] = {"url": refs[0]}
            else:
                payload["reference_images"] = [{"url": url} for url in refs]
        # Do not automatically retry a potentially billable submission.
        try:
            async with self._client(timeout=float(self.timeout)) as client:
                response = await client.post(
                    self._create_url(), headers=self._headers(), json=payload
                )
        except asyncio.CancelledError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise VideoSubmissionUnknownError(
                f"xAI 视频提交连接中断，任务可能已被接收，不会自动重试: {exc}"
            ) from exc
        if response.status_code not in {200, 201, 202}:
            raise RuntimeError(f"xAI 视频提交失败 HTTP {response.status_code}: {self._error_detail(response.json())}" if "application/json" in response.headers.get("content-type", "") else f"xAI 视频提交失败 HTTP {response.status_code}")
        try:
            data = response.json()
        except Exception as exc:
            raise VideoSubmissionUnknownError(
                "xAI 视频提交成功但响应无法解析，不会自动重试"
            ) from exc
        request_id = str(data.get("request_id") or "").strip()
        if not request_id:
            raise VideoSubmissionUnknownError(
                "xAI 视频提交成功但响应缺少 request_id，不会自动重试"
            )
        logger.info("[XaiVideo] 任务已提交: request_id=%s", request_id)
        if on_task_accepted is not None:
            await on_task_accepted(request_id)
        try:
            return await self._poll(request_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise VideoTaskAcceptedError(
                "xAI Video", request_id, "轮询", exc
            ) from exc

    async def _poll(self, request_id):
        deadline = time.monotonic() + self.poll_timeout
        consecutive_errors = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                async with self._client(timeout=min(30.0, remaining)) as client:
                    response = await asyncio.wait_for(
                        client.get(self._retrieve_url(request_id), headers=self._headers()),
                        timeout=remaining,
                    )
            except (httpx.TransportError, asyncio.TimeoutError) as exc:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise RuntimeError(f"xAI 视频查询连续网络失败, request_id={request_id}") from exc
                logger.warning("[XaiVideo] 查询网络异常，将重试: request_id=%s", request_id)
                continue
            if response.status_code in {408, 429} or response.status_code >= 500:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise RuntimeError(f"xAI 视频查询连续失败 HTTP {response.status_code}, request_id={request_id}")
                logger.warning("[XaiVideo] 查询 HTTP %s，将重试: request_id=%s", response.status_code, request_id)
                continue
            if response.status_code == 202:
                consecutive_errors = 0
                continue
            if response.status_code != 200:
                raise RuntimeError(f"xAI 视频查询失败 HTTP {response.status_code}, request_id={request_id}")
            data = response.json()
            consecutive_errors = 0
            if not isinstance(data, dict):
                raise RuntimeError(f"xAI 查询响应不是 JSON 对象, request_id={request_id}")
            status = str(data.get("status") or "").strip().lower()
            if status in {"failed", "expired", "cancelled", "canceled"}:
                raise RuntimeError(f"xAI 视频任务 {status}: {self._error_detail(data)}")
            if status in {"done", "completed", "succeeded", "success", ""}:
                url = self._result_url(data)
                if url:
                    return url
                if status:
                    raise RuntimeError(
                        f"xAI 完成响应缺少可用视频地址（video/url/video_url/metadata）, request_id={request_id}"
                    )
        raise RuntimeError(f"xAI 视频轮询超时, request_id={request_id}")

    async def resume_video_url(self, upstream_task_id: str) -> str:
        request_id = str(upstream_task_id or "").strip()
        if not request_id:
            raise ValueError("缺少 xAI 上游 request_id")
        return await self._poll(request_id)
