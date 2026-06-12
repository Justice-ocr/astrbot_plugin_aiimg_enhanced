"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
import base64
import mimetypes
import pathlib
import re
from quart import jsonify, request, send_file
from astrbot.api import logger
import asyncio
import time
from pathlib import Path
from ..core.persona_manager import PersonaManager

class PagesAPIMixin:
    def _register_pages_web_api(self) -> None:
        register_web_api = getattr(self.context, "register_web_api", None)
        if not callable(register_web_api):
            logger.warning(
                "[GiteeAIImagePlugin] context.register_web_api unavailable; "
                "settings page APIs are not registered"
            )
            return

        _pid = "astrbot_plugin_aiimg_enhanced"
        routes = [
            ("get_config", self._pages_get_config, ["GET"], "获取 AI绘图站 插件配置"),
            ("save_config", self._pages_save_config, ["POST"], "保存 AI绘图站 插件配置"),
            ("get_persona", self._pages_get_persona, ["GET"], "获取人设信息"),
            ("switch_persona", self._pages_switch_persona, ["POST"], "切换人设"),
            ("get_image", self._pages_get_image, ["GET"], "获取本地参考图预览"),
            ("get_image_b64", self._pages_get_image_b64, ["GET"], "获取本地参考图base64（bridge用）"),
            (
                "upload_ref_image",
                self._pages_upload_ref_image,
                ["POST"],
                "上传人设参考图",
            ),

        ]
        for name, handler, methods, desc in routes:
            register_web_api(f"/{_pid}/{name}", handler, methods, desc)


    def _check_path_safe(self, path: str):
        """检查路径合法性，返回 (Path, None) 或 (None, error_response_tuple)。"""
        p = pathlib.Path(path)
        try:
            p.resolve().relative_to(pathlib.Path(self.data_dir).resolve())
        except ValueError:
            return None, (jsonify({"success": False, "error": "禁止访问"}), 403)
        if not p.is_file():
            return None, (jsonify({"success": False, "error": "文件不存在"}), 404)
        return p, None

    async def _pages_get_config(self):
        """GET /astrbot_plugin_aiimg_enhanced/get_config"""
        try:
            payload = dict(self.config) if isinstance(self.config, dict) else {}
            payload["persona_config"] = self.persona_mgr.to_config_dict()
            # AstrBot Chat provider 列表，供前端意图分类下拉框使用
            try:
                astrbot_providers = [
                    {"id": p.meta().id, "model": p.meta().model or ""}
                    for p in (self.context.get_all_providers() or [])
                ]
            except Exception:
                astrbot_providers = []
            payload["astrbot_providers"] = astrbot_providers
            return jsonify({"success": True, "config": payload})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    def _inline_persona_ref_images(self, payload: dict) -> None:
        """把 persona_config 里所有本地路径的参考图转成 base64 data URL。
        文件不存在或读取失败则保留原路径（前端会显示占位符）。
        """
        PAGE_MAX_INLINE = 2 * 1024 * 1024  # 2MB 以内直接内联 base64，超出保留路径
        persona_cfg = payload.get("persona_config")
        if not isinstance(persona_cfg, dict):
            return

        def inline_refs(refs: list) -> list:
            result = []
            for ref in refs:
                ref = str(ref or "").strip()
                if not ref:
                    continue
                if ref.startswith(("data:image", "http://", "https://")):
                    result.append(ref)
                    continue
                try:
                    p = pathlib.Path(ref)
                    if not p.is_file():
                        result.append(ref)
                        continue
                    if p.stat().st_size > PAGE_MAX_INLINE:
                        result.append(ref)  # 太大，保留路径（前端 bridge fallback 处理）
                        continue
                    mime = mimetypes.guess_type(str(p))[0] or "image/png"
                    b64 = base64.b64encode(p.read_bytes()).decode()
                    result.append(f"data:{mime};base64,{b64}")
                except Exception:
                    result.append(ref)
            return result

        # 处理各人设的 persona_ref_image
        for profile in persona_cfg.get("profiles") or []:
            if isinstance(profile, dict):
                profile["persona_ref_image"] = inline_refs(
                    profile.get("persona_ref_image") or []
                )
        # 处理全局 persona_ref_image
        if "persona_ref_image" in persona_cfg:
            persona_cfg["persona_ref_image"] = inline_refs(
                persona_cfg.get("persona_ref_image") or []
            )


    async def _pages_save_config(self):
        """POST /astrbot_plugin_aiimg_enhanced/save_config"""
        try:
            data = await request.get_json(force=True) or {}
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "无效的 JSON 数据"})

            if not isinstance(self.config, dict):
                self.config = {}

            # 深度合并：features 用逐子项 update，避免覆盖 chain/gitee_task_types 等前端未展示的字段
            if "features" in data and isinstance(data["features"], dict):
                cfg_feats = self.config.setdefault("features", {})
                for feat_key, feat_val in data["features"].items():
                    if isinstance(feat_val, dict) and isinstance(cfg_feats.get(feat_key), dict):
                        cfg_feats[feat_key].update(feat_val)
                    else:
                        cfg_feats[feat_key] = feat_val

            # 标量 / 简单字段直接覆盖
            for key in ("storage", "debounce_interval", "max_user_concurrency",
                        "max_user_video_concurrency", "network", "reply_config"):
                if key in data:
                    self.config[key] = data[key]

            # providers: 把前端的 __type 转换为 __template_key（registry所需），再保存
            providers_changed = False
            if "providers" in data and isinstance(data["providers"], list):
                clean_providers = []
                for p in data["providers"]:
                    if isinstance(p, dict):
                        cleaned = {k: v for k, v in p.items() if k != "__type"}
                        if "__template_key" not in cleaned and "__type" in p:
                            cleaned["__template_key"] = p["__type"]
                        clean_providers.append(cleaned)
                self.config["providers"] = clean_providers
                providers_changed = True

            # persona_config：先把 base64 参考图转存为本地文件，再替换
            if "persona_config" in data:
                pc = data["persona_config"]
                if isinstance(pc, dict):
                    for profile in pc.get("profiles") or []:
                        if isinstance(profile, dict):
                            profile["persona_ref_image"] = await self._save_base64_refs(
                                profile.get("persona_ref_image") or []
                            )
                self.config["persona_config"] = pc
                self.persona_mgr = PersonaManager(self.config, self.data_dir)

            # providers有变化时热重载 registry（draw/edit同一引用，自动生效）
            if providers_changed:
                # 精确清理：只清掉配置发生变化或被删除的 provider 的 backend 缓存
                # 保留未变更的 backend 实例，避免重建连接池
                new_providers = {
                    str(p.get("id") or "").strip(): p
                    for p in (self.config.get("providers") or [])
                    if isinstance(p, dict) and str(p.get("id") or "").strip()
                }
                old_provider_ids = set(self.registry._providers.keys())
                for pid in list(old_provider_ids):
                    old_conf = self.registry._providers.get(pid)
                    new_conf = new_providers.get(pid)
                    if new_conf is None or old_conf != new_conf:
                        # 删除或配置有变化 → 清对应 backend 缓存
                        self.registry._backends.pop(pid, None)
                        self.registry._video_backends.pop(pid, None)
                # 新增的 provider 不需要提前清，懒加载即可
                self.registry._providers.clear()
                self.registry._load_providers()
                logger.info("[AI绘图站] Registry 已热重载，providers=%s",
                            list(self.registry._providers.keys()))
                # 服务商列表变了，同步更新工具描述
                self._update_llm_tool_descriptions()

            # 对齐 omnidraw：先写 JSON 持久化，再同步到 native config
            self._safe_update_config()
            logger.info("[AI绘图站] 配置已持久化并热重载")

            return jsonify({
                "success": True,
                "active_persona": {
                    "id": self.persona_mgr.active.id,
                    "name": self.persona_mgr.active.name,
                }
            })
        except Exception as e:
            logger.error("[Pages] save_config 失败: %s", e, exc_info=True)
            return jsonify({"success": False, "error": str(e)})


    async def _pages_get_persona(self):
        """GET /astrbot_plugin_aiimg_enhanced/get_persona"""
        try:
            personas = []
            for p in self.persona_mgr.all_personas:
                personas.append({
                    "id": p.id,
                    "name": p.name,
                    "base_prompt": p.base_prompt,
                    "ref_images": p.ref_images,
                    "ref_count": len(p.ref_images),
                    "active": p.id == self.persona_mgr.active.id,
                })
            return jsonify({
                "success": True,
                "active_id": self.persona_mgr.active.id,
                "personas": personas,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})


    async def _pages_switch_persona(self):
        """POST /astrbot_plugin_aiimg_enhanced/switch_persona  { "id": "..." }"""
        try:
            data = await request.get_json(force=True) or {}
            selector = str(data.get("id") or data.get("selector") or "").strip()
            if not selector:
                return jsonify({"success": False, "error": "缺少 id 参数"})
            target = self.persona_mgr.switch(selector)
            if not target:
                return jsonify({"success": False, "error": f"找不到人设: {selector}"})
            # 对齐 omnidraw：_set_active_persona → _persist_config → _safe_update_context_config
            if isinstance(self.config, dict):
                self.config.setdefault("persona_config", {})["active_persona_id"] = target.id
            self._safe_update_config()
            return jsonify({"success": True, "active": {"id": target.id, "name": target.name}})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})


    async def _pages_get_image(self):
        """GET /astrbot_plugin_aiimg_enhanced/get_image?path=<abs_path>&token=<token>"""
        try:
            path = str(request.args.get("path") or "").strip()
            if not path:
                return jsonify({"success": False, "error": "缺少 path 参数"}), 400
            p, err = self._check_path_safe(path)
            if err is not None:
                return err
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
            return await send_file(str(p), mimetype=mime)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


    async def _pages_get_image_b64(self):
        """GET /astrbot_plugin_aiimg_enhanced/get_image_b64?path=<abs_path>
        通过 bridge.apiGet 调用，返回 {success, image_data: "data:image/...;base64,..."}。

        不使用顶层 data 字段，因为 AstrBot Pages Bridge 会自动解包该字段。
        """
        try:
            path = str(request.args.get("path") or "").strip()
            return await self._pages_image_b64_response(path)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    async def _pages_image_b64_response(self, path: str):
        if not path:
            return jsonify({"success": False, "error": "缺少 path 参数"}), 400
        p, err = self._check_path_safe(path)
        if err is not None:
            return err
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        raw = await asyncio.to_thread(p.read_bytes)
        b64 = base64.b64encode(raw).decode()
        return jsonify({
            "success": True,
            "image_data": f"data:{mime};base64,{b64}",
        })

    async def _save_base64_refs(self, refs: list) -> list:
        """把 persona_ref_image 列表里的 base64 data URL 转存为本地文件，返回替换后的列表。"""
        ref_dir = pathlib.Path(self.data_dir) / "persona_refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for ref in refs:
            ref = str(ref or "").strip()
            if not ref:
                continue
            if ref.startswith("data:image"):
                try:
                    # data:image/jpeg;base64,XXXX
                    m = re.match(r"data:(image/[^;]+);base64,(.+)", ref, re.DOTALL)
                    if not m:
                        continue
                    mime, b64data = m.group(1), m.group(2)
                    raw = base64.b64decode(b64data)
                    if len(raw) > 20 * 1024 * 1024:
                        logger.warning("[AI绘图站] base64参考图超过20MB，跳过")
                        continue
                    ext = mime.split("/")[-1].replace("jpeg", "jpg")
                    fname = f"{int(time.time()*1000)}.{ext}"
                    save_path = ref_dir / fname
                    await asyncio.to_thread(save_path.write_bytes, raw)
                    result.append(str(save_path))
                    logger.info("[AI绘图站] base64参考图已转存: %s", save_path)
                except Exception as e:
                    logger.warning("[AI绘图站] base64参考图转存失败: %s", e)
            else:
                result.append(ref)
        return result


    async def _pages_upload_ref_image(self):
        """POST /astrbot_plugin_aiimg_enhanced/upload_ref_image
        multipart/form-data: file=<image>
        返回: { success, path, filename }
        """
        try:
            files = await request.files
            file = files.get("file")
            if file is None:
                return jsonify({"success": False, "error": "未收到文件"}), 400

            filename = pathlib.Path(file.filename or "upload").name
            ext = pathlib.Path(filename).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                return jsonify({"success": False, "error": f"不支持的文件格式: {ext}"}), 400

            ref_dir = pathlib.Path(self.data_dir) / "persona_refs"
            ref_dir.mkdir(parents=True, exist_ok=True)

            safe_name = f"{int(time.time() * 1000)}_{filename}"
            save_path = ref_dir / safe_name

            data = file.read()
            if len(data) > 20 * 1024 * 1024:
                return jsonify({"success": False, "error": "文件大小超过 20MB 限制"}), 400

            await asyncio.to_thread(save_path.write_bytes, data)
            logger.info("[AI绘图站] 参考图已上传: %s", save_path)

            return jsonify({
                "success": True,
                "path": str(save_path),
                "filename": safe_name,
            })
        except Exception as e:
            logger.error("[Pages] upload_ref_image 失败: %s", e, exc_info=True)
            return jsonify({"success": False, "error": str(e)}), 500
