import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_nai_workflow_tests'
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / 'core')]
sys.modules[PACKAGE] = pkg
mod = importlib.import_module(f'{PACKAGE}.nai_workflow')


class NaiWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workflow = mod.NaiWorkflow()
        self.provider = {'id': 'nai', '__template_key': 'nai_native',
                         'nai_artist': 'artist:configured', 'nai_prompt_prefix': 'masterpiece',
                         'negative_prompt': 'lowres, blurry', 'api_keys': ['fake-key']}
        self.context = types.SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value='chat'),
            llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text='{"tags":"1girl, sunset, outdoors"}')),
        )

    async def test_authored_artist_and_tags_bypass_llm_preserving_weighting(self):
        draft = await self.workflow.prepare(self.context,
            '画师串：{{artist:chosen}}, [artist:second] 正面：1girl, {blue_eyes}, looking_at_viewer 负面：lowres, bad_hands',
            self.provider, 'qq:GroupMessage:123')
        self.assertFalse(draft['converted'])
        self.context.llm_generate.assert_not_awaited()
        self.assertEqual(draft['artist'], '{{artist:chosen}}, [artist:second]')
        self.assertEqual(draft['prompt'], 'masterpiece, {{artist:chosen}}, [artist:second], 1girl, {blue_eyes}, looking_at_viewer')
        self.assertEqual(draft['negative'], 'lowres, bad_hands')

    async def test_inline_artist_is_tag_syntax_not_section_and_overrides_defaults(self):
        draft = await self.workflow.prepare(self.context,
            '{{artist:chosen}}, 1girl, solo, blue_eyes', self.provider, 'umo')
        self.assertEqual(draft['artist'], '')
        self.assertEqual(draft['prompt'], 'masterpiece, {{artist:chosen}}, 1girl, solo, blue_eyes')
        self.context.llm_generate.assert_not_awaited()

    async def test_natural_language_converts_only_tags_and_preserves_artist(self):
        draft = await self.workflow.prepare(self.context,
            '画师：artist:requested 正面：一个女孩在夕阳下 负面：bad hands', self.provider, 'qq:GroupMessage:123')
        self.assertTrue(draft['converted'])
        self.assertEqual(draft['artist'], 'artist:requested')
        self.assertEqual(draft['negative'], 'bad hands')
        self.assertEqual(draft['tags'], '1girl, sunset, outdoors')
        self.assertEqual(self.context.llm_generate.call_args.kwargs['prompt'], '一个女孩在夕阳下')
        self.context.get_current_chat_provider_id.assert_awaited_once_with(umo='qq:GroupMessage:123')
        self.assertEqual(self.workflow.pending, {})

    async def test_explicit_conversion_model_and_empty_negative(self):
        draft = await self.workflow.prepare(self.context, '正面：夕阳 负面：', self.provider, 'umo', llm_id='chosen')
        self.assertEqual(draft['negative'], '')
        self.assertEqual(draft['artist'], 'artist:configured')
        self.context.get_current_chat_provider_id.assert_not_awaited()
        self.assertEqual(self.context.llm_generate.call_args.kwargs['chat_provider_id'], 'chosen')

    async def test_conversion_error_does_not_submit_or_remember(self):
        self.context.llm_generate.return_value.completion_text = 'not json'
        with self.assertRaisesRegex(RuntimeError, 'JSON'):
            await self.workflow.prepare(self.context, '女孩', self.provider, 'umo')
        self.assertFalse(self.workflow.pending)

    async def test_confirmation_is_scoped_single_use_and_exact(self):
        draft = await self.workflow.prepare(self.context, '女孩', self.provider, 'umo')
        draft['provider_id'] = 'nai'
        remembered = self.workflow.remember(('umo', 'alice'), draft, self.provider)
        with self.assertRaises(ValueError):
            self.workflow.consume(('umo', 'bob'), remembered['token'], self.provider)
        with self.assertRaises(ValueError):
            self.workflow.consume(('other', 'alice'), remembered['token'], self.provider)
        with self.assertRaises(ValueError):
            self.workflow.consume(('umo', 'alice'), 'wrong', self.provider)
        item = self.workflow.consume(('umo', 'alice'), remembered['token'], self.provider)
        self.assertEqual(item['prompt'], draft['prompt'])
        with self.assertRaises(ValueError):
            self.workflow.consume(('umo', 'alice'), remembered['token'], self.provider)

    async def test_config_changes_and_expired_or_replaced_draft_reject_confirmation(self):
        draft = await self.workflow.prepare(self.context, '女孩', self.provider, 'umo')
        key = ('umo', 'alice')
        first = self.workflow.remember(key, draft, self.provider)
        second = self.workflow.remember(key, draft, self.provider)
        with self.assertRaises(ValueError):
            self.workflow.consume(key, first['token'], self.provider)
        with self.assertRaisesRegex(ValueError, '配置已变化'):
            self.workflow.consume(key, second['token'], {**self.provider, 'nai_artist': 'changed'})
        third = self.workflow.remember(key, draft, self.provider)
        self.workflow.pending[key]['expires'] = 0
        with self.assertRaises(ValueError):
            self.workflow.consume(key, third['token'], self.provider)

    def test_nai_detection_and_conservative_tag_detection(self):
        for template in ('nai_native', 'nai_gateway', 'nai_openai_images'):
            self.assertTrue(mod.is_nai_provider({'__template_key': template}))
        self.assertFalse(mod.is_nai_provider({'__template_key': 'openai_images', 'model': 'gpt-image-1'}))
        self.assertTrue(mod.is_nai_provider({'__template_key': 'openai_images', 'model': 'nai-diffusion-4-5-full'}))
        self.assertTrue(mod.looks_like_tags('1girl, blue_eyes, {long_hair}'))
        self.assertFalse(mod.looks_like_tags('画一个女孩, 蓝色眼睛'))
        self.assertFalse(mod.looks_like_tags('Please draw a girl who is standing outdoors in the warm sunlight'))
