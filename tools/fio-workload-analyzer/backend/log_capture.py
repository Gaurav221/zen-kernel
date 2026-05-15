"""
System log capture — runs before and after each test.

The user will extend LOG_CAPTURE_COMMANDS in config.py with device-specific
commands (e.g. nvme smart-log, nvme log, vendor CLIs).

Each capture function saves a timestamped file and returns the raw text.
"""
import asyncio
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import LOGS_DIR
from .database import DriveSnapshot, SystemLog


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

async def _run_cmd(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command asynchronously and return (returncode, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return -1, f"[timeout after {timeout}s]"
        return proc.returncode, out.decode(errors="replace")
    except FileNotFoundError:
        return -1, f"[command not found: {cmd[0]}]"
    except PermissionError as e:
        return -1, f"[permission error: {e}]"


def _save(content: str, session_id: int, job_id: Optional[int], log_type: str, phase: str) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = f"session_{session_id}"
    if job_id is not None:
        name += f"_job_{job_id}"
    name += f"_{log_type}_{phase}_{ts}.txt"
    path = LOGS_DIR / name
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
#  Specific capture routines                                                   #
# --------------------------------------------------------------------------- #

async def capture_dmesg(session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    rc, text = await _run_cmd(["dmesg", "--time-format=iso", "-T"])
    path = _save(text, session_id, job_id, "dmesg", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="dmesg",
        phase=phase,
        content=text,
        file_path=str(path),
    )


async def capture_journal_kernel(session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    rc, text = await _run_cmd(
        ["journalctl", "-k", "--no-pager", "-n", "5000", "--output=short-iso"]
    )
    path = _save(text, session_id, job_id, "journal_kernel", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="journal_kernel",
        phase=phase,
        content=text,
        file_path=str(path),
    )


async def capture_blkstat(device: str, session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    dev_base = Path(device).name
    rc, text = await _run_cmd(["cat", f"/sys/block/{dev_base}/stat"])
    path = _save(text, session_id, job_id, "blkstat", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="blkstat",
        phase=phase,
        content=text,
        file_path=str(path),
    )


async def capture_nvme_smart(device: str, session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    rc, text = await _run_cmd(["nvme", "smart-log", device, "-o", "json"])
    path = _save(text, session_id, job_id, "nvme_smart", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="nvme_smart",
        phase=phase,
        content=text,
        file_path=str(path),
    )


async def capture_nvme_log(device: str, session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    """Capture NVMe error log (log page 1)."""
    rc, text = await _run_cmd(["nvme", "error-log", device, "-o", "json"])
    path = _save(text, session_id, job_id, "nvme_error_log", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="nvme_error_log",
        phase=phase,
        content=text,
        file_path=str(path),
    )


async def capture_nvme_telemetry(device: str, session_id: int, job_id: Optional[int], phase: str) -> list[SystemLog]:
    """Capture NVMe host + controller telemetry (vendor-specific pages)."""
    logs = []
    for page_id, name in [(7, "host_telemetry"), (8, "ctrl_telemetry")]:
        rc, text = await _run_cmd(
            ["nvme", "get-log", device, f"--log-id={page_id}", "-o", "json"]
        )
        path = _save(text, session_id, job_id, name, phase)
        logs.append(SystemLog(
            session_id=session_id,
            job_id=job_id,
            log_type=name,
            phase=phase,
            content=text,
            file_path=str(path),
        ))
    return logs


async def capture_iostat(device: str, session_id: int, job_id: Optional[int], phase: str) -> SystemLog:
    rc, text = await _run_cmd(["iostat", "-xdz", "1", "3", device])
    path = _save(text, session_id, job_id, "iostat", phase)
    return SystemLog(
        session_id=session_id,
        job_id=job_id,
        log_type="iostat",
        phase=phase,
        content=text,
        file_path=str(path),
    )


# --------------------------------------------------------------------------- #
#  Drive snapshot (SMART → DriveSnapshot ORM)                                 #
# --------------------------------------------------------------------------- #

def _parse_nvme_smart_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


async def capture_drive_snapshot(
    device: str, session_id: int, phase: str
) -> DriveSnapshot:
    _, smart_text = await _run_cmd(["nvme", "smart-log", device, "-o", "json"])
    _, errlog_text = await _run_cmd(["nvme", "error-log", device, "-o", "json"])

    smart = _parse_nvme_smart_json(smart_text)

    snap = DriveSnapshot(
        session_id=session_id,
        phase=phase,
        device=device,
        smart_json=smart_text,
        nvme_log_json=errlog_text,
    )

    # Map well-known NVMe SMART fields
    snap.power_on_hours       = smart.get("power_on_hours")
    snap.unsafe_shutdowns     = smart.get("unsafe_shutdowns")
    snap.media_errors         = smart.get("media_errors")
    snap.data_units_written   = smart.get("data_units_written")
    snap.data_units_read      = smart.get("data_units_read")
    snap.available_spare_pct  = smart.get("avail_spare")
    snap.percentage_used      = smart.get("percent_used")

    temp_composite = smart.get("temperature", None)
    if temp_composite is not None:
        snap.temperature_c = temp_composite - 273  # Kelvin → Celsius

    return snap


# --------------------------------------------------------------------------- #
#  High-level: capture all logs for a session/job phase                       #
# --------------------------------------------------------------------------- #

async def capture_all(
    session_id: int,
    job_id: Optional[int],
    phase: str,
    device: Optional[str] = None,
) -> list[SystemLog]:
    """Run all standard captures; device-specific ones if device is given."""
    tasks = [
        capture_dmesg(session_id, job_id, phase),
        capture_journal_kernel(session_id, job_id, phase),
    ]
    if device:
        tasks += [
            capture_blkstat(device, session_id, job_id, phase),
            capture_nvme_smart(device, session_id, job_id, phase),
            capture_nvme_log(device, session_id, job_id, phase),
            capture_iostat(device, session_id, job_id, phase),
        ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    logs: list[SystemLog] = []
    for r in results:
        if isinstance(r, list):
            logs.extend(r)
        elif isinstance(r, SystemLog):
            logs.append(r)
        # silently skip exceptions — capture is best-effort

    return logs


# --------------------------------------------------------------------------- #
#  Log diff helper                                                             #
# --------------------------------------------------------------------------- #

def diff_logs(before: str, after: str) -> str:
    """Return lines that appear in 'after' but not in 'before' (new entries)."""
    before_lines = set(before.splitlines())
    new_lines = [l for l in after.splitlines() if l not in before_lines]
    return "\n".join(new_lines)


# --------------------------------------------------------------------------- #
#  Drive discovery                                                             #
# --------------------------------------------------------------------------- #

def list_nvme_devices() -> list[dict]:
    """Return list of NVMe devices visible to the OS."""
    try:
        result = subprocess.run(
            ["nvme", "list", "-o", "json"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        devices = data.get("Devices", [])
        return [
            {
                "device": d.get("DevicePath", ""),
                "model": d.get("ModelNumber", "").strip(),
                "serial": d.get("SerialNumber", "").strip(),
                "firmware": d.get("Firmware", "").strip(),
                "capacity_gb": round(d.get("PhysicalSize", 0) / 1e9, 1),
            }
            for d in devices
        ]
    except Exception:
        return []


def list_block_devices() -> list[dict]:
    """Return block devices from lsblk."""
    try:
        result = subprocess.run(
            ["lsblk", "-d", "-o", "NAME,SIZE,MODEL,SERIAL,TYPE", "--json"],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        devs = []
        for d in data.get("blockdevices", []):
            if d.get("type") in ("disk", "nvme"):
                devs.append({
                    "device": f"/dev/{d['name']}",
                    "model": (d.get("model") or "").strip(),
                    "serial": (d.get("serial") or "").strip(),
                    "size": d.get("size", ""),
                })
        return devs
    except Exception:
        return []
