import { normalizeOutputSize, sizeOptionsHtml } from './output_sizes.js';
import { PROVIDER_TEMPLATES } from './provider_catalog.js';

const modes = ['auto', 'stream', 'non_stream'];

const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

function buildField(id, label, t = 'text', val = '', hint = '') {
  return `<div class="pform-group"><label class="pform-label">${label}${hint ? `<span class="hint">${hint}</span>` : ''}</label><input type="${t}" class="inp full" id="pf-${id}" value="${esc(String(val ?? ''))}"/></div>`;
}

function buildTextareaField(id, label, val = '', hint = '') {
  return `<div class="pform-group pform-full"><label class="pform-label">${label}${hint ? `<span class="hint">${hint}</span>` : ''}</label><textarea class="ta" id="pf-${id}" rows="3">${esc(Array.isArray(val) ? val.join('\n') : String(val ?? ''))}</textarea></div>`;
}

function buildSelectField(id, label, opts, val = '') {
  return `<div class="pform-group"><label class="pform-label">${label}</label><select class="sel" id="pf-${id}">${opts.map(o => `<option value="${o}" ${o === val ? 'selected' : ''}>${o}</option>`).join('')}</select></div>`;
}

function buildSizeField(id, label, val = '') {
  return `<div class="pform-group"><label class="pform-label">${label}</label><select class="sel" id="pf-${id}">${sizeOptionsHtml(val)}</select></div>`;
}

function buildCheckField(id, label, val = false) {
  return `<div class="pform-group" style="flex-direction:row;align-items:center;gap:8px;"><input type="checkbox" class="toggle" id="pf-${id}" ${val ? 'checked' : ''}/>  <label class="pform-label" for="pf-${id}" style="margin:0">${label}</label></div>`;
}

