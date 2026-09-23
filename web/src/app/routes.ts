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
  { id: "create", label: "创作", icon: ImagePlus },
  { id: "canvas", label: "画布", icon: Boxes },
  { id: "assets", label: "素材", icon: FolderOpen },
  { id: "tasks", label: "任务", icon: ListChecks },
  { id: "history", label: "历史", icon: History },
  { id: "personas", label: "人设", icon: Users },
  { id: "prompts", label: "提示词", icon: Sparkles },
  { id: "gif", label: "GIF", icon: GalleryHorizontalEnd },
  { id: "design", label: "设计", icon: Brush },
  { id: "agent", label: "Agent", icon: Bot },
  { id: "providers", label: "服务商", icon: Settings2 },
  { id: "settings", label: "设置", icon: Settings2 },
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
