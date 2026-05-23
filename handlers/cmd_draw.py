"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
from ..core.emoji_feedback import mark_failed, mark_processing, mark_success
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import logger
import asyncio
import time

class DrawCommandsMixin:
    @filter.command("文生图")
    async def generate_image_with_presets(self, event: AstrMessageEvent):
        """支持文生图预设的图片生成命令。"""
        parsed = self._parse_structured_image_request(event.message_str)
        if parsed is None or parsed.spec.source_command != "文生图":
            await mark_failed(event)
            return

        spec = parsed.spec
        if not str(spec.effective_prompt or "").strip():
            await mark_failed(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "draw_preset", user_id)
        if self.debouncer.hit(request_id):
            await mark_failed(event)
            return
        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
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
            executed = await self._execute_image_task_spec(event, spec)
            self._remember_last_image(event, executed.image_path)
            sent = await self._send_image_with_fallback(event, executed.image_path)
            if not sent:
                await mark_failed(event)
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
            await mark_failed(event)
            return
        provider_override: str | None = None
        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await mark_failed(event)
            return

        prompt = arg.strip()
        size: str | None = None
        parts = arg.split()
        if parts and parts[-1] in self.SUPPORTED_RATIOS:
            ratio = parts[-1]
            prompt = " ".join(parts[:-1]).strip()
            size = self._resolve_ratio_size(ratio)

        if not prompt:
            await mark_failed(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "generate", user_id)

        # 防抖检查
        if self.debouncer.hit(request_id):
            await mark_failed(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
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
            image_path = await self.draw.generate(
                prompt, size=size, provider_id=provider_override
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path)
            if not sent:
                await mark_failed(event)
                logger.warning(
                    "[文生图] 图片发送失败，已仅使用表情标注: reason=%s", sent.reason
                )
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


    @filter.regex(r"[/!！.。．]批量(?:\s*\d+|\d+)(?:\s|$)", priority=-10)
    async def batch_image_command(self, event: AstrMessageEvent):
        """批量图片任务入口。"""
        fragment = self._extract_batch_command_fragment(event.message_str)
        parsed = self._parse_structured_image_request(fragment)
        if parsed is None or parsed.batch_count <= 1:
            await mark_failed(event)
            return
        if parsed.batch_count > self._get_batch_max_count():
            await event.send(
                event.plain_result(
                    f"批量数量过大，当前上限为 {self._get_batch_max_count()}。"
                )
            )
            await mark_failed(event)
            return

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "batch_image", user_id)
        if self.debouncer.hit(request_id):
            await mark_failed(event)
            return
        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
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