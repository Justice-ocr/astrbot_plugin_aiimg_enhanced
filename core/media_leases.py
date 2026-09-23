from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock


_lock = Lock()
_leases: dict[Path, int] = {}


def acquire_media(path: Path) -> Path:
    resolved = Path(path).resolve()
    with _lock:
        _leases[resolved] = _leases.get(resolved, 0) + 1
    return resolved


def release_media(path: Path) -> None:
    resolved = Path(path).resolve()
    with _lock:
        count = _leases.get(resolved, 0)
        if count <= 1:
            _leases.pop(resolved, None)
        else:
            _leases[resolved] = count - 1


def media_is_active(path: Path) -> bool:
    resolved = Path(path).resolve()
    with _lock:
        return _leases.get(resolved, 0) > 0


@contextmanager
def hold_media(path: Path):
    resolved = acquire_media(path)
    try:
        yield resolved
    finally:
        release_media(resolved)
