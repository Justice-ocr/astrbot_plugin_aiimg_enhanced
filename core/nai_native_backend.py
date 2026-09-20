from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import secrets
import zipfile

from PIL import Image, ImageOps

from .nai_gateway_backend import NaiGatewayBackend


class NaiNativeBackend(NaiGatewayBackend):
    """Native JSON/ZIP protocol for compatible NAI gateways."""

    def __init__(self, *, imgr, settings):
        super().__init__(imgr=imgr, settings=settings)
        self.supports_edit = True
        self.base_url = str(settings.get("base_url") or "").rstrip("/")
        self.full_generate_url = self.base_url + "/ai/generate-image"
        self.mode = settings.get("nai_reference_mode") or "img2img"
        if self.mode not in {"img2img", "character", "vibe"}:
            raise ValueError("无效的 NAI 参考图模式")
        self._vibe_cache = {}
        self._vibe_lock = asyncio.Lock()

    def _number(self, name, default):
        value = float(self.settings.get(name, default))
        if not 0 <= value <= 1:
            raise ValueError(f"{name} 必须在 0 到 1 之间")
        return value

    @staticmethod
    def _image(raw, character=False):
        with Image.open(io.BytesIO(raw)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            if character:
                sizes = [(1472, 1472), (1536, 1024), (1024, 1536)]
                ratio = image.width / image.height
                target = min(sizes, key=lambda s: abs(s[0] / s[1] - ratio))
                image = ImageOps.pad(image, target, color="white")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90)
        return base64.b64encode(output.getvalue()).decode("ascii")

    async def _post(self, path, payload, key):
        import httpx

        try:
            response = await self._get_client().post(
                self.base_url + path, json=payload,
                headers={"Authorization": f"Bearer {key}"},
            )
        except httpx.HTTPError:
            raise RuntimeError("NAI 原生接口网络请求失败") from None
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"NAI 原生接口请求失败 HTTP {response.status_code}")
        return response

    async def _encode_vibe(self, image, model, key):
        info = self._number("nai_vibe_information", 1)
        cache_key = hashlib.sha256(
            json.dumps([self.base_url, key, model, info, image]).encode()
        ).hexdigest()
        async with self._vibe_lock:
            if cache_key not in self._vibe_cache:
                response = await self._post("/ai/encode-vibe", {
                    "image": image, "model": model, "information_extracted": info,
                }, key)
                if not response.content:
                    raise RuntimeError("NAI Vibe 编码为空")
                if len(self._vibe_cache) >= 32:
                    self._vibe_cache.pop(next(iter(self._vibe_cache)))
                self._vibe_cache[cache_key] = base64.b64encode(response.content).decode("ascii")
            return self._vibe_cache[cache_key]

    @staticmethod
    def _unzip(content):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for entry in archive.infolist():
                if entry.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    if entry.file_size > 32 * 1024 * 1024:
                        raise RuntimeError("NAI 返回图片过大")
                    return archive.read(entry)
        raise RuntimeError("NAI ZIP 中没有图片")

    async def _run(self, prompt, images, *, model=None, size=None, resolution=None, extra_body=None):
        if extra_body:
            raise ValueError("NAI 原生模板暂不支持任务级额外参数")
        if not str(prompt or "").strip():
            raise ValueError("NAI 提示词不能为空")
        if images and self.mode != "vibe" and len(images) != 1:
            raise ValueError("NAI 重绘和角色保持需要且仅支持一张参考图，请明确选择参考图")
        if len(images) > 9:
            raise ValueError("NAI Vibe 最多支持 9 张参考图")
        model = model or self.default_model
        width, height = map(int, self._resolve_size(size, resolution).split("x"))
        if min(width, height) < 64 or width % 64 or height % 64 or width * height > 4194304:
            raise ValueError("NAI 尺寸须为 64 的倍数，且不超过 4194304 像素")
        seed = self.settings.get("seed")
        seed = secrets.randbelow(2**32) if seed in (None, "") else int(seed)
        if not 0 <= seed < 2**32:
            raise ValueError("NAI seed 必须为 0 到 4294967295")
        prompt = ", ".join(str(v).strip() for v in [
            self.settings.get("nai_prompt_prefix"), self.settings.get("nai_artist"), prompt
        ] if v and str(v).strip())
        negative = self.settings.get("negative_prompt") or ""
        parameters = {
            "params_version": 3, "width": width, "height": height,
            "steps": int(self.settings.get("num_inference_steps", 28)),
            "scale": float(self.settings.get("guidance_scale", 5)),
            "seed": seed, "n_samples": 1,
            "sampler": self.settings.get("nai_sampler") or "k_euler_ancestral",
            "noise_schedule": self.settings.get("nai_noise_schedule") or "karras",
            "negative_prompt": negative,
            "cfg_rescale": float(self.settings.get("nai_cfg") or 0),
            "qualityToggle": False, "ucPreset": 0,
            "v4_prompt": {"caption": {"base_caption": prompt, "char_captions": []},
                          "use_coords": False, "use_order": True},
            "v4_negative_prompt": {"caption": {"base_caption": negative, "char_captions": []}},
        }
        if not 1 <= parameters["steps"] <= 50:
            raise ValueError("NAI steps 必须为 1 到 50")
        key = self._next_key()
        if key.lower().startswith("bearer "):
            key = key.split(" ", 1)[1].strip()
        action = "generate"
        if images:
            encoded = [await asyncio.to_thread(self._image, raw, self.mode == "character") for raw in images]
            if self.mode == "img2img":
                action = "img2img"
                parameters.update(image=encoded[0], strength=self._number("nai_strength", .6), noise=0)
            elif self.mode == "character":
                parameters.update(
                    director_reference_images=encoded,
                    director_reference_strength_values=[1.0],
                    director_reference_information_extracted=[1.0],
                    director_reference_secondary_strength_values=[self._number("nai_strength", .6)],
                    director_reference_descriptions=[{
                        "caption": {"base_caption": "character", "char_captions": []},
                        "use_coords": False, "use_order": False, "legacy_uc": False,
                    }],
                )
            else:
                strength = self._number("nai_strength", .6)
                parameters.update(
                    reference_image_multiple=[await self._encode_vibe(image, model, key) for image in encoded],
                    reference_strength_multiple=[strength] * len(encoded),
                    normalize_reference_strength_multiple=True,
                    add_original_image=False,
                )
        response = await self._post("/ai/generate-image", {
            "input": prompt, "model": model, "action": action, "parameters": parameters,
        }, key)
        if response.content.startswith(b"PK"):
            image = await asyncio.to_thread(self._unzip, response.content)
            return await self.imgr.save_image(image)
        return await self._save_response(response, endpoint_url=self.full_generate_url)

    async def generate(self, prompt, **kwargs):
        return await self._run(prompt, [], **kwargs)

    async def edit(self, prompt, images, **kwargs):
        if not images:
            raise ValueError("NAI 参考图不能为空")
        return await self._run(prompt, images, **kwargs)
