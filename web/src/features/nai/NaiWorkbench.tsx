import { useEffect, useRef, useState } from "react";
import type { ProviderConfig, StudioSnapshot } from "../../api/contracts";
import { createStudioJob, prepareNaiPrompt } from "../../api/client";

type Fields = { artist: string; tags: string; negative: string; prefix: string };
const empty: Fields = { artist: "", tags: "", negative: "", prefix: "" };

export function isNaiProvider(provider: ProviderConfig): boolean {
  const type = String(provider.__template_key || provider.__type || "");
  return ["nai_native", "nai_gateway", "nai_openai_images"].includes(type) ||
    (["openai_images"].includes(type) &&
      (/nai|novelai/i.test(String(provider.model || "")) || provider.nai_translate_prompt === true));
}

function compose(fields: Fields): string {
  return [fields.prefix, fields.artist, fields.tags].map((value) => value.trim().replace(/^[,\s]+|[,\s]+$/g, "")).filter(Boolean).join(", ");
}

export function NaiWorkbench({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const providers = (snapshot.config.providers || []).filter(isNaiProvider);
  const [providerId, setProviderId] = useState("");
  const [llmId, setLlmId] = useState("");
  const [fields, setFields] = useState<Fields>(empty);
  const [description, setDescription] = useState("");
  const [size, setSize] = useState("");
  const [draft, setDraft] = useState<Fields | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const sequence = useRef(0);
  const provider = providers.find((item) => item.id === providerId);

  useEffect(() => {
    if (!providers.some((item) => item.id === providerId)) setProviderId(providers[0]?.id || "");
  }, [snapshot.configRevision]);

  useEffect(() => {
    sequence.current += 1;
    setFields(empty); setDescription(""); setDraft(null); setReviewed(false);
    setSize(""); setBusy(""); setError(""); setStatus("");
  }, [scope, providerId]);

  function update(key: keyof Fields, value: string) {
    sequence.current += 1;
    setFields((current) => ({ ...current, [key]: value }));
    setReviewed(false); setStatus(""); setDraft(null);
  }

  function prefill() {
    if (!provider) return;
    sequence.current += 1;
    setFields({ artist: String(provider.nai_artist || ""), tags: "",
      prefix: String(provider.nai_prompt_prefix || ""), negative: String(provider.negative_prompt || "") });
    setSize(String(provider.default_size || ""));
    setLlmId(String(provider.nai_llm_provider_id || ""));
    setReviewed(false); setDraft(null); setStatus("已预填充服务商默认值，请填写或转换正面 Tag。");
  }

  async function convert() {
    const request = ++sequence.current;
    setBusy("convert"); setError(""); setDraft(null); setReviewed(false);
    try {
      const prompt = `${fields.artist ? `画师串：${fields.artist} ` : ""}正面：${description} 负面：${fields.negative}`;
      const result = await prepareNaiPrompt({ scope, provider_id: providerId, llm_provider_id: llmId, prompt });
      if (request !== sequence.current) return;
      setDraft({ artist: fields.artist || result.artist, tags: result.tags, negative: fields.negative, prefix: fields.prefix });
      setStatus("转换完成，尚未生图。检查草稿后预填充到编辑区。");
    } catch (reason) {
      if (request === sequence.current) setError(reason instanceof Error ? reason.message : "Tag 转换失败");
    } finally { if (request === sequence.current) setBusy(""); }
  }

  async function generate() {
    if (!reviewed || !provider || !scope || !fields.tags.trim()) return;
    setBusy("generate"); setError("");
    try {
      const id = globalThis.crypto?.randomUUID?.() || `nai-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      await createStudioJob({ scope, kind: "image", mode: "draw", provider_id: providerId,
        prompt: compose(fields), size, idempotency_key: id, nai_workbench: true, nai_reviewed: true,
        nai_artist: fields.artist, nai_tags: fields.tags, nai_prefix: fields.prefix, negative_prompt: fields.negative });
      setReviewed(false); setStatus("NAI 生图任务已提交，可在任务中心查看结果。"); onRefresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "NAI 生图提交失败"); }
    finally { setBusy(""); }
  }

  return <section className="nai-workbench">
    <div className="panel-heading"><div><span className="section-kicker">NOVELAI</span><h1>NAI 工作台</h1><p>独立编辑画师串与 Tag。自然语言转换只生成草稿，审阅确认后才提交图片任务。</p></div></div>
    {!providers.length && <p className="capability-notice">请先在服务商页添加 NAI 原生或 NAI OpenAI 兼容模板。</p>}
    {!scope && <p className="capability-notice">请先选择目标会话。</p>}
    <div className="settings-field-grid">
      <label className="stack-field"><span>NAI 服务商</span><select value={providerId} disabled={Boolean(busy)} onChange={(event) => setProviderId(event.target.value)}><option value="">选择 NAI 服务商</option>{providers.map((item) => <option key={item.id} value={item.id}>{item.id} · {String(item.model || "")}</option>)}</select></label>
      <label className="stack-field"><span>图片尺寸</span><input value={size} disabled={Boolean(busy)} placeholder={String(provider?.default_size || "832x1216")} onChange={(event) => { setSize(event.target.value); setReviewed(false); }} /></label>
    </div>
    <button type="button" className="secondary-action" disabled={!provider || Boolean(busy)} onClick={prefill}>预填充服务商默认值</button>
    <div className="nai-tag-grid">{([["prefix", "前缀 Tag"], ["artist", "画师串"], ["tags", "正面 Tag"], ["negative", "负面 Tag"]] as const).map(([key, label]) => <label className="stack-field" key={key}><span>{label}</span><textarea rows={key === "tags" ? 7 : 3} value={fields[key]} disabled={Boolean(busy)} spellCheck={false} onChange={(event) => update(key, event.target.value)} placeholder={key === "artist" ? "artist:画师名，支持完整权重画师串" : "保留逗号、权重和原始 Tag 语法"} /></label>)}</div>
    <section className="settings-section"><h2>自然语言转 Tag</h2>
      <label className="stack-field"><span>自然语言描述</span><textarea rows={4} value={description} disabled={Boolean(busy)} onChange={(event) => { sequence.current += 1; setDescription(event.target.value); setDraft(null); }} /></label>
      <label className="stack-field"><span>转换 LLM</span><select value={llmId} disabled={Boolean(busy)} onChange={(event) => { setLlmId(event.target.value); setDraft(null); }}><option value="">跟随服务商配置或当前会话</option>{(snapshot.config.astrbot_providers || []).map((item: { id: string; model?: string }) => <option key={item.id} value={item.id}>{item.id} · {item.model}</option>)}</select></label>
      <button type="button" className="secondary-action" disabled={Boolean(busy) || !description.trim() || !provider || !scope} onClick={() => void convert()}>{busy === "convert" ? "转换中…" : "转换为 Tag 草稿"}</button>
      {draft && <div className="nai-conversion-draft"><h3>转换草稿（未生图）</h3><pre>{`画师串：${draft.artist || "（未指定）"}\n正面 Tag：${draft.tags}`}</pre><button type="button" className="secondary-action" onClick={() => { setFields(draft); setDraft(null); setReviewed(false); setStatus("草稿已预填充，请检查画师串和 Tag。"); }}>预填充到编辑区</button></div>}
    </section>
    <section className="settings-section"><h2>生图前审阅</h2><pre className="nai-final-prompt">{compose(fields) || "请填写画师串和正面 Tag"}</pre><p>画师名称由你填写或从服务商配置预填充，转换模型不会自动猜测画师。</p>
      <label className="tool-toggle"><input type="checkbox" checked={reviewed} disabled={Boolean(busy) || !fields.tags.trim()} onChange={(event) => setReviewed(event.target.checked)} />已检查画师串、正负面 Tag 和尺寸，确认使用当前内容生图</label>
      <button type="button" className="primary-action" disabled={Boolean(busy) || !reviewed || !provider || !scope || !fields.tags.trim()} onClick={() => void generate()}>{busy === "generate" ? "提交中…" : "确认并生成 NAI 图片"}</button>
    </section>
    {status && <p role="status">{status}</p>}{error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
