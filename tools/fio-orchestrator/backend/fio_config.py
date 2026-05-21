"""FIO job file generator and template library."""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List, Optional
from .models import FioGlobalOptions, FioJob, FioStepConfig


# ──────────────────────────── .fio file generator ─────────────────────────

def _kv(key: str, val: Any) -> str:
    """Format a single FIO key=value line, skipping None."""
    if val is None:
        return ""
    return f"{key}={val}"


def render_fio_file(cfg: FioStepConfig, log_dir: str, step_name: str) -> str:
    """Render a complete .fio file string from a FioStepConfig."""
    lines: List[str] = []

    # [global]
    lines.append("[global]")
    g = cfg.global_options
    global_dict = g.model_dump(exclude_none=True)

    # Always use JSON output for parsing; normalise the key name
    global_dict.pop("output_format", None)
    lines.append("output-format=json")

    # Inject log paths relative to step's log_dir
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", step_name)
    global_dict.setdefault("write_bw_log",   os.path.join(log_dir, safe))
    global_dict.setdefault("write_iops_log", os.path.join(log_dir, safe))
    global_dict.setdefault("write_lat_log",  os.path.join(log_dir, safe))

    for k, v in global_dict.items():
        k_fio = k.replace("_", "-") if k in _HYPHEN_KEYS else k
        line = _kv(k_fio, v)
        if line:
            lines.append(line)

    lines.append("")

    # [jobN]
    for job in cfg.jobs:
        lines.append(f"[{job.name}]")
        job_dict = job.model_dump(exclude_none=True, exclude={"name", "description"})
        for k, v in job_dict.items():
            k_fio = k.replace("_", "-") if k in _HYPHEN_KEYS else k
            line = _kv(k_fio, v)
            if line:
                lines.append(line)
        lines.append("")

    return "\n".join(lines)


# Keys that FIO spells with hyphens rather than underscores
_HYPHEN_KEYS = {
    "output_format", "time_based", "ramp_time", "fill_device",
    "io_size", "fsync_on_close", "sync_file_range", "rate_iops",
    "rate_min", "rate_process", "offset_increment", "random_distribution",
    "cpus_allowed", "cpus_allowed_policy", "iomem_align", "log_avg_msec",
    "log_compression", "log_store_compressed", "new_group", "exitall",
    "exitall_on_error", "exec_prerun", "exec_postrun", "sqthread_poll",
    "sqthread_poll_cpu", "random_generator", "write_bw_log", "write_iops_log",
    "write_lat_log", "write_hist_log", "per_job_logs", "group_reporting",
    "iodepth_batch", "iodepth_batch_complete_min", "iodepth_batch_complete_max",
    "verify_pattern", "verify_fatal", "verify_dump", "do_verify",
    "number_ios", "norandommap", "lockmem", "iomem", "bsrange", "bssplit",
    "nrfiles", "openfiles", "prioclass", "startdelay",
}


# ─────────────────────────────── Templates ────────────────────────────────

def _g(**kwargs) -> FioGlobalOptions:
    return FioGlobalOptions(**kwargs)


def _j(**kwargs) -> FioJob:
    return FioJob(**kwargs)


