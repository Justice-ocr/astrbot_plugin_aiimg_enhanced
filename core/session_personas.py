from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path


class SessionPersonas:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "session_personas.sqlite3"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.execute("CREATE TABLE IF NOT EXISTS selections (scope TEXT PRIMARY KEY, persona TEXT NOT NULL)")
        return conn

    async def get(self, scope: str) -> str:
        def read():
            conn = self._connect()
            try:
                row = conn.execute("SELECT persona FROM selections WHERE scope=?", (scope,)).fetchone()
                return row[0] if row else ""
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def set(self, scope: str, persona: str) -> None:
        def write():
            conn = self._connect()
            try:
                with conn:
                    if persona:
                        conn.execute("INSERT OR REPLACE INTO selections VALUES (?,?)", (scope, persona))
                    else:
                        conn.execute("DELETE FROM selections WHERE scope=?", (scope,))
            finally:
                conn.close()
        await asyncio.to_thread(write)

    async def list(self):
        def read():
            conn = self._connect()
            try:
                return dict(conn.execute("SELECT scope, persona FROM selections"))
            finally:
                conn.close()
        return await asyncio.to_thread(read)

    async def clear_persona(self, persona: str) -> int:
        """Remove stale selections after a persona is deleted."""
        value = str(persona or "").strip()
        if not value:
            return 0

        def write():
            conn = self._connect()
            try:
                with conn:
                    result = conn.execute("DELETE FROM selections WHERE persona=?", (value,))
                    return int(result.rowcount)
            finally:
                conn.close()

        return await asyncio.to_thread(write)
