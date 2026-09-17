import asyncio
import base64
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "minimax_h3_video_testpkg"
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
        f"{CORE_PACKAGE_NAME}.minimax_h3_video_service",
        ROOT / "core" / "minimax_h3_video_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MiniMaxH3VideoServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load_module()
        self.backend = self.mod.MiniMaxH3VideoService(
            settings={"api_keys": ["secret"], "model": "MiniMax-H3"}
        )

    def test_builds_text_first_frame_and_reference_payloads(self):
        text = self.backend._build_payload("rainy city", [])
        self.assertEqual(text["model"], "MiniMax-H3")
        self.assertEqual(text["resolution"], "2K")
        self.assertEqual(text["duration"], 5)
        self.assertEqual(text["ratio"], "16:9")
        self.assertEqual(text["content"], [{"type": "text", "text": "rainy city"}])

        first_frame = self.backend._build_payload(
            "walk forward", ["https://cdn.test/first.png"]
        )
        self.assertEqual(first_frame["ratio"], "adaptive")
        self.assertEqual(first_frame["content"][1]["role"], "first_frame")

        reference = self.backend._build_payload(
            "preserve character",
            ["https://cdn.test/one.png", "https://cdn.test/two.png"],
        )
        self.assertEqual(reference["ratio"], "16:9")
        self.assertEqual(
            [item["role"] for item in reference["content"][1:]],
            ["reference_image", "reference_image"],
        )

    async def test_local_image_defaults_to_data_uri(self):
        png = b"\x89PNG\r\n\x1a\nimage-data"
        refs = await self.backend._prepare_reference_urls([png], [""])

        self.assertEqual(len(refs), 1)
        self.assertTrue(refs[0].startswith("data:image/"))
        encoded = refs[0].split(",", 1)[1]
        self.assertEqual(base64.b64decode(encoded), png)

    async def test_rejects_unsupported_local_image_format(self):
        with self.assertRaisesRegex(RuntimeError, "仅支持 JPEG、PNG 或 WEBP"):
            await self.backend._prepare_reference_urls([b"GIF89aimage-data"], [""])

    def test_builds_official_endpoints(self):
        self.assertEqual(
            self.backend._create_url(), "https://api.minimax.io/v2/video_generation"
        )
        self.assertEqual(
            self.backend._poll_url("task/1"),
            "https://api.minimax.io/v2/query/video_generation/task%2F1",
        )

    def test_parses_success_and_failure_task_responses(self):
        self.assertEqual(
            self.backend._parse_poll_result(
                {
                    "task": {
                        "status": "succeeded",
                        "content": {"url": "https://cdn.test/result.mp4"},
                    }
                }
            ),
            ("succeeded", "https://cdn.test/result.mp4", ""),
        )
        self.assertEqual(
            self.backend._parse_poll_result(
                {
                    "task": {
                        "status": "failed",
                        "error": {"message": "sensitive content"},
                    }
                }
            ),
            ("failed", "", "sensitive content"),
        )

    async def test_generate_prepares_images_submits_and_polls(self):
        self.backend._prepare_reference_urls = AsyncMock(
            return_value=["https://cdn.test/first.png"]
        )
        self.backend._submit = AsyncMock(return_value="task-1")
        self.backend._poll = AsyncMock(return_value="https://cdn.test/result.mp4")

        result = await self.backend.generate_video_url(
            "animate", image_bytes_list=[b"image"], image_urls=[""]
        )

        self.assertEqual(result, "https://cdn.test/result.mp4")
        payload = self.backend._submit.await_args.args[0]
        self.assertEqual(payload["content"][1]["role"], "first_frame")
        self.backend._poll.assert_awaited_once_with("task-1")

    async def test_cancelled_reference_preparation_propagates(self):
        self.backend._prepare_reference_urls = AsyncMock(
            side_effect=asyncio.CancelledError
        )
        with self.assertRaises(asyncio.CancelledError):
            await self.backend.generate_video_url(
                "animate", image_bytes_list=[b"image"]
            )

    def test_rejects_adaptive_ratio_for_text_video(self):
        backend = self.mod.MiniMaxH3VideoService(
            settings={"api_keys": ["secret"], "ratio": "adaptive"}
        )
        with self.assertRaisesRegex(RuntimeError, "文生视频不能使用 adaptive"):
            backend._build_payload("rainy city", [])


if __name__ == "__main__":
    unittest.main()
