"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
from astrbot.api.event import AstrMessageEvent
from ..core.image_task_parser import ImageTaskSpec

class LLMToolsMixin:
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
            prompt(string): selfie_ref时描述想要的效果/服装/场景；edit时描述如何修改图片；text时描述生成内容
            mode(string): selfie_ref=bot自拍（图片为参考素材）, edit=改图（图片为被改对象）, text=文生图, auto=自动判断
            backend(string): auto=自动选择；也可填服务商ID（如 ccode、jojocode）
            output(string): 输出尺寸，例如 2048x2048 或 4K，留空用默认
        """
        prompt = (prompt or "").strip()
        m = (mode or "auto").strip().lower()

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

        # 方案 B：如果用户在对话里说"@ccode 画一只猫"，LLM 会把 "@ccode 画一只猫" 原样
        # 作为 prompt 传进来，此处解析出 @provider_id 前缀并转为 backend 覆盖
        provider_from_prompt, prompt = self._parse_provider_override_prefix(prompt)
        if provider_from_prompt and (not backend or backend.lower() == "auto"):
            backend = provider_from_prompt
            logger.debug("[aiimg_generate] 从 prompt 解析出 backend=%s", backend)

        b_raw = (backend or "auto").strip()
        known_provider_ids = set(self.registry.provider_ids())
        if not b_raw or b_raw.lower() == "auto":
            target_backend = None
        elif b_raw in known_provider_ids:
            target_backend = b_raw
        else:
            logger.warning(
                "[aiimg_generate] 忽略未知 backend 覆盖，回退自动链路: backend=%s",
                b_raw,
            )
            target_backend = None

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
                    event, image_path, task_meta=task_meta
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
                            event, image_path, task_meta=task_meta
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
                            event, image_path, task_meta=task_meta
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
                image_path = await self.edit.edit(
                    prompt=prompt,
                    images=bytes_images,
                    backend=target_backend,
                    size=size,
                    resolution=resolution,
                )
                task_meta = self._build_image_task_meta(
                    mode="edit",
                    user_prompt=prompt,
                    effective_prompt=prompt,
                    continue_with="edit",
                    backend=target_backend,
                )
                return await self._finalize_llm_tool_image(
                    event, image_path, task_meta=task_meta
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
            image_path = await self.draw.generate(
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
                event, image_path, task_meta=task_meta
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
            prompt(string): 用户的总要求。应包含整组图片共同要满足的条件。
            count(number): 目标数量。建议 2-8。
            mode(string): auto=自动判断, text=文生图, edit=改图, selfie_ref=参考照自拍
            backend(string): auto=自动选择；也可填 provider_id（你在 WebUI providers 里配置的 id）
            output(string): 输出尺寸/分辨率。例: 2048x2048 或 4K（不同后端支持能力不同，留空用默认）
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