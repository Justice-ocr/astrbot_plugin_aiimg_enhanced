"""GPT Image 2.6 animated output, with explicit provider protocols and no paid retries."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import time
from urllib.parse import quote, urlsplit

import httpx
from PIL import Image

from .net_safety import URLFetchPolicy, collect_trusted_origins, ensure_url_allowed, read_network_policy


class GifTaskFailed(RuntimeError):
    """The upstream task reached a permanent terminal state."""


class GptImageGifBackend:
    MAX_BYTES = 20 * 1024 * 1024

    @staticmethod
    def validate(payload):
        protocol = str(payload.get('gif_protocol') or '')
        model = str(payload.get('gif_model') or '')
        if protocol not in {'openai', 'apimart', 'spicy'}:
            raise ValueError('请选择 GIF 接口协议')
        if model not in {'gpt-image-2.6-flare', 'gpt-image-2.6-sunburst'}:
            raise ValueError('GIF 专用工作台仅支持 GPT Image 2.6 Flare / Sunburst')
        def integer(key, default, minimum, maximum):
            value = payload.get(key, default)
            if isinstance(value, bool):
                raise ValueError(f'{key} 必须为整数')
            try:
                number = int(value)
                if float(value) != number or not minimum <= number <= maximum:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f'{key} 必须为 {minimum}–{maximum} 的整数') from None
            return number
        count = integer('frame_count', 9, 2, 16)
        duration = integer('frame_duration_ms', 200, 20, 2000)
        if duration % 10:
            raise ValueError('每帧时长必须是 10 ms 的倍数')
        size = str(payload.get('size') or '512x512')
        if size not in {'512x512', '768x768', '512x768', '768x512'}:
            raise ValueError('请使用 GIF 工作台提供的帧尺寸')
        w, h = map(int, size.split('x'))
        cols, rows = (4, 2) if count <= 8 else (3, 3) if count == 9 else (4, 3) if count <= 12 else (4, 4)
        if not any(max(w*c, h*r) <= 3840 and w*h*c*r <= 8294400 and max(w*c,h*r)/min(w*c,h*r) <= 3 for c,r in [(cols,rows),(rows,cols)]):
            raise ValueError('帧尺寸与帧数超过整张帧图限制，请减少帧数或尺寸')
        refs = payload.get('reference_asset_ids') or []
        if not isinstance(refs, list) or len(refs) > 16 or any(not isinstance(v, str) or not v.strip() for v in refs) or len(set(refs)) != len(refs):
            raise ValueError('参考图必须是最多 16 张不重复的素材')
        if payload.get('reference_paths'):
            raise ValueError('GIF 工作台仅支持当前会话的参考素材')
        if protocol == 'spicy' and refs:
            raise ValueError('SpicyAPI 当前仅开放文生 GIF，不支持参考图 GIF')
        if protocol == 'spicy' and size not in {'512x512', '768x768'}:
            raise ValueError('SpicyAPI GIF 暂仅提供方形 512 / 768 档位')
        quality = str(payload.get('quality') or 'low')
        complexity = str(payload.get('complexity') or 'low')
        if quality not in {'low','medium','high','xhigh','max'} or complexity not in {'low','medium','high'}:
            raise ValueError('GIF 质量或规划等级无效')
        return dict(gif_protocol=protocol, gif_model=model, frame_count=count, frame_duration_ms=duration,
                    size=size, quality=quality, complexity=complexity, reference_asset_ids=refs)

    def __init__(self, provider, config):
        self.provider = provider
        self.config = config
        self.root = str(provider.get('base_url') or provider.get('api_url') or '').strip().rstrip('/')
        parts = urlsplit(self.root)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('服务商需要有效的 Base URL')
        pool = provider.get('api_keys') or []
        self.keys = [v.strip() for v in pool if isinstance(v, str) and v.strip()] if isinstance(pool, list) else []
        if not self.keys and provider.get('api_key'):
            self.keys = [str(provider['api_key']).strip()]
        if not self.keys:
            raise ValueError('服务商未配置 API Key')
        self.policy = URLFetchPolicy(allow_private=bool(read_network_policy(config).get('media_allow_private', False)), trusted_origins=frozenset(collect_trusted_origins(config)))

    def _client(self):
        proxy = str(self.provider.get('proxy_url') or '').strip()
        return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20), follow_redirects=False, **({'proxy': proxy} if proxy else {}))

    def api_root(self, protocol):
        root = self.root
        if protocol == 'spicy':
            return root[:-7] if root.endswith('/api/v1') else root
        return root if root.endswith('/v1') else root + '/v1'

    def fingerprint(self, key, protocol):
        return hashlib.sha256(f'{self.api_root(protocol)}\0{key}'.encode()).hexdigest()

    async def _json(self, client, method, url, key, **kwargs):
        await ensure_url_allowed(url, policy=self.policy)
        try:
            async with client.stream(method, url, headers={'Authorization': f'Bearer {key}'}, **kwargs) as response:
                if response.status_code >= 400 or response.is_redirect:
                    raise RuntimeError(f'GIF 接口请求失败（HTTP {response.status_code}）；未自动重新提交生成')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 75 * 1024 * 1024:
                        raise RuntimeError('GIF 接口响应超过大小限制')
                import json
                try:
                    body = json.loads(raw)
                except ValueError:
                    raise RuntimeError('GIF 接口返回了非 JSON 数据') from None
                if not isinstance(body, dict):
                    raise RuntimeError('GIF 接口返回格式错误')
                return body
        except httpx.HTTPError:
            raise RuntimeError('GIF 接口网络中断；提交结果可能未知，请核对上游账单与任务记录，勿直接重复生成') from None

    async def generate(self, request, references, accepted):
        protocol = request['gif_protocol']
        key = self.keys[0]
        root = self.api_root(protocol)
        body = {k: request[k] for k in ('prompt','size','quality','complexity','frame_count','frame_duration_ms')}
        body.update(model=request['gif_model'], output_format='gif', n=1)
        files = []
        if len(references) > 16 or sum(len(raw) for raw in references) > 100 * 1024 * 1024:
            raise ValueError('GIF 参考图最多 16 张，合计不能超过 100MB')
        data_urls = []
        for index, raw in enumerate(references):
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError('单张参考图不能超过 20MB')
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in {'PNG','JPEG','WEBP'} or getattr(im, 'n_frames', 1) > 1:
                    raise ValueError('GIF 参考图需为静态 PNG / JPEG / WebP')
                mime = Image.MIME[im.format]
            files.append(('image[]', (f'reference-{index}', raw, mime)))
            data_urls.append(f'data:{mime};base64,' + base64.b64encode(raw).decode())
        async with self._client() as client:
            if protocol == 'spicy':
                inputs = {k:v for k,v in body.items() if k not in {'model','n','size','complexity'}}
                inputs.update(num_outputs=1, resolution=request['size'].split('x')[0], aspect_ratio='1:1')
                model = 'openai/' + request['gif_model'] + '/text-to-image'
                response = await self._json(client, 'POST', root + '/api/v1/jobs/createTask', key, json={'model':model, 'input':inputs})
                data = response.get('data') or {}
                task_id = data.get('taskId') if isinstance(data,dict) and response.get('code') == 200 else None
            elif protocol == 'apimart':
                if data_urls:
                    body['image_urls'] = data_urls
                response = await self._json(client, 'POST', root + '/images/generations', key, json=body)
                data = response.get('data')
                task_id = data[0].get('task_id') if response.get('code') == 200 and isinstance(data,list) and data and isinstance(data[0],dict) else None
            else:
                response = await self._json(client, 'POST', root + ('/images/edits' if references else '/images/generations'), key,
                    **({'data':{k:str(v) for k,v in body.items()}, 'files':files} if references else {'json':body}))
                data = response.get('data')
                if not isinstance(data,list) or len(data) != 1 or not isinstance(data[0],dict):
                    raise RuntimeError('GIF 同步响应缺少单个结果；请确认接口协议，勿重复生成')
                return await self._result(client, data[0])
            if not isinstance(task_id,str) or not task_id.strip():
                raise RuntimeError('GIF 提交响应缺少任务 ID；请核对上游记录，勿直接重复生成')
            await accepted(task_id, self.fingerprint(key,protocol))
            return await self._poll(client, request, task_id, key)

    async def resume(self, request, task_id, fingerprint):
        protocol = request['gif_protocol']
        key = next((k for k in self.keys if self.fingerprint(k,protocol) == fingerprint), None)
        if not key:
            raise ValueError('恢复 GIF 需要提交时的原地址和原密钥，请恢复配置后重试')
        async with self._client() as client:
            return await self._poll(client, request, task_id, key)

    async def _poll(self, client, request, task_id, key):
        protocol = request['gif_protocol']
        root = self.api_root(protocol)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                url = root + ('/api/v1/jobs/recordInfo' if protocol == 'spicy' else '/tasks/' + quote(task_id,safe=''))
                body = await self._json(client, 'GET', url, key, **({'params':{'taskId':task_id}} if protocol == 'spicy' else {}))
            except RuntimeError:
                await asyncio.sleep(5)
                continue
            data = body.get('data') or {}
            if body.get('code') != 200 or not isinstance(data,dict):
                raise RuntimeError(f'GIF 查询业务响应无效；保留原任务 {task_id}')
            state = str(data.get('state' if protocol == 'spicy' else 'status') or '').lower()
            if state in {'failed','expired','canceled','cancelled'}:
                raise GifTaskFailed(f'上游 GIF 任务已终止（{state}），任务 ID：{task_id}')
            if state in {'succeeded','completed'}:
                if protocol == 'spicy':
                    assets = (data.get('output') or {}).get('assets') or []
                    if assets and all(a.get('unavailable') for a in assets if isinstance(a,dict)):
                        raise GifTaskFailed(f'GIF 文件已不可用，任务 ID：{task_id}')
                    urls = [a.get('url') for a in assets if isinstance(a,dict) and not a.get('pending') and not a.get('unavailable')]
                else:
                    images = (data.get('result') or {}).get('images') or []
                    urls = []
                    for image in images:
                        value = image.get('url') if isinstance(image,dict) else None
                        urls.extend(value if isinstance(value,list) else [value])
                url = next((v for v in urls if isinstance(v,str) and v), None)
                if url:
                    return await self._download(client,url)
            await asyncio.sleep(3)
        raise RuntimeError(f'本地等待结束，上游 GIF 可能仍在运行，请继续查询原任务：{task_id}')

    async def _result(self, client, item):
        if item.get('b64_json'):
            try:
                raw = base64.b64decode(item['b64_json'], validate=True)
            except (ValueError,TypeError):
                raise RuntimeError('GIF Base64 数据无效') from None
            return self.verify(raw)
        if isinstance(item.get('url'),str):
            return await self._download(client,item['url'])
        raise RuntimeError('GIF 响应缺少图片数据')

    async def _download(self, client, url):
        # No API key is attached to asset URLs, including validated redirects.
        for _ in range(4):
            await ensure_url_allowed(url,policy=self.policy)
            try:
                async with client.stream('GET',url) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url,response.headers.get('location',''))
                        continue
                    if response.status_code != 200:
                        raise RuntimeError(f'GIF 下载失败（HTTP {response.status_code}）')
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>self.MAX_BYTES:
                            raise RuntimeError('GIF 文件超过 20MB 限制')
                    return self.verify(bytes(raw))
            except httpx.HTTPError:
                raise RuntimeError('GIF 文件下载中断，请保留原任务继续查询') from None
        raise RuntimeError('GIF 下载重定向次数过多')

    @classmethod
    def verify(cls, raw):
        if len(raw)>cls.MAX_BYTES:
            raise RuntimeError('GIF 文件超过 20MB 限制')
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'GIF' or not 2 <= getattr(image,'n_frames',1) <= 16:
                    raise ValueError()
                if max(image.size)>3840 or image.width*image.height>8294400:
                    raise ValueError()
                for frame in range(image.n_frames):
                    image.seek(frame)
                    image.load()
        except Exception:
            raise RuntimeError('上游未返回有效的 2–16 帧动画 GIF；未将静态图冒充动画') from None
        return raw
