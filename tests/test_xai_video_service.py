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

    async def test_auto_ratio_and_1080p_single_image(self):
        backend = self.mod.XaiVideoService(settings={
            "api_keys": ["secret"], "xai_reference_mode": "image",
            "aspect_ratio": "auto", "xai_resolution": "1080p", "duration": "1",
        })
        async def handler(request):
            payload = json.loads(request.content)
            self.assertNotIn("aspect_ratio", payload)
            self.assertEqual(payload["resolution"], "1080p")
            self.assertEqual(payload["duration"], 1)
            if backend.reference_mode == "image":
                self.assertEqual(payload["image"], {"url": "https://cdn.test/a"})
            else:
                self.assertNotIn("reference_images", payload)
            return httpx.Response(200, json={"request_id": "req"})
        backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        backend._poll = AsyncMock(return_value="result")
        await backend.generate_video_url("animate", image_urls=["https://cdn.test/a"])
        backend.reference_mode = "reference"
        with self.assertRaisesRegex(ValueError, "720p"):
            await backend.generate_video_url("animate", image_urls=["https://cdn.test/a"])
        await backend.generate_video_url("animate")

    async def test_poll_recovers_without_resubmission(self):
        codes = iter([503, 429, 200])
        async def handler(request):
            self.assertEqual(request.method, "GET")
            return httpx.Response(next(codes), json={
                "status": "done", "video": {"url": "https://cdn.test/result"},
            })
        self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.object(self.mod.asyncio, "sleep", new=AsyncMock()):
            self.assertEqual(await self.backend._poll("req"), "https://cdn.test/result")

    async def test_poll_errors_are_bounded_and_auth_is_not_retried(self):
        for code, expected in [(500, 3), (401, 1)]:
            calls = []
            async def handler(request):
                calls.append(request)
                return httpx.Response(code)
            self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch.object(self.mod.asyncio, "sleep", new=AsyncMock()):
                with self.assertRaisesRegex(RuntimeError, "request_id=req"):
                    await self.backend._poll("req")
            self.assertEqual(len(calls), expected)
