"""Async SQLite storage for flows and runs."""
from __future__ import annotations
import json
import os
from typing import List, Optional

import aiosqlite

from .models import Flow, RunRecord

DB_PATH = os.environ.get("FIO_DB", "./fio_orchestrator.db")


async def _conn():
    return await aiosqlite.connect(DB_PATH)


async def init_db():
    async with await _conn() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS flows (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                flow_id TEXT,
                data TEXT NOT NULL,
                status TEXT,
                started_at TEXT
            )
        """)
        await db.commit()


# ───────────────── Flow CRUD ──────────────────────────────────────────────

async def save_flow(flow: Flow) -> None:
    async with await _conn() as db:
        await db.execute(
            "INSERT OR REPLACE INTO flows (id, data, created_at, updated_at) VALUES (?,?,?,?)",
            (flow.id, flow.model_dump_json(), str(flow.created_at), str(flow.updated_at)),
        )
        await db.commit()


async def get_flow(flow_id: str) -> Optional[Flow]:
    async with await _conn() as db:
        async with db.execute("SELECT data FROM flows WHERE id=?", (flow_id,)) as cur:
            row = await cur.fetchone()
    if row:
        return Flow.model_validate_json(row[0])
    return None


async def list_flows() -> List[Flow]:
    async with await _conn() as db:
        async with db.execute("SELECT data FROM flows ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    return [Flow.model_validate_json(r[0]) for r in rows]


async def delete_flow(flow_id: str) -> bool:
    async with await _conn() as db:
        cur = await db.execute("DELETE FROM flows WHERE id=?", (flow_id,))
        await db.commit()
        return cur.rowcount > 0


# ───────────────── Run CRUD ───────────────────────────────────────────────

async def save_run(run: RunRecord) -> None:
    async with await _conn() as db:
        await db.execute(
            "INSERT OR REPLACE INTO runs (id, flow_id, data, status, started_at) VALUES (?,?,?,?,?)",
            (run.id, run.flow_id, run.model_dump_json(),
             run.status, str(run.started_at)),
        )
        await db.commit()


async def get_run(run_id: str) -> Optional[RunRecord]:
    async with await _conn() as db:
        async with db.execute("SELECT data FROM runs WHERE id=?", (run_id,)) as cur:
            row = await cur.fetchone()
    if row:
        return RunRecord.model_validate_json(row[0])
    return None


async def list_runs(flow_id: Optional[str] = None) -> List[RunRecord]:
    async with await _conn() as db:
        if flow_id:
            async with db.execute(
                "SELECT data FROM runs WHERE flow_id=? ORDER BY started_at DESC",
                (flow_id,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT data FROM runs ORDER BY started_at DESC"
            ) as cur:
                rows = await cur.fetchall()
    return [RunRecord.model_validate_json(r[0]) for r in rows]
