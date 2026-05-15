"""FIO job file generation and async execution with real-time streaming."""
import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

from .config import FIO_BINARY, FIO_JOBS_DIR, RESULTS_DIR
from .database import FIOJob, FIOResult, IOTimeSeries, TestStatus


# --------------------------------------------------------------------------- #
#  Job file generation                                                         #
# --------------------------------------------------------------------------- #

def generate_job_file(job: FIOJob) -> Path:
    """Write an .fio INI job file and return its path."""
    lines = ["[global]"]

    def _add(key: str, val):
        if val is not None and val != "":
            lines.append(f"{key}={val}")

    _add("ioengine", job.ioengine)
    _add("direct", 1 if job.direct else 0)
    _add("sync", 1 if job.sync else 0)
    _add("group_reporting", 1 if job.group_reporting else 0)
    _add("time_based", 1 if job.time_based else 0)
    if job.runtime_s:
        _add("runtime", job.runtime_s)
    if job.ramp_time_s:
        _add("ramp_time", job.ramp_time_s)
    _add("iodepth", job.iodepth)
    _add("numjobs", job.numjobs)
    _add("size", job.size)
    _add("bs", job.bs)

    # Per-job write log files (enable time-series capture)
    log_prefix = str(RESULTS_DIR / f"job_{job.id}")
    _add("write_bw_log", log_prefix + "_bw")
    _add("write_iops_log", log_prefix + "_iops")
    _add("write_lat_log", log_prefix + "_lat")
    _add("log_avg_msec", 1000)

    lines.append("")
    lines.append(f"[{job.job_name}]")
    _add("rw", job.rw)
    _add("filename", job.filename)

    if job.rw in ("randrw", "rw"):
        _add("rwmixread", job.rwmixread)

    if job.fill_device:
        _add("fill_device", 1)

    if job.rate_iops:
        _add("rate_iops", job.rate_iops)

    # Append any extra raw options
    if job.extra_options:
        lines.append(job.extra_options)

    content = "\n".join(lines) + "\n"
    job_path = FIO_JOBS_DIR / f"session_{job.session_id}_job_{job.id}.fio"
    job_path.write_text(content)
    return job_path


# --------------------------------------------------------------------------- #
#  Async execution                                                             #
# --------------------------------------------------------------------------- #

