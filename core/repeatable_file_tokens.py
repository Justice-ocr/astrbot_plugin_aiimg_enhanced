from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from astrbot.api import logger


_REGISTRY_ATTR = "_aiimg_repeatable_file_tokens"
_PATCHED_ATTR = "_aiimg_repeatable_file_tokens_patched"
_ORIGINAL_ATTR = "_aiimg_repeatable_file_tokens_original"


def install_repeatable_file_token_support(file_token_service: Any) -> bool:
    if getattr(file_token_service, _PATCHED_ATTR, False):
        return True
    required = ("handle_file", "lock", "_cleanup_expired_tokens", "staged_files")
    if not all(hasattr(file_token_service, name) for name in required):
        return False

    original = file_token_service.handle_file
    setattr(file_token_service, _REGISTRY_ATTR, {})

    async def scoped_handle_file(file_token: str) -> str:
        registry = getattr(file_token_service, _REGISTRY_ATTR, {})
        expected_path = registry.get(file_token)
        if not expected_path:
            return await original(file_token)

        delegate_to_original = False
        async with file_token_service.lock:
            await file_token_service._cleanup_expired_tokens()
            staged = file_token_service.staged_files.get(file_token)
            if not staged:
                registry.pop(file_token, None)
                raise KeyError(f"无效或过期的文件 token: {file_token}")
            file_path, expire_time = staged
            if str(Path(file_path).resolve()) != expected_path:
                registry.pop(file_token, None)
                delegate_to_original = True
            elif time.time() > expire_time:
                file_token_service.staged_files.pop(file_token, None)
                registry.pop(file_token, None)
                raise KeyError(f"无效或过期的文件 token: {file_token}")
            elif not Path(file_path).is_file():
                file_token_service.staged_files.pop(file_token, None)
                registry.pop(file_token, None)
                raise FileNotFoundError(f"文件不存在: {file_path}")
            else:
                return file_path
        if delegate_to_original:
            return await original(file_token)
        raise KeyError(f"无效或过期的文件 token: {file_token}")

    setattr(file_token_service, _ORIGINAL_ATTR, original)
    file_token_service.handle_file = scoped_handle_file
    setattr(file_token_service, _PATCHED_ATTR, True)
    logger.info("[VideoFileToken] 已启用插件参考图 token 的限定重复访问")
    return True


def mark_repeatable_file_token(
    file_token_service: Any,
    file_token: str,
    file_path: Path,
) -> None:
    if not install_repeatable_file_token_support(file_token_service):
        raise RuntimeError("当前 AstrBot 文件服务不支持参考图 token 重复访问")
    registry = getattr(file_token_service, _REGISTRY_ATTR)
    for token, path in list(registry.items()):
        if not Path(path).is_file():
            registry.pop(token, None)
    registry[str(file_token)] = str(Path(file_path).resolve())
