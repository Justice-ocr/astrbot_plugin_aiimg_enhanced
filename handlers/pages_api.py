"""Auto-split from main.py — mixin class, do not use standalone."""
from __future__ import annotations
import inspect
import pathlib
from quart import jsonify, request
from astrbot.api import logger
from ..core.persona_manager import PersonaManager
from ..core.pages_config_service import PagesConfigService
from ..core.persona_ref_service import PersonaRefService

class PagesAPIMixin:
    _REF_IMAGE_MAX_BYTES = 20 * 1024 * 1024

    def _persona_ref_service(self) -> PersonaRefService:
        return PersonaRefService(self.data_dir)

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
            ("get_image_b64", self._pages_get_image_b64, ["GET"], "获取本地参考图base64（bridge用）"),
            (
                "upload_ref_image",
                self._pages_upload_ref_image,
                ["POST"],
                "上传人设参考图",
            ),
            (
                "upload_ref_image_b64",
                self._pages_upload_ref_image_b64,
                ["POST"],
                "上传人设参考图（base64 fallback）",
            ),

        ]
        for name, handler, methods, desc in routes:
            register_web_api(f"/{_pid}/{name}", handler, methods, desc)

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

    async def _pages_save_config(self):
        """POST /astrbot_plugin_aiimg_enhanced/save_config"""
        try:
            data = await request.get_json(force=True) or {}
            if not isinstance(data, dict):
                return jsonify({"success": False, "error": "无效的 JSON 数据"})

            if not isinstance(self.config, dict):
                self.config = {}

            apply_result = PagesConfigService(self.config).apply_payload(data)

            # persona_config：先把 base64 参考图转存为本地文件，再替换
            if "persona_config" in data:
                pc = data["persona_config"]
                if isinstance(pc, dict):
                    ref_service = self._persona_ref_service()
                    for profile in pc.get("profiles") or []:
                        if isinstance(profile, dict):
                            profile["persona_ref_image"] = await ref_service.save_base64_refs(
                                profile.get("persona_ref_image") or []
                            )
                self.config["persona_config"] = pc
                self.persona_mgr = PersonaManager(self.config, self.data_dir)

            # providers有变化时热重载 registry（draw/edit同一引用，自动生效）
            if apply_result.providers_changed:
                self._reload_registry_after_provider_change()

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
        try:
            image_data = await self._persona_ref_service().preview_data_url(path)
        except ValueError:
            return jsonify({"success": False, "error": "禁止访问"}), 403
        except FileNotFoundError:
            return jsonify({"success": False, "error": "文件不存在"}), 404
        return jsonify({
            "success": True,
            "image_data": image_data,
        })


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
            data = file.read()
            if inspect.isawaitable(data):
                data = await data
            save_path, safe_name = await self._persona_ref_service().save_image_bytes(filename, data)
            logger.info("[AI绘图站] 参考图已上传: %s", save_path)

            return jsonify({
                "success": True,
                "path": save_path,
                "filename": safe_name,
            })
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error("[Pages] upload_ref_image 失败: %s", e, exc_info=True)
            return jsonify({"success": False, "error": str(e)}), 500

    async def _pages_upload_ref_image_b64(self):
        """POST /astrbot_plugin_aiimg_enhanced/upload_ref_image_b64
        JSON: { filename, data: "data:image/...;base64,..." }
        """
        try:
            data = await request.get_json(force=True) or {}
            filename = pathlib.Path(str(data.get("filename") or "upload")).name
            data_url = str(data.get("data") or "")

            save_path, safe_name = await self._persona_ref_service().save_data_url(filename, data_url)
            logger.info("[AI绘图站] 参考图已通过 base64 fallback 上传: %s", save_path)

            return jsonify({
                "success": True,
                "path": save_path,
                "filename": safe_name,
            })
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.error("[Pages] upload_ref_image_b64 失败: %s", e, exc_info=True)
            return jsonify({"success": False, "error": str(e)}), 500

    def _reload_registry_after_provider_change(self) -> None:
        new_providers = PagesConfigService.provider_configs_by_id(
            self.config.get("providers") or []
        )
        old_provider_ids = set(self.registry._providers.keys())
        for pid in list(old_provider_ids):
            old_conf = self.registry._providers.get(pid)
            new_conf = new_providers.get(pid)
            if new_conf is None or old_conf != new_conf:
                self.registry._backends.pop(pid, None)
                self.registry._video_backends.pop(pid, None)
        self.registry._providers.clear()
        self.registry._load_providers()
        logger.info("[AI绘图站] Registry 已热重载，providers=%s",
                    list(self.registry._providers.keys()))
        self._update_llm_tool_descriptions()
