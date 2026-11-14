import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Clapperboard, Download, ImagePlus, Play, RefreshCw, Sparkles, X } from "lucide-react";
import { createStudioJob, downloadStudioAsset, loadAssetPreview, resumeStudioJob, uploadStudioAsset } from "../../api/client";
import type { StudioSnapshot } from "../../api/contracts";
import "../../styles/gif-workbench.css";

function GifImage({ id, scope, alt }: { id: string; scope: string; alt: string }) {
  const [src, setSrc] = useState("");
  useEffect(() => { let active = true; setSrc(""); void loadAssetPreview(id, scope).then((value) => { if (active) setSrc(value); }).catch(() => {}); return () => { active = false; }; }, [id, scope]);
  return src ? <img src={src} alt={alt} /> : <div className="gif-image-loading">读取素材…</div>;
}

export function GifWorkbench({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const providers = (snapshot.config.providers || []).filter((item) => Boolean(item.base_url || item.api_url) && snapshot.capabilities.some((cap) => cap.provider_id === item.id && cap.operations.image_generate === "supported") && !String(item.__template_key || "").startsWith("nai_"));
  const [providerId, setProviderId] = useState("");
  const [protocol, setProtocol] = useState("openai");
  const [model, setModel] = useState("gpt-image-2.6-flare");
  const [prompt, setPrompt] = useState("");
  const [frames, setFrames] = useState(9);
  const [duration, setDuration] = useState(200);
  const [size, setSize] = useState("512x512");
  const [quality, setQuality] = useState("low");
  const [complexity, setComplexity] = useState("low");
  const [references, setReferences] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [library, setLibrary] = useState(false);
  const sequence = useRef(0);
  const locked = useRef(false);
  const submission = useRef({ signature: "", key: "" });
  const images = snapshot.assets.filter((item) => item.scope === scope && item.media_type === "image" && item.source !== "history" && !item.filename.toLowerCase().endsWith('.gif'));
  const jobs = snapshot.jobs.filter((item) => item.kind === "gif" && item.scope === scope);
  const job = jobs.find((item) => item.id === jobId) || jobs[0];
  const assetId = String(job?.result?.asset_id || "");
  const maxFrames = size === "768x768" ? 12 : 16;
  const referenceLimit = protocol === "spicy" ? 0 : 16;
  const invalid = frames > maxFrames || references.length > referenceLimit;

  useEffect(() => { sequence.current += 1; locked.current = false; setBusy(false); setUploading(false); setReferences([]); setJobId(""); setError(""); setLibrary(false); submission.current = { signature: "", key: "" }; }, [scope]);
  useEffect(() => { if (protocol === "spicy" && !["512x512", "768x768"].includes(size)) setSize("512x512"); }, [protocol]);
  useEffect(() => () => { sequence.current += 1; }, []);
  useEffect(() => {
    if (!jobs.some((item) => ["queued", "running"].includes(item.state))) return;
    const timer = window.setInterval(onRefresh, 4000);
    return () => window.clearInterval(timer);
  }, [jobs.map((item) => `${item.id}:${item.state}`).join(), onRefresh]);

  function chooseProvider(id: string) {
    setProviderId(id);
    const provider = providers.find((item) => item.id === id);
    const root = String(provider?.base_url || provider?.api_url || "");
    setProtocol(provider?.__template_key === "spicy_images" ? "spicy" : /apimart\./i.test(root) ? "apimart" : "openai");
    setError("");
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []); event.target.value = "";
    if (!files.length || uploading || busy) return;
    if (references.length + files.length > referenceLimit) { setError(`当前协议最多支持 ${referenceLimit} 张参考图`); return; }
    if (files.some((file) => !["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 20 * 1024 * 1024)) { setError("请使用不超过 20MB 的静态 PNG / JPEG / WebP"); return; }
    const version = sequence.current;
    setUploading(true); setError("");
    try {
      const ids: string[] = [];
      for (const file of files) {
        const item = await uploadStudioAsset(file, scope);
        if (version !== sequence.current) return;
        ids.push(item.asset_id);
      }
      setReferences((current) => [...new Set([...current, ...ids])]); onRefresh();
    } catch (reason) { if (version === sequence.current) setError(reason instanceof Error ? reason.message : "上传失败"); }
    finally { if (version === sequence.current) setUploading(false); }
  }

  async function generate() {
    if (locked.current || uploading || !scope || !providerId || !prompt.trim() || invalid) return;
    locked.current = true; setBusy(true); setError("");
    const version = sequence.current;
    const payload = { scope, kind: "gif", mode: "gif", provider_id: providerId, gif_protocol: protocol, gif_model: model,
      prompt: prompt.trim(), size, quality, complexity, frame_count: frames, frame_duration_ms: duration, reference_asset_ids: references };
    const signature = JSON.stringify(payload);
    if (submission.current.signature !== signature) submission.current = { signature, key: globalThis.crypto?.randomUUID?.() || `gif-${Date.now()}-${Math.random().toString(36).slice(2)}` };
    try {
      const created = await createStudioJob({ ...payload, idempotency_key: submission.current.key });
      if (version !== sequence.current) return;
      setJobId(created.id); onRefresh();
    } catch (reason) { if (version === sequence.current) setError(reason instanceof Error ? reason.message : "GIF 提交失败"); }
    finally { if (version === sequence.current) { locked.current = false; setBusy(false); } }
  }

  async function resume() {
    if (!job || busy) return;
    const version = sequence.current; setBusy(true); setError("");
    try { await resumeStudioJob(job.id, scope); if (version === sequence.current) onRefresh(); }
    catch (reason) { if (version === sequence.current) setError(String(reason)); }
    finally { if (version === sequence.current) setBusy(false); }
  }

  return <div className="gif-ai-workbench">
    <header className="gif-ai-heading"><div className="gif-ai-symbol"><Clapperboard size={25} /></div><div><span className="eyebrow">GPT IMAGE 2.6</span><h1>GIF 动画工作台</h1><p>让一个动作自然发生，再回到故事的起点。</p></div><span className="gif-ai-badge">Flare / Sunburst</span></header>
    <div className="gif-ai-layout"><div className="gif-ai-editor">
      <section className="gif-ai-card"><div className="gif-ai-card-title"><span>01</span><h2>连接与模型</h2></div>
        <div className="gif-ai-fields"><label className="stack-field"><span>连接服务商</span><select value={providerId} disabled={busy || uploading} onChange={(event) => chooseProvider(event.target.value)}><option value="">选择已配置的服务商</option>{providers.map((item) => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}</select></label>
        <label className="stack-field"><span>GIF 接口协议</span><select value={protocol} disabled={busy || uploading} onChange={(event) => setProtocol(event.target.value)}><option value="openai">OpenAI 同步图片接口</option><option value="apimart">APIMart 异步任务</option><option value="spicy">SpicyAPI 文生 GIF</option></select></label></div>
        <div className="gif-ai-models">{[["gpt-image-2.6-flare", "Flare", "快速探索动作与循环"], ["gpt-image-2.6-sunburst", "Sunburst", "侧重细节与视觉一致性"]].map(([id, title, subtitle]) => <button type="button" key={id} aria-pressed={model === id} disabled={busy} onClick={() => setModel(id)}><Sparkles size={17} /><span><strong>{title}</strong><small>{subtitle}</small></span><span className="gif-ai-radio" /></button>)}</div>
        <p className="gif-ai-note">复用服务商的地址与密钥，模型由本页指定。请确认所选渠道开放 GPT Image 2.6 及对应 GIF 协议。</p>
      </section>
      <section className="gif-ai-card"><div className="gif-ai-card-title"><span>02</span><h2>描述动画</h2></div><label className="stack-field"><span>主体、动作与循环方式</span><textarea aria-label="GIF 动画提示词" rows={5} maxLength={8000} value={prompt} disabled={busy} onChange={(event) => setPrompt(event.target.value)} placeholder="一只纸做的小猫轻轻抬起爪子挥手，耳朵微动，最后回到起始姿势。固定镜头，保持造型与背景一致，无缝循环。" /></label>
        <div className="gif-ai-prompt-tools"><button type="button" disabled={busy} onClick={() => setPrompt("参考图中的主体轻轻眨眼，头发随微风摆动，然后回到起始姿态。固定镜头，保持人物身份、服装和背景一致，无缝循环。")}>使用循环示例</button><span>{prompt.length} / 8000</span></div>
        <div className="gif-ai-reference-heading"><strong>参考图 <span>{references.length} / {referenceLimit}</span></strong><div><label className={`gif-ai-upload ${!scope || busy || uploading || referenceLimit === 0 ? "is-disabled" : ""}`}><ImagePlus size={14} />{uploading ? "上传中…" : "上传"}<input type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={!scope || busy || uploading || referenceLimit === 0} onChange={(event) => void upload(event)} /></label><button type="button" disabled={!scope || busy || uploading || referenceLimit === 0} onClick={() => setLibrary(!library)}>从素材库选择</button></div></div>
        {protocol === "spicy" && <p className="gif-ai-note">SpicyAPI 当前仅开放文生 GIF。已有参考图会保留，请移除后生成或切换支持参考图的协议。</p>}
        {references.length > 0 ? <div className="gif-ai-references">{references.map((id, index) => <div key={id}><GifImage id={id} scope={scope} alt={`参考图 ${index + 1}`} /><span>{index + 1}</span><button type="button" aria-label={`移除参考图 ${index + 1}`} disabled={busy || uploading} onClick={() => setReferences(references.filter((item) => item !== id))}><X size={12} /></button></div>)}</div> : <p className="gif-ai-note">可不传参考图直接生成；多图时在提示词中说明图一、图二分别提供哪些元素。</p>}
        {library && <div className="gif-ai-library">{images.map((item) => <button type="button" key={item.asset_id} disabled={references.includes(item.asset_id) || references.length >= referenceLimit || busy || uploading} onClick={() => setReferences([...references, item.asset_id])}><GifImage id={item.asset_id} scope={scope} alt={item.filename} /><span>{item.filename}</span></button>)}{!images.length && <p>当前会话暂无静态图片素材，可直接上传。</p>}</div>}
      </section>
      <section className="gif-ai-card"><div className="gif-ai-card-title"><span>03</span><h2>动画参数</h2><span className="gif-ai-duration">{(frames * duration / 1000).toFixed(2)} 秒 / 循环</span></div><div className="gif-ai-fields">
        <label className="stack-field"><span>每帧尺寸</span><select value={size} disabled={busy} onChange={(event) => setSize(event.target.value)}><option value="512x512">512 × 512 · 方形</option><option value="768x768">768 × 768 · 方形</option>{protocol !== "spicy" && <><option value="512x768">512 × 768 · 竖版</option><option value="768x512">768 × 512 · 横版</option></>}</select></label>
        <label className="stack-field"><span>动画帧数</span><select value={frames} disabled={busy} onChange={(event) => setFrames(Number(event.target.value))}>{Array.from({length:15}, (_,i) => i+2).map((n) => <option key={n} value={n} disabled={n>maxFrames}>{n} 帧{n>maxFrames ? "（当前尺寸不支持）" : ""}</option>)}</select></label>
        <label className="stack-field"><span>每帧时长（ms）</span><input type="number" min={20} max={2000} step={10} value={duration} disabled={busy} onChange={(event) => setDuration(Number(event.target.value))} /></label>
        <label className="stack-field"><span>渲染质量</span><select value={quality} disabled={busy} onChange={(event) => setQuality(event.target.value)}>{[["low","Low · 低成本草稿"],["medium","Medium · 均衡"],["high","High · 精细"],["xhigh","Extra high"],["max","Maximum"]].map(([v,l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="stack-field"><span>规划复杂度{protocol === "spicy" ? "（此渠道未开放）" : ""}</span><select value={complexity} disabled={busy || protocol === "spicy"} onChange={(event) => setComplexity(event.target.value)}><option value="low">Low · 单一动作</option><option value="medium">Medium · 均衡</option><option value="high">High · 复杂关系</option></select></label>
      </div><p className="gif-ai-note">费用按完整帧图计算，参考图另计输入；更高质量、更多帧或更大尺寸可能增加费用。每次生成 1 个 GIF。</p></section>
      {invalid && <p className="error-text" role="alert">当前尺寸最多 {maxFrames} 帧，当前协议最多 {referenceLimit} 张参考图，请调整后生成。</p>}{error && <p className="error-text" role="alert">{error}</p>}
      <button type="button" className="primary-action gif-ai-generate" disabled={busy || uploading || !scope || !providerId || !prompt.trim() || invalid || (duration % 10 !== 0 || duration < 20 || duration > 2000)} onClick={() => void generate()}><Sparkles size={17} />{busy ? "提交中…" : "生成 GIF 动画"}</button><p className="gif-ai-note">生成使用所选服务商余额。提交后可离开页面，任务继续运行；本地取消不保证取消远端计费。相同参数再次点击会查询同一任务，修改参数后才创建新任务。</p>
    </div><aside className="gif-ai-results"><section className="gif-ai-card"><div className="gif-ai-card-title"><Play size={17} /><h2>动画预览</h2>{job && <span className="gif-ai-badge">{{queued:"排队中",running:"生成中",completed:"已完成",failed:"失败",interrupted:"等待继续查询",cancelled:"已取消"}[job.state] || job.state}</span>}</div>
      <div className="gif-ai-preview">{assetId ? <GifImage key={assetId} id={assetId} scope={scope} alt="GPT Image 2.6 生成的 GIF 动画" /> : <div className="gif-ai-placeholder"><Clapperboard size={44} /><strong>{job && ["queued","running"].includes(job.state) ? "动画正在生成" : "让静态画面动起来"}</strong><p>成片将在这里循环播放，并自动存入素材库。</p></div>}</div>
      {job?.error && <p className="error-text">{job.error}</p>}{job?.upstream_task_id && <p className="gif-ai-task-id">上游任务：{job.upstream_task_id}</p>}
      <div className="gif-ai-result-actions">{job?.state === "completed" && <button type="button" disabled={busy || uploading || invalid || !prompt.trim() || !providerId} onClick={() => { submission.current = { signature: "", key: "" }; void generate(); }}><Sparkles size={15} />按当前参数再生成一版</button>}{assetId && <button type="button" className="primary-action" onClick={() => void downloadStudioAsset(assetId,"gpt-image-animation.gif",scope).catch((reason) => setError(String(reason)))}><Download size={15} />下载 GIF</button>}{job?.upstream_task_id && ["interrupted","cancelled"].includes(job.state) && <button type="button" disabled={busy} onClick={() => void resume()}><RefreshCw size={15} />继续查询原任务</button>}</div>
    </section><section className="gif-ai-card"><div className="gif-ai-card-title"><h2>本会话动画任务</h2><span>{jobs.length}</span></div><div className="gif-ai-job-list">{jobs.map((item) => <button type="button" key={item.id} className={job?.id === item.id ? "is-active" : ""} onClick={() => setJobId(item.id)}><strong>{item.prompt}</strong><small>{String(item.request?.gif_model || "").replace("gpt-image-2.6-","")} · {String(item.request?.frame_count || "")} 帧 · {{completed:"已完成",running:"生成中",queued:"排队中",failed:"失败",interrupted:"可继续查询",cancelled:"已取消"}[item.state] || item.state}</small></button>)}{!jobs.length && <p className="gif-ai-note">尚未生成动画。</p>}</div></section></aside></div>
  </div>;
}