export function buildProviderForm(p) {
  const type = p.__type || 'openai_images';
  const hasField = k => PROVIDER_TEMPLATES[type] && (k in PROVIDER_TEMPLATES[type] || k === 'id' || k === '__type');
  const rows = [`<input type="hidden" id="pf-__type" value="${esc(type)}"/>`, `<div class="pform-grid">`,
    buildField('id', '服务商 ID (唯一)', 'text', p.id || '', '英文/数字/下划线'),
    buildField('label', '显示名称（可选）', 'text', p.label || '')
  ];
  if (hasField('api_url')) rows.push(buildField('api_url', 'API URL', 'text', p.api_url || ''));
  if (hasField('base_url')) rows.push(buildField('base_url', 'Base URL', 'text', p.base_url || ''));
  if (hasField('full_generate_url')) rows.push(buildField('full_generate_url', '文生图完整 URL', 'text', p.full_generate_url || ''));
  if (hasField('full_edit_url')) rows.push(buildField('full_edit_url', '改图完整 URL', 'text', p.full_edit_url || ''));
  if (hasField('model')) rows.push(buildField('model', '模型名称', 'text', p.model || ''));
  if (hasField('apikey')) rows.push(buildField('apikey', 'API Key', 'text', p.apikey || ''));
  rows.push('</div>');
  if (hasField('api_keys')) rows.push(buildTextareaField('api_keys', 'API Key 池（每行一个）', p.api_keys || []));
  if (hasField('cookie_list')) rows.push(buildTextareaField('cookie_list', 'cookie_list（每行一条）', p.cookie_list || []));
  rows.push('<div class="pform-grid">');
  if (hasField('timeout')) rows.push(buildField('timeout', '超时(秒)', 'number', p.timeout ?? 120));
  if (hasField('timeout_seconds')) rows.push(buildField('timeout_seconds', '超时(秒)', 'number', p.timeout_seconds ?? 180));
  if (hasField('max_retries')) {
    const hint = '额外重试次数（=不重试共1次，2=最多3次）';
    rows.push(buildField('max_retries', '最多重试次数', 'number', p.max_retries ?? 2, hint));
  }
  if (hasField('default_size')) rows.push(buildSizeField('default_size', '默认输出尺寸', p.default_size || '4096x4096'));
  if (hasField('default_resolution')) rows.push(buildSizeField('default_resolution', '默认分辨率', p.default_resolution || '4096x4096'));
  if (hasField('generate_request_mode')) rows.push(buildSelectField('generate_request_mode', '文生图请求模式', modes, p.generate_request_mode || 'auto'));
  if (hasField('edit_request_mode')) rows.push(buildSelectField('edit_request_mode', '改图请求模式', modes, p.edit_request_mode || 'auto'));
  if (hasField('supports_edit')) rows.push(buildCheckField('supports_edit', '支持改图', p.supports_edit !== false));
  if (hasField('use_proxy')) rows.push(buildCheckField('use_proxy', '启用代理', p.use_proxy || false));
  if (hasField('num_inference_steps')) rows.push(buildField('num_inference_steps', '推理步数', 'number', p.num_inference_steps ?? 9));
  if (hasField('guidance_scale')) rows.push(buildField('guidance_scale', '引导系数', 'number', p.guidance_scale ?? 1.0));
  if (hasField('poll_interval')) rows.push(buildField('poll_interval', '轮询间隔(秒)', 'number', p.poll_interval ?? 5));
  if (hasField('poll_timeout')) rows.push(buildField('poll_timeout', '轮询超时(秒)', 'number', p.poll_timeout ?? 300));
  if (hasField('seconds')) {
    if (type === 'openai_video') rows.push(buildField('seconds', '视频时长(秒)', 'number', p.seconds || '4'));
    else rows.push(buildSelectField('seconds', '视频时长(秒)', ['4','5','6','7','8','9','10','11','12'], String(p.seconds || '5')));
  }
  if (hasField('duration')) rows.push(buildSelectField('duration', '视频时长(秒)', ['4','5','6','7','8','9','10','11','12','13','14','15'], String(p.duration || '5')));
  if (hasField('aspect_ratio')) rows.push(buildSelectField('aspect_ratio', '视频画幅', ['21:9','16:9','4:3','1:1','3:4','9:16'], p.aspect_ratio || '16:9'));
  if (hasField('resolution')) rows.push(buildSelectField('resolution', '视频分辨率', ['768P','2K'], p.resolution || '2K'));
  if (hasField('ratio')) rows.push(buildSelectField('ratio', '视频画幅', ['adaptive','21:9','16:9','4:3','1:1','3:4','9:16'], p.ratio || '16:9'));
  if (hasField('size')) rows.push(buildField('size', '视频尺寸（可选）', 'text', p.size || '', '如 1280x720；留空使用服务商默认'));
  if (hasField('input_reference_field')) rows.push(buildField('input_reference_field', '参考图字段名', 'text', p.input_reference_field || 'input_reference'));
  if (hasField('max_download_mb')) rows.push(buildField('max_download_mb', '最大下载大小(MB)', 'number', p.max_download_mb ?? 500));
  if (hasField('image_handling_method')) {
    const imageMethods = type === 'minimax_h3_video' ? ['data_uri','astrbot','disabled'] : ['auto','astrbot','third_party','free_public','disabled'];
    rows.push(buildSelectField('image_handling_method', '本地参考图处理', imageMethods, p.image_handling_method || imageMethods[0]));
  }
  if (hasField('default_style')) rows.push(buildField('default_style', '默认风格', 'text', p.default_style || '写实'));
  if (hasField('default_ratio')) rows.push(buildField('default_ratio', '默认比例', 'text', p.default_ratio || '1:1'));
  if (hasField('default_model')) rows.push(buildField('default_model', '默认模型', 'text', p.default_model || 'Seedream 4.0'));
  if (hasField('api_key')) rows.push(buildField('api_key', 'API Key', 'text', p.api_key || ''));
  if (hasField('empty_response_retry')) rows.push(buildField('empty_response_retry', '无视频URL重试次数', 'number', p.empty_response_retry ?? 2));
  if (hasField('retry_delay')) rows.push(buildField('retry_delay', '重试间隔(秒)', 'number', p.retry_delay ?? 2));
  rows.push('</div>');
  if (hasField('file_service_base_url')) rows.push(buildField('file_service_base_url', 'AstrBot 文件服务公网地址', 'text', p.file_service_base_url || ''));
  if (hasField('enable_file_service_magic')) rows.push(buildCheckField('enable_file_service_magic', '允许文件 token 在有效期内重复访问', p.enable_file_service_magic !== false));
  if (hasField('third_party_upload_url')) rows.push(buildField('third_party_upload_url', '第三方图床上传 URL', 'text', p.third_party_upload_url || ''));
  if (hasField('third_party_token')) rows.push(buildField('third_party_token', '第三方图床 Token', 'password', p.third_party_token || ''));
  if (hasField('proxy_url')) rows.push(buildTextareaField('proxy_url', '代理地址（可选）', p.proxy_url || '').replace('rows="3"', 'rows="1"'));
  if (hasField('negative_prompt')) rows.push(buildTextareaField('negative_prompt', '负面提示词', p.negative_prompt || ''));
  if (hasField('system_prompt')) rows.push(buildTextareaField('system_prompt', '系统提示词（可选）', p.system_prompt || ''));
  if (hasField('presets')) rows.push(buildTextareaField('presets', '预设提示词（每行格式: 名称:英文提示词）', p.presets || [], '如: 电影感:cinematic lighting, epic'));
  if (hasField('generate_path')) rows.push(buildField('generate_path', '生成接口路径', 'text', p.generate_path || '/v1/chat/completions'));
  if (hasField('poll_path')) rows.push(buildField('poll_path', '轮询路径（为空不轮询）', 'text', p.poll_path || '', '如 /v1/tasks/{task_id}'));
  if (hasField('response_url_path')) rows.push(buildField('response_url_path', '视频URL路径', 'text', p.response_url_path || '', '如 data.0.url'));
  if (hasField('task_id_path')) rows.push(buildField('task_id_path', 'task_id路径', 'text', p.task_id_path || '', '如 id'));
  if (hasField('status_path')) rows.push(buildField('status_path', '状态字段路径', 'text', p.status_path || '', '如 status'));
  if (hasField('done_statuses')) rows.push(buildField('done_statuses', '完成状态值（逗号分隔）', 'text', p.done_statuses || 'succeeded,completed,done,finished,success'));
  if (hasField('fail_statuses')) rows.push(buildField('fail_statuses', '失败状态值（逗号分隔）', 'text', p.fail_statuses || 'failed,error,cancelled'));
  if (hasField('image_field')) rows.push(buildField('image_field', '图片字段名', 'text', p.image_field || 'image'));
  if (hasField('request_mode')) rows.push(buildSelectField('request_mode', '请求模式', ['auto', 'json', 'multipart'], p.request_mode || 'auto'));
  if (hasField('extra_body')) rows.push(buildTextareaField('extra_body', '额外请求体（JSON，可选）', p.extra_body || ''));
  if (hasField('extra_form')) rows.push(buildTextareaField('extra_form', '额外表单字段（JSON，可选）', p.extra_form || ''));
  return rows.join('');
}

