'use strict';

// ── Provider类型推断 ─────────────────────────────────────────────────────────
function inferProviderType(p) {
  if (!p || typeof p !== 'object') return 'openai_images';
  if ('poll_interval' in p || 'poll_timeout' in p) return 'gitee_async';
  if ('cookie_list' in p || 'apikey' in p) return 'jimeng';
  if ('recaptcha_base_api' in p || 'graphql_api_key' in p) return 'vertex_ai_anonymous';
  if ('server_url' in p && 'empty_response_retry' in p) return 'grok_video';
  if ('full_generate_url' in p) return 'openai_full_url_images';
  if ('num_inference_steps' in p && 'negative_prompt' in p) return 'gitee_images';
  const bu = String(p.base_url || p.api_url || '');
  if (bu.includes('generativelanguage.googleapis.com')) return 'gemini_native';
  // grok_video: server_url 字段是独有标志
  if ('server_url' in p && 'api_key' in p) return 'grok_video';
  if ('server_url' in p) return 'grok_video';
  // grok2api_video 必须在 x.ai 通用判断之前：base_url含x.ai + api_keys + 无use_proxy + 无generate_path
  if (bu.includes('x.ai') && 'api_keys' in p && !('use_proxy' in p) && !('generate_path' in p)) return 'grok2api_video';
  // grok_chat/grok_images
  if (bu.includes('x.ai')) return ('use_proxy' in p && !('supports_edit' in p) && !(p.api_keys && p.api_keys.length)) ? 'grok_chat' : 'grok_images';
  if (bu.includes('gitee.com')) return 'gitee_images';
  const m = String(p.model || '');
  if (m.startsWith('gemini')) return 'gemini_openai_images';
  if ('supports_edit' in p) return 'openai_images';
  // flow2api_video: api_url + 无base_url + 无generate_path + 有model
  // flow2api_video: api_url + api_keys/api_key + 无 base_url + 无 generate_path
  if ('api_url' in p && !('base_url' in p) && !('generate_path' in p) && !('num_inference_steps' in p) && !('cookie_list' in p)) {
    // 视频：有 model 但无 generate_request_mode
    if ('model' in p && !('generate_request_mode' in p) && !('edit_request_mode' in p)) return 'flow2api_video';
    return 'flow2api';
  }
  if ('api_url' in p) return 'flow2api';
  return 'openai_images';
}

// ── 工具 ─────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const asInt = (v,d) => { const n=parseInt(v); return isNaN(n)?d:n; };
const asBool = v => typeof v==='boolean'?v: String(v||'').toLowerCase()==='true';

// ── Bridge ───────────────────────────────────────────────────────────────────
const bridge = window.AstrBotPluginPage || {
  ready: async () => ({}),
  apiGet: async (name) => {
    if (name !== 'get_config') return { success: false };
    return { success: true, config: {
      features: {
        draw:   { enabled:true, llm_tool_enabled:true, default_output:'1024x1024', batch_concurrency:2,
                  chain:[{provider_id:'gitee',output:''}] },
        edit:   { enabled:true, llm_tool_enabled:true, default_output:'4K', batch_concurrency:2,
                  chain:[{provider_id:'gitee_async',output:''}] },
        selfie: { enabled:true, llm_tool_enabled:true, default_output:'4K',
                  use_edit_chain_when_empty:true, prompt_prefix:'',
                  chain:[] },
        video:  { enabled:false, llm_tool_enabled:true, send_mode:'auto',
                  send_timeout_seconds:90, download_timeout_seconds:300,
                  presets:[], chain:[] },
        batch:  { max_count:8 },
      },
      storage:{ max_cached_images:50, max_cached_videos:20 },
      debounce_interval:10, max_user_concurrency:2, max_user_video_concurrency:1,
      network:{ media_allow_private:false, max_image_bytes:52428800, max_video_bytes:52428800, max_redirects:5, dns_resolve_timeout_seconds:2 },
      providers:[
        { id:'gitee', __type:'gitee_images', label:'Gitee Images', base_url:'https://ai.gitee.com/v1', model:'z-image-turbo' },
        { id:'gitee_async', __type:'gitee_async', label:'Gitee 异步改图', base_url:'https://ai.gitee.com/v1', model:'Qwen-Image-Edit-2511' },
      ],
      persona_config:{ active_persona_id:'default', profiles:[
        { id:'default', persona_name:'默认助理', persona_base_prompt:'', persona_ref_image:[] },
      ]},
      reply_config:{ draw_pending_message:'', selfie_pending_message:'', verbose_report:false },
    }};
  },
  apiPost: async (name, payload) => {
    console.info('[mock]', name, payload);
    if (name === 'switch_persona') return { success:true, active:{id:payload.id,name:payload.id} };
    return { success:true };
  },
};

