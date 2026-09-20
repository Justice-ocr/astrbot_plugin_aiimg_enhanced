import asyncio
import importlib.util
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


spec = importlib.util.spec_from_file_location(
    "nai_prompt_test", Path(__file__).resolve().parents[1] / "core" / "nai_prompt.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NaiPromptTests(unittest.IsolatedAsyncioTestCase):
    def context(self, text='{"tags":"landscape, sunset"}'):
        return types.SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value="session-model"),
            llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text=text)),
        )

    async def test_current_session_model(self):
        context = self.context()
        result = await module.translate_nai_prompt(context, "夕阳风景", {}, "session-a")
        self.assertEqual(result, "landscape, sunset")
        context.get_current_chat_provider_id.assert_awaited_once_with(umo="session-a")
        self.assertEqual(context.llm_generate.call_args.kwargs["chat_provider_id"], "session-model")
        self.assertEqual(context.llm_generate.call_args.kwargs["prompt"], "夕阳风景")

    async def test_explicit_model_and_fenced_json(self):
        context = self.context('```json\n{"tags":"sky"}\n```')
        result = await module.translate_nai_prompt(
            context, "天空", {"nai_llm_provider_id": "chosen"}, None
        )
        self.assertEqual(result, "sky")
        context.get_current_chat_provider_id.assert_not_awaited()
        self.assertEqual(context.llm_generate.call_args.kwargs["chat_provider_id"], "chosen")

    async def test_rejects_invalid_and_empty_results(self):
        for text in ["", "explanation", "[]", '{"tags":""}', '{"tags":[]}']:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                await module.translate_nai_prompt(self.context(text), "天空", {}, "session")

    async def test_missing_session_and_cancellation(self):
        with self.assertRaisesRegex(RuntimeError, "缺少会话"):
            await module.translate_nai_prompt(self.context(), "天空", {}, None)
        context = self.context()
        context.llm_generate.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await module.translate_nai_prompt(context, "天空", {}, "session")
