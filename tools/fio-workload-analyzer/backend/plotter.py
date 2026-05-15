"""Generate matplotlib plots for FIO results and time-series data."""
import io
import json
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from .config import PLOTS_DIR
from .database import FIOResult, IOTimeSeries

plt.rcParams.update({
    "figure.facecolor": "#1e1e2e",
    "axes.facecolor": "#1e1e2e",
    "axes.edgecolor": "#585b70",
    "axes.labelcolor": "#cdd6f4",
    "xtick.color": "#cdd6f4",
    "ytick.color": "#cdd6f4",
    "text.color": "#cdd6f4",
    "grid.color": "#313244",
    "grid.linestyle": "--",
    "grid.alpha": 0.6,
    "legend.facecolor": "#313244",
    "legend.edgecolor": "#585b70",
    "font.size": 10,
    "axes.titlesize": 12,
    "figure.titlesize": 13,
})

_BLUE  = "#89b4fa"
_GREEN = "#a6e3a1"
_RED   = "#f38ba8"
_YELL  = "#f9e2af"
_MAUVE = "#cba6f7"
_TEAL  = "#94e2d5"


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _save(fig: plt.Figure, name: str) -> Path:
    path = PLOTS_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _to_png_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf.read()


# --------------------------------------------------------------------------- #
#  Individual plots                                                            #
# --------------------------------------------------------------------------- #

def plot_iops_bw_summary(results: list[FIOResult], labels: list[str], name: str) -> Path:
    """Bar chart — IOPS and bandwidth per job."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("IOPS & Bandwidth Summary")

    r_iops  = [r.read_iops  / 1000 for r in results]
    w_iops  = [r.write_iops / 1000 for r in results]
    r_bw    = [r.read_bw_kbps  / 1024 for r in results]
    w_bw    = [r.write_bw_kbps / 1024 for r in results]
    x = np.arange(len(labels))
    w = 0.35

    ax = axes[0]
    ax.bar(x - w/2, r_iops, w, label="Read",  color=_BLUE)
    ax.bar(x + w/2, w_iops, w, label="Write", color=_GREEN)
    ax.set_title("IOPS (K)")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("KIOPS"); ax.legend(); ax.grid(axis="y")

    ax = axes[1]
    ax.bar(x - w/2, r_bw, w, label="Read",  color=_BLUE)
    ax.bar(x + w/2, w_bw, w, label="Write", color=_GREEN)
    ax.set_title("Bandwidth (MiB/s)")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("MiB/s"); ax.legend(); ax.grid(axis="y")

    return _save(fig, name)


def plot_latency_percentiles(results: list[FIOResult], labels: list[str], name: str) -> Path:
    """Grouped bar chart of latency percentiles (µs)."""
    pct_keys  = ["p50", "p90", "p95", "p99", "p999", "p9999"]
    r_fields  = ["read_clat_p50_ns", "read_clat_p90_ns", "read_clat_p95_ns",
                 "read_clat_p99_ns", "read_clat_p999_ns", "read_clat_p9999_ns"]
    w_fields  = ["write_clat_p50_ns","write_clat_p90_ns","write_clat_p95_ns",
                 "write_clat_p99_ns","write_clat_p999_ns","write_clat_p9999_ns"]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle("Completion Latency Percentiles (µs)")
    colors = [_BLUE, _TEAL, _GREEN, _YELL, _RED, _MAUVE]

    for ax, fields, title in [(axes[0], r_fields, "Read"), (axes[1], w_fields, "Write")]:
        x = np.arange(len(pct_keys))
        bar_w = 0.8 / max(len(results), 1)
        for i, (res, label) in enumerate(zip(results, labels)):
            vals = [getattr(res, f) / 1000 for f in fields]  # ns → µs
            ax.bar(x + i * bar_w, vals, bar_w, label=label, alpha=0.85)
        ax.set_title(f"{title} Latency")
        ax.set_xticks(x + bar_w * (len(results)-1)/2)
        ax.set_xticklabels(pct_keys); ax.set_ylabel("µs")
        ax.legend(fontsize=8); ax.grid(axis="y")
        ax.set_yscale("log")

    return _save(fig, name)


def plot_time_series(ts_rows: list[IOTimeSeries], job_name: str, name: str) -> Path:
    """4-panel time-series: Read IOPS, Write IOPS, BW, Latency."""
    if not ts_rows:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No time-series data", ha="center", va="center")
        return _save(fig, name)

    t  = [r.elapsed_ms / 1000 for r in ts_rows]  # seconds
    ri = [r.iops_read    for r in ts_rows]
    wi = [r.iops_write   for r in ts_rows]
    rb = [r.bw_read_kbps / 1024  for r in ts_rows]
    wb = [r.bw_write_kbps/ 1024  for r in ts_rows]
    rl = [r.lat_read_ns  / 1000  for r in ts_rows]  # µs
    wl = [r.lat_write_ns / 1000  for r in ts_rows]

    fig = plt.figure(figsize=(16, 10))
    fig.suptitle(f"Time Series — {job_name}")
    gs = gridspec.GridSpec(2, 2, hspace=0.45, wspace=0.35)

    def _panel(pos, title, ylabel, series):
        ax = fig.add_subplot(pos)
        for label, data, color in series:
            ax.plot(t, data, label=label, color=color, linewidth=1.2)
        ax.set_title(title); ax.set_xlabel("Time (s)")
        ax.set_ylabel(ylabel); ax.legend(); ax.grid()
        return ax

    _panel(gs[0, 0], "Read IOPS",      "IOPS",   [("Read",  ri, _BLUE)])
    _panel(gs[0, 1], "Write IOPS",     "IOPS",   [("Write", wi, _GREEN)])
    _panel(gs[1, 0], "Bandwidth",      "MiB/s",  [("Read",  rb, _BLUE), ("Write", wb, _GREEN)])
    _panel(gs[1, 1], "Latency (mean)", "µs",     [("Read",  rl, _BLUE), ("Write", wl, _GREEN)])

    return _save(fig, name)


def plot_latency_histogram(result: FIOResult, job_name: str, name: str) -> Path:
    """CDF of read & write completion latency using stored percentile blobs."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f"Latency CDF — {job_name}")

    def _cdf_from_percentiles(pct_json: str, ax: plt.Axes, label: str, color: str):
        pcts = json.loads(pct_json or "{}")
        if not pcts:
            ax.text(0.5, 0.5, "No data", ha="center", va="center")
            return
        items = sorted((float(k), v / 1000) for k, v in pcts.items())  # µs
        x = [v for _, v in items]
        y = [k / 100 for k, _ in items]
        ax.plot(x, y, "o-", color=color, linewidth=2, markersize=4, label=label)
        ax.set_xscale("log"); ax.set_xlabel("Latency (µs)")
        ax.set_ylabel("CDF"); ax.set_title(f"{label} Latency CDF")
        ax.grid(True, which="both")

        # Annotate key percentiles
        for pct_pct, pct_label in [(0.50, "P50"), (0.99, "P99"), (0.999, "P99.9")]:
            vals_below = [(lat, p) for p, lat in zip(y, x) if p <= pct_pct]
            if vals_below:
                lat_v = vals_below[-1][0]
                ax.axvline(lat_v, linestyle=":", alpha=0.7, color=_YELL)
                ax.text(lat_v * 1.05, pct_pct - 0.06, pct_label, color=_YELL, fontsize=8)

    _cdf_from_percentiles(result.read_percentiles_json,  axes[0], "Read",  _BLUE)
    _cdf_from_percentiles(result.write_percentiles_json, axes[1], "Write", _GREEN)

    return _save(fig, name)


