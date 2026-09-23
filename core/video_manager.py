"""
视频缓存管理器

用于在需要以本地文件方式发送时，下载 Grok 返回的视频并进行简单清理。

注意：部分后端可能返回的是一个页面 URL（text/html），页面里再包含真正的 mp4 链接。
本管理器会在下载前尝试把 HTML/JSON 解析成“直链 mp4”，避免最终发送的只是一个网页链接。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import aiofiles
import httpx

from astrbot.api import logger
from .media_leases import (
    acquire_media,
    hold_media,
    media_is_active,
    release_media,
)
from .task_manager import update_task_state

from .net_safety import URLFetchPolicy, collect_trusted_origins, ensure_url_allowed, read_network_policy


def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        value_int = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value_int))


class VideoManager:
    def __init__(self, config: dict, data_dir: Path):
        self.config = config
        storage = config.get("storage", {}) if isinstance(config, dict) else {}

        self.video_dir = data_dir / "videos"
        self.video_dir.mkdir(parents=True, exist_ok=True)

        net = read_network_policy(config)
        self._media_allow_private: bool = bool(net.get("media_allow_private", False))
        self._media_max_video_bytes: int = _clamp_int(
            net.get("max_video_bytes", 50 * 1024 * 1024),
            default=50 * 1024 * 1024,
            min_value=5 * 1024 * 1024,
            max_value=5 * 1024 * 1024 * 1024,
        )
        self._media_max_redirects: int = _clamp_int(
            net.get("max_redirects", 5), default=5, min_value=0, max_value=10
        )
        self._dns_timeout_seconds: int = _clamp_int(
            net.get("dns_resolve_timeout_seconds", 2),
            default=2,
            min_value=1,
            max_value=10,
        )
        self._trusted_origins: frozenset[str] = frozenset(collect_trusted_origins(config))

        self.max_cached_videos: int = _clamp_int(
            (storage.get("max_cached_videos") if isinstance(storage, dict) else None)
            or config.get("max_cached_videos", 20),
            default=20,
            min_value=0,
            max_value=500,
        )
        self.cleanup_batch_ratio = 0.5

    @staticmethod
    def _wrapper_video_url(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("url", "video_url", "download_url"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        items = data.get("data")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return str(items[0].get("url") or "").strip()
        return ""

    async def _resolve_video_url(
        self,
        url: str,
        *,
        timeout: httpx.Timeout,
        policy: URLFetchPolicy,
    ) -> str:
        """Resolve a possibly indirect URL into a direct mp4 URL.

        Some providers return an HTML page or JSON wrapper that contains the real mp4 link.
        """
        u = str(url or "").strip()
        if not u:
            return ""
        if u.lower().endswith(".mp4"):
            return u

        current = u
        redirects = 0
        preview_limit = 512 * 1024
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            while True:
                await ensure_url_allowed(current, policy=policy)
                try:
                    async with client.stream(
                        "GET",
                        current,
                        headers={"Accept": "text/html,application/json,video/*"},
                    ) as resp:
                        if resp.status_code in {301, 302, 303, 307, 308}:
                            if redirects >= self._media_max_redirects:
                                raise RuntimeError("Too many redirects")
                            location = (resp.headers.get("location") or "").strip()
                            if not location:
                                raise RuntimeError("Redirect without location")
                            current = str(httpx.URL(current).join(location))
                            redirects += 1
                            continue

                        resp.raise_for_status()
                        content_type = (
                            resp.headers.get("content-type") or ""
                        ).lower()
                        if content_type.startswith("video/"):
                            return current

                        body = bytearray()
                        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            remaining = preview_limit - len(body)
                            if remaining <= 0:
                                break
                            body.extend(chunk[:remaining])
                            if len(body) >= preview_limit:
                                break
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    logger.debug(
                        "[VideoManager] 视频包装页解析失败，按原 URL 下载: %s",
                        exc,
                    )
                    return u
                break

        text = bytes(body).decode("utf-8", errors="replace")
        if "application/json" in content_type:
            try:
                candidate = self._wrapper_video_url(json.loads(text))
                if candidate:
                    return str(httpx.URL(current).join(candidate))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        if "text/html" in content_type or text.lstrip().lower().startswith("<!doctype"):
            match = re.search(r"https?://[^\s\"']+?\.mp4(?:\?[^\s\"']*)?", text)
            if match:
                return match.group(0)

        return u

    @contextmanager
    def hold_video(self, path: Path):
        with hold_media(path) as resolved:
            yield resolved

    async def download_video(self, url: str, *, timeout_seconds: int = 300) -> Path:
        update_task_state("downloading")
        if not url:
            raise ValueError("缺少视频 URL")

        timeout_seconds = max(1, min(int(timeout_seconds), 3600))
        filename = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"
        path = self.video_dir / filename
        tmp_path = self.video_dir / f"{filename}.part"

        timeout = httpx.Timeout(
            connect=10.0,
            read=float(timeout_seconds),
            write=10.0,
            pool=float(timeout_seconds) + 10.0,
        )

        policy = URLFetchPolicy(
            allow_private=self._media_allow_private,
            trusted_origins=self._trusted_origins,
            allowed_hosts=frozenset(),
            dns_timeout_seconds=float(self._dns_timeout_seconds),
        )

        active_paths = {path.resolve(), tmp_path.resolve()}
        for active_path in active_paths:
            acquire_media(active_path)
        t0 = time.perf_counter()
        try:
            current = await self._resolve_video_url(
                str(url or "").strip(),
                timeout=timeout,
                policy=policy,
            )
            redirects = 0
            while True:
                await ensure_url_allowed(current, policy=policy)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    async with client.stream("GET", current) as resp:
                        if resp.status_code in {301, 302, 303, 307, 308}:
                            if redirects >= self._media_max_redirects:
                                raise RuntimeError("Too many redirects")
                            loc = (resp.headers.get("location") or "").strip()
                            if not loc:
                                raise RuntimeError("Redirect without location")
                            current = str(httpx.URL(current).join(loc))
                            redirects += 1
                            continue

                        resp.raise_for_status()

                        total = 0
                        async with aiofiles.open(tmp_path, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                                if not chunk:
                                    continue
                                total += len(chunk)
                                if total > self._media_max_video_bytes:
                                    raise RuntimeError("Video too large")
                                await f.write(chunk)

                break
        except Exception:
            try:
                if tmp_path.exists():
                    await asyncio.to_thread(tmp_path.unlink)
            except Exception:
                pass
            raise
        else:
            try:
                await asyncio.to_thread(tmp_path.replace, path)
            except Exception:
                await asyncio.to_thread(tmp_path.rename, path)

            logger.info(
                f"[VideoManager] 下载完成: path={path}, 耗时={time.perf_counter() - t0:.2f}s"
            )

            await self.cleanup_old_videos()
            return path
        finally:
            for active_path in active_paths:
                release_media(active_path)

    async def cleanup_old_videos(self) -> None:
        if self.max_cached_videos <= 0:
            return

        try:
            all_videos = [
                path
                for path in self.video_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() == ".mp4"
            ]
            total = len(all_videos)
            if total <= self.max_cached_videos:
                return

            videos = [
                path
                for path in all_videos
                if not media_is_active(path)
            ]
            overflow = total - self.max_cached_videos
            delete_count = min(len(videos), overflow)
            if delete_count <= 0:
                return

            stats = await asyncio.gather(
                *[asyncio.to_thread(p.stat) for p in videos],
                return_exceptions=True,
            )

            valid: list[tuple[Path, float]] = []
            for p, st in zip(videos, stats):
                if isinstance(st, os.stat_result):
                    valid.append((p, st.st_mtime))

            valid.sort(key=lambda x: x[1])  # old -> new
            to_delete = valid[:delete_count]

            await asyncio.gather(
                *[asyncio.to_thread(p.unlink) for p, _ in to_delete],
                return_exceptions=True,
            )

            logger.debug(
                f"[VideoManager] 清理旧视频: 删除={len(to_delete)}, 当前={total - len(to_delete)}"
            )

        except Exception as e:
            logger.warning(f"[VideoManager] 清理旧视频失败: {e}")
