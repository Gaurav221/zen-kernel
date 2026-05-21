"""FastAPI application — FIO Orchestrator."""
from __future__ import annotations
import asyncio
import io
import json
import os
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import delete_flow, get_flow, get_run, init_db, list_flows, list_runs, save_flow, save_run
from .exporter import export_flow
from .fio_config import TEMPLATES
from .log_parser import build_step_summary
from .models import (
    ExportRequest, Flow, RunRecord, StepStatus, WsMessage,
)
from .executor import execute_flow

app = FastAPI(title="FIO Orchestrator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections keyed by run_id
_ws_clients: Dict[str, List[WebSocket]] = {}
# Active run tasks keyed by run_id
_run_tasks: Dict[str, asyncio.Task] = {}


@app.on_event("startup")
async def startup():
    await init_db()


# ─────────────────────────────── Flows ────────────────────────────────────

@app.get("/api/flows")
async def list_flows_route():
    flows = await list_flows()
    return [f.model_dump(mode="json") for f in flows]


@app.post("/api/flows", status_code=201)
async def create_flow(flow: Flow):
    flow.created_at = datetime.utcnow()
    flow.updated_at = datetime.utcnow()
    await save_flow(flow)
    return flow.model_dump(mode="json")


@app.get("/api/flows/{flow_id}")
async def get_flow_route(flow_id: str):
    flow = await get_flow(flow_id)
    if not flow:
        raise HTTPException(404, "Flow not found")
    return flow.model_dump(mode="json")


@app.put("/api/flows/{flow_id}")
async def update_flow(flow_id: str, flow: Flow):
    existing = await get_flow(flow_id)
    if not existing:
        raise HTTPException(404, "Flow not found")
    flow.id = flow_id
    flow.created_at = existing.created_at
    flow.updated_at = datetime.utcnow()
    await save_flow(flow)
    return flow.model_dump(mode="json")


@app.delete("/api/flows/{flow_id}", status_code=204)
async def delete_flow_route(flow_id: str):
    if not await delete_flow(flow_id):
        raise HTTPException(404, "Flow not found")


# ─────────────────────────────── Templates ────────────────────────────────

@app.get("/api/templates")
async def get_templates():
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "category": t["category"],
            "description": t["description"],
            "config": t["config"].model_dump(mode="json"),
        }
        for t in TEMPLATES
    ]


# ────────────────────────────── Run flow ──────────────────────────────────

@app.post("/api/flows/{flow_id}/run", status_code=202)
async def run_flow(flow_id: str, output_dir: Optional[str] = None):
    flow = await get_flow(flow_id)
    if not flow:
        raise HTTPException(404, "Flow not found")

    step_statuses = [
        StepStatus(step_id=s.id, step_name=s.name, status="pending")
        for s in flow.steps
    ]
    run = RunRecord(
        flow_id=flow.id,
        flow_name=flow.name,
        status="running",
        output_dir=output_dir or flow.output_dir or "./results",
        steps=step_statuses,
    )
    await save_run(run)

    def _broadcast(msg: WsMessage):
        clients = _ws_clients.get(run.id, [])
        payload = msg.model_dump_json()
        for ws in list(clients):
            asyncio.create_task(ws.send_text(payload))

    async def _run():
        try:
            await execute_flow(run, flow.steps, flow.edges, _broadcast)
        except Exception as e:
            run.status = "error"
        finally:
            await save_run(run)

    task = asyncio.create_task(_run())
    _run_tasks[run.id] = task
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    task = _run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
    run = await get_run(run_id)
    if run:
        run.status = "cancelled"
        run.finished_at = datetime.utcnow()
        await save_run(run)
        return run.model_dump(mode="json")
    raise HTTPException(404, "Run not found")


# ────────────────────────────── Run queries ───────────────────────────────

@app.get("/api/runs")
async def list_runs_route(flow_id: Optional[str] = None):
    runs = await list_runs(flow_id)
    return [r.model_dump(mode="json") for r in runs]


@app.get("/api/runs/{run_id}")
async def get_run_route(run_id: str):
    run = await get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run.model_dump(mode="json")


@app.get("/api/runs/{run_id}/summary")
async def get_run_summary(run_id: str):
    run = await get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    summaries = []
    for step in run.steps:
        if step.log_dir:
            summaries.append(build_step_summary(step.log_dir))
    return {"run_id": run_id, "steps": summaries}


@app.get("/api/runs/{run_id}/steps/{step_id}/summary")
async def get_step_summary(run_id: str, step_id: str):
    run = await get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    step = next((s for s in run.steps if s.step_id == step_id), None)
    if not step:
        raise HTTPException(404, "Step not found")
    if not step.log_dir:
        return {}
    return build_step_summary(step.log_dir)


# ──────────────────────────── WebSocket stream ────────────────────────────

@app.websocket("/ws/runs/{run_id}")
async def ws_run_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()
    _ws_clients.setdefault(run_id, []).append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.get(run_id, []).remove(websocket)


# ─────────────────────────────── Export ───────────────────────────────────

@app.post("/api/export")
async def export_route(req: ExportRequest):
    """Return a zip file containing all exported files."""
    files = export_flow(req.flow, req.format, req.output_dir)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, content in files:
            zf.writestr(rel_path, content)
    buf.seek(0)

    safe_name = req.flow.name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_fio_scripts.zip"'},
    )


@app.post("/api/export/preview")
async def export_preview(req: ExportRequest):
    """Return exported file contents as JSON (for preview in the UI)."""
    files = export_flow(req.flow, req.format, req.output_dir)
    return [{"path": path, "content": content} for path, content in files]


# ──────────────────────── Static frontend ─────────────────────────────────

_static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