// ── P_TEMPLATES ───────────────────────────────────────────────────────────────
const P_TEMPLATES = {
  openai_images:          { label:'OpenAI Images', base_url:'', api_keys:[], model:'', timeout:120, max_retries:2, proxy_url:'', default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  openai_chat:            { label:'OpenAI Chat图', base_url:'', api_keys:[], model:'', timeout:120, max_retries:2, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  gemini_native:          { label:'Gemini 原生', api_url:'https://generativelanguage.googleapis.com', api_keys:[], model:'gemini-3-pro-image-preview', timeout:120, use_proxy:false, proxy_url:'', default_resolution:'4K', generate_request_mode:'auto', edit_request_mode:'auto' },
  flow2api:               { label:'Flow2API', api_url:'', api_keys:[], model:'', timeout:120, use_proxy:false, proxy_url:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  vertex_ai_anonymous:    { label:'Vertex AI 匿名', model:'gemini-3-pro-image-preview', timeout:300, max_retries:10, proxy_url:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  grok_images:            { label:'Grok Images', base_url:'https://api.x.ai/v1', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  grok_chat:              { label:'Grok Chat图', base_url:'https://api.x.ai/v1', api_keys:[], model:'', timeout:120, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  grok2api_images:        { label:'Grok2API Images', base_url:'', api_keys:[], model:'', timeout:120, default_size:'4096x4096', generate_request_mode:'auto', edit_request_mode:'auto' },
  gemini_openai_images:   { label:'Gemini Images', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  gemini_openai_chat:     { label:'Gemini Chat图', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
  gitee_images:           { label:'Gitee Images', base_url:'https://ai.gitee.com/v1', api_keys:[], model:'z-image-turbo', timeout:300, max_retries:2, default_size:'1024x1024', num_inference_steps:9, negative_prompt:'', generate_request_mode:'auto', edit_request_mode:'auto' },
  gitee_async:            { label:'Gitee 异步改图', base_url:'https://ai.gitee.com/v1', api_keys:[], model:'Qwen-Image-Edit-2511', num_inference_steps:4, guidance_scale:1.0, poll_interval:5, poll_timeout:300, generate_request_mode:'auto', edit_request_mode:'auto' },
  jimeng:                 { label:'即梦', api_url:'', apikey:'', cookie_list:[], default_style:'真实', default_ratio:'1:1', default_model:'Seedream 4.0', timeout:120 },
  grok_video:             { label:'Grok 视频', server_url:'https://api.x.ai', api_key:'', model:'grok-imagine-0.9', timeout_seconds:180, max_retries:2, empty_response_retry:2, retry_delay:2, presets:[] },
  grok2api_video:         { label:'Grok2API 视频', base_url:'https://api.x.ai', api_keys:[], model:'grok-imagine-1.0-video', timeout:300, max_retries:2 },
  flow2api_video:         { label:'Flow2API 视频', api_url:'', api_keys:[], model:'', timeout:300, use_proxy:false, proxy_url:'' },
  custom_video:           { label:'自定义视频', base_url:'', generate_path:'/v1/chat/completions', poll_path:'', api_keys:[], model:'', timeout:300, max_retries:0, poll_interval:5, poll_timeout:300, response_url_path:'', task_id_path:'', status_path:'', done_statuses:'succeeded,completed,done,finished,success', fail_statuses:'failed,error,cancelled', extra_body:'', request_mode:'auto', image_field:'image', proxy_url:'' },
  modelscope_openai_images:{ label:'魔搭 Images', base_url:'', api_keys:[], model:'', timeout:120, proxy_url:'', default_size:'1024x1024', supports_edit:false, generate_request_mode:'auto', edit_request_mode:'auto' },
  openai_full_url_images: { label:'OpenAI ImagesURL', full_generate_url:'', full_edit_url:'', api_keys:[], model:'', timeout:120, default_size:'4096x4096', supports_edit:true, generate_request_mode:'auto', edit_request_mode:'auto' },
};
const P_NAMES = {
  openai_images:'OpenAI Images', openai_chat:'OpenAI Chat图', gemini_native:'Gemini 原生',
  flow2api:'Flow2API', vertex_ai_anonymous:'Vertex AI 匿名', grok_images:'Grok Images',
  grok_chat:'Grok Chat图', grok2api_images:'Grok2API Images', gemini_openai_images:'Gemini Images',
  gemini_openai_chat:'Gemini Chat图', gitee_images:'Gitee Images', gitee_async:'Gitee 异步改图',
  jimeng:'即梦', grok_video:'Grok 视频', grok2api_video:'Grok2API 视频', flow2api_video:'Flow2API 视频', custom_video:'自定义视频',
  modelscope_openai_images:'魔搭 Images', openai_full_url_images:'OpenAI ImagesURL',
};

// ── 状态 ─────────────────────────────────────────────────────────────────────
let S = {
  features:{}, storage:{}, debounce_interval:10,
  max_user_concurrency:2, max_user_video_concurrency:1, network:{},
  providers:[],
  // chain状态单独存，key: 'draw'|'edit'|'selfie'|'video'
  chains:{ draw:[], edit:[], selfie:[], video:[] },
  persona_config:{ active_persona_id:'default', profiles:[] },
  reply_config:{},
  draw_presets:[], edit_presets:[], video_presets:[],
  dirty:false,
};

function showToast(msg, type='ok') {
  const el=$('toast'); el.textContent=msg; el.className=`toast ${type}`; el.style.display='block';
  clearTimeout(el._t); el._t=setTimeout(()=>el.style.display='none',3000);
}
function markDirty() {
  if(S.dirty)return; S.dirty=true;
  $('save-hint').textContent='有未保存的更改'; $('save-hint').className='save-hint dirty';
}
function markClean(msg='配置已同步') {
  S.dirty=false; $('save-hint').textContent=msg; $('save-hint').className='save-hint';
}

// ── Tab切换 ──────────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      btn.classList.add('active');
      const t=document.getElementById(btn.dataset.tab);
      if(t){ t.classList.add('active'); $('topbar-title').textContent=btn.textContent.replace(/^[^ ]+ /,''); }
    });
  });
}

// ── 链路选择器 ───────────────────────────────────────────────────────────────
// 视频服务商类型集合
const VIDEO_PROVIDER_TYPES = new Set(['grok_video', 'grok2api_video', 'flow2api_video', 'custom_video']);

// chain是 [{provider_id, output?}] 的数组，第一个是主用，后续是备用
function renderChain(containerId, chainKey, hasOutput=true) {
  const el = $(containerId);
  if (!el) return;
  const chain = S.chains[chainKey] || [];
  const isVideo = chainKey === 'video';
  const providerIds = S.providers
    .filter(p => isVideo ? VIDEO_PROVIDER_TYPES.has(p.__type) : !VIDEO_PROVIDER_TYPES.has(p.__type))
    .map(p => p.id).filter(Boolean);

  let html = '<div class="chain-list">';

  if (!chain.length) {
    html += '<div class="chain-empty">未配置服务商链路，将使用系统默认行为</div>';
  } else {
    chain.forEach((item, idx) => {
      const isFirst = idx === 0;
      html += `<div class="chain-item" data-chain="${chainKey}" data-idx="${idx}">
        <span class="chain-order">${isFirst ? '主' : '备'}</span>
        <select class="sel chain-pid" data-chain="${chainKey}" data-idx="${idx}">
          <option value="">-- 选择服务商 --</option>
          ${providerIds.map(id => `<option value="${esc(id)}" ${id===item.provider_id?'selected':''}>${esc(id)}</option>`).join('')}
        </select>
        ${hasOutput ? `<input type="text" class="inp chain-output" placeholder="输出尺寸（留空默认）" value="${esc(item.output||'')}" data-chain="${chainKey}" data-idx="${idx}" title="覆盖输出尺寸，如 4K 或 1024x1024，留空使用功能默认值"/>` : ''}
        <div class="chain-btns">
          ${idx>0 ? `<button class="chain-btn" data-chain="${chainKey}" data-act="up" data-idx="${idx}" title="上移">↑</button>` : ''}
          ${idx<chain.length-1 ? `<button class="chain-btn" data-chain="${chainKey}" data-act="down" data-idx="${idx}" title="下移">↓</button>` : ''}
          <button class="chain-btn danger" data-chain="${chainKey}" data-act="del" data-idx="${idx}" title="移除">✕</button>
        </div>
      </div>`;
    });
  }

  html += '</div>';
  // 添加按钮
  if (providerIds.length) {
    html += `<button class="btn-add-chain" data-chain="${chainKey}" data-has-output="${hasOutput}">+ 添加服务商</button>`;
  } else {
    html += '<div class="chain-empty" style="margin-top:6px">请先在「服务商」页配置服务商</div>';
  }
  el.innerHTML = html;

  // 绑定事件
  el.querySelectorAll('.chain-pid').forEach(sel => {
    sel.addEventListener('change', () => {
      const {chain: k, idx} = sel.dataset;
      S.chains[k][parseInt(idx)].provider_id = sel.value;
      markDirty();
    });
  });
  el.querySelectorAll('.chain-output').forEach(inp => {
    inp.addEventListener('input', () => {
      const {chain: k, idx} = inp.dataset;
      S.chains[k][parseInt(idx)].output = inp.value.trim();
      markDirty();
    });
  });
  el.querySelectorAll('[data-act]').forEach(btn => {
    btn.addEventListener('click', () => {
      const k=btn.dataset.chain, idx=parseInt(btn.dataset.idx), act=btn.dataset.act;
      const arr=S.chains[k];
      if (act==='del') { arr.splice(idx,1); }
      else if (act==='up' && idx>0) { [arr[idx-1],arr[idx]]=[arr[idx],arr[idx-1]]; }
      else if (act==='down' && idx<arr.length-1) { [arr[idx],arr[idx+1]]=[arr[idx+1],arr[idx]]; }
      renderChain(containerId, k, btn.dataset.hasOutput!=='false');
      markDirty();
    });
  });
  el.querySelectorAll('.btn-add-chain').forEach(btn => {
    btn.addEventListener('click', () => {
      const k=btn.dataset.chain;
      const hasOut = btn.dataset.hasOutput !== 'false';
      // 默认选第一个未在链路里的服务商，或直接选第一个
      const used = new Set(S.chains[k].map(i=>i.provider_id));
      const next = S.providers.find(p=>p.id&&!used.has(p.id));
      S.chains[k].push({ provider_id: next?.id||'', output:'' });
      renderChain(containerId, k, hasOut);
      markDirty();
    });
  });
}

function renderAllChains() {
  renderChain('chain-draw',   'draw',   true);
  renderChain('chain-edit',   'edit',   true);
  renderChain('chain-selfie', 'selfie', true);
  renderChain('chain-video',  'video',  false);
}

// ── 从config加载到state ───────────────────────────────────────────────────────
function applyConfig(cfg) {
  const feat = cfg.features || {};
  const draw = feat.draw || {};
  const edit = feat.edit || {};
  const selfie = feat.selfie || {};
  const video = feat.video || {};
  const batch = feat.batch || {};

  const setCk=(id,v)=>{const e=$(id);if(e)e.checked=v;};
  const setSel=(id,v)=>{const e=$(id);if(e)e.value=v;};
  const setVal=(id,v)=>{const e=$(id);if(e)e.value=v;};
  const setTa=(id,v)=>{const e=$(id);if(e)e.value=v;};

  setCk('feat-draw-enabled', asBool(draw.enabled!==false));
  setCk('feat-draw-llm', asBool(draw.llm_tool_enabled!==false));
  setSel('feat-draw-output', draw.default_output||'');
  setVal('feat-draw-batch', draw.batch_concurrency??2);

  setCk('feat-edit-enabled', asBool(edit.enabled!==false));
  setCk('feat-edit-llm', asBool(edit.llm_tool_enabled!==false));
  setSel('feat-edit-output', edit.default_output||'');
  setVal('feat-edit-batch', edit.batch_concurrency??2);

  setCk('feat-selfie-enabled', asBool(selfie.enabled!==false));
  setCk('feat-selfie-llm', asBool(selfie.llm_tool_enabled!==false));
  setSel('feat-selfie-output', selfie.default_output||'');
  setCk('feat-selfie-fallback', asBool(selfie.use_edit_chain_when_empty!==false));
  setTa('feat-selfie-prefix', selfie.prompt_prefix||'');

  setCk('feat-video-enabled', asBool(video.enabled));
  setCk('feat-video-llm', asBool(video.llm_tool_enabled!==false));
  setSel('feat-video-send', video.send_mode||'auto');
  setVal('feat-video-send-timeout', video.send_timeout_seconds??90);
  setVal('feat-video-dl-timeout', video.download_timeout_seconds??300);
  setVal('feat-batch-max', batch.max_count??8);

  // chain
  const parseChain = arr => (Array.isArray(arr)?arr:[]).map(item => ({
    provider_id: String(item.provider_id||''),
    output: String(item.output||''),
  }));
  S.chains.draw   = parseChain(draw.chain);
  S.chains.edit   = parseChain(edit.chain);
  S.chains.selfie = parseChain(selfie.chain);
  S.chains.video  = parseChain(video.chain);

  // 高级
  const net=cfg.network||{}, stor=cfg.storage||{};
  // 填充意图分类模型下拉框（从 get_config 返回的 astrbot_providers 列表）
  const intentSel = $('adv-intent-provider');
  if (intentSel && Array.isArray(cfg.astrbot_providers)) {
    // 保留第一个「不启用」选项，追加 AstrBot providers
    while (intentSel.options.length > 1) intentSel.remove(1);
    cfg.astrbot_providers.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = `${p.id}${p.model ? ' (' + p.model + ')' : ''}`;
      intentSel.appendChild(opt);
    });
  }
  // 回显已保存的值
  const savedIntent = (cfg.features?.intent_classifier?.provider_id) || '';
  if (intentSel) intentSel.value = savedIntent;
  setVal('adv-debounce', cfg.debounce_interval??10);
  setVal('adv-concur-img', cfg.max_user_concurrency??2);
  setVal('adv-concur-vid', cfg.max_user_video_concurrency??1);
  setVal('adv-cache-img', stor.max_cached_images??50);
  setVal('adv-cache-vid', stor.max_cached_videos??20);
  setCk('adv-net-private', asBool(net.media_allow_private));
  setVal('adv-net-img-bytes', net.max_image_bytes??52428800);
  setVal('adv-net-vid-bytes', net.max_video_bytes??52428800);
  setVal('adv-net-redirects', net.max_redirects??5);
  setVal('adv-net-dns', net.dns_resolve_timeout_seconds??2);

  // reply_config
  const rc=cfg.reply_config||{};
  setTa('rc-draw-pending', rc.draw_pending_message||'');
  setTa('rc-edit-pending', rc.edit_pending_message||'');
  setTa('rc-selfie-pending', rc.selfie_pending_message||'');
  setTa('rc-video-pending', rc.video_pending_message||'');
  setTa('rc-draw-error', rc.draw_error_message||'');
  setTa('rc-selfie-error', rc.selfie_error_message||'');
  setCk('rc-verbose', asBool(rc.verbose_report));

  // providers：优先从 __template_key 读取类型，再用字段特征推断
  S.providers = (Array.isArray(cfg.providers)?cfg.providers:[]).map(p => {
    if(p.__type) return p;
    if(p.__template_key) return { ...p, __type: p.__template_key };
    const t=inferProviderType(p);
    return t?{...p,__type:t}:p;
  });
  renderProviders();

  // persona
  const pc=cfg.persona_config||{};
  S.persona_config.active_persona_id = pc.active_persona_id||'default';
  S.persona_config.profiles = Array.isArray(pc.profiles)?pc.profiles:[];
  renderPersonas();

  // presets
  S.draw_presets  = (feat.draw?.presets||[]).map(parsePreset);
  S.edit_presets  = (feat.edit?.presets||[]).map(parsePreset);
  S.video_presets = (feat.video?.presets||[]).map(parsePreset);
  renderPresets('draw-presets-list', S.draw_presets, 'draw');
  renderPresets('edit-presets-list', S.edit_presets, 'edit');
  renderPresets('video-presets-list', S.video_presets, 'video');

  // 渲染chain选择器（需要在providers加载后）
  renderAllChains();
  updateStats();
}

const parsePreset = s => {
  if(typeof s==='string'&&s.includes(':')){ const[k,...r]=s.split(':'); return{name:k.trim(),prompt:r.join(':').trim()}; }
  return typeof s==='object'?s:{name:'',prompt:''};
};

// ── 读取UI到payload ──────────────────────────────────────────────────────────
function buildPayload() {
  const getCk=id=>!!$(id)?.checked;
  const getVal=id=>$(id)?.value??'';
  const getTa=id=>$(id)?.value??'';
  const getInt=(id,d)=>asInt(getVal(id),d);

  const chainToSave = (key, hasOutput=true) =>
    (S.chains[key]||[]).filter(i=>i.provider_id).map(i =>
      hasOutput ? {provider_id:i.provider_id, output:i.output||''} : {provider_id:i.provider_id}
    );

  return {
    features:{
      draw:{
        enabled:getCk('feat-draw-enabled'), llm_tool_enabled:getCk('feat-draw-llm'),
        default_output:getVal('feat-draw-output'), batch_concurrency:getInt('feat-draw-batch',2),
        chain:chainToSave('draw',true),
        presets:S.draw_presets.filter(p=>p.name).map(p=>`${p.name}:${p.prompt}`),
      },
      edit:{
        enabled:getCk('feat-edit-enabled'), llm_tool_enabled:getCk('feat-edit-llm'),
        default_output:getVal('feat-edit-output'), batch_concurrency:getInt('feat-edit-batch',2),
        chain:chainToSave('edit',true),
        presets:S.edit_presets.filter(p=>p.name).map(p=>`${p.name}:${p.prompt}`),
      },
      selfie:{
        enabled:getCk('feat-selfie-enabled'), llm_tool_enabled:getCk('feat-selfie-llm'),
        default_output:getVal('feat-selfie-output'),
        use_edit_chain_when_empty:getCk('feat-selfie-fallback'),
        prompt_prefix:getTa('feat-selfie-prefix'),
        chain:chainToSave('selfie',true),
      },
      video:{
        enabled:getCk('feat-video-enabled'), llm_tool_enabled:getCk('feat-video-llm'),
        send_mode:getVal('feat-video-send'),
        send_timeout_seconds:getInt('feat-video-send-timeout',90),
        download_timeout_seconds:getInt('feat-video-dl-timeout',300),
        chain:chainToSave('video',false),
        presets:S.video_presets.filter(p=>p.name).map(p=>`${p.name}:${p.prompt}`),
      },
      batch:{ max_count:getInt('feat-batch-max',8) },
      intent_classifier:{ provider_id: ($('adv-intent-provider')?.value||'') },
    },
    storage:{ max_cached_images:getInt('adv-cache-img',50), max_cached_videos:getInt('adv-cache-vid',20) },
    debounce_interval:getInt('adv-debounce',10),
    max_user_concurrency:getInt('adv-concur-img',2),
    max_user_video_concurrency:getInt('adv-concur-vid',1),
    network:{
      media_allow_private:getCk('adv-net-private'),
      max_image_bytes:getInt('adv-net-img-bytes',52428800),
      max_video_bytes:getInt('adv-net-vid-bytes',52428800),
      max_redirects:getInt('adv-net-redirects',5),
      dns_resolve_timeout_seconds:getInt('adv-net-dns',2),
    },
    providers:S.providers.map(p=>{const c={...p};delete c.__type;if(!c.__template_key&&p.__type)c.__template_key=p.__type;return c;}),
    persona_config:{ active_persona_id:S.persona_config.active_persona_id, profiles:S.persona_config.profiles },
    reply_config:{
      draw_pending_message:getTa('rc-draw-pending'), edit_pending_message:getTa('rc-edit-pending'),
      selfie_pending_message:getTa('rc-selfie-pending'), video_pending_message:getTa('rc-video-pending'),
      draw_error_message:getTa('rc-draw-error'), selfie_error_message:getTa('rc-selfie-error'),
      verbose_report:getCk('rc-verbose'),
    },
  };
}

// ── 统计 ─────────────────────────────────────────────────────────────────────
function updateStats() {
  $('stat-providers').textContent=S.providers.length;
  $('stat-personas').textContent=S.persona_config.profiles.length;
  $('stat-presets').textContent=S.draw_presets.length+S.edit_presets.length+S.video_presets.length;
}

// ── 服务商渲染 ────────────────────────────────────────────────────────────────
function renderProviders() {
  const el=$('providers-list');
  if(!el)return;
  if(!S.providers.length){ el.innerHTML='<div class="preset-empty">暂无服务商，选择模板后点击"添加服务商"</div>'; return; }
  el.innerHTML='';
  S.providers.forEach((p,idx)=>{
    const type=p.__type||'?';
    const div=document.createElement('div'); div.className='provider-item';
    div.innerHTML=`
      <span class="provider-tag">${esc(P_NAMES[type]||type)}</span>
      <div class="provider-info">
        <div class="pid">${esc(p.id||'(未命名)')}</div>
        <div class="pmeta">${esc(p.label||'')}${p.model?' · '+esc(p.model):''}${(p.base_url||p.api_url)?' · '+(p.base_url||p.api_url).slice(0,40):''}</div>
      </div>
      <div class="provider-actions">
        <button class="btn-ghost btn-sm" data-act="edit" data-idx="${idx}">编辑</button>
        <button class="btn-danger" data-act="del" data-idx="${idx}">删除</button>
      </div>`;
    el.appendChild(div);
  });
  el.querySelectorAll('[data-act]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const idx=parseInt(btn.dataset.idx);
      if(btn.dataset.act==='edit') openProviderModal(idx);
      else if(btn.dataset.act==='del'){ S.providers.splice(idx,1); renderProviders(); renderAllChains(); updateStats(); markDirty(); }
    });
  });
}

