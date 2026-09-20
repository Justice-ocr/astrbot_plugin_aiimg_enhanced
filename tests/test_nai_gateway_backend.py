import importlib
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class NaiGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.cls = importlib.import_module(
            f"{CORE_PACKAGE_NAME}.nai_gateway_backend"
        ).NaiGatewayBackend
        self.imgr = AsyncMock()
        self.imgr.save_image.return_value = Path("result.png")
        self.imgr.download_image.return_value = Path("download.png")

    async def test_query_parameters_and_binary_response(self):
        backend = self.cls(imgr=self.imgr, settings={
            "base_url": "https://gateway.test",
            "api_keys": ["Bearer secret"], "nai_artist": "artist:test",
            "nai_prompt_prefix": "masterpiece", "num_inference_steps": 28,
            "guidance_scale": 5, "nai_cfg": 0, "seed": 0,
            "extra_body": '{"nocache":true}',
        })

        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/generate")
            self.assertEqual(request.url.params["token"], "secret")
            self.assertEqual(request.url.params["tag"], "masterpiece, landscape")
            self.assertEqual(request.url.params["artist"], "artist:test")
            self.assertEqual(request.url.params["cfg"], "0")
            self.assertEqual(request.url.params["seed"], "0")
            self.assertEqual(request.url.params["steps"], "28")
            return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})

        backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            self.assertEqual(await backend.generate("landscape"), Path("result.png"))
            self.assertFalse(backend.supports_edit)
        finally:
            await backend.close()

    async def test_bearer_and_json_url(self):
        backend = self.cls(imgr=self.imgr, settings={
            "base_url": "https://gateway.test", "generate_path": "/custom",
            "api_keys": ["secret"], "nai_auth_mode": "bearer",
        })

        def handler(request):
            self.assertEqual(request.url.path, "/custom")
            self.assertNotIn("token", request.url.params)
            self.assertEqual(request.headers["authorization"], "Bearer secret")
            return httpx.Response(200, json={"url": "https://cdn.test/image.png"})

        backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            self.assertEqual(await backend.generate("landscape"), Path("download.png"))
        finally:
            await backend.close()

    async def test_error_does_not_echo_token(self):
        backend = self.cls(imgr=self.imgr, settings={
            "base_url": "https://gateway.test", "api_keys": ["secret"],
        })
        backend._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(400, text="secret")
        ))
        try:
            with self.assertRaisesRegex(RuntimeError, "HTTP 400") as ctx:
                await backend.generate("landscape")
            self.assertNotIn("secret", str(ctx.exception))
            with self.assertRaisesRegex(RuntimeError, "仅支持文生图"):
                await backend.edit("change", [])
        finally:
            await backend.close()
