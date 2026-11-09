import importlib
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class ModelDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.mod = importlib.import_module(f'{CORE_PACKAGE_NAME}.provider_models')
        self.service = self.mod.ProviderModelDiscovery({})
        self.allowed = patch.object(self.mod, 'ensure_url_allowed', new=AsyncMock())
        self.allowed.start()
        self.addCleanup(self.allowed.stop)

    def transport(self, handler):
        self.service._client = lambda proxy=None: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_server_keys_are_retained_only_for_same_origin_and_never_mutate_config(self):
        saved = {'id': 'one', 'base_url': 'https://api.test/v1', 'api_keys': ['saved-key']}
        config = {'providers': [saved]}
        draft = {'id': 'renamed', 'base_url': 'https://api.test/v2', 'api_keys_configured': True, 'api_keys': ['injected']}
        result = self.mod.discovery_provider(config, draft, 'one', {})
        self.assertEqual(result['api_keys'], ['saved-key'])
        self.assertNotIn('api_keys_configured', result)
        draft['base_url'] = 'https://different.test'
        with self.assertRaisesRegex(ValueError, '现有密钥不会'):
            self.mod.discovery_provider(config, draft, 'one', {})
        result = self.mod.discovery_provider(config, draft, 'one', {'api_keys': {'value': ['draft-key']}})
        self.assertEqual(result['api_keys'], ['draft-key'])
        self.assertEqual(saved['api_keys'], ['saved-key'])
        result = self.mod.discovery_provider(config, {**saved}, 'one', {'api_keys': {'clear': True}})
        self.assertEqual(result['api_keys'], [])

    async def test_spicy_catalog_only_exposes_live_ids_and_task_metadata(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.path, '/api/v1/models')
            self.assertEqual(request.url.params['modality'], 'image')
            self.assertEqual(request.headers['authorization'], 'Bearer draft-key')
            return httpx.Response(200, json={'code': 200, 'data': {'items': [
                {'model': 'lab/flash/edit', 'displayName': 'Flash Edit', 'enabled': True, 'available': True, 'tasks': ['image-to-image'], 'inputSchema': {'secret': 'not exposed'}},
                {'model': 'lab/flash/text-to-image', 'enabled': True, 'available': True, 'tasks': ['text-to-image']},
                {'model': 'lab/unavailable/edit', 'enabled': True, 'available': False},
                {'model': 'lab/disabled/edit', 'enabled': False, 'available': True},
            ]}})
        self.transport(handler)
        models = await self.service.fetch({'__template_key': 'spicy_images', 'base_url': 'https://api.test', 'api_keys': ['draft-key']})
        self.assertEqual([m['id'] for m in models], ['lab/flash/edit', 'lab/flash/text-to-image'])
        self.assertEqual(set(models[0]), {'id', 'label', 'tasks'})
        self.assertEqual(len(calls), 1)

    async def test_openai_paths_and_gemini_pagination(self):
        for root, expected in [('https://api.test', '/v1/models'), ('https://api.test/v1', '/v1/models'), ('https://api.test/proxy/v1/images/generations', '/proxy/v1/models')]:
            def handler(request):
                self.assertEqual(request.url.path, expected)
                return httpx.Response(200, json={'data': [{'id': 'model-a'}, {'id': 'model-a'}, {'id': 'model-b'}]})
            self.transport(handler)
            models = await self.service.fetch({'__template_key': 'openai_images', 'base_url': root})
            self.assertEqual(len(models), 2)
        calls = []
        def gemini(request):
            calls.append(request)
            self.assertEqual(request.headers['x-goog-api-key'], 'gem-key')
            self.assertNotIn('key', request.url.params)
            self.assertEqual(request.url.path, '/v1beta/models')
            if len(calls) == 1:
                return httpx.Response(200, json={'models': [{'name': 'models/first'}], 'nextPageToken': 'page-2'})
            self.assertEqual(request.url.params['pageToken'], 'page-2')
            return httpx.Response(200, json={'models': [{'name': 'models/second'}]})
        self.transport(gemini)
        models = await self.service.fetch({'__template_key': 'gemini_native', 'api_url': 'https://api.test', 'api_keys': ['gem-key']})
        self.assertEqual([m['id'] for m in models], ['first', 'second'])

    async def test_http_error_body_is_not_exposed_and_redirects_are_not_followed(self):
        for status in (302, 401, 404, 429, 500):
            self.transport(lambda request: httpx.Response(status, text='sensitive-key', headers={'Location': 'https://other.test'}))
            with self.assertRaises(ValueError) as caught:
                await self.service.fetch({'__template_key': 'openai_images', 'base_url': 'https://api.test'})
            self.assertNotIn('sensitive-key', str(caught.exception))
            self.assertIn(str(status), str(caught.exception))

    async def test_unsupported_empty_and_malformed_catalogs(self):
        with self.assertRaisesRegex(ValueError, '手动'):
            await self.service.fetch({'__template_key': 'nai_native', 'base_url': 'https://api.test'})
        self.transport(lambda request: httpx.Response(200, json={'data': []}))
        self.assertEqual(await self.service.fetch({'__template_key': 'openai_images', 'base_url': 'https://api.test'}), [])
        for body in ([], {'data': {}}, 'not-json'):
            self.transport(lambda request: httpx.Response(200, content=json.dumps(body).encode() if not isinstance(body, str) else body.encode()))
            with self.assertRaises(ValueError):
                await self.service.fetch({'__template_key': 'openai_images', 'base_url': 'https://api.test'})

    async def test_untrusted_network_is_checked_before_http(self):
        self.mod.ensure_url_allowed.side_effect = RuntimeError('Disallowed IP address')
        with self.assertRaises(RuntimeError):
            await self.service.fetch({'__template_key': 'openai_images', 'base_url': 'http://127.0.0.1'})
