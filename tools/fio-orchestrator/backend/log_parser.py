"""Parse FIO JSON output and time-series log files."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────── FIO JSON output ──────────────────────────────

def parse_fio_json(path: str) -> Optional[Dict]:
    """Return parsed FIO JSON dict or None if file is missing/invalid."""
    try:
        with open(path) as f:
            raw = f.read().strip()
        # FIO sometimes emits multiple JSON objects — keep the last one
        # (happens when multiple job groups are present)
        chunks = re.split(r"\n(?=\{)", raw)
        return json.loads(chunks[-1])
    except Exception:
        return None


def summarise_fio_result(data: Dict) -> List[Dict]:
    """Extract per-job summary rows from a parsed FIO JSON."""
    rows = []
    for job in data.get("jobs", []):
        row: Dict[str, Any] = {
            "job_name": job.get("jobname", "?"),
            "error": job.get("error", 0),
        }
        for direction in ("read", "write", "trim"):
            d = job.get(direction, {})
            if not d or d.get("io_bytes", 0) == 0:
                continue
            lat = d.get("lat_ns", {})
            clat = d.get("clat_ns", {})
            pct = clat.get("percentile", {})
            row[direction] = {
                "io_bytes":   d.get("io_bytes", 0),
                "io_kbytes":  d.get("io_kbytes", 0),
                "bw_kbps":    d.get("bw", 0),
                "bw_mbps":    round(d.get("bw", 0) / 1024, 2),
                "iops":       round(d.get("iops", 0), 1),
                "runtime_ms": d.get("runtime", 0),
                "lat_min_us": round(lat.get("min", 0) / 1000, 3),
                "lat_max_us": round(lat.get("max", 0) / 1000, 3),
                "lat_mean_us": round(lat.get("mean", 0) / 1000, 3),
                "lat_stddev_us": round(lat.get("stddev", 0) / 1000, 3),
                "clat_p50_us":   round(float(pct.get("50.000000", 0)) / 1000, 3),
                "clat_p99_us":   round(float(pct.get("99.000000", 0)) / 1000, 3),
                "clat_p999_us":  round(float(pct.get("99.900000", 0)) / 1000, 3),
                "clat_p9999_us": round(float(pct.get("99.990000", 0)) / 1000, 3),
            }
        rows.append(row)
    return rows


def extract_disk_util(data: Dict) -> List[Dict]:
    """Extract disk utilisation from FIO JSON."""
    return data.get("disk_util", [])


# ───────────────────── FIO time-series log files ──────────────────────────
# FIO bw/iops/lat logs are CSV: time_ms, value, direction (0=read,1=write,2=trim), bs

def parse_fio_log(path: str) -> List[Dict]:
    """Parse a FIO bw/iops/lat log file into a list of dicts."""
    records = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) < 3:
                    continue
                try:
                    records.append({
                        "time_ms":  int(parts[0].strip()),
                        "value":    float(parts[1].strip()),
                        "dir":      int(parts[2].strip()),   # 0=read,1=write,2=trim
                        "bs":       int(parts[3].strip()) if len(parts) > 3 else 0,
                    })
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return records


def collect_timeseries(log_dir: str) -> Dict[str, List[Dict]]:
    """Scan a step log_dir and return all time-series data keyed by filename."""
    result: Dict[str, List[Dict]] = {}
    p = Path(log_dir)
    if not p.exists():
        return result
    for f in sorted(p.glob("*.log")):
        # Detect bw/iops/lat/clat from filename suffix
        name = f.stem  # e.g.  "4k_randread_bw.1"
        records = parse_fio_log(str(f))
        if records:
            result[name] = records
    return result


# ─────────────────────────── iostat parser ────────────────────────────────

def parse_iostat(path: str) -> List[Dict]:
    """Very basic iostat -x output parser."""
    snapshots: List[Dict] = []
    if not os.path.exists(path):
        return snapshots
    with open(path) as f:
        text = f.read()
    blocks = re.split(r"\n(?=Linux|\d{2}/|\d{4}-)", text)
    for block in blocks:
        lines = block.strip().splitlines()
        header_idx = next((i for i, l in enumerate(lines) if "Device" in l), None)
        if header_idx is None:
            continue
        headers = lines[header_idx].split()
        for line in lines[header_idx + 1:]:
            parts = line.split()
            if not parts:
                continue
            entry = dict(zip(headers, parts))
            if entry:
                snapshots.append(entry)
    return snapshots


# ───────────────────────── Step result summary ────────────────────────────

def build_step_summary(log_dir: str) -> Dict:
    """Return a machine-parseable summary dict for a completed step."""
    summary: Dict[str, Any] = {"log_dir": log_dir}

    fio_json_path = os.path.join(log_dir, "fio_output.json")
    if os.path.exists(fio_json_path):
        fio_data = parse_fio_json(fio_json_path)
        if fio_data:
            summary["fio_jobs"] = summarise_fio_result(fio_data)
            summary["fio_disk_util"] = extract_disk_util(fio_data)
            summary["fio_raw"] = fio_data

    iostat_path = os.path.join(log_dir, "iostat.log")
    if os.path.exists(iostat_path):
        summary["iostat"] = parse_iostat(iostat_path)

    summary["timeseries"] = collect_timeseries(log_dir)

    return summary
