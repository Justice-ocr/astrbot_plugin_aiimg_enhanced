import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "pixel_output_testpkg"
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


class _DummyImageManager:
    async def save_image(self, data: bytes):
        return Path("/tmp/result.png")


def _clear_modules():
    for name in list(sys.modules):
        if name.startswith(PACKAGE_NAME) or name in {"astrbot", "astrbot.api"}:
            sys.modules.pop(name, None)


def _install_package_stubs():
    _clear_modules()
    pkg = types.ModuleType(PACKAGE_NAME)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = pkg

    core_pkg = types.ModuleType(CORE_PACKAGE_NAME)
    core_pkg.__path__ = [str(ROOT / "core")]
    sys.modules[CORE_PACKAGE_NAME] = core_pkg

    astrbot_mod = types.ModuleType("astrbot")
    sys.modules["astrbot"] = astrbot_mod

    api_mod = types.ModuleType("astrbot.api")
    api_mod.logger = _Logger()
    sys.modules["astrbot.api"] = api_mod


def _load_core_module(module_name: str):
    module_full_name = f"{CORE_PACKAGE_NAME}.{module_name}"
    spec = importlib.util.spec_from_file_location(
        module_full_name,
        ROOT / "core" / f"{module_name}.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_full_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_gemini_module():
    _install_package_stubs()
    _load_core_module("image_format")
    return _load_core_module("gemini_edit")


def _load_vertex_module():
    _install_package_stubs()
    _load_core_module("image_format")
    _load_core_module("gitee_sizes")
    _load_core_module("vertex_ai_anonymous_utils")
    return _load_core_module("vertex_ai_anonymous_backend")


def _load_openai_compat_module():
    _install_package_stubs()
    _load_core_module("image_format")
    _load_core_module("gitee_sizes")
    return _load_core_module("openai_compat_backend")


class GeminiPixelOutputRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_converts_pixel_size_to_gemini_resolution(self):
        mod = _load_gemini_module()
        backend = mod.GeminiEditBackend(
            imgr=_DummyImageManager(),
            settings={
                "api_keys": ["test-key"],
                "model": "gemini-3-pro-image-preview",
                "resolution": "1024x1024",
            },
        )
        seen: dict[str, object] = {}

        async def _request(parts, *, resolution=None):
            seen["parts"] = parts
            seen["resolution"] = resolution
            return {"candidates": []}

        async def _extract_images_with_fallback(data):
            return [b"image-bytes"]

        backend._request = _request
        backend._extract_images_with_fallback = _extract_images_with_fallback

        await backend.generate("draw a city", size="2048x2048")

        self.assertEqual(seen["resolution"], "2K")
        self.assertIn("2K resolution image", seen["parts"][0]["text"])

    async def test_generate_converts_pixel_default_resolution(self):
        mod = _load_gemini_module()
        backend = mod.GeminiEditBackend(
            imgr=_DummyImageManager(),
            settings={
                "api_keys": ["test-key"],
                "model": "gemini-3-pro-image-preview",
                "resolution": "4096x4096",
            },
        )
        seen: dict[str, object] = {}

        async def _request(parts, *, resolution=None):
            seen["parts"] = parts
            seen["resolution"] = resolution
            return {"candidates": []}

        async def _extract_images_with_fallback(data):
            return [b"image-bytes"]

        backend._request = _request
        backend._extract_images_with_fallback = _extract_images_with_fallback

        await backend.generate("draw a city")

        self.assertEqual(seen["resolution"], "4K")
        self.assertIn("4K resolution image", seen["parts"][0]["text"])


class SizeCompatibilityTests(unittest.TestCase):
    def test_gitee_supported_sizes_are_16_aligned(self):
        _install_package_stubs()
        mod = _load_core_module("gitee_sizes")

        for size in mod.GITEE_SUPPORTED_SIZES:
            width, height = [int(part) for part in size.split("x", 1)]
            self.assertEqual(width % 16, 0, size)
            self.assertEqual(height % 16, 0, size)

    def test_openai_compat_falls_back_to_same_ratio_allowed_size(self):
        mod = _load_openai_compat_module()
        backend = mod.OpenAICompatBackend(
            imgr=object(),
            base_url="https://example.com/v1",
            api_keys=["key"],
            default_model="model",
            default_size="1024x1024",
            allowed_sizes=["1024x1024", "2048x1152", "576x1024"],
        )

        final_size, raw_size, fallback_used = backend._resolve_size("3840x2160", None)

        self.assertEqual(raw_size, "3840x2160")
        self.assertEqual(final_size, "2048x1152")
        self.assertTrue(fallback_used)


class VertexPixelOutputRoutingTests(unittest.TestCase):
    def test_square_pixel_size_sets_vertex_image_size(self):
        mod = _load_vertex_module()
        settings = mod.VertexAIAnonymousSettings(
            model="gemini-3-pro-image-preview",
            timeout_seconds=300,
            max_retries=1,
            proxy_url=None,
            recaptcha_base_api="https://www.google.com",
            vertex_base_api="https://vertex.example",
            system_prompt=None,
            query_signature="sig",
            graphql_api_key="key",
        )
        backend = mod.VertexAIAnonymousBackend(
            imgr=object(),
            settings=settings,
        )

        body = backend._build_body(
            "draw a city",
            None,
            size="4096x4096",
            resolution=None,
        )

        image_config = body["variables"]["generationConfig"]["imageConfig"]
        self.assertEqual(image_config["aspectRatio"], "1:1")
        self.assertEqual(image_config["imageSize"], "4K")


if __name__ == "__main__":
    unittest.main()