export function readProviderForm($) {
  const type = $('pf-__type')?.value || 'openai_images';
  const tpl = PROVIDER_TEMPLATES[type] || {};
  const has = k => k in tpl || k === 'id' || k === 'label' || k === '__type';
  const g = id => $(`pf-${id}`)?.value?.trim() ?? '';
  const gCk = id => !!$(`pf-${id}`)?.checked;
  const gList = id => ($(`pf-${id}`)?.value || '').split('\n').map(s => s.trim()).filter(Boolean);
  const gNum = (id, d) => {
    const v = parseFloat($(`pf-${id}`)?.value);
    return Number.isNaN(v) ? d : v;
  };

  const result = { __type: type, __template_key: type, id: g('id'), label: g('label') };
  if (has('api_url')) result.api_url = g('api_url');
  if (has('base_url')) result.base_url = g('base_url');
  if (has('full_generate_url')) result.full_generate_url = g('full_generate_url');
  if (has('full_edit_url')) result.full_edit_url = g('full_edit_url');
  if (has('model')) result.model = g('model');
  if (has('api_keys')) result.api_keys = gList('api_keys');
  if (has('apikey')) result.apikey = g('apikey');
  if (has('api_key')) result.api_key = g('api_key');
  if (has('cookie_list')) result.cookie_list = gList('cookie_list');
  if (has('timeout')) result.timeout = gNum('timeout', 120);
  if (has('timeout_seconds')) result.timeout_seconds = gNum('timeout_seconds', 180);
  if (has('max_retries')) result.max_retries = gNum('max_retries', 2);
  if (has('default_size')) result.default_size = normalizeOutputSize(g('default_size'));
  if (has('default_resolution')) result.default_resolution = normalizeOutputSize(g('default_resolution'));
  if (has('supports_edit')) result.supports_edit = gCk('supports_edit');
  if (has('generate_request_mode')) result.generate_request_mode = g('generate_request_mode');
  if (has('edit_request_mode')) result.edit_request_mode = g('edit_request_mode');
  if (has('use_proxy')) result.use_proxy = gCk('use_proxy');
  if (has('proxy_url')) result.proxy_url = g('proxy_url');
  if (has('num_inference_steps')) result.num_inference_steps = gNum('num_inference_steps', 9);
  if (has('guidance_scale')) result.guidance_scale = gNum('guidance_scale', 1.0);
  if (has('poll_interval')) result.poll_interval = gNum('poll_interval', 5);
  if (has('poll_timeout')) result.poll_timeout = gNum('poll_timeout', 300);
  if (has('seconds')) result.seconds = g('seconds');
  if (has('duration')) result.duration = g('duration');
  if (has('aspect_ratio')) result.aspect_ratio = g('aspect_ratio');
  if (has('resolution')) result.resolution = g('resolution');
  if (has('ratio')) result.ratio = g('ratio');
  if (has('size')) result.size = g('size');
  if (has('input_reference_field')) result.input_reference_field = g('input_reference_field');
  if (has('max_download_mb')) result.max_download_mb = gNum('max_download_mb', 500);
  if (has('image_handling_method')) result.image_handling_method = g('image_handling_method');
  if (has('file_service_base_url')) result.file_service_base_url = g('file_service_base_url');
  if (has('enable_file_service_magic')) result.enable_file_service_magic = gCk('enable_file_service_magic');
  if (has('default_style')) result.default_style = g('default_style');
  if (has('default_ratio')) result.default_ratio = g('default_ratio');
  if (has('default_model')) result.default_model = g('default_model');
  if (has('negative_prompt')) result.negative_prompt = g('negative_prompt');
  if (has('system_prompt')) result.system_prompt = g('system_prompt');
  if (has('empty_response_retry')) result.empty_response_retry = gNum('empty_response_retry', 2);
  if (has('retry_delay')) result.retry_delay = gNum('retry_delay', 2);
  if (has('third_party_upload_url')) result.third_party_upload_url = g('third_party_upload_url');
  if (has('third_party_token')) result.third_party_token = g('third_party_token');
  if (has('presets')) result.presets = g('presets').split('\n').map(s => s.trim()).filter(Boolean);
  if (has('generate_path')) result.generate_path = g('generate_path');
  if (has('poll_path')) result.poll_path = g('poll_path');
  if (has('response_url_path')) result.response_url_path = g('response_url_path');
  if (has('task_id_path')) result.task_id_path = g('task_id_path');
  if (has('status_path')) result.status_path = g('status_path');
  if (has('done_statuses')) result.done_statuses = g('done_statuses');
  if (has('fail_statuses')) result.fail_statuses = g('fail_statuses');
  if (has('image_field')) result.image_field = g('image_field');
  if (has('request_mode')) result.request_mode = g('request_mode');
  if (has('extra_body')) result.extra_body = g('extra_body');
  if (has('extra_form')) result.extra_form = g('extra_form');
  return result;
}
