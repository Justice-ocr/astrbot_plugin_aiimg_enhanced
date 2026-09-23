export interface ProviderConfig {
  id: string;
  label?: string;
  model?: string;
  __template_key?: string;
  __type?: string;
  [key: string]: unknown;
}

export interface StudioConfig {
  astrbot_providers?: Array<{ id: string; model: string }>;
  providers?: ProviderConfig[];
  features?: Record<string, {
    enabled?: boolean;
    presets?: unknown[];
    chain?: Array<string | { provider_id?: string }>;
    default_entry?: "create" | "settings";
    llm_tool_enabled?: boolean;
    use_edit_chain_when_empty?: boolean;
    provider_id?: string;
  }>;
  persona_config?: {
    active_persona_id?: string;
    profiles?: Array<{
      id: string;
      persona_name?: string;
      persona_ref_image?: string[];
    }>;
  };
}

export type CapabilityStatus = "supported" | "unsupported" | "unknown";

export interface ProviderCapability {
  provider_id: string;
  label: string;
  model: string;
  template_key: string;
  source: "template" | "template+explicit";
  protocol: {
    id: string;
    last_verified: string;
  };
  operations: Record<string, CapabilityStatus>;
  references: {
    status: CapabilityStatus;
    active_mode?: string;
    modes: Array<{
      id: string;
      label: string;
      status: CapabilityStatus;
      min_images: number;
      max_images: number;
      accepted_media_types: string[];
      resolutions?: string[];
      duration?: {
        minimum: number;
        maximum: number;
        unit: string;
      };
    }>;
  };
  parameters: {
    duration?: {
      status: CapabilityStatus;
      minimum?: number;
      maximum?: number;
      default?: number;
      unit?: string;
    };
    aspect_ratios?: EnumParameter;
    sizes?: EnumParameter;
    resolutions?: EnumParameter;
  };
  streaming: Record<string, CapabilityStatus>;
  cancellation: {
    local: CapabilityStatus;
    upstream: CapabilityStatus;
  };
}

export interface EnumParameter {
  status: CapabilityStatus;
  values: string[];
  default: string;
}

export interface ManagedTask {
  id: string;
  state: string;
  kind?: string;
  prompt?: string;
  created_at: number;
  generated?: number;
  sent?: number;
  persona?: string;
  conversation?: string;
  sender?: string;
  error?: string;
}

export interface StudioJob {
  id: string;
  scope: string;
  kind: string;
  mode: string;
  prompt: string;
  state: string;
  created_at: number;
  updated_at: number;
  finished_at?: number | null;
  request?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  provider_id?: string;
  upstream_task_id?: string;
  accepted_state?: string;
  delivery_state?: string;
  plan_index?: number;
}

export interface StudioAsset {
  asset_id: string;
  id?: string;
  scope?: string;
  media_type: string;
  filename: string;
  byte_size?: number;
  created_at: number;
  pinned?: boolean;
  source?: string;
  history_id?: number;
  available?: boolean;
  prompt?: string;
  conversation?: string;
  conversation_title?: string;
  metadata?: Record<string, unknown>;
}

export interface StudioProject {
  id: string;
  scope: string;
  name: string;
  kind: "canvas" | "gif" | "design" | "web_replica" | string;
  revision: number;
  document: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

export interface HistoryItem {
  id: number;
  sequence: number;
  created_at: number;
  mode?: string;
  provider?: string;
  prompt?: string;
  conversation?: string;
  conversation_title?: string;
  available?: boolean;
}

export interface SessionPersona {
  scope: string;
  persona_scope?: string;
  origin: string;
  bot: string;
  conversation: string;
  title?: string;
  persona_id?: string;
  effective_name?: string;
}

export interface PersonaChoice {
  id: string;
  name: string;
}

export type PersonaReferenceRole = "identity" | "clothing" | "pose" | "scene";

export interface PersonaProfile {
  id: string;
  name: string;
  base_prompt: string;
  ref_images: string[];
  ref_roles: Record<string, PersonaReferenceRole>;
  active?: boolean;
}

export interface StudioSnapshot {
  config: StudioConfig;
  configRevision?: string;
  capabilities: ProviderCapability[];
  jobs: StudioJob[];
  tasks: ManagedTask[];
  history: HistoryItem[];
  historyTotal: number;
  assets: StudioAsset[];
  projects: StudioProject[];
  sessions: SessionPersona[];
  personas: PersonaChoice[];
  personaProfiles: PersonaProfile[];
}
