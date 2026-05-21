"""
Executes a Workflow step by step, writing structured logs to disk.

Output layout:
    {run_dir}/
    ├── 00_run_metadata.json
    ├── 00_workflow.yaml
    ├── 001_<step_name>/
    │   ├── meta.json          # timing, exit_code, step type
    │   ├── fio_job.ini        # (FIO steps only)
    │   ├── fio_out.json       # FIO JSON output
    │   ├── fio_out.txt        # FIO human-readable output
    │   └── <label>.txt        # (command steps, one file per command)
    └── summary/
        ├── all_fio_results.json
        ├── report.txt
        └── report.html
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .generator import generate_fio_job_file
from .parser import parse_fio_json
from .reporter import build_html_report, build_text_report, build_summary_json
from .workflow import Workflow, WorkflowStep


class StepError(Exception):
    pass


class WorkflowExecutor:
    def __init__(
        self,
        workflow: Workflow,
        on_status: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
    ):
        self.workflow = workflow
        self.on_status = on_status or (lambda msg: print(msg))
        self.dry_run = dry_run
        self.run_dir: Optional[Path] = None
        self.fio_analyses: List[dict] = []

    def _log(self, msg: str) -> None:
        self.on_status(msg)

    def _run_dir_for(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(self.workflow.output_dir).expanduser()
        return base / f"{self.workflow.name}_{ts}"

    def execute(self) -> Path:
        run_dir = self._run_dir_for()
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save workflow copy
        (run_dir / "00_workflow.yaml").write_text(self.workflow.to_yaml())

        start_ts = datetime.now(timezone.utc).isoformat()
        self._log(f"[run] Starting '{self.workflow.name}' → {run_dir}")

        metadata = {
            "workflow_name": self.workflow.name,
            "description": self.workflow.description,
            "start_time": start_ts,
            "output_dir": str(run_dir),
            "dry_run": self.dry_run,
            "steps": [],
        }

        enabled = self.workflow.enabled_steps()
        self.fio_analyses = []

        for idx, step in enumerate(enabled, start=1):
            step_prefix = f"{idx:03d}_{step.name}"
            step_dir = run_dir / step_prefix
            step_dir.mkdir(parents=True, exist_ok=True)

            self._log(f"\n[step {idx}/{len(enabled)}] {step.type.upper()} — {step.name}")
            if step.description:
                self._log(f"  {step.description}")

            step_meta = self._execute_step(step, step_dir, idx)
            metadata["steps"].append(step_meta)

        metadata["end_time"] = datetime.now(timezone.utc).isoformat()
        metadata["total_steps"] = len(enabled)
        (run_dir / "00_run_metadata.json").write_text(json.dumps(metadata, indent=2))

        # Build summary
        summary_dir = run_dir / "summary"
        summary_dir.mkdir(exist_ok=True)
        self._build_summary(summary_dir)

        self._log(f"\n[done] Results in {run_dir}")
        return run_dir

    def _execute_step(self, step: WorkflowStep, step_dir: Path, idx: int) -> dict:
        t_start = time.monotonic()
        wall_start = datetime.now(timezone.utc).isoformat()
        exit_code = 0

        try:
            if step.type == "fio":
                analysis = self._run_fio_step(step, step_dir)
                if analysis:
                    analysis["step_index"] = idx
                    analysis["step_name"] = step.name
                    self.fio_analyses.append(analysis)
                    (step_dir / "fio_analysis.json").write_text(json.dumps(analysis, indent=2))
                    self._log(f"  read_iops={analysis['summary'].get('total_read_iops', 0):.0f}  "
                              f"write_iops={analysis['summary'].get('total_write_iops', 0):.0f}  "
                              f"read_bw={analysis['summary'].get('total_read_bw_MiB_s', 0):.1f} MiB/s  "
                              f"write_bw={analysis['summary'].get('total_write_bw_MiB_s', 0):.1f} MiB/s")
            elif step.type == "command":
                exit_code = self._run_command_step(step, step_dir)
        except Exception as exc:
            exit_code = 1
            self._log(f"  [ERROR] {exc}")

        duration_ms = int((time.monotonic() - t_start) * 1000)
        meta = {
            "step_index": idx,
            "name": step.name,
            "type": step.type,
            "description": step.description,
            "start_time": wall_start,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
        }
        (step_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        self._log(f"  finished in {duration_ms/1000:.1f}s (exit={exit_code})")
        return meta

    def _run_fio_step(self, step: WorkflowStep, step_dir: Path) -> Optional[dict]:
        job_file = step_dir / "fio_job.ini"
        generate_fio_job_file(step, self.workflow.global_fio, job_file)

        json_out = step_dir / "fio_out.json"
        txt_out = step_dir / "fio_out.txt"

        cmd_json = ["fio", "--output-format=json", f"--output={json_out}", str(job_file)]
        cmd_txt = ["fio", str(job_file)]

        if self.dry_run:
            self._log(f"  [dry-run] {' '.join(cmd_json)}")
            return None

        # Run for JSON output (primary)
        self._log(f"  running: fio {job_file.name} ...")
        result_json = subprocess.run(
            cmd_json, capture_output=True, text=True
        )

        # Also capture human-readable output
        result_txt = subprocess.run(
            cmd_txt, capture_output=True, text=True
        )
        txt_out.write_text(result_txt.stdout + result_txt.stderr)

        if result_json.returncode != 0 and not json_out.exists():
            self._log(f"  [warn] fio exited {result_json.returncode}")
            (step_dir / "fio_stderr.txt").write_text(result_json.stderr)
            return None

        if json_out.exists():
            try:
                return parse_fio_json(json_out)
            except Exception as e:
                self._log(f"  [warn] parse failed: {e}")
        return None

    def _run_command_step(self, step: WorkflowStep, step_dir: Path) -> int:
        last_exit = 0
        for cmd_entry in step.commands:
            out_file = step_dir / f"{cmd_entry.label}.txt"
            actual_cmd = cmd_entry.cmd
            if cmd_entry.sudo and os.geteuid() != 0:
                actual_cmd = "sudo " + actual_cmd

            self._log(f"  cmd [{cmd_entry.label}]: {cmd_entry.cmd}")

            if self.dry_run:
                out_file.write_text(f"[dry-run] {actual_cmd}\n")
                continue

            try:
                result = subprocess.run(
                    actual_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=cmd_entry.timeout,
                )
                out_file.write_text(result.stdout + result.stderr)
                last_exit = result.returncode
                if result.returncode != 0 and not cmd_entry.ignore_errors:
                    self._log(f"  [warn] exit={result.returncode}")
            except subprocess.TimeoutExpired:
                out_file.write_text(f"[timeout after {cmd_entry.timeout}s]\n")
                last_exit = 124

        return last_exit

    def _build_summary(self, summary_dir: Path) -> None:
        if self.fio_analyses:
            (summary_dir / "all_fio_results.json").write_text(
                json.dumps(self.fio_analyses, indent=2)
            )
            summary = build_summary_json(self.fio_analyses)
            (summary_dir / "comparison.json").write_text(json.dumps(summary, indent=2))
            (summary_dir / "report.txt").write_text(build_text_report(self.fio_analyses))
            (summary_dir / "report.html").write_text(
                build_html_report(self.workflow, self.fio_analyses)
            )
            self._log(f"\n[summary] HTML report → {summary_dir / 'report.html'}")
        else:
            self._log("[summary] No FIO results to summarize")
