import asyncio
import base64
import importlib
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from test_openai_video_service import _load_module, CORE_PACKAGE_NAME


def animated_gif():
    out = io.BytesIO()
    Image.new('RGB',(32,32),'red').save(out,format='GIF',save_all=True,append_images=[Image.new('RGB',(32,32),'blue')],duration=200,loop=0)
    return out.getvalue()


class GptGifTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _load_module()
        self.mod = importlib.import_module(f'{CORE_PACKAGE_NAME}.gpt_image_gif_backend')
        self.cls = self.mod.GptImageGifBackend
        self.provider = {'base_url':'https://api.test/v1','api_keys':['first-key','second-key']}
        self.backend = self.cls(self.provider, {'providers':[self.provider]})
        self.raw = animated_gif()
        self.req = dict(self.cls.validate({'gif_protocol':'openai','gif_model':'gpt-image-2.6-flare'}),prompt='A cat waves, seamless loop')
        self.allow = patch.object(self.mod,'ensure_url_allowed',new=AsyncMock())
        self.allow.start(); self.addCleanup(self.allow.stop)

    def transport(self, handler):
        self.backend._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_parameter_limits_sheet_budget_and_protocol(self):
        self.assertEqual(self.req['frame_count'],9)
        for updates in [{'frame_count':1},{'frame_count':17},{'frame_count':2.5},{'frame_count':True},
                        {'frame_duration_ms':25},{'frame_duration_ms':2010},{'size':'2048x2048'},
                        {'size':'768x768','frame_count':16},{'gif_model':'gpt-image-1'},
                        {'reference_asset_ids':['a','a']},{'reference_asset_ids':list(map(str,range(17)))},
                        {'gif_protocol':'spicy','reference_asset_ids':['a']},{'gif_protocol':'spicy','size':'512x768'}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.cls.validate({**self.req,**updates})
        self.cls.validate({**self.req,'size':'768x768','frame_count':12})
        self.cls.validate({**self.req,'size':'512x768','frame_count':16})

    async def test_openai_returns_real_gif_and_sends_only_gif_parameters(self):
        calls=[]
        def handler(request):
            calls.append(request)
            body=json.loads(request.content)
            self.assertEqual(request.url.path,'/v1/images/generations')
            self.assertEqual(body['output_format'],'gif')
            self.assertEqual(body['n'],1)
            self.assertNotIn('resolution',body)
            return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]})
        self.transport(handler)
        self.assertEqual(await self.backend.generate(self.req,[],AsyncMock()),self.raw)
        self.assertEqual(len(calls),1)

    async def test_reference_edit_is_multipart_and_preserves_order(self):
        images=[]
        for color in ('red','blue','green'):
            out=io.BytesIO(); Image.new('RGB',(8,8),color).save(out,format='PNG'); images.append(out.getvalue())
        def handler(request):
            self.assertEqual(request.url.path,'/v1/images/edits')
            self.assertIn('multipart/form-data',request.headers['content-type'])
            data=request.content
            self.assertEqual(data.count(b'name="image[]"'),3)
            self.assertLess(data.index(images[0]),data.index(images[1]))
            self.assertLess(data.index(images[1]),data.index(images[2]))
            return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]})
        self.transport(handler)
        self.assertEqual(await self.backend.generate(self.req,images,AsyncMock()),self.raw)

    async def test_apimart_async_accept_poll_download_without_credentials(self):
        self.req['gif_protocol']='apimart'
        calls=[]
        def handler(request):
            calls.append(request)
            if request.method=='POST':
                self.assertEqual(request.url.path,'/v1/images/generations')
                return httpx.Response(200,json={'code':200,'data':[{'task_id':'task/id'}]})
            if request.url.host=='cdn.test':
                self.assertNotIn('authorization',request.headers)
                return httpx.Response(200,content=self.raw)
            self.assertEqual(request.headers['authorization'],'Bearer first-key')
            return httpx.Response(200,json={'code':200,'data':{'status':'completed','result':{'images':[{'url':['https://cdn.test/a.gif']}]}}})
        self.transport(handler)
        accepted=AsyncMock()
        result=await self.backend.generate(self.req,[],accepted)
        self.assertEqual(result,self.raw)
        accepted.assert_awaited_once_with('task/id',self.backend.fingerprint('first-key','apimart'))
        self.assertEqual(sum(r.method=='POST' for r in calls),1)
        self.assertIn('task%2Fid',str(calls[1].url))

    async def test_spicy_uses_nested_inputs_and_published_resolution(self):
        self.backend=self.cls({**self.provider,'base_url':'https://api.test'},{})
        self.req['gif_protocol']='spicy'
        calls=[]
        def handler(request):
            calls.append(request)
            if request.method=='POST':
                data=json.loads(request.content)
                self.assertEqual(request.url.path,'/api/v1/jobs/createTask')
                self.assertEqual(data['model'],'openai/gpt-image-2.6-flare/text-to-image')
                self.assertEqual(data['input']['resolution'],'512')
                self.assertNotIn('size',data['input'])
                self.assertNotIn('complexity',data['input'])
                return httpx.Response(202,json={'code':200,'data':{'taskId':'job-spicy'}})
            if request.url.host=='cdn.test':return httpx.Response(200,content=self.raw)
            return httpx.Response(200,json={'code':200,'data':{'state':'succeeded','output':{'assets':[{'url':'https://cdn.test/a.gif'}]}}})
        self.transport(handler)
        self.assertEqual(await self.backend.generate(self.req,[],AsyncMock()),self.raw)

    async def test_lost_submission_does_not_retry_and_hides_transport_secrets(self):
        calls=[]
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('first-key secret response',request=request)
        self.transport(handler)
        with self.assertRaisesRegex(RuntimeError,'提交结果可能未知') as caught:
            await self.backend.generate(self.req,[],AsyncMock())
        self.assertEqual(len(calls),1)
        self.assertNotIn('first-key',str(caught.exception))

    async def test_resume_requires_original_key_and_origin(self):
        self.req['gif_protocol']='apimart'
        fingerprint=self.backend.fingerprint('second-key','apimart')
        def handler(request):
            if request.url.host=='cdn.test':return httpx.Response(200,content=self.raw)
            self.assertEqual(request.headers['authorization'],'Bearer second-key')
            return httpx.Response(200,json={'code':200,'data':{'status':'completed','result':{'images':[{'url':['https://cdn.test/a.gif']}]}}})
        self.transport(handler)
        self.assertEqual(await self.backend.resume(self.req,'saved-task',fingerprint),self.raw)
        with self.assertRaisesRegex(ValueError,'原地址和原密钥'):
            await self.backend.resume(self.req,'saved-task','other-fingerprint')

    async def test_terminal_task_stops_and_static_image_is_rejected(self):
        self.req['gif_protocol']='apimart'
        self.transport(lambda request:httpx.Response(200,json={'code':200,'data':{'status':'failed','error':{'message':'first-key'}}}))
        with self.assertRaises(self.mod.GifTaskFailed) as caught:
            await self.backend.resume(self.req,'task',self.backend.fingerprint('first-key','apimart'))
        self.assertNotIn('first-key',str(caught.exception))
        out=io.BytesIO(); Image.new('RGB',(8,8),'red').save(out,format='PNG')
        with self.assertRaisesRegex(RuntimeError,'动画 GIF'):
            self.cls.verify(out.getvalue())

    async def test_asset_redirect_validated_and_download_does_not_forward_key(self):
        def handler(request):
            self.assertNotIn('authorization',request.headers)
            if request.url.host=='cdn.test':return httpx.Response(302,headers={'Location':'https://final.test/a.gif'})
            return httpx.Response(200,content=self.raw)
        self.transport(handler)
        async with self.backend._client() as client:
            self.assertEqual(await self.backend._download(client,'https://cdn.test/a.gif'),self.raw)
        self.assertEqual(self.mod.ensure_url_allowed.await_count,2)
