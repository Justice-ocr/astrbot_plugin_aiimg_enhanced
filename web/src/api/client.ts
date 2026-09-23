import type { PersonaProfile, ProviderConfig, StudioAsset, StudioJob, StudioProject, StudioSnapshot } from "./contracts";

interface AstrBotPageBridge {
  ready(): Promise<unknown>;
  apiGet(name: string, params?: Record<string, string>): Promise<any>;
  apiPost(name: string, payload?: unknown): Promise<any>;
  download(name: string, params?: Record<string, string>, filename?: string): Promise<any>;
}

declare global {
  interface Window {
    AstrBotPluginPage?: AstrBotPageBridge;
  }
}

function getBridge(): AstrBotPageBridge {
  const bridge = window.AstrBotPluginPage;
  if (!bridge) {
    throw new Error("请从 AstrBot 插件页面打开 Studio");
  }
  return bridge;
}

async function requireSuccess<T>(promise: Promise<any>): Promise<T> {
  const result = await promise;
  if (!result?.success) {
    throw new Error(result?.error || "AstrBot API 请求失败");
  }
  return result as T;
}

export async function loadStudioSnapshot(requestedScope = ""): Promise<StudioSnapshot> {
  const bridge = getBridge();
  await bridge.ready();
  const sessionResult = await requireSuccess<any>(bridge.apiGet("get_session_personas"));
  const availableScopes = (sessionResult.items || []).map((item: any) => String(item.scope || ""));
  const scope = requestedScope && availableScopes.includes(requestedScope)
    ? requestedScope
    : String(availableScopes[0] || "");
  const scoped: Record<string, string> = scope ? { scope } : {};
  const [configResult, capabilityResult, taskResult, jobResult, historyResult, assetResult, projectResult, personaResult] =
    await Promise.all([
      requireSuccess<any>(bridge.apiGet("get_studio_config")),
      requireSuccess<any>(bridge.apiGet("get_provider_capabilities")),
      requireSuccess<any>(bridge.apiGet("get_tasks")),
      requireSuccess<any>(bridge.apiGet("get_jobs", scoped)),
      requireSuccess<any>(bridge.apiGet("get_history", { page: "1", query: "" })),
      requireSuccess<any>(bridge.apiGet("get_assets", { ...scoped, limit: "80", query: "" })),
      requireSuccess<any>(bridge.apiGet("get_projects", { ...scoped, limit: "80" })),
      requireSuccess<any>(bridge.apiGet("get_studio_personas")),
    ]);

  return {
    config: configResult.config || {},
    configRevision: String(configResult.revision || ""),
    capabilities: capabilityResult.items || [],
    jobs: jobResult.items || [],
    tasks: taskResult.items || [],
    history: historyResult.items || [],
    historyTotal: Number(historyResult.total || 0),
    assets: assetResult.items || [],
    projects: projectResult.items || [],
    sessions: sessionResult.items || [],
    personas: sessionResult.personas || [],
    personaProfiles: (personaResult.profiles || []) as PersonaProfile[],
  };
}

export async function saveStudioPersona(profile: Record<string, unknown>, originalId = ""): Promise<PersonaProfile> {
  const result = await requireSuccess<any>(getBridge().apiPost("save_studio_persona", {
    profile,
    original_id: originalId,
  }));
  return result.profile as PersonaProfile;
}

export async function deleteStudioPersona(id: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("delete_studio_persona", { id }));
}

export async function switchStudioPersona(id: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("switch_persona", { id }));
}

export async function uploadStudioPersonaReference(file: File): Promise<string> {
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("人设参考图读取失败"));
    reader.readAsDataURL(file);
  });
  const result = await requireSuccess<any>(getBridge().apiPost("upload_studio_persona_ref", {
    filename: file.name,
    data,
  }));
  return String(result.path || "");
}

