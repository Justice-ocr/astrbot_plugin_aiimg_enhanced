import asyncio
import json
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

    def test_normalizes_full_width_ratio_and_pixel_size(self):
        ratio_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "size": " 16 ： 9 ",
            }
        )
        ratio_fields = dict(ratio_backend._multipart_fields("go", None))
        self.assertEqual(ratio_fields["size"], (None, "16:9"))

        pixel_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "size": "1280×720",
            }
        )
        pixel_fields = dict(pixel_backend._multipart_fields("go", None))
        self.assertEqual(pixel_fields["size"], (None, "1280x720"))

    async def test_prepares_public_and_data_uri_reference_images(self):
        png = b"\x89PNG\r\n\x1a\nimage-data"
        refs = await self.backend._prepare_reference_urls(
            [b"", png],
            ["https://cdn.test/one.png", ""],
        )

        self.assertEqual(refs[0], "https://cdn.test/one.png")
        self.assertTrue(refs[1].startswith("data:image/png;base64,"))

    def test_builds_image_urls_for_up_to_nine_references(self):
        backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "seconds": "8",
                "video_resolution": "1080p",
                "image_input_mode": "image_urls",
            }
        )
        refs = [f"https://cdn.test/{index}.png" for index in range(12)]
        fields = dict(
            backend._multipart_fields("animate", b"image", reference_urls=refs)
        )

        self.assertEqual(fields["resolution"], (None, "1080p"))
        self.assertEqual(
            json.loads(fields["image_urls"][1]),
            refs[:9],
        )
        self.assertNotIn("input_reference", fields)

    def test_builds_first_and_last_frame_fields(self):
        backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "seconds": "10",
                "video_resolution": "768p",
                "image_input_mode": "first_last_frame",
            }
        )
        refs = ["https://cdn.test/first.png", "https://cdn.test/last.png"]
        fields = dict(
            backend._multipart_fields("transition", b"first", reference_urls=refs)
        )

        self.assertEqual(fields["first_frame_image"], (None, refs[0]))
        self.assertEqual(fields["last_frame_image"], (None, refs[1]))
        self.assertNotIn("image_urls", fields)

        with self.assertRaisesRegex(RuntimeError, "必须同时提供且仅提供两张"):
            backend._multipart_fields("transition", b"first", reference_urls=refs[:1])

    def test_builds_image_with_roles_variants(self):
        refs = ["https://cdn.test/one.png", "https://cdn.test/two.png"]
        reference_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "image_input_mode": "roles_reference",
            }
        )
        reference_fields = dict(
            reference_backend._multipart_fields("keep characters", b"one", reference_urls=refs)
        )
        self.assertEqual(
            json.loads(reference_fields["image_with_roles"][1]),
            [
                {"url": refs[0], "role": "reference_image"},
                {"url": refs[1], "role": "reference_image"},
            ],
        )

        frame_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "image_input_mode": "roles_frames",
            }
        )
        frame_fields = dict(
            frame_backend._multipart_fields("transition", b"one", reference_urls=refs)
        )
        self.assertEqual(
            json.loads(frame_fields["image_with_roles"][1]),
            [
                {"url": refs[0], "role": "first_frame"},
                {"url": refs[1], "role": "last_frame"},
            ],
        )

    def test_validates_minimax_h3_duration_and_resolution_by_mode(self):
        text_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "seconds": "15",
                "video_resolution": "768p",
            }
        )
        text_backend._multipart_fields("text video", None)

        reference_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "seconds": "11",
                "image_input_mode": "image_urls",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "图生视频时长必须为 1–10 秒"):
            reference_backend._multipart_fields(
                "reference video",
                b"image",
                reference_urls=["https://cdn.test/ref.png"],
            )

        frame_backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "video_resolution": "1080p",
                "image_input_mode": "first_last_frame",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "480p / 768p"):
            frame_backend._multipart_fields(
                "frames",
                b"image",
                reference_urls=["https://cdn.test/first.png", "https://cdn.test/last.png"],
            )

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

    async def test_retries_data_uri_fields_as_json_on_multipart_parser_error(self):
        png = b"\x89PNG\r\n\x1a\nimage-data"
        refs = await self.backend._prepare_reference_urls([png], [""])
        backend = self.mod.OpenAIVideoService(
            settings={
                "api_keys": ["secret"],
                "model": "minimax-h3",
                "image_input_mode": "image_urls",
            }
        )
        requests = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                self.assertTrue(
                    request.headers["content-type"].startswith("multipart/form-data;")
                )
                return httpx.Response(
                    400,
                    json={
                        "code": "invalid_json",
                        "message": "multipart: NextPart: bufio: buffer full",
                    },
                )

            self.assertEqual(request.headers["content-type"], "application/json")
            payload = json.loads((await request.aread()).decode("utf-8"))
            self.assertEqual(payload["image_urls"], refs)
            return httpx.Response(200, json={"id": "video-json", "status": "queued"})

        transport = httpx.MockTransport(handler)
        backend._client = lambda **kwargs: httpx.AsyncClient(
            transport=transport, follow_redirects=True
        )

        self.assertEqual(
            await backend._submit("animate", png, reference_urls=refs),
            "video-json",
        )
        self.assertEqual(len(requests), 2)

    async def test_does_not_json_retry_binary_reference_upload(self):
        backend = self.mod.OpenAIVideoService(
            settings={"api_keys": ["secret"], "max_retries": 0}
        )
        requests = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                400,
                json={"message": "multipart: NextPart: bufio: buffer full"},
            )

        transport = httpx.MockTransport(handler)
        backend._client = lambda **kwargs: httpx.AsyncClient(
            transport=transport, follow_redirects=True
        )

        with self.assertRaisesRegex(RuntimeError, "bufio: buffer full"):
            await backend._submit("animate", b"image-bytes")
        self.assertEqual(len(requests), 1)

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
        submit_call = self.backend._submit.await_args
        self.assertEqual(submit_call.args, ("animate", b"image"))
        self.assertEqual(submit_call.kwargs["reference_urls"], [])
        self.backend._poll.assert_awaited_once_with("video-1")

        self.backend._submit = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.backend.generate_video_url("cancel")


if __name__ == "__main__":
    unittest.main()