TEMPLATES: List[Dict] = [
    {
        "id": "4k_randread",
        "name": "4K Random Read",
        "category": "IOPS",
        "description": "Peak random read IOPS — typical SSD/NVMe characterization.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="4k_randread", rw="randread", bs="4k", iodepth=128, numjobs=4)],
        ),
    },
    {
        "id": "4k_randwrite",
        "name": "4K Random Write",
        "category": "IOPS",
        "description": "Peak random write IOPS.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="4k_randwrite", rw="randwrite", bs="4k", iodepth=128, numjobs=4)],
        ),
    },
    {
        "id": "4k_randrw_7030",
        "name": "4K Random Mixed 70/30",
        "category": "IOPS",
        "description": "Realistic mixed workload — 70% read, 30% write.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="4k_randrw", rw="randrw", bs="4k", rwmixread=70,
                     iodepth=64, numjobs=4)],
        ),
    },
    {
        "id": "128k_seqread",
        "name": "128K Sequential Read",
        "category": "Throughput",
        "description": "Maximum sequential read bandwidth.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="128k_seqread", rw="read", bs="128k", iodepth=32, numjobs=1)],
        ),
    },
    {
        "id": "128k_seqwrite",
        "name": "128K Sequential Write",
        "category": "Throughput",
        "description": "Maximum sequential write bandwidth.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="128k_seqwrite", rw="write", bs="128k", iodepth=32, numjobs=1)],
        ),
    },
    {
        "id": "iodepth_sweep",
        "name": "Queue Depth Sweep (1→128)",
        "category": "Latency",
        "description": "Multiple jobs at increasing iodepth separated by stonewall — shows latency/IOPS trade-off curve.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=30,
                              ramp_time=3, group_reporting=1, filename="/dev/null"),
            jobs=[
                _j(name="qd1",   rw="randread", bs="4k", iodepth=1),
                _j(name="qd4",   rw="randread", bs="4k", iodepth=4,   stonewall=1),
                _j(name="qd16",  rw="randread", bs="4k", iodepth=16,  stonewall=1),
                _j(name="qd64",  rw="randread", bs="4k", iodepth=64,  stonewall=1),
                _j(name="qd128", rw="randread", bs="4k", iodepth=128, stonewall=1),
            ],
        ),
    },
    {
        "id": "bs_sweep",
        "name": "Block Size Sweep (512B→1M)",
        "category": "Throughput",
        "description": "Sequential read at 8 block sizes — maps throughput vs transfer size.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=20,
                              ramp_time=2, group_reporting=1, filename="/dev/null"),
            jobs=[
                _j(name="bs_512",  rw="read", bs="512",  iodepth=8),
                _j(name="bs_4k",   rw="read", bs="4k",   iodepth=8, stonewall=1),
                _j(name="bs_8k",   rw="read", bs="8k",   iodepth=8, stonewall=1),
                _j(name="bs_32k",  rw="read", bs="32k",  iodepth=8, stonewall=1),
                _j(name="bs_128k", rw="read", bs="128k", iodepth=8, stonewall=1),
                _j(name="bs_512k", rw="read", bs="512k", iodepth=8, stonewall=1),
                _j(name="bs_1m",   rw="read", bs="1m",   iodepth=8, stonewall=1),
            ],
        ),
    },
    {
        "id": "io_uring_4k",
        "name": "io_uring 4K Random Read",
        "category": "io_uring",
        "description": "Like 4K randread but using io_uring engine.",
        "config": FioStepConfig(
            global_options=_g(ioengine="io_uring", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="iou_4k_randread", rw="randread", bs="4k", iodepth=128,
                     numjobs=4, sqthread_poll=1)],
        ),
    },
    {
        "id": "latency_profile",
        "name": "Latency Profile (low depth)",
        "category": "Latency",
        "description": "Low queue depth to measure raw device latency distribution.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=60,
                              ramp_time=5, group_reporting=1),
            jobs=[_j(name="lat_profile", rw="randread", bs="4k", iodepth=1, numjobs=1)],
        ),
    },
    {
        "id": "write_verify",
        "name": "Write + Verify",
        "category": "Verification",
        "description": "Write data then read-verify it — data integrity check.",
        "config": FioStepConfig(
            global_options=_g(ioengine="sync", direct=1, group_reporting=1),
            jobs=[
                _j(name="write_phase", rw="write", bs="4k", size="1g",
                   verify="crc32c", do_verify=0),
                _j(name="verify_phase", rw="read", bs="4k", size="1g",
                   verify="crc32c", do_verify=1, stonewall=1),
            ],
        ),
    },
    {
        "id": "stress_full",
        "name": "Full Drive Stress",
        "category": "Stress",
        "description": "Long-running mixed workload stress test across full device.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=3600,
                              ramp_time=60, group_reporting=1, fill_device=1),
            jobs=[_j(name="stress", rw="randrw", bs="4k", rwmixread=60,
                     iodepth=64, numjobs=8)],
        ),
    },
    {
        "id": "numjobs_sweep",
        "name": "Num Jobs Sweep (1→16)",
        "category": "Scalability",
        "description": "Test how IOPS scale with number of parallel jobs.",
        "config": FioStepConfig(
            global_options=_g(ioengine="libaio", direct=1, time_based=1, runtime=30,
                              ramp_time=3, filename="/dev/null"),
            jobs=[
                _j(name="j1",  rw="randread", bs="4k", iodepth=32, numjobs=1),
                _j(name="j2",  rw="randread", bs="4k", iodepth=32, numjobs=2,  stonewall=1),
                _j(name="j4",  rw="randread", bs="4k", iodepth=32, numjobs=4,  stonewall=1),
                _j(name="j8",  rw="randread", bs="4k", iodepth=32, numjobs=8,  stonewall=1),
                _j(name="j16", rw="randread", bs="4k", iodepth=32, numjobs=16, stonewall=1),
            ],
        ),
    },
]

TEMPLATES_BY_ID = {t["id"]: t for t in TEMPLATES}
