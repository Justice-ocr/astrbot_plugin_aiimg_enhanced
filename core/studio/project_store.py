from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
from .project_references import asset_references


class StudioProjectStore:
    """Optimistic-locking storage for canvas/GIF/design project documents."""

    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "studio.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id TEXT PRIMARY KEY, scope TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, "
            "revision INTEGER NOT NULL, document_json TEXT NOT NULL, created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_projects_scope_time "
            "ON projects(scope, updated_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_versions ("
            "project_id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, "
            "PRIMARY KEY(project_id, revision))"
        )
        return conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        raw = item.pop("document_json", "{}")
        try:
            item["document"] = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            item["document"] = {}
        return item

    async def list(self, *, scope: str = "", kind: str = "", limit: int = 50) -> list[dict[str, Any]]:
        def read():
            conn = self._connect()
            try:
                clauses: list[str] = []
                params: list[Any] = []
                if scope:
                    clauses.append("scope=?")
                    params.append(scope)
                if kind:
                    clauses.append("kind=?")
                    params.append(kind)
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                params.append(max(1, min(int(limit), 100)))
                rows = conn.execute(
                    f"SELECT * FROM projects{where} ORDER BY updated_at DESC LIMIT ?", params
                ).fetchall()
                return [self._row(row) for row in rows if row is not None]
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def scopes(self) -> set[str]:
        def read():
            conn = self._connect()
            try:
                return {str(row[0]) for row in conn.execute("SELECT DISTINCT scope FROM projects")}
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def get(self, project_id: str) -> dict[str, Any] | None:
        def read():
            conn = self._connect()
            try:
                return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def save(
        self,
        *,
        project_id: str | None,
        scope: str,
        name: str,
        kind: str,
        document: dict[str, Any],
        revision: int | None,
    ) -> dict[str, Any]:
        requested_project_id = project_id

        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    references = asset_references(document)
                    if references:
                        has_assets = conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assets'"
                        ).fetchone()
                        if not has_assets:
                            raise ValueError("项目引用素材不存在")
                        for asset_id in references:
                            asset = conn.execute("SELECT scope FROM assets WHERE id=?", (asset_id,)).fetchone()
                            if asset is None or asset["scope"] != scope:
                                raise ValueError("项目引用素材不存在或不属于当前会话")
                    now = time.time()
                    current_project_id = requested_project_id
                    if current_project_id:
                        row = conn.execute("SELECT * FROM projects WHERE id=?", (current_project_id,)).fetchone()
                        if row is None:
                            raise ValueError("项目不存在")
                        if str(row["scope"]) != scope:
                            raise ValueError("项目不属于当前会话")
                        expected = int(revision if revision is not None else -1)
                        if int(row["revision"]) != expected:
                            raise RuntimeError("PROJECT_REVISION_CONFLICT")
                        conn.execute(
                            "INSERT OR IGNORE INTO project_versions VALUES(?,?,?)",
                            (current_project_id, expected, json.dumps(self._row(row), ensure_ascii=False)),
                        )
                        conn.execute(
                            "DELETE FROM project_versions WHERE project_id=? AND revision NOT IN "
                            "(SELECT revision FROM project_versions WHERE project_id=? ORDER BY revision DESC LIMIT 20)",
                            (current_project_id, current_project_id),
                        )
                        next_revision = expected + 1
                        conn.execute(
                            "UPDATE projects SET name=?,kind=?,revision=?,document_json=?,updated_at=? WHERE id=?",
                            (name[:160], kind[:40], next_revision,
                             json.dumps(document, ensure_ascii=False), now, current_project_id),
                        )
                    else:
                        current_project_id = uuid.uuid4().hex
                        next_revision = 1
                        conn.execute(
                            "INSERT INTO projects(id,scope,name,kind,revision,document_json,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (current_project_id, scope, name[:160], kind[:40], next_revision,
                             json.dumps(document, ensure_ascii=False), now, now),
                        )
                    return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (current_project_id,)).fetchone()) or {}
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def versions(self, project_id: str, *, scope: str) -> list[dict[str, Any]]:
        def read():
            conn = self._connect()
            try:
                current = conn.execute("SELECT scope FROM projects WHERE id=?", (project_id,)).fetchone()
                if current is None or current["scope"] != scope:
                    raise ValueError("项目不存在或不属于当前会话")
                return [
                    json.loads(row["snapshot_json"])
                    for row in conn.execute(
                        "SELECT snapshot_json FROM project_versions WHERE project_id=? ORDER BY revision DESC",
                        (project_id,),
                    )
                ]
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def attach_canvas_result(
        self, *, project_id: str, scope: str, node_id: str,
        submission_key: str, job_id: str, asset_id: str,
    ) -> dict[str, Any] | None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT * FROM projects WHERE id=? AND scope=? AND kind='canvas'",
                        (project_id, scope),
                    ).fetchone()
                    if row is None:
                        return None
                    asset = conn.execute(
                        "SELECT 1 FROM assets WHERE id=? AND scope=?", (asset_id, scope),
                    ).fetchone()
                    if asset is None:
                        raise ValueError("生成结果素材不存在或不属于当前会话")
                    document = json.loads(row["document_json"])
                    node = next((
                        item for item in document.get("nodes", [])
                        if isinstance(item, dict) and item.get("id") == node_id
                    ), None)
                    if node is None or node.get("type") != "generation" or node.get("submission_key") != submission_key:
                        return None
                    if node.get("asset_id") == asset_id and node.get("job_id") == job_id:
                        return self._row(row)
                    if node.get("asset_id") and node.get("asset_id") != asset_id:
                        raise ValueError("生成节点已经关联其他素材")
                    node["asset_id"] = asset_id
                    node["job_id"] = job_id
                    revision = int(row["revision"])
                    conn.execute(
                        "INSERT OR IGNORE INTO project_versions VALUES(?,?,?)",
                        (project_id, revision, json.dumps(self._row(row), ensure_ascii=False)),
                    )
                    conn.execute(
                        "DELETE FROM project_versions WHERE project_id=? AND revision NOT IN "
                        "(SELECT revision FROM project_versions WHERE project_id=? ORDER BY revision DESC LIMIT 20)",
                        (project_id, project_id),
                    )
                    conn.execute(
                        "UPDATE projects SET revision=?,document_json=?,updated_at=? WHERE id=?",
                        (revision + 1, json.dumps(document, ensure_ascii=False), time.time(), project_id),
                    )
                    return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def attach_canvas_job(
        self, *, project_id: str, scope: str, node_id: str,
        submission_key: str, job_id: str,
    ) -> dict[str, Any] | None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT * FROM projects WHERE id=? AND scope=? AND kind='canvas'",
                        (project_id, scope),
                    ).fetchone()
                    if row is None:
                        return None
                    document = json.loads(row["document_json"])
                    node = next((
                        item for item in document.get("nodes", [])
                        if isinstance(item, dict) and item.get("id") == node_id
                    ), None)
                    if node is None or node.get("type") != "generation" or node.get("submission_key") != submission_key:
                        return None
                    if node.get("job_id") == job_id:
                        return self._row(row)
                    if node.get("job_id"):
                        raise ValueError("生成节点已经关联其他任务")
                    node["job_id"] = job_id
                    revision = int(row["revision"])
                    conn.execute(
                        "INSERT OR IGNORE INTO project_versions VALUES(?,?,?)",
                        (project_id, revision, json.dumps(self._row(row), ensure_ascii=False)),
                    )
                    conn.execute(
                        "DELETE FROM project_versions WHERE project_id=? AND revision NOT IN "
                        "(SELECT revision FROM project_versions WHERE project_id=? ORDER BY revision DESC LIMIT 20)",
                        (project_id, project_id),
                    )
                    conn.execute(
                        "UPDATE projects SET revision=?,document_json=?,updated_at=? WHERE id=?",
                        (revision + 1, json.dumps(document, ensure_ascii=False), time.time(), project_id),
                    )
                    return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def record_gif_job(
        self, *, project_id: str, scope: str, frame_key: str,
        job_id: str, asset_id: str = "",
    ) -> dict[str, Any] | None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT * FROM projects WHERE id=? AND scope=? AND kind='gif'",
                        (project_id, scope),
                    ).fetchone()
                    if row is None:
                        return None
                    document = json.loads(row["document_json"])
                    entry = next((
                        item for item in document.get("frame_jobs", [])
                        if isinstance(item, dict) and item.get("key") == frame_key
                    ), None)
                    if entry is None:
                        return None
                    if entry.get("job_id") not in (None, "", job_id):
                        raise ValueError("帧编号已关联其他任务")
                    if asset_id:
                        asset = conn.execute(
                            "SELECT media_type FROM assets WHERE id=? AND scope=?",
                            (asset_id, scope),
                        ).fetchone()
                        if asset is None or asset["media_type"] != "image":
                            raise ValueError("GIF 生成帧素材无效")
                        if entry.get("result_asset_id") not in (None, "", asset_id):
                            raise ValueError("帧编号已关联其他素材")
                    if entry.get("job_id") == job_id and (not asset_id or entry.get("result_asset_id") == asset_id):
                        return self._row(row)
                    entry["job_id"] = job_id
                    if asset_id:
                        entry["result_asset_id"] = asset_id
                        frames = document.setdefault("frames", [])
                        durations = document.setdefault("frame_durations_ms", [document.get("duration_ms", 500)] * len(frames))
                        if len(frames) < 60:
                            frames.append(asset_id)
                            durations.append(int(document.get("duration_ms") or 500))
                    revision = int(row["revision"])
                    conn.execute(
                        "INSERT OR IGNORE INTO project_versions VALUES(?,?,?)",
                        (project_id, revision, json.dumps(self._row(row), ensure_ascii=False)),
                    )
                    conn.execute(
                        "DELETE FROM project_versions WHERE project_id=? AND revision NOT IN "
                        "(SELECT revision FROM project_versions WHERE project_id=? ORDER BY revision DESC LIMIT 20)",
                        (project_id, project_id),
                    )
                    conn.execute(
                        "UPDATE projects SET revision=?,document_json=?,updated_at=? WHERE id=?",
                        (revision + 1, json.dumps(document, ensure_ascii=False), time.time(), project_id),
                    )
                    return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def record_design_job(
        self, *, project_id: str, scope: str, repair_key: str,
        job_id: str, asset_id: str = "",
    ) -> dict[str, Any] | None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT * FROM projects WHERE id=? AND scope=? AND kind='design'",
                        (project_id, scope),
                    ).fetchone()
                    if row is None:
                        return None
                    document = json.loads(row["document_json"])
                    entry = next((item for item in document.get("blocks", [])
                                  if isinstance(item, dict) and item.get("type") == "repair"
                                  and item.get("key") == repair_key), None)
                    if entry is None or entry.get("job_id") not in (None, "", job_id):
                        return None
                    if asset_id:
                        asset = conn.execute(
                            "SELECT media_type FROM assets WHERE id=? AND scope=?",
                            (asset_id, scope),
                        ).fetchone()
                        if asset is None or asset["media_type"] != "image":
                            raise ValueError("修补结果素材无效")
                    if entry.get("job_id") == job_id and (not asset_id or entry.get("result_asset_id") == asset_id):
                        return self._row(row)
                    entry["job_id"] = job_id
                    if asset_id:
                        entry["result_asset_id"] = asset_id
                    revision = int(row["revision"])
                    conn.execute(
                        "INSERT OR IGNORE INTO project_versions VALUES(?,?,?)",
                        (project_id, revision, json.dumps(self._row(row), ensure_ascii=False)),
                    )
                    conn.execute(
                        "DELETE FROM project_versions WHERE project_id=? AND revision NOT IN "
                        "(SELECT revision FROM project_versions WHERE project_id=? ORDER BY revision DESC LIMIT 20)",
                        (project_id, project_id),
                    )
                    conn.execute(
                        "UPDATE projects SET revision=?,document_json=?,updated_at=? WHERE id=?",
                        (revision + 1, json.dumps(document, ensure_ascii=False), time.time(), project_id),
                    )
                    return self._row(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def delete(self, project_id: str, *, revision: int | None = None) -> bool:
        def write():
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
                    if row is None:
                        return False
                    if revision is not None and int(row["revision"]) != int(revision):
                        raise RuntimeError("PROJECT_REVISION_CONFLICT")
                    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
                    conn.execute("DELETE FROM project_versions WHERE project_id=?", (project_id,))
                    return True
            finally:
                conn.close()
        return await asyncio.to_thread(write)
