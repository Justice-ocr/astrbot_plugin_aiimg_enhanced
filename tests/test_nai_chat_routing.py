import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_batch_result_delivery import _load_module, CORE_PACKAGE_NAME, ROOT


class NaiChatRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.services = {}
        for name in ("draw_service", "edit_router"):
            spec = importlib.util.spec_from_file_location(
                f"{CORE_PACKAGE_NAME}.{name}", ROOT / "core" / f"{name}.py"
            )
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            self.services[name] = mod
        self.translator = importlib.import_module(f"{CORE_PACKAGE_NAME}.nai_prompt")
        self.original = self.translator.translate_nai_prompt
        self.translator.translate_nai_prompt = AsyncMock(return_value="landscape, sunset")
        self.addCleanup(setattr, self.translator, "translate_nai_prompt", self.original)

    def router(self, edit=False, enabled=True, template="openai_chat"):
        backend = types.SimpleNamespace(
            generate=AsyncMock(return_value=Path("result.png")),
            edit=AsyncMock(return_value=Path("result.png")),
        )
        conf = {"__template_key": template, "nai_translate_prompt": enabled}
        registry = types.SimpleNamespace(
            get=lambda pid: conf, get_backend=lambda pid: backend,
            provider_ids=lambda: ["nai"],
        )
        cls = (
            self.services["edit_router"].EditRouter if edit
            else self.services["draw_service"].ImageDrawService
        )
        return cls({}, None, Path("."), registry=registry, context=object()), backend

    async def test_draw_translates_only_when_enabled_for_supported_template(self):
        for enabled, template, expected in [
            (True, "openai_chat", "landscape, sunset"),
            (False, "openai_chat", "original"),
            (True, "openai_images", "original"),
        ]:
            router, backend = self.router(enabled=enabled, template=template)
            self.translator.translate_nai_prompt.reset_mock()
            await router.generate("original", provider_id="nai", session_id="session-a")
            self.assertEqual(backend.generate.call_args.args[0], expected)
            self.assertEqual(
                self.translator.translate_nai_prompt.await_count,
                int(enabled and template == "openai_chat"),
            )

    async def test_edit_preserves_images_and_session(self):
        router, backend = self.router(edit=True)
        images = [b"reference"]
        await router.edit("original", images, backend="nai", session_id="session-b")
        self.assertEqual(backend.edit.call_args.args, ("landscape, sunset", images))
        self.assertEqual(self.translator.translate_nai_prompt.call_args.args[3], "session-b")

    async def test_translation_failure_does_not_submit(self):
        self.translator.translate_nai_prompt.side_effect = RuntimeError("conversion failed")
        router, backend = self.router()
        with self.assertRaisesRegex(RuntimeError, "conversion failed"):
            await router.generate("original", provider_id="nai", session_id="session")
        backend.generate.assert_not_awaited()
