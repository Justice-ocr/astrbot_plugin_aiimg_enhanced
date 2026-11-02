import types
import unittest
from unittest.mock import AsyncMock

from test_batch_result_delivery import _load_module


class NaiCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load_module()
        self.plugin = object.__new__(self.mod.GiteeAIImagePlugin)
        self.providers = {
            'first': {'id': 'first', '__template_key': 'nai_native', 'model': 'nai-v4', 'nai_artist': 'artist:default'},
            'second': {'id': 'second', '__template_key': 'nai_openai_images', 'model': 'nai-v4', 'nai_artist': 'artist:second'},
        }
        self.plugin.registry = types.SimpleNamespace(get=lambda key: self.providers.get(key), provider_ids=lambda: list(self.providers))
        self.plugin.nai_workflow = self.mod.NaiWorkflow()
        self.plugin.context = types.SimpleNamespace(
            get_current_chat_provider_id=AsyncMock(return_value='chat'),
            llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text='{"tags":"1girl, sunset, outdoors"}')),
        )
        self.plugin._nai_generate_confirmed = AsyncMock()

    def event(self, message, umo='qq:GroupMessage:100', user='alice'):
        return types.SimpleNamespace(message_str=message, unified_msg_origin=umo,
            get_sender_id=lambda: user, send=AsyncMock(), plain_result=lambda value: value, stop_event=lambda: None)

    async def test_conversion_is_preview_until_matching_user_confirms_exact_provider(self):
        event = self.event('/nai @second 画一个女孩')
        await self.plugin.nai_command(event)
        self.plugin._nai_generate_confirmed.assert_not_awaited()
        key = (event.unified_msg_origin, 'alice')
        draft = self.plugin.nai_workflow.pending[key]
        self.assertEqual(draft['provider_id'], 'second')
        self.assertIn('NAI 草稿', event.send.call_args.args[0])
        self.assertIn(draft['token'], event.send.call_args.args[0])
        await self.plugin.nai_confirm_command(self.event('/nai确认 ' + draft['token'], user='bob'))
        self.plugin._nai_generate_confirmed.assert_not_awaited()
        confirmation = self.event('/nai确认 ' + draft['token'])
        await self.plugin.nai_confirm_command(confirmation)
        self.plugin._nai_generate_confirmed.assert_awaited_once()
        actual = self.plugin._nai_generate_confirmed.call_args.args[1]
        self.assertEqual(actual['provider_id'], 'second')
        self.assertEqual(actual['prompt'], draft['prompt'])
        await self.plugin.nai_confirm_command(confirmation)
        self.assertEqual(self.plugin._nai_generate_confirmed.await_count, 1)

    async def test_authored_artist_tags_generate_without_translation(self):
        for text in ('画师串：{artist:chosen} 正面：1girl, blue_eyes 负面：lowres', '{artist:chosen}, 1girl, blue_eyes'):
            await self.plugin.nai_command(self.event('/nai @second ' + text))
        self.assertEqual(self.plugin._nai_generate_confirmed.await_count, 2)
        self.plugin.context.llm_generate.assert_not_awaited()
        self.assertEqual(self.plugin.nai_workflow.pending, {})

    async def test_cancel_and_new_failed_request_invalidate_previous_draft(self):
        await self.plugin.nai_command(self.event('/nai 女孩'))
        await self.plugin.nai_command(self.event('/nai 取消'))
        self.assertFalse(self.plugin.nai_workflow.pending)
        await self.plugin.nai_command(self.event('/nai 女孩'))
        self.plugin.context.llm_generate.return_value.completion_text = 'broken'
        await self.plugin.nai_command(self.event('/nai 新描述'))
        self.assertFalse(self.plugin.nai_workflow.pending)
        self.plugin._nai_generate_confirmed.assert_not_awaited()

    async def test_deleted_provider_invalidates_confirmation_and_blank_token_is_safe(self):
        await self.plugin.nai_command(self.event('/nai @second 女孩'))
        await self.plugin.nai_confirm_command(self.event('/nai确认   '))
        self.plugin._nai_generate_confirmed.assert_not_awaited()
        key = ('qq:GroupMessage:100', 'alice')
        token = self.plugin.nai_workflow.pending[key]['token']
        del self.providers['second']
        await self.plugin.nai_confirm_command(self.event('/nai确认 ' + token))
        self.plugin._nai_generate_confirmed.assert_not_awaited()
