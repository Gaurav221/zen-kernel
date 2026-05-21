"""
Parses FIO JSON output into a clean, structured dict.

The canonical output schema (written to fio_analysis.json):
{
  "fio_version": "fio-3.33",
  "timestamp": "2024-01-15T14:30:00",
  "step_name": "<set by executor>",
  "step_index": 0,
  "jobs": [
    {
      "jobname": "...",
      "read": {
        "iops":       12345.0,
        "bw_KiB_s":  98765,
        "bw_MiB_s":  96.4,
        "lat_ns": { "min":…, "max":…, "mean":…, "stddev":… },
        "clat_percentiles_us": {
          "p50": …, "p90": …, "p95": …,
          "p99": …, "p99_9": …, "p99_99": …
        },
        "iops_min": …, "iops_max": …, "iops_mean": …, "iops_stddev": …,
        "bw_min_KiB_s": …, "bw_max_KiB_s": …
      },
      "write": { … same … },
      "usr_cpu": …,
      "sys_cpu": …,
      "job_options": { … }
    }
  ],
  "disk_util": [ { "name": …, "util": … } ],
  "summary": {
    "total_read_iops": …,   "total_write_iops": …,
    "total_read_bw_MiB_s": …, "total_write_bw_MiB_s": …,
    "p99_read_lat_us": …,   "p99_write_lat_us": …,
    "p99_9_read_lat_us": …, "p99_9_write_lat_us": …,
  }
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


# FIO latency percentile keys in the JSON → our label
_PCTILE_MAP = {
    "50.000000":  "p50",
    "90.000000":  "p90",
    "95.000000":  "p95",
    "99.000000":  "p99",
    "99.500000":  "p99_5",
    "99.900000":  "p99_9",
    "99.950000":  "p99_95",
    "99.990000":  "p99_99",
}


def _parse_rw_section(rw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a single read/write section from a FIO job."""
    out: Dict[str, Any] = {}

    out["iops"] = float(rw_data.get("iops", 0))
    out["iops_min"] = rw_data.get("iops_min", 0)
    out["iops_max"] = rw_data.get("iops_max", 0)
    out["iops_mean"] = float(rw_data.get("iops_mean", 0))
    out["iops_stddev"] = float(rw_data.get("iops_stddev", 0))

    bw_kib = rw_data.get("bw", 0)           # KiB/s
    out["bw_KiB_s"] = bw_kib
    out["bw_MiB_s"] = round(bw_kib / 1024, 2)
    out["bw_min_KiB_s"] = rw_data.get("bw_min", 0)
    out["bw_max_KiB_s"] = rw_data.get("bw_max", 0)
    out["bw_mean_KiB_s"] = float(rw_data.get("bw_mean", 0))

    # Total IO
    out["io_kbytes"] = rw_data.get("io_kbytes", 0)
    out["io_GiB"] = round(rw_data.get("io_bytes", 0) / (1024 ** 3), 3)

    # Completion latency (most useful for end-to-end)
    for lat_key in ("clat_ns", "lat_ns"):
        lat = rw_data.get(lat_key, {})
        if lat:
            out["lat_ns"] = {
                "min":    lat.get("min", 0),
                "max":    lat.get("max", 0),
                "mean":   float(lat.get("mean", 0)),
                "stddev": float(lat.get("stddev", 0)),
            }
            # Percentiles (stored in ns by FIO)
            pctiles_ns = lat.get("percentile", {})
            pctiles_us: Dict[str, float] = {}
            for fio_key, label in _PCTILE_MAP.items():
                if fio_key in pctiles_ns:
                    pctiles_us[label] = round(pctiles_ns[fio_key] / 1000, 1)
            out["clat_percentiles_us"] = pctiles_us
            break

    return out


def _parse_job(job: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "jobname":     job.get("jobname", "unknown"),
        "groupid":     job.get("groupid", 0),
        "error":       job.get("error", 0),
        "usr_cpu":     job.get("usr_cpu", 0.0),
        "sys_cpu":     job.get("sys_cpu", 0.0),
        "job_options": job.get("job options", {}),
    }

    for direction in ("read", "write", "trim"):
        section = job.get(direction, {})
        if section.get("io_bytes", 0) > 0 or section.get("iops", 0) > 0:
            out[direction] = _parse_rw_section(section)
        else:
            out[direction] = None

    return out


def _build_summary(jobs: list) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total_read_iops":       0.0,
        "total_write_iops":      0.0,
        "total_read_bw_MiB_s":  0.0,
        "total_write_bw_MiB_s": 0.0,
        "p99_read_lat_us":       None,
        "p99_write_lat_us":      None,
        "p99_9_read_lat_us":     None,
        "p99_9_write_lat_us":    None,
    }

    for job in jobs:
        for direction, key_iops, key_bw, key_p99, key_p99_9 in [
            ("read",  "total_read_iops",  "total_read_bw_MiB_s",  "p99_read_lat_us",  "p99_9_read_lat_us"),
            ("write", "total_write_iops", "total_write_bw_MiB_s", "p99_write_lat_us", "p99_9_write_lat_us"),
        ]:
            d = job.get(direction)
            if d:
                summary[key_iops] += d.get("iops", 0)
                summary[key_bw]   += d.get("bw_MiB_s", 0)
                pctiles = d.get("clat_percentiles_us", {})
                if pctiles.get("p99"):
                    summary[key_p99] = pctiles["p99"]
                if pctiles.get("p99_9"):
                    summary[key_p99_9] = pctiles["p99_9"]

    # Round floats
    for k in ("total_read_iops", "total_write_iops"):
        summary[k] = round(summary[k], 1)
    for k in ("total_read_bw_MiB_s", "total_write_bw_MiB_s"):
        summary[k] = round(summary[k], 2)

    return summary


def parse_fio_json(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load and parse a FIO JSON output file.
    Returns the structured analysis dict.
    """
    raw_text = Path(path).read_text()

    # FIO sometimes prepends text before the JSON object; find the JSON start
    json_start = raw_text.find("{")
    if json_start == -1:
        raise ValueError("No JSON object found in FIO output")
    raw_text = raw_text[json_start:]

    data = json.loads(raw_text)

    ts_epoch = data.get("timestamp", 0)
    ts_str = datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat() if ts_epoch else ""

    jobs = [_parse_job(j) for j in data.get("jobs", [])]

    disk_util = [
        {
            "name":       d.get("name", ""),
            "util":       d.get("util", 0.0),
            "read_ios":   d.get("read_ios", 0),
            "write_ios":  d.get("write_ios", 0),
        }
        for d in data.get("disk_util", [])
    ]

    return {
        "fio_version":   data.get("fio version", "unknown"),
        "timestamp":     ts_str,
        "global_options": data.get("global options", {}),
        "jobs":          jobs,
        "disk_util":     disk_util,
        "summary":       _build_summary(jobs),
        # These are set by executor after the fact:
        "step_name":     "",
        "step_index":    0,
    }
