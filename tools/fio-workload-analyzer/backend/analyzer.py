"""Statistical analysis of FIO results across sessions and jobs."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from .database import FIOResult, IOTimeSeries, TestSession


# --------------------------------------------------------------------------- #
#  Single-result metrics                                                       #
# --------------------------------------------------------------------------- #

def compute_derived_metrics(result: FIOResult) -> dict:
    """Return a flat dict of computed metrics for display / ML."""
    total_iops = result.read_iops + result.write_iops
    total_bw   = (result.read_bw_kbps + result.write_bw_kbps) / 1024  # MiB/s

    read_p99  = result.read_clat_p99_ns  / 1000  # µs
    write_p99 = result.write_clat_p99_ns / 1000

    return {
        "total_iops":        round(total_iops, 1),
        "total_bw_mbps":     round(total_bw, 2),
        "read_iops":         round(result.read_iops, 1),
        "write_iops":        round(result.write_iops, 1),
        "read_bw_mbps":      round(result.read_bw_kbps / 1024, 2),
        "write_bw_mbps":     round(result.write_bw_kbps / 1024, 2),
        "read_lat_mean_us":  round(result.read_lat_mean_ns / 1000, 2),
        "write_lat_mean_us": round(result.write_lat_mean_ns / 1000, 2),
        "read_p50_us":       round(result.read_clat_p50_ns  / 1000, 2),
        "read_p99_us":       round(read_p99, 2),
        "read_p999_us":      round(result.read_clat_p999_ns / 1000, 2),
        "write_p50_us":      round(result.write_clat_p50_ns  / 1000, 2),
        "write_p99_us":      round(write_p99, 2),
        "write_p999_us":     round(result.write_clat_p999_ns / 1000, 2),
        "cpu_usr":           round(result.cpu_usr, 2),
        "cpu_sys":           round(result.cpu_sys, 2),
        "iops_stability":    round(result.iops_stability or 0, 4),
        "lat_tail_ratio":    round(result.lat_tail_ratio or 0, 2),
        "write_amp_est":     round(result.write_amp_est or 1.0, 2),
        "gc_pause_score":    round(result.gc_pause_score or 0, 3),
    }


# --------------------------------------------------------------------------- #
#  Time-series analysis                                                        #
# --------------------------------------------------------------------------- #

def analyze_time_series(rows: list[IOTimeSeries]) -> dict:
    """Compute stability, trend, and anomaly stats from time-series rows."""
    if not rows:
        return {}

    df = pd.DataFrame([{
        "t":   r.elapsed_ms / 1000,
        "ri":  r.iops_read,
        "wi":  r.iops_write,
        "rb":  r.bw_read_kbps,
        "wb":  r.bw_write_kbps,
        "rl":  r.lat_read_ns / 1000,   # µs
        "wl":  r.lat_write_ns / 1000,
    } for r in rows])

    out = {}

    for col, label in [("ri", "read_iops"), ("wi", "write_iops"),
                       ("rl", "read_lat_us"), ("wl", "write_lat_us")]:
        series = df[col].dropna()
        if len(series) < 2:
            continue
        out[f"{label}_mean"]   = float(series.mean())
        out[f"{label}_stddev"] = float(series.std())
        out[f"{label}_cv"]     = float(series.std() / series.mean()) if series.mean() > 0 else 0.0
        out[f"{label}_min"]    = float(series.min())
        out[f"{label}_max"]    = float(series.max())
        out[f"{label}_p95"]    = float(np.percentile(series, 95))

        # Linear trend (slope > 0 → degrading, < 0 → improving)
        slope, _, r_val, _, _ = stats.linregress(df["t"], series)
        out[f"{label}_trend_slope"] = float(slope)
        out[f"{label}_trend_r2"]    = float(r_val ** 2)

    # Latency spike detection: points > 3 sigma above mean
    for col, label in [("rl", "read"), ("wl", "write")]:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        z_scores = np.abs(stats.zscore(series))
        n_spikes = int((z_scores > 3).sum())
        out[f"{label}_lat_spikes"] = n_spikes
        out[f"{label}_spike_rate"] = round(n_spikes / len(series), 4)

    return out


# --------------------------------------------------------------------------- #
#  Cross-session comparison                                                    #
# --------------------------------------------------------------------------- #

def compare_sessions(sessions_results: list[dict]) -> dict:
    """
    sessions_results: list of {"session": TestSession, "metrics": dict}
    Returns comparison table data.
    """
    if not sessions_results:
        return {}

    key_metrics = [
        "total_iops", "total_bw_mbps", "read_p99_us", "write_p99_us",
        "write_amp_est", "gc_pause_score",
    ]
    rows = []
    for sr in sessions_results:
        row = {
            "session_id":   sr["session"].id,
            "session_name": sr["session"].name,
            "drive":        sr["session"].drive_model or "?",
        }
        row.update({k: sr["metrics"].get(k) for k in key_metrics})
        rows.append(row)

    df = pd.DataFrame(rows)

    # Rank sessions by total_iops (descending)
    if "total_iops" in df.columns:
        df["iops_rank"] = df["total_iops"].rank(ascending=False).astype(int)

    return {
        "table": df.to_dict(orient="records"),
        "best_iops":    int(df["session_id"].iloc[df["total_iops"].idxmax()]) if "total_iops" in df.columns else None,
        "best_latency": int(df["session_id"].iloc[df["read_p99_us"].idxmin()]) if "read_p99_us" in df.columns else None,
    }


# --------------------------------------------------------------------------- #
#  Performance degradation detection                                           #
# --------------------------------------------------------------------------- #

def detect_performance_cliff(ts_rows: list[IOTimeSeries]) -> dict:
    """
    Detect sudden IOPS drop (write cliff / GC event) in a time series.
    Returns detected cliff times and magnitudes.
    """
    if len(ts_rows) < 10:
        return {"detected": False}

    iops = np.array([r.iops_read + r.iops_write for r in ts_rows])
    times_s = np.array([r.elapsed_ms / 1000 for r in ts_rows])

    # Sliding window std — a spike in variance signals a cliff
    window = max(5, len(iops) // 20)
    rolling_mean = pd.Series(iops).rolling(window).mean().dropna().values
    rolling_std  = pd.Series(iops).rolling(window).std().dropna().values

    cliffs = []
    for i in range(1, len(rolling_mean)):
        drop = rolling_mean[i - 1] - rolling_mean[i]
        if rolling_mean[i - 1] > 0:
            drop_pct = drop / rolling_mean[i - 1]
            if drop_pct > 0.20:  # >20% drop in rolling mean
                cliffs.append({
                    "time_s": float(times_s[i + window - 1]),
                    "drop_pct": round(drop_pct * 100, 1),
                    "before_iops": round(float(rolling_mean[i - 1]), 0),
                    "after_iops":  round(float(rolling_mean[i]), 0),
                })

    return {
        "detected":  len(cliffs) > 0,
        "n_cliffs":  len(cliffs),
        "cliffs":    cliffs[:10],  # top 10
    }


# --------------------------------------------------------------------------- #
#  Feature vector for ML                                                       #
# --------------------------------------------------------------------------- #

def build_ml_feature_vector(
    result: FIOResult,
    ts_rows: list[IOTimeSeries],
    job_bs: str,
    job_qd: int,
    job_rw: str,
) -> dict:
    """
    Build a flat feature dict suitable for ML training / inference.
    Includes performance metrics + time-series stats.
    """
    base = compute_derived_metrics(result)
    ts_stats = analyze_time_series(ts_rows) if ts_rows else {}
    cliff = detect_performance_cliff(ts_rows) if ts_rows else {}

    # Encode workload parameters
    rw_map = {"read": 0, "write": 1, "randread": 2, "randwrite": 3, "randrw": 4, "rw": 5}
    bs_bytes = _parse_bs(job_bs)

    features = {
        **base,
        **ts_stats,
        "bs_bytes":          bs_bytes,
        "log2_bs":           math.log2(bs_bytes) if bs_bytes > 0 else 0,
        "queue_depth":       job_qd,
        "log2_qd":           math.log2(job_qd) if job_qd > 0 else 0,
        "rw_encoded":        rw_map.get(job_rw, -1),
        "n_perf_cliffs":     cliff.get("n_cliffs", 0),
    }
    return features


def _parse_bs(bs: str) -> int:
    """Convert block size string to bytes."""
    bs = bs.lower().strip()
    multipliers = {"k": 1024, "m": 1024**2, "g": 1024**3}
    for suffix, mult in multipliers.items():
        if bs.endswith(suffix):
            try:
                return int(bs[:-1]) * mult
            except ValueError:
                return 0
    try:
        return int(bs)
    except ValueError:
        return 0
