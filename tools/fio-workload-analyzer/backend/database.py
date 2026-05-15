from datetime import datetime
from typing import Optional
import json

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text,
    DateTime, Boolean, ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from sqlalchemy.pool import StaticPool
import enum

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TestStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TestSession(Base):
    __tablename__ = "test_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, default="")
    status = Column(SAEnum(TestStatus), default=TestStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Target device info (filled after discovery)
    drive_device = Column(String(64), nullable=True)
    drive_model = Column(String(256), nullable=True)
    drive_serial = Column(String(128), nullable=True)
    drive_firmware = Column(String(64), nullable=True)
    drive_capacity_gb = Column(Float, nullable=True)

    # Host info
    host_name = Column(String(256), nullable=True)
    kernel_version = Column(String(256), nullable=True)
    cpu_model = Column(String(256), nullable=True)
    ram_gb = Column(Float, nullable=True)

    error_message = Column(Text, nullable=True)
    tags = Column(String(512), default="")  # comma-separated

    jobs = relationship("FIOJob", back_populates="session", cascade="all, delete-orphan")
    system_logs = relationship("SystemLog", back_populates="session", cascade="all, delete-orphan")
    drive_snapshots = relationship("DriveSnapshot", back_populates="session", cascade="all, delete-orphan")


class FIOJob(Base):
    __tablename__ = "fio_jobs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("test_sessions.id"), nullable=False)
    job_index = Column(Integer, default=0)
    job_name = Column(String(256), nullable=False)

    # Core FIO parameters
    rw = Column(String(32), nullable=False)          # read/write/randread/randwrite/randrw/rw
    bs = Column(String(32), nullable=False)           # 4k, 128k, 1m …
    iodepth = Column(Integer, nullable=False)
    numjobs = Column(Integer, default=1)
    size = Column(String(32), default="100%")
    runtime_s = Column(Integer, nullable=True)
    ramp_time_s = Column(Integer, default=10)
    filename = Column(String(512), nullable=False)
    ioengine = Column(String(32), default="libaio")
    direct = Column(Boolean, default=True)
    sync = Column(Boolean, default=False)
    rwmixread = Column(Integer, default=70)           # for randrw/rw
    time_based = Column(Boolean, default=True)
    fill_device = Column(Boolean, default=False)
    group_reporting = Column(Boolean, default=True)
    rate_iops = Column(Integer, nullable=True)

    # Extra raw INI section passed verbatim
    extra_options = Column(Text, default="")

    # Generated job file path
    job_file_path = Column(String(512), nullable=True)
    raw_output_path = Column(String(512), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(SAEnum(TestStatus), default=TestStatus.PENDING)
    exit_code = Column(Integer, nullable=True)

    session = relationship("TestSession", back_populates="jobs")
    result = relationship("FIOResult", back_populates="job", uselist=False, cascade="all, delete-orphan")
    time_series = relationship("IOTimeSeries", back_populates="job", cascade="all, delete-orphan")


class FIOResult(Base):
    __tablename__ = "fio_results"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("fio_jobs.id"), nullable=False, unique=True)

    # --- Read stats ---
    read_iops = Column(Float, default=0.0)
    read_iops_stddev = Column(Float, default=0.0)
    read_bw_kbps = Column(Float, default=0.0)
    read_bw_stddev = Column(Float, default=0.0)
    read_lat_mean_ns = Column(Float, default=0.0)
    read_lat_stddev_ns = Column(Float, default=0.0)
    read_lat_min_ns = Column(Float, default=0.0)
    read_lat_max_ns = Column(Float, default=0.0)
    read_clat_p50_ns = Column(Float, default=0.0)
    read_clat_p90_ns = Column(Float, default=0.0)
    read_clat_p95_ns = Column(Float, default=0.0)
    read_clat_p99_ns = Column(Float, default=0.0)
    read_clat_p999_ns = Column(Float, default=0.0)
    read_clat_p9999_ns = Column(Float, default=0.0)
    read_total_ios = Column(Integer, default=0)
    read_total_bytes = Column(Integer, default=0)

    # --- Write stats ---
    write_iops = Column(Float, default=0.0)
    write_iops_stddev = Column(Float, default=0.0)
    write_bw_kbps = Column(Float, default=0.0)
    write_bw_stddev = Column(Float, default=0.0)
    write_lat_mean_ns = Column(Float, default=0.0)
    write_lat_stddev_ns = Column(Float, default=0.0)
    write_lat_min_ns = Column(Float, default=0.0)
    write_lat_max_ns = Column(Float, default=0.0)
    write_clat_p50_ns = Column(Float, default=0.0)
    write_clat_p90_ns = Column(Float, default=0.0)
    write_clat_p95_ns = Column(Float, default=0.0)
    write_clat_p99_ns = Column(Float, default=0.0)
    write_clat_p999_ns = Column(Float, default=0.0)
    write_clat_p9999_ns = Column(Float, default=0.0)
    write_total_ios = Column(Integer, default=0)
    write_total_bytes = Column(Integer, default=0)

    # --- CPU / system ---
    cpu_usr = Column(Float, default=0.0)
    cpu_sys = Column(Float, default=0.0)
    ctx_switches = Column(Integer, default=0)
    runtime_ms = Column(Integer, default=0)

    # Full percentile JSON blob
    read_percentiles_json = Column(Text, default="{}")
    write_percentiles_json = Column(Text, default="{}")

    # Raw FIO JSON for future re-parsing
    raw_json = Column(Text, default="{}")

    # Derived ML features
    iops_stability = Column(Float, nullable=True)     # iops_stddev / iops_mean
    lat_tail_ratio = Column(Float, nullable=True)     # p99.9 / p50
    write_amp_est = Column(Float, nullable=True)      # estimated write amplification
    gc_pause_score = Column(Float, nullable=True)     # inferred GC pressure

    job = relationship("FIOJob", back_populates="result")

    @property
    def read_percentiles(self) -> dict:
        return json.loads(self.read_percentiles_json or "{}")

    @property
    def write_percentiles(self) -> dict:
        return json.loads(self.write_percentiles_json or "{}")


class IOTimeSeries(Base):
    """Per-second IOPS / BW / lat from FIO's write_*_log files."""
    __tablename__ = "io_time_series"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("fio_jobs.id"), nullable=False)
    elapsed_ms = Column(Integer, nullable=False)
    iops_read = Column(Float, default=0.0)
    iops_write = Column(Float, default=0.0)
    bw_read_kbps = Column(Float, default=0.0)
    bw_write_kbps = Column(Float, default=0.0)
    lat_read_ns = Column(Float, default=0.0)
    lat_write_ns = Column(Float, default=0.0)

    job = relationship("FIOJob", back_populates="time_series")


