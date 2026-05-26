"""
Gitee AI 图像生成插件

功能:
- 文生图 (z-image-turbo)
- 图生图/改图 (Gemini / Gitee 千问，可切换)
- Bot 自拍（参考照）：上传参考人像后用改图模型生成自拍
- 视频生成 (Grok imagine, 参考图 + 提示词)
- 预设提示词
- 智能降级
"""

import asyncio
import base64
import io
import json
import math
import mimetypes
import os
import pathlib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mcp

from quart import jsonify, request, send_file

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import (
    At,
    AtAll,
    File,
    Image,
    Plain,
    Reply,
    Video,
)
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

from .core.batch_executor import BatchRunResult, run_batch
from .core.debouncer import Debouncer
from .core.draw_service import ImageDrawService
from .core.edit_router import EditRouter
from .core.emoji_feedback import mark_failed, mark_processing, mark_success
from .core.image_task_parser import (
    ImageTaskSpec,
    ParsedImageRequest,
    parse_image_request,
)
from .core.llm_batch_planner import (
    PlannedPromptItem,
    build_batch_planning_prompt,
    parse_planned_prompt_items,
    validate_planned_prompt_items,
)
from .core.gitee_sizes import (
    GITEE_SUPPORTED_RATIOS,
    normalize_size_text,
    resolve_ratio_size,
)
from .core.image_format import decode_base64_image_payload, guess_image_mime_and_ext
from .core.image_manager import ImageManager
from .core.nanobanana import NanoBananaService
from .core.persona_manager import PersonaManager, PersonaProfile
from .core.provider_registry import ProviderRegistry
from .core.ref_store import ReferenceStore
from .core.utils import close_session, get_images_from_event
from .core.video_manager import VideoManager

def _deep_merge(base: dict, override: dict) -> dict:
    """递归深度合并两个字典，override 的值覆盖 base，保留 base 中未被覆盖的字段。"""
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result

# ── 默认回复文案 ────────────────────────────────────────────────────────────
_DEFAULT_DRAW_PENDING     = "🎨 收到灵感，正在绘制..."
_DEFAULT_EDIT_PENDING     = "🖌️ 正在处理图片..."
_DEFAULT_SELFIE_PENDING   = "📸 正在为「{persona_name}」生成自拍，请稍候..."
_DEFAULT_VIDEO_PENDING    = "🎬 视频任务已提交后台渲染..."
_DEFAULT_DRAW_ERROR       = "💥 绘制失败: {error}"
_DEFAULT_SELFIE_ERROR     = "💥 自拍生成失败: {error}"

_BATCH_COMMAND_PATTERN = re.compile(r"[/!！.。．]批量(?:\s*\d+|\d+)")
_async_pause = asyncio.sleep

@dataclass(slots=True)
class SendImageResult:
    ok: bool
    reason: str = ""
    cached_path: Path | None = None
    used_fallback: bool = False
    last_error: str = ""

    def __bool__(self) -> bool:
        return self.ok

@dataclass(slots=True)
class ExecutedImageTask:
    spec: ImageTaskSpec
    image_path: Path
    task_meta: dict[str, Any]

from .handlers.cmd_draw import DrawCommandsMixin
from .handlers.cmd_edit import EditCommandsMixin
from .handlers.cmd_selfie import SelfieCommandsMixin
from .handlers.cmd_video import VideoCommandsMixin
from .handlers.cmd_misc import MiscCommandsMixin
from .handlers.llm_tools import LLMToolsMixin
from .handlers.pages_api import PagesAPIMixin