// ── 服务商弹窗 ────────────────────────────────────────────────────────────────
let _provIdx=-1;
function openProviderModal(idx) {
  _provIdx=idx;
  const isNew=idx<0;
  $('modal-provider-title').textContent=isNew?'新建服务商':'编辑服务商';
  const p=isNew?{id:'',__type:$('provider-template-sel').value,...P_TEMPLATES[$('provider-template-sel').value]}:S.providers[idx];
  $('provider-modal-body').innerHTML=buildProviderForm(p);
  $('provider-modal').style.display='flex';
}
function buildProviderForm(p) {
  const type=p.__type||'openai_images';
  const hasField=k=>P_TEMPLATES[type]&&(k in P_TEMPLATES[type]||k==='id'||k==='__type');
  const fld=(id,label,t='text',val='',hint='')=>`<div class="pform-group"><label class="pform-label">${label}${hint?`<span class="hint">${hint}</span>`:''}</label><input type="${t}" class="inp full" id="pf-${id}" value="${esc(String(val??''))}"/></div>`;
  const fldTA=(id,label,val='',hint='')=>`<div class="pform-group pform-full"><label class="pform-label">${label}${hint?`<span class="hint">${hint}</span>`:''}</label><textarea class="ta" id="pf-${id}" rows="3">${esc(Array.isArray(val)?val.join('\n'):String(val??''))}</textarea></div>`;
  const fldSel=(id,label,opts,val='')=>`<div class="pform-group"><label class="pform-label">${label}</label><select class="sel" id="pf-${id}">${opts.map(o=>`<option value="${o}" ${o===val?'selected':''}>${o}</option>`).join('')}</select></div>`;
  const fldCk=(id,label,val=false)=>`<div class="pform-group" style="flex-direction:row;align-items:center;gap:8px;"><input type="checkbox" class="toggle" id="pf-${id}" ${val?'checked':''}/>  <label class="pform-label" for="pf-${id}" style="margin:0">${label}</label></div>`;
  const modes=['auto','stream','non_stream'];
  const rows=[`<input type="hidden" id="pf-__type" value="${esc(type)}"/>`,`<div class="pform-grid">`,
    fld('id','服务商 ID (唯一)','text',p.id||'','英文/数字/下划线'), fld('label','显示名称（可选）','text',p.label||'')];
  if(hasField('api_url'))  rows.push(fld('api_url','API URL','text',p.api_url||''));
  if(hasField('base_url')) rows.push(fld('base_url','Base URL','text',p.base_url||''));
  if(hasField('full_generate_url')) rows.push(fld('full_generate_url','文生图完整 URL','text',p.full_generate_url||''));
  if(hasField('full_edit_url'))     rows.push(fld('full_edit_url','改图完整 URL','text',p.full_edit_url||''));
  if(hasField('model'))  rows.push(fld('model','模型名称','text',p.model||''));
  if(hasField('apikey')) rows.push(fld('apikey','API Key','text',p.apikey||''));
  rows.push('</div>');
  if(hasField('api_keys'))   rows.push(fldTA('api_keys','API Key 池（每行一个）',p.api_keys||[]));
  if(hasField('cookie_list'))rows.push(fldTA('cookie_list','cookie_list（每行一条）',p.cookie_list||[]));
  rows.push('<div class="pform-grid">');
  if(hasField('timeout'))        rows.push(fld('timeout','超时(秒)','number',p.timeout??120));
  if(hasField('timeout_seconds'))rows.push(fld('timeout_seconds','超时(秒)','number',p.timeout_seconds??180));
  if(hasField('max_retries')) {
    const isGrok = type==='grok_images';
    const hint = isGrok ? '总请求次数（grok_images专用语义，2=最多2次）' : '额外重试次数（0=不重试共1次，2=最多3次）';
    rows.push(fld('max_retries','最大重试次数','number',p.max_retries??2,hint));
  }
  if(hasField('default_size'))   rows.push(fld('default_size','默认输出尺寸','text',p.default_size||'4096x4096'));
  if(hasField('default_resolution'))rows.push(fldSel('default_resolution','默认分辨率',['1K','2K','4K'],p.default_resolution||'4K'));
  if(hasField('generate_request_mode'))rows.push(fldSel('generate_request_mode','文生图请求模式',modes,p.generate_request_mode||'auto'));
  if(hasField('edit_request_mode'))    rows.push(fldSel('edit_request_mode','改图请求模式',modes,p.edit_request_mode||'auto'));
  if(hasField('supports_edit'))rows.push(fldCk('supports_edit','支持改图',p.supports_edit!==false));
  if(hasField('use_proxy'))    rows.push(fldCk('use_proxy','启用代理',p.use_proxy||false));
  if(hasField('num_inference_steps'))rows.push(fld('num_inference_steps','推理步数','number',p.num_inference_steps??9));
  if(hasField('guidance_scale'))     rows.push(fld('guidance_scale','引导系数','number',p.guidance_scale??1.0));
  if(hasField('poll_interval'))      rows.push(fld('poll_interval','轮询间隔(秒)','number',p.poll_interval??5));
  if(hasField('poll_timeout'))       rows.push(fld('poll_timeout','轮询超时(秒)','number',p.poll_timeout??300));
  if(hasField('default_style'))rows.push(fld('default_style','默认风格','text',p.default_style||'真实'));
  if(hasField('default_ratio'))rows.push(fld('default_ratio','默认比例','text',p.default_ratio||'1:1'));
  if(hasField('default_model'))rows.push(fld('default_model','默认模型','text',p.default_model||'Seedream 4.0'));
  if(hasField('api_key'))      rows.push(fld('api_key','API Key','text',p.api_key||''));
  if(hasField('empty_response_retry'))rows.push(fld('empty_response_retry','无视频URL重试次数','number',p.empty_response_retry??2));
  if(hasField('retry_delay'))         rows.push(fld('retry_delay','重试间隔(秒)','number',p.retry_delay??2));
  rows.push('</div>');
  if(hasField('proxy_url'))      rows.push(fldTA('proxy_url','代理地址（可选）',p.proxy_url||'').replace('rows="3"','rows="1"'));
  if(hasField('negative_prompt'))rows.push(fldTA('negative_prompt','负面提示词',p.negative_prompt||''));
  if(hasField('system_prompt'))  rows.push(fldTA('system_prompt','系统提示词（可选）',p.system_prompt||''));
  // grok_video 专有字段
  if(hasField('presets'))        rows.push(fldTA('presets','预设提示词（每行格式: 名称:英文提示词）',p.presets||[],'如 电影感:cinematic lighting, epic'));
  // grok2api_video 专有字段（base_url+api_keys+model，复用已有通用字段，无需额外渲染）
  // custom_video 专有字段
  if(hasField('generate_path'))   rows.push(fld('generate_path','生成接口路径','text',p.generate_path||'/v1/chat/completions'));
  if(hasField('poll_path'))       rows.push(fld('poll_path','轮询路径（为空不轮询）','text',p.poll_path||'','如 /v1/tasks/{task_id}'));
  if(hasField('response_url_path')) rows.push(fld('response_url_path','视频URL路径','text',p.response_url_path||'','如 data.0.url'));
  if(hasField('task_id_path'))    rows.push(fld('task_id_path','task_id路径','text',p.task_id_path||'','如 id'));
  if(hasField('status_path'))     rows.push(fld('status_path','状态字段路径','text',p.status_path||'','如 status'));
  if(hasField('done_statuses'))   rows.push(fld('done_statuses','完成状态值（逗号分隔）','text',p.done_statuses||'succeeded,completed,done,finished,success'));
  if(hasField('fail_statuses'))   rows.push(fld('fail_statuses','失败状态值（逗号分隔）','text',p.fail_statuses||'failed,error,cancelled'));
  if(hasField('image_field'))     rows.push(fld('image_field','图片字段名','text',p.image_field||'image'));
  if(hasField('request_mode'))    rows.push(fldSel('request_mode','请求模式',['auto','json','multipart'],p.request_mode||'auto'));
  if(hasField('extra_body'))      rows.push(fldTA('extra_body','额外请求体（JSON，可选）',p.extra_body||''));
  return rows.join('');
}
function readProviderForm() {
  const type = $('pf-__type')?.value || 'openai_images';
  const tpl  = P_TEMPLATES[type] || {};
  const has  = k => k in tpl || k === 'id' || k === 'label' || k === '__type';

  const g    = id => $(`pf-${id}`)?.value?.trim() ?? '';
  const gCk  = id => !!$(`pf-${id}`)?.checked;
  const gList= id => ($(`pf-${id}`)?.value||'').split('\n').map(s=>s.trim()).filter(Boolean);
  const gNum = (id,d) => { const v=parseFloat($(`pf-${id}`)?.value); return isNaN(v)?d:v; };

  // 从模板默认值出发，只读取该类型有的字段
  const result = { __type: type, __template_key: type, id: g('id'), label: g('label') };

  if (has('api_url'))           result.api_url           = g('api_url');
  if (has('base_url'))          result.base_url          = g('base_url');
  if (has('full_generate_url')) result.full_generate_url = g('full_generate_url');
  if (has('full_edit_url'))     result.full_edit_url     = g('full_edit_url');
  if (has('model'))             result.model             = g('model');
  if (has('api_keys'))          result.api_keys          = gList('api_keys');
  if (has('apikey'))            result.apikey            = g('apikey');
  if (has('api_key'))           result.api_key           = g('api_key');
  if (has('cookie_list'))       result.cookie_list       = gList('cookie_list');
  if (has('timeout'))           result.timeout           = gNum('timeout', 120);
  if (has('timeout_seconds'))   result.timeout_seconds   = gNum('timeout_seconds', 180);
  if (has('max_retries'))       result.max_retries       = gNum('max_retries', 2);
  if (has('default_size'))      result.default_size      = g('default_size');
  if (has('default_resolution'))result.default_resolution= g('default_resolution');
  if (has('supports_edit'))     result.supports_edit     = gCk('supports_edit');
  if (has('generate_request_mode')) result.generate_request_mode = g('generate_request_mode');
  if (has('edit_request_mode'))     result.edit_request_mode     = g('edit_request_mode');
  if (has('use_proxy'))         result.use_proxy         = gCk('use_proxy');
  if (has('proxy_url'))         result.proxy_url         = g('proxy_url');
  if (has('num_inference_steps'))result.num_inference_steps = gNum('num_inference_steps', 9);
  if (has('guidance_scale'))    result.guidance_scale    = gNum('guidance_scale', 1.0);
  if (has('poll_interval'))     result.poll_interval     = gNum('poll_interval', 5);
  if (has('poll_timeout'))      result.poll_timeout      = gNum('poll_timeout', 300);
  if (has('default_style'))     result.default_style     = g('default_style');
  if (has('default_ratio'))     result.default_ratio     = g('default_ratio');
  if (has('default_model'))     result.default_model     = g('default_model');
  if (has('negative_prompt'))   result.negative_prompt   = g('negative_prompt');
  if (has('system_prompt'))     result.system_prompt     = g('system_prompt');
  if (has('empty_response_retry')) result.empty_response_retry = gNum('empty_response_retry', 2);
  if (has('retry_delay'))       result.retry_delay       = gNum('retry_delay', 2);
  // grok_video 专有字段
  if (has('presets'))           result.presets = g('presets').split('\n').map(s=>s.trim()).filter(Boolean);
  // custom_video 专有字段
  if (has('generate_path'))     result.generate_path     = g('generate_path');
  if (has('poll_path'))         result.poll_path         = g('poll_path');
  if (has('response_url_path')) result.response_url_path = g('response_url_path');
  if (has('task_id_path'))      result.task_id_path      = g('task_id_path');
  if (has('status_path'))       result.status_path       = g('status_path');
  if (has('done_statuses'))     result.done_statuses     = g('done_statuses');
  if (has('fail_statuses'))     result.fail_statuses     = g('fail_statuses');
  if (has('image_field'))       result.image_field       = g('image_field');
  if (has('request_mode'))      result.request_mode      = g('request_mode');
  if (has('extra_body'))        result.extra_body        = g('extra_body');

  return result;
}

