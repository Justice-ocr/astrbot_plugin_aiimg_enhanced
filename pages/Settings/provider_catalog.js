function inferProviderType(p) {
  if (!p || typeof p !== 'object') return 'openai_images';
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
  nai_native: { label:'NovelAI 原生协议中转', base_url:'', api_keys:[], model:'nai-diffusion-4-5-full', timeout:120, default_size:'832x1216', nai_reference_mode:'img2img', nai_strength:0.6, nai_vibe_information:1, nai_translate_prompt:false, nai_llm_provider_id:'', nai_prompt_prefix:'', nai_artist:'', negative_prompt:'', nai_sampler:'k_euler_ancestral', num_inference_steps:28, guidance_scale:5, nai_cfg:0, nai_noise_schedule:'karras', seed:'', proxy_url:'' },
  nai_gateway: { label:'NovelAI 第三方 GET 网关', base_url:'', generate_path:'/generate', api_keys:[], model:'nai-diffusion-4-5-full', timeout:120, default_size:'832x1216', nai_auth_mode:'token', nai_translate_prompt:false, nai_llm_provider_id:'', nai_prompt_prefix:'', nai_artist:'', negative_prompt:'', nai_sampler:'', num_inference_steps:28, guidance_scale:5, nai_cfg:'', nai_noise_schedule:'', seed:'', proxy_url:'', extra_body:'' },
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
  agnes_video:            { label:'Agnes 视频', base_url:'https://apihub.agnes-ai.com/v1', api_keys:[], model:'agnes-video-2.5-flash', timeout:120, max_retries:1, poll_interval:2, poll_timeout:900, seconds:'5', aspect_ratio:'16:9', image_handling_method:'auto', file_service_base_url:'', enable_file_service_magic:true, third_party_upload_url:'', third_party_token:'', proxy_url:'' },
  minimax_h3_video:       { label:'MiniMax H3 视频', base_url:'https://api.minimax.io', api_keys:[], model:'MiniMax-H3', timeout:120, max_retries:1, poll_interval:10, poll_timeout:1200, duration:'5', resolution:'2K', ratio:'16:9', image_handling_method:'data_uri', file_service_base_url:'', enable_file_service_magic:true, proxy_url:'' },
  openai_video:           { label:'OpenAI Videos', base_url:'https://api.openai.com', api_keys:[], model:'sora-2', timeout:300, max_retries:1, poll_interval:10, poll_timeout:1200, seconds:'4', size:'', video_resolution:'', seed:'', image_input_mode:'auto', input_reference_field:'input_reference', max_download_mb:500, extra_form:'', proxy_url:'' },
  grok_video:             { label:'Grok 视频', server_url:'https://api.x.ai', api_key:'', model:'grok-imagine-0.9', timeout_seconds:180, max_retries:2, empty_response_retry:2, retry_delay:2, presets:[] },
  grok2api_video:         { label:'Grok2API 视频', base_url:'https://api.x.ai', api_keys:[], model:'grok-imagine-1.0-video', timeout:300, max_retries:2 },
  flow2api_video:         { label:'Flow2API 视频', api_url:'', api_keys:[], model:'', timeout:300, use_proxy:false, proxy_url:'' },
  custom_video:           { label:'自定义视频', base_url:'', generate_path:'/v1/chat/completions', poll_path:'', api_keys:[], model:'', timeout:300, max_retries:0, poll_interval:5, poll_timeout:300, response_url_path:'', task_id_path:'', status_path:'', done_statuses:'succeeded,completed,done,finished,success', fail_statuses:'failed,error,cancelled', extra_body:'', request_mode:'auto', image_field:'image', proxy_url:'' },
  modelscope_openai_images:{ label:'魔搭 Images', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'1024x1024', supports_edit:false, generate_request_mode:'auto', edit_request_mode:'auto' },
  openai_full_url_images: { label:'OpenAI ImagesURL', full_generate_url:'', full_edit_url:'', api_keys:[], model:'', timeout:120, default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
};

const PROVIDER_NAMES = {
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

const VIDEO_PROVIDER_TYPES = new Set(['agnes_video', 'minimax_h3_video', 'openai_video', 'grok_video', 'grok2api_video', 'flow2api_video', 'custom_video']);

export {
  inferProviderType,
  PROVIDER_TEMPLATES,
  PROVIDER_NAMES,
  VIDEO_PROVIDER_TYPES,
};
