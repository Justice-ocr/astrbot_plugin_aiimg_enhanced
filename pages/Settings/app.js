import { loadOutputSizeData, normalizeOutputSize, sizeOptionsHtml } from './output_sizes.js';
import { createPersonaRefController } from './persona_refs.js';
import {
  inferProviderType,
  PROVIDER_NAMES,
  PROVIDER_TEMPLATES,
  VIDEO_PROVIDER_TYPES,
} from './provider_catalog.js';
import {
  buildProviderForm as buildProviderFormHtml,
  readProviderForm as readProviderFormValues,
} from './provider_form.js';

'use strict';

// ── 工具 ─────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const asInt = (v,d) => { const n=parseInt(v); return isNaN(n)?d:n; };
const asBool = v => typeof v==='boolean'?v: String(v||'').toLowerCase()==='true';
const bridge = window.AstrBotPluginPage || {
  ready: async () => ({}),
  apiGet: async (name) => {
    if (name !== 'get_config') return { success: false };
    return { success: true, config: {
      features: {
        draw:   { enabled:true, llm_tool_enabled:true, default_output:'1024x1024', batch_concurrency:2,
                  chain:[{provider_id:'gitee',output:''}] },
        edit:   { enabled:true, llm_tool_enabled:true, default_output:'4096x4096', batch_concurrency:2,
                  chain:[{provider_id:'gitee_async',output:''}] },
        selfie: { enabled:true, llm_tool_enabled:true, default_output:'4096x4096',
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
  upload: async (name, file) => {
    console.info('[mock upload]', name, file);
    return { success:false, error:'Upload requires the AstrBot Pages bridge' };
  },
};

// ── 状态 ─────────────────────────────────────────────────────────────────────
let S = {
  features:{}, storage:{}, debounce_interval:10,
  max_user_concurrency:2, max_user_video_concurrency:1, network:{},
  providers:[],
  // chain状态单独存，key: 'draw'|'edit'|'selfie'|'video'
  chains:{ draw:[], edit:[], selfie:[], video:[] },
  persona_config:{ active_persona_id:'default', profiles:[] },
  // Runtime-only preview cache. Config responses contain paths, never image data.
  persona_ref_previews:{},
  reply_config:{},
  draw_presets:[], edit_presets:[], video_presets:[],
  dirty:false,
};
const personaRefs = createPersonaRefController({
  $,
  bridge,
  previewCache: S.persona_ref_previews,
  markDirty,
  showToast,
});

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
function initOutputSizeSelects() {
  ['feat-draw-output', 'feat-edit-output', 'feat-selfie-output'].forEach(id => {
    const el = $(id);
    if (el) el.innerHTML = sizeOptionsHtml(el.value, {includeDefault:true});
  });
}

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
        ${hasOutput ? `<select class="sel chain-output" data-chain="${chainKey}" data-idx="${idx}" title="覆盖输出尺寸，留空使用功能默认值">${sizeOptionsHtml(item.output, {includeDefault:true})}</select>` : ''}
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
    inp.addEventListener('change', () => {
      const {chain: k, idx} = inp.dataset;
      S.chains[k][parseInt(idx)].output = normalizeOutputSize(inp.value);
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
  setSel('feat-draw-output', normalizeOutputSize(draw.default_output));
  setVal('feat-draw-batch', draw.batch_concurrency??2);

  setCk('feat-edit-enabled', asBool(edit.enabled!==false));
  setCk('feat-edit-llm', asBool(edit.llm_tool_enabled!==false));
  setSel('feat-edit-output', normalizeOutputSize(edit.default_output));
  setVal('feat-edit-batch', edit.batch_concurrency??2);

  setCk('feat-selfie-enabled', asBool(selfie.enabled!==false));
  setCk('feat-selfie-llm', asBool(selfie.llm_tool_enabled!==false));
  setSel('feat-selfie-output', normalizeOutputSize(selfie.default_output));
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
    output: normalizeOutputSize(item.output),
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
  Object.keys(S.persona_ref_previews).forEach(key => delete S.persona_ref_previews[key]);
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
      hasOutput ? {provider_id:i.provider_id, output:normalizeOutputSize(i.output)} : {provider_id:i.provider_id}
    );

  return {
    features:{
      draw:{
        enabled:getCk('feat-draw-enabled'), llm_tool_enabled:getCk('feat-draw-llm'),
        default_output:normalizeOutputSize(getVal('feat-draw-output')), batch_concurrency:getInt('feat-draw-batch',2),
        chain:chainToSave('draw',true),
        presets:S.draw_presets.filter(p=>p.name).map(p=>`${p.name}:${p.prompt}`),
      },
      edit:{
        enabled:getCk('feat-edit-enabled'), llm_tool_enabled:getCk('feat-edit-llm'),
        default_output:normalizeOutputSize(getVal('feat-edit-output')), batch_concurrency:getInt('feat-edit-batch',2),
        chain:chainToSave('edit',true),
        presets:S.edit_presets.filter(p=>p.name).map(p=>`${p.name}:${p.prompt}`),
      },
      selfie:{
        enabled:getCk('feat-selfie-enabled'), llm_tool_enabled:getCk('feat-selfie-llm'),
        default_output:normalizeOutputSize(getVal('feat-selfie-output')),
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
      <span class="provider-tag">${esc(PROVIDER_NAMES[type]||type)}</span>
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
  const templateKey = $('provider-template-sel').value;
  const p=isNew?{id:'',__type:templateKey,...PROVIDER_TEMPLATES[templateKey]}:S.providers[idx];
  $('provider-modal-body').innerHTML=buildProviderFormHtml(p);
  $('provider-modal').style.display='flex';
}
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
let _saving = false;

function openPersonaModal(idx){
  _personaIdx=idx;
  const isNew=idx<0;
  $('modal-persona-title').textContent=isNew?'新建人设':'编辑人设';
  const p=isNew?{id:'',persona_name:'',persona_base_prompt:'',persona_ref_image:[]}:S.persona_config.profiles[idx];
  $('modal-id').value=p.id||''; $('modal-name').value=p.persona_name||'';
  $('modal-prompt').value=p.persona_base_prompt||'';
  personaRefs.setRefs(p.persona_ref_image || []);
  $('persona-modal').style.display='flex'; $('modal-name').focus();
}

async function savePersonaModal(){
  try {
    await personaRefs.waitForUpload();
  } catch (e) {
    showToast(`参考图上传失败：${e}`, 'err');
    return;
  }
  const id=$('modal-id').value.trim().replace(/[^a-zA-Z0-9_\-]/g,'_')||`persona_${Date.now()}`;
  const persona_name=$('modal-name').value.trim()||id;
  const persona_base_prompt=$('modal-prompt').value.trim();
  // 旧配置可能仍含 data URL；后端会在保存时转存为本地文件。
  const persona_ref_image = personaRefs.refs();
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
  if (_saving) return;
  _saving = true;
  $('btn-save').disabled=true; $('btn-save').textContent='保存中...';
  $('save-hint').textContent='正在保存...'; $('save-hint').className='save-hint saving';
  try{
    $('save-hint').textContent='正在等待参考图上传...';
    await personaRefs.waitForUpload();
    const res=await bridge.apiPost('save_config',buildPayload());
    if(!res.success)throw new Error(res.error||'保存失败');
    markClean('配置已保存 ✓');showToast('✅ 配置已保存');
  }catch(e){
    $('save-hint').textContent='保存失败'; $('save-hint').className='save-hint dirty';
    showToast(`保存失败：${e}`,'err');
  }finally{
    _saving = false;
    $('btn-save').disabled=false; $('btn-save').textContent='保存更改';
  }
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
async function init(){
  await loadOutputSizeData();
  initOutputSizeSelects();
  initTabs();
  document.querySelectorAll('input:not([type=checkbox]):not([type=hidden]),textarea,select').forEach(el=>{
    el.addEventListener('input',markDirty); el.addEventListener('change',markDirty);
  });
  document.querySelectorAll('input[type=checkbox].toggle').forEach(el=>el.addEventListener('change',markDirty));
  $('btn-save').addEventListener('click',saveAll);
  // 事件委托兜底（omnidraw同款，保证在各种iframe环境下都能触发）
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action="save-config"]');
    if (btn) {
      e.preventDefault();
      saveAll();
    }
  });
  $('btn-add-provider').addEventListener('click',()=>openProviderModal(-1));
  $('btn-provider-modal-close').addEventListener('click',()=>$('provider-modal').style.display='none');
  $('btn-provider-modal-cancel').addEventListener('click',()=>$('provider-modal').style.display='none');
  $('btn-provider-modal-ok').addEventListener('click',()=>{
    const p=readProviderFormValues($);
    if(!p.id){showToast('请填写服务商 ID','err');return;}
    if(_provIdx<0)S.providers.push(p); else S.providers[_provIdx]=p;
    renderProviders();renderAllChains();updateStats();markDirty();
    $('provider-modal').style.display='none';
  });
  $('btn-add-persona').addEventListener('click',()=>openPersonaModal(-1));
  $('btn-modal-close').addEventListener('click',()=>$('persona-modal').style.display='none');
  $('btn-modal-cancel').addEventListener('click',()=>$('persona-modal').style.display='none');
  $('btn-modal-ok').addEventListener('click',savePersonaModal);
  personaRefs.bind();
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
