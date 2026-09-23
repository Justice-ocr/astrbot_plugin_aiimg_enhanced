from __future__ import annotations


class VideoNoFallbackError(RuntimeError):
    """A video error that must not trigger another billable provider."""


class VideoSubmissionUnknownError(VideoNoFallbackError):
    """The submit request may have reached upstream, but no task ID is known."""


class VideoTaskAcceptedError(VideoNoFallbackError):
    def __init__(
        self,
        provider: str,
        task_id: str,
        phase: str,
        cause: BaseException,
    ):
        self.provider = str(provider or "video")
        self.task_id = str(task_id or "")
        self.phase = str(phase or "processing")
        self.cause = cause
        super().__init__(
            f"{self.provider} 任务已提交，后续{self.phase}失败，"
            f"不会自动切换服务商重复生成；task_id={self.task_id}: {cause}"
        )
