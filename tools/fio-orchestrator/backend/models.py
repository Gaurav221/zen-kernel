from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


# ─────────────────────────── FIO Job Parameters ───────────────────────────

class FioGlobalOptions(BaseModel):
    """[global] section of a .fio file — applies to all jobs unless overridden."""
    ioengine: str = "libaio"
    direct: int = 1
    group_reporting: int = 1
    time_based: int = 1
    runtime: int = 60
    ramp_time: int = 5
    filename: Optional[str] = None
    directory: Optional[str] = None
    size: Optional[str] = None
    numjobs: int = 1
    thread: int = 1
    output_format: str = "json"
    log_avg_msec: int = 500

    class Config:
        extra = "allow"  # pass-through any extra FIO params


class FioJob(BaseModel):
    """A single [jobname] block in a .fio file."""
    name: str = "job"
    description: Optional[str] = None

    # Workload
    rw: str = "randread"
    rwmixread: Optional[int] = None
    rwmixwrite: Optional[int] = None
    bs: str = "4k"
    bsrange: Optional[str] = None
    bssplit: Optional[str] = None
    iodepth: int = 32
    iodepth_batch: Optional[int] = None
    iodepth_batch_complete_min: Optional[int] = None
    iodepth_batch_complete_max: Optional[int] = None
    numjobs: Optional[int] = None

    # Target
    filename: Optional[str] = None
    directory: Optional[str] = None
    size: Optional[str] = None
    fill_device: Optional[int] = None
    filesize: Optional[str] = None
    io_size: Optional[str] = None
    nrfiles: Optional[int] = None
    openfiles: Optional[int] = None

    # Timing
    runtime: Optional[int] = None
    time_based: Optional[int] = None
    ramp_time: Optional[int] = None
    startdelay: Optional[int] = None
    loops: Optional[int] = None
    number_ios: Optional[int] = None

    # Buffering
    direct: Optional[int] = None
    buffered: Optional[int] = None
    invalidate: Optional[int] = 1

    # Sync
    fsync: Optional[int] = None
    fdatasync: Optional[int] = None
    fsync_on_close: Optional[int] = None
    sync_file_range: Optional[str] = None

    # Rate limiting
    rate: Optional[str] = None
    rate_iops: Optional[int] = None
    rate_min: Optional[str] = None
    rate_process: Optional[str] = None

    # Offset
    offset: Optional[str] = None
    offset_increment: Optional[str] = None
    random_distribution: Optional[str] = None

    # CPU / priority
    cpus_allowed: Optional[str] = None
    cpus_allowed_policy: Optional[str] = None
    nice: Optional[int] = None
    prio: Optional[int] = None
    prioclass: Optional[int] = None

    # Memory
    mem: Optional[str] = None
    lockmem: Optional[str] = None
    iomem: Optional[str] = None
    iomem_align: Optional[str] = None

    # Randomness
    norandommap: Optional[int] = None
    randrepeat: Optional[int] = None
    random_generator: Optional[str] = None

    # Verification
    verify: Optional[str] = None
    verify_pattern: Optional[str] = None
    verify_fatal: Optional[int] = None
    verify_dump: Optional[int] = None
    do_verify: Optional[int] = None

    # Logging (per-job log file prefixes)
    write_bw_log: Optional[str] = None
    write_iops_log: Optional[str] = None
    write_lat_log: Optional[str] = None
    write_hist_log: Optional[str] = None
    per_job_logs: Optional[int] = None
    log_compression: Optional[int] = None

    # Job control
    stonewall: Optional[int] = None    # wait for all prior jobs to finish
    new_group: Optional[int] = None
    exitall: Optional[int] = None
    exitall_on_error: Optional[int] = None

    # Engine specific
    ioengine: Optional[str] = None
    sqthread_poll: Optional[int] = None       # io_uring
    sqthread_poll_cpu: Optional[int] = None

    # Hooks
    exec_prerun: Optional[str] = None
    exec_postrun: Optional[str] = None

    class Config:
        extra = "allow"


