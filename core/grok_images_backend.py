from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from typing import Any

import aiohttp

from astrbot.api import logger

from .gitee_sizes import size_to_ratio
from .image_format import guess_image_mime_and_ext

_IMAGE_RESPONSE_FORMAT_CANDIDATES = ("b64_json", "url", None)
_RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_BASE64_PREFIX_RE = re.compile(r"^(?:b64|base64)\s*:\s*", re.IGNORECASE)
_PIXEL_SIZE_RE = re.compile(r"^(\d{2,5})x(\d{2,5})$", re.IGNORECASE)
_XAI_ASPECT_RATIOS = {
    "1:1",
    "3:4",
    "4:3",
    "9:16",
    "16:9",
    "2:3",
    "3:2",
    "9:19.5",
    "19.5:9",
    "9:20",
    "20:9",
    "1:2",
    "2:1",
    "auto",
}
_LEGACY_MODEL_ALIASES = {
    "grok-imagine-1.0": "grok-imagine-image-quality",
    "grok-imagine-1.0-edit": "grok-imagine-image-quality",
}


def _normalize_base_url(base_url: str) -> str:
    url = str(base_url or "").strip().rstrip("/")
    for suffix in (
        "/v1/images/generations",
        "/v1/images/edits",
        "/images/generations",
        "/images/edits",
        "/v1",
    ):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _pick_first_api_key(api_keys: list[str]) -> str:
    keys = [str(k).strip() for k in (api_keys or []) if str(k).strip()]
    if not keys:
        raise RuntimeError("未配置 API Key")
    return keys[0]


def _decode_base64_bytes(text: str) -> bytes:
    s = re.sub(r"\s+", "", str(text or "").strip())
    if not s:
        return b""
    candidates = [s, s.replace("-", "+").replace("_", "/")]
    for cand in candidates:
        pad = "=" * ((4 - len(cand) % 4) % 4)
        try:
            raw = base64.b64decode(cand + pad, validate=False)
            if raw:
                return raw
        except Exception:
            continue
    return b""


def _iter_strings(obj: object) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()

    def walk(value: object) -> None:
        if value is None:
            return
        oid = id(value)
        if oid in seen:
            return
        seen.add(oid)
        if isinstance(value, str):
            out.append(value)
            return
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    walk(obj)
    return out


def _extract_ref_from_string(text: str) -> tuple[str | None, bytes | None]:
    s = (text or "").strip().strip('"').strip("'")
    if not s:
        return None, None
    if s.startswith("data:image/") and "," in s:
        _header, b64_data = s.split(",", 1)
        raw = _decode_base64_bytes(b64_data)
        return (None, raw) if raw else (None, None)
    if s.startswith(("http://", "https://")):
        return s, None
    normalized = _BASE64_PREFIX_RE.sub("", s)
    if len(normalized) >= 128:
        raw = _decode_base64_bytes(normalized)
        if raw:
            return None, raw
    return None, None


def _parse_sse_or_json(raw: bytes) -> Any:
    """自动检测并解析 SSE 或普通 JSON 响应。

    SSE 格式（text/event-stream）：每行 "data: {...}"，取最后一个含图片的事件。
    普通 JSON：直接解析。
    """
    text = raw.decode("utf-8", errors="replace").strip()

    # 检测是否是 SSE（含 "data:" 前缀的行）
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    has_sse = any(l.startswith("data:") for l in lines)

    if not has_sse:
        return json.loads(text)

    # SSE：收集所有 data: 事件
    events = []
    for line in lines:
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str in ("[DONE]", ""):
            continue
        try:
            events.append(json.loads(data_str))
        except json.JSONDecodeError:
            pass

    if not events:
        raise json.JSONDecodeError("SSE 无有效事件", text, 0)

    # 优先返回含图片数据的事件（data[]、url、b64_json）
    for evt in reversed(events):
        if not isinstance(evt, dict):
            continue
        if evt.get("data") or evt.get("url") or evt.get("b64_json"):
            return evt
    # fallback：返回最后一个事件
    return events[-1]


