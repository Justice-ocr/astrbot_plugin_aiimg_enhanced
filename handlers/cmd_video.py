"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations

class VideoCommandsMixin:
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
        event.should_call_llm(True)
        if not bool(self._get_feature("video").get("enabled", False)):
            await mark_failed(event)
            return
        arg = self._extract_extra_prompt(event, "视频")
        if not arg:
            await mark_failed(event)
            return

        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await mark_failed(event)
            return

        preset, prompt = self._parse_video_args(arg)
        presets = self._get_video_presets()
        if preset and preset in presets:
            preset_prompt = presets[preset]
            prompt = f"{preset_prompt}, {prompt}" if prompt else preset_prompt

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "video", user_id)

        if self.debouncer.hit(request_id):
            await mark_failed(event)
            return

        if not await self._video_begin(user_id):
            await mark_failed(event)
            return

        try:
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_video(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
        except Exception:
            await self._video_end(user_id)
            await mark_failed(event)
            return

        try:
            task = asyncio.create_task(
                self._async_generate_video(
                    event, prompt, user_id, provider_id=provider_override
                )
            )
        except Exception:
            await self._video_end(user_id)
            await mark_failed(event)
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

        event.should_call_llm(True)
        if not bool(self._get_feature("video").get("enabled", False)):
            await mark_failed(event)
            event.stop_event()
            return
        if not arg:
            await mark_failed(event)
            event.stop_event()
            return

        provider_override, arg = self._parse_provider_override_prefix(arg)
        if not arg:
            await mark_failed(event)
            event.stop_event()
            return

        preset, prompt = self._parse_video_args(arg)
        presets = self._get_video_presets()
        if preset and preset in presets:
            preset_prompt = presets[preset]
            prompt = f"{preset_prompt}, {prompt}" if prompt else preset_prompt

        user_id = str(event.get_sender_id() or "")
        request_id = self._debounce_key(event, "video", user_id)

        if self.debouncer.hit(request_id):
            await mark_failed(event)
            event.stop_event()
            return

        if not await self._video_begin(user_id):
            await mark_failed(event)
            event.stop_event()
            return

        try:
            await asyncio.gather(
                event.send(event.plain_result(self._pending_msg_video(prompt))),
                mark_processing(event),
                return_exceptions=True,
            )
        except Exception:
            await self._video_end(user_id)
            await mark_failed(event)
            event.stop_event()
            return

        try:
            task = asyncio.create_task(
                self._async_generate_video(
                    event, prompt, user_id, provider_id=provider_override
                )
            )
        except Exception:
            await self._video_end(user_id)
            await mark_failed(event)
            event.stop_event()
            return

        self._video_tasks.add(task)
        task.add_done_callback(lambda t: self._video_tasks.discard(t))
        event.stop_event()
        return


    @filter.command("视频预设列表")
    async def list_video_presets(self, event: AstrMessageEvent):
        """列出所有可用视频预设"""
        event.should_call_llm(True)
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
                    await mark_failed(event)
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
