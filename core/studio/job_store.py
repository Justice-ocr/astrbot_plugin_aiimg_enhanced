from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


TERMINAL_JOB_STATES = {"completed", "partial", "failed", "cancelled"}


class StudioJobStore:
    """Small durable job ledger for Web Studio requests.

    The ledger stores the request snapshot and result metadata only. Provider
    clients and asyncio tasks remain owned by the plugin process.
    """

    def __init__(self, data_dir: str | Path, *, limit: int = 200):
        self.path = Path(data_dir) / "studio.sqlite3"
        self.limit = max(20, min(1000, int(limit)))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, "
            "scope TEXT NOT NULL, kind TEXT NOT NULL, mode TEXT NOT NULL, "
            "prompt TEXT NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL, finished_at REAL, request_json TEXT NOT NULL, "
            "result_json TEXT NOT NULL, error TEXT NOT NULL, provider_id TEXT NOT NULL DEFAULT '', "
            "upstream_task_id TEXT NOT NULL DEFAULT '', accepted_state TEXT NOT NULL DEFAULT '', "
            "delivery_state TEXT NOT NULL DEFAULT 'pending', plan_id TEXT NOT NULL DEFAULT '', "
            "plan_index INTEGER NOT NULL DEFAULT 0)"
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        for name, definition in (
            ("provider_id", "TEXT NOT NULL DEFAULT ''"),
            ("upstream_task_id", "TEXT NOT NULL DEFAULT ''"),
            ("accepted_state", "TEXT NOT NULL DEFAULT ''"),
            ("delivery_state", "TEXT NOT NULL DEFAULT 'pending'"),
            ("plan_id", "TEXT NOT NULL DEFAULT ''"),
            ("plan_index", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_jobs_scope_time "
            "ON jobs(scope, created_at DESC)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS retired_job_keys ("
            "idempotency_key TEXT PRIMARY KEY, scope TEXT NOT NULL, "
            "job_id TEXT NOT NULL, retired_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plans ("
            "id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, "
            "prompt TEXT NOT NULL, count INTEGER NOT NULL, state TEXT NOT NULL, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL, provider_id TEXT NOT NULL DEFAULT '', "
            "parameter_hash TEXT NOT NULL DEFAULT '', request_json TEXT NOT NULL DEFAULT '{}')"
        )
        plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(plans)").fetchall()}
        for name, definition in (
            ("provider_id", "TEXT NOT NULL DEFAULT ''"),
            ("parameter_hash", "TEXT NOT NULL DEFAULT ''"),
            ("request_json", "TEXT NOT NULL DEFAULT '{}'"),
        ):
            if name not in plan_columns:
                conn.execute(f"ALTER TABLE plans ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_studio_plans_scope_time "
            "ON plans(scope, created_at DESC)"
        )
        return conn

    def _prune_completed(self, conn: sqlite3.Connection) -> None:
        # Active, uncertain, plan-owned and project-owned jobs remain recoverable.
        rows = conn.execute(
            "SELECT id,idempotency_key,scope FROM jobs "
            "WHERE state='completed' AND plan_id='' "
            "AND coalesce(json_extract(request_json, '$.project_id'), '')='' "
            "ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (self.limit,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO retired_job_keys "
                "(idempotency_key,scope,job_id,retired_at) VALUES(?,?,?,?)",
                (row["idempotency_key"], row["scope"], row["id"], time.time()),
            )
            conn.execute("DELETE FROM jobs WHERE id=?", (row["id"],))

    @staticmethod
    def _reject_retired_key(conn: sqlite3.Connection, key: str, scope: str) -> None:
        retired = conn.execute(
            "SELECT scope FROM retired_job_keys WHERE idempotency_key=?", (key,)
        ).fetchone()
        if retired is not None:
            if retired["scope"] != scope:
                raise ValueError("Idempotency key belongs to another session")
            raise ValueError("Task record was archived; this request cannot be submitted again")

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("request_json", "result_json"):
            raw = item.pop(key, "{}")
            try:
                item[key.removesuffix("_json")] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                item[key.removesuffix("_json")] = {}
        return item

    async def create(
        self,
        *,
        idempotency_key: str,
        scope: str,
        kind: str,
        mode: str,
        prompt: str,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        def write() -> tuple[dict[str, Any], bool]:
            now = time.time()
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._reject_retired_key(conn, idempotency_key, scope)
                    existing = conn.execute(
                        "SELECT * FROM jobs WHERE idempotency_key=?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing is not None:
                        if existing["scope"] != scope:
                            raise ValueError("Idempotency key belongs to another session")
                        if (
                            existing["kind"] != kind or existing["mode"] != mode
                            or existing["prompt"] != prompt
                            or json.loads(existing["request_json"]) != request
                        ):
                            raise ValueError("Task parameters changed; use a new idempotency key")
                        return self._row(existing) or {}, False
                    job_id = uuid.uuid4().hex[:16]
                    conn.execute(
                        "INSERT INTO jobs(id,idempotency_key,scope,kind,mode,prompt,state,"
                        "created_at,updated_at,finished_at,request_json,result_json,error) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            job_id, idempotency_key, scope, kind, mode, prompt,
                            "queued", now, now, None, json.dumps(request, ensure_ascii=False),
                            "{}", "",
                        ),
                    )
                    self._prune_completed(conn)
                    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                    return self._row(row) or {}, True
            finally:
                conn.close()

        return await asyncio.to_thread(write)

    async def create_plan(
        self,
        *,
        idempotency_key: str,
        scope: str,
        prompt: str,
        count: int,
        request: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        total = max(1, min(int(count), 8))

        def write():
            now = time.time()
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute(
                        "SELECT * FROM plans WHERE idempotency_key=?", (idempotency_key,)
                    ).fetchone()
                    if existing is not None:
                        if existing["scope"] != scope:
                            raise ValueError("Idempotency key belongs to another session")
                        plan = dict(existing)
                        try:
                            plan["request"] = json.loads(plan.get("request_json") or "{}")
                        except (TypeError, json.JSONDecodeError):
                            plan["request"] = {}
                        plan.pop("request_json", None)
                        if plan["count"] != total or plan["prompt"] != prompt or plan["request"] != request:
                            raise ValueError("Plan parameters changed; use a new idempotency key")
                        rows = conn.execute(
                            "SELECT * FROM jobs WHERE plan_id=? ORDER BY plan_index ASC",
                            (plan["id"],),
                        ).fetchall()
                        return plan, [self._row(row) for row in rows if row is not None], False

                    plan_id = uuid.uuid4().hex[:16]
                    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True)
                    parameter_hash = hashlib.sha256(request_json.encode("utf-8")).hexdigest()[:16]
                    provider_id = str(request.get("provider_id") or "").strip()
                    conn.execute(
                        "INSERT INTO plans(id,idempotency_key,scope,prompt,count,state,created_at,updated_at,provider_id,parameter_hash,request_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (plan_id, idempotency_key, scope, prompt, total, "queued", now, now, provider_id, parameter_hash, request_json),
                    )
                    jobs: list[dict[str, Any]] = []
                    for index in range(1, total + 1):
                        self._reject_retired_key(conn, f"{idempotency_key}:{index}", scope)
                        job_id = uuid.uuid4().hex[:16]
                        child_prompt = f"{prompt}\n变体 {index}/{total}"
                        job_request = {**request, "prompt": child_prompt, "plan_id": plan_id, "plan_index": index}
                        conn.execute(
                            "INSERT INTO jobs(id,idempotency_key,scope,kind,mode,prompt,state,"
                            "created_at,updated_at,finished_at,request_json,result_json,error,plan_id,plan_index) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                job_id, f"{idempotency_key}:{index}", scope, "image", "draw",
                                child_prompt, "queued", now, now, None,
                                json.dumps(job_request, ensure_ascii=False), "{}", "", plan_id, index,
                            ),
                        )
                        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                        if row is not None:
                            jobs.append(self._row(row) or {})
                    return {
                        "id": plan_id, "idempotency_key": idempotency_key, "scope": scope,
                        "prompt": prompt, "count": total, "state": "queued",
                        "created_at": now, "updated_at": now, "provider_id": provider_id,
                        "parameter_hash": parameter_hash, "request": request,
                    }, jobs, True
            finally:
                conn.close()

        return await asyncio.to_thread(write)

    async def create_structured_plan(
        self, *, idempotency_key: str, scope: str, goal: str,
        project_id: str, tasks: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        request = {"project_id": project_id, "tasks": tasks}
        total = len(tasks)
        if not 1 <= total <= 8:
            raise ValueError("计划任务数量必须在 1 到 8 之间")

        def write():
            now = time.time()
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute(
                        "SELECT * FROM plans WHERE idempotency_key=?", (idempotency_key,),
                    ).fetchone()
                    if existing is not None:
                        plan = dict(existing)
                        if plan["scope"] != scope or plan["prompt"] != goal or plan["count"] != total or json.loads(plan["request_json"]) != request:
                            raise ValueError("计划编号已被不同请求使用")
                        plan["request"] = json.loads(plan.pop("request_json"))
                        rows = conn.execute(
                            "SELECT * FROM jobs WHERE plan_id=? ORDER BY plan_index", (plan["id"],),
                        ).fetchall()
                        return plan, [self._row(row) for row in rows], False
                    for index in range(total):
                        self._reject_retired_key(conn, f"{idempotency_key}:{index + 1}", scope)
                    plan_id = uuid.uuid4().hex[:16]
                    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True)
                    digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()[:16]
                    conn.execute(
                        "INSERT INTO plans(id,idempotency_key,scope,prompt,count,state,created_at,updated_at,provider_id,parameter_hash,request_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (plan_id, idempotency_key, scope, goal, total, "queued", now, now, "", digest, request_json),
                    )
                    jobs = []
                    for index, task in enumerate(tasks, 1):
                        job_id = uuid.uuid4().hex[:16]
                        job_request = {
                            **task, "scope": scope, "project_id": project_id,
                            "plan_id": plan_id, "plan_index": index,
                            "idempotency_key": f"{idempotency_key}:{index}",
                        }
                        conn.execute(
                            "INSERT INTO jobs(id,idempotency_key,scope,kind,mode,prompt,state,"
                            "created_at,updated_at,finished_at,request_json,result_json,error,plan_id,plan_index) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                job_id, job_request["idempotency_key"], scope,
                                task["kind"], task["mode"], task["prompt"], "queued",
                                now, now, None, json.dumps(job_request, ensure_ascii=False),
                                "{}", "", plan_id, index,
                            ),
                        )
                        jobs.append(self._row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()))
                    return {
                        "id": plan_id, "scope": scope, "prompt": goal, "count": total,
                        "state": "queued", "created_at": now, "updated_at": now,
                        "parameter_hash": digest, "request": request,
                    }, jobs, True
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        def read():
            conn = self._connect()
            try:
                return self._row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def list(self, *, scope: str = "", limit: int = 50, project_id: str = "") -> list[dict[str, Any]]:
        def read():
            conn = self._connect()
            try:
                if project_id and scope:
                    rows = conn.execute(
                        "SELECT * FROM jobs WHERE scope=? AND json_extract(request_json, '$.project_id')=? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (scope, project_id, max(1, min(limit, 1000))),
                    ).fetchall()
                elif scope:
                    rows = conn.execute(
                        "SELECT * FROM jobs WHERE scope=? ORDER BY created_at DESC LIMIT ?",
                        (scope, max(1, min(limit, 100))),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                        (max(1, min(limit, 100)),),
                    ).fetchall()
                return [self._row(row) for row in rows if row is not None]
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def scopes(self) -> set[str]:
        def read():
            conn = self._connect()
            try:
                return {str(row[0]) for row in conn.execute("SELECT DISTINCT scope FROM jobs")}
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        provider_id: str | None = None,
        upstream_task_id: str | None = None,
        accepted_state: str | None = None,
        delivery_state: str | None = None,
    ) -> dict[str, Any] | None:
        def write():
            now = time.time()
            conn = self._connect()
            try:
                with conn:
                    current = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                    if current is None:
                        return None
                    next_state = state or current["state"]
                    finished = now if next_state in TERMINAL_JOB_STATES else current["finished_at"]
                    next_result = result if result is not None else json.loads(current["result_json"])
                    conn.execute(
                        "UPDATE jobs SET state=?,updated_at=?,finished_at=?,result_json=?,error=?,"
                        "provider_id=?,upstream_task_id=?,accepted_state=?,delivery_state=? WHERE id=?",
                        (
                            next_state, now, finished,
                            json.dumps(next_result, ensure_ascii=False),
                            str(error if error is not None else current["error"] or "")[:1000],
                            str(provider_id if provider_id is not None else current["provider_id"] or "")[:160],
                            str(upstream_task_id if upstream_task_id is not None else current["upstream_task_id"] or "")[:300],
                            str(accepted_state if accepted_state is not None else current["accepted_state"] or "")[:40],
                            str(delivery_state if delivery_state is not None else current["delivery_state"] or "pending")[:40],
                            job_id,
                        ),
                    )
                    return self._row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            finally:
                conn.close()
        return await asyncio.to_thread(write)

    async def mark_interrupted(self) -> int:
        def write():
            conn = self._connect()
            try:
                with conn:
                    result = conn.execute(
                        "UPDATE jobs SET state='interrupted',updated_at=?,error=? "
                        "WHERE state IN ('queued','running')",
                        (time.time(), "AstrBot 重启后任务未自动重新提交，上游状态需要继续查询"),
                    )
                    return result.rowcount
            finally:
                conn.close()
        return await asyncio.to_thread(write)
