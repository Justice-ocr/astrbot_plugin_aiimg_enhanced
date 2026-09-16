import asyncio
import base64
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_batch_result_delivery import _load_module
from test_image_history_commands import Event


class ManagedTaskIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = self.mod.GiteeAIImagePlugin(types.SimpleNamespace(), {})
        self.plugin.data_dir = self.root
        self.plugin.session_personas = self.mod.SessionPersonas(self.root)
        self.plugin.image_history = self.mod.ImageHistory(self.root)
        self.plugin.persona_mgr = self.mod.PersonaManager({}, str(self.root))
        self.plugin._image_inflight = {}
        self.plugin._video_inflight = {}
        self.plugin._concurrency_lock = asyncio.Lock()
        self.plugin.debouncer = types.SimpleNamespace(
            hit=lambda *args: False, llm_tool_is_duplicate=lambda *args: False,
        )
        self.plugin.registry = types.SimpleNamespace(provider_ids=lambda: [])
        self.plugin._parse_provider_override_prefix = lambda value: (None, value)
        self.plugin._llm_tool_text_result = lambda text: text
        self.mod.mark_processing = AsyncMock()
        self.mod.mark_success = AsyncMock()
        self.mod.mark_failed = AsyncMock()
        self.mod.get_images_from_event = AsyncMock(return_value=[])
        self.event = Event("modify previous image")

    async def test_cancel_during_llm_classification_releases_concurrency(self):
        ready = asyncio.Event()
        async def classify(*args):
            ready.set()
            await asyncio.Event().wait()
        self.plugin._resolve_aiimg_backend_and_mode = classify
        outer = asyncio.create_task(self.plugin.aiimg_generate(self.event, "draw"))
        await ready.wait()
        self.assertEqual(self.plugin._image_inflight, {"alice": 1})
        row = self.plugin.tasks.list()[0]
        self.plugin.tasks.cancel(row["id"], scope=await self.plugin._history_scope(self.event))
        await outer
        self.assertFalse(outer.cancelled())
        self.assertEqual(self.plugin._image_inflight, {})
        self.assertEqual(self.plugin.tasks.list()[0]["state"], "cancelled")
        self.assertFalse(self.event.llm)

    async def test_cancel_video_polling_releases_video_concurrency(self):
        ready = asyncio.Event()
        async def generate(**kwargs):
            ready.set()
            await asyncio.Event().wait()
        self.plugin.registry = types.SimpleNamespace(get_video_backend=lambda _: types.SimpleNamespace(generate_video_url=generate))
        self.plugin._get_video_chain = lambda: ["video"]
        await self.plugin._video_begin("alice")
        outer = asyncio.create_task(self.plugin._async_generate_video(self.event, "video", "alice"))
        await ready.wait()
        self.plugin.tasks.cancel(self.plugin.tasks.list()[0]["id"])
        await outer
        self.assertEqual(self.plugin._video_inflight, {})
        self.assertEqual(self.plugin.tasks.list()[0]["state"], "cancelled")

    async def test_agnes_video_receives_multiple_reference_images(self):
        class ImageSegment:
            def __init__(self, url, payload):
                self.url = url
                self.payload = payload

            async def convert_to_base64(self):
                return base64.b64encode(self.payload).decode("ascii")

        generate = AsyncMock(return_value="https://cdn.example.com/video.mp4")
        backend = types.SimpleNamespace(
            supports_multiple_images=True,
            generate_video_url=generate,
        )
        self.plugin.registry = types.SimpleNamespace(get_video_backend=lambda _: backend)
        self.plugin._get_video_chain = lambda: ["agnes"]
        self.plugin._send_video_result = AsyncMock()
        self.mod.decode_base64_image_payload = lambda value: base64.b64decode(value)
        self.mod.get_images_from_event = AsyncMock(
            return_value=[
                ImageSegment("https://cdn.example.com/one.png", b"\x89PNG\r\n\x1a\none"),
                ImageSegment("https://cdn.example.com/two.png", b"\x89PNG\r\n\x1a\ntwo"),
            ]
        )

        await self.plugin._async_generate_video(self.event, "animate", "alice")

        kwargs = generate.await_args.kwargs
        self.assertEqual(
            kwargs["image_bytes_list"],
            [b"\x89PNG\r\n\x1a\none", b"\x89PNG\r\n\x1a\ntwo"],
        )
        self.assertEqual(
            kwargs["image_urls"],
            ["https://cdn.example.com/one.png", "https://cdn.example.com/two.png"],
        )
        self.plugin._send_video_result.assert_awaited_once_with(
            self.event, "https://cdn.example.com/video.mp4"
        )

    async def test_successful_command_records_task_and_history(self):
        image_dir = self.root / "images"
        image_dir.mkdir()
        image = image_dir / "new.png"
        image.write_bytes(b"image")
        self.plugin.draw = types.SimpleNamespace(generate=AsyncMock(return_value=(image, [])))
        self.plugin._send_image_impl = AsyncMock(return_value=self.mod.SendImageResult(ok=True))
        event = Event("/aiimg test image")
        await self.plugin.generate_image_command(event, "test image")
        task = self.plugin.tasks.list()[0]
        self.assertEqual(task["state"], "completed")
        self.assertEqual((task["generated"], task["sent"]), (1, 1))
        self.assertEqual(self.plugin._image_inflight, {})
        self.assertTrue((await self.plugin.image_history.browse())["items"])

    async def test_web_cancel_and_task_list(self):
        from quart import Quart
        app = Quart(__name__)
        app.add_url_rule("/tasks", view_func=self.plugin._pages_get_tasks)
        app.add_url_rule("/cancel", view_func=self.plugin._pages_cancel_task, methods=["POST"])
        ready = asyncio.Event()
        async def operation():
            ready.set()
            await asyncio.Event().wait()
        scope = await self.plugin._history_scope(self.event)
        outer = asyncio.create_task(self.plugin.tasks.run(scope, "image", "prompt", operation))
        await ready.wait()
        async with app.test_client() as client:
            result = await (await client.get("/tasks")).get_json()
            self.assertEqual(result["items"][0]["sender"], "alice")
            response = await client.post("/cancel", json={"id": result["items"][0]["id"]})
            self.assertTrue((await response.get_json())["success"])
        with self.assertRaises(asyncio.CancelledError):
            await outer
        self.assertEqual(self.plugin.tasks.list()[0]["state"], "cancelled")

    async def test_shutdown_cancels_workers_without_user_cancel_message(self):
        ready = asyncio.Event()
        async def classify(*args):
            ready.set()
            await asyncio.Event().wait()
        self.plugin._resolve_aiimg_backend_and_mode = classify
        outer = asyncio.create_task(self.plugin.aiimg_generate(self.event, "draw"))
        await ready.wait()
        await self.plugin.tasks.close()
        with self.assertRaises(asyncio.CancelledError):
            await outer
        self.assertEqual(self.plugin._image_inflight, {})
        self.assertFalse(any("本地取消" in item for item in self.event.sent))