// ── 预设渲染 ──────────────────────────────────────────────────────────────────
function renderPresets(containerId, list, key) {
  const el=$(containerId); if(!el)return;
  if(!list.length){el.innerHTML='<div class="preset-empty">暂无预设</div>';return;}
  el.innerHTML='';
  list.forEach((p,idx)=>{
    const div=document.createElement('div'); div.className='preset-item';
    div.innerHTML=`<input type="text" class="inp" placeholder="名称" value="${esc(p.name)}" data-key="${key}" data-idx="${idx}" data-field="name" style="width:120px;flex-shrink:0"/>
      <span class="preset-item-sep">:</span>
      <input type="text" class="inp" placeholder="提示词" value="${esc(p.prompt)}" data-key="${key}" data-idx="${idx}" data-field="prompt" style="flex:1"/>
      <button class="btn-danger" data-del="${key}" data-idx="${idx}">✕</button>`;
    el.appendChild(div);
  });
  el.querySelectorAll('input[data-field]').forEach(inp=>{
    inp.addEventListener('input',()=>{
      const{key:k,idx,field}=inp.dataset;
      const arr=k==='draw'?S.draw_presets:k==='edit'?S.edit_presets:S.video_presets;
      if(arr[idx])arr[idx][field]=inp.value;
      updateStats();markDirty();
    });
  });
  el.querySelectorAll('[data-del]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const k=btn.dataset.del,idx=parseInt(btn.dataset.idx);
      const arr=k==='draw'?S.draw_presets:k==='edit'?S.edit_presets:S.video_presets;
      arr.splice(idx,1);
      renderPresets(containerId,arr,k);
      updateStats();markDirty();
    });
  });
}