export async function loadPersonaReferencePreview(path: string): Promise<string> {
  if (/^https?:\/\//.test(path)) return path;
  const result = await requireSuccess<any>(getBridge().apiGet("get_image_b64", { path }));
  return String(result.image_data || result.data || "");
}

export async function createStudioJob(payload: Record<string, unknown>): Promise<StudioJob> {
  const result = await requireSuccess<any>(getBridge().apiPost("create_job", payload));
  return result.item as StudioJob;
}

export async function loadStudioJob(id: string, scope: string): Promise<StudioJob> {
  const result = await requireSuccess<{ item: StudioJob }>(getBridge().apiGet("get_job", { id, scope }));
  return result.item;
}

export async function loadProjectJobs(projectId: string, scope: string): Promise<StudioJob[]> {
  const result = await requireSuccess<{ items: StudioJob[] }>(
    getBridge().apiGet("get_jobs", { project_id: projectId, scope, limit: "500" }),
  );
  return result.items;
}

export async function createStudioPlan(payload: Record<string, unknown>): Promise<StudioJob[]> {
  const result = await requireSuccess<any>(getBridge().apiPost("create_plan", payload));
  return (result.items || []) as StudioJob[];
}

export async function draftAgent(payload: Record<string, unknown>): Promise<StudioProject> {
  const result = await requireSuccess<{ item: StudioProject }>(getBridge().apiPost("draft_agent", payload));
  return result.item;
}

export async function reviewAgent(projectId: string, scope: string): Promise<{
  tasks: Array<Record<string, unknown>>; count: number; cost: string;
  confirmation_token: string; confirmation_expires: number;
}> {
  const result = await requireSuccess<{ plan: {
    tasks: Array<Record<string, unknown>>; count: number; cost: string;
    confirmation_token: string; confirmation_expires: number;
  } }>(getBridge().apiPost("submit_agent", { project_id: projectId, scope, preview: true }));
  return result.plan;
}

export async function executeAgent(payload: Record<string, unknown>): Promise<StudioJob[]> {
  const result = await requireSuccess<{ items: StudioJob[] }>(getBridge().apiPost("submit_agent", payload));
  return result.items;
}

export async function previewStudioPlan(payload: Record<string, unknown>): Promise<{
  confirmation_token: string; confirmation_expires: number;
}> {
  const result = await requireSuccess<any>(getBridge().apiPost("create_plan", { ...payload, preview: true }));
  return result.plan;
}

export async function transformStudioPrompt(payload: Record<string, unknown>): Promise<string> {
  const result = await requireSuccess<{ prompt: string }>(getBridge().apiPost("transform_prompt", payload));
  return result.prompt;
}

export async function generateWebReplica(payload: Record<string, unknown>): Promise<Array<{ path: string; content: string }>> {
  const result = await requireSuccess<{ files: Array<{ path: string; content: string }> }>(
    getBridge().apiPost("generate_web_replica", payload),
  );
  return result.files;
}

export async function cancelStudioJob(id: string, scope?: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("cancel_job", { id, scope }));
}

export async function resumeStudioJob(id: string, scope: string): Promise<StudioJob> {
  const result = await requireSuccess<any>(getBridge().apiPost("resume_job", { id, scope }));
  return result.item as StudioJob;
}

export async function uploadStudioReference(file: File, scope: string): Promise<string> {
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("参考图读取失败"));
    reader.readAsDataURL(file);
  });
  const result = await requireSuccess<any>(getBridge().apiPost("upload_asset_b64", {
    scope,
    filename: file.name,
    data,
  }));
  return String(result.asset_id || result.item?.asset_id || "");
}

export async function uploadStudioAsset(file: File, scope: string): Promise<StudioAsset> {
  const data = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("素材读取失败"));
    reader.readAsDataURL(file);
  });
  const result = await requireSuccess<any>(getBridge().apiPost("upload_asset_b64", {
    scope,
    filename: file.name,
    data,
  }));
  return result.item as StudioAsset;
}

export function studioAssetUrl(assetId: string, scope?: string, download = false): string {
  const query = new URLSearchParams({ id: assetId });
  if (scope) query.set("scope", scope);
  if (download) query.set("download", "1");
  return `get_asset_content?${query.toString()}`;
}

export async function loadAssetPreview(assetId: string, scope?: string): Promise<string> {
  const result = await requireSuccess<any>(getBridge().apiGet("get_asset_b64", {
    id: assetId,
    ...(scope ? { scope } : {}),
  }));
  return String(result.image_data || "");
}

export async function pinStudioAsset(id: string, pinned: boolean, scope?: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("pin_asset", { id, pinned, scope }));
}

export async function preserveHistoryAsset(id: number, scope: string): Promise<StudioAsset> {
  const result = await requireSuccess<{ item: StudioAsset }>(getBridge().apiPost("preserve_history_asset", { id, scope }));
  return result.item;
}

export async function deleteStudioAsset(id: string, scope?: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("delete_asset", { id, scope }));
}

