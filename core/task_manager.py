from __future__ import annotations

import asyncio
import contextvars
import functools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


_current = contextvars.ContextVar("aiimg_task", default=None)
TERMINAL = {"completed", "partial", "failed", "cancelled"}
STATUS_LABELS = {
    "preparing": "准备中", "generating": "生成中", "downloading": "下载中", "sending": "发送中",
    "cancelling": "取消中", "completed": "已完成", "partial": "部分完成",
    "failed": "失败", "cancelled": "已取消",
}

def update_task_state(state):
    item = _current.get()
    if item and item.state not in TERMINAL and item.state != "cancelling":
        item.state = state


@dataclass
class ManagedTask:
    id: str
    scope: str
    kind: str
    prompt: str
    created_at: float = field(default_factory=time.time)
    state: str = "preparing"
    finished_at: float | None = None
    generated: int = 0
    sent: int = 0
    failed: int = 0
    error: str = ""
    persona: str = ""
    worker: Any = field(default=None, repr=False)

    def public(self):
        return {key: value for key, value in vars(self).items() if key != "worker"}


class TaskManager:
    def __init__(self, limit=100):
        self.items: dict[str, ManagedTask] = {}
        self.limit = limit
        self.closing = False

    def current(self):
        value = _current.get()
        return value if value is not None and self.items.get(value.id) is value else None

    def update(self, state=None, *, generated=0, sent=0, failed=0):
        item = self.current()
        if item is None:
            return
        if state and item.state not in TERMINAL and item.state != "cancelling":
            item.state = state
        item.generated += generated
        item.sent += sent
        item.failed += failed

    def list(self, scope=None):
        return [item.public() for item in reversed(list(self.items.values()))
                if scope is None or item.scope == scope]

    def cancel(self, task_id, *, scope=None):
        item = self.items.get(task_id)
        if item is None or (scope is not None and item.scope != scope):
            raise ValueError("任务不存在或不属于当前用户会话")
        if item.state in TERMINAL or item.worker is None or item.worker.done():
            raise ValueError("任务已经结束")
        if item.state != "cancelling":
            item.state = "cancelling"
            item.worker.cancel()

    async def run(self, scope, kind, prompt, operation, *, persona="", requires_delivery=True):
        if self.current() is not None:
            return await operation()
        # Keep terminal history bounded without discarding active tasks.
        for key in list(self.items):
            if len(self.items) < self.limit:
                break
            if self.items[key].state in TERMINAL:
                del self.items[key]
        item = ManagedTask(uuid.uuid4().hex[:12], scope, kind, prompt[:2000], persona=persona)
        self.items[item.id] = item

        async def execute():
            token = _current.set(item)
            try:
                return await operation()
            finally:
                _current.reset(token)

        item.worker = asyncio.create_task(execute())
        try:
            result = await item.worker
            successful = item.sent if requires_delivery else item.generated
            item.state = "completed" if successful and successful == item.generated and not item.failed else (
                "partial" if successful else "failed"
            )
            if item.state == "failed":
                item.error = "未成功发送结果；若已生成，可在历史中重发" if requires_delivery else "未成功生成结果"
            return result
        except asyncio.CancelledError:
            item.state = "cancelled"
            raise
        except Exception as exc:
            item.state = "failed"
            item.error = str(exc)[:300]
            raise
        finally:
            item.finished_at = time.time()
            item.worker = None

    async def close(self):
        self.closing = True
        workers = [item.worker for item in self.items.values() if item.worker and not item.worker.done()]
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


def managed_task(kind="image"):
    """Run plugin work in a child task, never cancel the framework event worker."""
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(self, event, *args, **kwargs):
            manager = getattr(self, "tasks", None)
            if manager is None or manager.current() is not None:
                return await fn(self, event, *args, **kwargs)
            await self._capture_history_scope(event)
            started = False

            async def operation():
                nonlocal started
                started = True
                return await fn(self, event, *args, **kwargs)

            try:
                persona = await self._get_event_persona(event, snapshot=True)
                scope = await self._history_scope(event)
                return await manager.run(
                    scope, kind, str(getattr(event, "message_str", "") or ""),
                    operation, persona=persona.name,
                )
            except asyncio.CancelledError:
                # Propagate framework shutdown, but consume user-requested child cancellation.
                if asyncio.current_task().cancelling() or manager.closing:
                    raise
                event.stop_event()
                event.should_call_llm(False)
                message = "任务已在本地取消。已提交上游的请求可能仍会生成并计费。"
                await event.send(event.plain_result(message))
                if fn.__name__.startswith("aiimg_"):
                    return self._llm_tool_text_result(message)
            finally:
                # Video admission happens before its background worker is created.
                if kind == "video" and not started:
                    await self._video_end(str(event.get_sender_id() or ""))
        return wrapper
    return decorate
