import asyncio
import importlib
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class XaiVideoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.mod = importlib.import_module(f"{CORE_PACKAGE_NAME}.xai_video_service")
        self.backend = self.mod.XaiVideoService(settings={"api_keys": ["secret"]})

    async def test_reference_submission_and_poll(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if request.method == "POST":
                self.assertEqual(request.url.path, "/v1/videos/generations")
                payload = json.loads(request.content)
                self.assertEqual(payload["duration"], 8)
                self.assertNotIn("seconds", payload)
                self.assertEqual(payload["reference_images"], [{"url": "https://cdn.test/ref.png"}])
                return httpx.Response(200, json={"request_id": "req"})
            self.assertEqual(request.url.path, "/v1/videos/req")
            return httpx.Response(200, json={"status": "done", "video": {"url": "https://cdn.test/video.mp4"}})
        self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(self.mod.asyncio, "sleep", new=AsyncMock()):
            result = await self.backend.generate_video_url("animate", image_urls=["https://cdn.test/ref.png"])
        self.assertEqual(result, "https://cdn.test/video.mp4")
        self.assertEqual(len(calls), 2)

    async def test_modes_and_limits(self):
        self.backend.reference_mode = "text"
        with self.assertRaises(ValueError):
            await self.backend.generate_video_url("test", image_bytes=b"image")
        self.backend.reference_mode = "reference"
        with self.assertRaises(ValueError):
            await self.backend.generate_video_url("test", image_urls=["https://cdn.test/a"] * 8)
        text = self.mod.XaiVideoService(settings={"xai_reference_mode": "text"})
        self.assertFalse(text.supports_selfie_reference_fallback)

    async def test_expired_and_cancellation(self):
        self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "expired"})
        ))
        with patch.object(self.mod.asyncio, "sleep", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "expired"):
                await self.backend._poll("req")
        with patch.object(self.mod.asyncio, "sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.backend._poll("req")
