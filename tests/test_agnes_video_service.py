import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "agnes_video_testpkg"
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
        f"{CORE_PACKAGE_NAME}.agnes_video_service",
        ROOT / "core" / "agnes_video_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AgnesVideoServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load_module()
        self.backend = self.mod.AgnesVideoService(
            settings={"api_keys": ["secret"], "model": "agnes-video-2.5-flash"}
        )

    def test_builds_text_keyframe_and_reference_payloads(self):
        text = self.backend._build_payload("rainy city", [])
        self.assertEqual(text["mode"], "text")
        self.assertEqual(text["size"], "720P")
        self.assertEqual(text["seconds"], "5")

        keyframe = self.backend._build_payload("walk forward", ["https://cdn.test/first.png"])
        self.assertEqual(keyframe["mode"], "keyframe")
        self.assertEqual(keyframe["first_frame"], "https://cdn.test/first.png")

        reference = self.backend._build_payload(
            "preserve character",
            ["https://cdn.test/one.png", "https://cdn.test/two.png"],
        )
        self.assertEqual(reference["mode"], "reference")
        self.assertEqual(len(reference["images"]), 2)

    def test_builds_agnes_endpoints(self):
        self.assertEqual(
            self.backend._create_url(), "https://apihub.agnes-ai.com/v1/videos"
        )
        self.assertEqual(self.backend._api_root(), "https://apihub.agnes-ai.com")

    async def test_generate_prepares_images_submits_and_polls(self):
        self.backend._prepare_reference_urls = AsyncMock(
            return_value=["https://cdn.test/first.png"]
        )
        self.backend._submit = AsyncMock(return_value=("video-1", "task-1"))
        self.backend._poll = AsyncMock(return_value="https://cdn.test/result.mp4")

        result = await self.backend.generate_video_url(
            "animate",
            image_bytes_list=[b"image"],
            image_urls=[""],
        )

        self.assertEqual(result, "https://cdn.test/result.mp4")
        payload = self.backend._submit.await_args.args[0]
        self.assertEqual(payload["mode"], "keyframe")
        self.backend._poll.assert_awaited_once_with("video-1")

    async def test_cancelled_upload_propagates(self):
        self.backend._upload_free_public = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.backend._prepare_reference_urls([b"image"], [""])

    def test_extracts_metadata_video_url(self):
        self.assertEqual(
            self.backend._extract_video_url(
                {"status": "completed", "metadata": {"url": "https://cdn.test/out.mp4"}}
            ),
            "https://cdn.test/out.mp4",
        )


if __name__ == "__main__":
    unittest.main()
