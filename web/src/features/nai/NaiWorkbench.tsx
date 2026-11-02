import { useEffect, useRef, useState } from "react";
import "../../styles/nai-workbench.css";
import { ArrowDown, ArrowRight, BookOpen, Check, Copy, ImagePlus, Layers3, LoaderCircle, Palette, RefreshCw, Save, Settings2, ShieldCheck, Sparkles, Trash2, WandSparkles, X } from "lucide-react";
import type { ProviderConfig, StudioProject, StudioSnapshot } from "../../api/contracts";
import { createStudioJob, deleteNaiPreset, loadNaiPresets, prepareNaiPrompt, saveStudioProject } from "../../api/client";

type Fields = { artist: string; tags: string; negative: string; prefix: string };
const empty: Fields = { artist: "", tags: "", negative: "", prefix: "" };
const protocolNames: Record<string, string> = { nai_native: "NAI 原生", nai_gateway: "GET 网关", nai_openai_images: "OpenAI Images" };
const sizes = ["832x1216", "1216x832", "1024x1024", "1152x896", "896x1152", "1536x1024", "1024x1536"];

export function isNaiProvider(provider: ProviderConfig): boolean {
  const type = String(provider.__template_key || provider.__type || "");
  return ["nai_native", "nai_gateway", "nai_openai_images"].includes(type) ||
    (type === "openai_images" && (/nai|novelai/i.test(String(provider.model || "")) || provider.nai_translate_prompt === true));
}

function compose(fields: Fields): string {
  return [fields.prefix, fields.artist, fields.tags].map((value) => value.trim().replace(/^[,\s]+|[,\s]+$/g, "")).filter(Boolean).join(", ");
}

