import {
  ArrowDown,
  ArrowUp,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  CircleStop,
  Download,
  FolderOpen,
  Hand,
  MousePointer2,
  Maximize,
  ImagePlus,
  Image as ImageIcon,
  Moon,
  Pause,
  Play,
  Redo2,
  RefreshCw,
  RotateCcw,
  RotateCw,
  Send,
  Sun,
  Trash2,
  Undo2,
  Wifi,
  X,
  ZoomIn,
  ZoomOut,
  Pencil,
  Video,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type PointerEvent as ReactPointerEvent } from "react";
import {
  cancelTask,
  cancelStudioJob,
  createStudioGif,
  createStudioJob,
  loadProjectJobs,
  loadStudioProject,
  draftAgent,
  reviewAgent,
  executeAgent,
  transformStudioPrompt,
  generateWebReplica,
  sliceStudioAsset,
  downloadStudioAsset,
  downloadStudioJobMedia,
  deleteStudioAsset,
  loadAssetPreview,
  loadHistoryPreview,
  loadPersonaReferencePreview,
  loadStudioSnapshot,
  deleteStudioPersona,
  pinStudioAsset,
  preserveHistoryAsset,
  resumeStudioJob,
  saveStudioPersona,
  saveStudioProvider,
  saveStudioProject,
  exportWebProject,
  exportMediaProject,
  loadProjectVersions,
  saveStudioPreferences,
  setSessionPersona,
  switchStudioPersona,
  uploadStudioAsset,
  uploadStudioReference,
  uploadStudioPersonaReference,
} from "../api/client";
import type {
  StudioAsset,
  HistoryItem,
  ManagedTask,
  ProviderCapability,
  StudioJob,
  StudioProject,
  StudioSnapshot,
  PersonaProfile,
  PersonaReferenceRole,
  ProviderConfig,
} from "../api/contracts";
import { readRoute, routeHref, routes, type RouteId } from "./routes";
import { PresetEditor } from "../features/prompts/PresetEditor";
import { buildStaticPreview } from "../features/design/static-preview";

const EMPTY_SNAPSHOT: StudioSnapshot = {
  config: {},
  capabilities: [],
  jobs: [],
  tasks: [],
  history: [],
  historyTotal: 0,
  assets: [],
  projects: [],
  sessions: [],
  personas: [],
  personaProfiles: [],
};

const TASK_LABELS: Record<string, string> = {
  preparing: "准备中",
  generating: "生成中",
  downloading: "下载中",
  sending: "发送中",
  cancelling: "取消中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "等待继续",
};

const TERMINAL_TASKS = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
]);

function formatTime(value: number): string {
  if (!value) return "未记录";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value * 1000));
}

