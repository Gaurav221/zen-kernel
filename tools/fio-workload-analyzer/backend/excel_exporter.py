"""
Generate multi-sheet Excel workbook with embedded charts.
Sheets: Summary | Read | Write | Latency Percentiles | Time Series | System Logs | Drive Info | Raw Data
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.styles import (Alignment, Border, Font, GradientFill,
                              PatternFill, Side)
from openpyxl.utils import get_column_letter

from .config import EXPORTS_DIR
from .database import DriveSnapshot, FIOJob, FIOResult, IOTimeSeries, SystemLog, TestSession
from .analyzer import compute_derived_metrics, analyze_time_series

# ── Palette ──────────────────────────────────────────────────────────────────
_HDR_FILL   = PatternFill("solid", fgColor="1E1E2E")
_HDR_FONT   = Font(bold=True, color="CDD6F4", size=10)
_ALT_FILL_A = PatternFill("solid", fgColor="181825")
_ALT_FILL_B = PatternFill("solid", fgColor="11111B")
_BORDER     = Border(
    left=Side(style="thin", color="313244"),
    right=Side(style="thin", color="313244"),
    top=Side(style="thin", color="313244"),
    bottom=Side(style="thin", color="313244"),
)
_TITLE_FONT = Font(bold=True, color="89B4FA", size=13)
_GOOD_FILL  = PatternFill("solid", fgColor="1E4429")  # green
_WARN_FILL  = PatternFill("solid", fgColor="4A3000")  # yellow
_BAD_FILL   = PatternFill("solid", fgColor="4A0010")  # red


def _header_row(ws, cols: list[str], row: int = 1):
    for ci, col in enumerate(cols, start=1):
        cell = ws.cell(row=row, column=ci, value=col)
        cell.fill = _HDR_FILL
        cell.font = _HDR_FONT
        cell.alignment = Alignment(horizontal="center")
        cell.border = _BORDER
    ws.row_dimensions[row].height = 20


def _data_row(ws, values: list, row: int, alt: bool = False):
    fill = _ALT_FILL_A if alt else _ALT_FILL_B
    for ci, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=ci, value=v)
        cell.fill = fill
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="right" if isinstance(v, (int, float)) else "left")


def _auto_width(ws):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                max_len = max(max_len, len(str(cell.value or "")))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 3, 40)


def _write_title(ws, title: str, row: int = 1):
    ws.cell(row=row, column=1, value=title).font = _TITLE_FONT


def _ns_to_us(v: Optional[float]) -> Optional[float]:
    return round(v / 1000, 2) if v else None

def _kbps_to_mbps(v: Optional[float]) -> Optional[float]:
    return round(v / 1024, 2) if v else None


# --------------------------------------------------------------------------- #
#  Per-sheet writers                                                           #
# --------------------------------------------------------------------------- #

def _sheet_summary(wb: Workbook, session: TestSession, jobs: list[FIOJob], results: list[FIOResult]):
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False

    _write_title(ws, f"FIO Test Report — {session.name}", row=1)
    ws.row_dimensions[1].height = 28

    meta = [
        ("Session ID",    session.id),
        ("Status",        session.status),
        ("Created",       session.created_at.strftime("%Y-%m-%d %H:%M:%S") if session.created_at else ""),
        ("Drive Device",  session.drive_device or ""),
        ("Drive Model",   session.drive_model or ""),
        ("Drive Serial",  session.drive_serial or ""),
        ("Firmware",      session.drive_firmware or ""),
        ("Host",          session.host_name or ""),
        ("Kernel",        session.kernel_version or ""),
        ("CPU",           session.cpu_model or ""),
        ("RAM (GB)",      session.ram_gb or ""),
        ("Description",   session.description or ""),
    ]
    for ri, (k, v) in enumerate(meta, start=3):
        ws.cell(row=ri, column=1, value=k).font = _HDR_FONT
        ws.cell(row=ri, column=1).fill = _HDR_FILL
        ws.cell(row=ri, column=2, value=v)

    # Results table
    r_start = 3 + len(meta) + 2
    _write_title(ws, "Job Results Overview", row=r_start - 1)

    cols = ["Job", "Pattern", "BS", "QD", "Jobs",
            "Read IOPS", "Write IOPS", "Read BW (MB/s)", "Write BW (MB/s)",
            "Read P99 (µs)", "Write P99 (µs)", "GC Score", "WA Est."]
    _header_row(ws, cols, row=r_start)

    for ri, (job, result) in enumerate(zip(jobs, results), start=r_start + 1):
        if result:
            vals = [
                job.job_name, job.rw, job.bs, job.iodepth, job.numjobs,
                round(result.read_iops, 0), round(result.write_iops, 0),
                _kbps_to_mbps(result.read_bw_kbps), _kbps_to_mbps(result.write_bw_kbps),
                _ns_to_us(result.read_clat_p99_ns), _ns_to_us(result.write_clat_p99_ns),
                round(result.gc_pause_score or 0, 3), round(result.write_amp_est or 1.0, 2),
            ]
        else:
            vals = [job.job_name, job.rw, job.bs, job.iodepth, job.numjobs] + [""] * 8
        _data_row(ws, vals, ri, alt=(ri % 2 == 0))

    _auto_width(ws)


def _sheet_performance(wb: Workbook, direction: str, jobs: list[FIOJob], results: list[FIOResult]):
    ws = wb.create_sheet(title=f"{direction.capitalize()} Perf")
    ws.sheet_view.showGridLines = False
    _write_title(ws, f"{direction.capitalize()} Performance Details")

    cols = ["Job", "Pattern", "BS", "QD",
            "IOPS", "IOPS StdDev", "BW (MB/s)", "BW StdDev (MB/s)",
            "Lat Mean (µs)", "Lat StdDev (µs)", "Lat Min (µs)", "Lat Max (µs)",
            "Total IOs", "Total Bytes (GB)"]
    _header_row(ws, cols, row=2)

    for ri, (job, result) in enumerate(zip(jobs, results), start=3):
        if direction == "read":
            vals = [
                job.job_name, job.rw, job.bs, job.iodepth,
                round(result.read_iops, 0) if result else "",
                round(result.read_iops_stddev, 0) if result else "",
                _kbps_to_mbps(result.read_bw_kbps) if result else "",
                _kbps_to_mbps(result.read_bw_stddev) if result else "",
                _ns_to_us(result.read_lat_mean_ns) if result else "",
                _ns_to_us(result.read_lat_stddev_ns) if result else "",
                _ns_to_us(result.read_lat_min_ns) if result else "",
                _ns_to_us(result.read_lat_max_ns) if result else "",
                result.read_total_ios if result else "",
                round(result.read_total_bytes / 1e9, 3) if result else "",
            ]
        else:
            vals = [
                job.job_name, job.rw, job.bs, job.iodepth,
                round(result.write_iops, 0) if result else "",
                round(result.write_iops_stddev, 0) if result else "",
                _kbps_to_mbps(result.write_bw_kbps) if result else "",
                _kbps_to_mbps(result.write_bw_stddev) if result else "",
                _ns_to_us(result.write_lat_mean_ns) if result else "",
                _ns_to_us(result.write_lat_stddev_ns) if result else "",
                _ns_to_us(result.write_lat_min_ns) if result else "",
                _ns_to_us(result.write_lat_max_ns) if result else "",
                result.write_total_ios if result else "",
                round(result.write_total_bytes / 1e9, 3) if result else "",
            ]
        _data_row(ws, vals, ri, alt=(ri % 2 == 0))

    _auto_width(ws)


def _sheet_latency_percentiles(wb: Workbook, jobs: list[FIOJob], results: list[FIOResult]):
    ws = wb.create_sheet(title="Latency Percentiles")
    ws.sheet_view.showGridLines = False
    _write_title(ws, "Completion Latency Percentiles (µs)")

    pcts = ["P1", "P5", "P10", "P20", "P50", "P90", "P95", "P99", "P99.5", "P99.9", "P99.95", "P99.99"]
    pct_keys = ["1.000000","5.000000","10.000000","20.000000","50.000000","90.000000",
                "95.000000","99.000000","99.500000","99.900000","99.950000","99.990000"]

    for direction in ("Read", "Write"):
        _header_row(ws, ["Job", "Pattern", "BS", "QD", "Dir"] + pcts,
                    row=ws.max_row + 2)
        for job, result in zip(jobs, results):
            if not result:
                continue
            pct_blob = (result.read_percentiles if direction == "Read"
                        else result.write_percentiles)
            vals = [
                job.job_name, job.rw, job.bs, job.iodepth, direction
            ] + [round(float(pct_blob.get(k, 0)) / 1000, 2) for k in pct_keys]
            ri = ws.max_row + 1
            _data_row(ws, vals, ri, alt=(ri % 2 == 0))

    _auto_width(ws)


def _sheet_time_series(wb: Workbook, jobs: list[FIOJob], ts_map: dict[int, list[IOTimeSeries]]):
    ws = wb.create_sheet(title="Time Series")
    ws.sheet_view.showGridLines = False
    _write_title(ws, "Per-Second IO Statistics")

    row = 2
    for job in jobs:
        rows = ts_map.get(job.id, [])
        if not rows:
            continue
        ws.cell(row=row, column=1, value=f"Job: {job.job_name} ({job.rw} bs={job.bs} qd={job.iodepth})")\
          .font = Font(bold=True, color="89B4FA")
        row += 1
        _header_row(ws, ["Time (s)", "Read IOPS", "Write IOPS",
                         "Read BW (MB/s)", "Write BW (MB/s)",
                         "Read Lat (µs)", "Write Lat (µs)"], row=row)
        data_start = row + 1
        for ts in rows:
            row += 1
            _data_row(ws, [
                ts.elapsed_ms / 1000,
                round(ts.iops_read, 0), round(ts.iops_write, 0),
                round(ts.bw_read_kbps / 1024, 2), round(ts.bw_write_kbps / 1024, 2),
                round(ts.lat_read_ns / 1000, 2), round(ts.lat_write_ns / 1000, 2),
            ], row, alt=(row % 2 == 0))

        # Inline line chart for IOPS
        chart = LineChart()
        chart.title = f"IOPS — {job.job_name}"
        chart.style = 10
        chart.height = 12; chart.width = 24
        chart.y_axis.title = "IOPS"
        chart.x_axis.title = "Time (s)"
        cat = Reference(ws, min_col=1, min_row=data_start, max_row=row)
        for ci, label in [(2, "Read IOPS"), (3, "Write IOPS")]:
            data_ref = Reference(ws, min_col=ci, min_row=data_start - 1, max_row=row)
            chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cat)
        ws.add_chart(chart, f"I{data_start}")
        row += 2

    _auto_width(ws)


def _sheet_drive_info(wb: Workbook, snaps: list[DriveSnapshot]):
    ws = wb.create_sheet(title="Drive Info")
    ws.sheet_view.showGridLines = False
    _write_title(ws, "Drive SMART Snapshots")

    cols = ["Phase", "Captured At", "Device",
            "Power-On Hours", "% NAND Used", "Available Spare %",
            "Temp (°C)", "Data Written (units)", "Data Read (units)",
            "Media Errors", "Unsafe Shutdowns"]
    _header_row(ws, cols, row=2)
    for ri, snap in enumerate(snaps, start=3):
        _data_row(ws, [
            snap.phase,
            snap.captured_at.strftime("%Y-%m-%d %H:%M:%S") if snap.captured_at else "",
            snap.device,
            snap.power_on_hours, snap.percentage_used, snap.available_spare_pct,
            snap.temperature_c, snap.data_units_written, snap.data_units_read,
            snap.media_errors, snap.unsafe_shutdowns,
        ], ri, alt=(ri % 2 == 0))
    _auto_width(ws)


def _sheet_system_logs(wb: Workbook, logs: list[SystemLog]):
    ws = wb.create_sheet(title="System Logs")
    ws.sheet_view.showGridLines = False
    _write_title(ws, "Captured System Logs")

    cols = ["Log Type", "Phase", "Captured At", "File Path", "Preview (first 500 chars)"]
    _header_row(ws, cols, row=2)
    for ri, log in enumerate(logs, start=3):
        preview = (log.content or "")[:500].replace("\n", " ↵ ")
        _data_row(ws, [
            log.log_type, log.phase,
            log.captured_at.strftime("%Y-%m-%d %H:%M:%S") if log.captured_at else "",
            log.file_path or "",
            preview,
        ], ri, alt=(ri % 2 == 0))
    _auto_width(ws)


def _sheet_raw(wb: Workbook, jobs: list[FIOJob], results: list[FIOResult]):
    ws = wb.create_sheet(title="Raw FIO JSON")
    ws.sheet_view.showGridLines = False
    _write_title(ws, "Raw FIO JSON Output")
    row = 2
    for job, result in zip(jobs, results):
        if not result:
            continue
        ws.cell(row=row, column=1, value=f"Job: {job.job_name}").font = Font(bold=True, color="89B4FA")
        row += 1
        try:
            pretty = json.dumps(json.loads(result.raw_json), indent=2)
        except Exception:
            pretty = result.raw_json
        for line in pretty.splitlines():
            ws.cell(row=row, column=1, value=line)
            row += 1
        row += 1


# --------------------------------------------------------------------------- #
#  Main export function                                                        #
# --------------------------------------------------------------------------- #

def export_session_to_excel(
    session: TestSession,
    jobs: list[FIOJob],
    results: list[FIOResult],
    ts_map: dict[int, list[IOTimeSeries]],
    system_logs: list[SystemLog],
    drive_snaps: list[DriveSnapshot],
) -> Path:
    wb = Workbook()

    _sheet_summary(wb, session, jobs, results)
    _sheet_performance(wb, "read",  jobs, results)
    _sheet_performance(wb, "write", jobs, results)
    _sheet_latency_percentiles(wb, jobs, results)
    _sheet_time_series(wb, jobs, ts_map)
    _sheet_drive_info(wb, drive_snaps)
    _sheet_system_logs(wb, system_logs)
    _sheet_raw(wb, jobs, results)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = EXPORTS_DIR / f"session_{session.id}_{ts}.xlsx"
    wb.save(out_path)
    return out_path
