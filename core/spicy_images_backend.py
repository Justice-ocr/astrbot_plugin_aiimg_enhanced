from __future__ import annotations

import asyncio
import base64
import io
import time
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image


class SpicyImagesBackend:
    """SpicyAPI's nested-input task protocol (not OpenAI Images)."""

    def __init__(self, *, imgr, settings: dict):
        self.imgr = imgr
        self.settings = deepcopy(settings)
        self.supports_edit = bool(settings.get("supports_edit", True))
        root = str(settings.get("base_url") or "https://api.spicyapi.ai").rstrip("/")
        if root.endswith("/api/v1"):
            root = root[:-7]
        self.base_url = root
        self.keys = [str(k).strip() for k in settings.get("api_keys", []) if str(k).strip()]
        self._key_index = 0

    async def close(self):
        pass

    def _client(self):
        options = {"timeout": httpx.Timeout(float(self.settings.get("timeout", 120)), connect=30)}
        proxy = str(self.settings.get("proxy_url") or "").strip()
        if proxy:
            options["proxy"] = proxy
        return httpx.AsyncClient(**options)

    def _input(self, prompt, images, *, size=None, resolution=None):
        if not str(prompt or "").strip():
            raise ValueError("SpicyAPI 提示词不能为空")
        if images and not self.settings.get("supports_edit", True):
            raise ValueError("SpicyAPI 服务商未开启改图")
        limit = int(self.settings.get("max_reference_images", 10))
        if len(images) > limit:
            raise ValueError(f"SpicyAPI 当前配置最多允许 {limit} 张参考图")
        model = str((self.settings.get("edit_model") if images else self.settings.get("model")) or "").strip()
        if not model:
            raise ValueError("SpicyAPI 未配置对应操作的完整模型 ID")
        extra = self.settings.get("extra_input") or {}
        if isinstance(extra, str):
            import json
            extra = json.loads(extra)
        if not isinstance(extra, dict):
            raise ValueError("SpicyAPI extra_input 必须是 JSON 对象")
        if {"prompt", "image_urls"} & extra.keys():
            raise ValueError("extra_input 不能覆盖 prompt 或 image_urls")
        if any(name in extra and extra[name] != 1 for name in ("num_outputs", "n", "num_images")):
            raise ValueError("SpicyAPI 当前每次任务仅支持一张输出图，请将输出数量设为 1")
        data = deepcopy(extra)
        data["prompt"] = prompt
        if size and str(size).lower() in {"1k", "1.5k", "2k", "3k", "4k"}:
            resolution = resolution or str(size).lower()
            size = None
        tier = str(resolution or self.settings.get("default_resolution") or "").lower()
        if tier:
            if tier not in {"1k", "1.5k", "2k", "3k", "4k"}:
                raise ValueError("SpicyAPI resolution 必须使用模型支持的分辨率档位")
            data["resolution"] = tier
        ratio = str(self.settings.get("aspect_ratio") or "").strip()
        if size:
            value = str(size).lower().replace("×", "x")
            if "x" in value:
                try:
                    w, h = map(int, value.split("x"))
                    if min(w, h) <= 0:
                        raise ValueError()
                    supported = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "9:21", "2:1", "1:2", "3:1", "1:3", "5:4", "4:5"]
                    numeric_ratio = lambda value: int(value.split(":")[0]) / int(value.split(":")[1])
                    nearest = min(supported, key=lambda value: abs(numeric_ratio(value) - w / h))
                    if abs(numeric_ratio(nearest) - w / h) / numeric_ratio(nearest) > 0.02:
                        raise ValueError()
                    ratio = nearest
                except ValueError:
                    raise ValueError("SpicyAPI 图片尺寸格式错误") from None
            elif ":" in value:
                ratio = value
            else:
                raise ValueError("SpicyAPI size 需为宽高尺寸或比例；分辨率请使用 resolution")
        if ratio and ratio != "auto":
            data["aspect_ratio"] = ratio
        if images:
            refs = []
            for raw in images:
                with Image.open(io.BytesIO(raw)) as image:
                    image.verify()
                    mime = Image.MIME.get(image.format)
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    raise ValueError("SpicyAPI 参考图仅支持 JPEG、PNG、WebP")
                if len(raw) > 30 * 1024 * 1024:
                    raise ValueError("SpicyAPI 单张参考图不能超过 30 MB")
                refs.append(f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}")
            data["image_urls"] = refs
        return {"model": model, "input": data}

    @staticmethod
    def _record(response):
        if response.status_code not in {200, 202}:
            # Do not echo response bodies: they may contain prompts, keys or inline media.
            raise RuntimeError(f"SpicyAPI HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError("SpicyAPI 返回非 JSON") from None
        if not isinstance(body, dict) or body.get("code") != 200 or not isinstance(body.get("data"), dict):
            code = body.get("code", "invalid") if isinstance(body, dict) else "invalid"
            raise RuntimeError(f"SpicyAPI 业务错误 code={code}")
        return body["data"]

    async def _poll(self, client, task_id, key):
        deadline = time.monotonic() + float(self.settings.get("poll_timeout", 600))
        interval = max(0.1, float(self.settings.get("poll_interval", 3)))
        while time.monotonic() < deadline:
            try:
                response = await client.get(
                    self.base_url + "/api/v1/jobs/recordInfo",
                    params={"taskId": task_id}, headers={"Authorization": f"Bearer {key}"},
                )
                if response.status_code == 429 or response.status_code >= 500:
                    await asyncio.sleep(interval)
                    continue
                record = self._record(response)
            except httpx.TransportError:
                await asyncio.sleep(interval)
                continue
            state = record.get("state")
            if state == "succeeded":
                output = record.get("output") or {}
                assets = output.get("assets", []) if isinstance(output, dict) else []
                if not isinstance(assets, list):
                    raise RuntimeError("SpicyAPI 图片结果格式错误")
                if assets and all(isinstance(asset, dict) and asset.get("unavailable") for asset in assets):
                    raise RuntimeError("SpicyAPI 图片已过期或转存永久失败")
                for asset in assets:
                    if not isinstance(asset, dict) or asset.get("pending") or asset.get("unavailable"):
                        continue
                    url = asset.get("url")
                    if isinstance(url, str) and urlsplit(url).scheme in {"https", "http"} and urlsplit(url).hostname:
                        return url
                # Assets may still be transferring after generation succeeded.
                if record.get("contentState") in {"expired", "purged"}:
                    raise RuntimeError("SpicyAPI 结果已过期或删除")
            elif state not in {"queued", "running"}:
                raise RuntimeError(f"SpicyAPI 任务结束 state={state}, code={record.get('errorCode', 'unknown')}")
            await asyncio.sleep(interval)
        raise TimeoutError("SpicyAPI 本地等待超时，远端任务不会被取消")

    async def resume_image(self, task_id: str, *, api_key: str):
        """Collect an existing task with its original key; never submit a new task."""
        async with self._client() as client:
            url = await self._poll(client, task_id, api_key)
        return await self.imgr.download_image(url)

    async def _run(self, prompt, images, **kwargs) -> Path:
        payload = self._input(prompt, images, size=kwargs.get("size"), resolution=kwargs.get("resolution"))
        if not self.keys:
            raise ValueError("SpicyAPI 未配置 API Key")
        key = self.keys[self._key_index % len(self.keys)]
        self._key_index += 1
        idempotency = str(uuid.uuid4())
        headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": idempotency}
        task_id = ""
        try:
            async with self._client() as client:
                # A transport retry reuses BOTH key and idempotency token; never create a second job.
                for attempt in range(2):
                    try:
                        response = await client.post(self.base_url + "/api/v1/jobs/createTask", headers=headers, json=payload)
                        break
                    except httpx.TransportError:
                        if attempt:
                            raise RuntimeError(f"SpicyAPI 提交结果未知；幂等编号 {idempotency}，请勿直接重复生成") from None
                if response.status_code >= 500:
                    raise RuntimeError(f"SpicyAPI HTTP {response.status_code}；幂等编号 {idempotency}，提交状态需核对后再重试")
                record = self._record(response)
                task_id = str(record.get("taskId") or "").strip()
                if not task_id:
                    raise RuntimeError(f"SpicyAPI 未返回 taskId；幂等编号 {idempotency}，请勿直接重复生成")
                url = await self._poll(client, task_id, key)
            # Result URLs are signed; refresh once through the original task if download fails.
            # No API credentials are ever sent to the asset host.
            try:
                return await self.imgr.download_image(url)
            except Exception:
                async with self._client() as client:
                    url = await self._poll(client, task_id, key)
                return await self.imgr.download_image(url)
        except Exception as exc:
            if task_id:
                raise RuntimeError(f"{exc}（SpicyAPI taskId={task_id}；查询必须使用创建时的同一密钥）") from None
            raise

    async def generate(self, prompt: str, **kwargs) -> Path:
        return await self._run(prompt, [], **kwargs)

    async def edit(self, prompt: str, images: list[bytes], **kwargs) -> Path:
        if not images:
            raise ValueError("SpicyAPI 改图至少需要一张参考图")
        return await self._run(prompt, images, **kwargs)
