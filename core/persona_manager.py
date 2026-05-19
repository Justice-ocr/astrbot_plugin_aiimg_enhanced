"""
Gitee AI Image 插件 - 多人设管理器
支持多套人设（ID、名称、基础描述、参考图组），
兼容单人设旧版配置格式。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from astrbot.api import logger


@dataclass
class PersonaProfile:
    """单套人设"""
    id: str
    name: str
    base_prompt: str
    ref_images: list[str] = field(default_factory=list)


class PersonaManager:
    """多人设管理，负责解析配置、切换人设、构建自拍 prompt 前缀。"""

    DEFAULT_PERSONA_ID = "default"
    DEFAULT_PERSONA_NAME = "默认助理"

    def __init__(self, config: dict, data_dir: str):
        self.data_dir = data_dir
        self._personas: list[PersonaProfile] = []
        self._active_id: str = self.DEFAULT_PERSONA_ID
        self._load(config)

    # ── 解析 ──────────────────────────────────────────────────────────────────

    def _load(self, config: dict) -> None:
        persona_conf = config.get("persona_config") if isinstance(config, dict) else {}
        if not isinstance(persona_conf, dict):
            persona_conf = {}

        raw_profiles = persona_conf.get("profiles")
        # 旧格式兼容：若无 profiles 则从顶层字段构建单人设
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raw_profiles = [
                {
                    "id": persona_conf.get("active_persona_id") or self.DEFAULT_PERSONA_ID,
                    "persona_name": persona_conf.get("persona_name", self.DEFAULT_PERSONA_NAME),
                    "persona_base_prompt": persona_conf.get("persona_base_prompt", ""),
                    "persona_ref_image": persona_conf.get("persona_ref_image", []),
                }
            ]

        used_ids: set[str] = set()
        profiles: list[PersonaProfile] = []
        for idx, raw in enumerate(raw_profiles):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("persona_name") or raw.get("name") or "").strip()
            if not name:
                name = self.DEFAULT_PERSONA_NAME if idx == 0 else f"人设 {idx + 1}"
            pid = self._normalize_id(raw.get("id", ""), name, idx, used_ids)
            base_prompt = str(raw.get("persona_base_prompt") or raw.get("base_prompt") or "").strip()
            ref_images = self._resolve_ref_images(raw.get("persona_ref_image") or raw.get("ref_images") or [])
            profiles.append(PersonaProfile(id=pid, name=name, base_prompt=base_prompt, ref_images=ref_images))

        if not profiles:
            profiles.append(PersonaProfile(
                id=self.DEFAULT_PERSONA_ID, name=self.DEFAULT_PERSONA_NAME,
                base_prompt="", ref_images=[],
            ))

        self._personas = profiles
        active_id = str(persona_conf.get("active_persona_id") or "").strip()
        self._active_id = self._find_valid_id(active_id) or profiles[0].id

    def _normalize_id(self, raw: Any, name: str, idx: int, used: set[str]) -> str:
        candidate = str(raw or "").strip()
        if not candidate:
            candidate = "default" if idx == 0 else name
        candidate = re.sub(r"[^a-zA-Z0-9_\-]+", "_", candidate).strip("_").lower()
        if not candidate:
            candidate = "default" if idx == 0 else f"persona_{idx + 1}"
        base = candidate
        n = 2
        while candidate in used:
            candidate = f"{base}_{n}"
            n += 1
        used.add(candidate)
        return candidate

    def _resolve_ref_images(self, raw: Any) -> list[str]:
        """将 files/… 相对路径解析为绝对路径，并验证本地文件存在。"""
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [raw]
        result: list[str] = []
        for item in raw:
            ref = str(item or "").strip()
            if not ref:
                continue
            if ref.startswith("http://") or ref.startswith("https://"):
                result.append(ref)
                continue
            if ref.startswith("files/") or ref.startswith("data/"):
                # AstrBot 插件数据目录下的相对路径
                abs_path = os.path.join(self.data_dir, ref)
                if os.path.isfile(abs_path):
                    result.append(abs_path)
                elif os.path.isfile(ref):
                    result.append(ref)
                else:
                    logger.warning("[PersonaManager] 参考图不存在: %s", ref)
            elif os.path.isfile(ref):
                result.append(ref)
            else:
                # 尝试当作相对路径
                abs_path = os.path.join(self.data_dir, ref)
                if os.path.isfile(abs_path):
                    result.append(abs_path)
                else:
                    logger.warning("[PersonaManager] 参考图不存在: %s", ref)
        return result

    def _find_valid_id(self, pid: str) -> str:
        for p in self._personas:
            if p.id == pid or p.id.lower() == pid.lower():
                return p.id
        return ""

    # ── 查询 ─────────────────────────────────────────────────────────────────

    @property
    def active(self) -> PersonaProfile:
        for p in self._personas:
            if p.id == self._active_id:
                return p
        return self._personas[0]

    @property
    def all_personas(self) -> list[PersonaProfile]:
        return list(self._personas)

    def get_persona(self, persona_id: str) -> PersonaProfile | None:
        for p in self._personas:
            if p.id == persona_id or p.id.lower() == persona_id.lower():
                return p
        return None

    def find_by_name_or_id(self, selector: str) -> PersonaProfile | None:
        selector = selector.strip()
        # 精确 ID 匹配
        for p in self._personas:
            if p.id == selector or p.id.lower() == selector.lower():
                return p
        # 名称匹配
        for p in self._personas:
            if p.name == selector:
                return p
        # 序号匹配（1-based）
        try:
            idx = int(selector) - 1
            if 0 <= idx < len(self._personas):
                return self._personas[idx]
        except ValueError:
            pass
        return None

    # ── 切换 ─────────────────────────────────────────────────────────────────

    def switch(self, selector: str) -> PersonaProfile | None:
        """切换到目标人设，成功返回新人设，失败返回 None。"""
        target = self.find_by_name_or_id(selector)
        if target:
            self._active_id = target.id
        return target

    # ── 自拍参考图路径 ────────────────────────────────────────────────────────

    def get_active_ref_paths(self) -> list[str]:
        """返回当前人设有效的参考图路径列表。"""
        paths: list[str] = []
        for ref in self.active.ref_images:
            if ref.startswith("http://") or ref.startswith("https://"):
                paths.append(ref)
            elif os.path.isfile(ref):
                paths.append(ref)
            else:
                logger.warning("[PersonaManager] 参考图已失效，跳过: %s", ref)
        return paths

    # ── 格式化 /人设 列表消息 ─────────────────────────────────────────────────

    def format_list_message(self) -> str:
        lines = ["🎭 人设列表", "━━━━━━━━━━━━━━"]
        for i, p in enumerate(self._personas, 1):
            active_mark = " ◀ 当前" if p.id == self._active_id else ""
            ref_count = len(p.ref_images)
            lines.append(f"{i}. [{p.id}] {p.name}（参考图 {ref_count} 张）{active_mark}")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("切换：/切换人设 [序号/ID/名称]")
        return "\n".join(lines)

    # ── 序列化（供 Pages 和 context.update_config 用）─────────────────────────

    def to_config_dict(self) -> dict:
        profiles = []
        for p in self._personas:
            profiles.append({
                "id": p.id,
                "persona_name": p.name,
                "persona_base_prompt": p.base_prompt,
                "persona_ref_image": list(p.ref_images),
            })
        return {
            "active_persona_id": self._active_id,
            "persona_name": self.active.name,
            "persona_base_prompt": self.active.base_prompt,
            "persona_ref_image": list(self.active.ref_images),
            "profiles": profiles,
        }