def plot_qd_sweep(results: list[FIOResult], qd_values: list[int], rw: str, name: str) -> Path:
    """IOPS and latency vs queue depth."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f"Queue Depth Sweep — {rw}")

    iops = [r.read_iops + r.write_iops for r in results]
    lat  = [(r.read_clat_p99_ns or r.write_clat_p99_ns) / 1000 for r in results]

    ax1.plot(qd_values, [i / 1000 for i in iops], "o-", color=_BLUE, linewidth=2)
    ax1.set_xlabel("Queue Depth"); ax1.set_ylabel("KIOPS")
    ax1.set_title("IOPS vs Queue Depth"); ax1.set_xscale("log", base=2); ax1.grid()

    ax2.plot(qd_values, lat, "o-", color=_RED, linewidth=2)
    ax2.set_xlabel("Queue Depth"); ax2.set_ylabel("P99 Latency (µs)")
    ax2.set_title("Latency vs Queue Depth"); ax2.set_xscale("log", base=2); ax2.grid()

    return _save(fig, name)


def plot_bs_sweep(results: list[FIOResult], bs_labels: list[str], name: str) -> Path:
    """Bandwidth and IOPS vs block size."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Block-Size Sweep")

    bw   = [(r.read_bw_kbps + r.write_bw_kbps) / 1024 for r in results]
    iops = [(r.read_iops + r.write_iops) / 1000 for r in results]
    x = np.arange(len(bs_labels))

    ax1.bar(x, bw, color=_TEAL); ax1.set_xticks(x)
    ax1.set_xticklabels(bs_labels, rotation=45, ha="right")
    ax1.set_ylabel("MiB/s"); ax1.set_title("Bandwidth vs Block Size"); ax1.grid(axis="y")

    ax2.bar(x, iops, color=_MAUVE); ax2.set_xticks(x)
    ax2.set_xticklabels(bs_labels, rotation=45, ha="right")
    ax2.set_ylabel("KIOPS"); ax2.set_title("IOPS vs Block Size"); ax2.grid(axis="y")

    return _save(fig, name)