// ── 人设渲染 ──────────────────────────────────────────────────────────────────
function renderPersonas() {
  const el=$('persona-list'); if(!el)return;
  if(!S.persona_config.profiles.length){el.innerHTML='<div class="persona-empty">暂无人设，点击"新建人设"创建</div>';return;}
  el.innerHTML='';
  S.persona_config.profiles.forEach((p,idx)=>{
    const isActive=p.id===S.persona_config.active_persona_id;
    const refs=Array.isArray(p.persona_ref_image)?p.persona_ref_image:[];
    const div=document.createElement('div'); div.className=`persona-item${isActive?' is-active':''}`;
    div.innerHTML=`
      <div class="persona-avatar">${isActive?'👤':'🧑'}</div>
      <div class="persona-info">
        <div class="pname">${esc(p.persona_name||p.id)}</div>
        <div class="pmeta">ID: ${esc(p.id)} · 参考图 ${refs.length} 张${p.persona_base_prompt?' · '+esc(p.persona_base_prompt.slice(0,40))+(p.persona_base_prompt.length>40?'…':''):''}</div>
      </div>
      ${isActive?'<span class="persona-badge">当前启用</span>':''}
      <div class="persona-actions">
        ${!isActive?`<button class="btn-ghost btn-sm" data-act="activate" data-idx="${idx}">启用</button>`:''}
        <button class="btn-ghost btn-sm" data-act="edit" data-idx="${idx}">编辑</button>
        <button class="btn-danger" data-act="del" data-idx="${idx}">删除</button>
      </div>`;
    el.appendChild(div);
  });
  el.querySelectorAll('[data-act]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const idx=parseInt(btn.dataset.idx);
      if(btn.dataset.act==='activate') activatePersona(idx);
      else if(btn.dataset.act==='edit') openPersonaModal(idx);
      else if(btn.dataset.act==='del') delPersona(idx);
    });
  });
}
async function activatePersona(idx) {
  const p=S.persona_config.profiles[idx]; if(!p)return;
  try{
    const res=await bridge.apiPost('switch_persona',{id:p.id});
    if(!res.success)throw new Error(res.error||'切换失败');
    S.persona_config.active_persona_id=p.id;
    renderPersonas();updateStats();
    showToast(`✅ 已切换到「${p.persona_name||p.id}」`);
  }catch(e){showToast(String(e),'err');}
}
function delPersona(idx){
  if(S.persona_config.profiles.length<=1){showToast('至少保留一套人设','err');return;}
  const p=S.persona_config.profiles[idx];
  if(!confirm(`确定删除人设「${p.persona_name||p.id}」？`))return;
  if(S.persona_config.active_persona_id===p.id)
    S.persona_config.active_persona_id=S.persona_config.profiles[idx===0?1:0].id;
  S.persona_config.profiles.splice(idx,1);
  renderPersonas();updateStats();markDirty();
}
let _personaIdx=-1;
// 统一管理弹窗内的参考图列表（含本地路径、URL）
// base64 在上传时立即通过 upload_ref_image 转为服务器路径，不在内存存储
let _modalRefs = [];

