"""Async flow execution engine with WebSocket log streaming."""
from __future__ import annotations
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .models import (
    BlktraceConfig, CommandStepConfig, CustomCommandConfig, DmesgConfig,
    FioStepConfig, FlowEdge, FlowStep, IostatConfig, LogCollectStepConfig,
    PerfRecordConfig, PerfStatConfig, RunRecord, StepStatus, WsMessage,
)
from .fio_config import render_fio_file


# ─────────────────────────── Broadcast helper ─────────────────────────────

Broadcaster = Callable[[WsMessage], None]


def _msg(type_: str, **kwargs) -> WsMessage:
    return WsMessage(type=type_, **kwargs)


# ─────────────────────────── Execution order ──────────────────────────────

def topological_order(steps: List[FlowStep], edges: List[FlowEdge]) -> List[List[str]]:
    """
    Return steps grouped into sequential waves (parallel within a wave).
    Waves are determined by topological sort of the edge graph.
    Steps with no edges at all are treated as a single sequential chain
    in the order they appear in `steps`.
    """
    if not edges:
        # No edges: run in list order, one per wave
        return [[s.id] for s in steps]

    predecessors: Dict[str, Set[str]] = {s.id: set() for s in steps}
    for e in edges:
        if e.target in predecessors:
            predecessors[e.target].add(e.source)

    completed: Set[str] = set()
    waves: List[List[str]] = []
    remaining = set(s.id for s in steps)

    while remaining:
        wave = [sid for sid in remaining if predecessors[sid] <= completed]
        if not wave:
            # Cycle or disconnected — append remaining in original order
            order = [s.id for s in steps if s.id in remaining]
            waves.append(order)
            break
        waves.append(sorted(wave, key=lambda sid: next(
            (i for i, s in enumerate(steps) if s.id == sid), 0)))
        completed.update(wave)
        remaining -= set(wave)

    return waves


# ──────────────────────────── subprocess helpers ───────────────────────────

