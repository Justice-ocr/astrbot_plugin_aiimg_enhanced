import json
import subprocess
import asyncio
import pytest
from core.studio.asset_store import StudioAssetStore
from pathlib import Path

from core.studio.capability_catalog import build_provider_capability

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'agnes_video', 'openai_video', 'custom_video', 'xpivot_video'}
RETIRED = {'xai_video', 'minimax_h3_video', 'grok_video', 'grok2api_video', 'flow2api_video'}


def test_video_template_choices_and_schema_are_identical():
    definitions = json.loads((ROOT / 'web/src/app/video_templates.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / '_conf_schema.json').read_text(encoding='utf-8'))['providers']['templates']
    assert set(definitions) == EXPECTED
    assert not RETIRED.intersection(schema)
    script = "import {PROVIDER_TEMPLATES,VIDEO_PROVIDER_TYPES} from './web/src/app/provider_catalog.js'; console.log(JSON.stringify({templates:PROVIDER_TEMPLATES,types:[...VIDEO_PROVIDER_TYPES]}));"
    catalog = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', script], cwd=ROOT, text=True, encoding='utf-8'))
    assert {key for key in catalog['templates'] if key in catalog['types']} == EXPECTED
    assert RETIRED.issubset(catalog['types'])  # Classify saved legacy configs as videos.
    for key, definition in definitions.items():
        assert schema[key] == definition
        for field, settings in definition['items'].items():
            if field != 'id':
                assert catalog['templates'][key][field] == settings['default']
    assert definitions['xpivot_video']['items']['api_keys']['default'] == []


def test_xpivot_capability_has_single_and_seven_image_modes():
    capability = build_provider_capability({'id': 'muse', '__template_key': 'xpivot_video', 'model': 'grok-imagine-video-1.5'})
    assert capability['operations']['video_generate'] == 'supported'
    modes = {item['id']: item for item in capability['references']['modes']}
    assert modes['image']['max_images'] == 1
    assert modes['reference']['max_images'] == 7
    assert modes['text']['max_images'] == 0
    assert capability['parameters']['resolutions']['values'] == ['720p']
    assert str(capability['parameters']['duration']['default']) == '5'


@pytest.mark.asyncio
async def test_parallel_duplicate_reference_uploads_share_one_asset(tmp_path):
    store = StudioAssetStore(tmp_path)
    # A recognized PNG signature suffices for the storage transport test.
    data = b'\x89PNG\r\n\x1a\nfixture-reference'
    await store.list(scope='scope')
    results = await asyncio.gather(*(store.create_from_bytes('scope', f'ref-{i}.png', data) for i in range(7)))
    assert len({item['asset_id'] for item in results}) == 1
    assert len(await store.list(scope='scope')) == 1
    assert len(list(store.asset_dir.glob('*.png'))) == 1


def test_saved_provider_list_has_three_separate_groups():
    source = (ROOT / 'web/src/app/StudioApp.tsx').read_text(encoding='utf-8')
    assert 'label: "图片"' in source and 'label: "视频"' in source and 'label: "NAI"' in source
    assert 'isNaiProvider(provider) ? "nai" : VIDEO_PROVIDER_TYPES.has(inferProviderType(provider)) ? "video" : "image"' in source
