import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "video_manager_testpkg"
CORE_PACKAGE = f"{PACKAGE}.core"
MODULE_NAME = f"{CORE_PACKAGE}.video_manager"


class _Logger:
    def debug(self, *args, **kwargs):
        return None

    info = warning = error = debug


def _load_module():
    for name in list(sys.modules):
        if name == PACKAGE or name.startswith(f"{PACKAGE}."):
            sys.modules.pop(name, None)

    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = pkg

    core_pkg = types.ModuleType(CORE_PACKAGE)
    core_pkg.__path__ = [str(ROOT / "core")]
    sys.modules[CORE_PACKAGE] = core_pkg

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = _Logger()
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

    task_manager = types.ModuleType(f"{CORE_PACKAGE}.task_manager")
    task_manager.update_task_state = lambda _state: None
    sys.modules[f"{CORE_PACKAGE}.task_manager"] = task_manager

    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        ROOT / "core" / "video_manager.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class VideoManagerSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapper_url_is_checked_before_request(self):
        module = _load_module()
        requested = False

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def stream(self, *args, **kwargs):
                nonlocal requested
                requested = True
                raise AssertionError("request must not start")

        async def _deny(_url, *, policy):
            raise RuntimeError("Disallowed resolved IP address")

        with tempfile.TemporaryDirectory() as tmp:
            manager = module.VideoManager({}, Path(tmp))
            policy = module.URLFetchPolicy()
            with patch.object(module, "ensure_url_allowed", _deny), patch.object(
                module.httpx, "AsyncClient", _Client
            ):
                with self.assertRaisesRegex(RuntimeError, "Disallowed"):
                    await manager._resolve_video_url(
                        "https://example.invalid/result",
                        timeout=httpx.Timeout(5),
                        policy=policy,
                    )

        self.assertFalse(requested)

    async def test_cleanup_keeps_part_and_held_video(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            manager = module.VideoManager(
                {"storage": {"max_cached_videos": 1}},
                Path(tmp),
            )
            held = manager.video_dir / "held.mp4"
            old = manager.video_dir / "old.mp4"
            partial = manager.video_dir / "download.mp4.part"
            held.write_bytes(b"held")
            old.write_bytes(b"old")
            partial.write_bytes(b"partial")
            os.utime(old, (1, 1))
            os.utime(held, (2, 2))

            with manager.hold_video(held):
                await manager.cleanup_old_videos()

            self.assertTrue(held.exists())
            self.assertFalse(old.exists())
            self.assertTrue(partial.exists())


if __name__ == "__main__":
    unittest.main()
