"""通用自定义视频生成后端。

支持：
- 自定义 base_url + endpoint（如 /v1/chat/completions、/v1/videos 等）
- JSON 直接返回模式（同步，返回视频 URL）
- 轮询模式（异步任务，提交后轮询状态直到完成）
- 自定义请求字段（通过 extra_body 覆盖）
- 自定义响应解析路径（通过 response_url_path 指定）
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from astrbot.api import logger
from .image_format import guess_image_mime_and_ext


def _clamp_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


def _deep_get(obj: Any, path: str) -> Any:
    """按 'a.b[0].c' 格式从嵌套结构里取值。"""
    for part in re.split(r"[\.\[\]]", path):
        if not part:
            continue
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, (list, tuple)):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return obj


def _extract_video_url(data: Any, url_path: str | None) -> str | None:
    """从响应里提取视频 URL。

    先按 url_path 指定的路径查找，再尝试常见字段名。
    """
    if url_path:
        val = _deep_get(data, url_path)
        if isinstance(val, str) and val.strip().startswith("http"):
            return val.strip()

    # 常见响应格式兜底
    if not isinstance(data, dict):
        return None

    # {url: "..."} / {video_url: "..."} / {data: [{url: "..."}]}
    for key in ("url", "video_url", "video", "output", "result"):
        val = data.get(key)
        if isinstance(val, str) and val.strip().startswith("http"):
            return val.strip()

    if isinstance(data.get("data"), list) and data["data"]:
        first = data["data"][0]
        if isinstance(first, dict):
            for key in ("url", "video_url", "video"):
                val = first.get(key)
                if isinstance(val, str) and val.strip().startswith("http"):
                    return val.strip()
        elif isinstance(first, str) and first.startswith("http"):
            return first

    # choices[0].message.content 里找 URL（chat completions 格式）
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        content = None
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            content = msg.get("content")
        if isinstance(content, str):
            urls = re.findall(r'https?://\S+\.mp4\S*', content)
            if urls:
                return urls[0].rstrip(")")
            urls = re.findall(r'https?://\S+', content)
            for u in urls:
                u = u.rstrip(")")
                if any(ext in u.lower() for ext in (".mp4", ".mov", ".webm", "video", "videos")):
                    return u

    return None


def _extract_task_id(data: Any, task_id_path: str | None) -> str | None:
    if task_id_path:
        val = _deep_get(data, task_id_path)
        if val is not None:
            return str(val)
    if not isinstance(data, dict):
        return None
    for key in ("task_id", "id", "job_id", "request_id"):
        val = data.get(key)
        if val is not None:
            return str(val)
    return None


def _extract_status(data: Any, status_path: str | None) -> str | None:
    if status_path:
        val = _deep_get(data, status_path)
        if val is not None:
            return str(val).lower()
    if not isinstance(data, dict):
        return None
    for key in ("status", "state", "task_status"):
        val = data.get(key)
        if val is not None:
            return str(val).lower()
    return None


class CustomVideoBackend:
    """通用自定义视频生成后端。

    配置字段：
        base_url          服务商根地址，如 https://api.ccode.vip
        generate_path     生成接口路径，默认 /v1/chat/completions
        poll_path         轮询接口路径（为空则不轮询），如 /v1/tasks/{task_id}
        api_keys          API Key 池（列表）
        model             模型名称
        timeout           单次请求超时（秒），默认 300
        max_retries       最大重试次数，默认 0
        poll_interval     轮询间隔（秒），默认 5
        poll_timeout      轮询总超时（秒），默认 300
        response_url_path 响应里视频 URL 的 JSON 路径，如 data.0.url
        task_id_path      异步任务 ID 的 JSON 路径，如 task_id
        status_path       轮询状态字段路径，如 status
        done_statuses     完成状态值（逗号分隔），默认 succeeded,completed,done,finished
        fail_statuses     失败状态值（逗号分隔），默认 failed,error,cancelled
        extra_body        额外请求体字段（JSON 对象）
        request_mode      请求格式，auto/json/multipart，默认 auto
        image_field       图片字段名（multipart 时），默认 image
    """

    def __init__(self, *, settings: dict):
        s = settings if isinstance(settings, dict) else {}

        base = str(s.get("base_url") or "").rstrip("/")
        gen_path = str(s.get("generate_path") or "/v1/chat/completions").strip()
        if not gen_path.startswith("/"):
            gen_path = "/" + gen_path
        self.generate_url = base + gen_path

        poll_path = str(s.get("poll_path") or "").strip()
        self.poll_path = poll_path  # 含 {task_id} 占位符

        api_keys = s.get("api_keys") or []
        if isinstance(api_keys, str):
            api_keys = [k.strip() for k in api_keys.splitlines() if k.strip()]
        if not api_keys and s.get("api_key"):
            api_keys = [str(s["api_key"]).strip()]
        self.api_keys: list[str] = [str(k).strip() for k in api_keys if str(k).strip()]

        self.model = str(s.get("model") or "").strip()
        self.timeout = _clamp_int(s.get("timeout", 300), 300, 1, 3600)
        self.max_retries = _clamp_int(s.get("max_retries", 0), 0, 0, 10)
        self.poll_interval = _clamp_int(s.get("poll_interval", 5), 5, 1, 60)
        self.poll_timeout = _clamp_int(s.get("poll_timeout", 300), 300, 10, 7200)

        self.response_url_path: str | None = str(s.get("response_url_path") or "").strip() or None
        self.task_id_path: str | None = str(s.get("task_id_path") or "").strip() or None
        self.status_path: str | None = str(s.get("status_path") or "").strip() or None

        done_raw = str(s.get("done_statuses") or "succeeded,completed,done,finished,success")
        self.done_statuses = {v.strip().lower() for v in done_raw.split(",") if v.strip()}
        fail_raw = str(s.get("fail_statuses") or "failed,error,cancelled,canceled")
        self.fail_statuses = {v.strip().lower() for v in fail_raw.split(",") if v.strip()}

        extra = s.get("extra_body")
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        self.extra_body: dict = extra if isinstance(extra, dict) else {}

        self.request_mode = str(s.get("request_mode") or "auto").strip().lower()
        self.image_field = str(s.get("image_field") or "image").strip() or "image"

        # proxy
        proxy = str(s.get("proxy_url") or "").strip()
        self.proxy_url: str | None = proxy or None

    def _get_key(self) -> str:
        if not self.api_keys:
            raise RuntimeError("未配置 API Key")
        return self.api_keys[0]

    def _make_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=15.0,
            read=float(self.timeout),
            write=30.0,
            pool=float(self.timeout) + 15.0,
        )

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Authorization": f"Bearer {self._get_key()}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _build_json_payload(self, prompt: str) -> dict:
        payload: dict[str, Any] = {}
        if self.model:
            payload["model"] = self.model
        # 同时放 prompt 和 messages，服务商取自己支持的
        payload["prompt"] = prompt
        payload["messages"] = [{"role": "user", "content": prompt}]
        payload.update(self.extra_body)
        return payload

    async def _post_generate(
        self,
        prompt: str,
        image_bytes: bytes | None,
        client: httpx.AsyncClient,
    ) -> Any:
        use_multipart = (
            self.request_mode == "multipart"
            or (self.request_mode == "auto" and image_bytes is not None)
        )

        if use_multipart and image_bytes:
            mime, ext = guess_image_mime_and_ext(image_bytes)
            files = {self.image_field: (f"image.{ext}", image_bytes, mime)}
            data: dict[str, Any] = {"prompt": prompt}
            if self.model:
                data["model"] = self.model
            for k, v in self.extra_body.items():
                data[k] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            resp = await client.post(
                self.generate_url,
                headers=self._headers(),
                data=data,
                files=files,
            )
        else:
            payload = self._build_json_payload(prompt)
            resp = await client.post(
                self.generate_url,
                headers=self._headers("application/json"),
                json=payload,
            )

        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except Exception:
            raise RuntimeError(f"响应 JSON 解析失败: {resp.text[:200]}")

    async def _poll_for_url(self, task_id: str, client: httpx.AsyncClient) -> str:
        if not self.poll_path:
            raise RuntimeError("未配置 poll_path，无法轮询任务状态")

        poll_url = (
            self.generate_url.rsplit("/", 1)[0].rstrip("/")
            + "/"
            + self.poll_path.lstrip("/").replace("{task_id}", task_id)
        )
        # 如果 poll_path 是绝对路径（含 http），直接用
        if self.poll_path.startswith("http"):
            poll_url = self.poll_path.replace("{task_id}", task_id)

        t0 = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - t0
            if elapsed > self.poll_timeout:
                raise RuntimeError(f"轮询超时（{self.poll_timeout}s），task_id={task_id}")

            await asyncio.sleep(self.poll_interval)

            resp = await client.get(
                poll_url,
                headers=self._headers(),
            )
            if resp.status_code != 200:
                logger.warning("[CustomVideo] 轮询失败 HTTP %s，继续等待", resp.status_code)
                continue

            try:
                data = resp.json()
            except Exception:
                continue

            status = _extract_status(data, self.status_path)
            logger.debug("[CustomVideo] 轮询 task=%s status=%s elapsed=%.1fs", task_id, status, elapsed)

            if status in self.fail_statuses:
                raise RuntimeError(f"视频生成任务失败，status={status}")

            # 先尝试从轮询响应里提取 URL
            url = _extract_video_url(data, self.response_url_path)
            if url:
                return url

            if status in self.done_statuses:
                raise RuntimeError(f"任务完成但未找到视频 URL，响应: {str(data)[:200]}")

            # 继续轮询

    async def generate_video_url(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        *,
        preset: str | None = None,
    ) -> str:
        t0 = time.perf_counter()
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = min(3.0 * attempt, 10.0)
                logger.info("[CustomVideo] 第 %s/%s 次重试，%.1fs 后", attempt, self.max_retries, delay)
                await asyncio.sleep(delay)

            try:
                async with httpx.AsyncClient(
                    timeout=self._make_timeout(),
                    follow_redirects=True,
                    proxies=self.proxy_url,
                ) as client:
                    data = await self._post_generate(prompt, image_bytes, client)
                    logger.debug("[CustomVideo] 提交响应: %s", str(data)[:200])

                    # 直接返回型：响应里有 URL
                    url = _extract_video_url(data, self.response_url_path)
                    if url:
                        logger.info("[CustomVideo] 同步返回 URL，耗时=%.2fs", time.perf_counter() - t0)
                        return url

                    # 异步轮询型：响应里有 task_id
                    if self.poll_path:
                        task_id = _extract_task_id(data, self.task_id_path)
                        if task_id:
                            logger.info("[CustomVideo] 获取 task_id=%s，开始轮询", task_id)
                            url = await self._poll_for_url(task_id, client)
                            logger.info("[CustomVideo] 轮询完成 URL，耗时=%.2fs", time.perf_counter() - t0)
                            return url

                    raise RuntimeError(f"响应中未找到视频 URL 或 task_id，响应: {str(data)[:300]}")

            except Exception as e:
                last_exc = e
                logger.warning("[CustomVideo] attempt=%s/%s 失败: %s", attempt + 1, self.max_retries + 1, e)

        raise last_exc or RuntimeError("视频生成失败")
