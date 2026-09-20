from __future__ import annotations

import json
from pathlib import Path

import httpx

from .openai_full_url_backend import OpenAIFullURLBackend


class NaiGatewayBackend(OpenAIFullURLBackend):
    """NAI tag-based GET gateway, not the native NovelAI API."""

    def __init__(self, *, imgr, settings: dict):
        self.settings = dict(settings)
        base = str(settings.get("base_url") or "").strip().rstrip("/")
        path = str(settings.get("generate_path") or "/generate").strip()
        super().__init__(
            imgr=imgr,
            full_generate_url=base + "/" + path.lstrip("/"),
            api_keys=settings.get("api_keys") or [],
            default_model=settings.get("model") or "nai-diffusion-4-5-full",
            default_size=settings.get("default_size") or "832x1216",
            timeout=int(settings.get("timeout") or 120),
            max_retries=0,
            supports_edit=False,
        )
        self.auth_mode = settings.get("nai_auth_mode") or "token"
        if self.auth_mode not in {"token", "bearer"}:
            raise ValueError("NAI 鉴权方式必须为 token 或 bearer")

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                proxy=self.settings.get("proxy_url") or None,
                follow_redirects=False,
            )
        return self._client

    async def generate(
        self, prompt: str, *, model: str | None = None,
        size: str | None = None, resolution: str | None = None,
        extra_body: dict | None = None,
    ) -> Path:
        if not str(prompt or "").strip():
            raise ValueError("NAI 提示词不能为空")
        prefix = str(self.settings.get("nai_prompt_prefix") or "").strip()
        params = {
            "tag": f"{prefix}, {prompt}" if prefix else prompt,
            "model": model or self.default_model,
            "size": self._resolve_size(size, resolution),
        }
        for source, target in {
            "nai_artist": "artist", "negative_prompt": "negative",
            "nai_sampler": "sampler", "num_inference_steps": "steps",
            "guidance_scale": "scale", "nai_cfg": "cfg",
            "nai_noise_schedule": "noise_schedule", "seed": "seed",
        }.items():
            value = self.settings.get(source)
            if value is not None and value != "":
                params[target] = value
        extra = self.settings.get("extra_body") or {}
        if isinstance(extra, str):
            extra = json.loads(extra)
        if not isinstance(extra, dict):
            raise ValueError("NAI 额外参数必须为 JSON 对象")
        params.update(extra)
        params.update(extra_body or {})
        params.pop("token", None)
        key = self._next_key()
        if key.lower().startswith("bearer "):
            key = key.split(" ", 1)[1].strip()
        headers = {}
        if self.auth_mode == "token":
            params["token"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"
        try:
            response = await self._get_client().get(
                self.full_generate_url, params=params, headers=headers
            )
        except httpx.HTTPError:
            # GET query parameters can contain credentials; never echo the URL.
            raise RuntimeError("NAI 网关网络请求失败，请检查连接或超时设置") from None
        if response.status_code != 200:
            raise RuntimeError(f"NAI 网关请求失败 HTTP {response.status_code}")
        try:
            return await self._save_response(
                response, endpoint_url=self.full_generate_url
            )
        except Exception:
            raise RuntimeError("NAI 网关未返回可用图片，或图片下载失败") from None

    async def edit(self, *args, **kwargs):
        raise RuntimeError("NAI GET 网关模板仅支持文生图，不支持参考图或改图")
