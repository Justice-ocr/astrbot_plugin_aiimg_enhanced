"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image

class SelfieCommandsMixin:
    @filter.command("自拍")
    async def selfie_command(self, event: AstrMessageEvent):
        """使用“自拍参考照”生成 Bot 自拍。

        用法:
        - /自拍 <提示词>
        - 可附带多张参考图（衣服/姿势/场景）作为额外参考
        """
        if not self._is_selfie_enabled():
            await mark_failed(event)
            return
        event.should_call_llm(True)
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
                await mark_failed(event)
                event.stop_event()
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
        event.should_call_llm(True)
        if not self._is_selfie_enabled():
            await mark_failed(event)
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


    @filter.regex(r"[/!！.。．]自拍参考(\s|$)", priority=-10)
    async def selfie_reference_regex_fallback(self, event: AstrMessageEvent):
        """兼容“图片在前、文字在后”的消息：确保 /自拍参考 能触发。"""
        msg = (event.message_str or "").strip()
        if self._is_direct_command_message(event, ("自拍参考",)):
            return
        if not self._is_selfie_enabled():
            await mark_failed(event)
            event.stop_event()
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
            await mark_failed(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "selfie", user_id)

        if self.debouncer.hit(request_id):
            await mark_failed(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
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

            image_path, task_meta = await self._generate_selfie_image_with_meta(
                event, prompt, backend
            )
            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path)
            if not sent:
                await mark_failed(event)
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


    async def _set_selfie_reference(self, event: AstrMessageEvent):
        if not self._is_selfie_enabled():
            await mark_failed(event)
            return

        image_segs = await get_images_from_event(event, include_avatar=False)
        if not image_segs:
            await mark_failed(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)
        if not bytes_images:
            await mark_failed(event)
            return

        # 限制数量，避免一次塞太多
        max_images = 8
        bytes_images = bytes_images[:max_images]

        store_key = self._get_selfie_ref_store_key(event)
        try:
            await self.refs.set(store_key, bytes_images)
        except Exception:
            await mark_failed(event)
            return

        await mark_success(event)


    async def _show_selfie_reference(self, event: AstrMessageEvent):
        if not self._is_selfie_enabled():
            await mark_failed(event)
            return

        paths, source = await self._get_selfie_reference_paths(event)
        if not paths:
            await mark_failed(event)
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
            await mark_failed(event)
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