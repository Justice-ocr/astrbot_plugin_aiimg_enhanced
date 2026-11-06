import VIDEO_TEMPLATE_DEFINITIONS from './video_templates.json' with { type: 'json' };
import NAI_TEMPLATE_DEFINITIONS from './nai_templates.json' with { type: 'json' };

// Keep Web defaults and field definitions in the same source; schema parity is tested.
const NAI_PROVIDER_TEMPLATES = Object.fromEntries(Object.entries(NAI_TEMPLATE_DEFINITIONS).map(([key, definition]) => [key, {
  label: definition.name,
  ...Object.fromEntries(Object.entries(definition.items).filter(([name]) => !['id', 'label'].includes(name)).map(([name, field]) => [name, field.default])),
}]));

const VIDEO_PROVIDER_TEMPLATES = Object.fromEntries(Object.entries(VIDEO_TEMPLATE_DEFINITIONS).map(([key, definition]) => [key, {
  label: definition.name,
  ...Object.fromEntries(Object.entries(definition.items).filter(([name]) => !['id', 'label'].includes(name)).map(([name, field]) => [name, field.default])),
}]));

function inferProviderType(p) {
  if (!p || typeof p !== 'object') return 'openai_images';
  if (p.__template_key) return p.__template_key;
  if ('nai_reference_mode' in p) return 'nai_native';
  if ('nai_auth_mode' in p) return 'nai_gateway';
  if (String(p.model || '').toLowerCase() === 'grok-imagine-image-edit') return 'grok_images_edit';
  if ('poll_interval' in p || 'poll_timeout' in p) return 'gitee_async';
  if ('cookie_list' in p || 'apikey' in p) return 'jimeng';
  if ('recaptcha_base_api' in p || 'graphql_api_key' in p) return 'vertex_ai_anonymous';
  if ('server_url' in p && 'empty_response_retry' in p) return 'grok_video';
  if ('full_generate_url' in p) return 'openai_full_url_images';
  if ('num_inference_steps' in p && 'negative_prompt' in p) return 'gitee_images';
  const bu = String(p.base_url || p.api_url || '');
  if (bu.includes('generativelanguage.googleapis.com')) return 'gemini_native';
  if ('server_url' in p && 'api_key' in p) return 'grok_video';
  if ('server_url' in p) return 'grok_video';
  if (bu.includes('x.ai') && 'api_keys' in p && !('use_proxy' in p) && !('generate_path' in p)) return 'grok2api_video';
  if (bu.includes('x.ai')) return ('use_proxy' in p && !('supports_edit' in p) && !(p.api_keys && p.api_keys.length)) ? 'grok_chat' : 'grok_images';
  if (bu.includes('gitee.com')) return 'gitee_images';
  const m = String(p.model || '');
  if (m.startsWith('gemini')) return 'gemini_openai_images';
  if ('supports_edit' in p) return 'openai_images';
  if ('api_url' in p && !('base_url' in p) && !('generate_path' in p) && !('num_inference_steps' in p) && !('cookie_list' in p)) {
    if ('model' in p && !('generate_request_mode' in p) && !('edit_request_mode' in p)) return 'flow2api_video';
    return 'flow2api';
  }
  if ('api_url' in p) return 'flow2api';
  return 'openai_images';
}

