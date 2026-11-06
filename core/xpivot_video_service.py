from __future__ import annotations

from urllib.parse import quote

from .xai_video_service import XaiVideoService


class XpivotVideoService(XaiVideoService):
    """Xpivot's Muse mapping: singular submit path and New API task envelope.

    A single reference uses image.url; 2–7 references use reference_images.
    Poll the full task endpoint because /videos/{id} omits the result URL.
    Submission is never retried automatically, including lost responses.
    """

    def __init__(self, *, settings: dict, data_dir=None):
        super().__init__(settings={
            **settings,
            "base_url": settings.get("base_url") or "https://www.xpivot.top",
            "duration": settings.get("duration") or "5",
        }, data_dir=data_dir)

    def _create_url(self):
        return f"{self._api_root()}/video/generations"

    def _retrieve_url(self, task_id):
        return f"{self._create_url()}/{quote(str(task_id), safe='')}"

    def _content_url(self, task_id):
        return f"{self._api_root()}/videos/{quote(str(task_id), safe='')}/content"

    @staticmethod
    def _submission_id(data):
        return str(data.get("id") or data.get("task_id") or data.get("request_id") or "").strip()

    @staticmethod
    def _reference_payload(refs, mode):
        if not refs:
            return {}
        if len(refs) == 1:
            return {"image": {"url": refs[0]}}
        return {"reference_images": [{"url": url} for url in refs]}

    @staticmethod
    def _poll_data(data):
        if "code" not in data:
            return data
        if data.get("code") != "success":
            raise RuntimeError(f"Xpivot 视频查询失败: {data.get('message') or data.get('code')}")
        task = data.get("data")
        if not isinstance(task, dict):
            raise RuntimeError("Xpivot 视频查询缺少任务对象")
        status = str(task.get("status") or "").strip().lower()
        if not status:
            raise RuntimeError("Xpivot 视频查询缺少任务状态")
        if status in {"failure", "error"}:
            status = "failed"
        return {**task, "status": status, "error": task.get("fail_reason") or task.get("error")}

    @staticmethod
    def _result_url(data):
        # Keep moderation checks from the native service for both envelopes.
        url = XaiVideoService._result_url(data)
        nested = data.get("data")
        nested_url = XaiVideoService._result_url(nested) if isinstance(nested, dict) else ""
        from .openai_video_service import _is_http_url
        result = data.get("result_url")
        return url or nested_url or (result.strip() if isinstance(result, str) and _is_http_url(result) else "")
