from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


_IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": ("image", ".png", "image/png"),
    b"\xff\xd8\xff": ("image", ".jpg", "image/jpeg"),
    b"GIF87a": ("image", ".gif", "image/gif"),
    b"GIF89a": ("image", ".gif", "image/gif"),
}


class StudioAssetStore:
    """Durable, path-safe index for uploaded and generated Studio media."""

    def __init__(self, data_dir: str | Path, *, max_bytes: int = 100 * 1024 * 1024):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "studio.sqlite3"
        self.asset_dir = (self.data_dir / "studio_assets").resolve()
        self.max_bytes = max(1, int(max_bytes))

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS assets ("
            "id TEXT PRIMARY KEY, scope TEXT NOT NULL, media_type TEXT NOT NULL, "
            "storage_path TEXT NOT NULL, filename TEXT NOT NULL, content_hash TEXT NOT NULL, "
            "byte_size INTEGER NOT NULL, created_at REAL NOT NULL, source_job_id TEXT, "
            "pinned INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL, "
            "UNIQUE(scope, content_hash))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_assets_scope_time "
            "ON assets(scope, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_assets_hash "
            "ON assets(content_hash)"
        )
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        raw = item.pop("metadata_json", "{}")
        try:
            item["metadata"] = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            item["metadata"] = {}
        item["pinned"] = bool(item.get("pinned"))
        item["asset_id"] = item["id"]
        item.pop("storage_path", None)
        return item

    @staticmethod
    def _detect(data: bytes, filename: str) -> tuple[str, str, str]:
        for signature, result in _IMAGE_SIGNATURES.items():
            if data.startswith(signature):
                return result
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image", ".webp", "image/webp"
        if data.startswith(b"ftyp") or data[4:8] == b"ftyp":
            return "video", ".mp4", "video/mp4"
        suffix = Path(filename or "").suffix.lower()
        if suffix in {".mp4", ".webm", ".mov"}:
            return "video", suffix, mimetypes.guess_type(filename)[0] or "video/mp4"
        raise ValueError("仅支持 JPEG、PNG、GIF、WEBP、MP4、WEBM 或 MOV 素材")

    @staticmethod
    def decode_data_url(value: str) -> tuple[str, bytes]:
        text = str(value or "").strip()
        match = re.fullmatch(r"data:([^;,]+);base64,([A-Za-z0-9+/=_\-\s]+)", text, re.DOTALL)
        if not match:
            raise ValueError("素材必须是 base64 data URI")
        mime = match.group(1).lower()
        if not (mime.startswith("image/") or mime.startswith("video/")):
            raise ValueError("仅支持图片或视频素材")
        body = re.sub(r"\s+", "", match.group(2))
        try:
            raw = base64.b64decode(body.replace("-", "+").replace("_", "/"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("素材 base64 无效") from exc
        if not raw:
            raise ValueError("素材内容为空")
        return mime, raw

    def _safe_storage_path(self, raw: str) -> Path:
        path = Path(raw).resolve()
        if not path.is_relative_to(self.asset_dir):
            raise ValueError("素材路径无效")
        return path

    async def create_from_bytes(
        self,
        scope: str,
        filename: str,
        data: bytes,
        *,
        source_job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if len(data) > self.max_bytes:
            raise ValueError("素材超过大小限制")
        media_type, extension, mime = self._detect(data, filename)
        digest = hashlib.sha256(data).hexdigest()

        def write() -> dict[str, Any]:
            conn = self._connect()
            try:
                with conn:
                    existing = conn.execute(
                        "SELECT * FROM assets WHERE scope=? AND content_hash=?",
                        (scope, digest),
                    ).fetchone()
                    if existing is not None:
                        return self._row(existing) or {}
                    asset_id = uuid.uuid4().hex
                    self.asset_dir.mkdir(parents=True, exist_ok=True)
                    path = self.asset_dir / f"{asset_id}{extension}"
                    path.write_bytes(data)
                    now = time.time()
                    payload = dict(metadata or {})
                    payload.setdefault("mime_type", mime)
                    conn.execute(
                        "INSERT INTO assets(id,scope,media_type,storage_path,filename,content_hash,"
                        "byte_size,created_at,source_job_id,pinned,metadata_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            asset_id, scope, media_type, str(path),
                            Path(filename or f"asset{extension}").name[:180], digest,
                            len(data), now, source_job_id, 0,
                            json.dumps(payload, ensure_ascii=False),
                        ),
                    )
                    row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
                    return self._row(row) or {}
            finally:
                conn.close()

        return await asyncio.to_thread(write)

    async def create_from_path(
        self,
        scope: str,
        path: str | Path,
        *,
        filename: str | None = None,
        source_job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved = Path(path).resolve()
        if not resolved.is_file() or not resolved.is_relative_to(self.data_dir):
            raise ValueError("素材文件无效")
        data = await asyncio.to_thread(resolved.read_bytes)
        return await self.create_from_bytes(
            scope,
            filename or resolved.name,
            data,
            source_job_id=source_job_id,
            metadata=metadata,
        )

    async def get(self, asset_id: str) -> dict[str, Any] | None:
        def read():
            conn = self._connect()
            try:
                return self._row(conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def list(self, *, scope: str = "", limit: int = 60, query: str = "") -> list[dict[str, Any]]:
        def read():
            conn = self._connect()
            try:
                clauses: list[str] = []
                params: list[Any] = []
                if scope:
                    clauses.append("scope=?")
                    params.append(scope)
                if query:
                    clauses.append("filename LIKE ?")
                    params.append(f"%{query[:120]}%")
                where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
                params.append(max(1, min(int(limit), 200)))
                rows = conn.execute(
                    f"SELECT * FROM assets{where} ORDER BY created_at DESC LIMIT ?", params
                ).fetchall()
                return [self._row(row) for row in rows if row is not None]
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def scopes(self) -> set[str]:
        def read():
            conn = self._connect()
            try:
                return {str(row[0]) for row in conn.execute("SELECT DISTINCT scope FROM assets")}
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def content_path(self, asset_id: str) -> Path | None:
        def read():
            conn = self._connect()
            try:
                row = conn.execute("SELECT storage_path FROM assets WHERE id=?", (asset_id,)).fetchone()
                if row is None:
                    return None
                path = self._safe_storage_path(row[0])
                return path if path.is_file() else None
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def set_pinned(self, asset_id: str, pinned: bool) -> dict[str, Any] | None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("UPDATE assets SET pinned=? WHERE id=?", (1 if pinned else 0, asset_id))
                    return self._row(conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def delete(self, asset_id: str) -> bool:
        from .project_references import asset_references

        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
                    if row is None:
                        return False
                    if bool(row["pinned"]):
                        raise ValueError("已收藏素材不能直接删除")
                    tables = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "projects" in tables:
                        for project in conn.execute("SELECT document_json FROM projects"):
                            if asset_id in asset_references(json.loads(project[0])):
                                raise ValueError("素材仍被项目引用，不能删除")
                    if "project_versions" in tables:
                        for version in conn.execute("SELECT snapshot_json FROM project_versions"):
                            if asset_id in asset_references(json.loads(version[0]).get("document", {})):
                                raise ValueError("素材仍被项目历史版本引用，不能删除")
                    path = self._safe_storage_path(row["storage_path"])
                    conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
                path.unlink(missing_ok=True)
                return True
            finally:
                conn.close()
        return await asyncio.to_thread(write)