def plot_drive_health_dashboard(snap_pre, snap_post, name: str) -> Path:
    """Visual delta of SMART attributes before vs after."""
    fields = [
        ("data_units_written", "Data Units Written"),
        ("data_units_read",    "Data Units Read"),
        ("power_on_hours",     "Power-On Hours"),
        ("percentage_used",    "% NAND Used"),
        ("available_spare_pct","Available Spare %"),
        ("temperature_c",      "Temperature (°C)"),
        ("media_errors",       "Media Errors"),
        ("unsafe_shutdowns",   "Unsafe Shutdowns"),
    ]
    labels, before_vals, after_vals = [], [], []
    for attr, label in fields:
        b = getattr(snap_pre,  attr, None)
        a = getattr(snap_post, attr, None)
        if b is not None and a is not None:
            labels.append(label)
            before_vals.append(float(b))
            after_vals.append(float(a))

    if not labels:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No SMART data available", ha="center", va="center")
        return _save(fig, name)

    fig, ax = plt.subplots(figsize=(12, max(4, len(labels) * 0.7)))
    fig.suptitle("Drive SMART: Before vs After Test")
    y = np.arange(len(labels))
    ax.barh(y - 0.2, before_vals, 0.35, label="Before", color=_BLUE)
    ax.barh(y + 0.2, after_vals,  0.35, label="After",  color=_GREEN)
    ax.set_yticks(y); ax.set_yticklabels(labels)
    ax.legend(); ax.grid(axis="x")
    return _save(fig, name)


# --------------------------------------------------------------------------- #
#  Session-level overview (multi-plot composite)                               #
# --------------------------------------------------------------------------- #

def generate_session_plots(
    session_id: int,
    results_with_jobs: list[tuple],  # [(FIOJob, FIOResult)]
    ts_map: dict,                     # job_id → [IOTimeSeries]
) -> dict[str, str]:
    """Generate all relevant plots for a session and return {name: path}."""
    paths = {}

    if not results_with_jobs:
        return paths

    jobs_list    = [j for j, r in results_with_jobs if r]
    results_list = [r for j, r in results_with_jobs if r]
    labels       = [f"{j.rw} bs={j.bs} qd={j.iodepth}" for j in jobs_list]

    # Overall IOPS/BW summary
    p = plot_iops_bw_summary(results_list, labels, f"session_{session_id}_iops_bw")
    paths["iops_bw"] = str(p)

    # Latency percentiles
    p = plot_latency_percentiles(results_list, labels, f"session_{session_id}_latency_pct")
    paths["latency_pct"] = str(p)

    # Per-job time-series
    for job, result in results_with_jobs:
        if result and job.id in ts_map and ts_map[job.id]:
            p = plot_time_series(
                ts_map[job.id],
                f"{job.rw} bs={job.bs} qd={job.iodepth}",
                f"session_{session_id}_job_{job.id}_ts",
            )
            paths[f"ts_job_{job.id}"] = str(p)

        if result:
            p = plot_latency_histogram(
                result,
                f"{job.rw} bs={job.bs} qd={job.iodepth}",
                f"session_{session_id}_job_{job.id}_cdf",
            )
            paths[f"cdf_job_{job.id}"] = str(p)

    # QD sweep if applicable
    qd_jobs = [(j, r) for j, r in results_with_jobs
               if r and j.rw in ("randread","randwrite","read","write") and j.bs == jobs_list[0].bs]
    if len(qd_jobs) > 2:
        p = plot_qd_sweep(
            [r for _, r in qd_jobs],
            [j.iodepth for j, _ in qd_jobs],
            jobs_list[0].rw,
            f"session_{session_id}_qd_sweep",
        )
        paths["qd_sweep"] = str(p)

    # BS sweep if applicable
    bs_jobs = [(j, r) for j, r in results_with_jobs
               if r and j.rw == jobs_list[0].rw and j.iodepth == jobs_list[0].iodepth]
    if len({j.bs for j, _ in bs_jobs}) > 3:
        p = plot_bs_sweep(
            [r for _, r in bs_jobs],
            [j.bs for j, _ in bs_jobs],
            f"session_{session_id}_bs_sweep",
        )
        paths["bs_sweep"] = str(p)

    return paths
