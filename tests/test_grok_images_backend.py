import base64
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "grok_images_testpkg"
CORE_PACKAGE_NAME = f"{PACKAGE_NAME}.core"
PNG_BYTES = b"\x89PNG\r\n\x1a\nsource-image"
RESULT_BYTES = b"generated-image"


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
    def __init__(self):
        self.saved = None

    async def save_image(self, data: bytes):
        self.saved = data
        return Path("/tmp/result.png")

    async def download_image(self, url: str):
        raise AssertionError(f"unexpected download: {url}")


class _FakeResponse:
    def __init__(self, *, status=200, body=None):
        self.status = status
        if body is None:
            encoded = base64.b64encode(RESULT_BYTES).decode("ascii")
            body = {"data": [{"b64_json": encoded}]}
        self._body = json.dumps(body).encode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        return self._body


class _FakeSession:
    closed = False

    def __init__(self, responses=None):
        self.requests = []
        self.responses = list(responses or [])

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse()

    async def close(self):
        self.closed = True


def _clear_modules():
    for name in list(sys.modules):
        if name.startswith(PACKAGE_NAME) or name in {
            "aiohttp",
            "astrbot",
            "astrbot.api",
        }:
            sys.modules.pop(name, None)


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


def _load_module():
    _clear_modules()

    pkg = types.ModuleType(PACKAGE_NAME)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = pkg

    core_pkg = types.ModuleType(CORE_PACKAGE_NAME)
    core_pkg.__path__ = [str(ROOT / "core")]
    sys.modules[CORE_PACKAGE_NAME] = core_pkg

    sys.modules["astrbot"] = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    api_mod.logger = _Logger()
    sys.modules["astrbot.api"] = api_mod

    aiohttp_mod = types.ModuleType("aiohttp")
    aiohttp_mod.ClientError = type("ClientError", (Exception,), {})
    aiohttp_mod.ClientSession = object
    aiohttp_mod.ClientTimeout = lambda *, total: types.SimpleNamespace(total=total)
    sys.modules["aiohttp"] = aiohttp_mod

    _load_core_module("gitee_sizes")
    _load_core_module("image_format")
    return _load_core_module("grok_images_backend")


def _make_backend(
    mod,
    *,
    default_size="2048x2048",
    default_model="",
    max_retries=0,
    responses=None,
):
    imgr = _DummyImageManager()
    backend = mod.GrokImagesBackend(
        imgr=imgr,
        base_url="https://api.x.ai/v1",
        api_keys=["test-key"],
        max_retries=max_retries,
        default_model=default_model,
        default_size=default_size,
    )
    session = _FakeSession(responses)
    backend._session = session
    return backend, imgr, session


class GrokImagesBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_uses_xai_json_output_fields(self):
        mod = _load_module()
        backend, imgr, session = _make_backend(mod)

        result = await backend.generate("draw a city", size="1024x576")

        self.assertEqual(result, Path("/tmp/result.png"))
        self.assertEqual(imgr.saved, RESULT_BYTES)
        self.assertEqual(len(session.requests), 1)
        url, request = session.requests[0]
        self.assertEqual(url, "https://api.x.ai/v1/images/generations")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        payload = request["json"]
        self.assertEqual(payload["model"], "grok-imagine-image-quality")
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["resolution"], "1k")
        self.assertNotIn("size", payload)
        self.assertNotIn("data", request)

    async def test_single_image_edit_uses_json_image_data_uri(self):
        mod = _load_module()
        backend, imgr, session = _make_backend(mod)

        await backend.edit("make it a sketch", [PNG_BYTES], size="2048x1152")

        self.assertEqual(imgr.saved, RESULT_BYTES)
        url, request = session.requests[0]
        self.assertEqual(url, "https://api.x.ai/v1/images/edits")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        payload = request["json"]
        self.assertIn("image", payload)
        self.assertNotIn("images", payload)
        self.assertTrue(payload["image"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(payload["resolution"], "2k")
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("size", payload)
        self.assertNotIn("data", request)

    async def test_multi_image_edit_keeps_images_separate(self):
        mod = _load_module()
        backend, _imgr, session = _make_backend(mod)

        await backend.edit(
            "combine <IMAGE_0> and <IMAGE_1>",
            [PNG_BYTES, PNG_BYTES + b"-second"],
            size="2048x1152",
        )

        payload = session.requests[0][1]["json"]
        self.assertNotIn("image", payload)
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertNotEqual(payload["images"][0]["url"], payload["images"][1]["url"])

    async def test_edit_rejects_more_than_three_images(self):
        mod = _load_module()
        backend, _imgr, session = _make_backend(mod)

        with self.assertRaisesRegex(ValueError, "最多支持三张"):
            await backend.edit("combine", [PNG_BYTES] * 4)

        self.assertEqual(session.requests, [])

    async def test_legacy_model_name_is_migrated(self):
        mod = _load_module()
        backend, _imgr, session = _make_backend(mod)

        await backend.edit(
            "make it cinematic",
            [PNG_BYTES],
            model="grok-imagine-1.0-edit",
        )

        self.assertEqual(
            session.requests[0][1]["json"]["model"],
            "grok-imagine-image-quality",
        )

    async def test_edit_falls_back_when_quality_upstream_is_unavailable(self):
        mod = _load_module()
        unavailable = _FakeResponse(
            status=400,
            body={
                "error": {
                    "message": "上游服务暂不可用",
                    "code": "upstream_unavailable",
                }
            },
        )
        backend, imgr, session = _make_backend(
            mod,
            default_model="grok-imagine-image-quality",
            responses=[unavailable, _FakeResponse()],
        )

        await backend.edit("make it cinematic", [PNG_BYTES])

        self.assertEqual(imgr.saved, RESULT_BYTES)
        self.assertEqual(len(session.requests), 2)
        self.assertEqual(
            [request[1]["json"]["model"] for request in session.requests],
            ["grok-imagine-image-quality", "grok-imagine-image"],
        )


class GrokProviderConfigTests(unittest.TestCase):
    def test_schema_uses_current_xai_defaults(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        items = schema["providers"]["templates"]["grok_images"]["items"]

        self.assertEqual(items["model"]["default"], "grok-imagine-image-quality")
        self.assertEqual(items["default_size"]["default"], "2048x2048")
        self.assertNotIn("generate_request_mode", items)
        self.assertNotIn("edit_request_mode", items)

    def test_settings_catalog_uses_current_xai_defaults(self):
        source = (ROOT / "pages" / "Settings" / "provider_catalog.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("model:'grok-imagine-image-quality'", source)
        self.assertIn("default_size:'2048x2048'", source)


if __name__ == "__main__":
    unittest.main()