def _parse_image_api_response(data: Any) -> list[tuple[str | None, bytes | None]]:
    results: list[tuple[str | None, bytes | None]] = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        for item in data["data"]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url.strip():
                results.append((url.strip(), None))
                continue
            b64_json = item.get("b64_json")
            if isinstance(b64_json, str) and b64_json.strip():
                raw = _decode_base64_bytes(b64_json)
                if raw:
                    results.append((None, raw))

    if results:
        return results

    for text in _iter_strings(data):
        url, raw = _extract_ref_from_string(text)
        if url or raw:
            results.append((url, raw))
            break
    return results


def _extract_api_error_message(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if not isinstance(data, dict):
        return text[:500]
    error_obj = data.get("error")
    if isinstance(error_obj, dict):
        message = str(error_obj.get("message") or "").strip()
        code = str(error_obj.get("code") or "").strip()
        param = str(error_obj.get("param") or "").strip()
        parts = [
            x
            for x in (
                message,
                f"code={code}" if code and code not in message else "",
                f"param={param}" if param and param not in message else "",
            )
            if x
        ]
        if parts:
            return " | ".join(parts)
    if isinstance(error_obj, str) and error_obj.strip():
        return error_obj.strip()
    for key in ("message", "detail", "error_description"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return text[:500]


def _is_response_format_related_error(error_message: str) -> bool:
    err = str(error_message or "").lower()
    if not err:
        return False
    if "response_format" in err:
        return True
    return "format" in err and (
        "invalid" in err or "unsupported" in err or "must be" in err
    )


def _normalize_resolution(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"1k", "1024"}:
        return "1k"
    if raw in {"2k", "2048", "4k", "4096"}:
        return "2k"
    return None


def _normalize_model_name(value: str | None) -> str:
    raw = str(value or "").strip()
    return _LEGACY_MODEL_ALIASES.get(raw.lower(), raw)


def _pixel_size_resolution(value: str | None) -> str | None:
    match = _PIXEL_SIZE_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    longest_edge = max(int(match.group(1)), int(match.group(2)))
    return "1k" if longest_edge <= 1024 else "2k"


def _resolve_xai_output_params(
    *,
    size: str | None,
    resolution: str | None,
    default_size: str | None,
) -> dict[str, str]:
    raw_size = str(size or "").strip()
    raw_resolution = str(resolution or "").strip()
    fallback_size = str(default_size or "").strip()
    explicit_output = raw_size or raw_resolution
    pixel_source = next(
        (
            value
            for value in (raw_size, raw_resolution)
            if _PIXEL_SIZE_RE.fullmatch(value)
        ),
        "",
    )
    if not explicit_output and _PIXEL_SIZE_RE.fullmatch(fallback_size):
        pixel_source = fallback_size

    params: dict[str, str] = {}
    aspect_ratio = size_to_ratio(pixel_source) if pixel_source else None
    if aspect_ratio in _XAI_ASPECT_RATIOS:
        params["aspect_ratio"] = aspect_ratio

    final_resolution = (
        _normalize_resolution(raw_resolution)
        or _normalize_resolution(raw_size)
        or _pixel_size_resolution(pixel_source)
    )
    if final_resolution:
        params["resolution"] = final_resolution
    return params


def _image_data_uri(image: bytes) -> str:
    mime, _ext = guess_image_mime_and_ext(image)
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _merge_extra_payload(
    payload: dict[str, Any],
    *sources: dict | None,
    protected: set[str] | None = None,
) -> dict[str, Any]:
    blocked = protected or set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if str(key) not in blocked:
                payload[str(key)] = value
    return payload


class GrokImagesBackend:
    def __init__(
        self,
        *,
        imgr,
        base_url: str,
        api_keys: list[str],
        timeout: int = 120,
        max_retries: int = 2,
        default_model: str = "",
        default_size: str = "2048x2048",
        supports_edit: bool = True,
        extra_body: dict | None = None,
        proxy_url: str | None = None,
    ):
        self.imgr = imgr
        self.base_url = _normalize_base_url(base_url)
        self.api_key = _pick_first_api_key(api_keys)
        self.timeout = max(1, min(int(timeout) if timeout is not None else 120, 3600))
        self.max_retries = max(0, min(int(max_retries) if max_retries is not None else 2, 10))
        self.default_model = _normalize_model_name(default_model)
        self.default_size = str(default_size or "2048x2048").strip()
        self.supports_edit = bool(supports_edit)
        self.extra_body = extra_body or {}
        self.proxy_url = str(proxy_url or "").strip() or None
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        async with self._session_lock:
            if self._session and not self._session.closed:
                return self._session
            self._session = aiohttp.ClientSession()
            return self._session

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _retry_delay_seconds(attempt_index: int) -> float:
        return min(1.5 * (2**attempt_index), 4.0)

    async def _save_first_result(
        self, results: list[tuple[str | None, bytes | None]]
    ) -> Path:
        if not results:
            raise RuntimeError("未能从响应中提取图片")
        ref, raw = results[0]
        if raw:
            return await self.imgr.save_image(raw)
        if ref:
            return await self.imgr.download_image(ref)
        raise RuntimeError("返回数据不包含图片")

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        size: str | None = None,
        resolution: str | None = None,
        extra_body: dict | None = None,
    ) -> Path:
        if not self.base_url:
            raise RuntimeError("未配置 base_url")

        final_model = _normalize_model_name(
            model or self.default_model or "grok-imagine-image-quality"
        )
        output_params = _resolve_xai_output_params(
            size=size,
            resolution=resolution,
            default_size=self.default_size,
        )
        api_url = f"{self.base_url}/v1/images/generations"
        session = await self._ensure_session()
        last_error = ""

        for response_format in _IMAGE_RESPONSE_FORMAT_CANDIDATES:
            payload: dict[str, Any] = {
                "model": final_model,
                "prompt": (prompt or "").strip() or "a high quality image",
                "n": 1,
                **output_params,
            }
            if response_format:
                payload["response_format"] = response_format
            _merge_extra_payload(
                payload,
                self.extra_body,
                extra_body,
                protected={"model", "prompt", "n", "response_format", "size"},
            )

            for attempt in range(self.max_retries + 1):
                try:
                    t0 = time.perf_counter()
                    async with session.post(
                        api_url,
                        headers={**self._headers(), "Content-Type": "application/json"},
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                        proxy=self.proxy_url,
                    ) as resp:
                        raw_content = await resp.read()
                    if resp.status != 200:
                        text = raw_content.decode("utf-8", errors="replace")
                        detail = _extract_api_error_message(text)
                        last_error = detail or f"HTTP {resp.status}"
                        if response_format and _is_response_format_related_error(
                            detail
                        ):
                            logger.warning(
                                "[GrokImages][generate] response_format=%s rejected: %s",
                                response_format,
                                detail[:160],
                            )
                            break
                        if (
                            resp.status in _RETRYABLE_HTTP_STATUS_CODES
                            and attempt < self.max_retries
                        ):
                            await asyncio.sleep(self._retry_delay_seconds(attempt))
                            continue
                        raise RuntimeError(last_error)
                    data = _parse_sse_or_json(raw_content)
                    results = _parse_image_api_response(data)
                    if results:
                        logger.info(
                            "[GrokImages][generate] success in %.2fs format=%s",
                            time.perf_counter() - t0,
                            response_format or "default",
                        )
                        return await self._save_first_result(results)
                    last_error = "未能从响应中提取图片"
                    raise RuntimeError(last_error)
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    last_error = str(e) or "请求超时"
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue
                except json.JSONDecodeError:
                    last_error = "API 响应格式异常（非 JSON/SSE）"
                except Exception as e:
                    last_error = str(e)
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue
                    if response_format and _is_response_format_related_error(
                        last_error
                    ):
                        break
                    raise

        raise RuntimeError(last_error or "Grok 文生图请求失败")

    async def edit(
        self,
        prompt: str,
        images: list[bytes],
        *,
        model: str | None = None,
        size: str | None = None,
        resolution: str | None = None,
        extra_body: dict | None = None,
    ) -> Path:
        if not self.supports_edit:
            raise RuntimeError("该后端不支持改图/图生图")
        if not images:
            raise ValueError("至少需要一张图片")
        if len(images) > 3:
            raise ValueError("xAI Grok 改图最多支持三张输入图片")
        if not self.base_url:
            raise RuntimeError("未配置 base_url")

        final_model = _normalize_model_name(
            model or self.default_model or "grok-imagine-image-quality"
        )
        output_params = _resolve_xai_output_params(
            size=size,
            resolution=resolution,
            default_size=self.default_size,
        )
        api_url = f"{self.base_url}/v1/images/edits"
        session = await self._ensure_session()
        last_error = ""

        image_inputs = [{"url": _image_data_uri(image)} for image in images]
        for response_format in _IMAGE_RESPONSE_FORMAT_CANDIDATES:
            payload: dict[str, Any] = {
                "model": final_model,
                "prompt": (prompt or "").strip() or "Edit this image",
                "n": 1,
                "resolution": output_params.get("resolution", "2k"),
            }
            if len(image_inputs) == 1:
                payload["image"] = image_inputs[0]
            else:
                payload["images"] = image_inputs
                if output_params.get("aspect_ratio"):
                    payload["aspect_ratio"] = output_params["aspect_ratio"]
            if response_format:
                payload["response_format"] = response_format
            _merge_extra_payload(
                payload,
                self.extra_body,
                extra_body,
                protected={
                    "model",
                    "prompt",
                    "n",
                    "response_format",
                    "size",
                    "image",
                    "images",
                },
            )

            for attempt in range(self.max_retries + 1):
                try:
                    t0 = time.perf_counter()
                    async with session.post(
                        api_url,
                        headers={**self._headers(), "Content-Type": "application/json"},
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout),
                        proxy=self.proxy_url,
                    ) as resp:
                        raw_content = await resp.read()
                    if resp.status != 200:
                        text = raw_content.decode("utf-8", errors="replace")
                        detail = _extract_api_error_message(text)
                        last_error = detail or f"HTTP {resp.status}"
                        if response_format and _is_response_format_related_error(detail):
                            logger.warning(
                                "[GrokImages][edit] response_format=%s rejected: %s",
                                response_format,
                                detail[:160],
                            )
                            break
                        if (
                            resp.status in _RETRYABLE_HTTP_STATUS_CODES
                            and attempt < self.max_retries
                        ):
                            await asyncio.sleep(self._retry_delay_seconds(attempt))
                            continue
                        raise RuntimeError(last_error)
                    data = _parse_sse_or_json(raw_content)
                    results = _parse_image_api_response(data)
                    if results:
                        logger.info(
                            "[GrokImages][edit] success in %.2fs images=%s format=%s",
                            time.perf_counter() - t0,
                            len(image_inputs),
                            response_format or "default",
                        )
                        return await self._save_first_result(results)
                    last_error = "未能从响应中提取图片"
                    raise RuntimeError(last_error)
                except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                    last_error = str(e) or "请求超时"
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue
                except json.JSONDecodeError:
                    last_error = "API 响应格式异常（非 JSON/SSE）"
                except Exception as e:
                    last_error = str(e)
                    if attempt < self.max_retries:
                        await asyncio.sleep(self._retry_delay_seconds(attempt))
                        continue
                    if response_format and _is_response_format_related_error(last_error):
                        break
                    raise

        raise RuntimeError(last_error or "Grok 改图请求失败")