function HistoryPreview({ item }: { item: HistoryItem }) {
  const [source, setSource] = useState("");

  useEffect(() => {
    let active = true;
    if (!item.available) return;
    loadHistoryPreview(item.id)
      .then((value) => {
        if (active) setSource(value);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [item.id, item.available]);

  return source ? (
    <img src={source} alt="" loading="lazy" />
  ) : (
    <div className="media-placeholder">
      <ImageIcon size={22} aria-hidden="true" />
    </div>
  );
}

type CreateMode = "image" | "edit" | "selfie" | "video";

function openAssetInCreate(assetId: string, mode: "edit" | "video") {
  const params = new URLSearchParams({ asset: assetId });
  window.location.hash = `#/create/${mode}?${params.toString()}`;
}

const CREATE_MODES: Array<{
  id: CreateMode;
  label: string;
  operation: string;
}> = [
  { id: "image", label: "文生图", operation: "image_generate" },
  { id: "edit", label: "改图", operation: "image_edit" },
  { id: "selfie", label: "自拍", operation: "image_edit" },
  { id: "video", label: "视频", operation: "video_generate" },
];

function capabilityForMode(
  capability: ProviderCapability,
  mode: CreateMode,
): "supported" | "unsupported" | "unknown" {
  const operation = CREATE_MODES.find((item) => item.id === mode)?.operation || "";
  return capability.operations[operation] || "unknown";
}

function CreateView({
  snapshot,
  scope,
  onScopeChange,
  onSubmitted,
}: {
  snapshot: StudioSnapshot;
  scope: string;
  onScopeChange: (scope: string) => void;
  onSubmitted: () => void;
}) {
  const [mode, setMode] = useState<CreateMode>("image");
  const [providerId, setProviderId] = useState("");
  const [prompt, setPrompt] = useState(() => (
    typeof window === "undefined" ? "" : window.localStorage.getItem("aiimg-studio-prompt-draft") || ""
  ));
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [referenceAssetIds, setReferenceAssetIds] = useState<string[]>([]);
  const [seconds, setSeconds] = useState("");
  const [aspectRatio, setAspectRatio] = useState("");
  const [resolution, setResolution] = useState("");
  const [size, setSize] = useState("");
  const [referenceMode, setReferenceMode] = useState("");
  const [uploading, setUploading] = useState(false);
  const uploadSequence = useRef(0);
  const capabilities = snapshot.capabilities;
  const providers = capabilities.filter(
    (capability) => capabilityForMode(capability, mode) === "supported",
  );
  const selected = capabilities.find(
    (capability) => capability.provider_id === providerId,
  );
  const videoDuration = selected?.parameters.duration;
  const aspectOptions = selected?.parameters.aspect_ratios?.values || [];
  const resolutionOptions = selected?.parameters.resolutions?.values || [];
  const sizeOptions = selected?.parameters.sizes?.values || [];
  const referenceOptions = selected?.references.modes.filter(
    (item) => item.status === "supported",
  ) || [];
  const activeReferenceMode = referenceOptions.find((item) => item.id === referenceMode);
  const referenceLimit = Math.min(9, activeReferenceMode?.max_images ?? 9);
  const presetFeature = mode === "image" ? "draw" : mode === "video" ? "video" : "edit";
  const presets = (snapshot.config.features?.[presetFeature]?.presets || []).flatMap((value) => {
    if (typeof value !== "string") return [];
    const colon = value.indexOf(":");
    return colon > 0 ? [{ name: value.slice(0, colon), prompt: value.slice(colon + 1) }] : [];
  });
  const referenceError = (mode === "edit" || mode === "video") && referenceAssetIds.length > referenceLimit
    ? `当前参考模式最多支持 ${referenceLimit} 张图片`
    : mode === "video" && activeReferenceMode && referenceAssetIds.length > 0 && referenceAssetIds.length < activeReferenceMode.min_images
      ? `当前参考模式需要至少 ${activeReferenceMode.min_images} 张图片` : "";

  useEffect(() => {
    if (prompt) localStorage.removeItem("aiimg-studio-prompt-draft");
  }, []);

  useEffect(() => {
    if (providerId && !providers.some((provider) => provider.provider_id === providerId)) {
      setProviderId("");
    }
  }, [mode, providerId, providers]);

  useEffect(() => {
    setSeconds(mode === "video" ? String(videoDuration?.default ?? "") : "");
    setAspectRatio(mode === "video" ? selected?.parameters.aspect_ratios?.default || "" : "");
    setResolution(selected?.parameters.resolutions?.default || "");
    setSize(selected?.parameters.sizes?.default || "");
    setReferenceMode(mode === "video" ? selected?.references.active_mode || "" : "");
  }, [mode, providerId]);

  useEffect(() => {
    if (mode !== "video") {
      setSeconds("");
      setAspectRatio("");
      setReferenceMode("");
    }
  }, [mode]);

  useEffect(() => {
    uploadSequence.current += 1;
    setUploading(false);
    setReferenceAssetIds([]);
    const match = window.location.hash.match(/^#\/create\/(edit|video)\?(.*)$/);
    if (!match) return;
    const assetId = new URLSearchParams(match[2]).get("asset");
    const asset = snapshot.assets.find((item) => item.asset_id === assetId);
    if (!asset || asset.scope !== scope || asset.media_type !== "image") {
      setSubmitError("参考素材不可用或不属于当前会话");
      return;
    }
    setMode(match[1] as "edit" | "video");
    setReferenceAssetIds([asset.asset_id]);
    setSubmitError("");
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/create`);
  }, [scope]);

  useEffect(() => () => { uploadSequence.current += 1; }, []);

  async function submit() {
    if (!scope || !prompt.trim() || uploading || referenceError) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      await createStudioJob({
        idempotency_key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        scope,
        kind: mode === "video" ? "video" : "image",
        mode: mode === "image" ? "draw" : mode,
        prompt: prompt.trim(),
        provider_id: providerId,
        seconds: mode === "video" ? seconds : undefined,
        aspect_ratio: mode === "video" ? aspectRatio : undefined,
        resolution,
        size,
        reference_mode: mode === "video" ? referenceMode : undefined,
        reference_asset_ids: mode === "edit" || mode === "video" ? referenceAssetIds : [],
      });
      setPrompt("");
      setReferenceAssetIds([]);
      onSubmitted();
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function onReferenceChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    if (files.length + referenceAssetIds.length > referenceLimit) {
      setSubmitError(`最多支持 ${referenceLimit} 张参考图，请先移除多余图片`);
      event.target.value = "";
      return;
    }
    const sequence = ++uploadSequence.current;
    setUploading(true);
    setSubmitError("");
    try {
      if (!scope) throw new Error("请先选择目标会话");
      const uploaded = await Promise.all(files.map((file) => uploadStudioReference(file, scope)));
      if (sequence === uploadSequence.current) setReferenceAssetIds((current) => [...current, ...uploaded.filter(Boolean)]);
    } catch (reason) {
      if (sequence === uploadSequence.current) setSubmitError(reason instanceof Error ? reason.message : "参考图上传失败");
    } finally {
      event.target.value = "";
      if (sequence === uploadSequence.current) setUploading(false);
    }
  }

  function referenceSummary(capability?: ProviderCapability): string {
    if (!capability) return "选择服务商后显示约束";
    if (capability.references.status === "unsupported") return "不支持参考图";
    const modes = capability.references.modes.filter(
      (item) => item.status === "supported" && item.max_images > 0,
    );
    if (!modes.length) return "参考图能力未知";
    return modes
      .map((item) => `${item.label} ${item.min_images}-${item.max_images} 张`)
      .join(" / ");
  }

  return (
    <section className="workspace create-workspace">
      <div className="workspace-heading">
        <div>
          <span className="section-kicker">CREATE</span>
          <h1>创作工作台</h1>
        </div>
        <span className="connection-chip">
          <Wifi size={14} aria-hidden="true" />
          {capabilities.length} 个服务商
        </span>
      </div>

      <div className="mode-switch" aria-label="创作模式">
        {CREATE_MODES.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            className={mode === id ? "active" : ""}
            onClick={() => setMode(id)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="composer-layout">
        <div className="prompt-editor">
          <label htmlFor="studio-prompt">提示词</label>
          <textarea
            id="studio-prompt"
            placeholder="描述画面、角色、镜头和氛围"
            rows={8}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <div className="composer-fields">
            <select aria-label="应用预设" value="" onChange={(event) => {
              const preset = presets[Number(event.target.value)];
              if (preset && (!prompt.trim() || window.confirm("用此预设替换当前提示词？"))) setPrompt(preset.prompt);
            }}>
              <option value="">选择预设</option>
              {presets.map((preset, index) => <option key={index} value={index}>{preset.name}</option>)}
            </select>
            <select aria-label="目标会话" value={scope} onChange={(event) => onScopeChange(event.target.value)}>
              <option value="">选择目标会话</option>
              {snapshot.sessions.map((session) => (
                <option key={session.scope} value={session.scope}>
                  {session.title || session.conversation || session.scope}
                </option>
              ))}
            </select>
            {(mode === "edit" || mode === "video") && (
              <label className="file-picker">
                <span>添加参考图（已选 {referenceAssetIds.length} 张）</span>
                <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={uploading || submitting || referenceAssetIds.length >= referenceLimit} onChange={(event) => void onReferenceChange(event)} />
              </label>
            )}
            {(mode === "edit" || mode === "video") && referenceAssetIds.length > 0 && <div className="reference-slots">
              {referenceAssetIds.map((id, index) => {
                const asset = snapshot.assets.find((item) => item.asset_id === id) || {
                  asset_id: id, scope, media_type: "image", filename: `参考图 ${index + 1}`, created_at: 0,
                };
                return <article className="reference-slot" key={`${id}-${index}`}>
                  <AssetPreview item={asset} />
                  <span>{referenceMode === "first_last_frame" ? (index === 0 ? "首帧" : "尾帧") : `参考图 ${index + 1}`}</span>
                  <div className="composer-actions">
                    <button type="button" className="icon-button" title="前移参考图" disabled={submitting || uploading || index === 0} onClick={() => setReferenceAssetIds((current) => {
                      const next = [...current]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next;
                    })}><ArrowUp size={16} /><span className="sr-only">前移参考图</span></button>
                    <button type="button" className="icon-button" title="后移参考图" disabled={submitting || uploading || index === referenceAssetIds.length - 1} onClick={() => setReferenceAssetIds((current) => {
                      const next = [...current]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; return next;
                    })}><ArrowDown size={16} /><span className="sr-only">后移参考图</span></button>
                    <button type="button" className="icon-button danger" title="移除参考图" disabled={submitting || uploading} onClick={() => setReferenceAssetIds((current) => current.filter((_, position) => position !== index))}><X size={16} /><span className="sr-only">移除参考图</span></button>
                  </div>
                </article>;
              })}
            </div>}
            {selected && (
              <div className="video-options">
                {mode === "video" && videoDuration?.status === "supported" && (
                  <label>
                    <span>时长（秒）</span>
                    <input
                      type="number"
                      min={videoDuration.minimum}
                      max={videoDuration.maximum}
                      step="1"
                      value={seconds}
                      onChange={(event) => setSeconds(event.target.value)}
                    />
                  </label>
                )}
                {mode === "video" && aspectOptions.length > 0 && (
                  <label>
                    <span>画幅</span>
                    <select value={aspectRatio} onChange={(event) => setAspectRatio(event.target.value)}>
                      {aspectOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                )}
                {resolutionOptions.length > 0 && (
                  <label>
                    <span>分辨率</span>
                    <select value={resolution} onChange={(event) => setResolution(event.target.value)}>
                      {resolutionOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                )}
                {sizeOptions.length > 0 && (
                  <label>
                    <span>尺寸</span>
                    <select value={size} onChange={(event) => setSize(event.target.value)}>
                      {sizeOptions.map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                )}
                {mode === "video" && referenceOptions.length > 0 && (
                  <label>
                    <span>参考模式</span>
                    <select value={referenceMode} onChange={(event) => setReferenceMode(event.target.value)}>
                      <option value="">自动</option>
                      {referenceOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select>
                  </label>
                )}
              </div>
            )}
          </div>
          <div className="composer-actions">
            <select
              aria-label="服务商"
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
            >
              <option value="">自动选择服务商</option>
              {providers.map((provider) => (
                <option key={provider.provider_id} value={provider.provider_id}>
                  {provider.label || provider.provider_id}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="primary-action"
              disabled={submitting || uploading || Boolean(referenceError) || !scope || !prompt.trim() || (mode === "edit" && referenceAssetIds.length === 0)}
              onClick={() => void submit()}
            >
              <Send size={17} aria-hidden="true" />
              {submitting ? "提交中" : "生成"}
            </button>
          </div>
          {mode !== "image" && (
            <p className="capability-notice">视频会进入统一任务中心并先下载到插件素材；改图和自拍会复用现有图片服务与会话人设。</p>
          )}
          {!scope && <p className="capability-notice">请先选择已有会话，任务结果会写入该会话的历史。</p>}
          {submitError && <p className="task-error">{submitError}</p>}
          {referenceError && <p className="task-error">{referenceError}</p>}
          {providers.length === 0 && (
            <p className="capability-notice">
              当前没有明确支持此模式的服务商。能力未知的模板不会自动开放。
            </p>
          )}
        </div>

        <aside className="runtime-summary">
          <h2>能力概览</h2>
          <dl>
            <div>
              <dt>可用服务商</dt>
              <dd>{providers.length}</dd>
            </div>
            <div>
              <dt>协议</dt>
              <dd>{selected?.protocol.id || "自动"}</dd>
            </div>
            <div>
              <dt>已核验</dt>
              <dd>{selected?.protocol.last_verified || "未知"}</dd>
            </div>
          </dl>
          <div className="capability-details">
            <div>
              <span>参考输入</span>
              <strong>{referenceSummary(selected)}</strong>
            </div>
            <div>
              <span>分辨率</span>
              <strong>
                {selected?.parameters.resolutions?.values.join(" / ") || "由服务商决定"}
              </strong>
            </div>
            <div>
              <span>画幅</span>
              <strong>
                {selected?.parameters.aspect_ratios?.values.join(" / ") || "由服务商决定"}
              </strong>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function TasksView({
  tasks,
  jobs,
  onRefresh,
}: {
  tasks: ManagedTask[];
  jobs: StudioJob[];
  onRefresh: () => void;
}) {
  const [cancelling, setCancelling] = useState("");

  async function onCancel(task: ManagedTask) {
    if (!window.confirm("取消本地任务？上游任务可能仍会继续。")) return;
    setCancelling(task.id);
    try {
      await cancelTask(task.id);
      onRefresh();
    } finally {
      setCancelling("");
    }
  }

  async function onCancelJob(job: StudioJob) {
    if (!window.confirm("取消本地 Studio 任务？已提交的上游请求可能仍会继续。")) return;
    setCancelling(job.id);
    try {
      await cancelStudioJob(job.id, job.scope);
      onRefresh();
    } finally {
      setCancelling("");
    }
  }

  async function onResumeJob(job: StudioJob) {
    setCancelling(job.id);
    try {
      await resumeStudioJob(job.id, job.scope);
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "恢复任务失败");
    } finally {
      setCancelling("");
    }
  }

  const jobTerminal = new Set(["completed", "partial", "failed", "cancelled"]);

  return (
    <section className="workspace">
      <div className="workspace-heading">
        <div>
          <span className="section-kicker">TASKS</span>
          <h1>任务管理</h1>
        </div>
        <button type="button" className="icon-button" onClick={onRefresh}>
          <RefreshCw size={18} />
          <span className="sr-only">刷新任务</span>
        </button>
      </div>
      <div className="task-table studio-job-table">
        {jobs.length > 0 && <div className="subsection-heading">Studio 任务</div>}
        {jobs.map((job) => (
          <article className="task-row" key={job.id}>
            <span className={"task-state state-" + job.state}>
              {jobTerminal.has(job.state) ? <CheckCircle2 size={17} aria-hidden="true" /> : <RefreshCw size={17} aria-hidden="true" />}
              {TASK_LABELS[job.state] || job.state}
            </span>
            <div className="task-main">
              <strong>{job.prompt || "Studio 生成任务"}</strong>
              <small>{formatTime(job.created_at)} · {job.mode === "draw" ? "文生图" : job.mode === "video" ? "视频" : "改图"} · {job.id}</small>
              {(job.provider_id || job.upstream_task_id) && <small>{job.provider_id || "服务商未知"}{job.upstream_task_id ? ` · 上游 ${job.upstream_task_id}` : ""}</small>}
              {job.error && <p className="task-error">{job.error}</p>}
            </div>
            <span className="task-count">{job.state === "completed" ? "1/1" : "-"}</span>
            <div className="task-actions">
              {(job.state === "interrupted" || job.state === "failed") && job.upstream_task_id && (
                <button type="button" className="icon-button" onClick={() => void onResumeJob(job)} disabled={cancelling === job.id} title="继续查询上游任务">
                  <RefreshCw size={18} />
                  <span className="sr-only">继续查询上游任务</span>
                </button>
              )}
              {job.state === "completed" && Boolean(job.result?.video_path) && (
                <button type="button" className="icon-button" onClick={() => void downloadStudioJobMedia(job.id, job.scope)}>
                  <Download size={18} />
                  <span className="sr-only">下载视频</span>
                </button>
              )}
              {!jobTerminal.has(job.state) && (
                <button type="button" className="icon-button danger" onClick={() => void onCancelJob(job)} disabled={cancelling === job.id}>
                  <CircleStop size={18} />
                  <span className="sr-only">取消 Studio 任务</span>
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      <div className="task-table">
        {tasks.length === 0 ? (
          <div className="empty-state">暂无任务</div>
        ) : (
          tasks.map((task) => (
            <article className="task-row" key={task.id}>
              <span className={"task-state state-" + task.state}>
                {TERMINAL_TASKS.has(task.state) ? (
                  <CheckCircle2 size={17} aria-hidden="true" />
                ) : (
                  <RefreshCw size={17} aria-hidden="true" />
                )}
                {TASK_LABELS[task.state] || task.state}
              </span>
              <div className="task-main">
                <strong>{task.prompt || task.kind || "生成任务"}</strong>
                <small>
                  {formatTime(task.created_at)} · {task.persona || "默认人设"} ·{" "}
                  {task.conversation || "默认会话"}
                </small>
                {task.error && <p className="task-error">{task.error}</p>}
              </div>
              <span className="task-count">
                {task.generated || 0}/{task.sent || 0}
              </span>
              {!TERMINAL_TASKS.has(task.state) && (
                <button
                  type="button"
                  className="icon-button danger"
                  onClick={() => onCancel(task)}
                  disabled={cancelling === task.id}
                >
                  <CircleStop size={18} />
                  <span className="sr-only">取消任务</span>
                </button>
              )}
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function HistoryView({ snapshot }: { snapshot: StudioSnapshot }) {
  return (
    <section className="workspace">
      <div className="workspace-heading">
        <div>
          <span className="section-kicker">ASSETS</span>
          <h1>生成历史</h1>
        </div>
        <span className="connection-chip">{snapshot.historyTotal} 张</span>
      </div>
      <div className="history-grid">
        {snapshot.history.map((item) => (
          <article className="history-card" key={item.id}>
            <div className="history-media">
              <HistoryPreview item={item} />
              <span className="history-sequence">{item.sequence}</span>
            </div>
            <div className="history-copy">
              <strong>{item.prompt || "未记录提示词"}</strong>
              <small>
                {item.conversation_title ||
                  item.conversation ||
                  "默认会话"}
              </small>
              <small>
                {formatTime(item.created_at)}
                {item.provider ? " · " + item.provider : ""}
              </small>
            </div>
          </article>
        ))}
        {snapshot.history.length === 0 && (
          <div className="empty-state">暂无生成历史</div>
        )}
      </div>
    </section>
  );
}

function AssetPreview({ item }: { item: StudioAsset; history?: HistoryItem[] }) {
  const [source, setSource] = useState("");

  useEffect(() => {
    let active = true;
    if (item.source === "history" && item.history_id && item.scope) {
      loadHistoryPreview(item.history_id, item.scope)
        .then((value) => active && setSource(value))
        .catch(() => undefined);
    } else if (item.media_type === "image") {
      loadAssetPreview(item.asset_id, item.scope)
        .then((value) => active && setSource(value))
        .catch(() => undefined);
    }
    return () => {
      active = false;
    };
  }, [item.asset_id, item.history_id, item.media_type, item.scope, item.source]);

  if (item.media_type === "video") {
    return <div className="media-placeholder"><Download size={22} aria-hidden="true" /></div>;
  }
  return source ? (
    <img src={source} alt="" loading="lazy" />
  ) : (
    <div className="media-placeholder"><ImageIcon size={22} aria-hidden="true" /></div>
  );
}

function AssetsView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const [busy, setBusy] = useState("");
  const assets = snapshot.assets;

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []).slice(0, 12);
    if (!scope || !files.length) return;
    setBusy("upload");
    try {
      await Promise.all(files.map((file) => uploadStudioAsset(file, scope)));
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "素材上传失败");
    } finally {
      setBusy("");
      event.target.value = "";
    }
  }

  async function togglePin(item: StudioAsset) {
    setBusy(item.asset_id);
    try {
      if (item.source === "history") {
        if (!item.history_id || !item.scope) throw new Error("历史图片会话信息不完整");
        await preserveHistoryAsset(item.history_id, item.scope);
      } else {
        await pinStudioAsset(item.asset_id, !item.pinned, item.scope);
      }
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "素材保存失败");
    } finally {
      setBusy("");
    }
  }

  async function remove(item: StudioAsset) {
    if (item.source === "history" || !window.confirm(`删除素材「${item.filename}」？`)) return;
    setBusy(item.asset_id);
    try {
      await deleteStudioAsset(item.asset_id, item.scope);
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "素材删除失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="workspace">
      <div className="workspace-heading">
        <div><span className="section-kicker">ASSETS</span><h1>素材库</h1></div>
        <label className="secondary-action">
          <ImagePlus size={16} aria-hidden="true" />
          {busy === "upload" ? "上传中" : "导入素材"}
          <input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm" multiple onChange={(event) => void upload(event)} />
        </label>
      </div>
      {!scope && <p className="capability-notice">请先在创作页选择一个已有会话，素材会按会话隔离。</p>}
      <div className="history-grid asset-grid">
        {assets.map((item) => (
          <article className="history-card" key={item.asset_id}>
            <div className="history-media"><AssetPreview item={item} history={snapshot.history} /></div>
            <div className="history-copy">
              <strong>{item.prompt || item.filename}</strong>
              <small>{item.source === "history" ? (item.conversation_title || item.conversation || "历史图片") : item.media_type}</small>
              <small>{formatTime(item.created_at)}{item.pinned ? " · 已收藏" : ""}</small>
              <div className="asset-actions">
                {item.media_type === "image" && item.scope === scope && item.source !== "history" && <>
                  <button type="button" className="icon-button" title="继续改图" onClick={() => openAssetInCreate(item.asset_id, "edit")}><Pencil size={17} /><span className="sr-only">继续改图</span></button>
                  <button type="button" className="icon-button" title="生成视频" onClick={() => openAssetInCreate(item.asset_id, "video")}><Video size={17} /><span className="sr-only">生成视频</span></button>
                </>}
                {item.source !== "history" && <button type="button" className="icon-button" onClick={() => void downloadStudioAsset(item.asset_id, item.filename, item.scope)} title="下载素材"><Download size={17} /><span className="sr-only">下载素材</span></button>}
                <button type="button" className="icon-button" onClick={() => void togglePin(item)} disabled={busy === item.asset_id} title={item.source === "history" ? "存入素材库" : item.pinned ? "取消收藏" : "收藏素材"}>
                  {item.pinned ? <CheckCircle2 size={17} /> : <FolderOpen size={17} />}
                  <span className="sr-only">{item.source === "history" ? "存入素材库" : item.pinned ? "取消收藏" : "收藏素材"}</span>
                </button>
                {item.source !== "history" && <button type="button" className="icon-button danger" onClick={() => void remove(item)} disabled={busy === item.asset_id} title="删除素材"><X size={17} /><span className="sr-only">删除素材</span></button>}
              </div>
            </div>
          </article>
        ))}
        {assets.length === 0 && <div className="empty-state">暂无素材。可以从创作页上传参考图，或等待生成结果。</div>}
      </div>
    </section>
  );
}

type CanvasNode = {
  id: string; type: "asset" | "generation"; asset_id: string;
  x: number; y: number; scale: number; rotation: number;
  job_id?: string; submission_key?: string;
  prompt?: string; provider_id?: string; size?: string; resolution?: string;
  mode?: "draw" | "edit"; reference_asset_ids?: string[];
};
type CanvasEdge = { id: string; from: string; to: string };
type CanvasEdit = { nodes: CanvasNode[]; edges: CanvasEdge[] };

function normalizeCanvasNodes(value: unknown): CanvasNode[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const raw = item as Record<string, unknown>;
    const assetId = String(raw.asset_id || "").trim();
    const type = raw.type === "generation" ? "generation" : "asset";
    if (!assetId && type !== "generation") return [];
    const numberValue = (input: unknown, fallback: number) => {
      const parsed = Number(input);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    return [{
      id: String(raw.id || `node-${index + 1}`),
      type,
      asset_id: assetId,
      x: numberValue(raw.x, 80 + index * 24),
      y: numberValue(raw.y, 80 + index * 24),
      scale: Math.max(0.25, Math.min(3, numberValue(raw.scale, 1))),
      rotation: numberValue(raw.rotation, 0),
      ...(type === "generation" ? {
        job_id: String(raw.job_id || ""),
        submission_key: String(raw.submission_key || ""),
        prompt: String(raw.prompt || ""),
        provider_id: String(raw.provider_id || ""),
        size: String(raw.size || ""),
        resolution: String(raw.resolution || ""),
        mode: raw.mode === "edit" ? "edit" as const : "draw" as const,
        reference_asset_ids: Array.isArray(raw.reference_asset_ids) ? raw.reference_asset_ids.map(String).slice(0, 9) : [],
      } : {}),
    }];
  });
}

function cloneCanvasNodes(nodes: CanvasNode[]): CanvasNode[] {
  return nodes.map((node) => ({ ...node }));
}

function normalizeCanvasEdges(value: unknown, nodes: CanvasNode[]): CanvasEdge[] {
  if (!Array.isArray(value)) return [];
  const ids = new Set(nodes.map((node) => node.id));
  const seen = new Set<string>();
  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const raw = item as Record<string, unknown>;
    const from = String(raw.from || "");
    const to = String(raw.to || "");
    const pair = `${from}\0${to}`;
    if (!ids.has(from) || !ids.has(to) || from === to || seen.has(pair)) return [];
    seen.add(pair);
    return [{ id: String(raw.id || `edge-${index + 1}`), from, to }];
  });
}

function CanvasView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const [importedAssets, setImportedAssets] = useState<StudioAsset[]>([]);
  const importing = useRef(false);
  const importVersion = useRef(0);
  const projects = snapshot.projects.filter((item) => item.kind === "canvas" && item.scope === scope);
  const initialProject = projects[0] || null;
  const [project, setProject] = useState<StudioProject | null>(initialProject);
  const [name, setName] = useState(initialProject?.name || "未命名画布");
  const [nodes, setNodes] = useState<CanvasNode[]>(() => normalizeCanvasNodes(initialProject?.document?.nodes));
  const [edges, setEdges] = useState<CanvasEdge[]>(() => normalizeCanvasEdges(initialProject?.document?.edges, normalizeCanvasNodes(initialProject?.document?.nodes)));
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [edgeFrom, setEdgeFrom] = useState("");
  const [history, setHistory] = useState<CanvasEdit[]>([]);
  const [future, setFuture] = useState<CanvasEdit[]>([]);
  const [busy, setBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 });
  const [panMode, setPanMode] = useState(false);
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [generationProvider, setGenerationProvider] = useState("");
  const [generationMode, setGenerationMode] = useState<"draw" | "edit">("draw");
  const [generationSize, setGenerationSize] = useState("");
  const [generationResolution, setGenerationResolution] = useState("");
  const [generationBusy, setGenerationBusy] = useState(false);
  const generationRequest = useRef<Record<string, unknown> | null>(null);
  const dirtyRef = useRef(false);
  const projectRevisionRef = useRef(project?.revision || 0);
  const generationProviders = snapshot.capabilities.filter((item) =>
    item.operations[generationMode === "edit" ? "image_edit" : "image_generate"] === "supported",
  );
  const [projectJobs, setProjectJobs] = useState<StudioJob[]>([]);
  const boardRef = useRef<HTMLDivElement>(null);
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  const edgesRef = useRef(edges);
  edgesRef.current = edges;
  const panRef = useRef<{ x: number; y: number; before: typeof view } | null>(null);
  const dragRef = useRef<{ id: string; startX: number; startY: number; before: CanvasEdit; moved: boolean } | null>(null);

  function openProject(next: StudioProject | null) {
    importVersion.current += 1;
    importing.current = false;
    setImportBusy(false);
    setStatus("");
    generationRequest.current = null;
    setGenerationBusy(false);
    setGenerationPrompt("");
    setProjectJobs([]);
    setEdgeFrom("");
    dirtyRef.current = false;
    const viewport = next?.document.viewport as Partial<typeof view> | undefined;
    setView({
      x: Number.isFinite(viewport?.x) ? Number(viewport?.x) : 0,
      y: Number.isFinite(viewport?.y) ? Number(viewport?.y) : 0,
      zoom: Number.isFinite(viewport?.zoom) ? Math.max(0.1, Math.min(4, Number(viewport?.zoom))) : 1,
    });
    panRef.current = null;
    setProject(next);
    projectRevisionRef.current = next?.revision || 0;
    setName(next?.name || "未命名画布");
    const restoredNodes = normalizeCanvasNodes(next?.document?.nodes);
    setNodes(restoredNodes);
    setEdges(normalizeCanvasEdges(next?.document?.edges, restoredNodes));
    setSelectedNodeId("");
    setHistory([]);
    setFuture([]);
    dragRef.current = null;
  }

  useEffect(() => {
    openProject(null);
    setImportedAssets([]);
    setBusy(false);
  }, [scope]);
  useEffect(() => () => { importVersion.current += 1; }, []);
  useEffect(() => {
    if (!project) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [jobs, latest] = await Promise.all([
          loadProjectJobs(project!.id, scope),
          loadStudioProject(project!.id, scope),
        ]);
        if (active) {
          setProjectJobs(jobs);
          if (!dirtyRef.current && !generationBusy && latest.revision !== projectRevisionRef.current) {
            projectRevisionRef.current = latest.revision;
            setProject(latest);
            const restored = normalizeCanvasNodes(latest.document.nodes);
            setNodes(restored);
            setEdges(normalizeCanvasEdges(latest.document.edges, restored));
            setHistory([]);
            setFuture([]);
          }
        }
      } catch (error) {
        if (active) setStatus(`读取画布任务失败：${String(error)}`);
      } finally {
        if (active) timer = setTimeout(poll, 5000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [project?.id, scope, generationBusy]);

  function commit(next: CanvasNode[]) {
    if (generationBusy) return;
    dirtyRef.current = true;
    setHistory((current) => [...current, { nodes: cloneCanvasNodes(nodes), edges: [...edges] }].slice(-50));
    setFuture([]);
    const normalized = normalizeCanvasNodes(next);
    setNodes(normalized);
    setEdges((current) => normalizeCanvasEdges(current, normalized));
  }

  function commitEdges(next: CanvasEdge[]) {
    if (generationBusy) return;
    dirtyRef.current = true;
    setHistory((current) => [...current, { nodes: cloneCanvasNodes(nodes), edges: [...edges] }].slice(-50));
    setFuture([]);
    setEdges(normalizeCanvasEdges(next, nodes));
  }

  async function addAsset(asset: StudioAsset) {
    if (busy || generationBusy || importing.current || asset.scope !== scope || asset.media_type !== "image") return;
    const version = importVersion.current;
    importing.current = true;
    setImportBusy(true);
    try {
      const managed = asset.source === "history" && asset.history_id
        ? await preserveHistoryAsset(asset.history_id, scope) : asset;
      if (version !== importVersion.current) return;
      setImportedAssets((current) => [...current.filter((item) => item.asset_id !== managed.asset_id), managed]);
      const current = nodesRef.current;
      if (current.length >= 500) throw new Error("画布最多支持 500 个节点");
      if (current.some((node) => node.asset_id === managed.asset_id)) return;
      const node: CanvasNode = { id: globalThis.crypto.randomUUID(), type: "asset", asset_id: managed.asset_id, x: (80 - view.x) / view.zoom, y: (80 - view.y) / view.zoom, scale: 1, rotation: 0 };
      setHistory((previous) => [...previous, { nodes: cloneCanvasNodes(current), edges: [...edgesRef.current] }].slice(-50));
      setNodes([...current, node]);
      dirtyRef.current = true;
      setSelectedNodeId(node.id);
      setFuture([]);
      if (asset.source === "history") onRefresh();
    } catch (reason) {
      if (version === importVersion.current) window.alert(reason instanceof Error ? reason.message : "导入图片失败");
    } finally {
      if (version === importVersion.current) {
        importing.current = false;
        setImportBusy(false);
      }
    }
  }

  function moveNode(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= nodes.length) return;
    const next = [...nodes];
    [next[index], next[target]] = [next[target], next[index]];
    commit(next);
  }

  function updateSelected(update: Partial<CanvasNode>) {
    if (!selectedNodeId) return;
    commit(nodes.map((node) => node.id === selectedNodeId ? { ...node, ...update } : node));
  }

  function removeNode(nodeId: string) {
    if (!nodeId) return;
    commit(nodes.filter((node) => node.id !== nodeId));
    if (selectedNodeId === nodeId) setSelectedNodeId("");
  }

  function removeSelected() {
    removeNode(selectedNodeId);
  }

  function undo() {
    if (!history.length || generationBusy) return;
    dirtyRef.current = true;
    const previous = history[history.length - 1];
    setHistory(history.slice(0, -1));
    setFuture([{ nodes: cloneCanvasNodes(nodes), edges: [...edges] }, ...future].slice(0, 50));
    setNodes(cloneCanvasNodes(previous.nodes));
    setEdges([...previous.edges]);
    setSelectedNodeId("");
  }

  function redo() {
    if (!future.length || generationBusy) return;
    dirtyRef.current = true;
    const next = future[0];
    setFuture(future.slice(1));
    setHistory([...history, { nodes: cloneCanvasNodes(nodes), edges: [...edges] }].slice(-50));
    setNodes(cloneCanvasNodes(next.nodes));
    setEdges([...next.edges]);
    setSelectedNodeId("");
  }

  function beginDrag(event: ReactPointerEvent<HTMLElement>, node: CanvasNode) {
    if (importing.current || generationBusy) { event.stopPropagation(); return; }
    if (panMode) return;
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedNodeId(node.id);
    boardRef.current?.focus();
    dragRef.current = { id: node.id, startX: event.clientX, startY: event.clientY, before: { nodes: cloneCanvasNodes(nodes), edges: [...edges] }, moved: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function moveDrag(event: ReactPointerEvent<HTMLElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = (event.clientX - drag.startX) / view.zoom;
    const dy = (event.clientY - drag.startY) / view.zoom;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) drag.moved = true;
    if (!drag.moved) return;
    const origin = drag.before.nodes.find((item) => item.id === drag.id);
    if (!origin) return;
    setNodes((current) => current.map((node) => node.id === drag.id ? { ...node, x: origin.x + dx, y: origin.y + dy } : node));
  }

  function endDrag() {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.moved) {
      dirtyRef.current = true;
      setHistory((current) => [...current, drag.before].slice(-50));
      setFuture([]);
    }
    dragRef.current = null;
  }

  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const selectedProvider = generationProviders.find((item) => item.provider_id === generationProvider);
  const jobForNode = (node: CanvasNode) => projectJobs.find((job) =>
    job.id === node.job_id || job.request?.canvas_node_id === node.id,
  );

  function addGenerationDraft() {
    if (generationBusy || busy || importing.current || nodes.length >= 500) return;
    const node: CanvasNode = {
      id: globalThis.crypto.randomUUID(), type: "generation", asset_id: "",
      x: (100 - view.x) / view.zoom, y: (100 - view.y) / view.zoom,
      scale: 1, rotation: 0, prompt: generationPrompt.trim(),
      provider_id: generationProvider, size: generationSize, resolution: generationResolution,
      mode: generationMode, reference_asset_ids: [],
    };
    commit([...nodes, node]);
    setSelectedNodeId(node.id);
  }

  function connectSelected() {
    if (!selectedNodeId || !edgeFrom || edgeFrom === selectedNodeId) return;
    if (edges.some((edge) => edge.from === edgeFrom && edge.to === selectedNodeId)) return;
    commitEdges([...edges, { id: globalThis.crypto.randomUUID(), from: edgeFrom, to: selectedNodeId }]);
    setEdgeFrom("");
  }

  useEffect(() => {
    if (!selectedNodeId) return;
    const selected = nodesRef.current.find((item) => item.id === selectedNodeId);
    if (selected?.type !== "generation") return;
    setGenerationPrompt(selected.prompt || "");
    setGenerationProvider(selected.provider_id || "");
    setGenerationMode(selected.mode || "draw");
    setGenerationSize(selected.size || "");
    setGenerationResolution(selected.resolution || "");
  }, [selectedNodeId]);

  useEffect(() => {
    if (!generationProvider) return;
    const choice = generationProviders.find((item) => item.provider_id === generationProvider);
    if (!choice || selectedNode?.submission_key) return;
    setGenerationSize(choice.parameters.sizes?.default || "");
    setGenerationResolution(choice.parameters.resolutions?.default || "");
  }, [generationProvider]);

  function zoomView(factor: number) {
    dirtyRef.current = true;
    const width = boardRef.current?.clientWidth || 600;
    const height = boardRef.current?.clientHeight || 560;
    setView((current) => {
      const zoom = Math.max(0.1, Math.min(4, current.zoom * factor));
      return { zoom, x: width / 2 - (width / 2 - current.x) * zoom / current.zoom, y: height / 2 - (height / 2 - current.y) * zoom / current.zoom };
    });
  }

  function fitView() {
    dirtyRef.current = true;
    if (!nodes.length) { setView({ x: 0, y: 0, zoom: 1 }); return; }
    // Radius covers rotated nodes as well as their controls.
    const bounds = nodes.map((node) => ({ ...node, radius: 270 * node.scale }));
    const left = Math.min(...bounds.map((node) => node.x - node.radius));
    const top = Math.min(...bounds.map((node) => node.y - node.radius));
    const right = Math.max(...bounds.map((node) => node.x + node.radius));
    const bottom = Math.max(...bounds.map((node) => node.y + node.radius));
    const width = boardRef.current?.clientWidth || 600;
    const height = boardRef.current?.clientHeight || 560;
    const zoom = Math.max(0.1, Math.min(2, (width - 40) / (right - left), (height - 40) / (bottom - top)));
    setView({ zoom, x: (width - (left + right) * zoom) / 2, y: (height - (top + bottom) * zoom) / 2 });
  }

  async function persistCanvas(nextNodes: CanvasNode[], nextEdges: CanvasEdge[], asCopy = false) {
    const version = importVersion.current;
    const next = await saveStudioProject({
      id: asCopy ? undefined : project?.id, revision: asCopy ? undefined : project?.revision,
      scope, name: asCopy ? `${name} 副本` : name, kind: "canvas",
      document: { ...project?.document, version: 4, nodes: nextNodes, edges: nextEdges, viewport: view },
    });
    if (version !== importVersion.current) return next;
    projectRevisionRef.current = next.revision;
    setProject(next);
    setName(next.name);
    dirtyRef.current = false;
    onRefresh();
    return next;
  }

  async function save(asCopy = false) {
    if (!scope || busy || generationBusy || importing.current) return;
    const version = importVersion.current;
    setBusy(true);
    try {
      await persistCanvas(nodes, edges, asCopy);
      if (version !== importVersion.current) return;
      setStatus("项目已保存");
    } catch (reason) {
      if (version === importVersion.current) setStatus(reason instanceof Error ? reason.message : "画布保存失败");
    } finally {
      if (version === importVersion.current) setBusy(false);
    }
  }

  async function generateOnCanvas() {
    if (generationBusy || busy || importing.current || !scope || !generationPrompt.trim() || !generationProvider) return;
    const version = importVersion.current;
    const existingNode = selectedNode?.type === "generation" ? selectedNode : null;
    if (existingNode?.job_id || (existingNode && jobForNode(existingNode))) {
      setStatus("这个节点已有任务；请新建生成节点以发起另一张图片");
      return;
    }
    const key = existingNode?.submission_key || globalThis.crypto.randomUUID();
    const references = existingNode?.submission_key
      ? existingNode.reference_asset_ids || []
      : edges.filter((edge) => edge.to === existingNode?.id)
          .map((edge) => nodes.find((item) => item.id === edge.from)?.asset_id || "")
          .filter(Boolean);
    if (generationMode === "edit" && (!existingNode || !references.length)) {
      setStatus("改图需要选中生成节点，并将图片素材节点连到它");
      return;
    }
    if (references.length > 9) {
      setStatus("改图参考素材最多 9 张");
      return;
    }
    if (!existingNode?.submission_key &&
        !window.confirm(`通过 ${generationProvider} 生成 1 张图片，费用以服务商账单为准。继续？`)) return;
    const node: CanvasNode = existingNode ? {
      ...existingNode, submission_key: key,
      prompt: generationPrompt.trim(), provider_id: generationProvider,
      size: generationSize, resolution: generationResolution,
      mode: generationMode, reference_asset_ids: generationMode === "edit" ? references : [],
    } : {
      id: globalThis.crypto.randomUUID(), type: "generation", asset_id: "",
      x: (100 - view.x) / view.zoom, y: (100 - view.y) / view.zoom,
      scale: 1, rotation: 0, submission_key: key,
      prompt: generationPrompt.trim(), provider_id: generationProvider,
      size: generationSize, resolution: generationResolution,
      mode: generationMode, reference_asset_ids: [],
    };
    if (existingNode?.submission_key &&
        (node.prompt !== existingNode.prompt || node.provider_id !== existingNode.provider_id ||
         node.size !== existingNode.size || node.resolution !== existingNode.resolution ||
         node.mode !== (existingNode.mode || "draw"))) {
      setStatus("已准备提交的节点参数不能修改；请新建生成节点");
      return;
    }
    const preparedNodes = existingNode
      ? nodes.map((item) => item.id === node.id ? node : item)
      : [...nodes, node];
    if (preparedNodes.length > 500) {
      setStatus("画布最多支持 500 个节点");
      return;
    }
    setGenerationBusy(true);
    try {
      const prepared = await persistCanvas(preparedNodes, edges);
      if (version !== importVersion.current) return;
      setNodes(preparedNodes);
      setSelectedNodeId(node.id);
      setHistory([]);
      setFuture([]);
      const payload = {
        idempotency_key: key, scope, project_id: prepared.id, canvas_node_id: node.id,
        kind: "image", mode: node.mode, prompt: node.prompt, provider_id: node.provider_id,
        size: node.size || "", resolution: node.resolution || "",
        reference_asset_ids: node.reference_asset_ids || [],
      };
      generationRequest.current = payload;
      await createStudioJob(payload);
      if (version !== importVersion.current) return;
      generationRequest.current = null;
      const latest = await loadStudioProject(prepared.id, scope);
      if (version !== importVersion.current) return;
      projectRevisionRef.current = latest.revision;
      setProject(latest);
      const restored = normalizeCanvasNodes(latest.document.nodes);
      setNodes(restored);
      setEdges(normalizeCanvasEdges(latest.document.edges, restored));
      setHistory([]);
      setFuture([]);
      dirtyRef.current = false;
      setStatus("生成任务已提交；任务状态将从项目记录更新");
      onRefresh();
    } catch (reason) {
      if (version === importVersion.current) setStatus(`${String(reason)}；确认任务中心状态后，可用相同节点与编号手动重试`);
    } finally {
      if (version === importVersion.current) setGenerationBusy(false);
    }
  }

  return (
    <section className="workspace">
      <div className="workspace-heading"><div><span className="section-kicker">CANVAS</span><h1>无限画布</h1></div><div className="composer-actions"><input className="project-name" value={name} onChange={(event) => { dirtyRef.current = true; setName(event.target.value); }} aria-label="项目名称" /><button type="button" className="primary-action" disabled={busy || generationBusy || !scope} onClick={() => void save()}>{busy ? "保存中" : "保存项目"}</button></div></div>
      <div className="canvas-toolbar" role="toolbar" aria-label="画布编辑工具">
        <button type="button" className="icon-button" aria-pressed={!panMode} title="选择节点" onClick={() => setPanMode(false)}><MousePointer2 size={17} /><span className="sr-only">选择节点</span></button>
        <button type="button" className="icon-button" aria-pressed={panMode} title="平移画布" onClick={() => setPanMode(true)}><Hand size={17} /><span className="sr-only">平移画布</span></button>
        <button type="button" className="icon-button" title="缩小视图" onClick={() => zoomView(1 / 1.2)}><ZoomOut size={17} /><span className="sr-only">缩小视图</span></button>
        <span>{Math.round(view.zoom * 100)}%</span>
        <button type="button" className="icon-button" title="放大视图" onClick={() => zoomView(1.2)}><ZoomIn size={17} /><span className="sr-only">放大视图</span></button>
        <button type="button" className="icon-button" title="显示全部节点" onClick={fitView}><Maximize size={17} /><span className="sr-only">显示全部节点</span></button>
        <button type="button" className="secondary-action" disabled={busy || generationBusy || importBusy || !scope} onClick={() => void save(true)}>另存副本</button>
        <button type="button" className="icon-button" disabled={busy || !project} title="导出已保存项目 ZIP" onClick={() => {
          if (project) void exportMediaProject(project.id, scope).catch((error) => setStatus(String(error)));
        }}><Download size={17} /><span className="sr-only">导出已保存项目 ZIP</span></button>
        <button type="button" className="icon-button" disabled={!selectedNode?.asset_id} title="继续改图" onClick={() => selectedNode?.asset_id && openAssetInCreate(selectedNode.asset_id, "edit")}><Pencil size={17} /><span className="sr-only">继续改图</span></button>
        <button type="button" className="icon-button" disabled={!selectedNode?.asset_id} title="生成视频" onClick={() => selectedNode?.asset_id && openAssetInCreate(selectedNode.asset_id, "video")}><Video size={17} /><span className="sr-only">生成视频</span></button>
        <select aria-label="画布项目" value={project?.id || ""} disabled={busy || generationBusy} onChange={(event) => {
          if (!window.confirm("切换项目？未保存的修改将丢失。")) return;
          openProject(projects.find((item) => item.id === event.target.value) || null);
        }}>
          <option value="">新建画布</option>
          {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <button type="button" className="icon-button" onClick={undo} disabled={!history.length || generationBusy} title="撤销"><Undo2 size={17} /><span className="sr-only">撤销</span></button>
        <button type="button" className="icon-button" onClick={redo} disabled={!future.length || generationBusy} title="重做"><Redo2 size={17} /><span className="sr-only">重做</span></button>
        <span className="toolbar-divider" />
        <button type="button" className="icon-button" onClick={() => updateSelected({ scale: Math.max(0.25, (selectedNode?.scale || 1) - 0.1) })} disabled={!selectedNode} title="缩小节点"><ZoomOut size={17} /><span className="sr-only">缩小节点</span></button>
        <button type="button" className="icon-button" onClick={() => updateSelected({ scale: Math.min(3, (selectedNode?.scale || 1) + 0.1) })} disabled={!selectedNode} title="放大节点"><ZoomIn size={17} /><span className="sr-only">放大节点</span></button>
        <button type="button" className="icon-button" onClick={() => updateSelected({ rotation: (selectedNode?.rotation || 0) - 15 })} disabled={!selectedNode} title="向左旋转"><RotateCcw size={17} /><span className="sr-only">向左旋转</span></button>
        <button type="button" className="icon-button" onClick={() => updateSelected({ rotation: (selectedNode?.rotation || 0) + 15 })} disabled={!selectedNode} title="向右旋转"><RotateCw size={17} /><span className="sr-only">向右旋转</span></button>
        <span className="toolbar-divider" />
        <button type="button" className="icon-button danger" onClick={removeSelected} disabled={!selectedNode} title="删除节点"><Trash2 size={17} /><span className="sr-only">删除节点</span></button>
        <span className="canvas-selection">{selectedNode ? `已选中 · ${Math.round(selectedNode.scale * 100)}% · ${Math.round(selectedNode.rotation)}°` : "未选择节点"}</span>
      </div>
      {status && <p role="status">{status}</p>}
      {importBusy && <p role="status">正在导入素材</p>}
      <div className="video-options">
        <label className="stack-field"><span>模式</span><select value={generationMode} disabled={generationBusy || !!selectedNode?.submission_key} onChange={(event) => {
          setGenerationMode(event.target.value as "draw" | "edit");
          setGenerationProvider("");
        }}><option value="draw">文生图</option><option value="edit">参考图改图</option></select></label>
        <label className="stack-field"><span>画布生成服务商</span><select value={generationProvider} disabled={generationBusy || !!generationRequest.current || !!selectedNode?.submission_key} onChange={(event) => setGenerationProvider(event.target.value)}>
          <option value="">选择服务商</option>{generationProviders.map((item) => <option key={item.provider_id} value={item.provider_id}>{item.label || item.provider_id}</option>)}
        </select></label>
        <label className="stack-field"><span>生成提示词</span><textarea rows={2} maxLength={8000} value={generationPrompt} disabled={generationBusy || !!generationRequest.current || !!selectedNode?.submission_key} onChange={(event) => setGenerationPrompt(event.target.value)} /></label>
        {!!selectedProvider?.parameters.sizes?.values.length && <label className="stack-field"><span>尺寸</span><select value={generationSize} disabled={generationBusy || !!selectedNode?.submission_key} onChange={(event) => setGenerationSize(event.target.value)}>{selectedProvider.parameters.sizes.values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
        {!!selectedProvider?.parameters.resolutions?.values.length && <label className="stack-field"><span>分辨率</span><select value={generationResolution} disabled={generationBusy || !!selectedNode?.submission_key} onChange={(event) => setGenerationResolution(event.target.value)}>{selectedProvider.parameters.resolutions.values.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
        <button type="button" className="icon-button" disabled={busy || generationBusy || nodes.length >= 500} title="添加生成节点" onClick={addGenerationDraft}><ImagePlus size={17} /><span className="sr-only">添加生成节点</span></button>
        <button type="button" className="primary-action" disabled={busy || generationBusy || !generationProvider || !generationPrompt.trim() || !!selectedNode?.job_id} onClick={() => void generateOnCanvas()}>{generationBusy ? "提交中" : selectedNode?.submission_key ? "核对并重试" : generationMode === "edit" ? "生成改图" : "生成图片"}</button>
      </div>
      <div className="canvas-connections">
        <label className="stack-field"><span>连线起点</span><select value={edgeFrom} disabled={generationBusy} onChange={(event) => setEdgeFrom(event.target.value)}><option value="">选择节点</option>{nodes.map((node, index) => <option key={node.id} value={node.id}>节点 {index + 1} · {node.type === "generation" ? "生成" : "素材"}</option>)}</select></label>
        <button type="button" className="secondary-action" disabled={generationBusy || !edgeFrom || !selectedNode || edgeFrom === selectedNodeId || edges.some((edge) => edge.from === edgeFrom && edge.to === selectedNodeId)} onClick={connectSelected}>连接到选中节点</button>
        {edges.map((edge) => <div className="canvas-edge-row" key={edge.id}><span>{nodes.findIndex((node) => node.id === edge.from) + 1} → {nodes.findIndex((node) => node.id === edge.to) + 1}</span><button type="button" className="icon-button danger" disabled={generationBusy} title="删除连线" onClick={() => commitEdges(edges.filter((item) => item.id !== edge.id))}><X size={15} /><span className="sr-only">删除连线</span></button></div>)}
      </div>
      {projectJobs.filter((job) => !nodes.some((node) => job.request?.canvas_node_id === node.id)).map((job) => <div className="composer-actions" key={job.id}>
        <span>{job.state} · {String(job.request?.provider_id || "")} · {job.prompt}</span>
        {job.state === "completed" && typeof job.result?.asset_id === "string" && <button type="button" className="secondary-action" disabled={importBusy} onClick={() => {
          const id = String(job.result?.asset_id);
          const asset = snapshot.assets.find((item) => item.asset_id === id);
          void addAsset(asset || { asset_id: id, scope, media_type: "image", filename: job.prompt, created_at: job.created_at });
        }}>加入画布</button>}
      </div>)}
      <div className="canvas-layout">
        <div ref={boardRef} className="canvas-board" aria-label="画布" tabIndex={0}
          onKeyDown={(event) => {
            if (event.target !== event.currentTarget) return;
            const step = event.shiftKey ? 50 : 10;
            const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
            if (delta && !generationBusy) {
              event.preventDefault();
              if (selectedNode && !panMode) updateSelected({ x: selectedNode.x + delta[0], y: selectedNode.y + delta[1] });
              else { dirtyRef.current = true; setView((current) => ({ ...current, x: current.x + delta[0], y: current.y + delta[1] })); }
            }
          }}
          onPointerDown={(event) => {
            if (generationBusy || (event.button !== 0 && event.button !== 1)) return;
            event.preventDefault();
            event.currentTarget.focus();
            setSelectedNodeId("");
            panRef.current = { x: event.clientX, y: event.clientY, before: view };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            const pan = panRef.current;
            if (pan) { dirtyRef.current = true; setView({ ...pan.before, x: pan.before.x + event.clientX - pan.x, y: pan.before.y + event.clientY - pan.y }); }
          }}
          onPointerUp={() => { panRef.current = null; }} onPointerCancel={() => { panRef.current = null; }}>
          {nodes.length === 0 && <div className="empty-state">从右侧素材库加入图片，生成结果会以 asset_id 进入画布。</div>}
          <div className="canvas-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` }}>
          <svg className="canvas-edge-layer" aria-hidden="true">
            {edges.map((edge) => {
              const from = nodes.find((node) => node.id === edge.from);
              const to = nodes.find((node) => node.id === edge.to);
              return from && to ? <line key={edge.id} x1={from.x + 95 * from.scale} y1={from.y + 80 * from.scale} x2={to.x + 95 * to.scale} y2={to.y + 80 * to.scale} /> : null;
            })}
          </svg>
          {nodes.map((node, index) => {
            const job = node.type === "generation" ? jobForNode(node) : undefined;
            const assetId = node.asset_id || (typeof job?.result?.asset_id === "string" ? job.result.asset_id : "");
            const asset = importedAssets.find((item) => item.asset_id === assetId) || snapshot.assets.find((item) => item.asset_id === assetId);
            const previewAsset = assetId ? asset || { asset_id: assetId, scope, media_type: "image", filename: assetId, created_at: 0 } : null;
            return <article className={selectedNodeId === node.id ? "canvas-node selected" : "canvas-node"} key={node.id} style={{ left: node.x, top: node.y, transform: `rotate(${node.rotation}deg) scale(${node.scale})`, zIndex: index + 1 }} onPointerDown={(event) => beginDrag(event, node)} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag}>
              <div className="history-media">{previewAsset ? <AssetPreview item={previewAsset} history={snapshot.history} /> : <div className="media-placeholder"><ImageIcon size={20} aria-hidden="true" /></div>}</div>
              {node.type === "generation" && <div className="canvas-node-detail">
                <strong>{job?.state || (node.submission_key ? "待核对" : "草稿")}</strong>
                <span>{node.mode === "edit" ? "改图" : "文生图"} · {node.provider_id || "未选择服务商"} · {[node.size, node.resolution].filter(Boolean).join(" · ") || "默认参数"} · {node.reference_asset_ids?.length || 0} 张参考</span>
                <small title={node.prompt}>{node.prompt || "未填写提示词"}</small>
              </div>}
              <div className="canvas-node-actions" onPointerDown={(event) => event.stopPropagation()}><button type="button" className="icon-button" onClick={() => moveNode(index, 1)} disabled={index === nodes.length - 1} title="上移图层"><ArrowUp size={15} /><span className="sr-only">上移图层</span></button><button type="button" className="icon-button" onClick={() => moveNode(index, -1)} disabled={index === 0} title="下移图层"><ArrowDown size={15} /><span className="sr-only">下移图层</span></button><button type="button" className="icon-button danger" onClick={() => removeNode(node.id)} title="移除节点"><Trash2 size={15} /><span className="sr-only">移除节点</span></button></div>
            </article>;
          })}
          </div>
        </div>
        <aside className="canvas-assets"><h2>素材</h2>{snapshot.assets.filter((item) => item.media_type === "image").map((asset) => <button type="button" className="asset-picker-row" key={asset.asset_id} onClick={() => addAsset(asset)}><AssetPreview item={asset} history={snapshot.history} /><span>{asset.filename}</span></button>)}{snapshot.assets.length === 0 && <div className="empty-state">暂无图片素材</div>}</aside>
      </div>
    </section>
  );
}

function GifView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const [importedAssets, setImportedAssets] = useState<StudioAsset[]>([]);
  const importing = useRef(false);
  const images = [...snapshot.assets, ...importedAssets.filter((asset) => !snapshot.assets.some((item) => item.asset_id === asset.asset_id))].filter((item) => item.media_type === "image" && item.scope === scope);
  const projects = snapshot.projects.filter((item) => item.kind === "gif" && item.scope === scope);
  const initialProject = snapshot.projects.find((item) => item.kind === "gif" && item.scope === scope) || null;
  const initialFrames = initialProject?.document?.frames || initialProject?.document?.asset_ids;
  const [project, setProject] = useState<StudioProject | null>(initialProject);
  const [selected, setSelected] = useState<string[]>(Array.isArray(initialFrames) ? initialFrames.map(String) : []);
  const [name, setName] = useState(initialProject?.name || "未命名动画");
  const [duration, setDuration] = useState(String(initialProject?.document?.duration_ms || 500));
  const [width, setWidth] = useState(String(initialProject?.document?.width || 512));
  const [height, setHeight] = useState(String(initialProject?.document?.height || 512));
  const [frameDurations, setFrameDurations] = useState<number[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [loop, setLoop] = useState(String(initialProject?.document?.loop ?? 0));
  const operationVersion = useRef(0);
  const [currentFrame, setCurrentFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [framePrompt, setFramePrompt] = useState("");
  const [frameProvider, setFrameProvider] = useState("");
  const [frameJobs, setFrameJobs] = useState<StudioJob[]>([]);
  const [encodingProgress, setEncodingProgress] = useState("");
  const [gifStatus, setGifStatus] = useState("");
  const [outputAssetId, setOutputAssetId] = useState(String(initialProject?.document?.output_asset_id || ""));
  const workerRef = useRef<Worker | null>(null);
  const abortEncoding = useRef<((reason: Error) => void) | null>(null);
  const dirtyRef = useRef(false);
  const revisionRef = useRef(initialProject?.revision || 0);
  const frameProviders = snapshot.capabilities.filter((item) => item.operations.image_generate === "supported");

  function markGifEdited() {
    dirtyRef.current = true;
    setOutputAssetId("");
    setGifStatus("");
  }

  function loadProject(next: StudioProject | null, invalidate = true) {
    if (invalidate) operationVersion.current += 1;
    importing.current = false;
    setImportBusy(false);
    setProject(next);
    revisionRef.current = next?.revision || 0;
    dirtyRef.current = false;
    const frames = next?.document?.frames || next?.document?.asset_ids;
    setSelected(Array.isArray(frames) ? frames.map(String) : []);
    setName(next?.name || "未命名动画");
    setDuration(String(next?.document?.duration_ms || 500));
    setWidth(String(next?.document?.width || 512));
    setHeight(String(next?.document?.height || 512));
    const savedDurations = next?.document?.frame_durations_ms;
    const fallback = Math.max(20, Math.min(10000, Number(next?.document?.duration_ms) || 500));
    setFrameDurations(Array.isArray(frames) ? frames.map((_, index) => Array.isArray(savedDurations) ? Math.max(20, Math.min(10000, Number(savedDurations[index]) || fallback)) : fallback) : []);
    setLoop(String(next?.document?.loop ?? 0));
    setPlaying(false);
    setCurrentFrame(0);
    setOutputAssetId(String(next?.document?.output_asset_id || ""));
    setFrameJobs([]);
    setGifStatus("");
  }

  useEffect(() => {
    operationVersion.current += 1;
    setBusy(false);
    loadProject(null);
    setImportedAssets([]);
  }, [scope]);
  useEffect(() => () => { operationVersion.current += 1; }, []);
  useEffect(() => {
    if (!project) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [jobs, latest] = await Promise.all([
          loadProjectJobs(project!.id, scope), loadStudioProject(project!.id, scope),
        ]);
        if (active) {
          setFrameJobs(jobs.filter((job) => !!job.request?.gif_frame_key));
          if (!dirtyRef.current && !busy && latest.revision !== revisionRef.current) {
            loadProject(latest);
            setFrameJobs(jobs.filter((job) => !!job.request?.gif_frame_key));
          }
        }
      } catch (reason) {
        if (active) setGifStatus(reason instanceof Error ? reason.message : "读取 GIF 项目失败");
      } finally {
        if (active) timer = setTimeout(poll, 5000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [project?.id, scope, busy]);
  useEffect(() => () => {
    abortEncoding.current?.(new Error("GIF 编码已取消"));
    workerRef.current?.terminate();
    workerRef.current = null;
  }, [scope]);

  useEffect(() => {
    setCurrentFrame((value) => selected.length ? Math.min(value, selected.length - 1) : 0);
  }, [selected.length]);

  useEffect(() => {
    if (!playing || selected.length < 2) return;
    const timer = window.setTimeout(() => setCurrentFrame((value) => (value + 1) % selected.length), frameDurations[currentFrame] || 500);
    return () => window.clearTimeout(timer);
  }, [playing, selected.length, frameDurations, currentFrame]);

  async function persistGif(frameEntries?: Array<Record<string, unknown>>, asCopy = false) {
    const durationValue = Math.round(Math.max(20, Math.min(10000, Number(duration) || 500)));
    const loopValue = Math.round(Math.max(0, Math.min(999, Number(loop) || 0)));
    const outputWidth = Number(width);
    const outputHeight = Number(height);
    if (!Number.isInteger(outputWidth) || !Number.isInteger(outputHeight)
      || outputWidth < 16 || outputHeight < 16 || outputWidth > 1024 || outputHeight > 1024) {
      throw new Error("GIF 输出宽高必须在 16–1024 像素之间");
    }
    const entries = asCopy ? [] : frameEntries || (project?.document.frame_jobs as Array<Record<string, unknown>> | undefined) || [];
    const saved = await saveStudioProject({
      id: asCopy ? undefined : project?.id, revision: asCopy ? undefined : project?.revision,
      scope, name: asCopy ? `${name.trim() || "未命名动画"} 副本` : name.trim() || "未命名动画",
      kind: "gif", document: {
        ...project?.document, version: 4, frames: selected, output_asset_id: asCopy ? "" : outputAssetId,
        duration_ms: durationValue, frame_durations_ms: selected.map((_, index) => frameDurations[index] || durationValue),
        loop: loopValue, width: outputWidth, height: outputHeight, frame_jobs: entries,
      },
    });
    revisionRef.current = saved.revision;
    setProject(saved);
    setName(saved.name);
    dirtyRef.current = false;
    onRefresh();
    return saved;
  }

  async function create(exportGif = false, asCopy = false) {
    if (busy || importing.current || !scope || (!selected.length && !Array.isArray(project?.document.frame_jobs))) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setGifStatus("");
    try {
      const saved = await persistGif(undefined, asCopy);
      if (version !== operationVersion.current) return;
      if (exportGif) {
        const asset = await createStudioGif({
          scope, asset_ids: selected,
          duration_ms: Number(saved.document.duration_ms),
          frame_durations_ms: saved.document.frame_durations_ms,
          loop: Number(saved.document.loop), width: Number(saved.document.width), height: Number(saved.document.height),
          filename: `${name.trim() || "studio-animation"}.gif`,
        });
        if (version !== operationVersion.current) return;
        setOutputAssetId(asset.asset_id);
        const updated = await saveStudioProject({
          id: saved.id, revision: saved.revision, scope, name: saved.name, kind: "gif",
          document: { ...saved.document, output_asset_id: asset.asset_id },
        });
        if (version !== operationVersion.current) return;
        setProject(updated);
        revisionRef.current = updated.revision;
        onRefresh();
      }
      setGifStatus(exportGif ? "GIF 已存入素材库" : "GIF 项目已保存");
    } catch (reason) {
      if (version === operationVersion.current) setGifStatus(reason instanceof Error ? reason.message : "GIF 保存或导出失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }

  async function encodeInWorker() {
    if (busy || importing.current || !scope || !selected.length || selected.length > 60) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setGifStatus("");
    setEncodingProgress("准备帧素材");
    try {
      const saved = await persistGif();
      if (version !== operationVersion.current) return;
      const assets = selected.map((id) => images.find((item) => item.asset_id === id));
      if (assets.some((item) => !item)) throw new Error("部分图片素材已不可用");
      const total = assets.reduce((sum, item) => sum + Number(item?.byte_size || 0), 0);
      if (total > 100 * 1024 * 1024 || assets.some((item) => Number(item?.byte_size || 0) > 20 * 1024 * 1024)) {
        throw new Error("GIF 输入总量不能超过 100MB，单张不能超过 20MB");
      }
      const cache = new Map<string, string>();
      for (const id of new Set(selected)) {
        cache.set(id, await loadAssetPreview(id, scope));
        if (version !== operationVersion.current) return;
      }
      if ([...cache.values()].reduce((sum, uri) => sum + Math.ceil(uri.length * 3 / 4), 0) > 100 * 1024 * 1024) {
        throw new Error("GIF 输入总量不能超过 100MB");
      }
      const worker = new Worker(new URL("../features/gif/encode.worker.ts", import.meta.url), { type: "module" });
      workerRef.current = worker;
      const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
        abortEncoding.current = reject;
        worker.onmessage = (event: MessageEvent<{ type: string; current?: number; total?: number; buffer?: ArrayBuffer; message?: string }>) => {
          if (event.data.type === "progress") setEncodingProgress(`${event.data.current}/${event.data.total}`);
          if (event.data.type === "complete" && event.data.buffer) resolve(event.data.buffer);
          if (event.data.type === "error") reject(new Error(event.data.message || "GIF 编码失败"));
        };
        worker.onerror = () => reject(new Error("GIF Worker 已中断"));
        worker.postMessage({
          frames: selected.map((id, index) => ({ dataUri: cache.get(id), durationMs: frameDurations[index] || 500 })),
          width: Number(width), height: Number(height), loop: Number(loop),
        });
      });
      if (version !== operationVersion.current) return;
      setEncodingProgress("上传中");
      const asset = await uploadStudioAsset(new File([buffer], `${name.trim() || "studio-animation"}.gif`, { type: "image/gif" }), scope);
      if (version !== operationVersion.current) return;
      setOutputAssetId(asset.asset_id);
      const updated = await saveStudioProject({
        id: saved.id, revision: saved.revision, scope, name: saved.name, kind: "gif",
        document: { ...saved.document, output_asset_id: asset.asset_id },
      });
      if (version !== operationVersion.current) return;
      revisionRef.current = updated.revision;
      setProject(updated);
      setGifStatus("GIF 已存入素材库");
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setGifStatus(reason instanceof Error ? reason.message : "GIF 编码失败");
    } finally {
      workerRef.current?.terminate();
      workerRef.current = null;
      abortEncoding.current = null;
      if (version === operationVersion.current) {
        setEncodingProgress("");
        setBusy(false);
      }
    }
  }

  async function generateFrame(entry?: { key: string; prompt: string; provider_id: string }) {
    const prompt = entry?.prompt || framePrompt.trim();
    const providerId = entry?.provider_id || frameProvider;
    if (!scope || busy || !prompt || !providerId || selected.length >= 60) return;
    if (!entry && !window.confirm(`通过 ${providerId} 生成 1 张 GIF 帧图片，费用以服务商账单为准。继续？`)) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setGifStatus("");
    try {
      const key = entry?.key || globalThis.crypto.randomUUID();
      const entries = (project?.document.frame_jobs as Array<Record<string, unknown>> | undefined) || [];
      const saved = entry ? project! : await persistGif([...entries, { key, prompt, provider_id: providerId }]);
      if (version !== operationVersion.current) return;
      await createStudioJob({
        scope, project_id: saved.id, gif_frame_key: key, idempotency_key: key,
        kind: "image", mode: "draw", prompt, provider_id: providerId,
      });
      if (version !== operationVersion.current) return;
      const latest = await loadStudioProject(saved.id, scope);
      if (version !== operationVersion.current) return;
      loadProject(latest, false);
      setFramePrompt("");
      setGifStatus("生成帧已提交");
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setGifStatus(`${String(reason)}；可从项目记录手动核对并重试`);
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }

  async function toggle(id: string) {
    if (busy || importing.current || selected.length >= 60) return;
    const recorded = ((project?.document.frame_jobs as Array<{ result_asset_id?: string }> | undefined) || [])
      .some((entry) => entry.result_asset_id === id);
    const asset = images.find((item) => item.asset_id === id) || (recorded
      ? { asset_id: id, scope, media_type: "image", filename: `生成帧 ${id}`, created_at: 0 }
      : null);
    if (!asset) return;
    const version = operationVersion.current;
    importing.current = true;
    setImportBusy(true);
    setPlaying(false);
    try {
      const managed = asset.source === "history" && asset.history_id
        ? await preserveHistoryAsset(asset.history_id, scope) : asset;
      if (version !== operationVersion.current) return;
      setImportedAssets((current) => [...current.filter((item) => item.asset_id !== managed.asset_id), managed]);
      setSelected((current) => [...current, managed.asset_id]);
      setFrameDurations((current) => [...current, Math.round(Math.max(20, Math.min(10000, Number(duration) || 500)))]);
      markGifEdited();
      if (asset.source === "history") onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) window.alert(reason instanceof Error ? reason.message : "导入帧失败");
    } finally {
      if (version === operationVersion.current) {
        importing.current = false;
        setImportBusy(false);
      }
    }
  }

  function moveFrame(index: number, direction: -1 | 1) {
    if (busy || importing.current) return;
    const target = index + direction;
    if (target < 0 || target >= selected.length) return;
    const next = [...selected];
    [next[index], next[target]] = [next[target], next[index]];
    setSelected(next);
    const times = [...frameDurations];
    [times[index], times[target]] = [times[target], times[index]];
    setFrameDurations(times);
    setPlaying(false);
    setCurrentFrame(target);
    markGifEdited();
  }

  function removeFrame(index: number) {
    if (busy || importing.current) return;
    setSelected((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setFrameDurations((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setPlaying(false);
    setCurrentFrame((value) => Math.max(0, Math.min(value, selected.length - 2)));
    markGifEdited();
  }

  const selectedAssets: StudioAsset[] = selected.map((id) => images.find((asset) => asset.asset_id === id) || {
    asset_id: id, scope, media_type: "image", filename: id, created_at: 0,
  });
  const previewAsset = selectedAssets[currentFrame];

  return (
    <section className="workspace">
      <div className="workspace-heading"><div><span className="section-kicker">GIF</span><h1>帧动画工作台</h1></div><div className="composer-actions"><input className="project-name" value={name} disabled={busy} onChange={(event) => { setName(event.target.value); markGifEdited(); }} aria-label="GIF 项目名称" /><span className="connection-chip">{selected.length}/60 帧</span></div></div>
      <div className="composer-actions">
        <select aria-label="GIF 项目" disabled={busy} value={project?.id || ""} onChange={(event) => {
          if (dirtyRef.current && !window.confirm("切换项目？未保存的修改将丢失。")) return;
          loadProject(projects.find((item) => item.id === event.target.value) || null);
        }}>
          <option value="">新建动画</option>
          {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <button type="button" className="secondary-action" disabled={busy || importBusy || !scope || (!selected.length && !Array.isArray(project?.document.frame_jobs))} onClick={() => void create(false)}>保存项目</button>
        {project && <button type="button" className="secondary-action" disabled={busy || importBusy || !selected.length} onClick={() => void create(false, true)}>另存副本</button>}
        {project && <button type="button" className="icon-button" title="导出项目 ZIP" disabled={busy} onClick={() => void exportMediaProject(project.id, scope).catch((reason) => setGifStatus(String(reason)))}><Download size={16} /><span className="sr-only">导出项目 ZIP</span></button>}
      </div>
      {importBusy && <p role="status">正在导入素材帧</p>}
      <div className="composer-actions">
        <label className="stack-field"><span>当前帧时长（毫秒）</span><input type="number" min="20" max="10000" step="10" disabled={!selected.length || busy || importBusy} value={frameDurations[currentFrame] || 500} onChange={(event) => {
          const value = Math.round(Math.max(20, Math.min(10000, Number(event.target.value) || 500)));
          setPlaying(false);
          setFrameDurations((current) => current.map((item, index) => index === currentFrame ? value : item));
          markGifEdited();
        }} /></label>
        <button type="button" className="secondary-action" disabled={!selected.length || busy || importBusy} onClick={() => {
          setFrameDurations(selected.map(() => Math.round(Math.max(20, Math.min(10000, Number(duration) || 500)))));
          markGifEdited();
        }}>统一帧时长</button>
      </div>
      <div className="tool-layout">
        <div className="tool-panel gif-editor-panel">
          <div className="panel-heading"><h2>帧序列</h2><div className="composer-actions">
            <button type="button" className="icon-button" onClick={() => setPlaying((value) => !value)} disabled={selected.length < 2} title={playing ? "暂停预览" : "播放预览"}>{playing ? <Pause size={17} /> : <Play size={17} />}<span className="sr-only">{playing ? "暂停预览" : "播放预览"}</span></button>
            <span>{selected.length ? `${currentFrame + 1}/${selected.length}` : "0/0"}</span>
          </div></div>
          <div className="gif-preview">{previewAsset ? <AssetPreview item={previewAsset} history={snapshot.history} /> : <div className="empty-state">暂无帧</div>}</div>
          <div className="gif-frame-list">{selectedAssets.map((asset, index) =>
            <article className={index === currentFrame ? "gif-frame-item active" : "gif-frame-item"} key={`${index}:${asset.asset_id}`} onClick={() => { setCurrentFrame(index); setPlaying(false); }}>
              <AssetPreview item={asset} history={snapshot.history} /><strong>{index + 1} · {frameDurations[index] || 500}ms</strong>
              <div className="gif-frame-actions">
                <button type="button" className="icon-button" onClick={(event) => { event.stopPropagation(); moveFrame(index, -1); }} disabled={busy || importBusy || index === 0} title="帧上移"><ArrowUp size={14} /><span className="sr-only">帧上移</span></button>
                <button type="button" className="icon-button" onClick={(event) => { event.stopPropagation(); moveFrame(index, 1); }} disabled={busy || importBusy || index === selectedAssets.length - 1} title="帧下移"><ArrowDown size={14} /><span className="sr-only">帧下移</span></button>
                <button type="button" className="icon-button danger" disabled={busy || importBusy} onClick={(event) => { event.stopPropagation(); removeFrame(index); }} title="移除帧"><X size={14} /><span className="sr-only">移除帧</span></button>
              </div>
            </article>
          )}</div>
          <h2 className="gif-library-heading">添加素材帧</h2>
          <div className="asset-select-grid">{images.map((asset) =>
            <button type="button" key={asset.asset_id} disabled={busy || importBusy || selected.length >= 60} className={selected.includes(asset.asset_id) ? "asset-select active" : "asset-select"} onClick={() => void toggle(asset.asset_id)}>
              <AssetPreview item={asset} history={snapshot.history} /><span>{selected.filter((id) => id === asset.asset_id).length || ""}</span>
            </button>
          )}</div>
          {images.length === 0 && <div className="empty-state">暂无图片素材</div>}
        </div>
        <aside className="runtime-summary">
          <h2>生成新帧</h2>
          <label className="stack-field"><span>服务商</span><select value={frameProvider} disabled={busy} onChange={(event) => setFrameProvider(event.target.value)}><option value="">选择服务商</option>{frameProviders.map((item) => <option key={item.provider_id} value={item.provider_id}>{item.label || item.provider_id}</option>)}</select></label>
          <label className="stack-field"><span>提示词</span><textarea rows={3} value={framePrompt} disabled={busy} onChange={(event) => setFramePrompt(event.target.value)} /></label>
          <button type="button" className="secondary-action" disabled={busy || !scope || !frameProvider || !framePrompt.trim() || selected.length >= 60} onClick={() => void generateFrame()}>生成帧</button>
          {((project?.document.frame_jobs as Array<{ key: string; prompt: string; provider_id: string; job_id?: string; result_asset_id?: string }> | undefined) || []).map((entry) => {
            const job = frameJobs.find((item) => item.id === entry.job_id || item.request?.gif_frame_key === entry.key);
            return <div className="canvas-edge-row" key={entry.key}><span title={entry.prompt}>{entry.provider_id} · {job?.state || (entry.job_id ? "查询中" : "未提交")} {entry.result_asset_id ? "· 已入库" : ""}</span>
              {entry.result_asset_id && <button type="button" className="icon-button" disabled={busy || selected.length >= 60} title="加入帧序列" onClick={() => void toggle(entry.result_asset_id!)}><ImagePlus size={15} /><span className="sr-only">加入帧序列</span></button>}
              {!entry.job_id && <button type="button" className="icon-button" disabled={busy} title="手动提交此帧" onClick={() => void generateFrame(entry)}><RefreshCw size={15} /><span className="sr-only">手动提交此帧</span></button>}</div>;
          })}
          <h2>导出参数</h2>
          <label className="stack-field"><span>默认帧时长（毫秒）</span><input type="number" min="20" max="10000" step="10" value={duration} disabled={busy} onChange={(event) => { setDuration(event.target.value); markGifEdited(); }} /></label>
          <label className="stack-field"><span>循环次数（0 为无限循环）</span><input type="number" min="0" max="999" value={loop} disabled={busy} onChange={(event) => { setLoop(event.target.value); markGifEdited(); }} /></label>
          <label className="stack-field"><span>宽度（像素）</span><input type="number" min="16" max="1024" value={width} disabled={busy} onChange={(event) => { setWidth(event.target.value); markGifEdited(); }} /></label>
          <label className="stack-field"><span>高度（像素）</span><input type="number" min="16" max="1024" value={height} disabled={busy} onChange={(event) => { setHeight(event.target.value); markGifEdited(); }} /></label>
          <span>总时长 {(frameDurations.reduce((sum, value) => sum + value, 0) / 1000).toFixed(2)} 秒</span>
          <button type="button" className="primary-action" disabled={busy || importBusy || !scope || !selected.length} onClick={() => void encodeInWorker()}>浏览器生成 GIF</button>
          <button type="button" className="secondary-action" disabled={busy || importBusy || !scope || !selected.length} onClick={() => void create(true)}>服务端兼容导出</button>
          {workerRef.current && <button type="button" className="secondary-action" onClick={() => abortEncoding.current?.(new Error("GIF 编码已取消"))}>取消编码</button>}
          {encodingProgress && <p role="status">{encodingProgress}</p>}
          {gifStatus && <p role="status">{gifStatus}</p>}
          {outputAssetId && <button type="button" className="secondary-action" onClick={() => void downloadStudioAsset(outputAssetId, `${name || "studio-animation"}.gif`, scope).catch((reason) => setGifStatus(String(reason)))}><Download size={16} />下载 GIF</button>}
        </aside>
      </div>
    </section>
  );
}

function PromptsView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const [presetFeature, setPresetFeature] = useState("draw");
  const [editingPresets, setEditingPresets] = useState(false);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState("");
  const [operation, setOperation] = useState("optimize");
  const [providerId, setProviderId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  useEffect(() => {
    requestVersion.current += 1;
    setAssetId("");
    setResult("");
    setBusy(false);
    setError("");
    return () => { requestVersion.current += 1; };
  }, [scope]);
  async function transform() {
    if (busy) return;
    const version = ++requestVersion.current;
    setBusy(true);
    setError("");
    try {
      const text = await transformStudioPrompt({ scope, operation, provider_id: providerId, asset_id: assetId, prompt: draft });
      if (version === requestVersion.current) setResult(text);
    } catch (reason) {
      if (version === requestVersion.current) setError(reason instanceof Error ? reason.message : "提示词处理失败");
    } finally {
      if (version === requestVersion.current) setBusy(false);
    }
  }
  const config = snapshot.config as Record<string, any>;
  const groups = [
    ["文生图", config.features?.draw?.presets || []],
    ["改图", config.features?.edit?.presets || []],
    ["视频", config.features?.video?.presets || []],
  ] as Array<[string, unknown[]]>;
  const items = groups.flatMap(([group, values]) => values.map((value) => {
    if (typeof value === "string") {
      const [name, ...rest] = value.split(":");
      return { group, name, prompt: rest.join(":") || name };
    }
    const item = value as Record<string, unknown>;
    return { group, name: String(item.name || item.id || "未命名预设"), prompt: String(item.prompt || item.value || "") };
  })).filter((item) => `${item.name} ${item.prompt}`.toLowerCase().includes(query.toLowerCase()));

  function usePrompt(prompt: string) {
    localStorage.setItem("aiimg-studio-prompt-draft", prompt);
    window.location.hash = "#/create";
  }

  return <section className="workspace">
    <div className="workspace-heading"><div><span className="section-kicker">PROMPTS</span><h1>提示词</h1></div></div>
    <div className="video-options">
      <label className="stack-field"><span>操作</span><select value={operation} disabled={busy} onChange={(event) => setOperation(event.target.value)}><option value="optimize">优化</option><option value="tags">NAI 标签化</option><option value="reverse">图片反推</option></select></label>
      <label className="stack-field"><span>AstrBot 模型</span><select value={providerId} disabled={busy} onChange={(event) => setProviderId(event.target.value)}><option value="">选择模型</option>{(config.astrbot_providers || []).map((item: { id: string; model: string }) => <option key={item.id} value={item.id}>{item.id} · {item.model}</option>)}</select></label>
      {operation === "reverse" && <label className="stack-field"><span>图片素材</span><select value={assetId} disabled={busy} onChange={(event) => setAssetId(event.target.value)}><option value="">选择图片</option>{snapshot.assets.filter((item) => item.media_type === "image" && item.scope === scope).map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename}</option>)}</select></label>}
    </div>
    <div className="prompt-editor"><label htmlFor="prompt-source">原始提示词</label><textarea id="prompt-source" value={draft} onChange={(event) => setDraft(event.target.value)} rows={4} maxLength={8000} /></div>
    <button type="button" className="primary-action" disabled={busy || !scope || !providerId || (operation === "reverse" ? !assetId : !draft.trim())} onClick={() => void transform()}>{busy ? "处理中" : "调用模型"}</button>
    {error && <p role="alert" className="task-error">{error}</p>}
    {result && <div className="prompt-editor"><label htmlFor="prompt-result">处理结果</label><textarea id="prompt-result" value={result} onChange={(event) => setResult(event.target.value)} rows={5} /><button type="button" className="primary-action" disabled={!result.trim()} onClick={() => usePrompt(result.trim())}>带入创作</button></div>}
    <div className="prompt-library-toolbar"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索预设" aria-label="搜索预设" /></div>
    <div className="composer-actions">
      <button type="button" className="secondary-action" onClick={() => {
        if (!editingPresets || window.confirm("关闭预设编辑？未保存的修改将丢失。")) setEditingPresets(!editingPresets);
      }}>{editingPresets ? "关闭编辑" : "编辑预设"}</button>
      {editingPresets && <select aria-label="预设类型" value={presetFeature} onChange={(event) => {
        if (window.confirm("切换预设类型？未保存的修改将丢失。")) setPresetFeature(event.target.value);
      }}><option value="draw">文生图</option><option value="edit">改图</option><option value="video">视频</option></select>}
    </div>
    {editingPresets && <PresetEditor key={presetFeature} feature={presetFeature} values={config.features?.[presetFeature]?.presets || []} revision={snapshot.configRevision || ""} onSaved={onRefresh} />}
    <div className="prompt-library">{items.map((item) => <article className="prompt-card" key={`${item.group}-${item.name}`}><span>{item.group}</span><strong>{item.name}</strong><p>{item.prompt}</p><button type="button" className="secondary-action" onClick={() => usePrompt(item.prompt)}>使用</button></article>)}</div>
  </section>;
}

function DesignView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const models = snapshot.config.astrbot_providers || [];
  const [importedAssets, setImportedAssets] = useState<StudioAsset[]>([]);
  const historyImports = useRef(new Map<string, StudioAsset>());
  const images = [...snapshot.assets, ...importedAssets.filter((asset) => !snapshot.assets.some((item) => item.asset_id === asset.asset_id))]
    .filter((item) => item.media_type === "image" && item.scope === scope);
  const projects = snapshot.projects.filter((item) => item.kind === "design" && item.scope === scope);
  const [project, setProject] = useState<StudioProject | null>(null);
  const [designVersions, setDesignVersions] = useState<StudioProject[]>([]);
  const operationVersion = useRef(0);
  const [assetId, setAssetId] = useState(images[0]?.asset_id || "");
  const [name, setName] = useState("未命名设计");
  const [caption, setCaption] = useState("标题与图片编排");
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState(2);
  const [columns, setColumns] = useState(2);
  const [sliceMode, setSliceMode] = useState<"grid" | "free">("grid");
  const [regions, setRegions] = useState<Array<{ x: number; y: number; width: number; height: number }>>([]);
  const [regionDraft, setRegionDraft] = useState({ x: 0, y: 0, width: 0.5, height: 0.5 });
  const [sourceSize, setSourceSize] = useState<[number, number] | null>(null);
  const [sliceAssets, setSliceAssets] = useState<string[]>([]);
  const [sliceStatus, setSliceStatus] = useState("");
  const [repairPrompt, setRepairPrompt] = useState("");
  const [repairProvider, setRepairProvider] = useState("");
  const [maskAssetId, setMaskAssetId] = useState("");
  const [repairJobs, setRepairJobs] = useState<StudioJob[]>([]);
  const repairProviders = snapshot.capabilities.filter((item) => item.operations.image_edit === "supported"
    && item.references.modes.some((mode) => mode.id === item.references.active_mode
      && mode.status === "supported" && mode.min_images <= 2 && mode.max_images >= 2));
  const [replicaProject, setReplicaProject] = useState<StudioProject | null>(null);
  const [replicaVersions, setReplicaVersions] = useState<StudioProject[]>([]);
  const [replicaName, setReplicaName] = useState("未命名网页");
  const [replicaPreview, setReplicaPreview] = useState(true);
  const [replicaPrompt, setReplicaPrompt] = useState("");
  const [replicaModel, setReplicaModel] = useState("");
  const [replicaReference, setReplicaReference] = useState(false);
  const [embeddedAssets, setEmbeddedAssets] = useState<Record<string, string>>({});
  const replicaProjects = snapshot.projects.filter((item) => item.kind === "web_replica" && item.scope === scope);
  const [replicaFiles, setReplicaFiles] = useState<Array<{ path: string; content: string; asset_ids?: string[] }>>([
    { path: "index.html", content: "<!doctype html>\n<html lang=\"zh-CN\">\n<head><meta charset=\"utf-8\"><title>设计预览</title></head>\n<body><main><h1>开始设计</h1></main></body>\n</html>" },
    { path: "style.css", content: "body { margin: 0; font-family: sans-serif; } main { padding: 32px; }" },
  ]);
  function openProject(next: StudioProject | null) {
    const blocks = Array.isArray(next?.document.blocks) ? next.document.blocks as Array<Record<string, unknown>> : [];
    setProject(next);
    setDesignVersions([]);
    setAssetId(String(blocks.find((item) => item.type === "image")?.asset_id || ""));
    setCaption(String(blocks.find((item) => item.type === "text")?.text || ""));
    setName(next?.name || "未命名设计");
    setRegions(Array.isArray(next?.document.regions) ? next.document.regions as typeof regions : []);
    setSourceSize(Array.isArray(next?.document.source_size) ? next.document.source_size as [number, number] : null);
    setSliceAssets(Array.isArray(next?.document.slice_asset_ids) ? next.document.slice_asset_ids as string[] : []);
    setRepairJobs([]);
    setSliceStatus("");
  }
  function openReplica(next: StudioProject | null) {
    setReplicaVersions([]);
    const files = next?.document.files;
    if (next && (!Array.isArray(files) || files.some((file) => !file || typeof file.path !== "string" || typeof file.content !== "string"))) {
      setSliceStatus("网页文件清单无效");
      return;
    }
    setReplicaProject(next);
    setReplicaPrompt("");
    setReplicaPreview(true);
    setReplicaName(next?.name || "未命名网页");
    setReplicaFiles(Array.isArray(files) ? files.map((file) => ({ ...file })) : [
      { path: "index.html", content: '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"><title>设计</title></head><body></body></html>' },
      { path: "style.css", content: "body { margin: 0; font-family: sans-serif; }" },
    ]);
    setSliceStatus("");
  }
  useEffect(() => {
    operationVersion.current += 1;
    openProject(null);
    openReplica(null);
    setReplicaReference(false);
    historyImports.current.clear();
    setImportedAssets([]);
    setBusy(false);
  }, [scope]);
  useEffect(() => {
    if (!assetId || !scope) { setSourceSize(null); return; }
    let active = true;
    loadAssetPreview(assetId, scope).then((uri) => {
      const image = new Image();
      image.onload = () => { if (active) setSourceSize([image.naturalWidth, image.naturalHeight]); };
      image.src = uri;
    }).catch(() => { if (active) setSourceSize(null); });
    return () => { active = false; };
  }, [assetId, scope]);
  useEffect(() => {
    let active = true;
    const ids = [...new Set(replicaFiles.flatMap((file) => file.asset_ids || []))];
    Promise.all(ids.map(async (id) => [id, await loadAssetPreview(id, scope)] as const))
      .then((pairs) => { if (active) setEmbeddedAssets(Object.fromEntries(pairs)); })
      .catch(() => { if (active) setEmbeddedAssets({}); });
    return () => { active = false; };
  }, [replicaFiles, scope]);
  useEffect(() => () => { operationVersion.current += 1; }, []);
  useEffect(() => {
    if (replicaModel && !models.some((model) => model.id === replicaModel)) setReplicaModel("");
  }, [replicaModel, models]);
  async function managedReference(version: number): Promise<string | null> {
    const asset = images.find((item) => item.asset_id === assetId);
    if (!asset) throw new Error("请重新选择当前会话的图片素材");
    if (asset.source !== "history") return asset.asset_id;
    if (!asset.history_id) throw new Error("历史图片编号无效");
    const managed = historyImports.current.get(asset.asset_id) || await preserveHistoryAsset(asset.history_id, scope);
    if (version !== operationVersion.current) return null;
    historyImports.current.set(asset.asset_id, managed);
    setImportedAssets((current) => [...current.filter((item) => item.asset_id !== managed.asset_id), managed]);
    setAssetId(managed.asset_id);
    onRefresh();
    return managed.asset_id;
  }
  async function slice() {
    if (busy || !assetId || !scope) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setSliceStatus("");
    try {
      const reference = await managedReference(version);
      if (!reference || version !== operationVersion.current) return;
      const results = await sliceStudioAsset({
        scope, asset_id: reference, ...(sliceMode === "free" ? { regions } : { rows, columns }),
      });
      if (version !== operationVersion.current) return;
      setSliceAssets((current) => [...current, ...results.map((item) => item.asset_id)]);
      setImportedAssets((current) => [...current, ...results]);
      setSliceStatus(`已保存 ${results.length} 张切片`);
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "切分失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function uploadMask(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !scope) return;
    setBusy(true);
    try {
      const asset = await uploadStudioAsset(file, scope);
      setImportedAssets((current) => [...current, asset]);
      setMaskAssetId(asset.asset_id);
      onRefresh();
    } catch (reason) {
      setSliceStatus(reason instanceof Error ? reason.message : "遮罩上传失败");
    } finally {
      event.target.value = "";
      setBusy(false);
    }
  }
  async function submitRepair(existing?: Record<string, unknown>) {
    if (busy || !scope || !assetId || !maskAssetId && !existing) return;
    if (!existing && !window.confirm("通过所选服务商使用原图和遮罩参考图生成修补结果，可能产生费用。继续？")) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setSliceStatus("");
    try {
      const reference = existing ? String((existing.reference_asset_ids as string[])[0]) : await managedReference(version);
      if (!reference || version !== operationVersion.current) return;
      const key = String(existing?.key || globalThis.crypto.randomUUID());
      const entry = existing || {
        type: "repair", key, prompt: repairPrompt.trim(), provider_id: repairProvider,
        reference_asset_ids: [reference, maskAssetId], mask_asset_id: maskAssetId,
      };
      let saved = project;
      if (!existing) {
        const blocks = Array.isArray(project?.document.blocks) ? [...project.document.blocks] as Array<Record<string, unknown>> : [];
        blocks.push(entry);
        saved = await saveStudioProject({
          id: project?.id, revision: project?.revision, scope, kind: "design", name,
          document: { ...project?.document, version: 2, blocks, regions, source_size: sourceSize,
            slice_asset_ids: sliceAssets },
        });
        if (version !== operationVersion.current) return;
        setProject(saved);
        onRefresh();
      }
      if (!saved) throw new Error("修补项目尚未保存");
      const job = await createStudioJob({
        scope, project_id: saved.id, design_repair_key: key, idempotency_key: key,
        kind: "image", mode: "edit", prompt: String(entry.prompt),
        provider_id: String(entry.provider_id), reference_asset_ids: entry.reference_asset_ids,
      });
      if (version !== operationVersion.current) return;
      setRepairJobs((current) => [...current.filter((item) => item.id !== job.id), job]);
      setProject(await loadStudioProject(saved.id, scope));
      setSliceStatus("修补任务已提交，请在任务中心查看进度");
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(`${String(reason)}；项目中的任务可手动核对`);
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function refreshRepair() {
    if (!project || busy) return;
    setBusy(true);
    try {
      const [latest, jobs] = await Promise.all([loadStudioProject(project.id, scope), loadProjectJobs(project.id, scope)]);
      openProject(latest);
      setRepairJobs(jobs);
      onRefresh();
    } catch (reason) {
      setSliceStatus(String(reason));
    } finally {
      setBusy(false);
    }
  }
  async function showDesignVersions() {
    if (!project || busy) return;
    setBusy(true);
    try {
      setDesignVersions(await loadProjectVersions(project.id, scope));
    } catch (reason) {
      setSliceStatus(String(reason));
    } finally {
      setBusy(false);
    }
  }
  async function save(asCopy = false) {
    if (busy || !scope || !assetId) return;
    const version = ++operationVersion.current;
    setBusy(true);
    try {
      const reference = await managedReference(version);
      if (!reference || version !== operationVersion.current) return;
      const blocks = Array.isArray(project?.document.blocks) ? [...project.document.blocks] as Array<Record<string, unknown>> : [];
      for (const block of [{ type: "image", asset_id: reference }, { type: "text", text: caption }]) {
        const index = blocks.findIndex((item) => item.type === block.type);
        if (index < 0) blocks.push(block);
        else blocks[index] = { ...blocks[index], ...block };
      }
      const saved = await saveStudioProject({
        id: asCopy ? undefined : project?.id, revision: asCopy ? undefined : project?.revision,
        scope, name: asCopy ? `${name} 副本` : name, kind: "design",
        document: { ...project?.document, version: 2, blocks, regions, source_size: sourceSize,
          slice_asset_ids: sliceAssets },
      });
      if (version !== operationVersion.current) return;
      setProject(saved);
      setName(saved.name);
      setSliceStatus("项目已保存");
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "设计项目保存失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function saveReplica(asCopy = false) {
    if (busy || !scope) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setSliceStatus("");
    try {
      const saved = await saveStudioProject({
        id: asCopy ? undefined : replicaProject?.id,
        revision: asCopy ? undefined : replicaProject?.revision,
        scope, name: asCopy ? `${replicaName} 副本` : replicaName, kind: "web_replica",
        document: { ...replicaProject?.document, version: 1, files: replicaFiles },
      });
      if (version !== operationVersion.current) return;
      setReplicaProject(saved);
      setReplicaName(saved.name);
      setSliceStatus(`静态网页项目已保存：${saved.name}`);
      onRefresh();
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "网页项目保存失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function generateReplica() {
    if (busy || !scope || !replicaPrompt.trim() || !replicaModel.trim()) return;
    if (replicaReference && !images.some((item) => item.asset_id === assetId)) {
      setSliceStatus("请先选择参考图片");
      return;
    }
    if (!window.confirm("调用所选模型生成网页草稿，可能产生费用，并替换当前未保存的文件内容。继续？")) return;
    const version = ++operationVersion.current;
    setBusy(true);
    setSliceStatus("");
    try {
      const reference = replicaReference ? await managedReference(version) : "";
      if (reference === null || version !== operationVersion.current) return;
      const files = await generateWebReplica({
        scope, provider_id: replicaModel.trim(), prompt: replicaPrompt.trim(),
        asset_id: reference,
        document: { files: replicaFiles },
      });
      if (version !== operationVersion.current) return;
      setReplicaFiles(files);
      setReplicaPreview(true);
      setSliceStatus("草稿已生成，尚未保存");
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "网页生成失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function exportReplica() {
    if (!replicaProject || busy) return;
    const version = ++operationVersion.current;
    setBusy(true);
    try {
      await exportWebProject(replicaProject.id, scope);
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "导出失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  async function showReplicaVersions() {
    if (!replicaProject || busy) return;
    const version = ++operationVersion.current;
    setBusy(true);
    try {
      const items = await loadProjectVersions(replicaProject.id, scope);
      if (version === operationVersion.current) {
        setReplicaVersions(items);
        setSliceStatus(items.length ? "" : "暂无历史版本");
      }
    } catch (reason) {
      if (version === operationVersion.current) setSliceStatus(reason instanceof Error ? reason.message : "读取版本失败");
    } finally {
      if (version === operationVersion.current) setBusy(false);
    }
  }
  const selectedAsset = images.find((item) => item.asset_id === assetId);
  const previewHtml = useMemo(
    () => typeof document === "undefined" ? "" : buildStaticPreview(replicaFiles, embeddedAssets),
    [replicaFiles, embeddedAssets],
  );
  return <section className="workspace">
    <div className="workspace-heading"><div><span className="section-kicker">DESIGN</span><h1>设计与切图</h1></div></div>
    <div className="design-layout">
        <div className="design-preview">
          <div className="design-preview-media" style={sourceSize ? { aspectRatio: `${sourceSize[0]} / ${sourceSize[1]}` } : undefined}>
            {selectedAsset && <AssetPreview item={selectedAsset} history={snapshot.history} />}
            {sliceMode === "free" && <div className="design-region-preview">{regions.map((region, index) =>
              <span key={index} title={`区域 ${index + 1}`} style={{ left: `${region.x * 100}%`, top: `${region.y * 100}%`, width: `${region.width * 100}%`, height: `${region.height * 100}%` }}>{index + 1}</span>
            )}</div>}
          </div>
          {sourceSize && <small>{sourceSize[0]} × {sourceSize[1]} px</small>}
          <h2>{caption}</h2>
          {sliceStatus && <p role="status">{sliceStatus}</p>}
          <div className="replica-preview-heading">
            <h2>网页静态预览</h2>
            <button type="button" className="secondary-action" onClick={() => setReplicaPreview((value) => !value)}>{replicaPreview ? "隐藏预览" : "显示预览"}</button>
          </div>
          {replicaPreview && <iframe
            className="replica-preview-frame"
            title="网页静态预览"
            sandbox=""
            referrerPolicy="no-referrer"
            srcDoc={previewHtml}
          />}
        </div>
      <aside className="runtime-summary">
        <label className="stack-field"><span>设计项目</span><select value={project?.id || ""} disabled={busy} onChange={(event) => {
          if ((assetId || caption) && !window.confirm("切换项目？未保存的修改将丢失。")) return;
          openProject(projects.find((item) => item.id === event.target.value) || null);
        }}><option value="">新建设计</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="stack-field"><span>项目名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="stack-field"><span>标题</span><input value={caption} onChange={(event) => setCaption(event.target.value)} /></label>
        <label className="stack-field"><span>主图素材</span><select value={assetId} disabled={busy} onChange={(event) => setAssetId(event.target.value)}><option value="">选择图片</option>{images.map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename}</option>)}</select></label>
        <button type="button" className="primary-action" disabled={busy || !selectedAsset} onClick={() => void save()}>保存设计项目</button>
        {project && <div className="composer-actions">
          <button type="button" className="secondary-action" disabled={busy || !selectedAsset} onClick={() => void save(true)}>另存副本</button>
          <button type="button" className="icon-button" disabled={busy} title="历史版本" onClick={() => void showDesignVersions()}><RotateCcw size={17} /><span className="sr-only">历史版本</span></button>
          <button type="button" className="icon-button" disabled={busy} title="导出设计项目 ZIP" onClick={() => void exportMediaProject(project.id, scope).catch((reason) => setSliceStatus(String(reason)))}><Download size={17} /><span className="sr-only">导出设计项目 ZIP</span></button>
        </div>}
        {designVersions.length > 0 && <label className="stack-field"><span>载入旧版本到编辑区</span><select value="" disabled={busy} onChange={(event) => {
          const previous = designVersions.find((item) => item.revision === Number(event.target.value));
          if (!previous || !window.confirm("载入历史设计？未保存的修改将丢失。")) return;
          const current = project;
          openProject(previous);
          setProject(current);
          setSliceStatus(`已载入版本 ${previous.revision}，保存后形成新修订`);
        }}><option value="">选择版本</option>{designVersions.map((item) => <option key={item.revision} value={item.revision}>v{item.revision} · {formatTime(item.updated_at)}</option>)}</select></label>}
        <h2>网格切图</h2>
        <div className="mode-switch"><button type="button" className={sliceMode === "grid" ? "active" : ""} onClick={() => setSliceMode("grid")}>网格</button><button type="button" className={sliceMode === "free" ? "active" : ""} onClick={() => setSliceMode("free")}>自由区域</button></div>
        {sliceMode === "grid" ? <>
          <label className="stack-field"><span>行数</span><input type="number" min={1} max={8} step={1} value={rows} disabled={busy} onChange={(event) => setRows(Number(event.target.value))} /></label>
          <label className="stack-field"><span>列数</span><input type="number" min={1} max={8} step={1} value={columns} disabled={busy} onChange={(event) => setColumns(Number(event.target.value))} /></label>
        </> : <>
          {(["x", "y", "width", "height"] as const).map((key) => <label key={key} className="stack-field"><span>{({ x: "左", y: "上", width: "宽", height: "高" })[key]}（原图比例 0–1）</span><input type="number" min={0} max={1} step={0.01} value={regionDraft[key]} disabled={busy} onChange={(event) => setRegionDraft((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>)}
          <button type="button" className="secondary-action" disabled={busy || regions.length >= 32 || !(regionDraft.width > 0 && regionDraft.height > 0 && regionDraft.x >= 0 && regionDraft.y >= 0 && regionDraft.x + regionDraft.width <= 1 && regionDraft.y + regionDraft.height <= 1)} onClick={() => setRegions((current) => [...current, { ...regionDraft }])}>添加区域</button>
          {regions.map((region, index) => <div className="canvas-edge-row" key={index}><span>{index + 1} · {sourceSize ? `${Math.round(region.x * sourceSize[0])}, ${Math.round(region.y * sourceSize[1])} · ${Math.round(region.width * sourceSize[0])}×${Math.round(region.height * sourceSize[1])} px` : `${region.x}, ${region.y}, ${region.width}, ${region.height}`}</span><button type="button" className="icon-button danger" title="移除区域" disabled={busy} onClick={() => setRegions((current) => current.filter((_, position) => position !== index))}><X size={15} /><span className="sr-only">移除区域</span></button></div>)}
        </>}
        <button type="button" className="primary-action" disabled={busy || !selectedAsset || (sliceMode === "free" ? !regions.length : !Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || columns < 1 || rows > 8 || columns > 8 || rows * columns > 32)} onClick={() => void slice()}>{busy ? "处理中" : `切分为 ${sliceMode === "free" ? regions.length : rows * columns} 张`}</button>
        {sliceAssets.length > 0 && <div className="asset-select-grid">{sliceAssets.map((id) => <button type="button" className="asset-select" key={id} onClick={() => setAssetId(id)} title="将切片用作主图"><AssetPreview item={images.find((asset) => asset.asset_id === id) || { asset_id: id, scope, media_type: "image", filename: id, created_at: 0 }} /></button>)}</div>}
        <a className="secondary-action" href="#/assets">查看素材</a>
        <h2>双图参考修补</h2>
        <label className="stack-field"><span>服务商</span><select value={repairProvider} disabled={busy} onChange={(event) => setRepairProvider(event.target.value)}><option value="">选择支持双图改图的服务商</option>{repairProviders.map((item) => <option key={item.provider_id} value={item.provider_id}>{item.label || item.provider_id}</option>)}</select></label>
        <label className="stack-field"><span>遮罩参考图</span><select value={maskAssetId} disabled={busy} onChange={(event) => setMaskAssetId(event.target.value)}><option value="">选择素材</option>{images.map((item) => <option key={item.asset_id} value={item.asset_id}>{item.filename}</option>)}</select></label>
        <label className="secondary-action">上传遮罩参考图<input className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(event) => void uploadMask(event)} /></label>
        <label className="stack-field"><span>修补提示词</span><textarea rows={3} value={repairPrompt} disabled={busy} onChange={(event) => setRepairPrompt(event.target.value)} /></label>
        <button type="button" className="secondary-action" disabled={busy || !assetId || !maskAssetId || !repairProvider || !repairPrompt.trim()} onClick={() => void submitRepair()}>提交参考修补</button>
        {project && <button type="button" className="icon-button" title="查询修补任务" disabled={busy} onClick={() => void refreshRepair()}><RefreshCw size={16} /><span className="sr-only">查询修补任务</span></button>}
        {((project?.document.blocks as Array<Record<string, unknown>> | undefined) || []).filter((item) => item.type === "repair").map((item) => {
          const job = repairJobs.find((candidate) => candidate.id === item.job_id);
          return <div className="canvas-edge-row" key={String(item.key)}><span>{String(item.provider_id)} · {job?.state || (item.job_id ? "已提交" : "待核对")}</span>
            {!item.job_id && <button type="button" className="icon-button" title="手动核对提交" disabled={busy} onClick={() => void submitRepair(item)}><RefreshCw size={15} /><span className="sr-only">手动核对提交</span></button>}
            {Boolean(item.result_asset_id) && <button type="button" className="icon-button" title="使用修补结果" onClick={() => setAssetId(String(item.result_asset_id))}><ImageIcon size={15} /><span className="sr-only">使用修补结果</span></button>}</div>;
        })}
        <h2>静态网页复刻</h2>
        <label className="stack-field"><span>AstrBot 模型</span><select disabled={busy} value={replicaModel} onChange={(event) => setReplicaModel(event.target.value)}><option value="">选择模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.id} · {model.model}</option>)}</select></label>
        <label className="stack-field"><span>生成或修改要求</span><textarea disabled={busy} rows={4} maxLength={8000} value={replicaPrompt} onChange={(event) => setReplicaPrompt(event.target.value)} /></label>
        <label className="check-row"><input type="checkbox" disabled={busy} checked={replicaReference} onChange={(event) => setReplicaReference(event.target.checked)} />使用主图参考</label>
        <button type="button" className="primary-action" disabled={busy || !scope || !replicaModel.trim() || !replicaPrompt.trim() || (replicaReference && !selectedAsset)} onClick={() => void generateReplica()}>生成网页草稿</button>
        <label className="stack-field"><span>网页项目</span><select disabled={busy} value={replicaProject?.id || ""} onChange={(event) => {
          if (!window.confirm("切换网页项目？未保存的修改将丢失。")) return;
          openReplica(replicaProjects.find((item) => item.id === event.target.value) || null);
        }}><option value="">新建网页</option>{replicaProjects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="stack-field"><span>网页名称</span><input disabled={busy} value={replicaName} onChange={(event) => setReplicaName(event.target.value)} /></label>
        {replicaFiles.map((file, index) => <label className="stack-field" key={file.path}><span>{file.path}</span><textarea rows={4} value={file.content} disabled={busy} onChange={(event) => setReplicaFiles((current) => current.map((item, position) => position === index ? { ...item, content: event.target.value } : item))} /></label>)}
        <button type="button" className="secondary-action" disabled={busy || !selectedAsset || !replicaFiles.some((file) => file.path === "index.html")} onClick={() => {
          const id = selectedAsset?.asset_id;
          if (!id) return;
          setReplicaFiles((current) => current.map((file) => file.path === "index.html"
            ? { ...file, content: `${file.content}\n<img src="asset://${id}" alt="">`,
                asset_ids: [...new Set([...(file.asset_ids || []), id])] } : file));
        }}>插入主图到网页</button>
        <button type="button" className="secondary-action" disabled={busy || !scope} onClick={() => void saveReplica()}>保存静态网页项目</button>
        {replicaProject && <div className="composer-actions">
          <button type="button" className="secondary-action" disabled={busy} onClick={() => void saveReplica(true)}>另存网页副本</button>
          <button type="button" className="icon-button" disabled={busy} title="历史版本" onClick={() => void showReplicaVersions()}><RotateCcw size={17} /><span className="sr-only">历史版本</span></button>
          <button type="button" className="icon-button" disabled={busy} title="导出已保存版本 ZIP" onClick={() => void exportReplica()}><Download size={17} /><span className="sr-only">导出已保存版本 ZIP</span></button>
        </div>}
        {replicaVersions.length > 0 && <label className="stack-field"><span>恢复到编辑区</span><select disabled={busy} value="" onChange={(event) => {
          const previous = replicaVersions.find((item) => item.revision === Number(event.target.value));
          if (!previous || !window.confirm("载入历史版本？当前未保存内容将被替换。")) return;
          const current = replicaProject;
          openReplica(previous);
          setReplicaProject(current);
          setSliceStatus(`已载入版本 ${previous.revision}，保存后生效`);
        }}><option value="">选择历史版本</option>{replicaVersions.map((item) => <option key={item.revision} value={item.revision}>v{item.revision} · {formatTime(item.updated_at)}</option>)}</select></label>}
      </aside>
    </div>
  </section>;
}

function AgentView({ snapshot, scope, onRefresh }: { snapshot: StudioSnapshot; scope: string; onRefresh: () => void }) {
  const projects = snapshot.projects.filter((item) => item.kind === "agent" && item.scope === scope);
  const models = snapshot.config.astrbot_providers || [];
  const [project, setProject] = useState<StudioProject | null>(null);
  const [goal, setGoal] = useState("");
  const [count, setCount] = useState("2");
  const [modelId, setModelId] = useState("");
  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [approval, setApproval] = useState<Awaited<ReturnType<typeof reviewAgent>> | null>(null);
  const planVersion = useRef(0);
  const projectRevision = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function openProject(next: StudioProject | null) {
    planVersion.current += 1;
    setProject(next);
    projectRevision.current = next?.revision || 0;
    setGoal(String(next?.document.goal || ""));
    setModelId(String(next?.document.model_provider_id || ""));
    setCount(String(next?.document.requested_count || 2));
    setJobs([]);
    setApproval(null);
    setConfirmed(false);
    setError("");
  }
  useEffect(() => {
    openProject(null);
    setBusy(false);
  }, [scope]);
  useEffect(() => () => { planVersion.current += 1; }, []);
  useEffect(() => {
    if (!project) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [items, latest] = await Promise.all([
          loadProjectJobs(project!.id, scope), loadStudioProject(project!.id, scope),
        ]);
        if (active) {
          setJobs(items.sort((a, b) => Number(a.plan_index || 0) - Number(b.plan_index || 0)));
          if (latest.revision !== projectRevision.current) {
            projectRevision.current = latest.revision;
            setProject(latest);
          }
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "读取 Agent 会话失败");
      } finally {
        if (active) timer = setTimeout(poll, 5000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [project?.id, scope]);

  function invalidateReview() {
    planVersion.current += 1;
    setApproval(null);
    setConfirmed(false);
  }
  async function plan() {
    if (busy || !scope || !goal.trim() || !modelId || !/^[1-8]$/.test(count)) return;
    const version = planVersion.current;
    setBusy(true);
    setError("");
    try {
      const next = await draftAgent({
        scope, goal: goal.trim(), count: Number(count), model_provider_id: modelId,
        project_id: project?.id, revision: project?.revision,
      });
      if (version !== planVersion.current) return;
      setProject(next);
      projectRevision.current = next.revision;
      setApproval(null);
      setConfirmed(false);
      onRefresh();
    } catch (reason) {
      if (version === planVersion.current) setError(reason instanceof Error ? reason.message : "Agent 规划失败");
    } finally {
      if (version === planVersion.current) setBusy(false);
    }
  }

  const saved = !!project && goal.trim() === project.document.goal &&
    modelId === project.document.model_provider_id &&
    Number(count) === Number(project.document.requested_count);
  async function review() {
    if (!project || !saved || busy) return;
    const version = planVersion.current;
    setBusy(true);
    setError("");
    try {
      const next = await reviewAgent(project.id, scope);
      if (version === planVersion.current) {
        setApproval(next);
        setConfirmed(false);
      }
    } catch (reason) {
      if (version === planVersion.current) setError(reason instanceof Error ? reason.message : "计划审阅失败");
    } finally {
      if (version === planVersion.current) setBusy(false);
    }
  }

  async function run() {
    if (!scope || !project || !saved || !confirmed || !approval || busy) return;
    const version = planVersion.current;
    setBusy(true);
    setError("");
    try {
      const items = await executeAgent({
        scope, project_id: project.id, confirmation_token: approval.confirmation_token,
        confirmation_expires: approval.confirmation_expires,
      });
      if (version !== planVersion.current) return;
      setJobs(items);
      setConfirmed(false);
      setApproval(null);
      const latest = await loadStudioProject(project.id, scope);
      if (version === planVersion.current) {
        projectRevision.current = latest.revision;
        setProject(latest);
      }
      onRefresh();
    } catch (reason) {
      if (version === planVersion.current) setError(reason instanceof Error ? reason.message : "Agent 任务提交失败");
    } finally {
      if (version === planVersion.current) setBusy(false);
    }
  }
  const tasks = (project?.document.tasks || []) as Array<Record<string, unknown>>;
  return <section className="workspace">
    <div className="workspace-heading"><div><span className="section-kicker">AGENT</span><h1>受控 Agent</h1></div></div>
    <div className="agent-layout">
      <fieldset className="prompt-editor" disabled={busy}>
        <label className="stack-field"><span>Agent 会话</span><select value={project?.id || ""} onChange={(event) => {
          if (goal.trim() && !window.confirm("切换 Agent 会话？未保存目标将丢失。")) return;
          openProject(projects.find((item) => item.id === event.target.value) || null);
        }}><option value="">新建会话</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label htmlFor="agent-prompt">任务目标</label>
        <textarea id="agent-prompt" rows={6} maxLength={8000} value={goal} disabled={project?.document.state === "submitted"} onChange={(event) => { invalidateReview(); setGoal(event.target.value); }} />
        <label className="stack-field"><span>最多任务数</span><input type="number" min="1" max="8" step="1" value={count} disabled={project?.document.state === "submitted"} onChange={(event) => { invalidateReview(); setCount(event.target.value); }} /></label>
        <label className="stack-field"><span>AstrBot 规划模型</span><select value={modelId} disabled={project?.document.state === "submitted"} onChange={(event) => { invalidateReview(); setModelId(event.target.value); }}>
          <option value="">选择模型</option>{models.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.model}</option>)}
        </select></label>
        <button type="button" className="secondary-action" disabled={busy || !scope || !modelId || !goal.trim() || !/^[1-8]$/.test(count) || project?.document.state === "submitted"} onClick={() => void plan()}>{project ? "重新规划" : "生成计划"}</button>
      </fieldset>
      <aside className="runtime-summary">
        <h2>任务计划</h2>
        <span>{snapshot.sessions.find((session) => session.scope === scope)?.title || scope || "未选择会话"}</span>
        {tasks.map((task, index) => <div className="agent-review" key={index}>
          <strong>{index + 1}. {String(task.prompt || "")}</strong>
          <span>{String(task.kind || "")} · {String(task.mode || "")} · {String(task.provider_id || "")}</span>
          <span>{[task.size, task.resolution, task.seconds && `${task.seconds} 秒`, task.aspect_ratio].filter(Boolean).map(String).join(" · ") || "服务商默认参数"}</span>
          <span>参考 {Array.isArray(task.reference_asset_ids) ? task.reference_asset_ids.length : 0} 张 · 依赖 {Array.isArray(task.depends_on) ? task.depends_on.length : 0} 项</span>
          <span>{jobs[index]?.state || "未执行"}</span>
        </div>)}
        {project && <span>费用：未知，以服务商实际账单为准</span>}
        {approval && <span>确认有效期至 {new Date(approval.confirmation_expires * 1000).toLocaleTimeString()}</span>}
        {error && <p role="alert" className="task-error">{error}</p>}
        {project?.document.state !== "submitted" && <>
          <button type="button" className="secondary-action" disabled={busy || !saved || !tasks.length} onClick={() => void review()}>审阅执行参数</button>
          <label className="check-row"><input type="checkbox" disabled={!approval || busy} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />确认 {tasks.length} 项任务及可能产生的费用</label>
          <button type="button" className="primary-action" disabled={busy || !approval || !confirmed || !saved} onClick={() => void run()}>{busy ? "处理中" : "执行已确认计划"}</button>
        </>}
        {jobs.map((job) => <div className="canvas-edge-row" key={job.id}><span>{job.plan_index || jobs.indexOf(job) + 1} · {job.state}</span>{job.state === "queued" && <button type="button" className="icon-button" title="取消本地排队步骤" onClick={() => void cancelStudioJob(job.id, scope).then(() => loadProjectJobs(project!.id, scope)).then(setJobs).catch((reason) => setError(String(reason)))}><CircleStop size={15} /><span className="sr-only">取消本地排队步骤</span></button>}</div>)}
      </aside>
    </div>
  </section>;
}

function PersonaReferencePreview({ path }: { path: string }) {
  const [source, setSource] = useState("");

  useEffect(() => {
    let active = true;
    loadPersonaReferencePreview(path)
      .then((value) => active && setSource(value))
      .catch(() => active && setSource(""));
    return () => {
      active = false;
    };
  }, [path]);

  return source ? <img src={source} alt="" loading="lazy" /> : <div className="media-placeholder"><ImageIcon size={20} aria-hidden="true" /></div>;
}

function PersonasView({ snapshot, onRefresh }: { snapshot: StudioSnapshot; onRefresh: () => void }) {
  const [pending, setPending] = useState("");
  const [selectedId, setSelectedId] = useState(snapshot.personaProfiles[0]?.id || "");
  const [draft, setDraft] = useState<PersonaProfile | null>(null);
  const selected = snapshot.personaProfiles.find((item) => item.id === selectedId);

  useEffect(() => {
    if (!selectedId || !snapshot.personaProfiles.some((item) => item.id === selectedId)) {
      const next = snapshot.personaProfiles[0];
      setSelectedId(next?.id || "");
      setDraft(next ? { ...next, ref_images: [...next.ref_images], ref_roles: { ...next.ref_roles } } : null);
    }
  }, [selectedId, snapshot.personaProfiles]);

  useEffect(() => {
    if (selected) {
      setDraft({ ...selected, ref_images: [...selected.ref_images], ref_roles: { ...selected.ref_roles } });
    }
  }, [selectedId]);

  function choose(id: string) {
    setSelectedId(id);
    const next = snapshot.personaProfiles.find((item) => item.id === id);
    setDraft(next ? { ...next, ref_images: [...next.ref_images], ref_roles: { ...next.ref_roles } } : null);
  }

  function createNew() {
    setSelectedId("");
    setDraft({ id: "", name: "", base_prompt: "", ref_images: [], ref_roles: {} });
  }

  function updateDraft(update: Partial<PersonaProfile>) {
    setDraft((current) => current ? { ...current, ...update } : current);
  }

  async function save() {
    if (!draft) return;
    setPending("save");
    try {
      const saved = await saveStudioPersona({
        id: draft.id,
        name: draft.name,
        base_prompt: draft.base_prompt,
        ref_images: draft.ref_images,
        ref_roles: draft.ref_roles,
      }, selectedId);
      setSelectedId(saved.id);
      setDraft({ ...saved, ref_images: [...saved.ref_images], ref_roles: { ...saved.ref_roles } });
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "人设保存失败");
    } finally {
      setPending("");
    }
  }

  async function remove() {
    if (!draft?.id || !window.confirm(`确定删除人设「${draft.name || draft.id}」？`)) return;
    setPending("delete");
    try {
      await deleteStudioPersona(draft.id);
      setDraft(null);
      setSelectedId("");
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "人设删除失败");
    } finally {
      setPending("");
    }
  }

  async function makeDefault() {
    if (!draft?.id) return;
    setPending("default");
    try {
      await switchStudioPersona(draft.id);
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "默认人设切换失败");
    } finally {
      setPending("");
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []).slice(0, 9);
    if (!files.length || !draft) return;
    setPending("upload");
    try {
      const uploaded: string[] = [];
      for (const file of files) uploaded.push(await uploadStudioPersonaReference(file));
      const refs = [...draft.ref_images, ...uploaded].slice(0, 32);
      const roles = { ...draft.ref_roles };
      uploaded.forEach((ref) => { roles[ref] = "identity"; });
      updateDraft({ ref_images: refs, ref_roles: roles });
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "参考图上传失败");
    } finally {
      setPending("");
      event.target.value = "";
    }
  }

  function removeRef(path: string) {
    if (!draft) return;
    const roles = { ...draft.ref_roles };
    delete roles[path];
    updateDraft({ ref_images: draft.ref_images.filter((item) => item !== path), ref_roles: roles });
  }

  function moveRef(index: number, direction: -1 | 1) {
    if (!draft) return;
    const target = index + direction;
    if (target < 0 || target >= draft.ref_images.length) return;
    const refs = [...draft.ref_images];
    [refs[index], refs[target]] = [refs[target], refs[index]];
    updateDraft({ ref_images: refs });
  }

  async function selectPersona(session: StudioSnapshot["sessions"][number], personaId: string) {
    setPending(session.scope);
    try {
      await setSessionPersona(session.persona_scope || session.scope, personaId);
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "会话人设保存失败");
    } finally {
      setPending("");
    }
  }

  const roleLabels: Record<PersonaReferenceRole, string> = {
    identity: "身份",
    clothing: "服装",
    pose: "姿势",
    scene: "场景",
  };

  return (
    <section className="workspace">
      <div className="workspace-heading">
        <div><span className="section-kicker">PERSONAS</span><h1>会话人设</h1></div>
        <span className="connection-chip">{snapshot.personaProfiles.length} 套人设</span>
      </div>
      <div className="persona-editor-layout">
        <aside className="tool-panel persona-list-panel">
          <div className="panel-heading"><h2>人设库</h2><button type="button" className="secondary-action" onClick={createNew}>新建</button></div>
          {snapshot.personaProfiles.map((persona) => (
            <button type="button" className={selectedId === persona.id ? "persona-picker active" : "persona-picker"} key={persona.id} onClick={() => choose(persona.id)}>
              <strong>{persona.name}</strong><small>{persona.id} · {persona.ref_images.length} 张参考图{persona.active ? " · 全局默认" : ""}</small>
            </button>
          ))}
        </aside>
        <div className="tool-panel persona-form">
          {draft ? <>
            <div className="panel-heading"><h2>{draft.id ? "编辑人设" : "新建人设"}</h2><div className="composer-actions"><button type="button" className="secondary-action" disabled={!draft.id || pending === "default" || draft.active} onClick={() => void makeDefault()}>{draft.active ? "全局默认" : "设为默认"}</button><button type="button" className="primary-action" disabled={pending === "save" || !draft.name.trim()} onClick={() => void save()}>{pending === "save" ? "保存中" : "保存人设"}</button></div></div>
            <label className="stack-field"><span>人设 ID</span><input value={draft.id} disabled={Boolean(selectedId)} onChange={(event) => updateDraft({ id: event.target.value })} placeholder="例如 robin" /></label>
            <label className="stack-field"><span>名称</span><input value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} placeholder="例如 知更鸟" /></label>
            <label className="stack-field"><span>基础提示词</span><textarea rows={4} value={draft.base_prompt} onChange={(event) => updateDraft({ base_prompt: event.target.value })} placeholder="角色外观、气质和长期设定" /></label>
            <div className="panel-heading"><h2>参考图与职责</h2><label className="secondary-action"><ImagePlus size={16} aria-hidden="true" />{pending === "upload" ? "上传中" : "添加参考图"}<input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple onChange={(event) => void upload(event)} /></label></div>
            <div className="persona-ref-grid">
              {draft.ref_images.map((path, index) => <article className="persona-ref-card" key={`${path}-${index}`}><div className="persona-ref-media"><PersonaReferencePreview path={path} /></div><small title={path}>{path.split(/[\\/]/).pop() || path}</small><select value={draft.ref_roles[path] || "identity"} onChange={(event) => updateDraft({ ref_roles: { ...draft.ref_roles, [path]: event.target.value as PersonaReferenceRole } })}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><div className="asset-actions"><button type="button" className="icon-button" onClick={() => moveRef(index, -1)} title="前移">←</button><button type="button" className="icon-button" onClick={() => moveRef(index, 1)} title="后移">→</button><button type="button" className="icon-button danger" onClick={() => removeRef(path)} title="移除">×</button></div></article>)}
              {draft.ref_images.length === 0 && <div className="empty-state">暂无参考图</div>}
            </div>
            {draft.id && <button type="button" className="secondary-action danger-action" disabled={pending === "delete"} onClick={() => void remove()}>删除这套人设</button>}
          </> : <div className="empty-state">选择一套人设，或点击新建。</div>}
        </div>
      </div>
      <div className="subsection-heading">会话独立选择</div>
      <div className="session-list">
        {snapshot.sessions.map((session) => <article className="session-row" key={session.scope}><div><strong>{session.title || session.conversation || "默认会话"}</strong><small>{session.origin} · {session.bot}</small></div><select value={session.persona_id || ""} disabled={pending === session.scope} onChange={(event) => void selectPersona(session, event.target.value)} aria-label="选择会话人设"><option value="">跟随默认人设</option>{snapshot.personas.map((persona) => <option key={persona.id} value={persona.id}>{persona.name}</option>)}</select><ChevronRight size={18} aria-hidden="true" /></article>)}
        {snapshot.sessions.length === 0 && <div className="empty-state">暂无会话记录</div>}
      </div>
    </section>
  );
}

function ProvidersView({ snapshot, onRefresh }: { snapshot: StudioSnapshot; onRefresh: () => void }) {
  const providers = snapshot.config.providers || [];
  const [selectedId, setSelectedId] = useState(String(providers[0]?.id || ""));
  const [draftJson, setDraftJson] = useState("");
  const [secretDraft, setSecretDraft] = useState<Record<string, { value: string; clear: boolean }>>({});
  const [busy, setBusy] = useState(false);
  const selected = providers.find((provider) => String(provider.id) === selectedId);

  function secretKeys(provider?: ProviderConfig): string[] {
    if (!provider) return [];
    return Object.keys(provider).filter((key) => {
      const lower = key.toLowerCase();
      return !key.endsWith("_configured") && (
        lower.includes("api_key") || lower === "apikey" || lower.includes("token") ||
        lower.includes("secret") || lower.includes("password") || lower.includes("authorization") ||
        lower.includes("cookie")
      );
    });
  }

  useEffect(() => {
    const next = providers.find((provider) => String(provider.id) === selectedId) || providers[0];
    const nextId = String(next?.id || "");
    setSelectedId(nextId);
    setDraftJson(next ? JSON.stringify(next, null, 2) : "");
    const nextSecrets: Record<string, { value: string; clear: boolean }> = {};
    secretKeys(next).forEach((key) => { nextSecrets[key] = { value: "", clear: false }; });
    setSecretDraft(nextSecrets);
  }, [selectedId, snapshot.configRevision]);

  function choose(provider: ProviderConfig) {
    setSelectedId(String(provider.id));
    setDraftJson(JSON.stringify(provider, null, 2));
    const nextSecrets: Record<string, { value: string; clear: boolean }> = {};
    secretKeys(provider).forEach((key) => { nextSecrets[key] = { value: "", clear: false }; });
    setSecretDraft(nextSecrets);
  }

  async function save() {
    setBusy(true);
    try {
      const provider = JSON.parse(draftJson) as Record<string, unknown>;
      if (!provider || typeof provider !== "object" || !provider.id) throw new Error("服务商 JSON 无效");
      const updates: Record<string, unknown> = {};
      Object.entries(secretDraft).forEach(([key, item]) => {
        if (item.clear) updates[key] = { clear: true };
        else if (item.value.trim()) {
          let value: unknown = item.value;
          if (item.value.trim().startsWith("[")) {
            try { value = JSON.parse(item.value); } catch { throw new Error(`${key} 的列表格式无效`); }
          }
          updates[key] = { value };
        }
      });
      await saveStudioProvider(provider, snapshot.configRevision, updates);
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "服务商保存失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace">
      <div className="workspace-heading">
        <div>
          <span className="section-kicker">PROVIDERS</span>
          <h1>服务商</h1>
        </div>
        <a className="secondary-action" href="../Settings/">
          旧版设置
          <ChevronRight size={16} aria-hidden="true" />
        </a>
      </div>
      <div className="provider-editor-layout">
        <div className="provider-list">
        {providers.map((provider) => (
          <button type="button" className={String(provider.id) === selectedId ? "provider-row active" : "provider-row"} key={provider.id} onClick={() => choose(provider)}>
            <span className="provider-mark" aria-hidden="true">
              {provider.id.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{provider.label || provider.id}</strong>
              <small>
                {provider.model || "未指定模型"} ·{" "}
                {provider.__template_key || provider.__type || "自定义"}
              </small>
            </div>
            <span className="status-dot">已配置</span>
          </button>
        ))}
        {providers.length === 0 && (
          <div className="empty-state">暂无服务商</div>
        )}
        </div>
        <div className="tool-panel provider-editor">
          {selected ? <>
            <div className="panel-heading"><h2>编辑模板：{selected.label || selected.id}</h2><button type="button" className="primary-action" disabled={busy} onClick={() => void save()}>{busy ? "保存中" : "保存服务商"}</button></div>
            <p className="capability-notice">普通字段使用 JSON 完整保存，未知字段不会被删除。敏感字段不会回显，只有填写替换值或勾选清空才会修改。</p>
            <label className="stack-field"><span>模板字段</span><textarea className="code-editor" rows={18} value={draftJson} onChange={(event) => setDraftJson(event.target.value)} spellCheck={false} /></label>
            {Object.keys(secretDraft).length > 0 && <div className="secret-editor"><h3>敏感字段</h3>{Object.entries(secretDraft).map(([key, item]) => <label className="stack-field" key={key}><span>{key}{selected[`${key}_configured`] ? " · 已配置" : ""}</span><input type={key.toLowerCase().includes("password") || key.toLowerCase().includes("token") || key.toLowerCase().includes("key") ? "password" : "text"} value={item.value} disabled={item.clear} placeholder="留空表示保持原值" onChange={(event) => setSecretDraft((current) => ({ ...current, [key]: { ...current[key], value: event.target.value } }))} /><span className="check-row"><input type="checkbox" checked={item.clear} onChange={(event) => setSecretDraft((current) => ({ ...current, [key]: { ...current[key], clear: event.target.checked, value: "" } }))} />明确清空</span></label>)}</div>}
          </> : <div className="empty-state">选择一个服务商开始编辑。</div>}
        </div>
      </div>
    </section>
  );
}

function SettingsView({ snapshot, onRefresh }: { snapshot: StudioSnapshot; onRefresh: () => void }) {
  const config = snapshot.config as Record<string, any>;
  const [features, setFeatures] = useState<Record<string, any>>(() => config.features || {});
  const [storage, setStorage] = useState<Record<string, any>>(() => config.storage || {});
  const [network, setNetwork] = useState<Record<string, any>>(() => config.network || {});
  const [reply, setReply] = useState<Record<string, any>>(() => config.reply_config || {});
  const [limits, setLimits] = useState(() => ({
    debounce_interval: Number(config.debounce_interval ?? 10),
    max_user_concurrency: Number(config.max_user_concurrency ?? 2),
    max_user_video_concurrency: Number(config.max_user_video_concurrency ?? 1),
  }));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFeatures(config.features || {});
    setStorage(config.storage || {});
    setNetwork(config.network || {});
    setReply(config.reply_config || {});
    setLimits({
      debounce_interval: Number(config.debounce_interval ?? 10),
      max_user_concurrency: Number(config.max_user_concurrency ?? 2),
      max_user_video_concurrency: Number(config.max_user_video_concurrency ?? 1),
    });
  }, [snapshot.config]);

  function featureEnabled(id: string) {
    return Boolean(features[id]?.enabled);
  }

  function setFeature(id: string, enabled: boolean) {
    setFeatures((current) => ({ ...current, [id]: { ...(current[id] || {}), enabled } }));
  }
  function chainFor(id: string): Array<{ provider_id: string; output?: string }> {
    const chain = features[id]?.chain;
    return Array.isArray(chain) ? chain.map((entry) => typeof entry === "string" ? { provider_id: entry } : entry) : [];
  }
  function setChain(id: string, chain: Array<{ provider_id: string; output?: string }>) {
    setFeatures((current) => ({ ...current, [id]: { ...current[id], chain } }));
  }

  async function save() {
    setSaving(true);
    try {
      const providerIds = new Set((config.providers || []).map((item: ProviderConfig) => item.id));
      for (const id of ["draw", "edit", "selfie", "video"]) {
        if (chainFor(id).some((entry) => !providerIds.has(entry.provider_id))) {
          throw new Error(`${id} 链路包含已删除的服务商，请先修复`);
        }
      }
      await saveStudioPreferences({
        revision: snapshot.configRevision, features, storage, network, reply_config: reply, ...limits,
      });
      onRefresh();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "设置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return <section className="workspace"><div className="workspace-heading"><div><span className="section-kicker">SETTINGS</span><h1>工作台设置</h1></div><a className="secondary-action" href="../Settings/">完整旧版设置<ChevronRight size={16} aria-hidden="true" /></a></div>
    <div className="settings-grid">
      <div className="tool-panel"><h2>功能</h2>
        {["draw", "edit", "selfie", "video"].map((id) => <div key={id}>
          <label className="check-row"><input type="checkbox" checked={featureEnabled(id)} onChange={(event) => setFeature(id, event.target.checked)} />{({ draw: "文生图", edit: "改图", selfie: "自拍", video: "视频" } as Record<string, string>)[id]}</label>
          <label className="check-row"><input type="checkbox" checked={features[id]?.llm_tool_enabled !== false} onChange={(event) => setFeatures((current) => ({ ...current, [id]: { ...current[id], llm_tool_enabled: event.target.checked } }))} />LLM 工具</label>
          <h3>{id} 服务商链</h3>
          {chainFor(id).map((entry, index, chain) => <div className="canvas-edge-row" key={index}>
            <span>{index === 0 ? "主" : "备"}</span>
            <select value={entry.provider_id} onChange={(event) => setChain(id, chain.map((item, position) => position === index ? { ...item, provider_id: event.target.value } : item))}>{(config.providers || []).map((provider: ProviderConfig) => <option key={provider.id} value={provider.id}>{provider.label || provider.id}</option>)}</select>
            <button type="button" className="icon-button" title="上移" disabled={index === 0} onClick={() => { const next = [...chain]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; setChain(id, next); }}><ArrowUp size={15} /><span className="sr-only">上移</span></button>
            <button type="button" className="icon-button" title="下移" disabled={index === chain.length - 1} onClick={() => { const next = [...chain]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; setChain(id, next); }}><ArrowDown size={15} /><span className="sr-only">下移</span></button>
            <button type="button" className="icon-button danger" title="移除服务商" onClick={() => setChain(id, chain.filter((_, position) => position !== index))}><X size={15} /><span className="sr-only">移除服务商</span></button>
          </div>)}
          <button type="button" className="secondary-action" disabled={chainFor(id).length >= (config.providers || []).length} onClick={() => { const next = (config.providers || []).find((provider: ProviderConfig) => !chainFor(id).some((entry) => entry.provider_id === provider.id)); if (next) setChain(id, [...chainFor(id), { provider_id: next.id }]); }}>添加服务商</button>
        </div>)}
        <label className="check-row"><input type="checkbox" checked={features.selfie?.use_edit_chain_when_empty !== false} onChange={(event) => setFeatures((current) => ({ ...current, selfie: { ...current.selfie, use_edit_chain_when_empty: event.target.checked } }))} />自拍链为空时使用改图链</label>
        <label className="stack-field"><span>意图识别模型</span><select value={features.intent_classifier?.provider_id || ""} onChange={(event) => setFeatures((current) => ({ ...current, intent_classifier: { ...current.intent_classifier, provider_id: event.target.value } }))}><option value="">未设置</option>{(config.astrbot_providers || []).map((model: { id: string }) => <option key={model.id} value={model.id}>{model.id}</option>)}</select></label>
      </div>
      <div className="tool-panel"><h2>缓存与并发</h2>
        {(["max_cached_images", "max_cached_videos"] as const).map((key) => <label className="stack-field" key={key}><span>{key === "max_cached_images" ? "最大缓存图片数" : "最大缓存视频数"}</span><input type="number" min={0} max={key === "max_cached_images" ? 100 : 500} value={storage[key] ?? (key === "max_cached_images" ? 100 : 20)} onChange={(event) => setStorage((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>)}
        {(["debounce_interval", "max_user_concurrency", "max_user_video_concurrency"] as const).map((key) => <label className="stack-field" key={key}><span>{({ debounce_interval: "防抖秒数", max_user_concurrency: "用户图片并发", max_user_video_concurrency: "用户视频并发" })[key]}</span><input type="number" min={key === "debounce_interval" ? 0 : 1} max={120} value={limits[key]} onChange={(event) => setLimits((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>)}
        <h2>网络</h2>
        <label className="check-row"><input type="checkbox" checked={Boolean(network.media_allow_private)} onChange={(event) => setNetwork((current) => ({ ...current, media_allow_private: event.target.checked }))} />允许私网媒体地址</label>
        {(["max_image_bytes", "max_video_bytes", "max_redirects", "dns_resolve_timeout_seconds"] as const).map((key) => <label className="stack-field" key={key}><span>{key}</span><input type="number" min={1} value={network[key] ?? ({ max_image_bytes: 52428800, max_video_bytes: 52428800, max_redirects: 5, dns_resolve_timeout_seconds: 2 })[key]} onChange={(event) => setNetwork((current) => ({ ...current, [key]: Number(event.target.value) }))} /></label>)}
        <h2>回复</h2>
        {(["draw_pending_message", "selfie_pending_message"] as const).map((key) => <label className="stack-field" key={key}><span>{key === "draw_pending_message" ? "绘图等待提示" : "自拍等待提示"}</span><input value={reply[key] || ""} onChange={(event) => setReply((current) => ({ ...current, [key]: event.target.value }))} /></label>)}
        <label className="check-row"><input type="checkbox" checked={Boolean(reply.verbose_report)} onChange={(event) => setReply((current) => ({ ...current, verbose_report: event.target.checked }))} />详细任务报告</label>
        <h2>Studio 入口</h2>
        <label className="check-row"><input type="checkbox" checked={features.studio?.enabled !== false} onChange={(event) => setFeatures((current) => ({ ...current, studio: { ...current.studio, enabled: event.target.checked } }))} />启用 Studio</label>
        <label className="stack-field"><span>默认页面</span><select value={features.studio?.default_entry || "create"} onChange={(event) => setFeatures((current) => ({ ...current, studio: { ...current.studio, default_entry: event.target.value } }))}><option value="create">创作</option><option value="settings">设置</option></select></label>
        <button type="button" className="primary-action" disabled={saving} onClick={() => void save()}>{saving ? "保存中" : "保存工作台设置"}</button>
      </div>
    </div>
  </section>;
}

export default function StudioApp() {
  const [route, setRoute] = useState<RouteId>("create");
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [activeScope, setActiveScope] = useState("");
  const activeScopeRef = useRef("");
  const refreshSequence = useRef(0);

  const refresh = useCallback(async (requestedScope = activeScopeRef.current) => {
    const sequence = ++refreshSequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await loadStudioSnapshot(requestedScope);
      if (sequence !== refreshSequence.current) return;
      setSnapshot(next);
      if (!window.location.hash && next.config.features?.studio?.default_entry === "settings") setRoute("settings");
      setActiveScope((current) => {
        const resolved = requestedScope && next.sessions.some((session) => session.scope === requestedScope)
          ? requestedScope
          : next.sessions.some((session) => session.scope === current)
            ? current
            : next.sessions[0]?.scope || "";
        activeScopeRef.current = resolved;
        return resolved;
      });
    } catch (reason) {
      if (sequence !== refreshSequence.current) return;
      setError(reason instanceof Error ? reason.message : "Studio 加载失败");
    } finally {
      if (sequence === refreshSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(readRoute());
      setMenuOpen(false);
    };
    onHashChange();
    window.addEventListener("hashchange", onHashChange);
    setDark(document.documentElement.dataset.theme === "dark");
    void refresh();
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [refresh]);

  function changeActiveScope(nextScope: string) {
    activeScopeRef.current = nextScope;
    setActiveScope(nextScope);
    void refresh(nextScope);
  }

  const activeRoute = useMemo(
    () => routes.find((item) => item.id === route) || routes[0],
    [route],
  );

  function toggleTheme() {
    const next = !dark;
    setDark(next);
    document.documentElement.dataset.theme = next ? "dark" : "light";
    localStorage.setItem("aiimg-studio-theme", next ? "dark" : "light");
  }

  return (
    <div className="studio-shell">
      <header className="studio-topbar">
        <button
          type="button"
          className="mobile-menu-button"
          onClick={() => setMenuOpen((value) => !value)}
          aria-label="打开导航"
        >
          {menuOpen ? <X size={21} /> : <ChevronRight size={21} />}
        </button>
        <a className="studio-brand" href="#/create">
          <img src="./logo.png" alt="" />
          <span>AI绘图站</span>
        </a>
        <span className="topbar-route">{activeRoute.label}</span>
        <div className="topbar-actions">
          {snapshot.sessions.length > 0 && (
            <select className="session-picker" aria-label="当前会话" value={activeScope} onChange={(event) => changeActiveScope(event.target.value)}>
              {snapshot.sessions.map((session) => (
                <option key={session.scope} value={session.scope}>
                  {session.title || session.conversation || "默认会话"}
                </option>
              ))}
            </select>
          )}
          <span className={"api-state " + (error ? "error" : "")}>
            {error ? (
              <AlertCircle size={15} aria-hidden="true" />
            ) : (
              <Wifi size={15} aria-hidden="true" />
            )}
            {error ? "连接异常" : "AstrBot"}
          </span>
          <button
            type="button"
            className="icon-button"
            onClick={toggleTheme}
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
            <span className="sr-only">切换主题</span>
          </button>
        </div>
      </header>

      <aside className={"studio-sidebar " + (menuOpen ? "open" : "")}>
        <nav aria-label="工作台导航">
          {routes.map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.id}
                href={routeHref(item.id)}
                className={route === item.id ? "active" : ""}
              >
                <Icon size={19} aria-hidden="true" />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <img src="./logo.png" alt="" />
          <div>
            <strong>AIIMG Studio</strong>
            <small>v4.12.0</small>
          </div>
        </div>
      </aside>

      <main className="studio-main">
        {loading && <div className="loading-bar" aria-label="正在加载" />}
        {error ? (
          <div className="error-banner">
            <AlertCircle size={20} aria-hidden="true" />
            <span>{error}</span>
            <button type="button" onClick={() => void refresh()}>
              重试
            </button>
          </div>
        ) : (
          snapshot.config.features?.studio?.enabled === false && route !== "settings" ? (
            <section className="workspace"><h1>Studio 已关闭</h1><a className="secondary-action" href="../Settings/">打开旧版设置</a><button type="button" className="secondary-action" onClick={() => setRoute("settings")}>工作台设置</button></section>
          ) : <>
            {route === "create" && <CreateView snapshot={snapshot} scope={activeScope} onScopeChange={changeActiveScope} onSubmitted={() => void refresh()} />}
            {route === "canvas" && <CanvasView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "assets" && <AssetsView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "tasks" && (
              <TasksView jobs={snapshot.jobs} tasks={snapshot.tasks} onRefresh={refresh} />
            )}
            {route === "history" && <HistoryView snapshot={snapshot} />}
            {route === "personas" && <PersonasView snapshot={snapshot} onRefresh={refresh} />}
            {route === "prompts" && <PromptsView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "gif" && <GifView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "design" && <DesignView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "agent" && <AgentView snapshot={snapshot} scope={activeScope} onRefresh={refresh} />}
            {route === "providers" && <ProvidersView snapshot={snapshot} onRefresh={() => void refresh()} />}
            {route === "settings" && <SettingsView snapshot={snapshot} onRefresh={refresh} />}
          </>
        )}
      </main>
    </div>
  );
}