class GiteeAIImagePlugin(
    DrawCommandsMixin,
    EditCommandsMixin,
    SelfieCommandsMixin,
    VideoCommandsMixin,
    MiscCommandsMixin,
    LLMToolsMixin,
    PagesAPIMixin,
    Star,
):
    """Gitee AI 图像生成插件"""

    # Gitee AI 支持的图片比例
    SUPPORTED_RATIOS: dict[str, list[str]] = GITEE_SUPPORTED_RATIOS
    IMAGE_AS_FILE_THRESHOLD_BYTES: int = 20 * 1024 * 1024

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_dir = StarTools.get_data_dir("astrbot_plugin_aiimg_enhanced")
        self._last_image_by_user: dict[str, Path] = {}
        self._last_image_task_meta_cache: dict[str, dict[str, Any]] = {}
        # 持久化：AstrBot原生config对象（可能有save_config方法）
        self._native_config = config if hasattr(config, "save_config") else None
        # 持久化：自管理的JSON文件路径（兜底）
        self._persist_config_path = str(
            pathlib.Path(self.data_dir) / "aiimg_persist_config.json"
        )

        self._register_pages_web_api()

    async def _call_native_poke(self, event: AstrMessageEvent, target_id: str) -> bool:
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return False

        user_id: int | str = int(target_id) if target_id.isdigit() else target_id
        try:
            await bot.call_action("friend_poke", user_id=user_id)
            return True
        except Exception as exc:
            logger.warning(
                "[GiteeAIImagePlugin] friend_poke failed: target=%s err=%s",
                target_id,
                exc,
            )

        try:
            await bot.call_action("send_poke", user_id=user_id)
            return True
        except Exception as exc:
            logger.warning(
                "[GiteeAIImagePlugin] send_poke failed: target=%s err=%s",
                target_id,
                exc,
            )
            return False

    async def _signal_llm_tool_failure(self, event: AstrMessageEvent) -> None:
        if event.is_private_chat():
            target_id = str(event.get_sender_id() or "").strip()
            if target_id:
                if await self._call_native_poke(event, target_id):
                    return
        await mark_failed(event)

    @staticmethod
    def _llm_tool_text_result(message: str) -> mcp.types.CallToolResult:
        text = str(message or "").strip()
        if not text:
            text = "The tool completed without additional details."
        return mcp.types.CallToolResult(
            content=[mcp.types.TextContent(type="text", text=text)]
        )

    @staticmethod
    def _summarize_status_text(
        value: Exception | str | None,
        *,
        fallback: str,
        limit: int = 180,
    ) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            return fallback
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3].rstrip()}..."

    @staticmethod
    def _truncate_text(value: Any, *, limit: int = 320) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3].rstrip()}..."

    @staticmethod
    def _get_event_conversation_id(event: AstrMessageEvent) -> str:
        provider_request = event.get_extra("provider_request")
        conversation = getattr(provider_request, "conversation", None)
        return str(getattr(conversation, "cid", "") or "").strip()

    @staticmethod
    def _get_event_self_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_self_id() or "").strip()
        except Exception:
            return ""

    def _image_task_store_key(
        self,
        event: AstrMessageEvent,
        *,
        conversation_id: str = "",
    ) -> str:
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip() or "unknown"
        self_id = self._get_event_self_id(event) or "unknown_bot"
        sender_id = str(event.get_sender_id() or "").strip() or "unknown"
        conversation_scope = (
            str(conversation_id or "").strip()
            or self._get_event_conversation_id(event)
            or "default"
        )
        return f"last_image_task::{umo}::{self_id}::{sender_id}::{conversation_scope}"

    async def _resolve_image_task_store_key(self, event: AstrMessageEvent) -> str:
        conversation_id = self._get_event_conversation_id(event)
        if not conversation_id:
            conversation = await self._resolve_plugin_conversation(event)
            conversation_id = str(getattr(conversation, "cid", "") or "").strip()
        return self._image_task_store_key(event, conversation_id=conversation_id)

    @staticmethod
    def _normalize_image_task_meta(meta: Any) -> dict[str, Any] | None:
        if not isinstance(meta, dict):
            return None
        mode = str(meta.get("mode") or "").strip()
        if not mode:
            return None
        try:
            reference_count = int(meta.get("reference_count") or 0)
            extra_reference_count = int(meta.get("extra_reference_count") or 0)
            created_at = float(meta.get("created_at") or time.time())
        except (TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "[GiteeAIImagePlugin] discard malformed last-image-task meta: %s",
                exc,
            )
            return None
        if (
            reference_count < 0
            or extra_reference_count < 0
            or not math.isfinite(created_at)
            or created_at < 0
        ):
            logger.warning(
                "[GiteeAIImagePlugin] discard invalid last-image-task meta values: %s",
                meta,
            )
            return None
        normalized = {
            "mode": mode,
            "user_prompt": str(meta.get("user_prompt") or "").strip(),
            "effective_user_prompt": str(meta.get("effective_user_prompt") or "").strip(),
            "effective_prompt": str(meta.get("effective_prompt") or "").strip(),
            "reference_source": str(meta.get("reference_source") or "").strip(),
            "reference_count": reference_count,
            "extra_reference_count": extra_reference_count,
            "continue_with": str(meta.get("continue_with") or mode).strip() or mode,
            "follow_up": bool(meta.get("follow_up", False)),
            "backend": str(meta.get("backend") or "").strip(),
            "created_at": created_at,
        }
        return normalized

    async def _save_last_image_task_meta(
        self, event: AstrMessageEvent, meta: dict[str, Any]
    ) -> None:
        normalized = self._normalize_image_task_meta(meta)
        if normalized is None:
            return

        store_key = await self._resolve_image_task_store_key(event)
        self._last_image_task_meta_cache[store_key] = normalized

        try:
            await self.put_kv_data(store_key, normalized)
        except Exception as exc:
            logger.debug(
                "[GiteeAIImagePlugin] skip persistent last-image-task save: %s",
                exc,
            )

    async def _load_last_image_task_meta(
        self, event: AstrMessageEvent
    ) -> dict[str, Any] | None:
        store_key = await self._resolve_image_task_store_key(event)
        cached_raw = self._last_image_task_meta_cache.get(store_key)
        cached = self._normalize_image_task_meta(cached_raw)
        if cached is not None:
            return cached
        if cached_raw is not None:
            self._last_image_task_meta_cache.pop(store_key, None)

        try:
            stored = await self.get_kv_data(store_key, None)
        except Exception as exc:
            logger.debug(
                "[GiteeAIImagePlugin] skip persistent last-image-task load: %s",
                exc,
            )
            return None

        normalized = self._normalize_image_task_meta(stored)
        if normalized is not None:
            self._last_image_task_meta_cache[store_key] = normalized
            return normalized
        if stored is not None:
            try:
                await self.delete_kv_data(store_key)
            except Exception as exc:
                logger.debug(
                    "[GiteeAIImagePlugin] skip cleanup malformed last-image-task meta: %s",
                    exc,
                )
        return None

    @staticmethod
    def _looks_like_image_follow_up(prompt: str) -> bool:
        text = str(prompt or "").strip()
        if not text:
            return False
        lowered = text.lower()
        keywords = (
            "不满意",
            "不太满意",
            "重新",
            "重来",
            "再来",
            "再拍",
            "换个",
            "换成",
            "换一下",
            "改一下",
            "改改",
            "调整",
            "重拍",
            "再生成",
            "重新拍",
            "重新来",
            "pose",
            "again",
            "redo",
            "adjust",
            "change",
        )
        return any(keyword in text or keyword in lowered for keyword in keywords)

    async def _match_selfie_follow_up(
        self, event: AstrMessageEvent, prompt: str
    ) -> dict[str, Any] | None:
        if self._is_auto_selfie_prompt(prompt):
            return None
        if not self._looks_like_image_follow_up(prompt):
            return None

        last_meta = await self._load_last_image_task_meta(event)
        if last_meta is None:
            return None
        if str(last_meta.get("continue_with") or "") != "selfie_ref":
            return None

        created_at = float(last_meta.get("created_at") or 0)
        if created_at > 0 and time.time() - created_at > 1800:
            return None

        ref_paths, ref_source = await self._get_selfie_reference_paths(event)
        if not ref_paths:
            return None

        meta = dict(last_meta)
        meta["reference_source"] = ref_source
        meta["reference_count"] = len(ref_paths)
        return meta

    def _build_selfie_follow_up_prompt(
        self, prompt: str, last_meta: dict[str, Any] | None
    ) -> str:
        current_prompt = str(prompt or "").strip()
        if last_meta is None:
            return current_prompt

        previous_prompt = (
            str(last_meta.get("effective_user_prompt") or "").strip()
            or str(last_meta.get("user_prompt") or "").strip()
        )
        if not previous_prompt:
            return current_prompt
        if not current_prompt:
            return f"延续上一张自拍要求：{previous_prompt}"
        return f"延续上一张自拍要求：{previous_prompt}；本次新增要求：{current_prompt}"

    def _build_image_task_meta(
        self,
        *,
        mode: str,
        user_prompt: str,
        effective_prompt: str,
        effective_user_prompt: str | None = None,
        reference_source: str = "",
        reference_count: int = 0,
        extra_reference_count: int = 0,
        continue_with: str | None = None,
        follow_up: bool = False,
        backend: str | None = None,
    ) -> dict[str, Any]:
        return {
            "mode": str(mode or "").strip(),
            "user_prompt": str(user_prompt or "").strip(),
            "effective_user_prompt": str(
                effective_user_prompt if effective_user_prompt is not None else user_prompt
            ).strip(),
            "effective_prompt": str(effective_prompt or "").strip(),
            "reference_source": str(reference_source or "").strip(),
            "reference_count": max(0, int(reference_count or 0)),
            "extra_reference_count": max(0, int(extra_reference_count or 0)),
            "continue_with": str(continue_with or mode or "").strip() or str(mode or "").strip(),
            "follow_up": bool(follow_up),
            "backend": str(backend or "").strip(),
            "created_at": time.time(),
        }

    def _build_image_task_completion_result(
        self, task_meta: dict[str, Any]
    ) -> mcp.types.CallToolResult:
        mode = str(task_meta.get("mode") or "image").strip() or "image"
        summary = {
            "status": "completed",
            "mode": mode,
            "continue_with": str(task_meta.get("continue_with") or mode).strip() or mode,
            "user_prompt": self._truncate_text(task_meta.get("user_prompt"), limit=180),
            "effective_prompt": self._truncate_text(
                task_meta.get("effective_prompt"), limit=260
            ),
            "reference_source": str(task_meta.get("reference_source") or "").strip(),
            "reference_count": int(task_meta.get("reference_count") or 0),
            "extra_reference_count": int(task_meta.get("extra_reference_count") or 0),
            "follow_up": bool(task_meta.get("follow_up", False)),
        }
        if task_meta.get("backend"):
            summary["backend"] = str(task_meta.get("backend"))

        hint = (
            "If the user asks to redo or adjust this selfie, continue with selfie_ref and reuse the same reference images unless the user explicitly changes them."
            if summary["continue_with"] == "selfie_ref"
            else "If the user asks for changes, continue from this completed image task instead of guessing a brand-new request."
        )
        return self._llm_tool_text_result(
            "The image has already been generated and sent to the user. Do not send another confirmation message to the user. "
            f"Store this task summary for follow-ups: {json.dumps(summary, ensure_ascii=False)} "
            + hint
        )

    async def _resolve_plugin_conversation(self, event: AstrMessageEvent) -> Any | None:
        provider_request = event.get_extra("provider_request")
        conversation = getattr(provider_request, "conversation", None)
        if conversation is not None:
            return conversation

        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return None

        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            return None

        try:
            conversation_id = await conv_mgr.get_curr_conversation_id(umo)
            if not conversation_id:
                return None
            conversation = await conv_mgr.get_conversation(umo, conversation_id)
        except Exception as exc:
            logger.warning(
                "[GiteeAIImagePlugin] failed to resolve conversation for plugin note: %s",
                exc,
            )
            return None

        if conversation is not None and provider_request is not None:
            try:
                provider_request.conversation = conversation
            except Exception:
                pass
        return conversation

    async def _append_plugin_conversation_note(
        self, event: AstrMessageEvent, note: str
    ) -> None:
        note = str(note or "").strip()
        if not note:
            return

        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return

        conversation = await self._resolve_plugin_conversation(event)
        if conversation is None:
            return

        history_raw = getattr(conversation, "history", "[]")
        if isinstance(history_raw, list):
            history = list(history_raw)
        else:
            try:
                parsed_history = json.loads(history_raw or "[]")
                history = list(parsed_history) if isinstance(parsed_history, list) else []
            except Exception as exc:
                logger.warning(
                    "[GiteeAIImagePlugin] failed to parse conversation history for plugin note: %s",
                    exc,
                )
                history = []

        history.append({"role": "user", "content": "Output your last task result below."})
        history.append({"role": "assistant", "content": note})

        try:
            await conv_mgr.update_conversation(
                event.unified_msg_origin,
                getattr(conversation, "cid", None),
                history=history,
            )
        except Exception as exc:
            logger.warning(
                "[GiteeAIImagePlugin] failed to persist plugin conversation note: %s",
                exc,
            )
            return

        try:
            conversation.history = json.dumps(history, ensure_ascii=False)
        except Exception:
            pass

    async def initialize(self):
        # 如果存在持久化的 JSON 文件，合并到 self.config（Pages保存的配置）
        persist_path = getattr(self, "_persist_config_path",
            str(pathlib.Path(self.data_dir) / "aiimg_persist_config.json"))
        if pathlib.Path(persist_path).is_file():
            try:
                with open(persist_path, "r", encoding="utf-8") as _f:
                    persisted = json.load(_f)
                if isinstance(persisted, dict) and persisted:
                    merged = _deep_merge(dict(self.config), persisted)
                    self.config.clear()
                    self.config.update(merged)
                    logger.info("[AI绘图站] 已从 %s 加载持久化配置", persist_path)
            except Exception as _e:
                logger.warning("[AI绘图站] 加载持久化配置失败: %s", _e)

        self.debouncer = Debouncer(self.config)
        self.imgr = ImageManager(self.config, self.data_dir)
        self.registry = ProviderRegistry(
            self.config, imgr=self.imgr, data_dir=self.data_dir
        )
        for err in self.registry.validate():
            logger.warning("[GiteeAIImagePlugin][config] %s", err)

        # 把实际服务商列表注入到 LLM 工具描述（方案 A+D）
        self._update_llm_tool_descriptions()

        self.draw = ImageDrawService(
            self.config, self.imgr, self.data_dir, registry=self.registry
        )
        self.edit = EditRouter(
            self.config, self.imgr, self.data_dir, registry=self.registry
        )
        self.nb = NanoBananaService(self.config, self.imgr)
        self.refs = ReferenceStore(self.data_dir)
        self.videomgr = VideoManager(self.config, self.data_dir)

        # 多人设管理器
        self.persona_mgr = PersonaManager(self.config, self.data_dir)

        self._concurrency_lock = asyncio.Lock()
        self._image_inflight: dict[str, int] = {}
        self._video_inflight: dict[str, int] = {}
        self._video_tasks: set[asyncio.Task] = set()

        self._patch_tool_image_cache_runtime()

        # 动态注册预设命令 (方案C: /手办化 直接触发)
        self._register_preset_commands()

        logger.info(
            f"[GiteeAIImagePlugin] 插件初始化完成: "
            f"改图后端={self.edit.get_available_backends()}, "
            f"文生图预设={len(self._get_draw_presets())}个, "
            f"改图预设={len(self.edit.get_preset_names())}个, "
            f"视频启用={bool(self._get_feature('video').get('enabled', False))}, "
            f"视频预设={len(self._get_video_presets())}个, "
            f"人设数={len(self.persona_mgr.all_personas)}个"
        )

    def _remember_last_image(self, event: AstrMessageEvent, image_path: Path) -> None:
        try:
            user_id = str(event.get_sender_id() or "")
        except Exception:
            user_id = ""
        if not user_id:
            return
        self._last_image_by_user[user_id] = Path(image_path)

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_bool(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
                return True
            if v in {"0", "false", "no", "n", "off", "disable", "disabled", ""}:
                return False
        return default

    def _patch_tool_image_cache_runtime(self) -> None:
        try:
            from astrbot.core.agent import tool_image_cache as cache_module
        except Exception as exc:
            logger.debug("[GiteeAIImagePlugin] skip tool image cache runtime patch: %s", exc)
            return

        cache_cls = getattr(cache_module, "ToolImageCache", None)
        cache_obj = getattr(cache_module, "tool_image_cache", None)
        cached_image_cls = getattr(cache_module, "CachedImage", None)
        if cache_cls is None or cache_obj is None or cached_image_cls is None:
            return
        if getattr(cache_cls, "_gitee_aiimg_runtime_patch", False):
            return

        def _patched_save_image(
            cache_self,
            base64_data: str,
            tool_call_id: str,
            tool_name: str,
            index: int = 0,
            mime_type: str = "image/png",
        ):
            ext = cache_self._get_file_extension(mime_type)
            cache_dir_value = str(getattr(cache_self, "_cache_dir", "") or "").strip()
            cache_dir = (
                Path(cache_dir_value)
                if cache_dir_value
                else Path(get_astrbot_temp_path())
                / getattr(cache_self, "CACHE_DIR_NAME", "tool_images")
            )
            file_path = cache_dir / f"{tool_call_id}_{index}{ext}"

            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                image_bytes = base64.b64decode(base64_data)
                file_path.write_bytes(image_bytes)
            except Exception as exc:
                logger.error(f"Failed to save tool image: {exc}")
                raise

            cache_self._cache_dir = str(cache_dir)
            logger.debug(
                "[GiteeAIImagePlugin] tool image cache runtime patch wrote: %s", file_path
            )
            return cached_image_cls(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                file_path=str(file_path),
                mime_type=mime_type,
            )

        cache_cls.save_image = _patched_save_image
        cache_cls._gitee_aiimg_runtime_patch = True
        cache_obj._cache_dir = str(
            Path(get_astrbot_temp_path())
            / getattr(cache_cls, "CACHE_DIR_NAME", "tool_images")
        )
        Path(cache_obj._cache_dir).mkdir(parents=True, exist_ok=True)
        logger.info(
            "[GiteeAIImagePlugin] tool image cache runtime patch active: %s",
            cache_obj._cache_dir,
        )

    def _get_max_user_concurrency(self) -> int:
        v = self._as_int(self.config.get("max_user_concurrency", 2), default=2)
        return max(1, min(10, v))

    def _get_max_user_video_concurrency(self) -> int:
        v = self._as_int(self.config.get("max_user_video_concurrency", 1), default=1)
        return max(1, min(5, v))

    def _debounce_key(self, event: AstrMessageEvent, prefix: str, user_id: str) -> str:
        """尽量用消息维度去重，避免同用户短时间内无法并发提交多条任务。"""
        mid = str(
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        ).strip()
        origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if mid and origin:
            return f"{prefix}:{origin}:{mid}"
        return f"{prefix}:{user_id}"

    async def _begin_user_job(self, user_id: str, *, kind: str) -> bool:
        user_id = str(user_id or "").strip()
        if not user_id:
            return True

        if kind == "video":
            limit = self._get_max_user_video_concurrency()
            store = self._video_inflight
        else:
            limit = self._get_max_user_concurrency()
            store = self._image_inflight

        async with self._concurrency_lock:
            cur = int(store.get(user_id, 0) or 0)
            if cur >= limit:
                return False
            store[user_id] = cur + 1
            return True

    async def _end_user_job(self, user_id: str, *, kind: str) -> None:
        user_id = str(user_id or "").strip()
        if not user_id:
            return

        store = self._video_inflight if kind == "video" else self._image_inflight
        async with self._concurrency_lock:
            cur = int(store.get(user_id, 0) or 0)
            if cur <= 1:
                store.pop(user_id, None)
            else:
                store[user_id] = cur - 1

    @staticmethod
    def _is_rich_media_transfer_failed(exc: Exception | None) -> bool:
        if exc is None:
            return False
        msg = f"{exc!r} {exc}".lower()
        return "rich media transfer failed" in msg

    @staticmethod
    def _build_compact_image_bytes(
        image_path: Path, *, max_side: int = 2048, target_bytes: int = 3_500_000
    ) -> bytes | None:
        """Build a smaller JPEG variant for platforms that reject large rich-media upload."""
        try:
            from PIL import Image as PILImage
        except Exception:
            return None

        try:
            with PILImage.open(image_path) as im:
                if im.mode not in {"RGB", "L"}:
                    im = im.convert("RGB")
                elif im.mode == "L":
                    im = im.convert("RGB")

                w, h = im.size
                if max(w, h) > max_side:
                    ratio = float(max_side) / float(max(w, h))
                    nw = max(1, int(w * ratio))
                    nh = max(1, int(h * ratio))
                    resampling = getattr(
                        getattr(PILImage, "Resampling", PILImage), "LANCZOS"
                    )
                    im = im.resize((nw, nh), resampling)

                for q in (88, 82, 76, 70, 64):
                    buf = io.BytesIO()
                    im.save(
                        buf,
                        format="JPEG",
                        quality=q,
                        optimize=True,
                        progressive=True,
                    )
                    data = buf.getvalue()
                    if data and (len(data) <= target_bytes or q == 64):
                        return data
        except Exception:
            return None
        return None

    def _is_feature_enabled(self, feat: str, *, default: bool = True) -> bool:
        return self._as_bool(self._get_feature(feat).get("enabled", default), default=default)

    def _is_feature_llm_enabled(self, feat: str, *, default: bool = True) -> bool:
        return self._as_bool(self._get_feature(feat).get("llm_tool_enabled", default), default=default)

    def _get_primary_provider(self, feature: str) -> str:
        """返回某功能链路的主服务商 ID，找不到则返回 'auto'。"""
        try:
            if feature == "draw":
                ids = self.draw._candidate_ids()
            elif feature in {"edit", "selfie"}:
                from .core.provider_chain import candidates_from_chain, as_list
                chain = as_list(self.edit._feature_conf().get("chain"))
                ids = [pid for pid, _ in candidates_from_chain(chain)]
            elif feature == "video":
                from .core.provider_chain import candidates_from_chain, as_list
                vconf = self._get_feature("video")
                chain = as_list(vconf.get("chain"))
                ids = [pid for pid, _ in candidates_from_chain(chain)]
            else:
                ids = []
            return ids[0] if ids else "auto"
        except Exception:
            return "auto"

    def _update_llm_tool_descriptions(self) -> None:
        """initialize() 完成后调用，把实际服务商列表和当前链路注入到工具描述里。

        AstrBot 的 llm_tool 装饰器在类加载时固化了 description，
        通过直接修改 func_list 里 FunctionTool 对象的字段实现运行时更新。
        """
        try:
            from astrbot.core.provider.register import llm_tools
        except Exception as e:
            logger.warning("[aiimg] 无法获取 llm_tools，跳过工具描述更新: %s", e)
            return

        # 生图/改图服务商（非视频）
        _VIDEO_KEYS = {"grok_video", "grok2api_video", "flow2api_video", "custom_video"}
        draw_ids  = [pid for pid in self.registry.provider_ids()
                     if self.registry.get(pid).get("__template_key", "") not in _VIDEO_KEYS]
        video_ids = [pid for pid in self.registry.provider_ids()
                     if self.registry.get(pid).get("__template_key", "") in _VIDEO_KEYS]

        draw_primary  = self._get_primary_provider("draw")
        edit_primary  = self._get_primary_provider("edit")
        video_primary = self._get_primary_provider("video")

        draw_list  = ", ".join(draw_ids)  or "（未配置）"
        video_list = ", ".join(video_ids) or "（未配置）"

        # ── 更新 aiimg_generate ──
        for tool in llm_tools.func_list:
            if tool.name == "aiimg_generate":
                tool.description = (
                    "根据用户意图生成或编辑图片。"
                    f"当前 draw 主链路: {draw_primary}，edit 主链路: {edit_primary}。"
                )
                backend_prop = tool.parameters.get("properties", {}).get("backend")
                if backend_prop is not None:
                    backend_prop["description"] = (
                        f"auto=自动选择；可指定服务商ID（生图/改图可选: {draw_list}）。"
                        "用户明确要求某服务商时才填，否则填 auto。"
                    )
                logger.debug("[aiimg] aiimg_generate 工具描述已更新")
                break

        # ── 更新 aiimg_batch_generate ──
        for tool in llm_tools.func_list:
            if tool.name == "aiimg_batch_generate":
                backend_prop = tool.parameters.get("properties", {}).get("backend")
                if backend_prop is not None:
                    backend_prop["description"] = (
                        f"auto=自动选择；可指定服务商ID（可选: {draw_list}）。"
                    )
                logger.debug("[aiimg] aiimg_batch_generate 工具描述已更新")
                break

        # ── 更新 grok_generate_video ──
        for tool in llm_tools.func_list:
            if tool.name == "grok_generate_video":
                tool.description = (
                    "生成视频。"
                    f"当前视频主链路: {video_primary}。"
                    f"可用视频服务商: {video_list}。"
                )
                logger.debug("[aiimg] grok_generate_video 工具描述已更新")
                break

    def _is_selfie_enabled(self) -> bool:
        return self._is_feature_enabled("selfie")

    def _is_selfie_llm_enabled(self) -> bool:
        return self._is_feature_llm_enabled("selfie")

    @staticmethod
    def _selfie_disabled_message() -> str:
        return "自拍参考图模式已关闭（features.selfie.enabled=false）"

    async def _send_elapsed_hint(
        self,
        event: AstrMessageEvent,
        elapsed: float | None,
        provider_tries: list[dict] | None = None,
    ) -> None:
        """发图后追发耗时+服务商信息提示，失败静默。

        provider_tries: [{pid, ok, error}, ...] 所有尝试过的服务商列表，
        成功的用 ✅，失败的用 ❌，多个用 → 连接。
        """
        if elapsed is None:
            return
        try:
            parts = [f"⏱ {elapsed:.1f}s"]
            if provider_tries:
                provider_str = " → ".join(
                    f"{'✅' if t['ok'] else '❌'} {t['pid']}"
                    for t in provider_tries
                )
                parts.append(provider_str)
            await event.send(event.plain_result("  |  ".join(parts)))
        except Exception:
            pass

    async def _send_image_with_fallback(
        self,
        event: AstrMessageEvent,
        image_path: Path,
        *,
        max_attempts: int = 3,
        elapsed: float | None = None,
        provider_tries: list[dict] | None = None,
    ) -> SendImageResult:
        """发送图片，按顺序尝试不同方式，每次只发一次，成功立即返回。

        Args:
            elapsed: 生图耗时（秒），非 None 时在发图后追发耗时提示。

        发送顺序：
        1. 大图（>阈值）优先以文件形式发送
        2. fromFileSystem（路径引用）
        3. fromBytes（字节流，兼容性更好）
        4. 压缩版 fromBytes（rich_media 失败时）
        5. File 文件发送（rich_media 失败兜底）

        关键设计：每次 event.send 只调用一次后立即 return 或记录失败，
        绝不在同一次调用后再次发送，防止重复发送同一张图。
        """
        p = Path(image_path)

        if not p.exists():
            logger.warning("[send_image] file not found: %s", p)
            return SendImageResult(ok=False, reason="file_not_found", cached_path=p)

        try:
            size_bytes = int(p.stat().st_size)
        except Exception:
            size_bytes = 0

        # 大图优先以文件发送
        if size_bytes > self.IMAGE_AS_FILE_THRESHOLD_BYTES:
            try:
                await event.send(event.chain_result([File(name=p.name, file=str(p))]))
                logger.info("[send_image] large image sent as file: %s bytes", size_bytes)
                try:
                    await event.send(event.plain_result("（图片较大，以文件形式发送）"))
                except Exception:
                    pass
                await self._send_elapsed_hint(event, elapsed, provider_tries)
                return SendImageResult(ok=True, cached_path=p, used_fallback=True)
            except Exception as e:
                logger.warning("[send_image] large image file send failed: %s", e)

        last_exc: Exception | None = None

        for attempt in range(1, max(1, max_attempts) + 1):
            is_rich_media_fail = False

            # 尝试1: fromFileSystem
            try:
                await event.send(event.chain_result([Image.fromFileSystem(str(p))]))
                logger.debug("[send_image] fromFileSystem OK (attempt=%s)", attempt)
                await self._send_elapsed_hint(event, elapsed, provider_tries)
                return SendImageResult(ok=True, cached_path=p, used_fallback=False)
            except Exception as e:
                last_exc = e
                is_rich_media_fail = self._is_rich_media_transfer_failed(e)
                logger.debug("[send_image] fromFileSystem failed (attempt=%s): %s", attempt, e)

            # 尝试2: fromBytes（字节流）
            try:
                data = await asyncio.to_thread(p.read_bytes)
                await event.send(event.chain_result([Image.fromBytes(data)]))
                logger.info("[send_image] fromBytes OK (attempt=%s)", attempt)
                await self._send_elapsed_hint(event, elapsed, provider_tries)
                return SendImageResult(ok=True, cached_path=p, used_fallback=True)
            except Exception as e:
                last_exc = e
                if self._is_rich_media_transfer_failed(e):
                    is_rich_media_fail = True
                logger.debug("[send_image] fromBytes failed (attempt=%s): %s", attempt, e)

            # rich_media 失败时的额外兜底（只做一次）
            if is_rich_media_fail and attempt == 1:
                # 尝试3: 压缩图
                compact = await asyncio.to_thread(self._build_compact_image_bytes, p)
                if compact:
                    try:
                        await event.send(event.chain_result([Image.fromBytes(compact)]))
                        logger.info("[send_image] compact fromBytes OK")
                        await self._send_elapsed_hint(event, elapsed, provider_tries)
                        return SendImageResult(ok=True, cached_path=p, used_fallback=True)
                    except Exception as e:
                        last_exc = e
                        logger.debug("[send_image] compact fromBytes failed: %s", e)

                # 尝试4: 文件发送
                try:
                    await event.send(event.chain_result([File(name=p.name, file=str(p))]))
                    logger.info("[send_image] file fallback OK (rich_media)")
                    try:
                        await event.send(event.plain_result("（图片发送遇到问题，已改用文件形式）"))
                    except Exception:
                        pass
                    if elapsed is not None:
                            try:
                                await self._send_elapsed_hint(event, elapsed, provider_tries)
                            except Exception:
                                pass
                    return SendImageResult(ok=True, cached_path=p, used_fallback=True)
                except Exception as e:
                    last_exc = e
                    logger.warning("[send_image] file fallback failed: %s", e)
                break  # rich_media 失败走了所有兜底，不再重试

            if attempt < max_attempts:
                await _async_pause(1.5)

        reason = (
            "rich_media_transfer_failed"
            if self._is_rich_media_transfer_failed(last_exc)
            else "send_failed"
        )
        logger.error(
            "[send_image] failed after retries: reason=%s, err=%s", reason, last_exc
        )
        return SendImageResult(
            ok=False,
            reason=reason,
            cached_path=p,
            last_error=str(last_exc or ""),
        )

    def _extract_extra_prompt(self, event: AstrMessageEvent, command_name: str) -> str:
        """从消息中提取命令后的额外提示词

        支持格式:
        - /手办化 加点金色元素 -> "加点金色元素"
        - /手办化@张三 背景是星空 -> "背景是星空"
        - /手办化@张三@李四 背景是星空 -> "背景是星空"

        注意: message_str 中 @用户 会被替换为空格或移除
        """
        msg = event.message_str.strip()
        # 移除命令前缀 (/, !, ., 等)
        # 兼容唤醒前缀：.视频 / 。视频 / ．视频
        if msg and msg[0] in "/!！.。．":
            msg = msg[1:]
        # 移除命令名
        if msg.startswith(command_name):
            msg = msg[len(command_name) :]
        # 清理多余空格
        return msg.strip()

    @staticmethod
    def _extract_command_arg_anywhere(message: str, command_name: str) -> str:
        """从任意位置提取“/命令 参数”，用于图片在前导致 @filter.command 不触发的场景。"""
        msg = (message or "").strip()
        if not msg:
            return ""
        for prefix in "/!！.。．":
            token = f"{prefix}{command_name}"
            idx = msg.find(token)
            if idx >= 0:
                return msg[idx + len(token) :].strip()
        return ""

    def _extract_command_arg_from_chain(
        self, event: AstrMessageEvent, command_name: str
    ) -> tuple[bool, str]:
        """从消息链中提取命令后的提示词。

        用于修复“/命令 + 图片 + 文本”时，平台把文本段无空格拼接到 `message_str`
        导致 command filter 和字符串提取都失效的问题。
        """
        try:
            chain = event.get_messages()
        except Exception:
            return False, ""

        found = False
        parts: list[str] = []
        for seg in chain:
            if isinstance(seg, (At, AtAll, Reply)):
                continue

            if not found:
                if not isinstance(seg, Plain):
                    continue
                plain = str(getattr(seg, "text", "") or "").lstrip()
                if not plain:
                    continue
                if plain[0] in "/!！.。．":
                    plain = plain[1:]
                if not plain.startswith(command_name):
                    continue
                found = True
                tail = plain[len(command_name) :].strip()
                if tail:
                    parts.append(tail)
                continue

            if isinstance(seg, Plain):
                text = str(getattr(seg, "text", "") or "").strip()
                if text:
                    parts.append(text)

        return found, " ".join(parts).strip()

    def _extract_chain_provider_id(self, item: object) -> str:
        if isinstance(item, str):
            return item.strip()
        if not isinstance(item, dict):
            return ""
        return str(
            item.get("provider_id")
            or item.get("id")
            or item.get("provider")
            or item.get("backend")
            or ""
        ).strip()

    def _normalize_chain_item(self, item: object) -> dict | None:
        pid = self._extract_chain_provider_id(item)
        if not pid:
            return None
        out = ""
        if isinstance(item, dict):
            out = str(item.get("output") or item.get("default_output") or "").strip()
        return {"provider_id": pid, "output": out} if out else {"provider_id": pid}

    def _parse_provider_override_prefix(self, text: str) -> tuple[str | None, str]:
        """仅当 @token 命中已配置 provider_id 时，才作为 provider 覆盖。"""
        s = (text or "").strip()
        if not s.startswith("@"):
            return None, s
        first, _, rest = s.partition(" ")
        candidate = first.lstrip("@").strip()
        if not candidate:
            return None, s
        # 大小写不敏感匹配，找到后返回实际注册的 id
        provider_ids = self.registry.provider_ids()
        candidate_lower = candidate.lower()
        for pid in provider_ids:
            if pid.lower() == candidate_lower:
                return pid, rest.strip()
        logger.debug(
            "[provider_override] 忽略未知 @token，继续走自动链路: token=%s",
            candidate,
        )
        return None, s

    @staticmethod
    def _plain_starts_with_command(text: str, command_name: str) -> bool:
        plain = (text or "").lstrip()
        if not plain:
            return False
        for prefix in "/!！.。．":
            if plain.startswith(f"{prefix}{command_name}"):
                return True
        return False

    def _is_direct_command_message(
        self, event: AstrMessageEvent, command_names: tuple[str, ...]
    ) -> bool:
        """仅当“首个有效文本段”直接是命令时返回 True。

        用于 regex 兜底去重：避免正常 /命令 被重复处理；
        同时允许“图片在前、命令在后”的消息继续走兜底逻辑。
        """
        try:
            chain = event.get_messages()
        except Exception:
            return False
        if not chain:
            return False

        first_plain = ""
        for seg in chain:
            if isinstance(seg, (At, AtAll, Reply)):
                continue
            if isinstance(seg, Plain):
                first_plain = str(getattr(seg, "text", "") or "")
            break

        if not first_plain:
            return False
        return any(
            self._plain_starts_with_command(first_plain, name) for name in command_names
        )

    @staticmethod
    def _is_framework_direct_command_text(
        message: str, command_names: tuple[str, ...], *, allow_bare: bool = True
    ) -> bool:
        """按 AstrBot CommandFilter 的文本规则判断是否可直接命中 command handler。"""
        plain = " ".join(str(message or "").strip().split())
        if not plain:
            return False
        if plain[0] in "/!！.。．":
            plain = plain[1:].lstrip()
        return any(
            (plain == name if allow_bare else False) or plain.startswith(f"{name} ")
            for name in command_names
        )

    async def _resolve_aiimg_backend_and_mode(
        self,
        prompt: str,
        backend: str,
        mode: str,
        event: AstrMessageEvent,
    ) -> tuple[str | None, str]:
        """解析 LLM 工具调用的 backend 和 mode。

        优先级：@前缀 > LLM意图分类 > auto。
        返回 (target_backend, resolved_mode)。
        """
        known_ids = set(self.registry.provider_ids())
        b_raw = (backend or "auto").strip()

        if not b_raw or b_raw.lower() == "auto":
            target_backend: str | None = None
        elif b_raw in known_ids:
            target_backend = b_raw
        else:
            logger.warning(
                "[aiimg_generate] 忽略未知 backend=%s，回退自动链路", b_raw
            )
            target_backend = None

        # LLM 意图分类（仅 auto backend 时才做，避免与明确指定冲突）
        if target_backend is None:
            has_image = bool(await get_images_from_event(event, include_avatar=False))
            llm_cls = await self._classify_intent_with_llm(prompt, has_image=has_image)
            if llm_cls:
                llm_backend = llm_cls.get("backend")
                if llm_backend and llm_backend in known_ids:
                    target_backend = llm_backend
                    logger.debug("[aiimg_generate] LLM识别服务商: %s", target_backend)
                if mode == "auto" and llm_cls.get("mode") in ("edit", "selfie_ref"):
                    mode = llm_cls["mode"]
                    logger.debug("[aiimg_generate] LLM识别mode: %s", mode)

        return target_backend, mode

    @filter.llm_tool(name="aiimg_generate")
    async def aiimg_generate(
        self,
        event: AstrMessageEvent,
        prompt: str,
        mode: str = "auto",
        backend: str = "auto",
        output: str = "",
    ):
        """根据用户意图生成或编辑图片。

        【关键判断：图片是"要改的对象"还是"给bot参考的素材"？】

        用户引用图片时，先判断意图主体：
        - 主体是图片本身（改这张图）→ mode=edit
        - 主体是bot/她/你（bot生成自己的照片，图片只是参考素材）→ mode=selfie_ref

        【mode 选择规则】：

        1. mode=selfie_ref【bot出镜，用户提供的图是参考素材】
           触发条件：用户要求bot/她/你出现在图里，图片（如有）是衣服/场景/风格参考
           典型场景：
           - "来张你的自拍" → selfie_ref
           - "你穿这件衣服拍张照" + 引用衣服图 → selfie_ref，衣服图作为参考
           - "换这个场景来一张你的照片" + 引用场景图 → selfie_ref，场景图作为参考
           - "你来一张" / "看看你" / "你本人照片" → selfie_ref
           - "穿上这个给我看看" / "穿这个拍张照" + 引用图 → selfie_ref
           ✅ 判断依据：句子主语是bot（你/她/人设名），图片是道具而非被改对象

        2. mode=edit【对用户提供的图本身进行修改】
           触发条件：用户要改的是引用图片本身的内容
           典型场景：
           - 引用图+"把白丝换成黑丝" → edit（改图片里人物的衣服）
           - 引用图+"换个背景" → edit（改图片背景）
           - 引用图+"风格改成水墨画" → edit（改图片风格）
           ✅ 判断依据：句子主语是图片里的内容，用户不要求bot出镜

        3. mode=text：纯文字生图，没有图片且不涉及bot自拍

        4. mode=auto：意图不明确时使用

        Args:
            prompt(string): 图片生成或修改的提示词
            mode(string): 可选值 selfie_ref edit text auto
            backend(string): 服务商ID，不指定填 auto
            output(string): 输出尺寸如 1024x1024，不填用默认
        """
        prompt = (prompt or "").strip()
        m = (mode or "auto").strip().lower()
        _t_start = time.perf_counter()  # 生图开始计时

        # === TTL 去重检查（防止 ToolLoop 重复调用）===
        message_id = (
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        )
        origin = getattr(event, "unified_msg_origin", "") or ""
        if message_id and origin:
            if self.debouncer.llm_tool_is_duplicate(message_id, origin):
                logger.debug(f"[aiimg_generate] 重复调用已拦截: msg_id={message_id}")
                await mark_success(event)
                return self._llm_tool_text_result(
                    "This image request was already handled for the same message. Do not run it again."
                )

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "aiimg", user_id)
        if self.debouncer.hit(request_id):
            await mark_success(event)
            return self._llm_tool_text_result(
                "This image request is already being handled or was just handled. Do not submit it again unless the user explicitly asks for a new image."
            )

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_success(event)
            return self._llm_tool_text_result(
                "An image request for this user is already in progress. Do not resubmit unless the user asks for a new request."
            )

        # 解析 backend：@前缀 → LLM分类 → auto
        provider_from_prompt, prompt = self._parse_provider_override_prefix(prompt)
        if provider_from_prompt and (not backend or backend.lower() == "auto"):
            backend = provider_from_prompt
        target_backend, m = await self._resolve_aiimg_backend_and_mode(
            prompt, backend, m, event
        )

        output = (output or "").strip()
        size = output if output and "x" in output else None
        resolution = output if output and size is None else None

        try:
            await mark_processing(event)

            if m in {"selfie_ref", "selfie", "ref"}:
                logger.info("[aiimg_generate] route=selfie_ref (explicit)")
                if not self._is_selfie_enabled():
                    logger.warning(
                        "[aiimg_generate] selfie blocked: features.selfie.enabled=false"
                    )
                    await self._signal_llm_tool_failure(event)
                    return self._llm_tool_text_result(
                        "The requested selfie image tool is disabled by plugin configuration."
                    )
                if not self._is_selfie_llm_enabled():
                    logger.warning(
                        "[aiimg_generate] selfie blocked: features.selfie.llm_tool_enabled=false"
                    )
                    await self._signal_llm_tool_failure(event)
                    return self._llm_tool_text_result(
                        "The requested selfie image tool is disabled by plugin configuration."
                    )
                image_path, task_meta = await self._generate_selfie_image_with_meta(
                    event,
                    prompt,
                    target_backend,
                    size=size,
                    resolution=resolution,
                )
                return await self._finalize_llm_tool_image(
                    event, image_path, task_meta=task_meta,
                    elapsed=time.perf_counter() - _t_start,
                )

            # 自动模式：优先识别"自拍"语义 + 已配置参考照
            if m == "auto" and await self._should_auto_selfie_ref(event, prompt):
                if not self._is_selfie_enabled():
                    logger.info(
                        "[aiimg_generate] auto-selfie skipped: features.selfie.enabled=false"
                    )
                elif not self._is_selfie_llm_enabled():
                    logger.info(
                        "[aiimg_generate] auto-selfie skipped: features.selfie.llm_tool_enabled=false"
                    )
                else:
                    try:
                        logger.info("[aiimg_generate] route=auto->selfie_ref")
                        image_path, task_meta = await self._generate_selfie_image_with_meta(
                            event,
                            prompt,
                            target_backend,
                            size=size,
                            resolution=resolution,
                        )
                    except Exception as e:
                        logger.warning(
                            "[aiimg_generate] auto-selfie failed, fallback to draw/edit: %s",
                            e,
                        )
                    else:
                        return await self._finalize_llm_tool_image(
                            event, image_path, task_meta=task_meta,
                    elapsed=time.perf_counter() - _t_start,
                            provider_tries=task_meta.get("provider_tries"),
                        )

            if m == "auto":
                follow_up_selfie_meta = await self._match_selfie_follow_up(event, prompt)
                if follow_up_selfie_meta is not None:
                    try:
                        logger.info("[aiimg_generate] route=auto->selfie_ref (follow-up)")
                        image_path, task_meta = await self._generate_selfie_image_with_meta(
                            event,
                            prompt,
                            target_backend,
                            size=size,
                            resolution=resolution,
                            follow_up_meta=follow_up_selfie_meta,
                        )
                    except Exception as e:
                        logger.warning(
                            "[aiimg_generate] selfie follow-up failed, fallback to draw/edit: %s",
                            e,
                        )
                    else:
                        return await self._finalize_llm_tool_image(
                            event, image_path, task_meta=task_meta,
                    elapsed=time.perf_counter() - _t_start,
                            provider_tries=task_meta.get("provider_tries"),
                        )

            # 改图：用户消息中有图片（不含头像兜底）或显式指定
            has_msg_images = await self._has_message_images(event)
            prefetched_edit_image_segs = None
            has_at_avatar_refs = False
            if m == "auto" and not has_msg_images:
                prefetched_edit_image_segs = await get_images_from_event(
                    event,
                    include_avatar=True,
                    include_sender_avatar_fallback=False,
                )
                has_at_avatar_refs = bool(prefetched_edit_image_segs)

            if m in {"edit", "img2img", "aiedit"} or (
                m == "auto" and (has_msg_images or has_at_avatar_refs)
            ):
                logger.info("[aiimg_generate] route=edit")
                if not self._is_feature_enabled("edit") or not self._is_feature_llm_enabled("edit"):
                    await self._signal_llm_tool_failure(event)
                    return self._llm_tool_text_result(
                        "The requested image editing tool is disabled by plugin configuration."
                    )
                image_segs = prefetched_edit_image_segs
                if image_segs is None:
                    image_segs = await get_images_from_event(
                        event,
                        include_avatar=True,
                        include_sender_avatar_fallback=False,
                    )
                bytes_images = await self._image_segs_to_bytes(image_segs)
                if not bytes_images:
                    await self._signal_llm_tool_failure(event)
                    return self._llm_tool_text_result(
                        "Image editing could not continue because no usable input image was found in the current message. This request has ended."
                    )

                logger.info(
                    "[aiimg_generate][edit] 准备调用edit: images=%d张, sizes=%s, backend=%s",
                    len(bytes_images),
                    [f"{len(b)//1024}KB" for b in bytes_images],
                    target_backend or "auto",
                )
                # 若 prompt 精确匹配预设名，自动转为预设（与 _do_edit 逻辑一致）
                edit_preset: str | None = None
                edit_prompt = prompt
                if prompt and prompt.strip() in self.edit.get_preset_names():
                    edit_preset = prompt.strip()
                    edit_prompt = ""

                image_path, _prov_tries = await self.edit.edit(
                    prompt=edit_prompt,
                    images=bytes_images,
                    backend=target_backend,
                    preset=edit_preset,
                    size=size,
                    resolution=resolution,
                )
                task_meta = self._build_image_task_meta(
                    mode="edit",
                    user_prompt=prompt,
                    effective_prompt=edit_prompt or (self.edit.presets.get(edit_preset, "") if edit_preset else prompt),
                    continue_with="edit",
                    backend=target_backend,
                )
                return await self._finalize_llm_tool_image(
                    event, image_path, task_meta=task_meta,
                    elapsed=time.perf_counter() - _t_start,
                    provider_tries=_prov_tries,
                )

            # 默认：文生图
            if not self._is_feature_enabled("draw") or not self._is_feature_llm_enabled("draw"):
                await self._signal_llm_tool_failure(event)
                return self._llm_tool_text_result(
                    "The requested image generation tool is disabled by plugin configuration."
                )
            if not prompt:
                prompt = "a selfie photo"

            logger.info("[aiimg_generate] route=draw")
            image_path, _prov_tries = await self.draw.generate(
                prompt,
                provider_id=target_backend,
                size=size,
                resolution=resolution,
            )
            task_meta = self._build_image_task_meta(
                mode="text",
                user_prompt=prompt,
                effective_prompt=prompt,
                continue_with="text",
                backend=target_backend,
            )
            return await self._finalize_llm_tool_image(
                event, image_path, task_meta=task_meta,
                    elapsed=time.perf_counter() - _t_start,
                    provider_tries=_prov_tries,
            )

        except Exception as e:
            logger.error(f"[aiimg_generate] 失败: {e}", exc_info=True)
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The image request failed and has ended. Reason: "
                + self._summarize_status_text(
                    e,
                    fallback="unknown error",
                )
                + ". Do not retry automatically unless the user explicitly asks."
            )
        finally:
            await self._end_user_job(user_id, kind="image")

    @filter.llm_tool(name="aiimg_batch_generate")
    async def aiimg_batch_generate(
        self,
        event: AstrMessageEvent,
        prompt: str,
        count: int = 4,
        mode: str = "auto",
        backend: str = "auto",
        output: str = "",
    ):
        """规划并批量生成一组图片。

        使用建议（给 LLM 的决策规则）：
        - 当用户明确想要一组不重复但同主题的图片时，优先调用这个工具。
        - 先规划多条不同 prompt，再批量执行，不要自己重复调用单图工具。

        Args:
            prompt(string): 整组图片共同要满足的要求
            count(number): 目标数量，建议 2-8
            mode(string): 可选值 auto text edit selfie_ref
            backend(string): 服务商ID，不指定填 auto
            output(string): 输出尺寸如 1024x1024，不填用默认
        """
        prompt = str(prompt or "").strip()
        if not prompt:
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result("Batch image planning failed because no prompt was provided.")

        target_count = self._as_int(count, default=4)
        target_count = max(1, min(self._get_batch_max_count(), target_count))
        resolved_mode = await self._resolve_llm_batch_mode(event, mode, prompt)
        target_backend = self._resolve_target_backend(backend)

        output = (output or "").strip()
        size = output if output and "x" in output else None
        resolution = output if output and size is None else None

        if resolved_mode == "draw":
            if not self._is_feature_enabled("draw") or not self._is_feature_llm_enabled("draw"):
                await self._signal_llm_tool_failure(event)
                return self._llm_tool_text_result(
                    "The requested batch text-to-image tool is disabled by plugin configuration."
                )
        elif resolved_mode == "edit":
            if not self._is_feature_enabled("edit") or not self._is_feature_llm_enabled("edit"):
                await self._signal_llm_tool_failure(event)
                return self._llm_tool_text_result(
                    "The requested batch image editing tool is disabled by plugin configuration."
                )
        elif resolved_mode == "selfie_ref":
            if not self._is_selfie_enabled() or not self._is_selfie_llm_enabled():
                await self._signal_llm_tool_failure(event)
                return self._llm_tool_text_result(
                    "The requested batch selfie image tool is disabled by plugin configuration."
                )

        message_id = (
            getattr(getattr(event, "message_obj", None), "message_id", "") or ""
        )
        origin = getattr(event, "unified_msg_origin", "") or ""
        if message_id and origin and self.debouncer.llm_tool_is_duplicate(message_id, origin):
            await mark_success(event)
            return self._llm_tool_text_result(
                "This batch image request was already handled for the same message. Do not run it again."
            )

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "aiimg_batch", user_id)
        if self.debouncer.hit(request_id):
            await mark_success(event)
            return self._llm_tool_text_result(
                "This batch image request is already being handled or was just handled. Do not resubmit unless the user explicitly asks for a new batch."
            )

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_success(event)
            return self._llm_tool_text_result(
                "A batch image request for this user is already in progress. Do not resubmit unless the user asks for a new request."
            )

        try:
            await mark_processing(event)
            planned_items = await self._plan_batch_prompt_items(
                mode=resolved_mode,
                user_prompt=prompt,
                count=target_count,
            )
            specs = [
                ImageTaskSpec(
                    mode=resolved_mode,
                    provider_id=target_backend,
                    preset_name=None,
                    user_prompt=item.prompt,
                    effective_prompt=item.prompt,
                    source_command="llm_batch",
                    variant_title=item.title,
                )
                for item in planned_items
            ]
            results = await self._run_batch_specs(
                event,
                specs,
                size=size,
                resolution=resolution,
                stream_send=True,
            )
            success_count = sum(1 for result in results if result.success and result.value)
            failed_count = len(results) - success_count
            if success_count > 0:
                await self._remember_batch_success(event, results)
                await mark_success(event)
            else:
                await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The batch image set has already been generated and sent to the user. "
                f"Mode={resolved_mode}, success={success_count}, failed={failed_count}. "
                "Do not send another confirmation message to the user."
            )
        except Exception as e:
            logger.error("[aiimg_batch_generate] 失败: %s", e, exc_info=True)
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The batch image request failed and has ended. Reason: "
                + self._summarize_status_text(e, fallback="unknown error")
            )
        finally:
            await self._end_user_job(user_id, kind="image")

    @filter.llm_tool()
    async def grok_generate_video(self, event: AstrMessageEvent, prompt: str):
        """根据用户发送/引用的图片生成视频。

        Args:
            prompt(string): 视频提示词。支持 "预设名 额外提示词"（与 `/视频 预设名 额外提示词` 一致）
        """
        if not self._is_feature_enabled("video", default=False):
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The requested video tool is disabled by plugin configuration."
            )
        if not self._is_feature_llm_enabled("video"):
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The requested video tool is disabled by plugin configuration."
            )

        arg = (prompt or "").strip()
        if not arg:
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The video request failed because no prompt was provided. This request has ended."
            )

        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The video request failed because no usable prompt remained after parsing provider overrides. This request has ended."
            )

        preset, extra_prompt = self._parse_video_args(arg)
        presets = self._get_video_presets()
        if preset and preset in presets:
            preset_prompt = presets[preset]
            extra_prompt = (
                f"{preset_prompt}, {extra_prompt}" if extra_prompt else preset_prompt
            )

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "video", user_id)

        if self.debouncer.hit(request_id):
            await mark_success(event)
            return self._llm_tool_text_result(
                "This video request is already being handled or was just handled. Do not submit it again unless the user explicitly asks for a new video."
            )

        if not await self._video_begin(user_id):
            await mark_success(event)
            return self._llm_tool_text_result(
                "A video request for this user is already in progress. Do not resubmit unless the user asks for a new request."
            )

        try:
            await mark_processing(event)
            task = asyncio.create_task(
                self._async_generate_video(
                    event,
                    extra_prompt,
                    user_id,
                    provider_id=provider_override,
                    llm_tool_failure=True,
                )
            )
        except Exception:
            await self._video_end(user_id)
            await self._signal_llm_tool_failure(event)
            return self._llm_tool_text_result(
                "The video request failed before background execution could start. This request has ended."
            )

        self._video_tasks.add(task)
        task.add_done_callback(lambda t: self._video_tasks.discard(t))

        return self._llm_tool_text_result(
            "Video generation has been accepted and is running in the background. The result will be sent to the user automatically when ready. Do not submit the same request again unless the user explicitly asks."
        )

    # ==================== 内部方法 ====================

    async def _fail_cmd(self, event: AstrMessageEvent) -> None:
        """Command handler 通用失败退出：标记失败 + 停止事件 + 禁止 LLM 介入。"""
        await mark_failed(event)
        event.stop_event()
        event.should_call_llm(True)

    @filter.command("文生图")
    async def generate_image_with_presets(self, event: AstrMessageEvent):
        """支持文生图预设的图片生成命令。"""
        parsed = self._parse_structured_image_request(event.message_str)
        if parsed is None or parsed.spec.source_command != "文生图":
            await self._fail_cmd(event)
            return

        spec = parsed.spec
        if not str(spec.effective_prompt or "").strip():
            await self._fail_cmd(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "draw_preset", user_id)
        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return
        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        # 占用 aiimg 防重槽，阻止 LLM 工具调用重复生图
        self.debouncer.hit(self._debounce_key(event, "aiimg", user_id))

        try:
            # 发送等待提示文案，同时贴处理中表情
            await asyncio.gather(
                event.send(event.plain_result(
                    self._pending_msg_draw(str(spec.effective_prompt or ""))
                )),
                mark_processing(event),
                return_exceptions=True,
            )
            _t0 = time.perf_counter()
            executed = await self._execute_image_task_spec(event, spec)
            self._remember_last_image(event, executed.image_path)
            sent = await self._send_image_with_fallback(event, executed.image_path, elapsed=time.perf_counter() - _t0, provider_tries=executed.task_meta.get("provider_tries"))
            if not sent:
                await self._fail_cmd(event)
                return
            await self._save_last_image_task_meta(event, executed.task_meta)
            await mark_success(event)
        except Exception as exc:
            logger.error("[文生图预设] 失败: %s", exc, exc_info=True)
            try:
                await event.send(event.plain_result(self._error_msg_draw(exc)))
            except Exception:
                pass
            await mark_failed(event)
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    @filter.command("aiimg", alias={"生图", "画图", "绘图", "出图"})
    async def generate_image_command(self, event: AstrMessageEvent, prompt: str):
        """生成图片指令

        用法: /aiimg [@provider_id] <提示词> [比例]
        示例: /aiimg 一个女孩 9:16
        支持比例: 1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16
        """
        # 解析参数
        arg = event.message_str.partition(" ")[2]
        if not arg:
            await self._fail_cmd(event)
            return
        provider_override: str | None = None
        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await self._fail_cmd(event)
            return

        prompt = arg.strip()
        size: str | None = None
        parts = arg.split()
        if parts and parts[-1] in self.SUPPORTED_RATIOS:
            ratio = parts[-1]
            prompt = " ".join(parts[:-1]).strip()
            size = self._resolve_ratio_size(ratio)

        if not prompt:
            await self._fail_cmd(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "generate", user_id)

        # 防抖检查
        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        # 占用 aiimg 防重槽，阻止 LLM 工具调用重复生图
        self.debouncer.hit(self._debounce_key(event, "aiimg", user_id))

        try:
            # 发送等待提示文案，同时贴"处理中"表情（两者并行）
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_draw(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
            t_start = time.perf_counter()
            image_path, _prov_tries = await self.draw.generate(
                prompt, size=size, provider_id=provider_override
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path, elapsed=t_end - t_start, provider_tries=_prov_tries)
            if not sent:
                await mark_failed(event)
                logger.warning(
                    "[文生图] 图片发送失败，已仅使用表情标注: reason=%s", sent.reason
                )
                event.stop_event()
                return

            # 标记成功
            await mark_success(event)
            logger.info(
                f"[文生图] 完成: {prompt[:30] if prompt else '文生图'}..., 耗时={t_end - t_start:.2f}s"
            )

        except Exception as e:
            logger.error(f"[文生图] 失败: {e}")
            try:
                await event.send(event.plain_result(self._error_msg_draw(e)))
            except Exception:
                pass
            await mark_failed(event)
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    @filter.regex(r"[/!！.。．]批量(?:\s*\d+|\d+)(?:\s|$)", priority=-10)
    async def batch_image_command(self, event: AstrMessageEvent):
        """批量图片任务入口。"""
        fragment = self._extract_batch_command_fragment(event.message_str)
        parsed = self._parse_structured_image_request(fragment)
        if parsed is None or parsed.batch_count <= 1:
            await self._fail_cmd(event)
            return
        if parsed.batch_count > self._get_batch_max_count():
            await event.send(
                event.plain_result(
                    f"批量数量过大，当前上限为 {self._get_batch_max_count()}。"
                )
            )
            await self._fail_cmd(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "batch_image", user_id)
        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return
        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        try:
            # 发送等待提示文案
            await asyncio.gather(
                event.send(event.plain_result(
                    self._pending_msg_draw(str(parsed.spec.effective_prompt or ""))
                )),
                mark_processing(event),
                return_exceptions=True,
            )
            specs = [parsed.spec for _ in range(parsed.batch_count)]
            results = await self._run_batch_specs(event, specs, stream_send=True)
            title = f"{self._batch_mode_label(parsed.spec)} x{parsed.batch_count}"
            if any(result.success and result.value for result in results):
                await self._remember_batch_success(event, results)
                await mark_success(event)
            else:
                await mark_failed(event)
        except Exception as exc:
            logger.error("[批量图片] 失败: %s", exc, exc_info=True)
            await mark_failed(event)
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    # ==================== 图生图/改图 ====================

    @filter.command("文生图预设列表")
    async def list_draw_presets(self, event: AstrMessageEvent):
        """列出所有可用文生图预设"""
        presets = self._get_draw_presets()
        backends = self.draw._candidate_ids()
        draw_conf = self._get_feature("draw")
        chain = []
        for it in (
            draw_conf.get("chain", [])
            if isinstance(draw_conf.get("chain", []), list)
            else []
        ):
            pid = self._extract_chain_provider_id(it)
            if pid and pid not in chain:
                chain.append(pid)

        if not presets:
            msg = "📋 文生图预设列表\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += f"🔧 可用后端: {', '.join(backends)}\n"
            if chain:
                msg += f"⭐ 当前链路: {', '.join(chain)}\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "📌 暂无预设\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "💡 在配置 features.draw.presets 中添加:\n"
            msg += '  格式: "预设名:英文提示词"'
        else:
            msg = "📋 文生图预设列表\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += f"🔧 可用后端: {', '.join(backends)}\n"
            if chain:
                msg += f"⭐ 当前链路: {', '.join(chain)}\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "📌 预设:\n"
            for name in presets:
                msg += f"  • {name}\n"
        msg += "━━━━━━━━━━━━━━\n"
        msg += "💡 用法: /文生图 [@provider_id] <预设名> [补充提示词]"
        yield event.plain_result(msg)

    @filter.command("预设列表")
    async def list_presets(self, event: AstrMessageEvent):
        """列出所有可用预设"""
        presets = self.edit.get_preset_names()
        backends = self.edit.get_available_backends()
        edit_conf = self._get_feature("edit")
        chain = []
        for it in (
            edit_conf.get("chain", [])
            if isinstance(edit_conf.get("chain", []), list)
            else []
        ):
            pid = self._extract_chain_provider_id(it)
            if pid and pid not in chain:
                chain.append(pid)

        if not presets:
            msg = "📋 改图预设列表\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += f"🔧 可用后端: {', '.join(backends)}\n"
            if chain:
                msg += f"⭐ 当前链路: {', '.join(chain)}\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "📌 暂无预设\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "💡 在配置 features.edit.presets 中添加:\n"
            msg += '  格式: "触发词:英文提示词"'
        else:
            msg = "📋 改图预设列表\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += f"🔧 可用后端: {', '.join(backends)}\n"
            if chain:
                msg += f"⭐ 当前链路: {', '.join(chain)}\n"
            msg += "━━━━━━━━━━━━━━\n"
            msg += "📌 预设:\n"
            for name in presets:
                msg += f"  • {name}\n"
        msg += "━━━━━━━━━━━━━━\n"
        msg += "💡 用法: /aiedit [@provider_id] <提示词> [图片]"

        yield event.plain_result(msg)

    def _register_preset_commands(self):
        """动态注册预设命令

        为每个预设创建对应的命令，如 /手办化, /Q版化 等
        """
        preset_names = self.edit.get_preset_names()
        if not preset_names:
            return

        for preset_name in preset_names:
            # 创建闭包捕获 preset_name
            self._create_and_register_preset_handler(preset_name)

        logger.info(f"[GiteeAIImagePlugin] 已注册 {len(preset_names)} 个预设命令")

    def _create_and_register_preset_handler(self, preset_name: str):
        """为单个预设创建并注册命令处理器

        支持: /手办化 [额外提示词]
        例如: /手办化 加点金色元素
        """

        # 默认后端命令: /手办化
        async def preset_handler(event: AstrMessageEvent):
            # 提取命令后的额外提示词
            extra_prompt = self._extract_extra_prompt(event, preset_name)
            await self._do_edit_direct(event, extra_prompt, preset=preset_name)

        preset_handler.__name__ = f"preset_{preset_name}"
        preset_handler.__doc__ = f"预设改图: {preset_name} [额外提示词]"

        self.context.register_commands(
            star_name="astrbot_plugin_aiimg_enhanced",
            command_name=preset_name,
            desc=f"预设改图: {preset_name}",
            priority=5,
            awaitable=preset_handler,
        )

    @filter.command("aiedit", alias={"图生图", "改图", "修图"})
    async def edit_image_default(self, event: AstrMessageEvent, prompt: str):
        """使用默认后端改图

        用法: /aiedit <提示词>
        需要同时发送或引用图片
        """
        await self._do_edit(event, prompt, backend=None)

    @filter.regex(r"(?:[/!！.。．])?(改图|图生图|修图|aiedit)", priority=-10)
    async def edit_image_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、文字在后”的消息：确保 /改图 能触发。"""
        msg = (event.message_str or "").strip()
        command_names = ("改图", "图生图", "修图", "aiedit")
        if self._is_framework_direct_command_text(msg, command_names, allow_bare=False):
            return
        try:
            if not await self._has_message_images(event):
                return
        except Exception:
            return

        prompt = ""
        matched = False
        for name in command_names:
            prompt = self._extract_command_arg_anywhere(msg, name)
            found_in_chain, chain_prompt = self._extract_command_arg_from_chain(
                event, name
            )
            if prompt or found_in_chain:
                matched = True
                if not prompt:
                    prompt = chain_prompt
                break
        if matched:
            await self._do_edit(event, prompt, backend=None)
            event.stop_event()

    @filter.regex(r"[/!！.。．][^\s]+", priority=-10)
    async def preset_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、预设命令在后”的消息：确保 /<预设名> 能触发。"""
        msg = (event.message_str or "").strip()
        preset_names = self.edit.get_preset_names()
        if not preset_names:
            return

        # 如果首段文本本来就是 /预设，则交给 command handler，避免重复处理
        try:
            if self._is_direct_command_message(event, tuple(preset_names)):
                return
        except Exception:
            pass

        # 仅当消息/引用里确实带图（不含头像兜底）时才兜底，避免误伤其它插件命令
        try:
            if not await self._has_message_images(event):
                return
        except Exception:
            return

        # 在任意位置找到第一个匹配的预设命令
        used_preset: str | None = None
        for name in preset_names:
            for prefix in "/!！.。．":
                if f"{prefix}{name}" in msg:
                    used_preset = name
                    break
            if used_preset:
                break

        if not used_preset:
            return

        extra_prompt = self._extract_command_arg_anywhere(msg, used_preset)
        await self._do_edit_direct(event, extra_prompt, preset=used_preset)
        event.stop_event()

    # ==================== 服务商 & 链路管理 ====================

    @filter.command("改图帮助")
    async def edit_help(self, event: AstrMessageEvent):
        """显示改图帮助"""
        msg = """🎨 改图功能帮助

━━ 基础命令 ━━
/aiedit [@provider_id] <提示词>

━━ 使用方式 ━━
1. 发送图片 + 命令
2. 引用图片消息 + 命令

━━ 服务商链路 ━━
在 WebUI 配置：
- providers：添加服务商（id/url/key/model/超时/重试等）
- features.edit.chain：按顺序填写 provider_id（第一个=主用，其余=兜底）

━━ 自定义预设 ━━
查看预设：/预设列表
在 WebUI 配置 features.edit.presets 添加：
格式: 预设名:英文提示词
示例: 手办化:Transform into figurine style
"""

        yield event.plain_result(msg)

    # ==================== LLM 工具 ====================

    async def _do_edit_direct(
        self,
        event: AstrMessageEvent,
        prompt: str,
        backend: str | None = None,
        preset: str | None = None,
    ):
        """改图执行入口 (非 generator 版本，用于动态注册的命令)

        使用 event.send() 直接发送消息，不使用 yield
        """
        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "edit", user_id)

        # 防抖
        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        p = (prompt or "").strip()
        override, rest = self._parse_provider_override_prefix(p)
        if override:
            backend = override
            prompt = rest

        # 获取图片
        image_segs = await get_images_from_event(
            event,
            include_avatar=True,
            include_sender_avatar_fallback=False,
        )
        logger.debug(f"[改图] 获取到 {len(image_segs)} 个图片段")
        if not image_segs:
            await event.send(event.plain_result(
                "🖼️ 改图需要提供一张图片。\n请同时发送图片 + 指令，或引用一条含图片的消息。"
            ))
            await self._fail_cmd(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)
        if not bytes_images:
            await event.send(event.plain_result("⚠️ 图片读取失败，请重新发送。"))
            await self._fail_cmd(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        # 占用 aiimg 防重槽，阻止 LLM 工具调用重复生图
        self.debouncer.hit(self._debounce_key(event, "aiimg", user_id))

        try:
            # 发送等待提示，同时贴处理中表情
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_edit(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
            t_start = time.perf_counter()
            image_path, _prov_tries = await self.edit.edit(
                prompt=prompt,
                images=bytes_images,
                backend=backend,
                preset=preset,
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path, elapsed=t_end - t_start, provider_tries=_prov_tries)
            if not sent:
                await mark_failed(event)
                event.stop_event()
                logger.warning(
                    "[改图] 结果发送失败，已仅使用表情标注: reason=%s",
                    sent.reason,
                )
                return

            # 标记成功
            await mark_success(event)
            display_name = preset or (prompt[:20] if prompt else "改图")
            logger.info(f"[改图] 完成: {display_name}..., 耗时={t_end - t_start:.2f}s")

        except Exception as e:
            logger.error(f"[改图] 失败: {e}", exc_info=True)
            await mark_failed(event)
            err_str = str(e)
            if "No edit providers configured" in err_str or "features.edit.chain" in err_str:
                hint = "⚠️ 改图失败：未配置改图服务商链路。\n请在 WebUI → 改图 → chain 中添加支持改图的服务商。"
            elif "不支持改图" in err_str or "does not support edit" in err_str:
                hint = "⚠️ 改图失败：当前服务商不支持改图功能，请在 features.edit.chain 中使用支持改图的服务商。"
            elif "disabled" in err_str.lower() and "edit" in err_str.lower():
                hint = "⚠️ 改图功能已被禁用（features.edit.enabled=false）。"
            else:
                hint = f"⚠️ 改图失败：{err_str[:120]}"
            try:
                await event.send(event.plain_result(hint))
            except Exception:
                pass
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    async def _do_edit(
        self,
        event: AstrMessageEvent,
        prompt: str,
        backend: str | None = None,
        preset: str | None = None,
    ):
        """统一改图执行入口

        预设触发逻辑:
        1. 如果 preset 参数已指定，直接使用
        2. 否则检查 prompt 是否匹配预设名，若匹配则自动转为预设
        3. 都不匹配则作为普通提示词处理
        """
        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "edit", user_id)

        # 防抖
        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        # Optional provider override: "/aiedit @provider_id <prompt>"
        p = (prompt or "").strip()
        override, rest = self._parse_provider_override_prefix(p)
        if override:
            backend = override
            prompt = rest

        # 预设自动检测: prompt 完全匹配预设名时，自动转为预设
        if not preset and prompt:
            prompt_stripped = prompt.strip()
            preset_names = self.edit.get_preset_names()
            if prompt_stripped in preset_names:
                preset = prompt_stripped
                prompt = ""  # 清空 prompt，使用预设的提示词
                logger.debug(f"[改图] 自动匹配预设: {preset}")

        # 获取图片
        # DEBUG: 打印消息链内容帮助排查引用图片提取问题
        try:
            from .core.utils import _get_event_chain
            from astrbot.core.message.components import Reply as _Reply
            _dbg_chain = _get_event_chain(event)
            logger.info(
                "[改图][DEBUG] get_messages chain_len=%d types=%s",
                len(_dbg_chain),
                [type(s).__name__ for s in _dbg_chain],
            )
            # 尝试从 message_obj.message（原始链）里找 Reply
            _raw_msg = getattr(getattr(event, "message_obj", None), "message", None)
            if isinstance(_raw_msg, list):
                logger.info(
                    "[改图][DEBUG] message_obj.message chain_len=%d types=%s",
                    len(_raw_msg),
                    [type(s).__name__ for s in _raw_msg],
                )
                for _seg in _raw_msg:
                    if isinstance(_seg, _Reply):
                        logger.info("[改图][DEBUG] Reply found in raw chain: id=%s chain=%s",
                            getattr(_seg, "id", "?"),
                            getattr(_seg, "chain", None),
                        )
            # 打印 message_obj 完整原始结构（排查 aiocqhttp raw event 格式）
            _mobj = getattr(event, "message_obj", None)
            logger.info("[改图][DEBUG] message_obj type=%s attrs=%s",
                type(_mobj).__name__,
                {k: str(getattr(_mobj, k, None))[:120]
                 for k in ("raw_message", "message_str", "message_type", "message")
                 if hasattr(_mobj, k)},
            )
        except Exception as _e:
            logger.debug("[改图][DEBUG] chain inspect failed: %s", _e)

        image_segs = await get_images_from_event(
            event,
            include_avatar=True,
            include_sender_avatar_fallback=False,
        )
        if not image_segs:
            await event.send(event.plain_result(
                "🖼️ 改图需要提供一张图片。\n请同时发送图片 + 指令，或引用一条含图片的消息。\n例如：发送图片，并在同一条消息里写 /改图 <提示词>"
            ))
            await self._fail_cmd(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)

        if not bytes_images:
            await event.send(event.plain_result("⚠️ 图片读取失败，请重新发送。"))
            await self._fail_cmd(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        # 占用 aiimg 防重槽，阻止 LLM 工具调用重复生图
        self.debouncer.hit(self._debounce_key(event, "aiimg", user_id))

        try:
            # 发送等待提示，同时贴处理中表情
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_edit(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
            t_start = time.perf_counter()
            image_path, _prov_tries = await self.edit.edit(
                prompt=prompt,
                images=bytes_images,
                backend=backend,
                preset=preset,
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path, elapsed=t_end - t_start, provider_tries=_prov_tries)
            if not sent:
                await mark_failed(event)
                event.stop_event()
                logger.warning(
                    "[改图] 结果发送失败，已仅使用表情标注: reason=%s",
                    sent.reason,
                )
                return

            # 标记成功
            await mark_success(event)
            display_name = preset or (prompt[:20] if prompt else "改图")
            logger.info(f"[改图] 完成: {display_name}..., 耗时={t_end - t_start:.2f}s")

        except Exception as e:
            logger.error(f"[改图] 失败: {e}")
            await mark_failed(event)
            # 向用户发送可读的错误原因，帮助排查配置问题
            err_str = str(e)
            if "No edit providers configured" in err_str or "features.edit.chain" in err_str:
                hint = "⚠️ 改图失败：未配置改图服务商链路。\n请在 WebUI → 改图 → chain 中添加支持改图的服务商。"
            elif "不支持改图" in err_str or "supports_edit" in err_str or "does not support edit" in err_str:
                hint = "⚠️ 改图失败：当前服务商不支持改图功能，请在 features.edit.chain 中使用支持改图的服务商。"
            elif "disabled" in err_str.lower() and "edit" in err_str.lower():
                hint = "⚠️ 改图功能已被禁用（features.edit.enabled=false）。"
            else:
                hint = f"⚠️ 改图失败：{err_str[:120]}"
            try:
                await event.send(event.plain_result(hint))
            except Exception:
                pass
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    # ==================== 自拍参考照：内部实现 ====================

    @filter.command("自拍")
    async def selfie_command(self, event: AstrMessageEvent):
        """使用“自拍参考照”生成 Bot 自拍。

        用法:
        - /自拍 <提示词>
        - 可附带多张参考图（衣服/姿势/场景）作为额外参考
        """
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return
        prompt = self._extract_extra_prompt(event, "自拍")
        await self._do_selfie(event, prompt, backend=None)

    @filter.regex(r"[/!！.。．]自拍(\s|$)", priority=-10)
    async def selfie_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、文字在后”的消息：确保 /自拍 能触发。"""
        msg = (event.message_str or "").strip()
        # 如果本来就是“首段文本命令”，交给 command handler，避免重复回复
        if self._is_direct_command_message(event, ("自拍",)):
            return
        prompt = self._extract_command_arg_anywhere(msg, "自拍")
        if prompt or "/自拍" in msg or "自拍" in msg:
            if not self._is_selfie_enabled():
                await self._fail_cmd(event)
                return
            await self._do_selfie(event, prompt, backend=None)
            event.stop_event()

    @filter.command("自拍参考")
    async def selfie_reference_command(self, event: AstrMessageEvent):
        """管理自拍参考照（建议仅管理员使用）。

        用法:
        - 发送图片 + /自拍参考 设置
        - /自拍参考 查看
        - /自拍参考 删除
        """
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return
        arg = self._extract_extra_prompt(event, "自拍参考")
        action, _, _rest = (arg or "").strip().partition(" ")
        action = action.strip().lower()

        if not action or action in {"帮助", "help", "h"}:
            msg = (
                "📸 自拍参考照\n"
                "━━━━━━━━━━━━━━\n"
                "设置：发送图片 + /自拍参考 设置\n"
                "查看：/自拍参考 查看\n"
                "删除：/自拍参考 删除\n"
                "━━━━━━━━━━━━━━\n"
                "生成自拍：/自拍 <提示词>\n"
                "可附带额外参考图（衣服/姿势/场景）"
            )
            yield event.plain_result(msg)
            return

        if action in {"设置", "set"}:
            await self._set_selfie_reference(event)
            return

        if action in {"查看", "show", "看"}:
            async for result in self._show_selfie_reference(event):
                yield result
            return

        if action in {"删除", "del", "delete"}:
            await self._delete_selfie_reference(event)
            return

        await mark_failed(event)
        event.stop_event()

    @filter.regex(r"[/!！.。．]自拍参考(\s|$)", priority=-10)
    async def selfie_reference_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、文字在后”的消息：确保 /自拍参考 能触发。"""
        msg = (event.message_str or "").strip()
        if self._is_direct_command_message(event, ("自拍参考",)):
            return
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return
        arg = self._extract_command_arg_anywhere(msg, "自拍参考")
        action, _, _rest = (arg or "").strip().partition(" ")
        action = action.strip().lower()

        if not action or action in {"帮助", "help", "h"}:
            yield event.plain_result(
                "📸 自拍参考照\n"
                "━━━━━━━━━━━━━━\n"
                "设置：发送图片 + /自拍参考 设置\n"
                "查看：/自拍参考 查看\n"
                "删除：/自拍参考 删除\n"
                "━━━━━━━━━━━━━━\n"
                "生成自拍：/自拍 <提示词>\n"
                "可附带额外参考图（衣服/姿势/场景）"
            )
            event.stop_event()
            return

        if action in {"设置", "set"}:
            await self._set_selfie_reference(event)
            event.stop_event()
            return

        if action in {"查看", "show", "看"}:
            async for r in self._show_selfie_reference(event):
                yield r
            event.stop_event()
            return

        if action in {"删除", "del", "delete"}:
            await self._delete_selfie_reference(event)
            event.stop_event()
            return

        await mark_failed(event)
        event.stop_event()

    # ==================== 视频生成 ====================

    async def _do_selfie(
        self,
        event: AstrMessageEvent,
        prompt: str,
        backend: str | None = None,
    ):
        """指令 /自拍 执行入口。"""
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "selfie", user_id)

        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await self._fail_cmd(event)
            return

        p = (prompt or "").strip()
        override, rest = self._parse_provider_override_prefix(p)
        if override:
            backend = override
            prompt = rest

        try:
            # 发送等待提示文案，同时贴"处理中"表情（两者并行）
            pending_text = self._pending_msg_selfie(prompt)
            await asyncio.gather(
                event.send(event.plain_result(pending_text)),
                mark_processing(event),
                return_exceptions=True,
            )

            _t0 = time.perf_counter()
            image_path, task_meta = await self._generate_selfie_image_with_meta(
                event, prompt, backend
            )
            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path, elapsed=time.perf_counter() - _t0, provider_tries=task_meta.get("provider_tries"))
            if not sent:
                await mark_failed(event)
                event.stop_event()
                logger.warning(
                    "[自拍] 结果发送失败，已仅使用表情标注: reason=%s",
                    sent.reason,
                )
                return
            await mark_success(event)
            await self._save_last_image_task_meta(event, task_meta)
        except Exception as e:
            logger.error(f"[自拍] 失败: {e}", exc_info=True)
            try:
                await event.send(event.plain_result(self._error_msg_selfie(e)))
            except Exception:
                pass
            await mark_failed(event)
        finally:
            await self._end_user_job(user_id, kind="image")
            event.stop_event()
            event.should_call_llm(True)

    async def _set_selfie_reference(self, event: AstrMessageEvent):
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return

        image_segs = await get_images_from_event(event, include_avatar=False)
        if not image_segs:
            await self._fail_cmd(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)
        if not bytes_images:
            await self._fail_cmd(event)
            return

        # 限制数量，避免一次塞太多
        max_images = 8
        bytes_images = bytes_images[:max_images]

        store_key = self._get_selfie_ref_store_key(event)
        try:
            await self.refs.set(store_key, bytes_images)
        except Exception:
            await self._fail_cmd(event)
            return

        await mark_success(event)

    async def _show_selfie_reference(self, event: AstrMessageEvent):
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return

        paths, source = await self._get_selfie_reference_paths(event)
        if not paths:
            await self._fail_cmd(event)
            return

        # 最多回显 5 张，避免刷屏
        max_show = 5
        show_paths = paths[:max_show]
        img_components = []
        for p in show_paths:
            ps = str(p)
            if ps.startswith("http://") or ps.startswith("https://"):
                img_components.append(Image.fromURL(ps))
            else:
                img_components.append(Image.fromFileSystem(ps))
        if img_components:
            yield event.chain_result(img_components)
        yield event.plain_result(
            f"📌 当前自拍参考照来源：{source}，共 {len(paths)} 张（已展示 {len(show_paths)} 张）"
        )

    async def _delete_selfie_reference(self, event: AstrMessageEvent):
        if not self._is_selfie_enabled():
            await self._fail_cmd(event)
            return

        store_key = self._get_selfie_ref_store_key(event)
        deleted = await self.refs.delete(store_key)

        webui_paths = self._get_config_selfie_reference_paths()
        if webui_paths:
            logger.info(
                "[自拍参考] 命令保存的参考照已删除，但 WebUI reference_images 仍生效（优先级更高）"
            )

        if deleted:
            await mark_success(event)
        else:
            await mark_failed(event)
            event.stop_event()

    async def _video_begin(self, user_id: str) -> bool:
        """单用户并发保护：成功占用返回 True，否则 False（上限可配置）"""
        return await self._begin_user_job(str(user_id or ""), kind="video")

    async def _video_end(self, user_id: str) -> None:
        await self._end_user_job(str(user_id or ""), kind="video")

    async def _send_video_result(self, event: AstrMessageEvent, video_url: str) -> None:
        vconf = self._get_feature("video")
        mode = str(vconf.get("send_mode", "auto")).strip().lower()
        if mode not in {"auto", "url", "file"}:
            mode = "auto"

        send_timeout = int(vconf.get("send_timeout_seconds", 90) or 90)
        send_timeout = max(10, min(send_timeout, 300))

        download_timeout = int(vconf.get("download_timeout_seconds", 300) or 300)
        download_timeout = max(1, min(download_timeout, 3600))

        async def _send_file(url: str) -> bool:
            try:
                video_path = await self.videomgr.download_video(
                    url, timeout_seconds=download_timeout
                )
                await asyncio.wait_for(
                    event.send(
                        event.chain_result([Video.fromFileSystem(str(video_path))])
                    ),
                    timeout=float(send_timeout),
                )
                return True
            except Exception as e:
                logger.warning(f"[视频] 本地文件发送失败: {e}")
                return False

        async def _send_url(url: str) -> bool:
            try:
                await asyncio.wait_for(
                    event.send(event.chain_result([Video.fromURL(url)])),
                    timeout=float(send_timeout),
                )
                return True
            except Exception as e:
                logger.warning(f"[视频] URL 发送失败: {e}")
                return False

        # file/url forced
        if mode == "file":
            if await _send_file(video_url):
                return
            await event.send(event.plain_result(video_url))
            return

        if mode == "url":
            if await _send_url(video_url):
                return
            await event.send(event.plain_result(video_url))
            return

        # auto: prefer file first (most platforms won't render URL as playable video)
        if await _send_file(video_url):
            return
        if await _send_url(video_url):
            return
        await event.send(event.plain_result(video_url))

    @filter.command("视频")
    async def generate_video_command(self, event: AstrMessageEvent):
        """生成视频

        用法:
        - /视频 [@provider_id] <提示词>
        - /视频 [@provider_id] <预设名> [额外提示词]
        """
        if not bool(self._get_feature("video").get("enabled", False)):
            await self._fail_cmd(event)
            return
        arg = self._extract_extra_prompt(event, "视频")
        if not arg:
            await self._fail_cmd(event)
            return

        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await self._fail_cmd(event)
            return

        preset, prompt = self._parse_video_args(arg)
        presets = self._get_video_presets()
        if preset and preset in presets:
            preset_prompt = presets[preset]
            prompt = f"{preset_prompt}, {prompt}" if prompt else preset_prompt

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "video", user_id)

        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        if not await self._video_begin(user_id):
            await self._fail_cmd(event)
            return

        try:
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_video(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
        except Exception:
            await self._video_end(user_id)
            await self._fail_cmd(event)
            return

        try:
            task = asyncio.create_task(
                self._async_generate_video(
                    event, prompt, user_id, provider_id=provider_override
                )
            )
        except Exception:
            await self._video_end(user_id)
            await self._fail_cmd(event)
            return

        self._video_tasks.add(task)
        task.add_done_callback(lambda t: self._video_tasks.discard(t))
        return

    @filter.regex(r"[/!！.。．]视频(\s|$)", priority=-10)
    async def generate_video_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、文字在后”的消息：确保 /视频 能触发。"""
        msg = (event.message_str or "").strip()
        if self._is_direct_command_message(event, ("视频",)):
            return

        arg = self._extract_command_arg_anywhere(msg, "视频")
        if not arg and "/视频" not in msg:
            return
        if not bool(self._get_feature("video").get("enabled", False)):
            await self._fail_cmd(event)
            return
        if not arg:
            await self._fail_cmd(event)
            return

        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await self._fail_cmd(event)
            return

        preset, prompt = self._parse_video_args(arg)
        presets = self._get_video_presets()
        if preset and preset in presets:
            preset_prompt = presets[preset]
            prompt = f"{preset_prompt}, {prompt}" if prompt else preset_prompt

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "video", user_id)

        if self.debouncer.hit(request_id):
            await self._fail_cmd(event)
            return

        if not await self._video_begin(user_id):
            await self._fail_cmd(event)
            return

        try:
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_video(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
        except Exception:
            await self._video_end(user_id)
            await self._fail_cmd(event)
            return

        try:
            task = asyncio.create_task(
                self._async_generate_video(
                    event, prompt, user_id, provider_id=provider_override
                )
            )
        except Exception:
            await self._video_end(user_id)
            await self._fail_cmd(event)
            return

        self._video_tasks.add(task)
        task.add_done_callback(lambda t: self._video_tasks.discard(t))
        event.stop_event()
        return

    @filter.command("视频预设列表")
    async def list_video_presets(self, event: AstrMessageEvent):
        """列出所有可用视频预设"""
        presets = self._get_video_presets()
        names = list(presets.keys())
        if not names:
            yield event.plain_result(
                "📋 视频预设列表\n暂无预设（请在配置 features.video.presets 中添加）"
            )
            return

        msg = "📋 视频预设列表\n"
        for name in names:
            msg += f"- {name}\n"
        msg += "\n用法: /视频 [@provider_id] <预设名> [额外提示词]"
        yield event.plain_result(msg)

    # ==================== 管理命令 ====================

    async def _async_generate_video(
        self,
        event: AstrMessageEvent,
        prompt: str,
        user_id: str,
        *,
        provider_id: str | None = None,
        llm_tool_failure: bool = False,
    ) -> None:
        try:
            image_segs = await get_images_from_event(
                event,
                include_avatar=True,
                include_sender_avatar_fallback=False,
            )
            had_image = bool(image_segs)
            image_bytes: bytes | None = None
            for i, seg in enumerate(image_segs):
                try:
                    b64 = await asyncio.wait_for(seg.convert_to_base64(), timeout=30.0)
                    image_bytes = decode_base64_image_payload(b64)
                    break
                except Exception as e:
                    logger.warning(f"[视频] 图片 {i + 1} 转换失败，跳过: {e}")

            # 允许文生视频（无图）走支持的后端；但若用户确实发了图却读不到，则直接失败
            if had_image and not image_bytes:
                if llm_tool_failure:
                    await self._append_plugin_conversation_note(
                        event,
                        "The last video generation task failed and has ended because the source image could not be read. Do not retry automatically unless the user explicitly asks.",
                    )
                if llm_tool_failure:
                    await self._signal_llm_tool_failure(event)
                else:
                    await self._fail_cmd(event)
                return

            t_start = time.perf_counter()
            candidates = (
                [str(provider_id).strip()] if provider_id else self._get_video_chain()
            )
            candidates = [c for c in candidates if c]
            if not candidates:
                raise RuntimeError(
                    "No video providers configured. Please set features.video.chain."
                )

            last_error: Exception | None = None
            video_url: str | None = None
            used_pid: str | None = None
            for pid in candidates:
                try:
                    backend = self.registry.get_video_backend(pid)
                    candidate_url = await backend.generate_video_url(
                        prompt=prompt, image_bytes=image_bytes
                    )
                    candidate_url = str(candidate_url or "").strip()
                    if not candidate_url:
                        raise RuntimeError("Provider returned empty video url")
                    video_url = candidate_url
                    used_pid = pid
                    break
                except Exception as e:
                    last_error = e
                    logger.warning("[视频] Provider=%s 失败: %s", pid, e)

            if not video_url:
                raise RuntimeError(f"视频生成失败: {last_error}") from last_error

            await self._send_video_result(event, video_url)
            await mark_success(event)
            if llm_tool_failure:
                await self._append_plugin_conversation_note(
                    event,
                    "The last video generation task has completed and the video was already sent to the user. Do not continue or resubmit this task unless the user explicitly asks for another video.",
                )

            t_end = time.perf_counter()
            name = used_pid or "video"
            logger.info(f"[视频] 完成: provider={name}, 耗时={t_end - t_start:.2f}s")

        except Exception as e:
            logger.error(f"[视频] 失败: {e}", exc_info=True)
            if llm_tool_failure:
                await self._append_plugin_conversation_note(
                    event,
                    "The last video generation task failed and has ended. Reason: "
                    + self._summarize_status_text(
                        e,
                        fallback="unknown error",
                    )
                    + ". Do not retry automatically unless the user explicitly asks.",
                )
            if llm_tool_failure:
                await self._signal_llm_tool_failure(event)
            else:
                await mark_failed(event)
        finally:
            await self._video_end(user_id)
            event.stop_event()
            event.should_call_llm(True)

    @filter.command("重发图片")
    async def resend_last_image(self, event: AstrMessageEvent):
        """重发最近一次生成/改图的图片（不重新生成，不消耗次数）。"""
        user_id = str(event.get_sender_id() or "")
        p = self._last_image_by_user.get(user_id)
        if not p:
            await self._fail_cmd(event)
            return
        if not Path(p).exists():
            await self._fail_cmd(event)
            return
        _t0 = time.perf_counter()
        ok = await self._send_image_with_fallback(event, p, elapsed=time.perf_counter() - _t0)
        if ok:
            await mark_success(event)
        else:
            await mark_failed(event)
        event.stop_event()
        event.should_call_llm(True)

    @filter.command("服务商")
    async def provider_list_command(self, event: AstrMessageEvent):
        """查看所有已配置的服务商。用法: /服务商"""
        ids = self.registry.provider_ids()
        if not ids:
            yield event.plain_result("⚠️ 暂无已配置的服务商，请在配置页添加。")
            return
        lines = ["🔌 已配置服务商："]
        for pid in ids:
            p = self.registry.get(pid)
            tkey = str((p or {}).get("__template_key") or "")
            label = str((p or {}).get("label") or "")
            model = str((p or {}).get("model") or "")
            meta = " · ".join(x for x in [tkey, model] if x)
            lines.append(f"  [{pid}]  {meta}")
        lines.append("\n用 /链路 查看各功能当前链路配置。")
        yield event.plain_result("\n".join(lines))

    @filter.command("链路")
    async def chain_command(self, event: AstrMessageEvent):
        """查看或设置各功能的服务商链路。

        用法:
        - /链路                           查看当前链路
        - /链路 draw @主用 @备用1 @备用2  设置文生图链路
        - /链路 edit @主用 @备用          设置改图链路
        - /链路 selfie @主用              设置自拍链路
        - /链路 video @主用               设置视频链路
        """
        arg = self._extract_extra_prompt(event, "链路").strip()

        # 无参数：查看当前链路
        if not arg:
            yield event.plain_result(self._format_chain_status())
            return

        # 解析 "draw @p1 @p2 ..." 格式
        parts = arg.split()
        feat_key = parts[0].lower()
        feat_map = {"draw": "draw", "文生图": "draw",
                    "edit": "edit", "改图": "edit", "图生图": "edit",
                    "selfie": "selfie", "自拍": "selfie",
                    "video": "video", "视频": "video"}
        if feat_key not in feat_map:
            yield event.plain_result(
                f"⚠️ 未知功能「{parts[0]}」\n"
                "可用功能：draw/文生图、edit/改图、selfie/自拍、video/视频"
            )
            return

        feat = feat_map[feat_key]
        provider_ids = self.registry.provider_ids()

        # 解析 @provider_id 列表
        raw_ids = [p.lstrip("@") for p in parts[1:] if p.startswith("@")]
        non_at  = [p for p in parts[1:] if not p.startswith("@")]
        if not raw_ids and not non_at:
            # 无参数：只显示该功能当前链路
            yield event.plain_result(self._format_chain_status(feat))
            return
        if not raw_ids and non_at:
            # 有参数但忘写@
            yield event.plain_result(
                f"⚠️ 服务商 ID 需要以 @ 开头。\n"
                f"示例：/链路 {parts[0]} @{non_at[0]}\n"
                f"用 /服务商 查看可用 ID。"
            )
            return

        # 验证每个 id，大小写不敏感
        resolved, unknown = [], []
        for rid in raw_ids:
            matched = next((p for p in provider_ids if p.lower() == rid.lower()), None)
            if matched:
                resolved.append(matched)
            else:
                unknown.append(rid)

        if unknown:
            yield event.plain_result(
                f"⚠️ 以下服务商未配置：{', '.join(unknown)}\n"
                f"用 /服务商 查看可用列表。"
            )
            return

        # 更新 chain
        has_output = feat != "video"
        new_chain = [{"provider_id": pid, "output": ""} if has_output else {"provider_id": pid}
                     for pid in resolved]

        if isinstance(self.config, dict):
            feats = self.config.setdefault("features", {})
            feats.setdefault(feat, {})["chain"] = new_chain
        self._safe_update_config()

        # 格式化确认消息
        order_labels = ["主用"] + [f"备用{i}" for i in range(1, len(resolved))]
        lines = [f"✅ 已更新「{feat}」链路："]
        for label, pid in zip(order_labels, resolved):
            lines.append(f"  {label}：{pid}")
        yield event.plain_result("\n".join(lines))

    def _format_chain_status(self, feat_filter: str | None = None) -> str:
        """格式化各功能链路状态。"""
        feat_names = {"draw": "文生图", "edit": "改图", "selfie": "自拍", "video": "视频"}
        feats = (self.config or {}).get("features", {}) if isinstance(self.config, dict) else {}
        lines = ["🔗 当前链路配置："]
        for feat_key, feat_label in feat_names.items():
            if feat_filter and feat_key != feat_filter:
                continue
            chain = (feats.get(feat_key) or {}).get("chain") or []
            if not chain:
                lines.append(f"  {feat_label}：（未配置，使用系统默认）")
            else:
                pids = [str(item.get("provider_id") or "") for item in chain if isinstance(item, dict)]
                pids = [p for p in pids if p]
                order_labels = ["主"] + [f"备{i}" for i in range(1, len(pids))]
                chain_str = "  →  ".join(f"{l}:{p}" for l, p in zip(order_labels, pids))
                lines.append(f"  {feat_label}：{chain_str}")
        if not feat_filter:
            lines.append("\n用 /服务商 查看所有可用服务商。")
        return "\n".join(lines)

    # ==================== 人设管理 ====================

    @filter.command("人设")
    async def persona_list_command(self, event: AstrMessageEvent):
        """查看所有人设列表及当前激活人设。用法: /人设"""
        msg = "🎭 可用人设：\n"
        for index, p in enumerate(self.persona_mgr.all_personas, start=1):
            marker = "👉" if p.id == self.persona_mgr.active.id else "  "
            msg += f"{marker} [{index}] {p.name} ({p.id}) · 参考图 {len(p.ref_images)} 张\n"
        msg += "\n使用 /切换人设 [序号/ID/名称] 切换自拍人格与对应参考图组。"
        yield event.plain_result(msg)

    @filter.command("切换人设")
    async def persona_switch_command(self, event: AstrMessageEvent):
        """切换当前激活的人设。用法: /切换人设 [序号/ID/名称]"""
        selector = self._extract_extra_prompt(event, "切换人设").strip()
        if not selector:
            yield event.plain_result("⚠️ 缺少人设。用法: /切换人设 [序号/ID/名称]\n可先发送 /人设 查看列表。")
            return

        target = self.persona_mgr.switch(selector)
        if not target:
            yield event.plain_result(f"⚠️ 找不到人设: {selector}\n可先发送 /人设 查看列表。")
            return

        # 对齐 omnidraw：_set_active_persona → _persist_config → _safe_update_context_config
        if isinstance(self.config, dict):
            self.config.setdefault("persona_config", {})["active_persona_id"] = target.id
        self._safe_update_config()

        ref_count = len(self.persona_mgr.get_active_ref_paths())
        yield event.plain_result(
            f"✅ 已切换至人设「{target.name}」，"
            f"自拍将使用该人设的 {ref_count} 张参考图。"
        )

    # ==================== Bot 自拍（参考照） ====================

    async def terminate(self):
        self.debouncer.clear_all()
        try:
            tasks = list(getattr(self, "_video_tasks", []))
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        await self.imgr.close()
        await self.draw.close()
        await self.edit.close()
        await self.nb.close()
        await close_session()  # 关闭 utils.py 的 HTTP 会话

    # ==================== 文生图 ====================

    def _get_feature(self, name: str) -> dict:
        feats = self.config.get("features", {}) if isinstance(self.config, dict) else {}
        feats = feats if isinstance(feats, dict) else {}
        conf = feats.get(name, {})
        return conf if isinstance(conf, dict) else {}

    def _get_batch_feature(self) -> dict:
        return self._get_feature("batch")

    def _get_batch_max_count(self) -> int:
        value = self._as_int(self._get_batch_feature().get("max_count", 8), default=8)
        return max(1, min(32, value))

    def _get_draw_batch_concurrency(self) -> int:
        value = self._as_int(
            self._get_feature("draw").get("batch_concurrency", 2), default=2
        )
        return max(1, min(8, value))

    def _get_edit_batch_concurrency(self) -> int:
        value = self._as_int(
            self._get_feature("edit").get("batch_concurrency", 2), default=2
        )
        return max(1, min(8, value))

    def _get_draw_presets(self) -> dict[str, str]:
        presets: dict[str, str] = {}
        conf = self._get_feature("draw")
        items = conf.get("presets", [])
        if not isinstance(items, list):
            return presets
        for item in items:
            if isinstance(item, str) and ":" in item:
                key, val = item.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key and val:
                    presets[key] = val
        return presets

    def _parse_structured_image_request(self, text: str) -> ParsedImageRequest | None:
        edit_presets = dict(getattr(self.edit, "presets", {}) or {})
        return parse_image_request(
            text,
            draw_presets=self._get_draw_presets(),
            edit_presets=edit_presets,
            known_provider_ids=set(self.registry.provider_ids()),
        )

    @staticmethod
    def _extract_batch_command_fragment(message: str) -> str:
        text = str(message or "")
        match = _BATCH_COMMAND_PATTERN.search(text)
        if not match:
            return ""
        return text[match.start() :].strip()

    def _batch_mode_label(self, spec: ImageTaskSpec) -> str:
        if spec.mode == "draw":
            if spec.preset_name:
                return f"文生图预设/{spec.preset_name}"
            return "文生图"
        if spec.mode == "edit":
            if spec.preset_name:
                return f"改图预设/{spec.preset_name}"
            return "改图"
        if spec.mode == "selfie_ref":
            return "自拍"
        return spec.mode

    def _get_batch_concurrency_for_mode(self, mode: str) -> int:
        if mode == "draw":
            return self._get_draw_batch_concurrency()
        return self._get_edit_batch_concurrency()

    def _resolve_target_backend(self, backend: str | None) -> str | None:
        raw = str(backend or "auto").strip()
        known_provider_ids = set(self.registry.provider_ids())
        if not raw or raw.lower() == "auto":
            return None
        if raw in known_provider_ids:
            return raw
        logger.warning(
            "[backend_override] 忽略未知 backend 覆盖，回退自动链路: backend=%s",
            raw,
        )
        return None

    def _get_draw_ratio_default_sizes(self) -> dict[str, str]:
        conf = self._get_feature("draw")
        raw = conf.get("ratio_default_sizes", {})
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for ratio, size in raw.items():
            r = str(ratio or "").strip()
            s = normalize_size_text(size)
            if not r or not s:
                continue
            out[r] = s
        return out

    def _resolve_ratio_size(self, ratio: str) -> str:
        ratio = str(ratio or "").strip()
        overrides = self._get_draw_ratio_default_sizes()
        size, warning = resolve_ratio_size(
            ratio,
            overrides=overrides,
            supported_ratios=self.SUPPORTED_RATIOS,
        )
        if warning:
            logger.warning("[aiimg] %s", warning)
        return size

    def _get_video_presets(self) -> dict[str, str]:
        presets: dict[str, str] = {}
        conf = self._get_feature("video")
        items = conf.get("presets", [])
        if not isinstance(items, list):
            return presets
        for item in items:
            if isinstance(item, str) and ":" in item:
                key, val = item.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key and val:
                    presets[key] = val
        return presets

    def _get_video_chain(self) -> list[str]:
        conf = self._get_feature("video")
        chain = conf.get("chain", [])
        if not isinstance(chain, list):
            return []
        out: list[str] = []
        for item in chain:
            pid = self._extract_chain_provider_id(item)
            if pid and pid not in out:
                out.append(pid)
        return out

    def _parse_video_args(self, text: str) -> tuple[str | None, str]:
        """解析 /视频 参数，返回 (preset, prompt)

        - 当第一个 token 命中预设名时：preset=该 token, prompt=剩余内容
        - 否则：preset=None, prompt=text
        """
        text = (text or "").strip()
        if not text:
            return None, ""

        first, _, rest = text.partition(" ")
        if first and first in self._get_video_presets():
            return first, rest.strip()
        return None, text

    async def _prepare_edit_image_bytes(self, event: AstrMessageEvent) -> list[bytes]:
        image_segs = await get_images_from_event(
            event,
            include_avatar=True,
            include_sender_avatar_fallback=False,
        )
        if not image_segs:
            raise RuntimeError("当前消息没有可用输入图片，无法执行改图批量任务。")
        bytes_images = await self._image_segs_to_bytes(image_segs)
        if not bytes_images:
            raise RuntimeError("当前消息图片读取失败，无法执行改图批量任务。")
        return bytes_images

    async def _execute_image_task_spec(
        self,
        event: AstrMessageEvent,
        spec: ImageTaskSpec,
        *,
        prepared_edit_images: list[bytes] | None = None,
        size: str | None = None,
        resolution: str | None = None,
    ) -> ExecutedImageTask:
        if spec.mode == "draw":
            prompt = str(spec.effective_prompt or spec.user_prompt or "").strip()
            if not prompt:
                raise RuntimeError("文生图提示词为空。")
            image_path, _prov_tries = await self.draw.generate(
                prompt,
                provider_id=spec.provider_id,
                size=size,
                resolution=resolution,
            )
            task_meta = self._build_image_task_meta(
                mode="text",
                user_prompt=spec.user_prompt,
                effective_user_prompt=prompt if spec.preset_name else spec.user_prompt,
                effective_prompt=prompt,
                continue_with="text",
                backend=spec.provider_id,
            )
            task_meta["provider_tries"] = _prov_tries
            return ExecutedImageTask(spec=spec, image_path=image_path, task_meta=task_meta)

        if spec.mode == "edit":
            bytes_images = prepared_edit_images
            if bytes_images is None:
                bytes_images = await self._prepare_edit_image_bytes(event)
            image_path, _prov_tries = await self.edit.edit(
                prompt=spec.user_prompt,
                images=bytes_images,
                backend=spec.provider_id,
                preset=spec.preset_name,
                size=size,
                resolution=resolution,
            )
            task_meta = self._build_image_task_meta(
                mode="edit",
                user_prompt=spec.user_prompt,
                effective_user_prompt=spec.effective_prompt,
                effective_prompt=spec.effective_prompt,
                continue_with="edit",
                backend=spec.provider_id,
            )
            if spec.preset_name:
                task_meta["preset_name"] = spec.preset_name
            task_meta["provider_tries"] = _prov_tries
            return ExecutedImageTask(spec=spec, image_path=image_path, task_meta=task_meta)

        if spec.mode == "selfie_ref":
            if not self._is_selfie_enabled():
                raise RuntimeError(self._selfie_disabled_message())
            image_path, task_meta = await self._generate_selfie_image_with_meta(
                event,
                spec.user_prompt,
                spec.provider_id,
                size=size,
                resolution=resolution,
            )
            return ExecutedImageTask(spec=spec, image_path=image_path, task_meta=task_meta)

        raise RuntimeError(f"不支持的图片任务模式: {spec.mode}")

    async def _run_batch_specs(
        self,
        event: AstrMessageEvent,
        specs: list[ImageTaskSpec],
        *,
        size: str | None = None,
        resolution: str | None = None,
        stream_send: bool = False,
    ) -> list[BatchRunResult[ExecutedImageTask]]:
        if not specs:
            return []

        prepared_edit_images: list[bytes] | None = None
        if any(spec.mode == "edit" for spec in specs):
            prepared_edit_images = await self._prepare_edit_image_bytes(event)

        concurrency = self._get_batch_concurrency_for_mode(specs[0].mode)
        total = len(specs)
        completed = 0

        async def _runner(index: int, spec: ImageTaskSpec) -> ExecutedImageTask:
            nonlocal completed
            result = await self._execute_image_task_spec(
                event,
                spec,
                prepared_edit_images=prepared_edit_images,
                size=size,
                resolution=resolution,
            )
            if stream_send:
                completed += 1
                try:
                    label = spec.variant_title or spec.effective_prompt or ""
                    caption = f"[{completed}/{total}] {label[:30]}" if label else f"[{completed}/{total}]"
                    await event.send(event.plain_result(caption))
                    await self._send_image_with_fallback(event, result.image_path, elapsed=None)
                except Exception as e:
                    logger.warning("[batch] 流式发送第%d张失败: %s", completed, e)
            return result

        return await run_batch(specs, concurrency=concurrency, runner=_runner)

    async def _remember_batch_success(
        self,
        event: AstrMessageEvent,
        results: list[BatchRunResult[ExecutedImageTask]],
    ) -> None:
        for result in reversed(results):
            if not result.success or result.value is None:
                continue
            self._remember_last_image(event, result.value.image_path)
            await self._save_last_image_task_meta(event, result.value.task_meta)
            return

    async def _send_batch_results_single(
        self,
        event: AstrMessageEvent,
        results: list[BatchRunResult[ExecutedImageTask]],
        *,
        title: str,
    ) -> None:
        for result in results:
            if result.success and result.value is not None:
                await self._send_image_with_fallback(event, result.value.image_path, elapsed=None)

    async def _send_batch_results(
        self,
        event: AstrMessageEvent,
        results: list[BatchRunResult[ExecutedImageTask]],
        *,
        title: str,
    ) -> None:
        await self._send_batch_results_single(event, results, title=title)

    async def _plan_batch_prompt_items(
        self,
        *,
        mode: str,
        user_prompt: str,
        count: int,
    ) -> list[PlannedPromptItem]:
        provider = self.context.get_using_provider()
        if provider is None or not hasattr(provider, "text_chat"):
            raise RuntimeError("当前没有可用的 LLM 提供商，无法规划批量提示词。")

        planning_prompt = build_batch_planning_prompt(
            mode=mode,
            user_prompt=user_prompt,
            count=count,
        )
        last_error: Exception | None = None
        for _ in range(3):
            llm_response = await provider.text_chat(
                prompt=planning_prompt,
                contexts=[],
                image_urls=[],
                func_tool=None,
                system_prompt=(
                    "You plan image prompt sets. Output JSON only. "
                    "No markdown, no code fence, no explanation."
                ),
            )
            text = str(getattr(llm_response, "completion_text", "") or "").strip()
            if not text:
                last_error = RuntimeError("LLM returned empty planner output")
                continue
            try:
                items = parse_planned_prompt_items(text)
                validation_error = validate_planned_prompt_items(
                    items, expected_count=count
                )
                if validation_error is not None:
                    raise ValueError(validation_error)
                return items
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"批量提示词规划失败: {last_error}")

    async def _resolve_llm_batch_mode(
        self, event: AstrMessageEvent, mode: str, prompt: str
    ) -> str:
        m = str(mode or "auto").strip().lower()
        if m in {"text", "draw", "aiimg"}:
            return "draw"
        if m in {"edit", "img2img", "aiedit"}:
            return "edit"
        if m in {"selfie_ref", "selfie", "ref"}:
            return "selfie_ref"
        if m != "auto":
            return "draw"

        if (
            self._is_selfie_enabled()
            and self._is_selfie_llm_enabled()
            and await self._should_auto_selfie_ref(event, prompt)
        ):
            return "selfie_ref"

        has_msg_images = await self._has_message_images(event)
        if has_msg_images:
            return "edit"

        prefetched_edit_image_segs = await get_images_from_event(
            event,
            include_avatar=True,
            include_sender_avatar_fallback=False,
        )
        if prefetched_edit_image_segs:
            return "edit"
        return "draw"

    def _get_selfie_conf(self) -> dict:
        return self._get_feature("selfie")

    # ==================== 回复文案辅助 ====================

    def _get_reply_conf(self) -> dict:
        conf = self.config.get("reply_config") if isinstance(self.config, dict) else {}
        return conf if isinstance(conf, dict) else {}

    def _safe_update_config(self) -> None:
        """持久化配置，完全对齐 omnidraw 的 _persist_config + _safe_update_context_config。"""
        # Step 1: 写自管理 JSON 文件（omnidraw 的 _persist_config，最可靠）
        try:
            persist_path = self._persist_config_path
            pathlib.Path(persist_path).parent.mkdir(parents=True, exist_ok=True)
            tmp = f"{persist_path}.{uuid.uuid4().hex}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dict(self.config), f, ensure_ascii=False, indent=4)
            os.replace(tmp, persist_path)
            logger.debug("[AI绘图站] 配置已写入 %s", persist_path)
        except Exception as e:
            logger.warning("[AI绘图站] JSON 文件持久化失败: %s", e)

        # Step 2: 同步到 native config（omnidraw 的 _safe_update_context_config）
        native = getattr(self, "_native_config", None) or (
            self.config if hasattr(self.config, "save_config") else None
        )
        if native is not None:
            try:
                if native is not self.config:
                    native.clear()
                    native.update(self.config)
                native.save_config()
                logger.debug("[AI绘图站] 配置已通过 native.save_config() 同步")
                return
            except Exception as e:
                logger.warning("[AI绘图站] native.save_config() 失败: %s", e)

        if hasattr(self.context, "update_config"):
            try:
                self.context.update_config(self.config)
            except Exception as e:
                logger.warning("[AI绘图站] context.update_config() 失败: %s", e)

    def _format_reply(self, template: str, default: str, **values: Any) -> str:
        """安全格式化回复文案，对齐 omnidraw 的 _format_reply_message。"""
        raw_template = str(template or "").strip() or default

        class _SafeValues(dict):
            def __missing__(self, key: str) -> str:
                return "{" + key + "}"

        safe_values = _SafeValues({k: str(v) for k, v in values.items()})
        try:
            formatted = raw_template.format_map(safe_values)
        except Exception:
            formatted = raw_template
        return formatted.strip() or default

    def _pending_msg_draw(self, prompt: str = "") -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("draw_pending_message") or "").strip()
        msg = self._format_reply(tpl, _DEFAULT_DRAW_PENDING,
                                  prompt=prompt,
                                  persona_name=self.persona_mgr.active.name)
        if self._as_bool(rc.get("verbose_report"), default=False) and prompt:
            msg += f"\n📝 提示词: {prompt[:200]}"
        return msg

    def _pending_msg_edit(self, prompt: str = "") -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("edit_pending_message") or "").strip()
        msg = self._format_reply(tpl, _DEFAULT_EDIT_PENDING,
                                  prompt=prompt,
                                  persona_name=self.persona_mgr.active.name)
        if self._as_bool(rc.get("verbose_report"), default=False) and prompt:
            msg += f"\n📝 提示词: {prompt[:200]}"
        return msg

    def _pending_msg_selfie(self, prompt: str = "") -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("selfie_pending_message") or "").strip()
        msg = self._format_reply(tpl, _DEFAULT_SELFIE_PENDING,
                                  prompt=prompt,
                                  persona_name=self.persona_mgr.active.name)
        if self._as_bool(rc.get("verbose_report"), default=False):
            ref_count = len(self.persona_mgr.get_active_ref_paths())
            msg += f"\n👤 人设: {self.persona_mgr.active.name}  📸 参考图: {ref_count} 张"
            if prompt:
                msg += f"\n📝 动作提示: {prompt[:200]}"
        return msg

    def _pending_msg_video(self, prompt: str = "") -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("video_pending_message") or "").strip()
        return self._format_reply(tpl, _DEFAULT_VIDEO_PENDING, prompt=prompt)

    def _error_msg_draw(self, error: Exception | str) -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("draw_error_message") or "").strip()
        error_text = " ".join(str(error or "未知错误").split())[:300]
        return self._format_reply(tpl, _DEFAULT_DRAW_ERROR,
                                   error=error_text,
                                   persona_name=self.persona_mgr.active.name)

    def _error_msg_selfie(self, error: Exception | str) -> str:
        rc = self._get_reply_conf()
        tpl = str(rc.get("selfie_error_message") or "").strip()
        error_text = " ".join(str(error or "未知错误").split())[:300]
        return self._format_reply(tpl, _DEFAULT_SELFIE_ERROR,
                                   error=error_text,
                                   persona_name=self.persona_mgr.active.name)

    # ==================== Pages 可视化配置 API ====================

    # ==================== Pages Web API ====================

    async def _ensure_tool_image_cache_dir(self) -> None:
        tool_image_dir = Path(get_astrbot_temp_path()) / "tool_images"
        await asyncio.to_thread(tool_image_dir.mkdir, parents=True, exist_ok=True)

    async def _build_llm_tool_image_result(
        self, image_path: Path
    ) -> mcp.types.CallToolResult | None:
        try:
            image_bytes = await asyncio.to_thread(Path(image_path).read_bytes)
        except Exception as exc:
            logger.warning(
                "[aiimg_generate] failed to read image for LLM context: path=%s err=%s",
                image_path,
                exc,
            )
            return None

        if not image_bytes:
            logger.warning(
                "[aiimg_generate] skip empty image for LLM context: path=%s",
                image_path,
            )
            return None

        mime_type, _ = guess_image_mime_and_ext(image_bytes)
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        return mcp.types.CallToolResult(
            content=[
                mcp.types.ImageContent(
                    type="image",
                    data=image_b64,
                    mimeType=mime_type,
                )
            ]
        )

    async def _finalize_llm_tool_image(
        self,
        event: AstrMessageEvent,
        image_path: Path,
        *,
        task_meta: dict[str, Any],
        elapsed: float | None = None,
        provider_tries: list[dict] | None = None,
    ) -> mcp.types.CallToolResult:
        self._remember_last_image(event, image_path)

        sent = await self._send_image_with_fallback(event, image_path, elapsed=elapsed, provider_tries=provider_tries)
        if not sent:
            await self._signal_llm_tool_failure(event)
            logger.warning(
                "[aiimg_generate] image send failed, emoji fallback only: reason=%s",
                sent.reason,
            )
            return self._llm_tool_text_result(
                "Image generation finished, but sending the image to the user failed. This request has ended. Do not retry automatically unless the user explicitly asks."
            )

        await mark_success(event)
        await self._save_last_image_task_meta(event, task_meta)
        return self._build_image_task_completion_result(task_meta)

    def _get_selfie_ref_store_key(self, event: AstrMessageEvent) -> str:
        """用于 ReferenceStore 的固定 key（按 bot self_id 隔离）。"""
        self_id = ""
        try:
            if hasattr(event, "get_self_id"):
                self_id = str(event.get_self_id() or "").strip()
        except Exception:
            self_id = ""
        return f"bot_selfie_{self_id}" if self_id else "bot_selfie"

    def _resolve_data_rel_path(self, rel_path: str) -> Path | None:
        """将 data_dir 下的相对路径解析为绝对路径，并阻止路径穿越。"""
        if not isinstance(rel_path, str) or not rel_path.strip():
            return None
        rel = rel_path.replace("\\", "/").lstrip("/")
        parts = [p for p in rel.split("/") if p]
        if any(p in {".", ".."} for p in parts):
            return None
        base = Path(self.data_dir).resolve(strict=False)
        target = (base / "/".join(parts)).resolve(strict=False)
        try:
            target.relative_to(base)
        except ValueError:
            return None
        return target

    def _get_config_selfie_reference_paths(self) -> list[Path]:
        """从 WebUI file 配置项读取参考图路径。"""
        conf = self._get_selfie_conf()
        ref_list = conf.get("reference_images", [])
        if not isinstance(ref_list, list):
            return []

        paths: list[Path] = []
        for rel_path in ref_list:
            p = self._resolve_data_rel_path(str(rel_path))
            if not p:
                continue
            if p.is_file():
                paths.append(p)
        return paths

    async def _get_selfie_reference_paths(
        self, event: AstrMessageEvent
    ) -> tuple[list[Path | str], str]:
        """返回(路径列表, 来源)；优先级：人设参考图 > WebUI reference_images > 命令设置的 store"""
        # 1) 当前人设的参考图（最高优先级）
        # URL参考图直接保留（字符串形式），本地路径转Path；两者混合时分别处理
        persona_ref_strs = self.persona_mgr.get_active_ref_paths()
        if persona_ref_strs:
            persona_paths: list[Path | str] = []
            for r in persona_ref_strs:
                if r.startswith("http://") or r.startswith("https://"):
                    persona_paths.append(r)          # URL保持字符串
                elif Path(r).is_file():
                    persona_paths.append(Path(r))    # 本地路径转Path
            if persona_paths:
                return persona_paths, f"persona:{self.persona_mgr.active.name}"

        # 2) WebUI features.selfie.reference_images
        webui_paths = self._get_config_selfie_reference_paths()
        if webui_paths:
            return webui_paths, "webui"

        # 3) 命令 /自拍参考 设置的 store
        store_key = self._get_selfie_ref_store_key(event)
        store_paths = await self.refs.get_paths(store_key)
        if store_paths:
            return store_paths, "store"

        return [], "none"

    async def _read_paths_bytes(self, paths: list[Path | str]) -> list[bytes]:
        """读取本地文件或下载 URL，返回 bytes 列表。"""
        out: list[bytes] = []
        for p in paths:
            try:
                if isinstance(p, str) and (p.startswith("http://") or p.startswith("https://")):
                    # URL：下载图片 bytes（URL 来自管理员配置，风险可控）
                    import aiohttp  # noqa: PLC0415
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(p, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            resp.raise_for_status()
                            data = await resp.read()
                else:
                    data = await asyncio.to_thread(Path(p).read_bytes)
                if data:
                    out.append(data)
            except Exception as e:
                logger.warning("[_read_paths_bytes] 读取失败，跳过: %s %s", p, e)
                continue
        return out

    async def _image_segs_to_bytes(self, image_segs: list, timeout: float = 30.0) -> list[bytes]:
        """将 Image 组件列表转换为 bytes。每张图片最多等待 timeout 秒（防止 QQ 图片 URL 过期导致挂起）。"""
        out: list[bytes] = []
        for seg in image_segs:
            try:
                b64 = await asyncio.wait_for(seg.convert_to_base64(), timeout=timeout)
                out.append(decode_base64_image_payload(b64))
            except asyncio.TimeoutError:
                logger.warning(f"[图片] 获取超时（{timeout}s），可能是图片URL已过期，跳过")
            except Exception as e:
                logger.warning(f"[图片] 转换失败，跳过: {e}")
        return out

    async def _has_message_images(self, event: AstrMessageEvent) -> bool:
        """仅检测用户消息/引用里的图片（不含头像兜底）。"""
        image_segs = await get_images_from_event(event, include_avatar=False)
        return bool(image_segs)

    async def _classify_intent_with_llm(
        self, prompt: str, has_image: bool
    ) -> dict | None:
        """用 AstrBot 配置的 LLM 一次性判断意图和服务商。

        返回 {mode: edit|selfie_ref|None, backend: provider_id|None}
        未配置 intent_classifier.provider_id 时返回 None。
        """
        try:
            provider_id = (
                self._get_feature("intent_classifier")
                .get("provider_id", "") or ""
            ).strip()
            if not provider_id:
                return None

            video_keys = {"grok_video", "grok2api_video", "flow2api_video", "custom_video"}
            draw_provider_ids = [
                pid for pid in self.registry.provider_ids()
                if self.registry.get(pid).get("__template_key", "") not in video_keys
            ]
            providers_hint = (
                "可用服务商ID列表: " + ", ".join(draw_provider_ids)
                if draw_provider_ids else "(无可用服务商)"
            )
            image_hint = "(消息中包含图片)" if has_image else ""

            classify_prompt = chr(10).join([
                "用户消息" + image_hint + ": [" + prompt + "]",
                "",
                providers_hint,
                "",
                "请判断以下两项，用JSON格式回答，不要解释：",
                "1. mode: edit=改图本身 selfie_ref=Bot出镜 null=无法判断",
                "2. backend: 用户明确指定的服务商ID，未指定填null",
                "",
                '{"mode": "edit", "backend": null}',
            ])
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=(
                    "你是意图分类器，只输出JSON对象，含mode和backend两个字段。"
                ),
                prompt=classify_prompt,
            )
            raw = (response.completion_text or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            parsed = json.loads(raw)
            mode = parsed.get("mode")
            backend = parsed.get("backend")
            if mode not in ("edit", "selfie_ref", None):
                mode = None
            if backend and backend not in draw_provider_ids:
                backend = None
            logger.debug(
                "[aiimg] LLM分类: %r -> mode=%s backend=%s",
                prompt[:40], mode, backend,
            )
            return {"mode": mode, "backend": backend}
        except Exception as e:
            logger.warning("[aiimg] LLM分类失败，回退关键词: %s", e)
            return None

    def _is_auto_selfie_prompt(self, prompt: str) -> bool:
        """判断 prompt 是否明确指向 bot 出镜（自拍/参考图穿搭等场景）。

        核心逻辑：主语是 bot/你/她 + 动词是拍/穿/换/来一张 → selfie_ref
        即使消息里带有引用图片，只要意图主体是 bot，也应走 selfie_ref。
        """
        text = (prompt or "").strip()
        if not text:
            return False
        lowered = text.lower()

        # 明确自拍词
        if "自拍" in text or "selfie" in lowered:
            return True

        # bot 主语 + 出镜意图
        if any(k in text for k in (
            "来一张你", "来张你", "你来一张", "你来张",
            "看看你", "你自己", "你本人",
            "你的照片", "你的自拍", "你自己的照片", "你自己的自拍",
            "你长什么样", "看看你本人", "看看你自己",
            "bot自拍", "机器人自拍",
            # 穿搭/出镜类——必须足够精确，避免误伤「你换背景/你换滤镜」等改图请求
            "你穿",                          # 你穿这件/你穿上
            "你换上", "你换件", "你换套", "你换身",  # 精确：换衣服；排除「你换背景/你换滤镜」
            "你试试", "你来穿",
            "穿给我看", "穿上给我", "穿着拍", "穿这个拍",
            "穿上这个", "换上这个", "换上这件", "穿这件",
            "给我看看你", "给我看看她",
            "让她穿", "让你穿",
            "让她换上", "让你换上",          # 精确：换上；排除「让她换发色/让她换背景」
            "她穿上", "她换上", "她来一张", "她来张",
            "帮她拍", "帮你拍", "拍一张你", "拍张你",
        )):
            return True

        # 英文
        if any(k in lowered for k in (
            "your selfie", "your photo", "your picture", "your face",
            "wear this", "put this on", "try this on",
            "photo of you", "picture of you", "show me you",
        )):
            return True

        return False

    async def _should_auto_selfie_ref(
        self, event: AstrMessageEvent, prompt: str
    ) -> bool:
        # 优先用 LLM 分类（用户配置了意图分类模型时）
        has_image = bool(await get_images_from_event(event, include_avatar=False))
        llm_result = await self._classify_intent_with_llm(prompt, has_image=has_image)
        if llm_result is not None:
            if llm_result.get("mode") == "edit":
                logger.debug("[aiimg_generate] auto-selfie skipped: LLM classified as edit")
                return False
            elif llm_result.get("mode") == "selfie_ref":
                pass  # LLM 明确判断为自拍，继续检查参考图
            else:
                # mode=null（LLM 无法判断）→ 回退关键词检查
                if not self._is_auto_selfie_prompt(prompt):
                    logger.debug("[aiimg_generate] auto-selfie skipped: LLM null + no selfie keyword")
                    return False
        elif not self._is_auto_selfie_prompt(prompt):
            logger.debug("[aiimg_generate] auto-selfie skipped: prompt not selfie")
            return False  # LLM 未启用，回退关键词
        paths, source = await self._get_selfie_reference_paths(event)
        if not paths:
            logger.info("[aiimg_generate] auto-selfie skipped: no reference images")
            return False
        logger.debug(
            "[aiimg_generate] auto-selfie candidate: refs=%s source=%s",
            len(paths),
            source,
        )
        return True

    def _build_selfie_prompt(self, prompt: str, extra_refs: int) -> str:
        conf = self._get_selfie_conf()
        prefix = str(conf.get("prompt_prefix", "") or "").strip()
        if not prefix:
            prefix = (
                "请根据参考图生成一张新的自拍照：\n"
                "1) 以第1张参考图的人脸身份为准（仅人脸身份特征），保持五官/气质一致。\n"
                "2) 如果还有其它参考图，请将它们仅作为服装/姿势/构图/场景的参考。\n"
                "3) 输出一张高质量照片风格自拍，不要拼图，不要水印。"
            )

        # 融合当前人设的基础描述
        persona_base = self.persona_mgr.active.base_prompt.strip()
        if persona_base:
            prefix = f"{prefix}\n人物设定：{persona_base}"

        user_prompt = (prompt or "").strip() or "日常自拍照"
        if extra_refs > 0:
            return (
                f"{prefix}\n\n用户要求：{user_prompt}\n（额外参考图数量：{extra_refs}）"
            )
        return f"{prefix}\n\n用户要求：{user_prompt}"

    def _merge_selfie_chain_with_edit_chain(
        self, selfie_chain: list[object]
    ) -> list[dict]:
        """将自拍链路与改图链路合并（自拍优先，去重 provider_id）。"""
        merged: list[dict] = []
        seen: set[str] = set()

        def append_unique(items: list) -> None:
            for item in items:
                normalized = self._normalize_chain_item(item)
                if not normalized:
                    continue
                pid = str(normalized.get("provider_id") or "").strip()
                if not pid or pid in seen:
                    continue
                merged.append(normalized)
                seen.add(pid)

        append_unique(selfie_chain)

        edit_chain_raw = self._get_feature("edit").get("chain", [])
        if isinstance(edit_chain_raw, list):
            append_unique(edit_chain_raw)

        return merged

    async def _generate_selfie_image_with_meta(
        self,
        event: AstrMessageEvent,
        prompt: str,
        backend: str | None,
        *,
        size: str | None = None,
        resolution: str | None = None,
        follow_up_meta: dict[str, Any] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        conf = self._get_selfie_conf()
        if not self._is_selfie_enabled():
            raise RuntimeError(self._selfie_disabled_message())

        # 1) 读取参考照（WebUI 优先，其次命令设置的 store）
        ref_paths, ref_source = await self._get_selfie_reference_paths(event)
        ref_images = await self._read_paths_bytes(ref_paths)
        if not ref_images:
            raise RuntimeError(
                "未设置自拍参考照。请先：发送图片 + /自拍参考 设置，或在 WebUI 配置 features.selfie.reference_images 上传。"
            )

        # 2) 读取额外参考图（衣服/姿势/场景）
        extra_segs = await get_images_from_event(event, include_avatar=False)
        extra_bytes = await self._image_segs_to_bytes(extra_segs)

        # 3) 拼接输入图：参考照在前
        images = [*ref_images, *extra_bytes]

        effective_user_prompt = self._build_selfie_follow_up_prompt(
            prompt, follow_up_meta
        )
        final_prompt = self._build_selfie_prompt(
            effective_user_prompt, extra_refs=len(extra_bytes)
        )

        chain_override: list[dict] | None = None
        use_edit_chain = bool(conf.get("use_edit_chain_when_empty", True))
        raw_chain = conf.get("chain", [])
        if isinstance(raw_chain, list):
            chain_items = [
                normalized
                for normalized in (self._normalize_chain_item(x) for x in raw_chain)
                if normalized is not None
            ]
            if chain_items:
                chain_override = chain_items

        if backend is None:
            if chain_override is None:
                if not use_edit_chain:
                    raise RuntimeError(
                        "No selfie provider chain configured. Please set features.selfie.chain or enable features.selfie.use_edit_chain_when_empty."
                    )
            elif use_edit_chain:
                # 自拍链路可作为主链，改图链路作为补充兜底，避免“自拍链仅一项导致无兜底”。
                chain_override = self._merge_selfie_chain_with_edit_chain(
                    chain_override
                )

        if chain_override:
            logger.debug(
                "[selfie] effective providers=%s",
                [
                    str(x.get("provider_id") or "").strip()
                    for x in chain_override
                    if isinstance(x, dict)
                ],
            )

        # 4) 千问后端可选 task_types（仅对 gitee 生效）
        task_types = conf.get("gitee_task_types")
        if isinstance(task_types, list) and task_types:
            gitee_task_types = [str(x).strip() for x in task_types if str(x).strip()]
        else:
            gitee_task_types = ["id", "background", "style"]

        default_output = str(conf.get("default_output") or "").strip() or None

        image_path, _prov_tries = await self.edit.edit(
            prompt=final_prompt,
            images=images,
            backend=backend,
            task_types=gitee_task_types,
            size=size,
            resolution=resolution,
            default_output=default_output,
            chain_override=chain_override,
        )
        task_meta = self._build_image_task_meta(
            mode="selfie_ref",
            user_prompt=prompt,
            effective_user_prompt=effective_user_prompt,
            effective_prompt=final_prompt,
            reference_source=ref_source,
            reference_count=len(ref_images),
            extra_reference_count=len(extra_bytes),
            continue_with="selfie_ref",
            follow_up=follow_up_meta is not None,
            backend=backend,
        )
        task_meta["provider_tries"] = _prov_tries
        return image_path, task_meta

    async def _generate_selfie_image(
        self,
        event: AstrMessageEvent,
        prompt: str,
        backend: str | None,
        *,
        size: str | None = None,
        resolution: str | None = None,
    ) -> Path:
        image_path, _ = await self._generate_selfie_image_with_meta(
            event,
            prompt,
            backend,
            size=size,
            resolution=resolution,
        )
        return image_path