export function NaiWorkbench({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const providers = (snapshot.config.providers || []).filter(isNaiProvider);
  const models = snapshot.config.astrbot_providers || [];
  const [providerId, setProviderId] = useState("");
  const [llmId, setLlmId] = useState("");
  const [fields, setFields] = useState<Fields>(empty);
  const [description, setDescription] = useState("");
  const [size, setSize] = useState("");
  const [conversion, setConversion] = useState<Fields | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [presets, setPresets] = useState<StudioProject[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(false);
  const [presetId, setPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetError, setPresetError] = useState("");
  const [saveOpen, setSaveOpen] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const sequence = useRef(0);
  const presetSequence = useRef(0);
  const provider = providers.find((item) => item.id === providerId);
  const selectedPreset = presets.find((item) => item.id === presetId);
  const finalPrompt = compose(fields);
  const tagCount = fields.tags.split(/[,，\n]/).filter((value) => value.trim()).length;
  const locked = Boolean(busy);
  const legacyDefaults = provider && ["nai_artist", "nai_prompt_prefix", "negative_prompt", "nai_llm_provider_id"].some((key) => Boolean(provider[key]));

  useEffect(() => {
    if (!providers.some((item) => item.id === providerId)) setProviderId(providers[0]?.id || "");
  }, [snapshot.configRevision]);

  useEffect(() => {
    ++sequence.current;
    setReviewed(false); setConversion(null); setBusy(""); setError("");
    setSize(String(provider?.default_size || "832x1216"));
  }, [providerId]);

  useEffect(() => {
    ++sequence.current;
    const request = ++presetSequence.current;
    setFields(empty); setDescription(""); setConversion(null); setReviewed(false);
    setLlmId(""); setPresetId(""); setPresetName(""); setPresets([]); setSaveOpen(false);
    setBusy(""); setError(""); setStatus(""); setPresetError(""); setDeleteArmed(false); setPresetsLoading(Boolean(scope));
    if (scope) loadNaiPresets(scope).then((items) => { if (request === presetSequence.current) setPresets(items); })
      .catch((reason) => { if (request === presetSequence.current) setPresetError(reason instanceof Error ? reason.message : "读取预设失败"); })
      .finally(() => { if (request === presetSequence.current) setPresetsLoading(false); });
    return () => { ++sequence.current; ++presetSequence.current; };
  }, [scope]);

  function invalidate() { ++sequence.current; setReviewed(false); setStatus(""); setError(""); setDeleteArmed(false); }
  function update(key: keyof Fields, value: string) {
    invalidate(); setFields((current) => ({ ...current, [key]: value })); setConversion(null);
  }
  function applyPreset(id: string) {
    const preset = presets.find((item) => item.id === id);
    invalidate(); setPresetId(id); setSaveOpen(false); setConversion(null);
    if (!preset) { setFields(empty); setLlmId(""); setPresetName(""); return; }
    const doc = preset.document;
    setFields({ artist: String(doc.artist || ""), prefix: String(doc.prefix || ""), tags: String(doc.tags || ""), negative: String(doc.negative || "") });
    setLlmId(String(doc.llm_provider_id || "")); setSize(String(doc.size || provider?.default_size || "832x1216"));
    setPresetName(preset.name); setStatus(`已预填充「${preset.name}」，可以继续编辑。`);
  }
  function importLegacy() {
    if (!provider) return;
    invalidate(); setFields({ artist: String(provider.nai_artist || ""), tags: fields.tags, prefix: String(provider.nai_prompt_prefix || ""), negative: String(provider.negative_prompt || "") });
    setLlmId(String(provider.nai_llm_provider_id || "")); setStatus("已导入旧服务商默认值。可保存成工作台预设，原配置未删除。");
  }
  async function savePreset(copy: boolean) {
    if (!scope || !presetName.trim() || presetsLoading) return;
    const request = ++sequence.current;
    setBusy("save"); setError("");
    try {
      const item = await saveStudioProject({ scope, kind: "nai_preset", name: presetName.trim(),
        ...(selectedPreset && !copy ? { id: selectedPreset.id, revision: selectedPreset.revision } : {}),
        document: { version: 1, ...fields, llm_provider_id: llmId, size } });
      if (request !== sequence.current) return;
      setPresets((current) => [item, ...current.filter((entry) => entry.id !== item.id)]);
      setPresetId(item.id); setPresetName(item.name); setSaveOpen(false); setStatus(`预设「${item.name}」已保存到当前会话。`);
    } catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : "预设保存失败"); }
    finally { if (request === sequence.current) setBusy(""); }
  }
  async function removePreset() {
    if (!selectedPreset || !scope) return;
    if (!deleteArmed) { setDeleteArmed(true); return; }
    const request = ++sequence.current;
    setBusy("delete"); setError("");
    try {
      await deleteNaiPreset(selectedPreset.id, selectedPreset.revision, scope);
      if (request !== sequence.current) return;
      setPresets((current) => current.filter((item) => item.id !== selectedPreset.id)); setPresetId(""); setPresetName("");
      setDeleteArmed(false); setStatus("预设已删除，当前编辑内容保持不变。");
    } catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : "删除预设失败"); }
    finally { if (request === sequence.current) setBusy(""); }
  }
  async function convert() {
    const request = ++sequence.current;
    setBusy("convert"); setError(""); setConversion(null); setReviewed(false);
    try {
      const result = await prepareNaiPrompt({ scope, provider_id: providerId, llm_provider_id: llmId, prompt: description, workbench: true });
      if (request !== sequence.current) return;
      setConversion({ ...fields, tags: result.tags }); setStatus("Tag 草稿已就绪，请先审阅，再应用到编辑区。");
    } catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : "Tag 转换失败"); }
    finally { if (request === sequence.current) setBusy(""); }
  }
  async function generate() {
    if (!reviewed || !provider || !scope || !fields.tags.trim()) return;
    const request = ++sequence.current;
    setBusy("generate"); setError("");
    try {
      const id = globalThis.crypto?.randomUUID?.() || `nai-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      await createStudioJob({ scope, kind: "image", mode: "draw", provider_id: providerId, prompt: finalPrompt, size,
        idempotency_key: id, nai_workbench: true, nai_reviewed: true,
        nai_artist: fields.artist, nai_tags: fields.tags, nai_prefix: fields.prefix, negative_prompt: fields.negative });
      if (request !== sequence.current) return;
      setReviewed(false); setStatus("NAI 生图任务已提交，可在任务中心查看结果。"); onRefresh();
    } catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : "NAI 生图提交失败"); }
    finally { if (request === sequence.current) setBusy(""); }
  }

  return <section className="nai-workbench">
    <header className="nai-hero"><div><span className="nai-eyebrow"><Palette size={15} /> NOVELAI STUDIO</span><h1>让灵感，落在每一个 Tag 上。</h1><p>专注画师串与标签的独立工作台。保留你的权重语法，每一次生成都由你确认。</p></div><span className="nai-hero-badge"><ShieldCheck size={18} /> 先审阅 · 后生图</span></header>
    <nav className="nai-steps" aria-label="NAI 工作流程"><span><b>01</b> 选择连接与预设</span><ArrowRight size={14} /><span><b>02</b> 编辑或转换 Tag</span><ArrowRight size={14} /><span><b>03</b> 审阅并生成</span></nav>
    {!providers.length && <p className="capability-notice">还没有 NAI 连接。请到 <a href="#/providers">服务商</a> 添加 NAI 原生或 OpenAI 兼容模板。</p>}
    {!scope && <p className="capability-notice">请在顶栏选择一个已有会话，预设与生成历史将按会话保存。</p>}
    <section className="nai-connection nai-card"><div className="nai-connection-label"><Settings2 size={18} /><span>生成连接<small>服务商只负责连接，不保存画师串</small></span></div><label className="nai-field"><span>NAI 服务商</span><select aria-label="NAI 服务商" value={providerId} disabled={locked} onChange={(event) => setProviderId(event.target.value)}><option value="">选择 NAI 服务商</option>{providers.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label><div className="nai-model"><span>{protocolNames[String(provider?.__template_key)] || "Images 兼容"}</span><strong>{String(provider?.model || "尚未选择模型")}</strong></div></section>
    <div className="nai-workspace-grid"><div className="nai-editor-column">
      <section className="nai-card nai-presets" aria-busy={presetsLoading}><div className="nai-card-heading"><div><BookOpen size={18} /><h2>提示词预设</h2></div><span>保存在当前会话</span></div><p className="nai-caption">画师串、前缀、正负面 Tag 与转换 LLM 都在这里管理，与供应商模板分开。</p>
        <div className="nai-preset-controls"><label className="nai-field"><span>已保存的预设</span><select aria-label="已保存的预设" value={presetId} disabled={locked || !scope || presetsLoading} onChange={(event) => applyPreset(event.target.value)}><option value="">{presetsLoading ? "正在加载预设…" : "空白草稿"}</option>{presets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button type="button" className="nai-button nai-button-soft" disabled={locked || !scope || presetsLoading} onClick={() => { setSaveOpen((value) => !value); setDeleteArmed(false); }}><Save size={15} />保存预设</button>{selectedPreset && <button type="button" className="nai-icon-button" aria-label={deleteArmed ? "确认删除预设" : "删除预设"} disabled={locked} onClick={() => void removePreset()}><Trash2 size={16} />{deleteArmed && "确认删除"}</button>}</div>
        {saveOpen && <div className="nai-preset-save"><label className="nai-field"><span>预设名称</span><input aria-label="预设名称" value={presetName} maxLength={80} placeholder="例如：柔和水彩 · 画师组合 A" disabled={locked} onChange={(event) => setPresetName(event.target.value)} /></label><button type="button" className="nai-button nai-button-solid" disabled={locked || !presetName.trim()} onClick={() => void savePreset(false)}>{busy === "save" ? <LoaderCircle size={15} className="nai-spinning" /> : <Check size={15} />}{selectedPreset ? "更新预设" : "保存新预设"}</button>{selectedPreset && <button type="button" className="nai-button nai-button-soft" disabled={locked || !presetName.trim()} onClick={() => void savePreset(true)}><Copy size={15} />另存为</button>}</div>}
        {presetError && <p className="form-error" role="alert">{presetError}</p>}
        {legacyDefaults && <details className="nai-legacy"><summary>兼容旧版默认值</summary><p>旧配置未删除。需要时可手动导入，再保存成工作台预设。</p><button type="button" className="nai-button nai-button-soft" disabled={locked} onClick={importLegacy}><RefreshCw size={14} />导入旧服务商默认值</button></details>}
      </section>
      <section className="nai-card nai-tag-editor"><div className="nai-card-heading"><div><Layers3 size={18} /><h2>Tag 编辑器</h2></div><span>逗号与权重原样保留</span></div>
        <label className="nai-field nai-artist-field"><span>画师串 <small>ARTIST</small></span><textarea aria-label="画师串" rows={3} value={fields.artist} disabled={locked} spellCheck={false} onChange={(event) => update("artist", event.target.value)} placeholder="artist:your_artist, {{artist:another_artist}}" /><em>使用你确认过的完整画师串；转换模型不会擅自猜测画师。</em></label>
        <label className="nai-field nai-positive-field"><span>正面 Tag <small>{tagCount} 个标签</small></span><textarea aria-label="正面 Tag" rows={7} value={fields.tags} disabled={locked} spellCheck={false} onChange={(event) => update("tags", event.target.value)} placeholder="1girl, blue_eyes, {long_hair}, outdoors, soft_lighting…" /></label>
        <div className="nai-secondary-fields"><label className="nai-field"><span>负面 Tag <small>NEGATIVE</small></span><textarea aria-label="负面 Tag" rows={3} value={fields.negative} disabled={locked} spellCheck={false} onChange={(event) => update("negative", event.target.value)} placeholder="lowres, blurry, bad_hands…" /></label><label className="nai-field"><span>前缀 Tag <small>PREFIX · 可选</small></span><textarea aria-label="前缀 Tag" rows={3} value={fields.prefix} disabled={locked} spellCheck={false} onChange={(event) => update("prefix", event.target.value)} placeholder="可复用的质量、风格等前缀" /></label></div>
      </section>
      <section className="nai-card nai-converter"><div className="nai-card-heading"><div><WandSparkles size={18} /><h2>自然语言转 Tag</h2></div><span className="nai-status-pill">只转换，不生图</span></div><p className="nai-caption">先描述画面，转换结果单独预览。应用后仍可修改，再由你确认生成。</p>
        <label className="nai-field"><span>自然语言描述</span><textarea aria-label="自然语言描述" rows={4} value={description} disabled={locked} onChange={(event) => { setDescription(event.target.value); setConversion(null); }} placeholder="例如：一个蓝眼睛的长发女孩，站在夕阳下的花园里，柔和的逆光…" /></label>
        <div className="nai-convert-controls"><label className="nai-field"><span>转换 LLM</span><select aria-label="转换 LLM" value={llmId} disabled={locked} onChange={(event) => { setLlmId(event.target.value); setConversion(null); }}><option value="">跟随当前会话的 LLM</option>{llmId && !models.some((item) => item.id === llmId) && <option value={llmId}>{llmId}（当前值，可能已不可用）</option>}{models.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.model}</option>)}</select></label><button type="button" className="nai-button nai-button-soft" disabled={locked || !description.trim() || !provider || !scope} onClick={() => void convert()}>{busy === "convert" ? <LoaderCircle size={16} className="nai-spinning" /> : <Sparkles size={16} />}{busy === "convert" ? "正在转换…" : "转换为 Tag 草稿"}</button></div>
        {!models.length && <p className="nai-caption">没有可选的文本 LLM。可跟随当前会话；如转换失败，请先在 AstrBot 配置文本模型。</p>}
        {conversion && <div className="nai-conversion-draft"><div className="nai-draft-heading"><strong><Sparkles size={15} />转换草稿（未生图）</strong><button type="button" className="nai-icon-button" aria-label="丢弃转换草稿" onClick={() => setConversion(null)}><X size={15} /></button></div><pre>{conversion.tags}</pre><button type="button" className="nai-button nai-button-solid" onClick={() => { invalidate(); setFields(conversion); setConversion(null); setStatus("草稿已预填充，请检查后确认。"); }}><ArrowDown size={15} />预填充到编辑区</button></div>}
      </section>
    </div>
    <aside className="nai-review-column"><section className="nai-card nai-review"><div className="nai-card-heading"><div><ShieldCheck size={18} /><h2>生成前审阅</h2></div></div><p className="nai-caption">这一份内容，就是最终提交的提示词。</p><div className="nai-review-meta"><span>连接<strong>{providerId || "未选择"}</strong></span><span>标签<strong>{tagCount} 个</strong></span></div>
      <label className="nai-field"><span>图片尺寸</span><input aria-label="图片尺寸" list="nai-image-sizes" value={size} disabled={locked} onChange={(event) => { invalidate(); setSize(event.target.value); }} placeholder="832x1216" /><datalist id="nai-image-sizes">{sizes.map((value) => <option key={value} value={value} />)}</datalist></label>
      <div className="nai-review-prompt"><span>最终正面提示词</span><pre>{finalPrompt || "填写画师串和正面 Tag 后，完整提示词将在这里展示。"}</pre></div><div className="nai-review-negative"><span>最终负面 Tag</span><p>{fields.negative || "未指定"}</p></div>
      <label className={"nai-review-check " + (reviewed ? "is-reviewed" : "")}><input type="checkbox" checked={reviewed} disabled={locked || !fields.tags.trim()} onChange={(event) => setReviewed(event.target.checked)} /><span>已检查画师串、正负面 Tag 和尺寸，确认使用当前内容生图</span></label>
      <button type="button" className="nai-button nai-button-solid nai-generate" disabled={locked || !reviewed || !provider || !scope || !fields.tags.trim()} onClick={() => void generate()}>{busy === "generate" ? <LoaderCircle size={18} className="nai-spinning" /> : <ImagePlus size={18} />}{busy === "generate" ? "正在提交…" : "确认并生成 NAI 图片"}</button><small className="nai-submit-note"><ShieldCheck size={12} />不二次转换 · 不自动追加画师串</small><a className="nai-tasks-link" href="#/tasks">前往任务中心 <ArrowRight size={14} /></a>
    </section></aside></div>
    {status && <p className="nai-feedback" role="status"><Check size={16} />{status}</p>}{error && <p className="form-error nai-feedback" role="alert">{error}</p>}
  </section>;
}
