from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import time
from pathlib import Path


class ImageHistory:
    """Globally bounded history with independent copies of generated images."""

    def __init__(self, data_dir: Path, *, limit: int = 100):
        self.path = Path(data_dir) / "image_history.sqlite3"
        self.image_dir = Path(data_dir) / "history_images"
        self.limit = max(1, min(100, limit))

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS images ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, "
            "path TEXT NOT NULL, created_at REAL NOT NULL, metadata TEXT NOT NULL, "
            "UNIQUE(scope, path))"
        )
        return conn

    def _archive_path(self, row) -> Path:
        ext = Path(row["path"]).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            ext = ".img"
        return self.image_dir / f"{row['id']}{ext}"

    def _record(self, row):
        if row is None:
            return None
        return {
            **dict(row), "path": str(self._archive_path(row)),
            "metadata": json.loads(row["metadata"]),
        }

    async def add(self, scope: str, path: Path, metadata: dict) -> dict:
        def write():
            conn = self._connect()
            copied = None
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    archive_id = 0
                    if path.parent.resolve() == self.image_dir.resolve() and path.stem.isdigit():
                        archive_id = int(path.stem)
                    existing = conn.execute(
                        "SELECT * FROM images WHERE scope=? AND (path=? OR id=?)",
                        (scope, str(path), archive_id),
                    ).fetchone()
                    if existing is not None:
                        return self._record(existing)
                    conn.execute(
                        "INSERT INTO images(scope,path,created_at,metadata) VALUES(?,?,?,?)",
                        (scope, str(path), time.time(), json.dumps(metadata, ensure_ascii=False)),
                    )
                    row = conn.execute(
                        "SELECT * FROM images WHERE scope=? AND path=?", (scope, str(path))
                    ).fetchone()
                    self.image_dir.mkdir(parents=True, exist_ok=True)
                    copied = self._archive_path(row)
                    shutil.copyfile(path, copied)
                    expired = conn.execute(
                        "SELECT * FROM images ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
                        (self.limit,),
                    ).fetchall()
                    conn.execute(
                        "DELETE FROM images WHERE id NOT IN "
                        "(SELECT id FROM images ORDER BY created_at DESC, id DESC LIMIT ?)",
                        (self.limit,),
                    )
                for old in expired:
                    target = self._archive_path(old).resolve()
                    if target.is_relative_to(self.image_dir.resolve()):
                        try:
                            target.unlink(missing_ok=True)
                        except OSError:
                            pass
                return self._record(row)
            except Exception:
                if copied is not None:
                    copied.unlink(missing_ok=True)
                raise
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def list(self, scope: str, *, limit: int = 10) -> list[dict]:
        def read():
            conn = self._connect()
            try:
                return [
                    self._record(row) for row in conn.execute(
                        "SELECT * FROM images WHERE scope=? ORDER BY created_at DESC, id DESC LIMIT ?",
                        (scope, max(1, min(limit, self.limit))),
                    )
                ]
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def get(self, scope: str, image_id: int | None = None) -> dict | None:
        if image_id is None:
            rows = await self.list(scope, limit=1)
            return rows[0] if rows else None

        def read():
            conn = self._connect()
            try:
                return self._record(conn.execute(
                    "SELECT * FROM images WHERE scope=? AND id=?", (scope, image_id)
                ).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def browse(self, *, page: int = 1, query: str = "", page_size: int = 24) -> dict:
        """Administrative view, exposed only through authenticated Pages APIs."""
        def read():
            conn = self._connect()
            try:
                term = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where = "WHERE json_extract(metadata, '$.user_prompt') LIKE ? ESCAPE '\\'" if query else ""
                params = [f"%{term}%"] if query else []
                total = conn.execute(f"SELECT COUNT(*) FROM images {where}", params).fetchone()[0]
                pages = max(1, (total + page_size - 1) // page_size)
                current = min(max(1, page), pages)
                rows = conn.execute(
                    "WITH numbered AS (SELECT *, ROW_NUMBER() OVER "
                    "(ORDER BY created_at DESC, id DESC) AS sequence FROM images) "
                    f"SELECT * FROM numbered {where} ORDER BY sequence LIMIT ? OFFSET ?",
                    [*params, page_size, (current - 1) * page_size],
                ).fetchall()
                return {
                    "items": [self._record(row) for row in rows],
                    "total": total, "page": current, "pages": pages,
                }
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def get_for_admin(self, image_id: int) -> dict | None:
        def read():
            conn = self._connect()
            try:
                return self._record(conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(read)
