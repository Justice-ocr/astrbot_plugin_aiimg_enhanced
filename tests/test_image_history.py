import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("image_history_store", ROOT / "core/image_history.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ImageHistory = module.ImageHistory


class ImageHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = ImageHistory(self.root, limit=3)
        for name in ("a", "b", "c", "d", "x", "same", "missing"):
            (self.root / f"{name}.png").write_bytes(name.encode())

    async def test_persistence_and_scope_isolation(self):
        row = await self.store.add("alice:group1", self.root / "a.png", {"user_prompt": "first"})
        reopened = ImageHistory(self.root)
        self.assertEqual((await reopened.get("alice:group1", row["id"]))["metadata"]["user_prompt"], "first")
        self.assertIsNone(await reopened.get("bob:group1", row["id"]))
        self.assertIsNone(await reopened.get("alice:group2", row["id"]))

    async def test_resend_does_not_change_latest_or_metadata(self):
        first = await self.store.add("scope", self.root / "a.png", {"user_prompt": "original"})
        second = await self.store.add("scope", self.root / "b.png", {})
        replay = await self.store.add("scope", self.root / "a.png", {"user_prompt": "resend"})
        self.assertEqual(replay, first)
        self.assertEqual((await self.store.get("scope"))["id"], second["id"])

    async def test_retention_is_global_and_does_not_reuse_ids(self):
        first = await self.store.add("scope", self.root / "a.png", {})
        other = await self.store.add("other", self.root / "x.png", {})
        for name in ("b", "c", "d"):
            await self.store.add("scope", self.root / f"{name}.png", {})
        rows = await self.store.list("scope")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["id"] > first["id"] for row in rows))
        self.assertIsNone(await self.store.get("scope", first["id"]))
        self.assertIsNone(await self.store.get("other", other["id"]))
        self.assertFalse(Path(first["path"]).exists())
        self.assertFalse(Path(other["path"]).exists())
        self.assertEqual(len(list(self.store.image_dir.iterdir())), 3)

    async def test_concurrent_writes_and_duplicate_paths(self):
        rows = await asyncio.gather(*(
            self.store.add("scope", self.root / "same.png", {"value": n})
            for n in range(12)
        ))
        self.assertEqual(len({row["id"] for row in rows}), 1)
        self.assertEqual(len(await self.store.list("scope")), 1)

    async def test_expired_files_keep_metadata(self):
        row = await self.store.add("scope", self.root / "missing.png", {})
        Path(row["path"]).unlink()
        self.assertEqual((await self.store.get("scope"))["id"], row["id"])

    async def test_archive_survives_normal_cache_cleanup(self):
        row = await self.store.add("scope", self.root / "a.png", {})
        (self.root / "a.png").unlink()
        self.assertEqual(Path(row["path"]).read_bytes(), b"a")

    async def test_browse_numbers_newest_first_and_escapes_search(self):
        first = await self.store.add("scope", self.root / "a.png", {"user_prompt": "100%"})
        second = await self.store.add("other", self.root / "b.png", {"user_prompt": "100 apples"})
        result = await self.store.browse()
        self.assertEqual([(r["id"], r["sequence"]) for r in result["items"]],
                         [(second["id"], 1), (first["id"], 2)])
        filtered = await self.store.browse(query="%")
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["sequence"], 2)

    async def test_limit_is_hard_capped_at_100(self):
        self.assertEqual(ImageHistory(self.root, limit=1000).limit, 100)
