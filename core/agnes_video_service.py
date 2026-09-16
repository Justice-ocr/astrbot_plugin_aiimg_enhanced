from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from astrbot.api import logger

from .image_format import guess_image_mime_and_ext


_ASPECT_RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
_DONE_STATUSES = {"completed", "complete", "succeeded", "success", "finished", "done"}
_FAIL_STATUSES = {"failed", "error", "cancelled", "canceled"}
_ASTRBOT_FILE_SERVICE_PATCHED = False


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


def _find_url_in_json(value: Any) -> str | None:
    preferred: list[str] = []
    fallback: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str) and _is_http_url(node):
            lowered = node.lower()
            if any(ext in lowered for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
                preferred.append(node.strip())
            else:
                fallback.append(node.strip())
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return (preferred or fallback or [None])[0]


class AgnesVideoService:
    """Agnes Video 2.5 Flash async video backend."""

    supports_multiple_images = True
    supports_selfie_reference_fallback = True

    def __init__(self, *, settings: dict, data_dir: Path | str | None = None):
        s = settings if isinstance(settings, dict) else {}
        self.data_dir = Path(data_dir or ".")
        self.base_url = str(s.get("base_url") or "https://apihub.agnes-ai.com/v1").rstrip("/")
        self.model = str(s.get("model") or "agnes-video-2.5-flash").strip()

        api_keys = s.get("api_keys") or []
        if isinstance(api_keys, str):
            api_keys = [line.strip() for line in api_keys.splitlines() if line.strip()]
        if not api_keys and s.get("api_key"):
            api_keys = [str(s.get("api_key") or "").strip()]
        self.api_keys = [str(key).strip() for key in api_keys if str(key).strip()]

        self.timeout = _clamp_int(s.get("timeout", 120), 120, 10, 3600)
        self.poll_interval = _clamp_int(s.get("poll_interval", 2), 2, 1, 60)
        self.poll_timeout = _clamp_int(s.get("poll_timeout", 900), 900, 30, 7200)
        self.max_retries = _clamp_int(s.get("max_retries", 1), 1, 0, 10)
        self.seconds = str(s.get("seconds") or "5").strip()
        self.aspect_ratio = str(s.get("aspect_ratio") or "16:9").strip()
        self.image_handling_method = str(s.get("image_handling_method") or "auto").strip().lower()
        self.file_service_base_url = str(
            s.get("file_service_base_url") or s.get("video_file_service_base_url") or ""
        ).strip().rstrip("/")
        self.enable_file_service_magic = bool(s.get("enable_file_service_magic", True))
        self.third_party_upload_url = str(s.get("third_party_upload_url") or "").strip()
        self.third_party_token = str(s.get("third_party_token") or "").strip()
        self.proxy_url = str(s.get("proxy_url") or "").strip() or None

    def _get_key(self) -> str:
        if not self.api_keys:
            raise RuntimeError("未配置 Agnes API Key")
        return self.api_keys[0]

    def _create_url(self) -> str:
        base = self.base_url
        if base.endswith("/videos"):
            return base
        if base.endswith("/v1"):
            return f"{base}/videos"
        return f"{base}/v1/videos"

    def _api_root(self) -> str:
        base = self.base_url
        if base.endswith("/v1/videos"):
            return base[: -len("/v1/videos")]
        if base.endswith("/videos"):
            base = base[: -len("/videos")]
        if base.endswith("/v1"):
            base = base[:-3]
        return base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_key()}",
            "Content-Type": "application/json",
        }

    def _client(self, *, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=timeout, write=30.0, pool=timeout + 15.0),
            follow_redirects=True,
            proxy=self.proxy_url,
        )

    async def _upload_free_public(self, image_bytes: bytes) -> str:
        mime, ext = guess_image_mime_and_ext(image_bytes)
        try:
            async with self._client(timeout=float(self.timeout)) as client:
                response = await client.post(
                    "https://telegra.ph/upload",
                    files={"file": (f"image.{ext}", image_bytes, mime)},
                )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    src = str(data[0].get("src") or "").strip()
                    if src:
                        return f"https://telegra.ph{src}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[AgnesVideo] Telegraph 上传失败，尝试 Catbox: %s", exc)

        async with self._client(timeout=float(self.timeout)) as client:
            response = await client.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (f"image.{ext}", image_bytes, mime)},
            )
        if response.status_code == 200 and _is_http_url(response.text):
            return response.text.strip()
        raise RuntimeError(f"Agnes 参考图公网上传失败: HTTP {response.status_code}")

    async def _upload_third_party(self, image_bytes: bytes) -> str:
        if not self.third_party_upload_url:
            raise RuntimeError("未配置第三方图床上传地址")
        mime, ext = guess_image_mime_and_ext(image_bytes)
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self.third_party_token:
            headers["Authorization"] = f"Bearer {self.third_party_token}"
            if "imgbb" in self.third_party_upload_url.lower():
                params["key"] = self.third_party_token

        async with self._client(timeout=float(self.timeout)) as client:
            response = await client.post(
                self.third_party_upload_url,
                headers=headers,
                params=params,
                files={"image": (f"image.{ext}", image_bytes, mime)},
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"第三方图床上传失败 HTTP {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("第三方图床响应不是 JSON") from exc
        url = _find_url_in_json(data)
        if not url:
            raise RuntimeError("第三方图床响应中未找到图片 URL")
        return url

    def _install_astrbot_file_service_magic(self, file_token_service: Any) -> None:
        global _ASTRBOT_FILE_SERVICE_PATCHED
        if not self.enable_file_service_magic or _ASTRBOT_FILE_SERVICE_PATCHED:
            return
        if getattr(file_token_service, "_aiimg_agnes_magic_patched", False):
            _ASTRBOT_FILE_SERVICE_PATCHED = True
            return
        required = ("handle_file", "lock", "_cleanup_expired_tokens", "staged_files")
        if not all(hasattr(file_token_service, name) for name in required):
            logger.warning("[AgnesVideo] 当前 AstrBot 文件服务不支持可重复访问补丁")
            return

        original_handle_file = file_token_service.handle_file

        async def repeatable_handle_file(file_token: str) -> str:
            async with file_token_service.lock:
                await file_token_service._cleanup_expired_tokens()
                if file_token not in file_token_service.staged_files:
                    raise KeyError(f"无效或过期的文件 token: {file_token}")
                file_path, expire_time = file_token_service.staged_files[file_token]
                if time.time() > expire_time:
                    file_token_service.staged_files.pop(file_token, None)
                    raise KeyError(f"无效或过期的文件 token: {file_token}")
                if not Path(file_path).is_file():
                    file_token_service.staged_files.pop(file_token, None)
                    raise FileNotFoundError(f"文件不存在: {file_path}")
                return file_path

        file_token_service._aiimg_agnes_original_handle_file = original_handle_file
        file_token_service.handle_file = repeatable_handle_file
        file_token_service._aiimg_agnes_magic_patched = True
        _ASTRBOT_FILE_SERVICE_PATCHED = True
        logger.info("[AgnesVideo] 已启用 AstrBot 文件 token 可重复访问")

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

    async def _upload_astrbot_file_service(self, image_bytes: bytes) -> tuple[str, Path]:
        try:
            from astrbot.core import file_token_service
        except Exception as exc:
            raise RuntimeError("当前 AstrBot 不提供文件 token 服务") from exc

        base_url = self._resolve_file_service_base_url()
        self._install_astrbot_file_service_magic(file_token_service)
        _, ext = guess_image_mime_and_ext(image_bytes)
        cache_dir = self.data_dir / "agnes_video_refs"
        await asyncio.to_thread(cache_dir.mkdir, parents=True, exist_ok=True)
        file_path = cache_dir / f"agnes_ref_{uuid.uuid4().hex}.{ext}"
        await asyncio.to_thread(file_path.write_bytes, image_bytes)
        try:
            token = await file_token_service.register_file(str(file_path))
        except Exception:
            file_path.unlink(missing_ok=True)
            raise
        token = str(token or "").strip()
        if not token:
            file_path.unlink(missing_ok=True)
            raise RuntimeError("AstrBot 文件服务未返回有效 token")
        public_url = f"{base_url}/api/file/{token}"
        logger.info("[AgnesVideo] 已生成 AstrBot 文件服务参考图 URL")
        return public_url, file_path

    async def _prepare_reference_urls(
        self,
        image_bytes_list: list[bytes],
        image_urls: list[str],
        temporary_paths: list[Path] | None = None,
    ) -> list[str]:
        refs: list[str] = []
        count = min(max(len(image_bytes_list), len(image_urls)), 5)
        for index in range(count):
            source_url = image_urls[index] if index < len(image_urls) else ""
            if _is_http_url(source_url):
                refs.append(source_url.strip())
                continue

            image_bytes = image_bytes_list[index] if index < len(image_bytes_list) else b""
            if not image_bytes:
                raise RuntimeError(f"Agnes 第 {index + 1} 张参考图缺少可用数据")

            if self.image_handling_method == "astrbot":
                url, file_path = await self._upload_astrbot_file_service(image_bytes)
                refs.append(url)
                if temporary_paths is not None:
                    temporary_paths.append(file_path)
            elif self.image_handling_method == "third_party":
                refs.append(await self._upload_third_party(image_bytes))
            elif self.image_handling_method == "free_public":
                refs.append(await self._upload_free_public(image_bytes))
            elif self.image_handling_method == "auto":
                if self.file_service_base_url:
                    url, file_path = await self._upload_astrbot_file_service(image_bytes)
                    refs.append(url)
                    if temporary_paths is not None:
                        temporary_paths.append(file_path)
                elif self.third_party_upload_url:
                    refs.append(await self._upload_third_party(image_bytes))
                else:
                    refs.append(await self._upload_free_public(image_bytes))
            else:
                raise RuntimeError("Agnes 参考图不是公网 URL，且未启用图床上传")
        return refs

    def _build_payload(self, prompt: str, refs: list[str]) -> dict[str, Any]:
        if self.model != "agnes-video-2.5-flash":
            raise RuntimeError("当前 Agnes 视频模板仅支持 agnes-video-2.5-flash")
        try:
            seconds = int(self.seconds)
        except ValueError as exc:
            raise RuntimeError("Agnes 视频时长必须为 4 到 12 秒") from exc
        if seconds < 4 or seconds > 12:
            raise RuntimeError("Agnes 视频时长必须为 4 到 12 秒")
        if self.aspect_ratio not in _ASPECT_RATIOS:
            raise RuntimeError(f"Agnes 不支持画幅 {self.aspect_ratio}")

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": str(prompt or "").strip(),
            "seconds": str(seconds),
            "mode": "text",
            "size": "720P",
            "aspect_ratio": self.aspect_ratio,
            "n": 1,
        }
        if not payload["prompt"]:
            raise RuntimeError("Agnes 视频提示词不能为空")
        if len(refs) == 1:
            payload["mode"] = "keyframe"
            payload["first_frame"] = refs[0]
        elif refs:
            payload["mode"] = "reference"
            payload["images"] = refs[:5]
        return payload

    async def _submit(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await asyncio.sleep(min(2**attempt, 10))
            try:
                async with self._client(timeout=float(self.timeout)) as client:
                    response = await client.post(
                        self._create_url(), headers=self._headers(), json=payload
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise RuntimeError(
                        f"Agnes 提交任务失败 HTTP {response.status_code}: {response.text[:300]}"
                    )
                data = response.json()
                video_id = str(data.get("video_id") or "").strip()
                task_id = str(data.get("task_id") or data.get("id") or "").strip() or None
                if not video_id:
                    raise RuntimeError(f"Agnes 未返回 video_id: {str(data)[:300]}")
                return video_id, task_id
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
        raise last_error or RuntimeError("Agnes 视频任务提交失败")

    @staticmethod
    def _extract_video_url(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        metadata = data.get("metadata")
        if isinstance(metadata, dict) and _is_http_url(metadata.get("url")):
            return str(metadata["url"]).strip()
        for key in ("url", "video_url", "output_url", "download_url", "file_url"):
            if _is_http_url(data.get(key)):
                return str(data[key]).strip()
        return None

    async def _poll(self, video_id: str) -> str:
        poll_url = (
            f"{self._api_root()}/agnesapi?video_id={quote(video_id, safe='')}"
            f"&model_name={quote(self.model, safe='')}"
        )
        deadline = time.monotonic() + self.poll_timeout
        consecutive_errors = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval)
            try:
                async with self._client(timeout=30.0) as client:
                    response = await client.get(poll_url, headers=self._headers())
                if response.status_code != 200:
                    consecutive_errors += 1
                    if consecutive_errors >= 3:
                        raise RuntimeError(
                            f"Agnes 轮询连续失败 HTTP {response.status_code}: {response.text[:200]}"
                        )
                    continue
                data = response.json()
                consecutive_errors = 0
                status = str(data.get("status") or data.get("state") or "").strip().lower()
                if status in _FAIL_STATUSES:
                    detail = data.get("error") or data.get("message") or data.get("detail") or status
                    raise RuntimeError(f"Agnes 视频生成失败: {detail}")
                video_url = self._extract_video_url(data)
                if video_url:
                    return video_url
                if status in _DONE_STATUSES:
                    raise RuntimeError("Agnes 任务已完成但未返回 metadata.url")
            except asyncio.CancelledError:
                raise
            except RuntimeError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("[AgnesVideo] 轮询异常: %s", exc)
                if consecutive_errors >= 3:
                    raise RuntimeError(f"Agnes 视频任务连续轮询异常: {exc}") from exc

        raise RuntimeError(f"Agnes 视频轮询超时（{self.poll_timeout}s），video_id={video_id}")

    async def generate_video_url(
        self,
        prompt: str,
        image_bytes: bytes | None = None,
        *,
        image_bytes_list: list[bytes] | None = None,
        image_urls: list[str] | None = None,
        preset: str | None = None,
    ) -> str:
        del preset
        byte_items = list(image_bytes_list or ([] if image_bytes is None else [image_bytes]))
        url_items = list(image_urls or [])
        temporary_paths: list[Path] = []
        try:
            refs = await self._prepare_reference_urls(
                byte_items, url_items, temporary_paths=temporary_paths
            )
            payload = self._build_payload(prompt, refs)
            video_id, task_id = await self._submit(payload)
            logger.info("[AgnesVideo] 任务已提交: video_id=%s task_id=%s", video_id, task_id or "")
            return await self._poll(video_id)
        finally:
            for path in temporary_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("[AgnesVideo] 清理临时参考图失败: %s", exc)
