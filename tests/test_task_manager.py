import asyncio
import importlib.util
import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


spec = importlib.util.spec_from_file_location(
    "_task_manager_test", Path(__file__).resolve().parents[1] / "core/task_manager.py"
)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class TaskManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_and_nested_calls_share_one_task(self):
        manager = mod.TaskManager()
        async def nested():
            manager.update("sending", generated=1, sent=1)
            return "done"
        async def operation():
            manager.update("generating")
            return await manager.run("scope", "image", "nested", nested)
        self.assertEqual(await manager.run("scope", "image", "prompt", operation), "done")
        items = manager.list("scope")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "completed")
        self.assertIsNotNone(items[0]["finished_at"])
        self.assertIsNone(manager.current())

    async def test_partial_success_and_delivery_failure_are_distinct(self):
        manager = mod.TaskManager()
        async def partial():
            manager.update(generated=2, sent=1, failed=1)
        await manager.run("scope", "batch", "prompt", partial)
        self.assertEqual(manager.list()[0]["state"], "partial")
        async def failed():
            manager.update(generated=1, failed=1)
        await manager.run("scope", "image", "prompt", failed)
        self.assertEqual(manager.list()[0]["state"], "failed")
        self.assertEqual(manager.list()[0]["generated"], 1)

    async def test_cancellation_checks_ownership_and_runs_cleanup(self):
        manager = mod.TaskManager()
        ready, cleanup = asyncio.Event(), asyncio.Event()
        async def operation():
            ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.set()
        task = asyncio.create_task(manager.run("alice", "image", "", operation))
        await ready.wait()
        task_id = manager.list()[0]["id"]
        with self.assertRaises(ValueError):
            manager.cancel(task_id, scope="bob")
        manager.cancel(task_id, scope="alice")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cleanup.is_set())
        self.assertEqual(manager.list()[0]["state"], "cancelled")
        with self.assertRaises(ValueError):
            manager.cancel(task_id)

    async def test_parallel_task_contexts_are_isolated(self):
        manager = mod.TaskManager()
        async def operation(count):
            await asyncio.sleep(0)
            manager.update(generated=count, sent=count)
        await asyncio.gather(*(
            manager.run(str(n), "image", str(n), lambda n=n: operation(n))
            for n in (1, 2, 3)
        ))
        for n in (1, 2, 3):
            self.assertEqual(manager.list(str(n))[0]["sent"], n)

    async def test_close_cancels_children_and_history_is_bounded(self):
        manager = mod.TaskManager(limit=2)
        async def done():
            manager.update(generated=1, sent=1)
        for _ in range(4):
            await manager.run("s", "image", "", done)
        self.assertEqual(len(manager.list()), 2)
        ready = asyncio.Event()
        async def pending():
            ready.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(manager.run("s", "image", "", pending))
        await ready.wait()
        await manager.close()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_decorator_preserves_signature_and_consumes_only_child_cancel(self):
        class Plugin:
            tasks = mod.TaskManager()
            _capture_history_scope = AsyncMock()
            _get_event_persona = AsyncMock(return_value=types.SimpleNamespace(name="Alice"))
            _history_scope = AsyncMock(return_value="s")

            @mod.managed_task()
            async def work(self, event, prompt: str = ""):
                ready.set()
                await asyncio.Event().wait()

        self.assertIn("prompt", inspect.signature(Plugin.work).parameters)
        self.assertEqual(Plugin.work.__module__, __name__)
        event = types.SimpleNamespace(message_str="", stop_event=lambda: None,
                                      should_call_llm=lambda value: None,
                                      send=AsyncMock(), plain_result=lambda text: text)
        ready = asyncio.Event()
        plugin = Plugin()
        outer = asyncio.create_task(plugin.work(event, "test"))
        await ready.wait()
        plugin.tasks.cancel(plugin.tasks.list()[0]["id"], scope="s")
        await outer
        self.assertFalse(outer.cancelled())
        event.send.assert_awaited_once()
