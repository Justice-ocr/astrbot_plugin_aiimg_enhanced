from __future__ import annotations

import asyncio
import time

import httpx

from astrbot.api import logger

from .openai_video_service import OpenAIVideoService, _is_http_url


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

    async def generate_video_url(
        self, prompt, image_bytes=None, *, image_bytes_list=None,
        image_urls=None, preset=None,
    ):
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("xAI 视频提示词不能为空")
        images = list(image_bytes_list or ([image_bytes] if image_bytes else []))
        urls = list(image_urls or [])
        count = max(len(images), len(urls))
        if self.reference_mode == "text" and count:
            raise ValueError("纯文生视频模式不接受参考图")
        if count > 7 or (self.reference_mode == "image" and count > 1):
            raise ValueError("xAI 首帧模式最多 1 张图片，参考图模式最多 7 张")
        if self.resolution == "1080p":
            if self.model != "grok-imagine-video-1.5":
                raise ValueError("1080p 仅对 grok-imagine-video-1.5 开放")
            if count and self.reference_mode == "reference":
                raise ValueError("xAI 多参考图模式最高支持 720p")
        refs = await self._prepare_reference_urls(images, urls)
        payload = {
            "model": self.model, "prompt": prompt, "duration": self.duration,
            "resolution": self.resolution,
        }
        if self.aspect_ratio != "auto":
            payload["aspect_ratio"] = self.aspect_ratio
        if refs:
            if self.reference_mode == "image":
                payload["image"] = {"url": refs[0]}
            else:
                payload["reference_images"] = [{"url": url} for url in refs]
        # Do not automatically retry a potentially billable submission.
        async with self._client(timeout=float(self.timeout)) as client:
            response = await client.post(self._create_url(), headers=self._headers(), json=payload)
        if response.status_code not in {200, 201, 202}:
            raise RuntimeError(f"xAI 视频提交失败 HTTP {response.status_code}: {self._error_detail(response.json())}" if "application/json" in response.headers.get("content-type", "") else f"xAI 视频提交失败 HTTP {response.status_code}")
        request_id = str(response.json().get("request_id") or "").strip()
        if not request_id:
            raise RuntimeError("xAI 视频响应缺少 request_id")
        logger.info("[XaiVideo] 任务已提交: request_id=%s", request_id)
        return await self._poll(request_id)

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
            if response.status_code != 200:
                raise RuntimeError(f"xAI 视频查询失败 HTTP {response.status_code}, request_id={request_id}")
            data = response.json()
            consecutive_errors = 0
            status = str(data.get("status") or "").lower()
            if status in {"failed", "expired", "cancelled", "canceled"}:
                raise RuntimeError(f"xAI 视频任务 {status}: {self._error_detail(data)}")
            if status == "done":
                video = data.get("video") or {}
                if video.get("respect_moderation") is False:
                    raise RuntimeError("xAI 视频未通过内容审核")
                url = video.get("url")
                if not _is_http_url(url):
                    raise RuntimeError("xAI 完成响应缺少 video.url")
                return url
        raise RuntimeError(f"xAI 视频轮询超时, request_id={request_id}")
