import asyncio
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from test_batch_result_delivery import _load_module
from test_image_history_commands import Event


class SessionPersonaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.refs = {}
        for name in ("face", "shirt", "pose", "scene"):
            path = self.root / f"{name}.png"
            path.write_bytes(name.encode())
            self.refs[name] = str(path)
        self.plugin = self.mod.GiteeAIImagePlugin(types.SimpleNamespace(), {
            "persona_config": {"active_persona_id": "a", "profiles": [
                {"id": "a", "persona_name": "Alice", "persona_base_prompt": "blue eyes",
                 "persona_ref_image": list(self.refs.values()),
                 "persona_ref_roles": {
                     self.refs["face"]: "identity", self.refs["shirt"]: "clothing",
                     self.refs["pose"]: "pose", self.refs["scene"]: "scene",
                 }},
                {"id": "b", "persona_name": "Bea", "persona_base_prompt": "green eyes",
                 "persona_ref_image": [self.refs["face"]]},
            ]},
            "features": {"edit": {"enabled": True}, "selfie": {"enabled": True}},
        })
        self.plugin.data_dir = self.root
        self.plugin.session_personas = self.mod.SessionPersonas(self.root)
        self.plugin.persona_mgr = self.mod.PersonaManager(self.plugin.config, str(self.root))
        self.plugin.edit = types.SimpleNamespace(edit=AsyncMock(return_value=(self.root / "output.png", [])))
        self.mod.get_images_from_event = AsyncMock(return_value=[])
        self.plugin._image_segs_to_bytes = AsyncMock(return_value=[])

    async def test_session_selection_persists_and_is_shared_within_group_only(self):
        event = Event()
        await self.plugin.session_personas.set(await self.plugin._persona_scope(event), "b")
        self.plugin.session_personas = self.mod.SessionPersonas(self.root)
        self.assertEqual((await self.plugin._get_event_persona(Event(sender="bob"))).id, "b")
        for kwargs in ({"origin": "group:2"}, {"bot": "other"}, {"cid": "new"}):
            self.assertEqual((await self.plugin._get_event_persona(Event(**kwargs))).id, "a")
        self.assertEqual(self.plugin.persona_mgr.active.id, "a")

    async def test_snapshot_survives_switch_and_profile_reload(self):
        event = Event()
        snapshot = await self.plugin._get_event_persona(event, snapshot=True)
        await self.plugin.session_personas.set(await self.plugin._persona_scope(event), "b")
        self.plugin.persona_mgr.active.base_prompt = "changed"
        self.assertEqual((await self.plugin._get_event_persona(event)).id, "a")
        self.assertEqual(snapshot.base_prompt, "blue eyes")
        self.assertEqual((await self.plugin._get_event_persona(Event())).id, "b")

    async def test_missing_profile_and_reset_use_global_default(self):
        scope = await self.plugin._persona_scope(Event())
        await self.plugin.session_personas.set(scope, "deleted")
        self.assertEqual((await self.plugin._get_event_persona(Event())).id, "a")
        await self.plugin.session_personas.set(scope, "b")
        event = Event("/切换人设 默认")
        messages = [value async for value in self.plugin.persona_switch_command(event)]
        self.assertTrue(messages)
        self.assertEqual(await self.plugin.session_personas.get(scope), "")

    async def test_command_does_not_change_global_default(self):
        event = Event("/切换人设 b")
        messages = [value async for value in self.plugin.persona_switch_command(event)]
        self.assertIn("Bea", messages[0])
        self.assertEqual(self.plugin.persona_mgr.active.id, "a")
        self.assertEqual((await self.plugin._get_event_persona(Event())).id, "b")

    async def test_roles_survive_serialization_and_legacy_refs_default_to_identity(self):
        config = {"persona_config": self.plugin.persona_mgr.to_config_dict()}
        rebuilt = self.mod.PersonaManager(config, str(self.root))
        self.assertEqual(rebuilt.active.ref_roles[self.refs["shirt"]], "clothing")
        self.assertEqual(rebuilt.get_persona("b").ref_roles[self.refs["face"]], "identity")

    async def test_missing_ref_does_not_shift_role_labels(self):
        Path(self.refs["shirt"]).unlink()
        _, meta = await self.plugin._generate_selfie_image_with_meta(Event(), "portrait", None)
        kwargs = self.plugin.edit.edit.await_args.kwargs
        self.assertEqual(kwargs["images"], [b"face", b"pose", b"scene"])
        self.assertIn("第2张：姿势", kwargs["prompt"])
        self.assertIn("第3张：场景", kwargs["prompt"])
        self.assertEqual(meta["reference_roles"], ["identity", "pose", "scene"])
        self.assertEqual(meta["persona_id"], "a")

    async def test_no_readable_identity_prevents_upstream_request(self):
        Path(self.refs["face"]).unlink()
        with self.assertRaisesRegex(RuntimeError, "身份"):
            await self.plugin._generate_selfie_image_with_meta(Event(), "portrait", None)
        self.plugin.edit.edit.assert_not_awaited()

    async def test_extra_message_refs_are_labeled_context_not_identity(self):
        self.mod.get_images_from_event.return_value = [object()]
        self.plugin._image_segs_to_bytes.return_value = [b"user"]
        await self.plugin._generate_selfie_image_with_meta(Event(), "portrait", None)
        kwargs = self.plugin.edit.edit.await_args.kwargs
        self.assertEqual(kwargs["images"][-1], b"user")
        self.assertIn("第5张：用户补充素材", kwargs["prompt"])

    async def test_parallel_sessions_use_distinct_personas(self):
        await self.plugin.session_personas.set(await self.plugin._persona_scope(Event(cid="b")), "b")
        await asyncio.gather(
            self.plugin._generate_selfie_image_with_meta(Event(cid="a"), "first", None),
            self.plugin._generate_selfie_image_with_meta(Event(cid="b"), "second", None),
        )
        prompts = [call.kwargs["prompt"] for call in self.plugin.edit.edit.await_args_list]
        self.assertTrue(any("blue eyes" in prompt and "first" in prompt for prompt in prompts))
        self.assertTrue(any("green eyes" in prompt and "second" in prompt for prompt in prompts))

    async def test_web_session_binding_validation(self):
        from quart import Quart
        app = Quart(__name__)
        app.add_url_rule("/select", view_func=self.plugin._pages_set_session_persona, methods=["POST"])
        scope = await self.plugin._persona_scope(Event())
        async with app.test_client() as client:
            ok = await client.post("/select", json={"scope": scope, "persona_id": "b"})
            self.assertTrue((await ok.get_json())["success"])
            self.assertEqual(await self.plugin.session_personas.get(scope), "b")
            bad = await client.post("/select", json={"scope": scope, "persona_id": "missing"})
            self.assertEqual(bad.status_code, 400)
            bad = await client.post("/select", json={"scope": "null", "persona_id": ""})
            self.assertEqual(bad.status_code, 400)
