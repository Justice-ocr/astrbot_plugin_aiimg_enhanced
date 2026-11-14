import asyncio
import importlib
import types
import sys
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from test_pages_downloads import setup, PACKAGE
from test_gpt_image_gif_backend import animated_gif


def load_service():
    api = types.ModuleType('astrbot.api')
    api.logger = logging.getLogger(__name__)
    registry = types.ModuleType(f'{PACKAGE}.core.provider_registry')
    @asynccontextmanager
    async def lease(*args):
        yield None
    registry.leased_backend = lease
    with patch.dict(sys.modules, {'astrbot': types.ModuleType('astrbot'), 'astrbot.api':api, f'{PACKAGE}.core.provider_registry':registry}):
        backend = importlib.import_module(f'{PACKAGE}.core.gpt_image_gif_backend')
        network = importlib.import_module(f'{PACKAGE}.core.net_safety')
        service = importlib.import_module(f'{PACKAGE}.core.studio.generation_service')
    sys.modules[f'{PACKAGE}.core.gpt_image_gif_backend'] = backend
    sys.modules[f'{PACKAGE}.core.net_safety'] = network
    return service


@pytest.mark.asyncio
async def test_gif_job_archives_animation_deduplicates_and_keeps_original_key_for_resume(tmp_path):
    plugin, client, scope, asset, raw = await setup(tmp_path)
    module = load_service()
    backend_mod = importlib.import_module(f'{PACKAGE}.core.gpt_image_gif_backend')
    tasks_cls = importlib.import_module(f'{PACKAGE}.core.task_manager').TaskManager
    provider = {'id':'gif','base_url':'https://fixture.test/v1','api_keys':['PRIVATE-FIXTURE-KEY']}
    plugin.config={'providers':[provider]}
    plugin.registry=types.SimpleNamespace(get=lambda pid:provider if pid=='gif' else None)
    plugin.tasks=tasks_cls()
    service=module.StudioGenerationService(plugin)
    payload=dict(scope=scope,kind='gif',mode='gif',prompt='A cat waves, seamless loop',idempotency_key='gif-one',provider_id='gif',gif_protocol='apimart',gif_model='gpt-image-2.6-flare',reference_asset_ids=[asset['asset_id']])
    calls=[]
    async def generate(backend,request,references,accepted):
        calls.append(request)
        assert references==[raw]
        await accepted('upstream-task',backend.fingerprint('PRIVATE-FIXTURE-KEY','apimart'))
        raise RuntimeError('本地等待结束，请继续查询原任务')
    with patch.object(backend_mod.GptImageGifBackend,'generate',generate):
        first,created=await service.submit(payload)
        again,created_again=await service.submit(payload)
        assert created and not created_again and first['id']==again['id']
        await asyncio.gather(*list(service._workers.values()))
    interrupted=await service.get(first['id'])
    assert interrupted['state']=='interrupted'
    assert interrupted['upstream_task_id']=='upstream-task'
    assert 'PRIVATE-FIXTURE-KEY' not in str(interrupted)
    assert len(calls)==1
    async def resume(backend,request,task_id,fingerprint):
        assert task_id=='upstream-task'
        assert fingerprint==backend.fingerprint('PRIVATE-FIXTURE-KEY','apimart')
        return animated_gif()
    with patch.object(backend_mod.GptImageGifBackend,'resume',resume), patch.object(backend_mod.GptImageGifBackend,'generate',new=AsyncMock()) as new_submission:
        await service.resume(first['id'])
        await asyncio.gather(*list(service._workers.values()))
        new_submission.assert_not_awaited()
    done=await service.get(first['id'])
    assert done['state']=='completed'
    saved=await plugin.studio_assets.get(done['result']['asset_id'])
    path=await plugin.studio_assets.content_path(saved['asset_id'])
    assert path.read_bytes()==animated_gif()
    assert saved['filename'].endswith('.gif')
    assert saved['metadata']['mime_type']=='image/gif'
    assert plugin.tasks.list()[0]['state']=='completed'
    await service.close()


@pytest.mark.asyncio
async def test_gif_reference_scope_checked_before_upstream_submission(tmp_path):
    plugin,client,scope,asset,raw=await setup(tmp_path)
    mod=load_service()
    provider={'id':'gif','base_url':'https://fixture.test/v1','api_keys':['fixture']}
    plugin.config={'providers':[provider]}
    plugin.registry=types.SimpleNamespace(get=lambda pid:provider)
    plugin.tasks=importlib.import_module(f'{PACKAGE}.core.task_manager').TaskManager()
    service=mod.StudioGenerationService(plugin)
    payload=dict(scope=scope,kind='gif',prompt='loop',provider_id='gif',idempotency_key='scope-invalid',gif_protocol='openai',gif_model='gpt-image-2.6-flare',reference_asset_ids=['missing'])
    with pytest.raises(ValueError,match='参考素材'):
        await service.submit(payload)
    assert await service.list(scope)==[]
