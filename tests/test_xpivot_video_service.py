import asyncio
import importlib
import json
import io
from PIL import Image
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


class XpivotVideoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.mod = importlib.import_module(f"{CORE_PACKAGE_NAME}.xpivot_video_service")
        self.backend = self.mod.XpivotVideoService(settings={"api_keys": ["fixture-only"]})
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buffer, format='PNG')
        self.image = buffer.getvalue()

    async def test_zero_single_two_and_seven_images_follow_verified_protocol(self):
        for count in (0, 1, 2, 7):
            calls = []
            accepted = AsyncMock()
            async def handler(request):
                calls.append(request)
                self.assertEqual(request.headers['authorization'], 'Bearer fixture-only')
                if request.method == 'POST':
                    self.assertEqual(request.url.path, '/v1/video/generations')
                    payload = json.loads(request.content)
                    self.assertEqual(payload['model'], 'grok-imagine-video-1.5')
                    self.assertEqual(payload['duration'], 5)
                    if count == 1:
                        self.assertIn('image', payload)
                        self.assertNotIn('reference_images', payload)
                        self.assertTrue(payload['image']['url'].startswith('data:image/'))
                    elif count:
                        self.assertNotIn('image', payload)
                        self.assertEqual(len(payload['reference_images']), count)
                        self.assertTrue(all(x['url'].startswith('data:image/') for x in payload['reference_images']))
                    else:
                        self.assertNotIn('image', payload)
                        self.assertNotIn('reference_images', payload)
                    return httpx.Response(200, json={'id': 'task-fixture', 'task_id': 'task-fixture', 'status': 'queued'})
                self.assertEqual(request.url.path, '/v1/video/generations/task-fixture')
                if len(calls) == 2:
                    return httpx.Response(200, json={'code': 'success', 'data': {'status': 'QUEUED', 'progress': '40%'}})
                return httpx.Response(200, json={'code': 'success', 'data': {'status': 'SUCCESS', 'result_url': 'https://cdn.test/video.mp4', 'data': {'model': 'muse-video'}}})
            self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch('asyncio.sleep', new=AsyncMock()):
                url = await self.backend.generate_video_url('animate', image_bytes_list=[self.image] * count, on_task_accepted=accepted)
            self.assertEqual(url, 'https://cdn.test/video.mp4')
            self.assertEqual(sum(r.method == 'POST' for r in calls), 1)
            accepted.assert_awaited_once_with('task-fixture')

    async def test_eight_images_and_invalid_modes_never_submit(self):
        self.backend._client = unittest.mock.Mock(side_effect=AssertionError('must not submit'))
        with self.assertRaises(ValueError):
            await self.backend.generate_video_url('test', image_bytes_list=[b'image'] * 8)
        for mode in ('text', 'image'):
            with self.assertRaises(ValueError):
                await self.backend.generate_video_url('test', image_bytes_list=[b'image'] * 2, reference_mode=mode)
        self.backend._client.assert_not_called()

    async def test_resume_reads_nested_video_and_never_posts(self):
        async def handler(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.path, '/v1/video/generations/task-existing')
            return httpx.Response(200, json={'code': 'success', 'data': {'status': 'SUCCESS', 'data': {'status': 'done', 'model': 'muse-video', 'video': {'url': 'https://cdn.test/resumed.mp4'}}}})
        self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('asyncio.sleep', new=AsyncMock()):
            self.assertEqual(await self.backend.resume_video_url('task-existing'), 'https://cdn.test/resumed.mp4')

    async def test_failures_bad_envelopes_and_moderation_are_not_success(self):
        for data in [
            {'code': 'success', 'data': {'status': 'FAILURE', 'fail_reason': 'fixture failure', 'result_url': 'https://cdn.test/no'}},
            {'code': 'task_not_exist', 'data': None},
            {'code': 'success', 'data': []},
            {'code': 'success', 'data': {}},
            {'code': 'success', 'data': {'status': 'SUCCESS', 'result_url': 'file:///tmp/no'}},
            {'code': 'success', 'data': {'status': 'SUCCESS', 'result_url': 'https://cdn.test/no', 'data': {'video': {'respect_moderation': False}}}},
        ]:
            self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)))
            with patch('asyncio.sleep', new=AsyncMock()):
                with self.assertRaises(RuntimeError):
                    await self.backend._poll('task-fixture')

    async def test_accepted_task_failure_preserves_id_without_resubmission(self):
        calls = []
        async def handler(request):
            calls.append(request)
            if request.method == 'POST':
                return httpx.Response(200, json={'task_id': 'task-accepted'})
            return httpx.Response(200, json={'code': 'success', 'data': {'status': 'FAILURE', 'fail_reason': 'upstream failed'}})
        self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        errors = importlib.import_module(f'{CORE_PACKAGE_NAME}.video_errors')
        with patch('asyncio.sleep', new=AsyncMock()):
            with self.assertRaises(errors.VideoTaskAcceptedError) as caught:
                await self.backend.generate_video_url('animate')
        self.assertIn('task-accepted', str(caught.exception))
        self.assertEqual(sum(r.method == 'POST' for r in calls), 1)

    async def test_timeout_and_missing_id_never_retry_submission(self):
        errors = importlib.import_module(f'{CORE_PACKAGE_NAME}.video_errors')
        for response in (None, {'status': 'queued'}):
            calls = []
            async def handler(request):
                calls.append(request)
                if response is None:
                    raise httpx.ReadTimeout('fixture timeout', request=request)
                return httpx.Response(200, json=response)
            self.backend._client = lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with self.assertRaises(errors.VideoSubmissionUnknownError):
                await self.backend.generate_video_url('animate')
            self.assertEqual(len(calls), 1)

    def test_api_root_and_encoded_ids(self):
        backend = self.mod.XpivotVideoService(settings={'base_url': 'https://fixture.test/v1/'})
        self.assertEqual(backend._create_url(), 'https://fixture.test/v1/video/generations')
        self.assertEqual(backend._retrieve_url('task/a?b'), 'https://fixture.test/v1/video/generations/task%2Fa%3Fb')