function openPersonaModal(idx){
  _personaIdx=idx;
  const isNew=idx<0;
  $('modal-persona-title').textContent=isNew?'新建人设':'编辑人设';
  const p=isNew?{id:'',persona_name:'',persona_base_prompt:'',persona_ref_image:[]}:S.persona_config.profiles[idx];
  $('modal-id').value=p.id||''; $('modal-name').value=p.persona_name||'';
  $('modal-prompt').value=p.persona_base_prompt||'';
  // _modalRefs 保留所有引用（路径/URL/base64），文本框只显示路径和URL（base64太长不展示）
  _modalRefs = [...(p.persona_ref_image||[])];
  $('modal-refs').value = _modalRefs.filter(r=>!String(r).startsWith('data:image')).join('\n');
  renderRefPreviews(_modalRefs);
  $('persona-modal').style.display='flex'; $('modal-name').focus();
}

function refPreviewSrc(r) {
  if (r.startsWith('data:image')) return r;
  if (r.startsWith('http://') || r.startsWith('https://')) return r;
  // 本地绝对路径 → 通过后端 get_image 接口代理返回图片
  return `/astrbot_plugin_aiimg_enhanced/get_image?path=${encodeURIComponent(r)}`;
}

function renderRefPreviews(refs) {
  const el = $('modal-ref-previews');
  if (!el) return;
  el.innerHTML = '';
  if (!refs.length) return;

  refs.forEach((r, i) => {
    const isBase64 = String(r).startsWith('data:image');
    const isHttp   = String(r).startsWith('http://') || String(r).startsWith('https://');
    const shortName = isBase64 ? ('图片 ' + (i+1)) : (r.split(/[\/\\]/).pop() || r).slice(0, 22);

    const wrap = document.createElement('div');
    wrap.className = 'ref-thumb';
    wrap.title = r;

    const img = document.createElement('img');
    img.loading = 'lazy';
    img.alt = shortName;

    const errDiv = document.createElement('div');
    errDiv.className = 'ref-thumb-err';
    errDiv.style.display = 'none';
    errDiv.textContent = '📷';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'ref-thumb-name';
    nameDiv.textContent = shortName;

    const delBtn = document.createElement('button');
    delBtn.className = 'ref-thumb-del';
    delBtn.title = '移除';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', () => {
      _modalRefs.splice(i, 1);
      $('modal-refs').value = _modalRefs.filter(x=>!String(x).startsWith('data:image')).join('\n');
      renderRefPreviews(_modalRefs);
      markDirty();
    });

    if (isBase64 || isHttp) {
      // base64 和 HTTP URL 直接显示
      img.src = r;
      img.onerror = () => { errDiv.style.display = 'flex'; img.style.display = 'none'; };
    } else {
      // 本地路径：通过 bridge.apiGet 获取 base64
      errDiv.style.display = 'flex'; // 先显示占位符
      img.style.display = 'none';
      bridge.apiGet('get_image_b64?path=' + encodeURIComponent(r))
        .then(d => {
          if (d && d.success && d.data) {
            img.src = d.data;
            img.style.display = 'block';
            errDiv.style.display = 'none';
          }
        })
        .catch(() => {});
    }

    wrap.append(img, errDiv, nameDiv, delBtn);
    el.appendChild(wrap);
  });
}