const PROVIDER_TEMPLATES = {
  ...NAI_PROVIDER_TEMPLATES,
  ...VIDEO_PROVIDER_TEMPLATES,
  openai_images:          { label:'OpenAI Images', base_url:'', api_keys:[], model:'', timeout:120, max_retries:2, proxy_url:'', default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto', nai_translate_prompt:false, nai_llm_provider_id:'' },
  openai_chat:            { label:'OpenAI Chat图', base_url:'', api_keys:[], model:'', timeout:120, max_retries:2, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto', nai_translate_prompt:false, nai_llm_provider_id:'' },
  gemini_native:          { label:'Gemini 原生', api_url:'https://generativelanguage.googleapis.com', api_keys:[], model:'gemini-3-pro-image-preview', timeout:120, use_proxy:false, proxy_url:'', default_resolution:'4096x4096', generate_request_mode:'auto', edit_request_mode:'auto' },
  flow2api:               { label:'Flow2API', api_url:'', api_keys:[], model:'', timeout:120, use_proxy:false, proxy_url:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  vertex_ai_anonymous:    { label:'Vertex AI 匿名', model:'gemini-3-pro-image-preview', timeout:300, max_retries:10, proxy_url:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  grok_images:            { label:'Grok Images', base_url:'https://api.x.ai/v1', api_keys:[], model:'grok-imagine-image-quality', timeout:120, max_retries:2, proxy_url:'', default_size:'2048x2048', supports_edit:true },
  grok_images_edit:       { label:'Grok Images 改图', base_url:'https://api.x.ai/v1', api_keys:[], model:'grok-imagine-image-edit', timeout:120, max_retries:2, proxy_url:'', default_size:'2048x2048', supports_edit:true },
  grok_chat:              { label:'Grok Chat图', base_url:'https://api.x.ai/v1', api_keys:[], model:'', timeout:120, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  grok2api_images:        { label:'Grok2API Images', base_url:'', api_keys:[], model:'', timeout:120, default_size:'4096x4096', generate_request_mode:'auto', edit_request_mode:'auto' },
  gemini_openai_images:   { label:'Gemini Images', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  gemini_openai_chat:     { label:'Gemini Chat图', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  gitee_images:           { label:'Gitee Images', base_url:'https://ai.gitee.com/v1', api_keys:[], model:'z-image-turbo', timeout:300, max_retries:2, default_size:'1024x1024', num_inference_steps:9, negative_prompt:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  gitee_async:            { label:'Gitee 异步改图', base_url:'https://ai.gitee.com/v1', api_keys:[], model:'Qwen-Image-Edit-2511', num_inference_steps:4, guidance_scale:1.0, poll_interval:5, poll_timeout:300, generate_request_mode:'auto', edit_request_mode:'auto' },
  jimeng:                 { label:'即梦', api_url:'', apikey:'', cookie_list:[], default_style:'写实', default_ratio:'1:1', default_model:'Seedream 4.0', timeout:120 },
  modelscope_openai_images:{ label:'魔搭 Images', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'1024x1024', supports_edit:false, generate_request_mode:'auto', edit_request_mode:'auto' },
  openai_full_url_images: { label:'OpenAI ImagesURL', full_generate_url:'', full_edit_url:'', api_keys:[], model:'', timeout:120, default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
};

const PROVIDER_NAMES = {
  xpivot_video:'Xpivot / Muse 视频（Grok 映射）',
  xai_video:'xAI 原生视频',
  nai_openai_images:'NAI OpenAI 兼容',
  nai_native:'NovelAI 原生协议中转',
  nai_gateway:'NovelAI 第三方 GET 网关',
  openai_images:'OpenAI Images',
  openai_chat:'OpenAI Chat图',
  gemini_native:'Gemini 原生',
  flow2api:'Flow2API',
  vertex_ai_anonymous:'Vertex AI 匿名',
  grok_images:'Grok Images',
  grok_images_edit:'Grok Images 改图',
  grok_chat:'Grok Chat图',
  grok2api_images:'Grok2API Images',
  gemini_openai_images:'Gemini Images',
  gemini_openai_chat:'Gemini Chat图',
  gitee_images:'Gitee Images',
  gitee_async:'Gitee 异步改图',
  jimeng:'即梦',
  agnes_video:'Agnes 视频',
  minimax_h3_video:'MiniMax H3 视频',
  openai_video:'OpenAI Videos',
  grok_video:'Grok 视频',
  grok2api_video:'Grok2API 视频',
  flow2api_video:'Flow2API 视频',
  custom_video:'自定义视频',
  modelscope_openai_images:'魔搭 Images',
  openai_full_url_images:'OpenAI ImagesURL',
};

const VIDEO_PROVIDER_TYPES = new Set(['xpivot_video', 'xai_video', 'agnes_video', 'minimax_h3_video', 'openai_video', 'grok_video', 'grok2api_video', 'flow2api_video', 'custom_video']);

export {
  inferProviderType,
  VIDEO_TEMPLATE_DEFINITIONS,
  NAI_TEMPLATE_DEFINITIONS,
  PROVIDER_TEMPLATES,
  PROVIDER_NAMES,
  VIDEO_PROVIDER_TYPES,
};
