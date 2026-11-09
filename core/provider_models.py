"""Read-only model discovery. Never submits generation or persists credentials."""
from __future__ import annotations

import copy
import json
from urllib.parse import urlsplit, urlunsplit

import httpx

from .net_safety import URLFetchPolicy, collect_trusted_origins, ensure_url_allowed, read_network_policy

SECRET_FIELDS = {"api_key", "api_keys", "apikey", "token", "access_token", "authorization", "cookie", "cookies", "cookie_list", "password", "secret", "refresh_token", "graphql_api_key", "third_party_token"}
OPENAI_TYPES = {
    "openai_images", "openai_chat", "gemini_openai_images", "gemini_openai_chat",
    "grok_images", "grok_images_edit", "grok_chat", "grok2api_images", "grok2api_video",
    "modelscope_openai_images", "gitee_images", "gitee_async", "openai_full_url_images",
    "openai_video", "xai_video", "xpivot_video", "agnes_video", "flow2api", "flow2api_video",
    "nai_openai_images",
}


def connection_origin(provider):
    raw = str(provider.get("base_url") or provider.get("api_url") or provider.get("full_generate_url") or "")
    parts = urlsplit(raw.strip())
    return (parts.scheme.lower(), parts.netloc.lower())


def discovery_provider(config, incoming, original_id, updates):
    """Merge draft with server-held key, without leaking a saved key to a changed origin."""
    if not isinstance(incoming, dict) or not isinstance(updates, dict):
        raise ValueError("服务商及凭据参数必须是对象")
    saved = next((p for p in config.get("providers", []) if isinstance(p, dict) and p.get("id") == original_id), {})
    merged = {k: copy.deepcopy(v) for k, v in incoming.items() if k not in SECRET_FIELDS and not k.endswith("_configured")}
    same_origin = connection_origin(saved) == connection_origin(merged)
    if same_origin:
        for key in SECRET_FIELDS:
            if key in saved:
                merged[key] = copy.deepcopy(saved[key])
    for key, update in updates.items():
        if key not in SECRET_FIELDS or not isinstance(update, dict):
            raise ValueError("凭据更新格式无效")
        if update.get("clear"):
            merged[key] = [] if key == "api_keys" else ""
        elif "value" in update:
            value = update["value"]
            if not isinstance(value, (str, list)) or len(value) > (20000 if isinstance(value, str) else 100):
                raise ValueError("凭据格式或长度无效")
            if isinstance(value, list) and any(not isinstance(v, str) or len(v) > 20000 for v in value):
                raise ValueError("密钥列表格式无效")
            merged[key] = value
    if saved and not same_origin and not any(merged.get(k) for k in SECRET_FIELDS):
        raise ValueError("API 地址已更换，请填写该地址的密钥后获取列表；现有密钥不会发送至新地址")
    return merged


class ProviderModelDiscovery:
    def __init__(self, config):
        self.config = config

    def _client(self, proxy=None):
        return httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), follow_redirects=False, **({"proxy": proxy} if proxy else {}))

    async def fetch(self, provider):
        kind = str(provider.get("__template_key") or provider.get("__type") or "")
        root = str(provider.get("base_url") or provider.get("api_url") or provider.get("full_generate_url") or "").strip().rstrip("/")
        parts = urlsplit(root)
        if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("请填写有效的 API 地址（不含凭据、查询参数或片段）")
        keys = provider.get("api_keys") or []
        if not isinstance(keys, list):
            raise ValueError("API Key 池必须是列表")
        key = next((str(k).strip() for k in keys if str(k).strip()), "") or str(provider.get("api_key") or "").strip()
        headers = {}
        params = {}
        path = parts.path.rstrip("/")
        if kind == "spicy_images":
            if path.endswith('/api/v1'):
                path = path[:-7]
            path += '/api/v1/models'
            params = {"modality": "image"}
        elif kind == "gemini_native":
            path = path.split('/models')[0]
            if not path.endswith(('/v1beta', '/v1')):
                path += '/v1beta'
            path += '/models'
        elif kind in OPENAI_TYPES:
            for suffix in ('/images/generations', '/images/edits', '/chat/completions', '/video/generations', '/videos'):
                if path.endswith(suffix):
                    path = path[:-len(suffix)]
                    break
            if not path:
                path = '/v1'
            path += '/models'
        else:
            raise ValueError("此模板没有通用模型列表接口，请手动填写模型 ID")
        if key:
            headers = {"x-goog-api-key": key} if kind == 'gemini_native' else {"Authorization": f"Bearer {key}"}
        elif kind in {'spicy_images', 'gemini_native'}:
            raise ValueError("请先填写 API Key 后获取模型列表")
        url = urlunsplit((parts.scheme, parts.netloc, path, '', ''))
        network = read_network_policy(self.config)
        policy = URLFetchPolicy(allow_private=bool(network.get('media_allow_private', False)), trusted_origins=frozenset(collect_trusted_origins(self.config)))
        await ensure_url_allowed(url, policy=policy)
        proxy = str(provider.get('proxy_url') or '').strip() or None
        models = {}
        async with self._client(proxy) as client:
            for page in range(20):
                async with client.stream('GET', url, headers=headers, params=params) as response:
                    if response.status_code != 200:
                        raise ValueError(f"模型列表获取失败（HTTP {response.status_code}），可继续手动填写")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 4 * 1024 * 1024:
                            raise ValueError("模型列表响应过大，请手动填写模型 ID")
                    try:
                        body = json.loads(content)
                    except ValueError:
                        raise ValueError("模型列表返回非 JSON，可继续手动填写") from None
                if not isinstance(body, dict):
                    raise ValueError("模型列表格式无效，可继续手动填写")
                if kind == 'spicy_images':
                    if body.get('code') != 200 or not isinstance(body.get('data'), dict):
                        raise ValueError("SpicyAPI 模型列表业务响应无效")
                    items = body['data'].get('items', [])
                else:
                    items = body.get('models' if kind == 'gemini_native' else 'data', [])
                if not isinstance(items, list):
                    raise ValueError("模型列表格式无效，可继续手动填写")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if kind == 'spicy_images' and (item.get('enabled') is not True or item.get('available') is not True):
                        continue
                    model_id = item.get('model') if kind == 'spicy_images' else item.get('name') if kind == 'gemini_native' else item.get('id')
                    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 300:
                        continue
                    model_id = model_id.strip()
                    model_id = model_id.removeprefix('models/') if kind == 'gemini_native' else model_id
                    label = str(item.get('displayName') or item.get('name') or model_id)[:300]
                    tasks = item.get('tasks', [])
                    if not isinstance(tasks, list):
                        tasks = []
                    models[model_id] = {'id': model_id, 'label': label, 'tasks': [t for t in tasks if isinstance(t, str)][:30]}
                token = body.get('nextPageToken') if kind == 'gemini_native' else None
                if not token:
                    break
                params['pageToken'] = token
            else:
                raise ValueError("模型列表分页过多，请手动填写模型 ID")
        return sorted(models.values(), key=lambda item: item['id'].lower())[:5000]
