import asyncio
import importlib
import types
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from test_pages_downloads import setup, PACKAGE


@pytest.mark.asyncio
async def test_conversion_endpoint_uses_full_umo_and_never_submits_image(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    provider = {'id': 'nai', '__template_key': 'nai_openai_images', 'nai_artist': '{artist:test}'}
    plugin.registry = types.SimpleNamespace(get=lambda pid: provider if pid == 'nai' else None)
    plugin.context = types.SimpleNamespace(get_current_chat_provider_id=AsyncMock(return_value='chat'),
        llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text='{"tags":"1girl, blue_eyes"}')))
    plugin.studio_generation = types.SimpleNamespace(submit=AsyncMock())
    client.app.add_url_rule('/nai', view_func=plugin._pages_prepare_nai_prompt, methods=['POST'])
    response = await client.post('/nai', json={'scope': scope, 'provider_id': 'nai', 'prompt': '女孩'})
    assert response.status_code == 200
    result = await response.get_json()
    assert result['draft']['artist'] == '{artist:test}'
    assert result['draft']['tags'] == '1girl, blue_eyes'
    plugin.context.get_current_chat_provider_id.assert_awaited_once_with(umo='group')
    plugin.studio_generation.submit.assert_not_awaited()
    denied = await client.post('/nai', json={'scope': '["fake","fake","fake","fake"]', 'provider_id': 'nai', 'prompt': '女孩'})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_reviewed_studio_request_keeps_exact_prompt_negative_and_umo(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    api = types.ModuleType('astrbot.api')
    import logging
    api.logger = logging.getLogger(__name__)
    registry_module = types.ModuleType(f'{PACKAGE}.core.provider_registry')
    @asynccontextmanager
    async def lease(registry, backend):
        yield backend
    registry_module.leased_backend = lease
    with patch.dict(sys.modules, {'astrbot': types.ModuleType('astrbot'), 'astrbot.api': api, f'{PACKAGE}.core.provider_registry': registry_module}):
        service_class = importlib.import_module(f'{PACKAGE}.core.studio.generation_service').StudioGenerationService
    task_class = importlib.import_module(f'{PACKAGE}.core.task_manager').TaskManager
    plugin.tasks = task_class()
    provider = {'id': 'nai', '__template_key': 'nai_openai_images', 'model': 'nai-model', 'supports_edit': False}
    plugin.registry = types.SimpleNamespace(get=lambda pid: provider if pid == 'nai' else None)
    path = tmp_path / 'image.png'
    path.write_bytes(raw)
    plugin.draw = types.SimpleNamespace(generate=AsyncMock(return_value=(path, [{'pid': 'nai', 'ok': True}])))
    service = service_class(plugin)
    payload = {'scope': scope, 'kind': 'image', 'mode': 'draw', 'provider_id': 'nai',
               'idempotency_key': 'nai-reviewed', 'nai_workbench': True, 'nai_reviewed': True,
               'nai_artist': '{{artist:chosen}}', 'nai_prefix': 'masterpiece', 'nai_tags': '1girl, {blue_eyes}',
               'negative_prompt': 'lowres, bad_hands', 'prompt': 'masterpiece, {{artist:chosen}}, 1girl, {blue_eyes}'}
    try:
        job, created = await service.submit(payload)
        await asyncio.gather(*list(service._workers.values()))
        assert created
        result = await service.get(job['id'])
        assert result['state'] == 'completed', result
        kwargs = plugin.draw.generate.call_args.kwargs
        assert plugin.draw.generate.call_args.args[0] == payload['prompt']
        assert kwargs['nai_prepared'] is True
        assert kwargs['negative_prompt'] == 'lowres, bad_hands'
        assert kwargs['session_id'] == 'group'
        assert (await plugin.image_history.browse())['items'][0]['metadata']['nai_artist'] == '{{artist:chosen}}'
        plugin.draw.generate.reset_mock()
        for override in ({'nai_reviewed': False}, {'prompt': 'changed'}, {'provider_id': 'missing'}):
            with pytest.raises(ValueError):
                await service.submit({**payload, **override, 'idempotency_key': 'invalid'})
        plugin.draw.generate.assert_not_awaited()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_history_and_asset_api_expose_full_umo_not_conversation_uuid(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    path = tmp_path / 'generated.png'
    path.write_bytes(raw)
    await plugin.image_history.add(scope, path, {'user_prompt': 'test'})
    client.app.add_url_rule('/assets', view_func=plugin._pages_get_assets)
    client.app.add_url_rule('/history', view_func=plugin._pages_get_history)
    result = await (await client.get('/history')).get_json()
    assert result['items'][0]['umo'] == 'group'
    assert result['items'][0]['conversation'] == 'session'
    assets = await (await client.get('/assets', query_string={'scope': scope})).get_json()
    history = next(item for item in assets['items'] if item.get('source') == 'history')
    assert history['umo'] == 'group'
    assert history['conversation'] == 'session'


@pytest.mark.asyncio
async def test_workbench_conversion_does_not_inherit_hidden_legacy_defaults(tmp_path):
    plugin, client, scope, _, _ = await setup(tmp_path)
    provider = {'id': 'nai', '__template_key': 'nai_openai_images', 'nai_artist': 'old_artist',
                'nai_prompt_prefix': 'old_prefix', 'negative_prompt': 'old_negative', 'nai_llm_provider_id': 'old_llm'}
    plugin.registry = types.SimpleNamespace(get=lambda pid: provider)
    plugin.context = types.SimpleNamespace(get_current_chat_provider_id=AsyncMock(return_value='session-llm'),
        llm_generate=AsyncMock(return_value=types.SimpleNamespace(completion_text='{"tags":"1girl, blue_eyes"}')))
    client.app.add_url_rule('/nai', view_func=plugin._pages_prepare_nai_prompt, methods=['POST'])
    result = await client.post('/nai', json={'scope': scope, 'provider_id': 'nai', 'prompt': '女孩', 'workbench': True})
    assert result.status_code == 200
    draft = (await result.get_json())['draft']
    assert draft['artist'] == draft['prefix'] == draft['negative'] == ''
    assert draft['tags'] == '1girl, blue_eyes'
    plugin.context.get_current_chat_provider_id.assert_awaited_once_with(umo='group')
    assert plugin.context.llm_generate.await_args.kwargs['chat_provider_id'] == 'session-llm'
    assert provider['nai_artist'] == 'old_artist'


@pytest.mark.asyncio
async def test_nai_presets_persist_exact_fields_and_validate_scope_revision(tmp_path):
    plugin, client, scope, _, _ = await setup(tmp_path)
    client.app.add_url_rule('/preset', view_func=plugin._pages_save_project, methods=['POST'])
    client.app.add_url_rule('/presets', view_func=plugin._pages_get_projects)
    document = {'version': 1, 'artist': '{{artist:foo}}, [artist:bar]', 'tags': '1girl, {{{blue_eyes}}}, 1.2::long_hair::',
                'negative': 'lowres, {bad_hands}', 'prefix': '{masterpiece}, best_quality', 'llm_provider_id': 'text-llm', 'size': '832x1216'}
    payload = {'scope': scope, 'kind': 'nai_preset', 'name': '画师预设 A', 'document': document}
    response = await client.post('/preset', json=payload)
    assert response.status_code == 200
    item = (await response.get_json())['item']
    response = await client.get('/presets', query_string={'scope': scope, 'kind': 'nai_preset'})
    assert (await response.get_json())['items'][0]['document'] == document
    updated = await client.post('/preset', json={**payload, 'id': item['id'], 'revision': item['revision'], 'name': '改名'})
    assert updated.status_code == 200
    conflict = await client.post('/preset', json={**payload, 'id': item['id'], 'revision': item['revision']})
    assert conflict.status_code == 409
    denied = await client.post('/preset', json={**payload, 'scope': '["fake","fake","fake","fake"]'})
    assert denied.status_code == 403
    assert (await plugin.studio_projects.get(item['id']))['document'] == document


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('artist', ['not-a-string']), ('prefix', 'x' * 8001), ('api_key', 'forbidden'), ('version', 99)])
async def test_nai_presets_reject_malformed_or_secret_fields(tmp_path, field, value):
    plugin, client, scope, _, _ = await setup(tmp_path)
    client.app.add_url_rule('/preset', view_func=plugin._pages_save_project, methods=['POST'])
    response = await client.post('/preset', json={'scope': scope, 'kind': 'nai_preset', 'name': 'invalid',
        'document': {'version': 1, field: value}})
    assert response.status_code == 400
    assert await plugin.studio_projects.list(scope=scope, kind='nai_preset') == []