export async function downloadStudioAsset(id: string, filename: string, scope?: string): Promise<void> {
  const bridge = getBridge();
  if (typeof bridge.download !== "function") {
    throw new Error("当前 AstrBot 页面桥接不支持下载");
  }
  await bridge.download("get_asset_content", { id, download: "1", ...(scope ? { scope } : {}) }, filename);
}

export async function saveStudioProject(payload: Record<string, unknown>): Promise<StudioProject> {
  const result = await requireSuccess<any>(getBridge().apiPost("save_project", payload));
  return result.item as StudioProject;
}

export async function loadStudioProject(id: string, scope: string): Promise<StudioProject> {
  const result = await requireSuccess<{ item: StudioProject }>(getBridge().apiGet("get_project", { id, scope }));
  return result.item;
}

export async function exportWebProject(id: string, scope: string): Promise<void> {
  const bridge = getBridge();
  if (typeof bridge.download !== "function") throw new Error("当前 AstrBot 页面桥接不支持下载");
  await bridge.download("export_web_project", { id, scope }, `studio-web-${id}.zip`);
}

export async function exportMediaProject(id: string, scope: string): Promise<void> {
  const bridge = getBridge();
  if (typeof bridge.download !== "function") throw new Error("当前 AstrBot 页面桥接不支持下载");
  await bridge.download("export_media_project", { id, scope }, `studio-project-${id}.zip`);
}

export async function loadProjectVersions(id: string, scope: string): Promise<StudioProject[]> {
  const result = await requireSuccess<{ items: StudioProject[] }>(getBridge().apiGet("get_project_versions", { id, scope }));
  return result.items;
}

export async function saveStudioPreferences(payload: Record<string, unknown>): Promise<string> {
  const result = await requireSuccess<any>(getBridge().apiPost("save_studio_preferences", payload));
  return String(result.revision || "");
}

export async function saveStudioPresets(feature: string, presets: string[], revision: string): Promise<string> {
  const result = await requireSuccess<{ revision: string }>(getBridge().apiPost("save_studio_presets", {
    feature, presets, revision,
  }));
  return result.revision;
}

export async function saveStudioProvider(
  provider: Record<string, unknown>,
  revision = "",
  secretUpdates: Record<string, unknown> = {},
  create = false,
  originalId = String(provider.id || ""),
): Promise<ProviderConfig> {
  const result = await requireSuccess<any>(getBridge().apiPost("save_studio_provider", {
    provider,
    revision,
    secret_updates: secretUpdates,
    create,
    original_id: originalId,
  }));
  return result.provider as ProviderConfig;
}

export async function deleteStudioProvider(providerId: string, revision: string): Promise<string> {
  const result = await requireSuccess<{ revision: string }>(getBridge().apiPost("delete_studio_provider", {
    provider_id: providerId,
    revision,
  }));
  return result.revision;
}

export async function deleteStudioProject(id: string, revision?: number): Promise<void> {
  await requireSuccess(getBridge().apiPost("delete_project", { id, revision }));
}

export async function createStudioGif(payload: Record<string, unknown>): Promise<StudioAsset> {
  const result = await requireSuccess<any>(getBridge().apiPost("create_gif", payload));
  return result.item as StudioAsset;
}

export async function sliceStudioAsset(payload: Record<string, unknown>): Promise<StudioAsset[]> {
  const result = await requireSuccess<{ items: StudioAsset[] }>(getBridge().apiPost("slice_asset", payload));
  return result.items;
}

export async function downloadStudioJobMedia(id: string, scope?: string): Promise<void> {
  const bridge = getBridge();
  if (typeof bridge.download !== "function") {
    throw new Error("当前 AstrBot 页面桥接不支持下载");
  }
  await bridge.download("download_job_media", { id, ...(scope ? { scope } : {}) }, `aiimg-studio-${id}.mp4`);
}

export async function loadHistoryPreview(id: number, scope?: string): Promise<string> {
  const result = await requireSuccess<any>(
    getBridge().apiGet("get_history_image", {
      id: String(id),
      original: "0",
      ...(scope ? { scope } : {}),
    }),
  );
  return String(result.image_data || "");
}

export async function cancelTask(id: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("cancel_task", { id }));
}

export async function setSessionPersona(scope: string, personaId: string): Promise<void> {
  await requireSuccess(getBridge().apiPost("set_session_persona", {
    persona_scope: scope,
    persona_id: personaId,
  }));
}
