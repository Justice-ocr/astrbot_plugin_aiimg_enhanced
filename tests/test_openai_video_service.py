import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "openai_video_testpkg"
CORE_PACKAGE_NAME = f"{PACKAGE_NAME}.core"


class _Logger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def _load_module():
    for name in list(sys.modules):
        if name.startswith(PACKAGE_NAME):
            sys.modules.pop(name, None)

    pkg = types.ModuleType(PACKAGE_NAME)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = pkg

    core_pkg = types.ModuleType(CORE_PACKAGE_NAME)
    core_pkg.__path__ = [str(ROOT / "core")]
    sys.modules[CORE_PACKAGE_NAME] = core_pkg

    if "astrbot" not in sys.modules:
        sys.modules["astrbot"] = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    api_mod.logger = _Logger()
    sys.modules["astrbot.api"] = api_mod

    image_spec = importlib.util.spec_from_file_location(
        f"{CORE_PACKAGE_NAME}.image_format", ROOT / "core" / "image_format.py"
    )
    image_mod = importlib.util.module_from_spec(image_spec)
    sys.modules[image_spec.name] = image_mod
    assert image_spec and image_spec.loader
    image_spec.loader.exec_module(image_mod)

    spec = importlib.util.spec_from_file_location(
        f"{CORE_PACKAGE_NAME}.openai_video_service",
        ROOT / "core" / "openai_video_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class OpenAIVideoServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load_module()
        self.backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "seconds": "4",
            }
        )

    def test_builds_standard_openai_video_endpoints(self):
        self.assertEqual(self.backend._create_url(), "https://api.openai.com/v1/videos")
        self.assertEqual(
            self.backend._retrieve_url("video/1"),
            "https://api.openai.com/v1/videos/video%2F1",
        )
        self.assertEqual(
            self.backend._content_url("video/1"),
            "https://api.openai.com/v1/videos/video%2F1/content",
        )

        backend = self.mod.OpenAIVideoService(
            settings={"base_url": "https://router.test/v1", "api_keys": ["key"]}
        )
        self.assertEqual(backend._create_url(), "https://router.test/v1/videos")

    def test_builds_multipart_fields_for_text_and_reference_image(self):
        fields = self.backend._multipart_fields("cinematic scene", None)
        values = {name: value for name, value in fields}

        self.assertEqual(values["model"], (None, "minimax-h3"))
        self.assertEqual(values["prompt"], (None, "cinematic scene"))
        self.assertEqual(values["seconds"], (None, "4"))
        self.assertNotIn("input_reference", values)

        png = b"\x89PNG\r\n\x1a\nimage-data"
        image_fields = self.backend._multipart_fields("animate", png)
        image_values = {name: value for name, value in image_fields}
        filename, content, mime = image_values["input_reference"]
        self.assertEqual(filename, "reference.png")
        self.assertEqual(content, png)
        self.assertEqual(mime, "image/png")

    def test_supports_compatible_gateway_fields(self):
        backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "size": "1280x720",
                "input_reference_field": "image",
                "extra_form": '{"quality":"high"}',
            }
        )
        fields = {name: value for name, value in backend._multipart_fields("go", b"x")}

        self.assertEqual(fields["size"], (None, "1280x720"))
        self.assertEqual(fields["quality"], (None, "high"))
        self.assertIn("image", fields)

    async def test_text_submission_is_multipart_and_returns_video_id(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertTrue(
                request.headers["content-type"].startswith("multipart/form-data;")
            )
            body = await request.aread()
            self.assertIn(b'minimax-h3', body)
            self.assertIn(b'cinematic scene', body)
            return httpx.Response(200, json={"id": "video-1", "status": "queued"})

        transport = httpx.MockTransport(handler)
        self.backend._client = lambda **kwargs: httpx.AsyncClient(
            transport=transport, follow_redirects=True
        )

        self.assertEqual(
            await self.backend._submit("cinematic scene", None), "video-1"
        )

    async def test_completed_task_downloads_authenticated_content(self):
        self.backend.poll_interval = 1
        self.backend._download_content = AsyncMock(return_value="C:/videos/result.mp4")

        class _Response:
            status_code = 200

            def json(self):
                return {"id": "video-1", "status": "completed"}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, *args, **kwargs):
                return _Response()

        self.backend._client = lambda **kwargs: _Client()
        original_sleep = self.mod.asyncio.sleep
        self.mod.asyncio.sleep = AsyncMock()
        try:
            result = await self.backend._poll("video-1")
        finally:
            self.mod.asyncio.sleep = original_sleep

        self.assertEqual(result, "C:/videos/result.mp4")
        self.backend._download_content.assert_awaited_once_with("video-1")

    async def test_downloads_content_to_local_video_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.mod.OpenAIVideoService(
                settings={"api_keys": ["secret"], "max_download_mb": 10},
                data_dir=tmp,
            )

            async def handler(request: httpx.Request) -> httpx.Response:
                self.assertEqual(request.headers["authorization"], "Bearer secret")
                self.assertTrue(str(request.url).endswith("/v1/videos/video-1/content"))
                return httpx.Response(
                    200,
                    headers={"content-type": "video/mp4"},
                    content=b"video-bytes",
                )

            transport = httpx.MockTransport(handler)
            backend._client = lambda **kwargs: httpx.AsyncClient(
                transport=transport, follow_redirects=True
            )

            result = await backend._download_content("video-1")
            path = Path(result)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"video-bytes")

    async def test_generate_submits_then_polls_and_propagates_cancellation(self):
        self.backend._submit = AsyncMock(return_value="video-1")
        self.backend._poll = AsyncMock(return_value="C:/videos/result.mp4")

        result = await self.backend.generate_video_url("animate", image_bytes=b"image")
        self.assertEqual(result, "C:/videos/result.mp4")
        self.backend._submit.assert_awaited_once_with("animate", b"image")
        self.backend._poll.assert_awaited_once_with("video-1")

        self.backend._submit = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.backend.generate_video_url("cancel")


if __name__ == "__main__":
    unittest.main()
