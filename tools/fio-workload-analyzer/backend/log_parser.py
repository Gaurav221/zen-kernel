"""Parse FIO JSON+ output into FIOResult ORM objects."""
import json
import math
from pathlib import Path
from typing import Optional

from .config import FIO_PERCENTILES
from .database import FIOResult


_PMAP = {
    "50.000000":  "p50",
    "90.000000":  "p90",
    "95.000000":  "p95",
    "99.000000":  "p99",
    "99.900000":  "p999",
    "99.990000":  "p9999",
}


def _pct(clat: dict, key: str) -> float:
    """Extract a percentile value from FIO clat_ns.percentile dict."""
    return float(clat.get("percentile", {}).get(key, 0.0))


def _safe(val, default=0.0):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return val


def parse_fio_json(raw_json: str, job_id: int) -> Optional[FIOResult]:
    """
    Parse FIO JSON+ output for a single job and return an unsaved FIOResult.

    FIO JSON+ contains one entry in the 'jobs' array per job; when
    group_reporting=1 all numjobs are merged into index 0.
    """
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    jobs = data.get("jobs", [])
    if not jobs:
        return None

    jd = jobs[0]

    def _section(key: str) -> dict:
        return jd.get(key, {})

    rd = _section("read")
    wr = _section("write")

    def _clat_pct(section: dict, pkey: str) -> float:
        return _pct(section.get("clat_ns", {}), pkey)

    result = FIOResult(
        job_id=job_id,
        raw_json=raw_json,

        # --- Read ---
        read_iops         = _safe(rd.get("iops", 0.0)),
        read_iops_stddev  = _safe(rd.get("iops_stddev", 0.0)),
        read_bw_kbps      = _safe(rd.get("bw", 0.0)),
        read_bw_stddev    = _safe(rd.get("bw_dev", 0.0)),
        read_lat_mean_ns  = _safe(rd.get("lat_ns", {}).get("mean", 0.0)),
        read_lat_stddev_ns= _safe(rd.get("lat_ns", {}).get("stddev", 0.0)),
        read_lat_min_ns   = _safe(rd.get("lat_ns", {}).get("min", 0.0)),
        read_lat_max_ns   = _safe(rd.get("lat_ns", {}).get("max", 0.0)),
        read_clat_p50_ns  = _clat_pct(rd, "50.000000"),
        read_clat_p90_ns  = _clat_pct(rd, "90.000000"),
        read_clat_p95_ns  = _clat_pct(rd, "95.000000"),
        read_clat_p99_ns  = _clat_pct(rd, "99.000000"),
        read_clat_p999_ns = _clat_pct(rd, "99.900000"),
        read_clat_p9999_ns= _clat_pct(rd, "99.990000"),
        read_total_ios    = int(_safe(rd.get("total_ios", 0), 0)),
        read_total_bytes  = int(_safe(rd.get("io_bytes", 0), 0)),

        # --- Write ---
        write_iops         = _safe(wr.get("iops", 0.0)),
        write_iops_stddev  = _safe(wr.get("iops_stddev", 0.0)),
        write_bw_kbps      = _safe(wr.get("bw", 0.0)),
        write_bw_stddev    = _safe(wr.get("bw_dev", 0.0)),
        write_lat_mean_ns  = _safe(wr.get("lat_ns", {}).get("mean", 0.0)),
        write_lat_stddev_ns= _safe(wr.get("lat_ns", {}).get("stddev", 0.0)),
        write_lat_min_ns   = _safe(wr.get("lat_ns", {}).get("min", 0.0)),
        write_lat_max_ns   = _safe(wr.get("lat_ns", {}).get("max", 0.0)),
        write_clat_p50_ns  = _clat_pct(wr, "50.000000"),
        write_clat_p90_ns  = _clat_pct(wr, "90.000000"),
        write_clat_p95_ns  = _clat_pct(wr, "95.000000"),
        write_clat_p99_ns  = _clat_pct(wr, "99.000000"),
        write_clat_p999_ns = _clat_pct(wr, "99.900000"),
        write_clat_p9999_ns= _clat_pct(wr, "99.990000"),
        write_total_ios    = int(_safe(wr.get("total_ios", 0), 0)),
        write_total_bytes  = int(_safe(wr.get("io_bytes", 0), 0)),

        # --- CPU / system ---
        cpu_usr      = _safe(jd.get("usr_cpu", 0.0)),
        cpu_sys      = _safe(jd.get("sys_cpu", 0.0)),
        ctx_switches = int(_safe(jd.get("ctx", 0), 0)),
        runtime_ms   = int(_safe(jd.get("job options", {}).get("runtime", 0), 0)) * 1000,

        # Full percentile blobs
        read_percentiles_json  = json.dumps(
            rd.get("clat_ns", {}).get("percentile", {})
        ),
        write_percentiles_json = json.dumps(
            wr.get("clat_ns", {}).get("percentile", {})
        ),
    )

    # --- Derived ML features ---
    result.iops_stability = _compute_stability(
        result.read_iops + result.write_iops,
        result.read_iops_stddev + result.write_iops_stddev,
    )
    result.lat_tail_ratio = _compute_tail_ratio(
        result.read_clat_p999_ns or result.write_clat_p999_ns,
        result.read_clat_p50_ns or result.write_clat_p50_ns,
    )
    result.write_amp_est = _estimate_write_amp(result)
    result.gc_pause_score = _estimate_gc_pressure(result)

    return result


def _compute_stability(total_iops: float, total_stddev: float) -> Optional[float]:
    if total_iops > 0:
        return min(total_stddev / total_iops, 10.0)
    return None


def _compute_tail_ratio(p999: float, p50: float) -> Optional[float]:
    if p50 > 0:
        return min(p999 / p50, 1000.0)
    return None


def _estimate_write_amp(r: FIOResult) -> Optional[float]:
    """
    Rough heuristic: if the device is being written to and BW stddev is
    disproportionately high, that suggests GC-induced WA > 1.
    This is a placeholder — real WA requires SMART counters.
    """
    if r.write_bw_kbps > 0 and r.write_bw_stddev > 0:
        cv = r.write_bw_stddev / r.write_bw_kbps
        # Translate BW coefficient-of-variation into a rough WA estimate
        return round(1.0 + cv * 2, 2)
    return None


def _estimate_gc_pressure(r: FIOResult) -> Optional[float]:
    """
    GC pressure score [0–1] inferred from:
    - write latency tail-ratio
    - write IOPS stability
    """
    score = 0.0
    count = 0
    if r.lat_tail_ratio is not None:
        # Normalize: tail ratio of 1 → 0, >100 → 1
        score += min(r.lat_tail_ratio / 100.0, 1.0)
        count += 1
    if r.iops_stability is not None:
        score += min(r.iops_stability, 1.0)
        count += 1
    return round(score / count, 3) if count > 0 else None


def parse_fio_output_file(path: Path, job_id: int) -> Optional[FIOResult]:
    """Convenience wrapper: read file then parse."""
    if not path.exists():
        return None
    return parse_fio_json(path.read_text(), job_id)
