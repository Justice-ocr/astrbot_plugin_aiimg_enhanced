import importlib
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from PIL import Image

from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class NaiNativeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.cls = importlib.import_module(f"{CORE_PACKAGE_NAME}.nai_native_backend").NaiNativeBackend
        output = io.BytesIO()
        Image.new("RGB", (64, 64)).save(output, "PNG")
        self.image = output.getvalue()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("metadata.txt", "test")
            z.writestr("image.png", self.image)
        self.zip = archive.getvalue()
        self.imgr = AsyncMock()
        self.imgr.save_image.return_value = Path("result.png")

    def backend(self, mode):
        backend = self.cls(imgr=self.imgr, settings={
            "base_url": "https://nai.test", "api_keys": ["secret"],
            "nai_reference_mode": mode, "seed": 0,
        })
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append((request.url.path, payload))
            self.assertEqual(request.headers["authorization"], "Bearer secret")
            if request.url.path.endswith("encode-vibe"):
                return httpx.Response(200, content=b"encoded")
            return httpx.Response(200, content=self.zip)

        backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return backend, requests

    async def test_img2img_and_zip(self):
        backend, requests = self.backend("img2img")
        try:
            result = await backend.edit("landscape", [self.image])
            self.assertEqual(result, Path("result.png"))
            payload = requests[0][1]
            self.assertEqual(payload["action"], "img2img")
            self.assertEqual(payload["parameters"]["seed"], 0)
            self.assertEqual(payload["parameters"]["strength"], .6)
            self.imgr.save_image.assert_awaited_once_with(self.image)
        finally:
            await backend.close()

    async def test_character_and_multi_image_rejection(self):
        backend, requests = self.backend("character")
        try:
            with self.assertRaisesRegex(ValueError, "仅支持一张"):
                await backend.edit("portrait", [self.image, self.image])
            self.assertEqual(requests, [])
            await backend.edit("portrait", [self.image])
            params = requests[0][1]["parameters"]
            self.assertIn("director_reference_images", params)
            self.assertNotIn("reference_image_multiple", params)
        finally:
            await backend.close()

    async def test_vibe_cache_and_generation_are_separate(self):
        backend, requests = self.backend("vibe")
        try:
            await backend.edit("landscape", [self.image, self.image])
            await backend.edit("landscape", [self.image])
            self.assertEqual(sum(path.endswith("encode-vibe") for path, _ in requests), 1)
            self.assertEqual(sum(path.endswith("generate-image") for path, _ in requests), 2)
            self.assertEqual(len(requests[1][1]["parameters"]["reference_image_multiple"]), 2)
        finally:
            await backend.close()

    async def test_bad_size_fails_before_network(self):
        backend, requests = self.backend("img2img")
        try:
            with self.assertRaises(ValueError):
                await backend.generate("landscape", size="100x100")
            self.assertEqual(requests, [])
        finally:
            await backend.close()
