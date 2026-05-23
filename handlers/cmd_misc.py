"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
from ..core.emoji_feedback import mark_failed, mark_success
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import logger
from pathlib import Path

class MiscCommandsMixin:
    @filter.command("重发图片")
    async def resend_last_image(self, event: AstrMessageEvent):
        """重发最近一次生成/改图的图片（不重新生成，不消耗次数）。"""
        user_id = str(event.get_sender_id() or "")
        p = self._last_image_by_user.get(user_id)
        if not p:
            await mark_failed(event)
            event.stop_event()
            return
        if not Path(p).exists():
            await mark_failed(event)
            event.stop_event()
            return
        ok = await self._send_image_with_fallback(event, p)
        if ok:
            await mark_success(event)
        else:
            await mark_failed(event)


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