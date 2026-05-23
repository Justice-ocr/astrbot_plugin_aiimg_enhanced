"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
from ..core.utils import get_images_from_event
from ..core.emoji_feedback import mark_failed, mark_processing, mark_success
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api import logger
import asyncio
import time

class EditCommandsMixin:
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
            await mark_failed(event)
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
            await mark_failed(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)
        if not bytes_images:
            await mark_failed(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
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
            image_path = await self.edit.edit(
                prompt=prompt,
                images=bytes_images,
                backend=backend,
                preset=preset,
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path)
            if not sent:
                await mark_failed(event)
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
        finally:
            await self._end_user_job(user_id, kind="image")


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
            await mark_failed(event)
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
        image_segs = await get_images_from_event(
            event,
            include_avatar=True,
            include_sender_avatar_fallback=False,
        )
        if not image_segs:
            await mark_failed(event)
            return

        bytes_images = await self._image_segs_to_bytes(image_segs)

        if not bytes_images:
            await mark_failed(event)
            return

        if not await self._begin_user_job(user_id, kind="image"):
            await mark_failed(event)
            return

        try:
            # 发送等待提示，同时贴处理中表情
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_edit(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
            t_start = time.perf_counter()
            image_path = await self.edit.edit(
                prompt=prompt,
                images=bytes_images,
                backend=backend,
                preset=preset,
            )
            t_end = time.perf_counter()

            self._remember_last_image(event, image_path)
            sent = await self._send_image_with_fallback(event, image_path)
            if not sent:
                await mark_failed(event)
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
        finally:
            await self._end_user_job(user_id, kind="image")

    # ==================== 自拍参考照：内部实现 ====================