async def run_fio_job(
    job: FIOJob,
    output_path: Path,
    send_line: Optional[callable] = None,
) -> tuple[int, dict]:
    """
    Run a single FIO job, stream stdout lines via send_line, and return
    (exit_code, parsed_json).
    """
    job_file = generate_job_file(job)

    cmd = [
        FIO_BINARY,
        str(job_file),
        "--output-format=json+",
        f"--output={output_path}",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    if send_line:
        await send_line(f"[fio] Starting: {' '.join(cmd)}\n")

    async for raw in proc.stdout:
        line = raw.decode(errors="replace")
        if send_line:
            await send_line(line)

    await proc.wait()

    parsed = {}
    if output_path.exists():
        try:
            parsed = json.loads(output_path.read_text())
        except json.JSONDecodeError:
            pass

    return proc.returncode, parsed


# --------------------------------------------------------------------------- #
#  Per-second log file parsers                                                 #
# --------------------------------------------------------------------------- #

def _parse_fio_log(path: Path) -> list[dict]:
    """Parse FIO write_*_log CSV: time_ms, value, direction(0=r,1=w), bs."""
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            rows.append({
                "elapsed_ms": int(parts[0].strip()),
                "value": float(parts[1].strip()),
                "direction": int(parts[2].strip()),  # 0=read, 1=write
            })
        except (ValueError, IndexError):
            continue
    return rows


def load_time_series(job: FIOJob) -> list[IOTimeSeries]:
    """
    Load BW + IOPS + lat log files for a job and merge into IOTimeSeries rows.
    Returns unsaved ORM objects.
    """
    prefix = str(RESULTS_DIR / f"job_{job.id}")

    # FIO appends _bw.1.log etc. per numjobs — aggregate by elapsed_ms bucket
    def _load_glob(suffix: str):
        base = Path(prefix + suffix)
        files = list(Path(base.parent).glob(base.name + "*"))
        rows: list[dict] = []
        for f in files:
            rows.extend(_parse_fio_log(f))
        return rows

    bw_rows = _load_glob("_bw")
    iops_rows = _load_glob("_iops")
    lat_rows = _load_glob("_lat")

    # Build a dict keyed by (elapsed_ms, direction)
    buckets: dict[tuple, dict] = {}

    def _merge(rows: list[dict], field_r: str, field_w: str):
        for r in rows:
            key = (r["elapsed_ms"], r["direction"])
            if key not in buckets:
                buckets[key] = {"elapsed_ms": r["elapsed_ms"]}
            buckets[key].setdefault(field_r, 0.0)
            buckets[key].setdefault(field_w, 0.0)
            if r["direction"] == 0:
                buckets[key][field_r] = r["value"]
            else:
                buckets[key][field_w] = r["value"]

    _merge(bw_rows,   "bw_read_kbps",  "bw_write_kbps")
    _merge(iops_rows, "iops_read",     "iops_write")
    _merge(lat_rows,  "lat_read_ns",   "lat_write_ns")

    objs = []
    seen_ms: set[int] = set()
    for (ms, _dir), vals in sorted(buckets.items(), key=lambda x: x[0][0]):
        if ms in seen_ms:
            # Merge into existing obj
            for o in objs:
                if o.elapsed_ms == ms:
                    for k, v in vals.items():
                        if k != "elapsed_ms":
                            setattr(o, k, getattr(o, k, 0.0) + v)
            continue
        seen_ms.add(ms)
        obj = IOTimeSeries(
            job_id=job.id,
            elapsed_ms=ms,
            iops_read=vals.get("iops_read", 0.0),
            iops_write=vals.get("iops_write", 0.0),
            bw_read_kbps=vals.get("bw_read_kbps", 0.0),
            bw_write_kbps=vals.get("bw_write_kbps", 0.0),
            lat_read_ns=vals.get("lat_read_ns", 0.0),
            lat_write_ns=vals.get("lat_write_ns", 0.0),
        )
        objs.append(obj)

    return objs


# --------------------------------------------------------------------------- #
#  Pre-defined workload profiles                                               #
# --------------------------------------------------------------------------- #

WORKLOAD_PROFILES = {
    "seq_read": {
        "label": "Sequential Read",
        "jobs": [{"rw": "read",    "bs": "1m",  "iodepth": qd} for qd in [1, 4, 16]],
    },
    "seq_write": {
        "label": "Sequential Write",
        "jobs": [{"rw": "write",   "bs": "1m",  "iodepth": qd} for qd in [1, 4, 16]],
    },
    "rand4k_read": {
        "label": "Random 4K Read",
        "jobs": [{"rw": "randread", "bs": "4k", "iodepth": qd} for qd in [1, 4, 8, 16, 32, 64]],
    },
    "rand4k_write": {
        "label": "Random 4K Write",
        "jobs": [{"rw": "randwrite","bs": "4k", "iodepth": qd} for qd in [1, 4, 8, 16, 32, 64]],
    },
    "mixed_7030": {
        "label": "Mixed 70/30 (rand)",
        "jobs": [{"rw": "randrw",  "bs": "4k",  "iodepth": qd, "rwmixread": 70}
                 for qd in [1, 4, 8, 16, 32]],
    },
    "database": {
        "label": "Database (OLTP)",
        "jobs": [
            {"rw": "randrw",  "bs": "4k",  "iodepth": 8,  "rwmixread": 70},
            {"rw": "randrw",  "bs": "8k",  "iodepth": 16, "rwmixread": 50},
            {"rw": "randread","bs": "4k",  "iodepth": 32},
        ],
    },
    "video_streaming": {
        "label": "Video Streaming",
        "jobs": [{"rw": "read", "bs": "256k", "iodepth": qd} for qd in [1, 2, 4]],
    },
    "bs_sweep": {
        "label": "Block-Size Sweep (random read)",
        "jobs": [{"rw": "randread", "bs": bs, "iodepth": 32}
                 for bs in ["512", "4k", "8k", "16k", "32k", "64k", "128k", "256k", "512k", "1m"]],
    },
    "qd_sweep": {
        "label": "Queue-Depth Sweep (random 4K read)",
        "jobs": [{"rw": "randread", "bs": "4k", "iodepth": qd}
                 for qd in [1, 2, 4, 8, 16, 32, 64, 128, 256]],
    },
}