class SystemLog(Base):
    """Pre/post test system log snapshots."""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("test_sessions.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("fio_jobs.id"), nullable=True)
    log_type = Column(String(64), nullable=False)    # dmesg, nvme_smart, nvme_log …
    phase = Column(String(16), nullable=False)        # pre / post
    captured_at = Column(DateTime, default=datetime.utcnow)
    content = Column(Text, default="")
    file_path = Column(String(512), nullable=True)

    session = relationship("TestSession", back_populates="system_logs")


class DriveSnapshot(Base):
    """SMART / NVMe telemetry captured before/after each session."""
    __tablename__ = "drive_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("test_sessions.id"), nullable=False)
    phase = Column(String(16), nullable=False)
    captured_at = Column(DateTime, default=datetime.utcnow)
    device = Column(String(64), nullable=False)
    smart_json = Column(Text, default="{}")
    nvme_log_json = Column(Text, default="{}")

    # Parsed key SMART/NVMe fields
    power_on_hours = Column(Integer, nullable=True)
    unsafe_shutdowns = Column(Integer, nullable=True)
    media_errors = Column(Integer, nullable=True)
    data_units_written = Column(Integer, nullable=True)
    data_units_read = Column(Integer, nullable=True)
    available_spare_pct = Column(Float, nullable=True)
    temperature_c = Column(Float, nullable=True)
    percentage_used = Column(Float, nullable=True)

    session = relationship("TestSession", back_populates="drive_snapshots")


class MLModel(Base):
    """Trained ML model registry."""
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(128), nullable=False)
    model_type = Column(String(64), nullable=False)  # isolation_forest, rf_regressor …
    trained_at = Column(DateTime, default=datetime.utcnow)
    n_samples = Column(Integer, default=0)
    metrics_json = Column(Text, default="{}")
    file_path = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)
