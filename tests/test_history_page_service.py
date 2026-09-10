import base64
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_history_page_test_core"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "core")]
sys.modules[PACKAGE] = package
ImageHistory = importlib.import_module(f"{PACKAGE}.image_history").ImageHistory
HistoryPageService = importlib.import_module(f"{PACKAGE}.history_page_service").HistoryPageService


class HistoryPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ImageHistory(self.root)
        self.service = HistoryPageService(self.store, self.root)
        self.path = self.root / "source.png"
        Image.new("RGB", (1200, 800), "#267a88").save(self.path)
        self.scope = json.dumps(["group:1", "bot", "alice", "conversation-1"])
        self.row = await self.store.add(self.scope, self.path, {
            "mode": "text", "user_prompt": "100% 海边",
            "provider_tries": [{"pid": "provider", "ok": True, "error": "SECRET"}],
            "conversation_title": "周末旅行",
        })

    async def test_list_exposes_session_time_sequence_but_not_internal_paths_or_errors(self):
        result = await self.service.browse()
        item = result["items"][0]
        self.assertEqual(item["sequence"], 1)
        self.assertEqual(item["conversation"], "conversation-1")
        self.assertEqual(item["conversation_title"], "周末旅行")
        self.assertEqual(item["sender"], "alice")
        self.assertEqual(item["provider"], "provider")
        self.assertTrue(item["available"])
        self.assertGreater(item["created_at"], 0)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    async def test_preview_is_small_and_original_is_unchanged(self):
        thumbnail = await self.service.image(self.row["id"])
        raw = base64.b64decode(thumbnail["image_data"].split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(max(image.size), 640)
        original = await self.service.image(self.row["id"], original=True)
        self.assertEqual(base64.b64decode(original["image_data"].split(",", 1)[1]), self.path.read_bytes())

    async def test_expired_image_and_unknown_id(self):
        Path(self.row["path"]).unlink()
        self.assertFalse((await self.service.browse())["items"][0]["available"])
        with self.assertRaises(FileNotFoundError):
            await self.service.image(self.row["id"])
        with self.assertRaises(FileNotFoundError):
            await self.service.image(999)

    async def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.service.safe_path(str(self.root / "secret.png"))

    async def test_hundred_image_global_cap_pagination_and_old_file_eviction(self):
        for n in range(104):
            await self.store.add(f"scope-{n}", self.path, {"user_prompt": f"picture {n}"})
        result = await self.service.browse()
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["pages"], 5)
        self.assertEqual([r["sequence"] for r in result["items"]], list(range(1, 25)))
        last = await self.service.browse(page=999)
        self.assertEqual(last["page"], 5)
        self.assertEqual([r["sequence"] for r in last["items"]], [97, 98, 99, 100])
        self.assertFalse(Path(self.row["path"]).exists())
        self.assertEqual(len(list(self.store.image_dir.iterdir())), 100)

    async def test_search_is_literal_and_keeps_global_sequence(self):
        await self.store.add("new", self.path, {"user_prompt": "different"})
        result = await self.service.browse(query="%")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["sequence"], 2)
