"""
FIO Workload Analyzer — FastAPI backend.

Endpoints:
  GET  /api/drives              — list NVMe/block devices
  GET  /api/profiles            — built-in workload profiles
  POST /api/sessions            — create & start a test session
  GET  /api/sessions            — list sessions
  GET  /api/sessions/{id}       — session detail
  GET  /api/sessions/{id}/results — all job results for session
  GET  /api/sessions/{id}/export — download Excel report
  POST /api/sessions/{id}/plots  — generate / list session plots
  GET  /api/sessions/{id}/logs  — system logs for session
  GET  /api/sessions/compare    — compare multiple sessions
  GET  /api/jobs/{id}/timeseries — time-series for a job
  POST /api/ml/train            — train ML models on all stored data
  POST /api/ml/predict/{session_id} — run ML inference on a session
  GET  /api/ml/models           — list trained model metadata
  WS   /ws/sessions/{id}        — real-time test output
"""
import asyncio
import json
import os
import platform
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
from fastapi import (Depends, FastAPI, HTTPException, Query, WebSocket,
                     WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .analyzer import (analyze_time_series, build_ml_feature_vector,
                        compare_sessions, compute_derived_metrics)
from .config import CORS_ORIGINS, EXPORTS_DIR, PLOTS_DIR
from .database import (DriveSnapshot, FIOJob, FIOResult, IOTimeSeries,
                        MLModel, SystemLog, TestSession, TestStatus,
                        create_tables, get_db)
from .excel_exporter import export_session_to_excel
from .fio_runner import WORKLOAD_PROFILES, load_time_series, run_fio_job
from .log_capture import (capture_all, capture_drive_snapshot,
                           list_block_devices, list_nvme_devices)
from .log_parser import parse_fio_output_file
from .ml_engine import (compute_health_score, get_age_regressor,
                         get_anomaly_detector, get_fw_fingerprint,
                         get_trend_forecaster)
from .plotter import generate_session_plots

app = FastAPI(
    title="FIO Workload Analyzer",
    version="1.0.0",
    description="SSD performance testing, log capture, ML-driven analysis",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
_frontend = Path(__file__).parent.parent / "frontend"
if _frontend.exists():
    app.mount("/ui", StaticFiles(directory=str(_frontend), html=True), name="frontend")

create_tables()

# Active WebSocket connections keyed by session_id
_ws_clients: dict[int, list[WebSocket]] = {}


# --------------------------------------------------------------------------- #
#  Pydantic schemas                                                            #
# --------------------------------------------------------------------------- #

class JobSpec(BaseModel):
    job_name: str = ""
    rw: str = "randread"
    bs: str = "4k"
    iodepth: int = 32
    numjobs: int = 1
    size: str = "100%"
    runtime_s: Optional[int] = 60
    ramp_time_s: int = 10
    filename: str
    ioengine: str = "libaio"
    direct: bool = True
    sync: bool = False
    rwmixread: int = 70
    time_based: bool = True
    fill_device: bool = False
    group_reporting: bool = True
    rate_iops: Optional[int] = None
    extra_options: str = ""


class SessionCreate(BaseModel):
    name: str
    description: str = ""
    tags: str = ""
    jobs: list[JobSpec]
    profile: Optional[str] = None          # built-in profile key
    capture_logs: bool = True
    drive_device: Optional[str] = None


class MLTrainRequest(BaseModel):
    model_types: list[str] = Field(
        default=["anomaly", "age", "fw", "trend"],
        description="Which models to train",
    )


# --------------------------------------------------------------------------- #
#  Helper: broadcast to all WS clients of a session                           #
# --------------------------------------------------------------------------- #

async def _broadcast(session_id: int, msg: str):
    clients = _ws_clients.get(session_id, [])
    dead = []
    for ws in clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.remove(ws)


# --------------------------------------------------------------------------- #
#  System info                                                                 #
# --------------------------------------------------------------------------- #

def _host_info() -> dict:
    return {
        "host_name":      socket.gethostname(),
        "kernel_version": platform.release(),
        "cpu_model":      _cpu_model(),
        "ram_gb":         round(psutil.virtual_memory().total / 1e9, 1),
    }


def _cpu_model() -> str:
    try:
        import cpuinfo
        return cpuinfo.get_cpu_info().get("brand_raw", platform.processor())
    except ImportError:
        return platform.processor()


# --------------------------------------------------------------------------- #
#  Routes — Device discovery                                                   #
# --------------------------------------------------------------------------- #

@app.get("/api/drives")
def get_drives():
    nvme  = list_nvme_devices()
    block = list_block_devices()
    all_devs = {d["device"]: d for d in block}
    for n in nvme:
        all_devs[n["device"]] = {**all_devs.get(n["device"], {}), **n}
    return {"drives": list(all_devs.values())}


@app.get("/api/profiles")
def get_profiles():
    return {
        k: {"label": v["label"], "n_jobs": len(v["jobs"])}
        for k, v in WORKLOAD_PROFILES.items()
    }


# --------------------------------------------------------------------------- #
#  Routes — Sessions                                                           #
# --------------------------------------------------------------------------- #

@app.get("/api/sessions")
def list_sessions(
    limit: int = Query(50, le=200),
    offset: int = 0,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(TestSession)
    if status:
        q = q.filter(TestSession.status == status)
    total = q.count()
    sessions = q.order_by(TestSession.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "sessions": [_session_summary(s) for s in sessions],
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = _get_or_404(db, TestSession, session_id)
    jobs = db.query(FIOJob).filter(FIOJob.session_id == session_id).all()
    results = {j.id: j.result for j in jobs}
    return {
        "session": _session_detail(s),
        "jobs": [_job_detail(j, results.get(j.id)) for j in jobs],
    }


@app.post("/api/sessions", status_code=202)
async def create_session(req: SessionCreate, db: Session = Depends(get_db)):
    info = _host_info()

    session = TestSession(
        name=req.name,
        description=req.description,
        tags=req.tags,
        drive_device=req.drive_device,
        **info,
    )
    db.add(session); db.commit(); db.refresh(session)

    # Resolve jobs from profile or inline spec
    job_specs: list[dict] = []
    if req.profile and req.profile in WORKLOAD_PROFILES:
        profile_jobs = WORKLOAD_PROFILES[req.profile]["jobs"]
        for pj in profile_jobs:
            spec = pj.copy()
            spec.setdefault("filename", req.jobs[0].filename if req.jobs else "/dev/null")
            spec.setdefault("runtime_s", req.jobs[0].runtime_s if req.jobs else 60)
            job_specs.append(spec)
    else:
        job_specs = [j.model_dump() for j in req.jobs]

    # Create job records
    fio_jobs: list[FIOJob] = []
    for idx, spec in enumerate(job_specs):
        name = spec.get("job_name") or f"{spec.get('rw','io')}_{spec.get('bs','4k')}_qd{spec.get('iodepth',1)}"
        job = FIOJob(
            session_id=session.id,
            job_index=idx,
            job_name=name,
            rw=spec.get("rw", "randread"),
            bs=spec.get("bs", "4k"),
            iodepth=spec.get("iodepth", 32),
            numjobs=spec.get("numjobs", 1),
            size=spec.get("size", "100%"),
            runtime_s=spec.get("runtime_s", 60),
            ramp_time_s=spec.get("ramp_time_s", 10),
            filename=spec.get("filename", "/dev/null"),
            ioengine=spec.get("ioengine", "libaio"),
            direct=spec.get("direct", True),
            sync=spec.get("sync", False),
            rwmixread=spec.get("rwmixread", 70),
            time_based=spec.get("time_based", True),
            fill_device=spec.get("fill_device", False),
            group_reporting=spec.get("group_reporting", True),
            rate_iops=spec.get("rate_iops"),
            extra_options=spec.get("extra_options", ""),
        )
        db.add(job)
    db.commit()

    # Kick off background execution
    asyncio.create_task(_run_session(session.id, req.capture_logs))
    return {"session_id": session.id, "status": "accepted"}


# --------------------------------------------------------------------------- #
#  Background session runner                                                   #
# --------------------------------------------------------------------------- #

async def _run_session(session_id: int, capture_logs: bool):
    from .database import SessionLocal
    db = SessionLocal()
    try:
        session = db.query(TestSession).filter_by(id=session_id).first()
        session.status = TestStatus.RUNNING
        session.started_at = datetime.utcnow()
        db.commit()

        await _broadcast(session_id, f"[session] Started: {session.name}\n")

        # Pre-session log capture
        if capture_logs:
            await _broadcast(session_id, "[logs] Capturing pre-test logs...\n")
            pre_logs = await capture_all(session_id, None, "pre", session.drive_device)
            for log in pre_logs:
                db.add(log)

            if session.drive_device:
                snap = await capture_drive_snapshot(session.drive_device, session_id, "pre")
                db.add(snap)
                session.drive_model    = snap.smart_json and _extract_model(snap.smart_json)
                session.drive_serial   = snap.smart_json and _extract_serial(snap.smart_json)
                session.drive_firmware = snap.smart_json and _extract_firmware(snap.smart_json)
            db.commit()

        jobs = (db.query(FIOJob)
                  .filter_by(session_id=session_id)
                  .order_by(FIOJob.job_index)
                  .all())

        for job in jobs:
            await _broadcast(session_id,
                f"[job] Starting {job.job_name} ({job.rw} bs={job.bs} qd={job.iodepth})\n")

            # Pre-job logs
            if capture_logs:
                pre_job_logs = await capture_all(session_id, job.id, "pre", session.drive_device)
                for log in pre_job_logs:
                    db.add(log)
                db.commit()

            job.status = TestStatus.RUNNING
            job.started_at = datetime.utcnow()
            db.commit()

            from .config import RESULTS_DIR
            out_path = RESULTS_DIR / f"job_{job.id}_fio.json"
            job.raw_output_path = str(out_path)

            async def _send(line: str):
                await _broadcast(session_id, line)

            exit_code, raw_json = await run_fio_job(job, out_path, _send)

            job.exit_code = exit_code
            job.completed_at = datetime.utcnow()
            job.status = TestStatus.COMPLETED if exit_code == 0 else TestStatus.FAILED
            db.commit()

            # Parse results
            if exit_code == 0 and raw_json:
                from .log_parser import parse_fio_json
                result = parse_fio_json(json.dumps(raw_json), job.id)
                if result:
                    db.add(result); db.commit()

                # Load and store time-series
                ts_rows = load_time_series(job)
                for row in ts_rows:
                    db.add(row)
                db.commit()

            # Post-job logs
            if capture_logs:
                post_job_logs = await capture_all(session_id, job.id, "post", session.drive_device)
                for log in post_job_logs:
                    db.add(log)
                db.commit()

            m = compute_derived_metrics(job.result) if job.result else {}
            await _broadcast(session_id,
                f"[result] {job.job_name}: R={m.get('read_iops',0):.0f} IOPS "
                f"W={m.get('write_iops',0):.0f} IOPS "
                f"R_P99={m.get('read_p99_us',0):.1f}µs\n")

        # Post-session logs
        if capture_logs:
            await _broadcast(session_id, "[logs] Capturing post-test logs...\n")
            post_logs = await capture_all(session_id, None, "post", session.drive_device)
            for log in post_logs:
                db.add(log)
            if session.drive_device:
                snap = await capture_drive_snapshot(session.drive_device, session_id, "post")
                db.add(snap)
            db.commit()

        session.status = TestStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        db.commit()
        await _broadcast(session_id, "[session] Completed!\n")

    except Exception as e:
        db.query(TestSession).filter_by(id=session_id).update(
            {"status": TestStatus.FAILED, "error_message": str(e)}
        )
        db.commit()
        await _broadcast(session_id, f"[error] {e}\n")
    finally:
        db.close()


def _extract_model(smart_json: str) -> Optional[str]:
    try:
        return json.loads(smart_json).get("model_number", "")
    except Exception:
        return None

def _extract_serial(smart_json: str) -> Optional[str]:
    try:
        return json.loads(smart_json).get("serial_number", "")
    except Exception:
        return None

def _extract_firmware(smart_json: str) -> Optional[str]:
    try:
        return json.loads(smart_json).get("firmware_revision", "")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Routes — Results & exports                                                  #
# --------------------------------------------------------------------------- #

@app.get("/api/sessions/{session_id}/results")
def get_results(session_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, TestSession, session_id)
    jobs = db.query(FIOJob).filter_by(session_id=session_id).order_by(FIOJob.job_index).all()
    out = []
    for job in jobs:
        result = job.result
        metrics = compute_derived_metrics(result) if result else {}
        out.append({
            "job": _job_detail(job, result),
            "metrics": metrics,
        })
    return {"results": out}


@app.get("/api/sessions/{session_id}/export")
def export_excel(session_id: int, db: Session = Depends(get_db)):
    session = _get_or_404(db, TestSession, session_id)
    jobs    = db.query(FIOJob).filter_by(session_id=session_id).order_by(FIOJob.job_index).all()
    results = [j.result for j in jobs]
    ts_map  = {j.id: db.query(IOTimeSeries).filter_by(job_id=j.id).all() for j in jobs}
    logs    = db.query(SystemLog).filter_by(session_id=session_id).all()
    snaps   = db.query(DriveSnapshot).filter_by(session_id=session_id).all()

    path = export_session_to_excel(session, jobs, results, ts_map, logs, snaps)
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/sessions/{session_id}/plots")
def generate_plots(session_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, TestSession, session_id)
    jobs = db.query(FIOJob).filter_by(session_id=session_id).order_by(FIOJob.job_index).all()
    results_with_jobs = [(j, j.result) for j in jobs]
    ts_map = {j.id: db.query(IOTimeSeries).filter_by(job_id=j.id).all() for j in jobs}
    paths = generate_session_plots(session_id, results_with_jobs, ts_map)
    return {"plots": paths}


@app.get("/api/plots/{filename}")
def get_plot(filename: str):
    path = PLOTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Plot not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/sessions/{session_id}/logs")
def get_logs(
    session_id: int,
    phase: Optional[str] = None,
    log_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _get_or_404(db, TestSession, session_id)
    q = db.query(SystemLog).filter_by(session_id=session_id)
    if phase:
        q = q.filter_by(phase=phase)
    if log_type:
        q = q.filter_by(log_type=log_type)
    logs = q.order_by(SystemLog.captured_at).all()
    return {
        "logs": [
            {
                "id":          l.id,
                "log_type":    l.log_type,
                "phase":       l.phase,
                "captured_at": l.captured_at.isoformat() if l.captured_at else None,
                "file_path":   l.file_path,
                "preview":     (l.content or "")[:500],
                "size":        len(l.content or ""),
            }
            for l in logs
        ]
    }


@app.get("/api/logs/{log_id}/content")
def get_log_content(log_id: int, db: Session = Depends(get_db)):
    log = _get_or_404(db, SystemLog, log_id)
    return {"content": log.content}


@app.get("/api/sessions/compare")
def compare(ids: str = Query(..., description="Comma-separated session IDs"),
            db: Session = Depends(get_db)):
    id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
    sessions_results = []
    for sid in id_list:
        s = db.query(TestSession).filter_by(id=sid).first()
        if not s:
            continue
        jobs = db.query(FIOJob).filter_by(session_id=sid).all()
        all_metrics: dict = {}
        for job in jobs:
            if job.result:
                m = compute_derived_metrics(job.result)
                for k, v in m.items():
                    if isinstance(v, (int, float)):
                        all_metrics[k] = all_metrics.get(k, 0) + v
        sessions_results.append({"session": s, "metrics": all_metrics})

    return compare_sessions(sessions_results)


# --------------------------------------------------------------------------- #
#  Routes — Time-series                                                        #
# --------------------------------------------------------------------------- #

@app.get("/api/jobs/{job_id}/timeseries")
def get_timeseries(job_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, FIOJob, job_id)
    rows = db.query(IOTimeSeries).filter_by(job_id=job_id).order_by(IOTimeSeries.elapsed_ms).all()
    stats = analyze_time_series(rows)
    return {
        "data": [
            {
                "t": r.elapsed_ms / 1000,
                "iops_read": r.iops_read, "iops_write": r.iops_write,
                "bw_read_mbps": r.bw_read_kbps / 1024, "bw_write_mbps": r.bw_write_kbps / 1024,
                "lat_read_us": r.lat_read_ns / 1000, "lat_write_us": r.lat_write_ns / 1000,
            }
            for r in rows
        ],
        "stats": stats,
    }


# --------------------------------------------------------------------------- #
#  Routes — ML                                                                 #
# --------------------------------------------------------------------------- #

@app.post("/api/ml/train")
def train_models(req: MLTrainRequest, db: Session = Depends(get_db)):
    # Collect all feature vectors from stored results
    jobs    = db.query(FIOJob).filter(FIOJob.result != None).all()
    vecs    = []
    tbw_pts = []  # (tbw_gb, iops) for trend model

    for job in jobs:
        r  = job.result
        ts = db.query(IOTimeSeries).filter_by(job_id=job.id).all()
        v  = build_ml_feature_vector(r, ts, job.bs, job.iodepth, job.rw)
        vecs.append(v)

        # TBW estimate from total bytes written
        tbw_gb = r.write_total_bytes / 1e9
        if tbw_gb > 0:
            tbw_pts.append((tbw_gb, r.write_iops))

    results_out = {}

    if "anomaly" in req.model_types and vecs:
        det = get_anomaly_detector()
        results_out["anomaly"] = det.train(vecs)

    if "age" in req.model_types and vecs:
        reg = get_age_regressor()
        results_out["age"] = reg.train(vecs)

    if "fw" in req.model_types and vecs:
        fp = get_fw_fingerprint()
        results_out["fw"] = fp.train(vecs)

    if "trend" in req.model_types and len(tbw_pts) >= 3:
        forecaster = get_trend_forecaster()
        tbw_vals  = [x[0] for x in tbw_pts]
        iops_vals = [x[1] for x in tbw_pts]
        results_out["trend"] = forecaster.train(tbw_vals, iops_vals)

    return {"trained": results_out, "n_samples": len(vecs)}


@app.get("/api/ml/predict/{session_id}")
def predict_session(session_id: int, db: Session = Depends(get_db)):
    _get_or_404(db, TestSession, session_id)
    jobs = db.query(FIOJob).filter_by(session_id=session_id).all()
    if not jobs or not jobs[0].result:
        raise HTTPException(400, "No results available for this session")

    predictions = []
    for job in jobs:
        r = job.result
        if not r:
            continue
        ts  = db.query(IOTimeSeries).filter_by(job_id=job.id).all()
        vec = build_ml_feature_vector(r, ts, job.bs, job.iodepth, job.rw)

        anomaly = get_anomaly_detector().predict(vec)
        age     = get_age_regressor().predict(vec)
        fw      = get_fw_fingerprint().predict(vec)

        snaps = db.query(DriveSnapshot).filter_by(session_id=session_id).all()
        pre_snap  = next((s for s in snaps if s.phase == "pre"),  None)
        post_snap = next((s for s in snaps if s.phase == "post"), None)

        health = compute_health_score(
            r,
            smart_available_spare=post_snap.available_spare_pct if post_snap else None,
            smart_pct_used=post_snap.percentage_used if post_snap else None,
            age_prediction=age,
            anomaly_prediction=anomaly,
        )

        # TBW trend forecast
        tbw_future = [r.write_total_bytes / 1e9 * x for x in [1, 2, 5, 10]]
        trend = get_trend_forecaster().predict(tbw_future)

        predictions.append({
            "job_id":    job.id,
            "job_name":  job.job_name,
            "anomaly":   anomaly,
            "age":       age,
            "fw":        fw,
            "health":    health,
            "trend":     trend,
        })

    return {"predictions": predictions}


# --------------------------------------------------------------------------- #
#  WebSocket                                                                   #
# --------------------------------------------------------------------------- #

@app.websocket("/ws/sessions/{session_id}")
async def ws_session(session_id: int, websocket: WebSocket):
    await websocket.accept()
    _ws_clients.setdefault(session_id, []).append(websocket)
    try:
        while True:
            # Keep alive — client can also send pings
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        clients = _ws_clients.get(session_id, [])
        if websocket in clients:
            clients.remove(websocket)


# --------------------------------------------------------------------------- #
#  Utility serializers                                                         #
# --------------------------------------------------------------------------- #

def _session_summary(s: TestSession) -> dict:
    return {
        "id": s.id, "name": s.name, "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "drive_model": s.drive_model, "drive_device": s.drive_device,
        "n_jobs": len(s.jobs), "tags": s.tags,
    }


def _session_detail(s: TestSession) -> dict:
    return {
        **_session_summary(s),
        "description": s.description,
        "drive_serial": s.drive_serial, "drive_firmware": s.drive_firmware,
        "drive_capacity_gb": s.drive_capacity_gb,
        "host_name": s.host_name, "kernel_version": s.kernel_version,
        "cpu_model": s.cpu_model, "ram_gb": s.ram_gb,
        "started_at":   s.started_at.isoformat()   if s.started_at   else None,
        "completed_at": s.completed_at.isoformat()  if s.completed_at else None,
        "error_message": s.error_message,
    }


def _job_detail(j: FIOJob, r: Optional[FIOResult]) -> dict:
    d = {
        "id": j.id, "job_name": j.job_name, "job_index": j.job_index,
        "rw": j.rw, "bs": j.bs, "iodepth": j.iodepth, "numjobs": j.numjobs,
        "size": j.size, "runtime_s": j.runtime_s, "filename": j.filename,
        "ioengine": j.ioengine, "direct": j.direct,
        "status": j.status,
        "started_at":   j.started_at.isoformat()   if j.started_at   else None,
        "completed_at": j.completed_at.isoformat()  if j.completed_at else None,
        "exit_code": j.exit_code,
    }
    if r:
        d["result"] = {
            "read_iops": r.read_iops, "write_iops": r.write_iops,
            "read_bw_mbps":  r.read_bw_kbps  / 1024,
            "write_bw_mbps": r.write_bw_kbps / 1024,
            "read_p99_us":   r.read_clat_p99_ns  / 1000,
            "write_p99_us":  r.write_clat_p99_ns / 1000,
            "read_p999_us":  r.read_clat_p999_ns / 1000,
            "write_p999_us": r.write_clat_p999_ns / 1000,
            "cpu_usr": r.cpu_usr, "cpu_sys": r.cpu_sys,
            "gc_pause_score": r.gc_pause_score,
            "write_amp_est":  r.write_amp_est,
            "iops_stability": r.iops_stability,
            "lat_tail_ratio": r.lat_tail_ratio,
        }
    return d


def _get_or_404(db: Session, model, pk: int):
    obj = db.query(model).filter_by(id=pk).first()
    if not obj:
        raise HTTPException(404, f"{model.__name__} {pk} not found")
    return obj


# --------------------------------------------------------------------------- #
#  Health check                                                                #
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
