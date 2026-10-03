import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class OpenAIImagesNegativeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        path = Path(__file__).resolve().parents[1] / "core" / "openai_compat_backend.py"
        spec = importlib.util.spec_from_file_location(f"{CORE_PACKAGE_NAME}.openai_compat_negative", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.cls = module.OpenAICompatBackend

    def backend(self, base_url):
        backend = self.cls(
            imgr=AsyncMock(), base_url=base_url, api_keys=["test"],
            default_model="nai", default_size="1024x1024", max_retries=0,
            extra_body={"negative_prompt": "default negative", "quality": "high"},
        )
        generate = AsyncMock(return_value=object())
        backend._get_client = lambda key: types.SimpleNamespace(images=types.SimpleNamespace(generate=generate))
        backend._save_images_response = AsyncMock(return_value=Path("result.png"))
        backend._try_get_image_size = lambda path: None
        return backend, generate

    async def test_gateway_override_empty_and_default(self):
        backend, generate = self.backend("https://gateway.test/v1")
        for negative, expected in (("lowres", "lowres"), ("", ""), (None, "default negative")):
            await backend.generate("{artist:test}, 1girl", negative_prompt=negative)
            request = generate.call_args.kwargs
            self.assertEqual(request["prompt"], "{artist:test}, 1girl")
            self.assertEqual(request["extra_body"]["negative_prompt"], expected)
            self.assertEqual(request["extra_body"]["quality"], "high")
        self.assertEqual(backend.extra_body["negative_prompt"], "default negative")

    async def test_override_wins_over_extra_body(self):
        backend, generate = self.backend("https://gateway.test/v1")
        await backend.generate("1girl", extra_body={"negative_prompt": "task extra"}, negative_prompt="explicit")
        self.assertEqual(generate.call_args.kwargs["extra_body"]["negative_prompt"], "explicit")

    async def test_official_uses_prompt_instruction_not_unknown_field(self):
        backend, generate = self.backend("https://api.openai.com/v1")
        await backend.generate("1girl", negative_prompt="text, watermark")
        request = generate.call_args.kwargs
        self.assertEqual(request["prompt"], "1girl\n\nAvoid these elements: text, watermark")
        self.assertNotIn("negative_prompt", request["extra_body"])
        await backend.generate("1girl", negative_prompt="")
        self.assertEqual(generate.call_args.kwargs["prompt"], "1girl")
        self.assertNotIn("negative_prompt", generate.call_args.kwargs["extra_body"])
        self.assertEqual(backend.extra_body["negative_prompt"], "default negative")
