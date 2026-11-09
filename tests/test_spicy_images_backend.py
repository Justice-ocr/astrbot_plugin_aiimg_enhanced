import asyncio
import importlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from test_openai_video_service import _load_module, CORE_PACKAGE_NAME

ROOT = Path(__file__).resolve().parents[1]


class SpicyImagesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        mod = importlib.import_module(f'{CORE_PACKAGE_NAME}.spicy_images_backend')
        self.imgr = unittest.mock.Mock()
        self.imgr.download_image = AsyncMock(return_value=Path('fixture.png'))
        self.settings = dict(api_keys=['fixture-a', 'fixture-b'], model='bytedance/seedream-5.0-flash/text-to-image', edit_model='bytedance/seedream-5.0-flash/edit', default_resolution='2k', max_reference_images=10)
        self.backend = mod.SpicyImagesBackend(imgr=self.imgr, settings=self.settings)
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buffer, format='PNG')
        self.image = buffer.getvalue()

    async def test_generate_and_three_reference_edit_use_separate_ids_and_nested_input(self):
        for count in (0, 3, 10):
            calls = []
            async def handler(request):
                calls.append(request)
                if request.method == 'POST':
                    body = json.loads(request.content)
                    self.assertEqual(request.url.path, '/api/v1/jobs/createTask')
                    self.assertTrue(request.headers['idempotency-key'])
                    self.assertEqual(set(body), {'model', 'input'})
                    self.assertEqual(body['model'], self.settings['edit_model' if count else 'model'])
                    self.assertEqual(body['input']['prompt'], 'keep ((artist:1.2)), exact')
                    self.assertEqual(body['input']['resolution'], '2k')
                    self.assertEqual(body['input']['aspect_ratio'], '2:3')
                    self.assertEqual(len(body['input'].get('image_urls', [])), count)
                    if count:
                        self.assertTrue(body['input']['image_urls'][0].startswith('data:image/png;base64,'))
                    return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-fixture'}})
                self.assertEqual(str(request.url.params['taskId']), 'job-fixture')
                self.assertEqual(request.headers['authorization'], calls[0].headers['authorization'])
                if len(calls) == 2:
                    return httpx.Response(200, json={'code': 200, 'data': {'state': 'running'}})
                return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'url': 'https://cdn.test/image.png'}]}}})
            self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch('asyncio.sleep', new=AsyncMock()):
                result = await self.backend._run('keep ((artist:1.2)), exact', [self.image] * count, size='2048x3072')
            self.assertEqual(result, Path('fixture.png'))
            self.assertEqual(sum(r.method == 'POST' for r in calls), 1)
            self.imgr.download_image.assert_called_with('https://cdn.test/image.png')

    async def test_lost_submission_reuses_key_and_idempotency(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ReadTimeout('lost response', request=request)
            if request.method == 'POST':
                self.assertEqual(calls[0].headers['idempotency-key'], request.headers['idempotency-key'])
                self.assertEqual(calls[0].headers['authorization'], request.headers['authorization'])
                self.assertEqual(calls[0].content, request.content)
                return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-original'}})
            return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'url': 'https://cdn.test/original.png'}]}}})
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await self.backend.generate('test')
        self.assertEqual(len(calls), 3)

    async def test_unresolved_submission_reports_idempotency_without_exposing_key(self):
        calls = []
        async def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('fixture network failure', request=request)
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(RuntimeError, '幂等编号') as caught:
            await self.backend.generate('test')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].headers['idempotency-key'], calls[1].headers['idempotency-key'])
        self.assertNotIn('fixture-a', str(caught.exception))
        self.assertNotIn('fixture-b', str(caught.exception))

    async def test_pending_assets_and_transient_poll_failure_do_not_resubmit(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if request.method == 'POST':
                return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-transfer'}})
            if len(calls) == 2:
                return httpx.Response(503)
            if len(calls) == 3:
                return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'status': 'pending'}]}}})
            return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'url': 'https://cdn.test/ready.png'}]}}})
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('asyncio.sleep', new=AsyncMock()):
            await self.backend.generate('test')
        self.assertEqual(sum(r.method == 'POST' for r in calls), 1)

    async def test_permanently_unavailable_asset_stops_polling(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if request.method == 'POST':
                return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-unavailable'}})
            return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'unavailable': True}]}}})
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertRaisesRegex(RuntimeError, 'job-unavailable'):
            await self.backend.generate('test')
        self.assertEqual(len(calls), 2)
        self.imgr.download_image.assert_not_called()

    async def test_failure_and_timeout_keep_task_id(self):
        for state in ('failed', 'expired', 'canceled', 'unexpected'):
            async def handler(request):
                if request.method == 'POST':
                    return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-failed'}})
                return httpx.Response(200, json={'code': 200, 'data': {'state': state, 'errorCode': 'content_rejected'}})
            self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with self.assertRaisesRegex(RuntimeError, 'job-failed'):
                await self.backend.generate('test')
        self.backend.settings['poll_timeout'] = 0
        with self.assertRaisesRegex(RuntimeError, 'job-failed'):
            await self.backend.generate('test')

    async def test_resume_gets_only_and_uses_original_key(self):
        async def handler(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.headers['authorization'], 'Bearer original-key')
            self.assertEqual(request.url.params['taskId'], 'job/a?b')
            return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'url': 'https://cdn.test/resume.png'}]}}})
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await self.backend.resume_image('job/a?b', api_key='original-key')

    async def test_validation_precedes_network(self):
        self.backend._client = unittest.mock.Mock(side_effect=AssertionError('network forbidden'))
        for images in ([self.image] * 11, [b'not an image']):
            with self.assertRaises((ValueError, OSError)):
                await self.backend.edit('test', images)
        self.backend.settings['extra_input'] = '{"prompt":"hidden override"}'
        with self.assertRaises(ValueError):
            await self.backend.generate('test')
        self.backend.settings['extra_input'] = '{"num_outputs":2}'
        with self.assertRaises(ValueError):
            await self.backend.generate('test')
        self.backend._client.assert_not_called()

    def test_size_tiers_are_not_sent_as_pixel_size(self):
        payload = self.backend._input('test', [], size='2K')
        self.assertEqual(payload['input']['resolution'], '2k')
        self.assertNotIn('size', payload['input'])
        self.assertEqual(self.backend._input('test', [], size='2048x1360')['input']['aspect_ratio'], '3:2')
        self.assertEqual(self.backend._input('test', [], size='1024x576')['input']['aspect_ratio'], '16:9')

    async def test_expired_signed_download_refreshes_same_task_without_resubmit(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if request.method == 'POST':
                return httpx.Response(202, json={'code': 200, 'data': {'taskId': 'job-signed'}})
            return httpx.Response(200, json={'code': 200, 'data': {'state': 'succeeded', 'output': {'assets': [{'url': f'https://cdn.test/image-{len(calls)}.png'}]}}})
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.imgr.download_image.side_effect = [RuntimeError('HTTP 403'), Path('refreshed.png')]
        self.assertEqual(await self.backend.generate('test'), Path('refreshed.png'))
        self.assertEqual([r.method for r in calls], ['POST', 'GET', 'GET'])
        self.assertEqual(self.imgr.download_image.call_args_list[1].args[0], 'https://cdn.test/image-3.png')

    def test_shared_template_and_capabilities(self):
        definition = json.loads((ROOT/'web/src/app/spicy_templates.json').read_text(encoding='utf-8'))['spicy_images']
        schema = json.loads((ROOT/'_conf_schema.json').read_text(encoding='utf-8'))['providers']['templates']['spicy_images']
        self.assertEqual(definition, schema)
        mod = importlib.import_module(f'{CORE_PACKAGE_NAME}.studio.capability_catalog')
        result = mod.build_provider_capability({'id': 'spicy', '__template_key': 'spicy_images', **self.settings})
        self.assertEqual(result['operations']['image_edit'], 'supported')
        self.assertEqual(result['references']['modes'][0]['max_images'], 10)