function uploadRefImages(files) {
  // 与 omnidraw 保持一致：FileReader 读 base64 存入 _modalRefs，直接预览
  // 保存人设时 base64 随 save_config payload 一起发给后端，后端 _save_base64_refs 转存为本地文件
  const btn = $('modal-upload-btn');
  const status = $('modal-upload-status');
  if (!files || !files.length) return;

  const fileArr = Array.from(files);
  const oversized = fileArr.filter(f => f.size > 20 * 1024 * 1024);
  if (oversized.length) {
    status.textContent = `✗ ${oversized.map(f=>f.name).join(', ')} 超过 20MB`;
    status.className = 'upload-status err';
    return;
  }

  btn.disabled = true;
  status.textContent = `读取中 (0/${fileArr.length})...`;
  status.className = 'upload-status uploading';

  let done = 0;
  fileArr.forEach(file => {
    const r = new FileReader();
    r.onload = evt => {
      _modalRefs.push(evt.target.result);  // base64 data URL，可直接作为 img.src
      done++;
      status.textContent = `读取中 (${done}/${fileArr.length})...`;
      if (done === fileArr.length) {
        $('modal-refs').value = _modalRefs.filter(r => !r.startsWith('data:image')).join('\n');
        renderRefPreviews(_modalRefs);
        status.textContent = `✓ 已添加 ${fileArr.length} 张图片`;
        status.className = 'upload-status ok';
        setTimeout(() => { status.textContent=''; status.className='upload-status'; btn.disabled=false; }, 2000);
        markDirty();
      }
    };
    r.onerror = () => {
      done++;
      status.textContent = `✗ ${file.name} 读取失败`;
      status.className = 'upload-status err';
      if (done === fileArr.length) btn.disabled = false;
    };
    r.readAsDataURL(file);
  });
}
function savePersonaModal(){
  const id=$('modal-id').value.trim().replace(/[^a-zA-Z0-9_\-]/g,'_')||`persona_${Date.now()}`;
  const persona_name=$('modal-name').value.trim()||id;
  const persona_base_prompt=$('modal-prompt').value.trim();
  // _modalRefs 包含本地路径/URL/base64，后端 _save_base64_refs 会把 base64 转存为本地文件
  const persona_ref_image = _modalRefs.filter(r => Boolean(r));
  const obj={id,persona_name,persona_base_prompt,persona_ref_image};
  if(_personaIdx<0){
    S.persona_config.profiles.push(obj);
    if(!S.persona_config.active_persona_id)S.persona_config.active_persona_id=id;
  }else{
    const wasActive=S.persona_config.profiles[_personaIdx].id===S.persona_config.active_persona_id;
    S.persona_config.profiles[_personaIdx]=obj;
    if(wasActive)S.persona_config.active_persona_id=id;
  }
  renderPersonas();updateStats();markDirty();
  $('persona-modal').style.display='none';
}