class FioStepConfig(BaseModel):
    """One FIO test step — one .fio file with global opts + 1..N jobs."""
    global_options: FioGlobalOptions = Field(default_factory=FioGlobalOptions)
    jobs: List[FioJob] = Field(default_factory=lambda: [FioJob()])


# ──────────────────────────── Log Collection ──────────────────────────────

class IostatConfig(BaseModel):
    type: Literal["iostat"] = "iostat"
    devices: List[str] = Field(default_factory=list)   # [] = all
    interval: float = 1.0
    count: Optional[int] = None       # None = run until stopped


class BlktraceConfig(BaseModel):
    type: Literal["blktrace"] = "blktrace"
    devices: List[str]
    duration: Optional[float] = None  # None = run until stopped


class PerfStatConfig(BaseModel):
    type: Literal["perf_stat"] = "perf_stat"
    events: List[str] = Field(default_factory=lambda: ["cycles", "instructions", "cache-misses"])
    pid: Optional[int] = None
    cpu: Optional[str] = None
    duration: Optional[float] = None


class PerfRecordConfig(BaseModel):
    type: Literal["perf_record"] = "perf_record"
    events: List[str] = Field(default_factory=lambda: ["cycles"])
    frequency: int = 99
    pid: Optional[int] = None
    cpu: Optional[str] = None
    duration: Optional[float] = None


class DmesgConfig(BaseModel):
    type: Literal["dmesg"] = "dmesg"
    clear_before: bool = False


class CustomCommandConfig(BaseModel):
    type: Literal["custom"] = "custom"
    command: str
    label: str = "custom"
    timeout: Optional[float] = None
    working_dir: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)


CollectorConfig = Union[
    IostatConfig,
    BlktraceConfig,
    PerfStatConfig,
    PerfRecordConfig,
    DmesgConfig,
    CustomCommandConfig,
]


class LogCollectStepConfig(BaseModel):
    """A step that runs one or more log collectors (possibly concurrently)."""
    collectors: List[CollectorConfig]
    duration: Optional[float] = None   # overall cap; None = run until done/stopped


# ─────────────────────────── Shell Command Step ───────────────────────────

class CommandStepConfig(BaseModel):
    command: str
    label: str = "command"
    timeout: Optional[float] = None
    working_dir: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    fail_on_error: bool = True


# ─────────────────────────────── Flow Graph ───────────────────────────────

StepType = Literal["fio", "log_collect", "command"]


class FlowStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: StepType
    name: str
    config: Union[FioStepConfig, LogCollectStepConfig, CommandStepConfig]
    # Position in the React Flow canvas
    position_x: float = 0.0
    position_y: float = 0.0


class FlowEdge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str   # step id
    target: str   # step id


class Flow(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    steps: List[FlowStep] = Field(default_factory=list)
    edges: List[FlowEdge] = Field(default_factory=list)
    output_dir: str = "./results"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────── Run / Results ───────────────────────────────

class StepStatus(BaseModel):
    step_id: str
    step_name: str
    status: Literal["pending", "running", "done", "error", "skipped"]
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    log_dir: Optional[str] = None
    error: Optional[str] = None


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    flow_id: str
    flow_name: str
    status: Literal["pending", "running", "done", "error", "cancelled"]
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    output_dir: str = ""
    steps: List[StepStatus] = Field(default_factory=list)


# ─────────────────────────── Export Request ───────────────────────────────

class ExportRequest(BaseModel):
    flow: Flow
    format: Literal["bash", "python", "both"] = "both"
    output_dir: str = "./fio_run"


# ──────────────────────────── WebSocket Messages ──────────────────────────

class WsMessage(BaseModel):
    type: Literal["log", "step_start", "step_done", "run_done", "error"]
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    data: Any = None
    ts: datetime = Field(default_factory=datetime.utcnow)