async def _stream_process(
    cmd: List[str],
    log_path: str,
    broadcast: Optional[Broadcaster],
    step_id: str,
    env: Optional[Dict] = None,
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> int:
    """Run a subprocess, tee stdout+stderr to log_path, broadcast lines."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    proc_env = {**os.environ, **(env or {})}

    async def _read_stream(stream: asyncio.StreamReader, sink):
        async for raw in stream:
            line = raw.decode(errors="replace").rstrip()
            sink.write(raw)
            if broadcast:
                broadcast(_msg("log", step_id=step_id, data=line))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=proc_env,
        cwd=cwd,
    )

    with open(log_path, "wb") as fout:
        reader_task = asyncio.create_task(_read_stream(proc.stdout, fout))
        try:
            if timeout:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            else:
                await proc.wait()
        except asyncio.TimeoutError:
            proc.terminate()
            await asyncio.sleep(1)
            proc.kill()
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass

    return proc.returncode or 0


# ──────────────────────────── Step runners ────────────────────────────────

async def run_fio_step(
    step: FlowStep,
    cfg: FioStepConfig,
    log_dir: str,
    broadcast: Optional[Broadcaster],
) -> int:
    os.makedirs(log_dir, exist_ok=True)

    # Write .fio job file
    fio_content = render_fio_file(cfg, log_dir, step.name)
    fio_path = os.path.join(log_dir, f"{step.name}.fio")
    with open(fio_path, "w") as f:
        f.write(fio_content)

    if broadcast:
        broadcast(_msg("log", step_id=step.id,
                       data=f"[fio] job file → {fio_path}"))
        broadcast(_msg("log", step_id=step.id,
                       data=f"--- .fio content ---\n{fio_content}---"))

    # Run fio, capture JSON output separately
    json_out = os.path.join(log_dir, "fio_output.json")
    txt_out  = os.path.join(log_dir, "fio_output.txt")

    cmd = ["fio", fio_path, f"--output={json_out}", "--output-format=json"]

    rc = await _stream_process(
        cmd,
        log_path=txt_out,
        broadcast=broadcast,
        step_id=step.id,
    )
    return rc


async def run_iostat(
    cfg: IostatConfig,
    log_dir: str,
    step_id: str,
    broadcast: Optional[Broadcaster],
    stop_event: asyncio.Event,
) -> None:
    os.makedirs(log_dir, exist_ok=True)
    cmd = ["iostat", "-xdt", str(cfg.interval)]
    if cfg.devices:
        cmd += cfg.devices
    if cfg.count is not None:
        cmd += [str(cfg.count)]

    log_path = os.path.join(log_dir, "iostat.log")
    proc_env = os.environ.copy()

    async def _run():
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=proc_env,
        )
        with open(log_path, "wb") as fout:
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                fout.write(raw)
                if broadcast:
                    broadcast(_msg("log", step_id=step_id,
                                   data=f"[iostat] {line}"))
                if stop_event.is_set():
                    proc.terminate()
                    break
            await proc.wait()

    await _run()


async def _dmesg_snapshot(log_dir: str, label: str, step_id: str,
                           broadcast: Optional[Broadcaster]) -> None:
    path = os.path.join(log_dir, f"dmesg_{label}.log")
    cmd = ["dmesg", "--time-format=iso"]
    await _stream_process(cmd, log_path=path, broadcast=broadcast,
                          step_id=step_id, timeout=10)


async def run_log_collect_step(
    step: FlowStep,
    cfg: LogCollectStepConfig,
    log_dir: str,
    broadcast: Optional[Broadcaster],
) -> int:
    os.makedirs(log_dir, exist_ok=True)
    stop_events: List[asyncio.Event] = []
    tasks: List[asyncio.Task] = []

    for idx, collector in enumerate(cfg.collectors):
        t = collector.type
        stop = asyncio.Event()
        stop_events.append(stop)

        if t == "dmesg":
            task = asyncio.create_task(
                _dmesg_snapshot(log_dir, f"{idx}", step.id, broadcast))
        elif t == "iostat":
            task = asyncio.create_task(
                run_iostat(collector, log_dir, step.id, broadcast, stop))
        elif t == "blktrace":
            log_path = os.path.join(log_dir, f"blktrace_{idx}.log")
            devs = " ".join(f"-d {d}" for d in collector.devices)
            cmd = f"blktrace {devs} -o {log_dir}/blktrace_{idx}"
            shell_cmd = ["bash", "-c", cmd]
            task = asyncio.create_task(
                _stream_process(shell_cmd, log_path, broadcast, step.id,
                                timeout=collector.duration))
        elif t == "perf_stat":
            evts = ",".join(collector.events)
            cmd = ["perf", "stat", f"-e{evts}"]
            if collector.pid:
                cmd += ["-p", str(collector.pid)]
            log_path = os.path.join(log_dir, f"perf_stat_{idx}.log")
            task = asyncio.create_task(
                _stream_process(cmd, log_path, broadcast, step.id,
                                timeout=collector.duration))
        elif t == "perf_record":
            evts = ",".join(collector.events)
            out = os.path.join(log_dir, f"perf_{idx}.data")
            cmd = ["perf", "record", f"-e{evts}", f"-F{collector.frequency}",
                   "-a", "-o", out]
            log_path = os.path.join(log_dir, f"perf_record_{idx}.log")
            task = asyncio.create_task(
                _stream_process(cmd, log_path, broadcast, step.id,
                                timeout=collector.duration))
        elif t == "custom":
            safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", collector.label)
            log_path = os.path.join(log_dir, f"cmd_{idx}_{safe_label}.log")
            cmd_list = ["bash", "-c", collector.command]
            task = asyncio.create_task(
                _stream_process(cmd_list, log_path, broadcast, step.id,
                                env=collector.env, timeout=collector.timeout))
        else:
            continue

        tasks.append(task)

    if cfg.duration is not None:
        await asyncio.sleep(cfg.duration)
        for ev in stop_events:
            ev.set()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    return 0


async def run_command_step(
    step: FlowStep,
    cfg: CommandStepConfig,
    log_dir: str,
    broadcast: Optional[Broadcaster],
) -> int:
    os.makedirs(log_dir, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", cfg.label)
    log_path = os.path.join(log_dir, f"{safe_label}.log")
    rc = await _stream_process(
        ["bash", "-c", cfg.command],
        log_path=log_path,
        broadcast=broadcast,
        step_id=step.id,
        env=cfg.env,
        cwd=cfg.working_dir,
        timeout=cfg.timeout,
    )
    if cfg.fail_on_error and rc != 0:
        return rc
    return 0


# ─────────────────────────── Main flow runner ─────────────────────────────

async def execute_flow(
    run: RunRecord,
    steps: List[FlowStep],
    edges: List[FlowEdge],
    broadcast: Optional[Broadcaster] = None,
) -> RunRecord:
    base_dir = os.path.join(run.output_dir, run.id)
    os.makedirs(base_dir, exist_ok=True)

    # Save run metadata
    meta_path = os.path.join(base_dir, "run_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(run.model_dump(mode="json"), f, indent=2, default=str)

    step_map = {s.id: s for s in steps}
    waves = topological_order(steps, edges)
    step_statuses: Dict[str, StepStatus] = {s.id: s for s in run.steps}

    global_idx = 0  # sequential counter across all waves for dir naming

    for wave in waves:
        wave_tasks = []

        async def _run_step(sid: str, idx: int):
            step = step_map[sid]
            st = step_statuses[sid]
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", step.name)
            log_dir = os.path.join(base_dir, f"{idx:03d}_{step.type}_{safe_name}")
            st.log_dir = log_dir
            st.status = "running"
            st.started_at = datetime.utcnow()

            if broadcast:
                broadcast(_msg("step_start", step_id=sid, step_name=step.name,
                               data={"log_dir": log_dir}))

            try:
                if step.type == "fio":
                    rc = await run_fio_step(step, step.config, log_dir, broadcast)
                elif step.type == "log_collect":
                    rc = await run_log_collect_step(step, step.config, log_dir, broadcast)
                elif step.type == "command":
                    rc = await run_command_step(step, step.config, log_dir, broadcast)
                else:
                    rc = 0

                st.exit_code = rc
                st.status = "done" if rc == 0 else "error"
            except Exception as exc:
                st.status = "error"
                st.error = str(exc)
                if broadcast:
                    broadcast(_msg("error", step_id=sid, data=str(exc)))

            st.finished_at = datetime.utcnow()

            # Write step metadata
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "metadata.json"), "w") as f:
                json.dump(st.model_dump(mode="json"), f, indent=2, default=str)

            if broadcast:
                broadcast(_msg("step_done", step_id=sid, step_name=step.name,
                               data=st.model_dump(mode="json")))

        # Assign monotonically increasing indices to all steps in this wave
        for sid in wave:
            wave_tasks.append(_run_step(sid, global_idx))
            global_idx += 1

        await asyncio.gather(*wave_tasks)

        # Abort if any step in the wave errored
        for sid in wave:
            if step_statuses[sid].status == "error":
                run.status = "error"
                run.finished_at = datetime.utcnow()
                if broadcast:
                    broadcast(_msg("run_done", data=run.model_dump(mode="json")))
                # Update metadata
                with open(meta_path, "w") as f:
                    json.dump(run.model_dump(mode="json"), f, indent=2, default=str)
                return run

    run.status = "done"
    run.finished_at = datetime.utcnow()
    # Update step list in run record
    run.steps = list(step_statuses.values())
    with open(meta_path, "w") as f:
        json.dump(run.model_dump(mode="json"), f, indent=2, default=str)

    if broadcast:
        broadcast(_msg("run_done", data=run.model_dump(mode="json")))

    return run
