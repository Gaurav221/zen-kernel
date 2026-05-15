from pathlib import Path
import os

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
RESULTS_DIR = DATA_DIR / "results"
EXPORTS_DIR = DATA_DIR / "exports"
PLOTS_DIR = DATA_DIR / "plots"
FIO_JOBS_DIR = DATA_DIR / "fio_jobs"
MODELS_DIR = DATA_DIR / "models"

for _d in [DATA_DIR, LOGS_DIR, RESULTS_DIR, EXPORTS_DIR, PLOTS_DIR, FIO_JOBS_DIR, MODELS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/fio_analyzer.db"

FIO_BINARY = os.environ.get("FIO_BINARY", "fio")

# Log capture configuration — user will populate capture commands here
LOG_CAPTURE_COMMANDS: dict[str, list[str]] = {
    "dmesg": ["dmesg", "--time-format=iso", "-T"],
    "kernel_messages": ["journalctl", "-k", "--no-pager", "-n", "2000"],
    "nvme_smart": [],   # populated by drive discovery
    "nvme_log": [],     # populated by drive discovery
    "blktrace_summary": [],  # optional; set FIO_BLKTRACE=1 to enable
}

# How many lines of context to keep around log deltas
LOG_CONTEXT_LINES = 50

# Percentile keys used in FIO JSON output
FIO_PERCENTILES = [
    "1.000000", "5.000000", "10.000000", "20.000000", "30.000000",
    "40.000000", "50.000000", "60.000000", "70.000000", "80.000000",
    "90.000000", "95.000000", "99.000000", "99.500000", "99.900000",
    "99.950000", "99.990000",
]

CORS_ORIGINS = ["*"]
