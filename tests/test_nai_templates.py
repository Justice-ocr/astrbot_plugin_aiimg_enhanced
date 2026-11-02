"""Protocol-specific template contracts, not just successful page rendering."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = ROOT / 'web/src/app/nai_templates.json'


def definitions():
    return json.loads(DEFINITIONS.read_text(encoding='utf-8'))


def test_nai_schema_and_web_definitions_are_identical():
    schema = json.loads((ROOT / '_conf_schema.json').read_text(encoding='utf-8'))
    for key, definition in definitions().items():
        assert schema['providers']['templates'][key] == definition


def test_web_catalog_defaults_match_nai_schema():
    source = (ROOT / 'web/src/app/provider_catalog.js').as_uri()
    script = f'import {{ PROVIDER_TEMPLATES }} from {json.dumps(source)}; console.log(JSON.stringify(PROVIDER_TEMPLATES));'
    result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=True, encoding='utf-8')
    templates = json.loads(result.stdout)
    for key, definition in definitions().items():
        expected = {'label': definition['name'], **{name: field['default'] for name, field in definition['items'].items() if name not in {'id', 'label'}}}
        assert templates[key] == expected


def test_provider_templates_do_not_contain_workbench_prompt_preferences():
    for definition in definitions().values():
        for key in ('nai_artist', 'nai_prompt_prefix', 'negative_prompt', 'nai_llm_provider_id', 'nai_translate_prompt'):
            assert key not in definition['items']


def test_native_template_contains_only_implemented_protocol_fields():
    template = definitions()['nai_native']
    items = template['items']
    for unused in ('supports_edit', 'generate_request_mode', 'edit_request_mode', 'max_retries', 'extra_body', 'nai_translate_prompt'):
        assert unused not in items
    assert '/ai/generate-image' in items['base_url']['hint']
    assert '不会自动补 /v1' in items['base_url']['hint']
    assert items['nai_reference_mode']['options'] == ['img2img', 'character', 'vibe']
    assert 'seed' in items and items['seed']['default'] == ''
    for key in ('guidance_scale', 'nai_vibe_information', 'nai_cfg', 'nai_strength'):
        assert items[key]['type'] == 'float'
    for size in items['default_size']['options']:
        w, h = map(int, size.split('x'))
        assert w % 64 == h % 64 == 0
        assert w * h <= 4194304


def test_compat_template_does_not_claim_native_or_streaming_options():
    items = definitions()['nai_openai_images']['items']
    assert items['max_retries']['default'] == 0
    assert items['supports_edit']['default'] is False
    assert items['default_size']['default'] == '832x1216'
    for key in ('generate_request_mode', 'edit_request_mode', 'nai_reference_mode', 'nai_sampler', 'guidance_scale', 'nai_vibe_information', 'nai_strength', 'nai_cfg'):
        assert key not in items


def test_nai_form_uses_template_metadata_instead_of_global_video_options():
    source = (ROOT / 'web/src/app/StudioApp.tsx').read_text(encoding='utf-8')
    assert 'definition.options.map' in source
    assert 'definition?.type === "float" ? "any" : 1' in source
    assert '["text", "纯文生"]' not in source.split('nai_reference_mode:')[1].split('\n')[0]
    assert 'key === "nai_llm_provider_id"' in source