// ── 保存 ──────────────────────────────────────────────────────────────────────
async function saveAll(){
  $('btn-save').disabled=true; $('btn-save').textContent='保存中...';
  $('save-hint').textContent='正在保存...'; $('save-hint').className='save-hint saving';
  try{
    const res=await bridge.apiPost('save_config',buildPayload());
    if(!res.success)throw new Error(res.error||'保存失败');
    markClean('配置已保存 ✓');showToast('✅ 配置已保存');
  }catch(e){
    $('save-hint').textContent='保存失败'; $('save-hint').className='save-hint dirty';
    showToast(`保存失败：${e}`,'err');
  }finally{
    $('btn-save').disabled=false; $('btn-save').textContent='保存更改';
  }
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
async function init(){
  initTabs();
  document.querySelectorAll('input:not([type=checkbox]):not([type=hidden]),textarea,select').forEach(el=>{
    el.addEventListener('input',markDirty); el.addEventListener('change',markDirty);
  });
  document.querySelectorAll('input[type=checkbox].toggle').forEach(el=>el.addEventListener('change',markDirty));
  $('btn-save').addEventListener('click',saveAll);
  // 事件委托兜底（omnidraw同款，保证在各种iframe环境下都能触发）
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action="save-config"]');
    if (btn) saveAll();
  });
  $('btn-add-provider').addEventListener('click',()=>openProviderModal(-1));
  $('btn-provider-modal-close').addEventListener('click',()=>$('provider-modal').style.display='none');
  $('btn-provider-modal-cancel').addEventListener('click',()=>$('provider-modal').style.display='none');
  $('btn-provider-modal-ok').addEventListener('click',()=>{
    const p=readProviderForm();
    if(!p.id){showToast('请填写服务商 ID','err');return;}
    if(_provIdx<0)S.providers.push(p); else S.providers[_provIdx]=p;
    renderProviders();renderAllChains();updateStats();markDirty();
    $('provider-modal').style.display='none';
  });
  $('btn-add-persona').addEventListener('click',()=>openPersonaModal(-1));
  $('btn-modal-close').addEventListener('click',()=>$('persona-modal').style.display='none');
  $('btn-modal-cancel').addEventListener('click',()=>$('persona-modal').style.display='none');
  $('btn-modal-ok').addEventListener('click',savePersonaModal);
  // 上传按钮
  const uploadBtn = $('modal-upload-btn');
  const fileInput = $('modal-file-input');
  if (uploadBtn && fileInput) {
    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length) {
        uploadRefImages(fileInput.files);
        fileInput.value = ''; // 允许重复上传同名文件
      }
    });
  }
  // 文本框变化时刷新预览
  const modalRefs = $('modal-refs');
  if (modalRefs) {
    modalRefs.addEventListener('input', () => {
      // 文本框的路径/URL + 内存里的base64合并
      const textPart = modalRefs.value.split('\n').map(s=>s.trim()).filter(Boolean);
      const b64Part  = _modalRefs.filter(r=>String(r).startsWith('data:image'));
      _modalRefs = [...b64Part, ...textPart];
      renderRefPreviews(_modalRefs);
    });
  }
  const addPreset=(arr,key,cid)=>{arr.push({name:'',prompt:''});renderPresets(cid,arr,key);updateStats();markDirty();};
  $('btn-add-draw-preset').addEventListener('click',()=>addPreset(S.draw_presets,'draw','draw-presets-list'));
  $('btn-add-edit-preset').addEventListener('click',()=>addPreset(S.edit_presets,'edit','edit-presets-list'));
  $('btn-add-video-preset').addEventListener('click',()=>addPreset(S.video_presets,'video','video-presets-list'));
  try{
    await bridge.ready();
    const res=await bridge.apiGet('get_config');
    if(res.success&&res.config)applyConfig(res.config); else applyConfig({});
  }catch(e){
    console.warn('加载配置失败',e); showToast('加载配置失败，使用默认值','err'); applyConfig({});
  }
  markClean();
}
init().catch(e => { console.error('[AI绘图站] 初始化失败', e); });
