import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_batch_result_delivery import _load_module


class Event:
    def __init__(self, text="", *, sender="alice", origin="group:1", bot="bot1", cid="chat1"):
        self.message_str = text
        self.unified_msg_origin = origin
        self.sender, self.bot, self.cid = sender, bot, cid
        self.sent = []
        self.stopped = False
        self.llm = True
        self.message_obj = types.SimpleNamespace(message_id="")

    def get_sender_id(self):
        return self.sender

    def get_self_id(self):
        return self.bot

    def get_extra(self, name):
        if name == "provider_request":
            return types.SimpleNamespace(conversation=types.SimpleNamespace(cid=self.cid))

    def plain_result(self, text):
        return text

    async def send(self, result):
        self.sent.append(result)

    def stop_event(self):
        self.stopped = True

    def should_call_llm(self, enabled):
        self.llm = enabled


class HistoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = self.mod.GiteeAIImagePlugin(types.SimpleNamespace(), {})
        self.plugin.data_dir = self.root
        self.plugin.image_history = self.mod.ImageHistory(self.root)
        self.plugin.session_personas = self.mod.SessionPersonas(self.root)
        self.images = self.root / "images"
        self.images.mkdir()
        self.source = self.images / "source.png"
        self.source.write_bytes(b"source")
        self.result = self.images / "result.png"
        self.result.write_bytes(b"result")
        self.event = Event()
        await self.plugin._record_image_history(self.event, self.source, {"user_prompt": "original"})
        self.row = await self.plugin._get_history_image(self.event)
        for name in ("mark_processing", "mark_success", "mark_failed"):
            setattr(self.mod, name, AsyncMock())
        self.mod.get_images_from_event = AsyncMock(return_value=[])
        self.plugin._image_segs_to_bytes = AsyncMock(return_value=[])
        self.plugin._begin_user_job = AsyncMock(return_value=True)
        self.plugin._end_user_job = AsyncMock()
        self.plugin.debouncer = types.SimpleNamespace(
            hit=lambda *a: False, llm_tool_is_duplicate=lambda *a: False,
        )
        self.plugin.persona_mgr = types.SimpleNamespace(active=types.SimpleNamespace(name="test"))
        self.plugin.edit = types.SimpleNamespace(
            get_preset_names=lambda: [], presets={},
            edit=AsyncMock(return_value=(self.result, [])),
        )
        self.plugin._send_image_with_fallback = AsyncMock(return_value=True)

    async def test_scope_separates_sender_group_bot_and_conversation(self):
        for kw in (
            {"sender": "bob"}, {"origin": "group:2"},
            {"bot": "bot2"}, {"cid": "chat2"},
        ):
            with self.assertRaises(ValueError):
                await self.plugin._get_history_image(Event(**kw), str(self.row["id"]))

    async def test_resend_uses_history_without_calling_backend(self):
        self.event.message_str = f"/重发图片 #{self.row['id']}"
        await self.plugin.resend_last_image(self.event)
        self.plugin._send_image_with_fallback.assert_awaited_once_with(self.event, Path(self.row["path"]))
        self.plugin.edit.edit.assert_not_awaited()
        self.assertFalse(self.event.llm)

    async def test_continue_edits_selected_image_and_records_parent(self):
        self.event.message_str = f"/继续改图 #{self.row['id']}\t换背景"
        await self.plugin.continue_image_command(self.event)
        self.assertEqual(self.plugin.edit.edit.await_args.kwargs["images"], [b"source"])
        latest = await self.plugin._get_history_image(self.event)
        self.assertEqual(latest["metadata"]["parent_image_id"], self.row["id"])
        self.plugin._end_user_job.assert_awaited_once()
        self.assertFalse(self.event.llm)

    async def test_current_image_wins_even_with_invalid_history_id(self):
        self.mod.get_images_from_event.return_value = [object()]
        self.plugin._image_segs_to_bytes.return_value = [b"current"]
        self.event.message_str = "/继续改图 #999999 换背景"
        await self.plugin.continue_image_command(self.event)
        self.assertEqual(self.plugin.edit.edit.await_args.kwargs["images"], [b"current"])

    async def test_broken_current_image_does_not_fall_back_to_history(self):
        self.mod.get_images_from_event.return_value = [object()]
        self.event.message_str = "/继续改图 换背景"
        await self.plugin.continue_image_command(self.event)
        self.plugin.edit.edit.assert_not_awaited()

    async def test_expired_latest_does_not_select_an_older_image(self):
        await self.plugin._record_image_history(self.event, self.result)
        Path((await self.plugin._get_history_image(self.event))["path"]).unlink()
        self.event.message_str = "/继续改图 换背景"
        await self.plugin.continue_image_command(self.event)
        self.plugin.edit.edit.assert_not_awaited()
        self.assertTrue(any("过期" in text for text in self.event.sent))

    async def test_failed_delivery_keeps_generated_image_for_resend(self):
        self.plugin._send_image_with_fallback.return_value = self.mod.SendImageResult(
            ok=False, reason="send_failed",
        )
        self.event.message_str = "/继续改图 换背景"
        await self.plugin.continue_image_command(self.event)
        latest = await self.plugin._get_history_image(self.event)
        self.assertEqual(Path(latest["path"]).read_bytes(), b"result")

    async def test_listing_includes_stable_ids_and_expired_status(self):
        Path(self.row["path"]).unlink()
        await self.plugin.image_history_command(self.event)
        self.assertIn(f"#{self.row['id']}", self.event.sent[0])
        self.assertIn("已过期", self.event.sent[0])
        self.assertFalse(self.event.llm)

    async def test_stored_external_path_is_rejected(self):
        external = self.root / "secret.png"
        external.write_bytes(b"secret")
        await self.plugin._record_image_history(self.event, external)
        self.assertEqual((await self.plugin._get_history_image(self.event))["id"], self.row["id"])

    async def test_generation_scope_stays_pinned_when_active_chat_changes(self):
        self.event.cid = "new-chat"
        await self.plugin._record_image_history(self.event, self.result)
        self.assertEqual(Path((await self.plugin._get_history_image(self.event))["path"]).read_bytes(), b"result")
        with self.assertRaises(ValueError):
            await self.plugin._get_history_image(Event(cid="new-chat"))

    async def test_invalid_id_never_defaults_to_latest(self):
        for selector in ("-1", "abc", "0", "#", "##12", "999999999999999999999999999"):
            with self.assertRaises(ValueError):
                await self.plugin._get_history_image(self.event, selector)

    async def test_llm_previous_image_routes_to_edit(self):
        self.plugin._resolve_aiimg_backend_and_mode = AsyncMock(return_value=(None, "auto"))
        self.plugin._parse_provider_override_prefix = lambda text: (None, text)
        self.plugin._finalize_llm_tool_image = AsyncMock(return_value="done")
        self.event.message_str = "把上一张背景换掉"
        result = await self.plugin.aiimg_generate(self.event, self.event.message_str)
        self.assertEqual(result, "done")
        self.assertEqual(self.plugin.edit.edit.await_args.kwargs["images"], [b"source"])
        meta = self.plugin._finalize_llm_tool_image.await_args.kwargs["task_meta"]
        self.assertEqual(meta["parent_image_id"], self.row["id"])

    async def test_history_pages_api_pagination_and_invalid_parameters(self):
        from quart import Quart
        app = Quart(__name__)
        app.add_url_rule("/history", view_func=self.plugin._pages_get_history)
        app.add_url_rule("/image", view_func=self.plugin._pages_get_history_image)
        async with app.test_client() as client:
            response = await client.get("/history?page=1")
            result = await response.get_json()
            self.assertTrue(result["success"])
            self.assertEqual(result["items"][0]["conversation"], "chat1")
            self.assertEqual(result["items"][0]["sequence"], 1)
            self.assertEqual((await client.get("/history?page=oops")).status_code, 400)
            self.assertEqual((await client.get("/image?id=-1")).status_code, 400)
            self.assertEqual((await client.get("/image?id=999999")).status_code, 404)
