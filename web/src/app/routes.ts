import {
  Bot,
  Boxes,
  Brush,
  FolderOpen,
  GalleryHorizontalEnd,
  History,
  ImagePlus,
  ListChecks,
  Settings2,
  Sparkles,
  Users,
} from "lucide-react";

export const routes = [
  { id: "create", label: "创作", wordmark: "Create", icon: ImagePlus },
  { id: "canvas", label: "画布", wordmark: "Canvas", icon: Boxes },
  { id: "assets", label: "素材", wordmark: "Assets", icon: FolderOpen },
  { id: "tasks", label: "任务", wordmark: "Tasks", icon: ListChecks },
  { id: "history", label: "历史", wordmark: "History", icon: History },
  { id: "personas", label: "人设", wordmark: "Personas", icon: Users },
  { id: "prompts", label: "提示词", wordmark: "Prompts", icon: Sparkles },
  { id: "gif", label: "GIF", wordmark: "GIF", icon: GalleryHorizontalEnd },
  { id: "design", label: "设计", wordmark: "Design", icon: Brush },
  { id: "agent", label: "Agent", wordmark: "Agent", icon: Bot },
  { id: "providers", label: "服务商", wordmark: "Providers", icon: Settings2 },
  { id: "settings", label: "设置", wordmark: "Settings", icon: Settings2 },
] as const;

export type RouteId = (typeof routes)[number]["id"];

export function readRoute(): RouteId {
  const value = window.location.hash.replace(/^#\/?/, "").split("/")[0];
  return routes.some((route) => route.id === value)
    ? (value as RouteId)
    : "create";
}

export function routeHref(route: RouteId): string {
  return "#/" + route;
}
